from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from ..config import ConfigError, RelayConfig, SourceConfig, load_config
from .ffmpeg import build_ffmpeg_command, prepare_file_destinations, redact_command, redact_text

PREVIEW_FILE_NAME = "preview.jpg"
LOG_DIR_NAME = "logs"
RELAY_LOG_FILE_NAME = "relay.log"
NGINX_ERROR_LOG_FILE_NAME = "nginx-error.log"
NGINX_RTMP_ACCESS_LOG_FILE_NAME = "nginx-rtmp-access.log"
RECENT_LOG_LINES = 40
BITRATE_SAMPLE_LIMIT = 90
BITRATE_HISTORY_SECONDS = 30
BITRATE_SAMPLE_INTERVAL_SECONDS = 1.0
BITRATE_PATTERN = re.compile(r"bitrate=\s*([0-9.]+)\s*([kKmM])?bits/s")
INPUT_STREAM_BITRATE_PATTERN = re.compile(
    r"^\s*Stream #0:(?P<stream>\d+).*?: .*?, (?P<bitrate>[0-9.]+) kb/s"
)
PUBLISH_FANOUT_DELAY_SECONDS = 0.25
FANOUT_START_ATTEMPTS = 6
FANOUT_RETRY_DELAY_SECONDS = 0.5
FANOUT_INPUT_GRACE_SECONDS = 3.0
FANOUT_INPUT_POLL_SECONDS = 0.1


class RelayController:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.preview_path = config_path.parent / "preview" / PREVIEW_FILE_NAME
        self.log_path = config_path.parent / LOG_DIR_NAME / RELAY_LOG_FILE_NAME
        self.nginx_error_log_path = config_path.parent / LOG_DIR_NAME / NGINX_ERROR_LOG_FILE_NAME
        self.nginx_rtmp_access_log_path = (
            config_path.parent / LOG_DIR_NAME / NGINX_RTMP_ACCESS_LOG_FILE_NAME
        )
        self.process: subprocess.Popen[bytes] | None = None
        self.watch_thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.stream_incoming = False
        self.active_source_id: str | None = None
        self.active_stream_name: str | None = None
        self.active_since: str | None = None
        self.current_bitrate_kbps = 0.0
        self.bitrate_samples: deque[dict[str, float]] = deque(maxlen=BITRATE_SAMPLE_LIMIT)
        self.input_stream_bitrates: dict[str, float] = {}
        self.recent_log_lines: deque[str] = deque(maxlen=RECENT_LOG_LINES)
        self.log_lock = threading.Lock()
        self.state_lock = threading.Lock()
        self._last_command: list[str] = []

    def status(self) -> dict[str, Any]:
        running = self.process is not None and self.process.poll() is None
        if self.process is not None and not running:
            code = self.process.returncode
            self._close_process_pipes(self.process)
            self.process = None
            with self.state_lock:
                self.stream_incoming = False
                self.active_source_id = None
                self.active_stream_name = None
                self.active_since = None
                self.current_bitrate_kbps = 0.0
                self.input_stream_bitrates.clear()
            if code:
                self.last_error = f"Relay exited with code {code}. See relay log: {self.log_path}"

        self._refresh_bitrate_sample()
        telemetry = self._telemetry()
        payload = {
            "running": running,
            "pid": self.process.pid if running and self.process is not None else None,
            "lastError": self.last_error,
            "streamIncoming": self.stream_incoming,
            "sourcePublishing": self.active_source_id is not None,
            "ready": True,
            "state": self._state(running),
            "previewUrl": self.preview_url if self.stream_incoming else None,
            "relayLogPath": str(self.log_path),
            "nginxErrorLogPath": str(self.nginx_error_log_path),
            "nginxRtmpAccessLogPath": str(self.nginx_rtmp_access_log_path),
            "recentRelayLog": self._recent_log_lines(),
            "telemetry": telemetry,
        }
        try:
            config = load_config(
                self.config_path,
                require_ready=False,
                expand_environment=False,
            )
            enabled = config.enabled_pipelines
            source = None
            if enabled:
                source = config.source_by_id(enabled[0].source_id)
            else:
                enabled_sources = [item for item in config.sources if item.enabled]
                if len(enabled_sources) == 1:
                    source = enabled_sources[0]
            if source is not None:
                payload["source"] = {
                    "id": source.id,
                    "name": source.name,
                    "publicUrl": source.public_url,
                    "stream": source.stream,
                    "live": self.active_source_id == source.id,
                    "bitrateKbps": telemetry["source"]["bitrateKbps"],
                    "bitrateHistory": telemetry["source"]["history"],
                }
            payload["pipelines"] = [
                self._pipeline_status(pipeline, telemetry) for pipeline in config.pipelines
            ]
        except ConfigError as exc:
            payload["configError"] = str(exc)
            payload["ready"] = False
            payload["state"] = "config_error"
        return payload

    def start(self) -> dict[str, Any]:
        if self.status()["running"]:
            return self.status()

        config = load_config(self.config_path)
        source = self._active_source(config)
        self._start_process(config, source=source, input_url=None, listen=True)
        return {**self.status(), "command": self._last_command}

    def publish(self, *, app: str, stream: str) -> dict[str, Any]:
        config = load_config(self.config_path)
        source = self._active_source(config)
        self._append_log_line(f"RTMP publish callback received for app={app} stream=***")
        if app != source.app or stream != source.stream:
            self._append_log_line("RTMP publish rejected: app or stream key did not match config.")
            raise ConfigError("RTMP publish path or stream key is invalid.")

        with self.state_lock:
            active_source_id = self.active_source_id
            active_stream_name = self.active_stream_name
        if active_source_id is not None:
            if active_source_id == source.id and active_stream_name == stream:
                return self.status()
            raise ConfigError("Another source is already live.")

        if self.process is not None and self.process.poll() is None:
            if self.active_source_id == source.id and self.active_stream_name == stream:
                return self.status()
            raise ConfigError("Another source is already live.")

        input_url = f"rtmp://127.0.0.1:{source.port}/{source.app}/{source.stream}"
        self._mark_source_publishing(source)
        self._append_log_line("RTMP publish accepted; scheduling fanout worker startup.")
        threading.Thread(
            target=self._start_process_after_publish,
            args=(config, source, input_url, stream),
            daemon=True,
        ).start()
        return self.status()

    def publish_done(self, *, app: str, stream: str) -> dict[str, Any]:
        self._append_log_line(f"RTMP publish_done callback received for app={app} stream=***")
        with self.state_lock:
            matches_active_stream = self.active_stream_name == stream
        if matches_active_stream:
            return self.stop()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self._terminate_process(clear_session=False)
        with self.state_lock:
            self.stream_incoming = False
            self.active_source_id = None
            self.active_stream_name = None
            self.active_since = None
            self.current_bitrate_kbps = 0.0
        self._clear_preview()
        return self.status()

    @property
    def preview_url(self) -> str:
        version = int(self.preview_path.stat().st_mtime) if self.preview_path.exists() else 0
        return f"/preview/{PREVIEW_FILE_NAME}?v={version}"

    def _start_process(
        self,
        config: RelayConfig,
        *,
        source: SourceConfig,
        input_url: str | None,
        listen: bool,
    ) -> None:
        prepare_file_destinations(config)
        self._prepare_preview()
        command = build_ffmpeg_command(
            config,
            preview_path=self.preview_path,
            input_url=input_url,
            listen=listen,
        )
        redacted_command = redact_command(command)
        self._prepare_log(redacted_command)
        self.process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
        )
        self.watch_thread = threading.Thread(target=self._watch_process_output, daemon=True)
        self.watch_thread.start()
        self.last_error = None
        self._last_command = redacted_command
        with self.state_lock:
            self.stream_incoming = False
            self.active_source_id = source.id
            self.active_stream_name = source.stream
            self.active_since = datetime.now(UTC).isoformat(timespec="seconds")
            self.current_bitrate_kbps = 0.0
            self.bitrate_samples.clear()
            self.input_stream_bitrates.clear()

    def _mark_source_publishing(self, source: SourceConfig) -> None:
        self.last_error = None
        self._prepare_preview()
        with self.state_lock:
            self.stream_incoming = False
            self.active_source_id = source.id
            self.active_stream_name = source.stream
            self.active_since = datetime.now(UTC).isoformat(timespec="seconds")
            self.current_bitrate_kbps = 0.0
            self.bitrate_samples.clear()
            self.input_stream_bitrates.clear()

    def _start_process_after_publish(
        self,
        config: RelayConfig,
        source: SourceConfig,
        input_url: str,
        stream: str,
    ) -> None:
        time.sleep(PUBLISH_FANOUT_DELAY_SECONDS)
        with self.state_lock:
            still_active = self.active_source_id == source.id and self.active_stream_name == stream
        if not still_active:
            return
        if self.process is not None and self.process.poll() is None:
            return
        for attempt in range(1, FANOUT_START_ATTEMPTS + 1):
            with self.state_lock:
                still_active = (
                    self.active_source_id == source.id and self.active_stream_name == stream
                )
            if not still_active:
                return

            try:
                self._append_log_line(f"Starting fanout worker attempt {attempt}.")
                self._start_process(config, source=source, input_url=input_url, listen=False)
            except ConfigError as exc:
                self.last_error = str(exc)
                return
            except OSError as exc:
                self.last_error = f"Could not start FFmpeg: {exc}"
            else:
                process = self.process
                if process is not None and self._wait_for_fanout_input(process, source, stream):
                    self.last_error = None
                    return
                self._append_log_line(
                    f"Fanout worker did not receive input on attempt {attempt}; retrying."
                )
                self._terminate_process(clear_session=False)

            if attempt < FANOUT_START_ATTEMPTS:
                time.sleep(FANOUT_RETRY_DELAY_SECONDS)

        self.last_error = "Fanout worker could not read the active source stream."
        self._append_log_line(self.last_error)

    def _wait_for_fanout_input(
        self,
        process: subprocess.Popen[bytes],
        source: SourceConfig,
        stream: str,
    ) -> bool:
        deadline = time.monotonic() + FANOUT_INPUT_GRACE_SECONDS
        while time.monotonic() < deadline:
            with self.state_lock:
                still_active = self.active_source_id == source.id and self.active_stream_name == stream
                stream_incoming = self.stream_incoming
            if not still_active:
                return True
            if stream_incoming:
                return True
            if process.poll() is not None:
                return False
            time.sleep(FANOUT_INPUT_POLL_SECONDS)

        with self.state_lock:
            return self.stream_incoming

    def _terminate_process(self, *, clear_session: bool) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
            if self.watch_thread is not None:
                self.watch_thread.join(timeout=1)
            self._close_process_pipes(self.process)
        elif self.process is not None:
            self._close_process_pipes(self.process)

        self.process = None
        self.watch_thread = None
        if clear_session:
            with self.state_lock:
                self.stream_incoming = False
                self.active_source_id = None
                self.active_stream_name = None
                self.active_since = None
                self.current_bitrate_kbps = 0.0
                self.input_stream_bitrates.clear()

    def _close_process_pipes(self, process: subprocess.Popen[bytes]) -> None:
        if process.stderr is not None and not process.stderr.closed:
            process.stderr.close()

    def _watch_process_output(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        pending = ""
        try:
            while True:
                chunk = process.stderr.read(1)
                if not chunk:
                    break
                char = chunk.decode("utf-8", errors="replace")
                if char in {"\r", "\n"}:
                    self._handle_process_output_line(pending)
                    pending = ""
                else:
                    pending += char
            if pending:
                self._handle_process_output_line(pending)
        finally:
            self._close_process_pipes(process)

    def _handle_process_output_line(self, line: str) -> None:
        if not line:
            return
        self._append_log_line(line)
        if "Input #0" in line or "Stream mapping:" in line:
            with self.state_lock:
                self.stream_incoming = True
        self._record_bitrate_from_line(line)

    def _record_bitrate_from_line(self, line: str) -> None:
        match = BITRATE_PATTERN.search(line)
        if match:
            value = float(match.group(1))
            unit = (match.group(2) or "k").lower()
            bitrate_kbps = value * 1000 if unit == "m" else value
            self._record_bitrate_sample(bitrate_kbps)
            return

        input_match = INPUT_STREAM_BITRATE_PATTERN.search(line)
        if not input_match:
            return
        stream_id = input_match.group("stream")
        bitrate_kbps = float(input_match.group("bitrate"))
        with self.state_lock:
            self.input_stream_bitrates[stream_id] = bitrate_kbps
            total_bitrate_kbps = sum(self.input_stream_bitrates.values())
        self._record_bitrate_sample(total_bitrate_kbps)

    def _record_bitrate_sample(self, bitrate_kbps: float) -> None:
        sample = {"time": time.time(), "bitrateKbps": bitrate_kbps}
        with self.state_lock:
            self.current_bitrate_kbps = bitrate_kbps
            self.bitrate_samples.append(sample)

    def _refresh_bitrate_sample(self) -> None:
        now = time.time()
        with self.state_lock:
            if not self.stream_incoming or self.current_bitrate_kbps <= 0:
                return
            if self.bitrate_samples:
                last_sample_time = self.bitrate_samples[-1]["time"]
                if now - last_sample_time < BITRATE_SAMPLE_INTERVAL_SECONDS:
                    return
            bitrate_kbps = self.current_bitrate_kbps
            self.bitrate_samples.append({"time": now, "bitrateKbps": bitrate_kbps})

    def _prepare_log(self, command: list[str]) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        header = [
            "",
            f"=== Relay started at {timestamp} ===",
            f"Command: {' '.join(command)}",
        ]
        with self.log_lock:
            self.recent_log_lines.clear()
            with self.log_path.open("a", encoding="utf-8") as log:
                for line in header:
                    log.write(f"{line}\n")
                    self.recent_log_lines.append(line)

    def _append_log_line(self, line: str) -> None:
        redacted = redact_text(line.rstrip("\n"))
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_lock:
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(f"{redacted}\n")
            self.recent_log_lines.append(redacted)

    def _recent_log_lines(self) -> list[str]:
        with self.log_lock:
            return list(self.recent_log_lines)

    def _telemetry(self) -> dict[str, Any]:
        cutoff = time.time() - BITRATE_HISTORY_SECONDS
        with self.state_lock:
            history = [
                sample for sample in self.bitrate_samples if sample["time"] >= cutoff
            ]
            bitrate = self.current_bitrate_kbps
            active_since = self.active_since
        return {
            "source": {
                "bitrateKbps": bitrate,
                "history": history,
                "activeSince": active_since,
            }
        }

    def _state(self, running: bool) -> str:
        if self.last_error:
            return "error"
        if self.active_source_id is not None:
            return "live"
        return "waiting"

    def _pipeline_status(self, pipeline: Any, telemetry: dict[str, Any]) -> dict[str, Any]:
        active = bool(pipeline.enabled and self.stream_incoming)
        bitrate = telemetry["source"]["bitrateKbps"] if active else 0.0
        return {
            "name": pipeline.name,
            "enabled": pipeline.enabled,
            "sourceId": pipeline.source_id,
            "destinationId": pipeline.destination_id,
            "mode": "copy"
            if not pipeline.transcodes
            else f"transcode:{pipeline.transcodes[-1].codec}",
            "health": "healthy" if active else "inactive",
            "live": active,
            "bitrateKbps": bitrate,
            "bitrateHistory": telemetry["source"]["history"] if active else [],
        }

    def _active_source(self, config: RelayConfig) -> SourceConfig:
        enabled = config.enabled_pipelines
        if enabled:
            source_ids = {pipeline.source_id for pipeline in enabled}
        else:
            source_ids = {source.id for source in config.sources if source.enabled}

        if not source_ids:
            raise ConfigError("At least one source must be enabled.")
        if len(source_ids) > 1:
            raise ConfigError("Only one active RTMP source is supported per relay process right now.")

        source = config.source_by_id(next(iter(source_ids)))
        if not source.enabled:
            raise ConfigError(f"Source '{source.name}' must be enabled before starting the relay.")
        return source

    def _prepare_preview(self) -> None:
        self.preview_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_preview()

    def _clear_preview(self) -> None:
        try:
            self.preview_path.unlink()
        except FileNotFoundError:
            pass
