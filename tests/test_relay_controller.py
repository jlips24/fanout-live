from __future__ import annotations

import stat
import tempfile
import time
import unittest
from collections import deque
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from fanout_live.web import RelayController


class FakeThread:
    created = []

    def __init__(self, *, target, args=(), daemon=False, **_kwargs) -> None:
        self.target = target
        self.args = args
        self.daemon = daemon
        self.started = False
        self.created.append(self)

    def start(self) -> None:
        self.started = True

    def join(self, timeout: int | None = None) -> None:
        return None


class FakeProcess:
    pid = 12345

    def __init__(self, *_args, **_kwargs) -> None:
        self.stderr = None
        self.returncode = None

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: int | None = None) -> int:
        self.returncode = 0
        return 0

    def kill(self) -> None:
        self.returncode = -9


class FakeOutputProcess(FakeProcess):
    def __init__(self, stderr: bytes) -> None:
        super().__init__()
        self.stderr = BytesIO(stderr)


class RelayControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeThread.created = []

    def test_publish_marks_source_live_before_ffmpeg_input_logs(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)
            with patch("fanout_live.relay.controller.threading.Thread", FakeThread):
                status = controller.publish(app="live", stream="stream-key")

            self.assertEqual(status["state"], "live")
            self.assertTrue(status["sourcePublishing"])
            self.assertTrue(status["source"]["live"])
            self.assertFalse(status["streamIncoming"])
            self.assertFalse(status["running"])

    def test_log_paths_use_logs_directory(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)
            status = controller.status()

            self.assertEqual(controller.log_path.parent.name, "logs")
            self.assertIn("/logs/relay.log", status["relayLogPath"])
            self.assertIn("/logs/nginx-error.log", status["nginxErrorLogPath"])
            self.assertIn("/logs/nginx-rtmp-access.log", status["nginxRtmpAccessLogPath"])

    def test_publish_defers_ffmpeg_start_until_after_callback_returns(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)
            popen_calls = []

            def fake_popen(*args, **kwargs):
                popen_calls.append((args, kwargs))
                return FakeProcess()

            with (
                patch("fanout_live.relay.controller.threading.Thread", FakeThread),
                patch("fanout_live.relay.controller.subprocess.Popen", fake_popen),
                patch("fanout_live.relay.controller.time.sleep", lambda _seconds: None),
                patch.object(controller, "_wait_for_fanout_input", return_value=True),
            ):
                status = controller.publish(app="live", stream="stream-key")

                self.assertEqual(status["state"], "live")
                self.assertFalse(status["running"])
                self.assertEqual(popen_calls, [])
                self.assertEqual(len(FakeThread.created), 1)
                self.assertTrue(FakeThread.created[0].started)
                self.assertTrue(FakeThread.created[0].daemon)

                FakeThread.created[0].target(*FakeThread.created[0].args)

            self.assertEqual(len(popen_calls), 1)
            self.assertTrue(controller.status()["running"])

    def test_deferred_fanout_retries_when_first_pull_has_no_input(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)
            popen_calls = []

            def fake_popen(*args, **kwargs):
                popen_calls.append((args, kwargs))
                return FakeProcess()

            with (
                patch("fanout_live.relay.controller.threading.Thread", FakeThread),
                patch("fanout_live.relay.controller.subprocess.Popen", fake_popen),
                patch("fanout_live.relay.controller.time.sleep", lambda _seconds: None),
                patch.object(controller, "_wait_for_fanout_input", side_effect=[False, True]),
            ):
                controller.publish(app="live", stream="stream-key")
                FakeThread.created[0].target(*FakeThread.created[0].args)

            self.assertEqual(len(popen_calls), 2)
            self.assertTrue(controller.status()["running"])
            self.assertIsNone(controller.last_error)

    def test_bitrate_parser_records_ffmpeg_progress_bitrate(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)

            controller._record_bitrate_from_line(
                "frame= 115 fps=0.0 size=1079KiB time=00:00:01.00 bitrate=8841.6kbits/s"
            )

            telemetry = controller.status()["telemetry"]["source"]
            self.assertEqual(telemetry["bitrateKbps"], 8841.6)
            self.assertEqual(telemetry["history"][-1]["bitrateKbps"], 8841.6)

    def test_bitrate_parser_falls_back_to_declared_input_stream_bitrates(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)

            controller._record_bitrate_from_line(
                "  Stream #0:0: Audio: aac (LC), 48000 Hz, stereo, fltp, 163 kb/s"
            )
            controller._record_bitrate_from_line(
                "  Stream #0:1: Video: h264 (High), yuv420p, 3024x1964, 6144 kb/s, 60 fps"
            )

            telemetry = controller.status()["telemetry"]["source"]
            self.assertEqual(telemetry["bitrateKbps"], 6307.0)
            self.assertEqual(telemetry["history"][-1]["bitrateKbps"], 6307.0)

    def test_watcher_parses_carriage_return_ffmpeg_progress(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)
            controller.process = FakeOutputProcess(
                b"frame=1 bitrate=1000.0kbits/s\rframe=2 bitrate=2000.0kbits/s\r"
            )

            controller._watch_process_output()

            telemetry = controller.status()["telemetry"]["source"]
            self.assertEqual(telemetry["bitrateKbps"], 2000.0)
            self.assertEqual(telemetry["history"][-1]["bitrateKbps"], 2000.0)

    def test_bitrate_refresh_adds_samples_once_per_second(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)
            controller.stream_incoming = True
            controller.current_bitrate_kbps = 4000.0

            with patch("fanout_live.relay.controller.time.time", return_value=100.0):
                controller._refresh_bitrate_sample()
            with patch("fanout_live.relay.controller.time.time", return_value=100.5):
                controller._refresh_bitrate_sample()
            with patch("fanout_live.relay.controller.time.time", return_value=101.1):
                controller._refresh_bitrate_sample()

            history = list(controller.bitrate_samples)
            self.assertEqual([sample["time"] for sample in history], [100.0, 101.1])
            self.assertEqual([sample["bitrateKbps"] for sample in history], [4000.0, 4000.0])

    def test_telemetry_keeps_last_30_seconds_of_bitrate_history(self) -> None:
        with self.config_path() as config_path:
            controller = RelayController(config_path)
            controller.bitrate_samples = deque(
                [
                    {"time": 69.9, "bitrateKbps": 1000.0},
                    {"time": 70.0, "bitrateKbps": 2000.0},
                    {"time": 100.0, "bitrateKbps": 3000.0},
                ],
                maxlen=90,
            )

            with patch("fanout_live.relay.controller.time.time", return_value=100.0):
                telemetry = controller._telemetry()

            self.assertEqual(
                telemetry["source"]["history"],
                [
                    {"time": 70.0, "bitrateKbps": 2000.0},
                    {"time": 100.0, "bitrateKbps": 3000.0},
                ],
            )

    def test_failed_relay_writes_redacted_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            fake_ffmpeg = tmp_path / "fake-ffmpeg"
            fake_ffmpeg.write_text(
                "\n".join(
                    [
                        "#!/bin/sh",
                        "echo 'Failed to open rtmp://live.twitch.tv/app/super-secret-key' >&2",
                        "exit 224",
                    ]
                ),
                encoding="utf-8",
            )
            fake_ffmpeg.chmod(fake_ffmpeg.stat().st_mode | stat.S_IXUSR)

            config_path = tmp_path / "config.toml"
            config_path.write_text(
                f"""
[ffmpeg]
binary = "{fake_ffmpeg}"
log_level = "info"

[[sources]]
name = "phone"
host = "127.0.0.1"
port = 1935
app = "live"
stream = "phone-key"
""",
                encoding="utf-8",
            )

            controller = RelayController(config_path)
            controller.start()

            deadline = time.time() + 2
            status = controller.status()
            while status["running"] and time.time() < deadline:
                time.sleep(0.05)
                status = controller.status()

            self.assertFalse(status["running"])
            self.assertIn("Relay exited with code 224", status["lastError"])
            self.assertEqual(status["relayLogPath"], str(controller.log_path))
            self.assertTrue(controller.log_path.exists())

            log_text = controller.log_path.read_text(encoding="utf-8")
            self.assertIn("Relay started", log_text)
            self.assertIn("Failed to open rtmp://live.twitch.tv/app/***", log_text)
            self.assertNotIn("super-secret-key", log_text)
            self.assertIn("Failed to open rtmp://live.twitch.tv/app/***", status["recentRelayLog"])

    def config_path(self):
        return ConfigPathFixture()


class ConfigPathFixture:
    def __enter__(self) -> Path:
        self.tmpdir = tempfile.TemporaryDirectory()
        config_path = Path(self.tmpdir.name) / "config.toml"
        config_path.write_text(
            """
[ffmpeg]
binary = "ffmpeg"
log_level = "info"

[[sources]]
id = "obs"
name = "obs"
host = "0.0.0.0"
port = 1935
app = "live"
stream = "stream-key"
""",
            encoding="utf-8",
        )
        return config_path

    def __exit__(self, *_args) -> None:
        self.tmpdir.cleanup()


if __name__ == "__main__":
    unittest.main()
