from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from remote_multistreamer.config import ConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_load_config_expands_environment_variables_and_pipelines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            previous = os.environ.get("TWITCH_STREAM_KEY")
            os.environ["TWITCH_STREAM_KEY"] = "abc123"
            try:
                config_path = Path(tmpdir) / "config.toml"
                config_path.write_text(
                    """
[ffmpeg]
binary = "ffmpeg"

[[sources]]
name = "obs"
host = "127.0.0.1"
port = 1935
app = "live"
stream = "stream"

[[destinations]]
name = "twitch"
service = "twitch"
stream_key = "${TWITCH_STREAM_KEY}"

[[pipelines]]
name = "twitch-direct"
source = "obs"
destination = "twitch"
""",
                    encoding="utf-8",
                )

                config = load_config(config_path)

                self.assertEqual(
                    config.source_by_name("obs").listen_url,
                    "rtmp://127.0.0.1:1935/live/stream",
                )
                self.assertEqual(
                    config.destination_by_name("twitch").url,
                    "rtmp://live.twitch.tv/app/abc123",
                )
                self.assertEqual(config.enabled_pipelines[0].name, "twitch-direct")
            finally:
                if previous is None:
                    os.environ.pop("TWITCH_STREAM_KEY", None)
                else:
                    os.environ["TWITCH_STREAM_KEY"] = previous

    def test_legacy_config_migrates_for_editing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                """
[ingest]
enabled = false

[[destinations]]
name = "twitch"
enabled = false
url = "rtmp://live.twitch.tv/app/example"
""",
                encoding="utf-8",
            )

            config = load_config(config_path, require_ready=False)

            self.assertFalse(config.source_by_name("obs").enabled)
            self.assertEqual(config.pipelines[0].destination_id, "twitch")

            with self.assertRaisesRegex(ConfigError, "source"):
                load_config(config_path)

    def test_multiple_active_sources_are_rejected_for_now(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                """
[[sources]]
name = "obs-a"

[[sources]]
name = "obs-b"

[[destinations]]
name = "a"
url = "rtmp://example.invalid/app/a"

[[destinations]]
name = "b"
url = "rtmp://example.invalid/app/b"

[[pipelines]]
name = "a"
source = "obs-a"
destination = "a"

[[pipelines]]
name = "b"
source = "obs-b"
destination = "b"
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "one active RTMP source"):
                load_config(config_path)

    def test_legacy_pipeline_name_references_resolve_to_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                """
[[sources]]
id = "source-123"
name = "OBS Renamed"

[[destinations]]
id = "destination-456"
name = "Twitch Renamed"
enabled = false
service = "twitch"

[[pipelines]]
name = "twitch"
enabled = false
source = "OBS Renamed"
destination = "Twitch Renamed"
""",
                encoding="utf-8",
            )

            config = load_config(config_path, require_ready=False)

            self.assertEqual(config.pipelines[0].source_id, "source-123")
            self.assertEqual(config.pipelines[0].destination_id, "destination-456")

    def test_missing_environment_variable_is_config_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.environ.pop("TWITCH_STREAM_KEY", None)
            config_path = Path(tmpdir) / "config.toml"
            config_path.write_text(
                """
[[sources]]
name = "obs"

[[destinations]]
name = "twitch"
service = "twitch"
stream_key = "${TWITCH_STREAM_KEY}"

[[pipelines]]
name = "twitch"
source = "obs"
destination = "twitch"
""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "TWITCH_STREAM_KEY"):
                load_config(config_path)

    def test_default_edit_config_has_no_destinations_or_pipelines(self):
        from remote_multistreamer.config_store import load_raw_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_raw_config(Path(tmpdir) / "missing.toml")

            self.assertEqual(config["destinations"], [])
            self.assertEqual(config["pipelines"], [])
            self.assertRegex(config["sources"][0]["stream"], r"^rms_")

    def test_ensure_config_file_persists_generated_stream_key(self):
        from remote_multistreamer.config_store import ensure_config_file

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            first = ensure_config_file(config_path)
            second = ensure_config_file(config_path)

            self.assertTrue(config_path.exists())
            self.assertEqual(first["sources"][0]["stream"], second["sources"][0]["stream"])

    def test_rotate_source_stream_key_persists_new_value(self):
        from remote_multistreamer.config_store import ensure_config_file, rotate_source_stream_key

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            before = ensure_config_file(config_path)["sources"][0]["stream"]
            rotated = rotate_source_stream_key(config_path, "obs")
            after = rotated["sources"][0]["stream"]

            self.assertNotEqual(before, after)
            self.assertRegex(after, r"^rms_")

    def test_pipeline_ids_survive_source_and_destination_renames(self):
        from remote_multistreamer.config_store import save_raw_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            saved = save_raw_config(
                config_path,
                {
                    "sources": [{"id": "source-123", "name": "OBS"}],
                    "ffmpeg": {"binary": "ffmpeg", "log_level": "info"},
                    "destinations": [
                        {
                            "id": "destination-456",
                            "name": "YouTube",
                            "enabled": False,
                            "service": "youtube",
                            "stream_key": "",
                            "url": "",
                        }
                    ],
                    "pipelines": [
                        {
                            "name": "Direct",
                            "enabled": False,
                            "source_id": "source-123",
                            "destination_id": "destination-456",
                            "transcodes": [],
                        }
                    ],
                },
            )
            saved["sources"][0]["name"] = "Renamed OBS"
            saved["destinations"][0]["name"] = "Renamed YouTube"
            renamed = save_raw_config(config_path, saved)

            self.assertEqual(renamed["pipelines"][0]["source_id"], "source-123")
            self.assertEqual(renamed["pipelines"][0]["destination_id"], "destination-456")

            config = load_config(config_path, require_ready=False)
            self.assertEqual(config.source_by_id("source-123").name, "Renamed OBS")
            self.assertEqual(
                config.destination_by_id("destination-456").name,
                "Renamed YouTube",
            )

    def test_known_destination_can_be_saved_with_stream_key_only(self):
        from remote_multistreamer.config_store import save_raw_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            saved = save_raw_config(
                config_path,
                {
                    "sources": [{"name": "obs"}],
                    "ffmpeg": {"binary": "ffmpeg", "log_level": "info"},
                    "destinations": [
                        {
                            "name": "youtube",
                            "enabled": True,
                            "service": "youtube",
                            "stream_key": "abc-def",
                            "url": "",
                        }
                    ],
                    "pipelines": [],
                },
            )

            self.assertEqual(saved["destinations"][0]["service"], "youtube")
            self.assertEqual(saved["destinations"][0]["stream_key"], "abc-def")

    def test_file_destination_can_be_saved_with_recording_path(self):
        from remote_multistreamer.config_store import save_raw_config

        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.toml"
            saved = save_raw_config(
                config_path,
                {
                    "sources": [{"name": "obs"}],
                    "ffmpeg": {"binary": "ffmpeg", "log_level": "info"},
                    "destinations": [
                        {
                            "name": "recordings",
                            "enabled": True,
                            "service": "file",
                            "stream_key": "",
                            "url": "/config/recordings",
                        }
                    ],
                    "pipelines": [],
                },
            )

            self.assertEqual(saved["destinations"][0]["service"], "file")
            self.assertEqual(saved["destinations"][0]["url"], "/config/recordings")


if __name__ == "__main__":
    unittest.main()
