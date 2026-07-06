from __future__ import annotations

import json
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .config import ConfigError, load_config
from .config_store import (
    ensure_config_file,
    load_raw_config,
    rotate_source_stream_key,
    save_raw_config,
)
from .ffmpeg import build_ffmpeg_command, prepare_file_destinations, redact_command

STATIC_DIR = Path(__file__).with_name("webui")
PREVIEW_FILE_NAME = "preview.jpg"


class RelayController:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.preview_path = config_path.parent / "preview" / PREVIEW_FILE_NAME
        self.process: subprocess.Popen[bytes] | None = None
        self.watch_thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.stream_incoming = False

    def status(self) -> dict[str, Any]:
        running = self.process is not None and self.process.poll() is None
        if self.process is not None and not running:
            code = self.process.returncode
            self._close_process_pipes(self.process)
            self.process = None
            self.stream_incoming = False
            if code:
                self.last_error = f"Relay exited with code {code}."

        payload = {
            "running": running,
            "pid": self.process.pid if running and self.process is not None else None,
            "lastError": self.last_error,
            "streamIncoming": self.stream_incoming,
            "previewUrl": self.preview_url if self.stream_incoming else None,
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
                }
            payload["pipelines"] = [
                {
                    "name": pipeline.name,
                    "enabled": pipeline.enabled,
                    "sourceId": pipeline.source_id,
                    "destinationId": pipeline.destination_id,
                    "mode": "copy"
                    if not pipeline.transcodes
                    else f"transcode:{pipeline.transcodes[-1].codec}",
                }
                for pipeline in config.pipelines
            ]
        except ConfigError as exc:
            payload["configError"] = str(exc)
        return payload

    def start(self) -> dict[str, Any]:
        if self.status()["running"]:
            return self.status()

        config = load_config(self.config_path)
        prepare_file_destinations(config)
        self._prepare_preview()
        command = build_ffmpeg_command(config, preview_path=self.preview_path)
        self.process = subprocess.Popen(
            command,
            stderr=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
        )
        self.watch_thread = threading.Thread(target=self._watch_process_output, daemon=True)
        self.watch_thread.start()
        self.last_error = None
        return {**self.status(), "command": redact_command(command)}

    def stop(self) -> dict[str, Any]:
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
        self.process = None
        self.watch_thread = None
        self.stream_incoming = False
        self._clear_preview()
        return self.status()

    @property
    def preview_url(self) -> str:
        version = int(self.preview_path.stat().st_mtime) if self.preview_path.exists() else 0
        return f"/preview/{PREVIEW_FILE_NAME}?v={version}"

    def _close_process_pipes(self, process: subprocess.Popen[bytes]) -> None:
        if process.stderr is not None and not process.stderr.closed:
            process.stderr.close()

    def _watch_process_output(self) -> None:
        process = self.process
        if process is None or process.stderr is None:
            return
        try:
            for raw_line in process.stderr:
                line = raw_line.decode("utf-8", errors="replace")
                if "Input #0" in line or "Stream mapping:" in line:
                    self.stream_incoming = True
        finally:
            self._close_process_pipes(process)

    def _prepare_preview(self) -> None:
        self.preview_path.parent.mkdir(parents=True, exist_ok=True)
        self._clear_preview()

    def _clear_preview(self) -> None:
        try:
            self.preview_path.unlink()
        except FileNotFoundError:
            pass


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def run_web_server(config_path: Path, host: str, port: int) -> None:
    ensure_config_file(config_path)
    controller = RelayController(config_path)
    try:
        controller.start()
    except ConfigError as exc:
        controller.last_error = str(exc)

    class Handler(WebHandler):
        relay_controller = controller
        relay_config_path = config_path

    server = ReusableThreadingHTTPServer((host, port), Handler)
    print(f"Web UI: http://{host}:{port}")
    print(f"Config: {config_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping web UI...")
    finally:
        controller.stop()
        server.server_close()


class WebHandler(SimpleHTTPRequestHandler):
    relay_controller: RelayController
    relay_config_path: Path

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        super().end_headers()

    def do_GET(self) -> None:
        if self.path == "/api/config":
            self._send_json(load_raw_config(self.relay_config_path))
            return
        if self.path == "/api/status":
            self._send_json(self.relay_controller.status())
            return
        if self.path.startswith("/preview/"):
            self._send_preview()
            return
        super().do_GET()

    def do_PUT(self) -> None:
        if self.path != "/api/config":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self._read_json()
            saved = save_raw_config(self.relay_config_path, payload)
        except (ConfigError, json.JSONDecodeError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json(saved)

    def do_POST(self) -> None:
        try:
            if self.path == "/api/relay/start":
                self._send_json(self.relay_controller.start())
                return
            if self.path == "/api/relay/stop":
                self._send_json(self.relay_controller.stop())
                return
            if self.path == "/api/source-key/rotate":
                payload = self._read_json()
                source_id = str(payload.get("source_id", payload.get("source", "")))
                self._send_json(rotate_source_stream_key(self.relay_config_path, source_id))
                return
        except ConfigError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        data = self.rfile.read(length)
        payload = json.loads(data.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ConfigError("Request body must be a JSON object.")
        return payload

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_preview(self) -> None:
        preview_path = self.relay_controller.preview_path
        if not preview_path.exists() or time.time() - preview_path.stat().st_mtime > 10:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        body = preview_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
