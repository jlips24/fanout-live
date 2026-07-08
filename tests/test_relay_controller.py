from __future__ import annotations

import stat
import tempfile
import time
import unittest
from pathlib import Path

from fanout_live.web import RelayController


class RelayControllerTests(unittest.TestCase):
    def test_failed_relay_writes_redacted_log(self):
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


if __name__ == "__main__":
    unittest.main()
