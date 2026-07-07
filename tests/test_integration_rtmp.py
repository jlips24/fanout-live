from __future__ import annotations

import shutil
import socket
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from fanout_live.web import RelayController

FFMPEG = shutil.which("ffmpeg")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError as exc:
            raise unittest.SkipTest("local socket binding is not permitted") from exc
        return int(sock.getsockname()[1])


def _terminate(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    finally:
        if process.stderr is not None and not process.stderr.closed:
            process.stderr.close()


@unittest.skipUnless(FFMPEG, "ffmpeg is required for RTMP integration tests")
class RtmpIntegrationTests(unittest.TestCase):
    def test_relay_accepts_rtmp_publish_without_pipelines(self):
        source_port = _free_port()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                f"""
[ffmpeg]
binary = "{FFMPEG}"
log_level = "info"

[[sources]]
name = "phone"
host = "127.0.0.1"
port = {source_port}
app = "live"
stream = "phone-key"
""",
                encoding="utf-8",
            )

            controller = RelayController(config_path)
            try:
                controller.start()
                time.sleep(0.25)
                publisher = subprocess.run(
                    [
                        FFMPEG,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-re",
                        "-f",
                        "lavfi",
                        "-i",
                        "testsrc=size=320x180:rate=15",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=channel_layout=stereo:sample_rate=44100",
                        "-t",
                        "3",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-f",
                        "flv",
                        f"rtmp://127.0.0.1:{source_port}/live/phone-key",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=15,
                )

                self.assertEqual(
                    publisher.returncode,
                    0,
                    publisher.stderr.decode("utf-8", errors="replace"),
                )
                self.assertTrue(controller.preview_path.exists())
                self.assertGreater(controller.preview_path.stat().st_size, 0)
            finally:
                controller.stop()

    def test_relay_accepts_rtmp_publish_and_forwards_to_destination(self):
        source_port = _free_port()
        destination_port = _free_port()

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                f"""
[ffmpeg]
binary = "{FFMPEG}"
log_level = "info"

[[sources]]
name = "phone"
host = "127.0.0.1"
port = {source_port}
app = "live"
stream = "phone-key"

[[destinations]]
name = "loopback"
url = "rtmp://127.0.0.1:{destination_port}/sink/out"

[[pipelines]]
name = "loopback-direct"
source = "phone"
destination = "loopback"
""",
                encoding="utf-8",
            )

            sink = subprocess.Popen(
                [
                    FFMPEG,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-listen",
                    "1",
                    "-i",
                    f"rtmp://127.0.0.1:{destination_port}/sink/out",
                    "-t",
                    "2",
                    "-f",
                    "null",
                    "-",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            controller = RelayController(config_path)
            try:
                controller.start()
                time.sleep(0.25)
                publisher = subprocess.run(
                    [
                        FFMPEG,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-re",
                        "-f",
                        "lavfi",
                        "-i",
                        "testsrc=size=320x180:rate=15",
                        "-f",
                        "lavfi",
                        "-i",
                        "anullsrc=channel_layout=stereo:sample_rate=44100",
                        "-t",
                        "1.5",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-pix_fmt",
                        "yuv420p",
                        "-c:a",
                        "aac",
                        "-f",
                        "flv",
                        f"rtmp://127.0.0.1:{source_port}/live/phone-key",
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=15,
                )

                self.assertEqual(
                    publisher.returncode,
                    0,
                    publisher.stderr.decode("utf-8", errors="replace"),
                )

                deadline = time.time() + 5
                while not controller.status()["streamIncoming"] and time.time() < deadline:
                    time.sleep(0.1)

                self.assertTrue(controller.status()["streamIncoming"])

                sink_return_code = sink.wait(timeout=10)
                sink_stderr = sink.stderr.read().decode("utf-8", errors="replace")
                sink.stderr.close()
                self.assertEqual(
                    sink_return_code,
                    0,
                    sink_stderr,
                )
            finally:
                controller.stop()
                _terminate(sink)


if __name__ == "__main__":
    unittest.main()
