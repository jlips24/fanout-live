from __future__ import annotations

import unittest
from pathlib import Path

from fanout_live.config import (
    ConfigError,
    DestinationConfig,
    FfmpegConfig,
    PipelineConfig,
    RelayConfig,
    SourceConfig,
    TranscodeConfig,
)
from fanout_live.ffmpeg import build_ffmpeg_command, redact_command, redact_text


class FfmpegTests(unittest.TestCase):
    def test_build_ffmpeg_command_supports_copy_and_transcode_pipelines(self):
        config = RelayConfig(
            ffmpeg=FfmpegConfig(binary="ffmpeg", log_level="warning"),
            sources=(
                SourceConfig(
                    id="obs",
                    name="obs",
                    enabled=True,
                    host="0.0.0.0",
                    port=1935,
                    app="live",
                    stream="stream",
                ),
            ),
            destinations=(
                DestinationConfig(
                    id="youtube",
                    name="youtube",
                    enabled=True,
                    service="youtube",
                    stream_key="youtube-key",
                    url="rtmp://a.rtmp.youtube.com/live2/youtube-key",
                ),
                DestinationConfig(
                    id="twitch",
                    name="twitch",
                    enabled=True,
                    service="twitch",
                    stream_key="twitch-key",
                    url="rtmp://live.twitch.tv/app/twitch-key",
                ),
            ),
            pipelines=(
                PipelineConfig(
                    name="youtube-direct",
                    enabled=True,
                    source_id="obs",
                    destination_id="youtube",
                    transcodes=(),
                ),
                PipelineConfig(
                    name="twitch-h264",
                    enabled=True,
                    source_id="obs",
                    destination_id="twitch",
                    transcodes=(
                        TranscodeConfig(
                            codec="h264",
                            video_bitrate_kbps=6000,
                            audio_bitrate_kbps=160,
                            preset="veryfast",
                        ),
                    ),
                ),
            ),
        )

        command = build_ffmpeg_command(config)

        self.assertIn("-listen", command)
        self.assertIn("rtmp://0.0.0.0:1935/live/stream", command)
        self.assertIn("rtmp://a.rtmp.youtube.com/live2/youtube-key", command)
        self.assertIn("rtmp://live.twitch.tv/app/twitch-key", command)
        self.assertIn("copy", command)
        self.assertIn("libx264", command)
        self.assertIn("6000k", command)

    def test_redact_command_hides_stream_keys(self):
        command = [
            "ffmpeg",
            "-i",
            "rtmp://0.0.0.0:1935/live/stream",
            "rtmp://live.twitch.tv/app/secret",
        ]

        self.assertEqual(
            redact_command(command),
            [
                "ffmpeg",
                "-i",
                "rtmp://0.0.0.0:1935/live/***",
                "rtmp://live.twitch.tv/app/***",
            ],
        )

    def test_redact_text_hides_stream_keys_in_ffmpeg_output(self):
        self.assertEqual(
            redact_text("Failed to open rtmp://live.twitch.tv/app/secret-key"),
            "Failed to open rtmp://live.twitch.tv/app/***",
        )

    def test_disabled_source_cannot_build_command(self):
        config = RelayConfig(
            ffmpeg=FfmpegConfig(binary="ffmpeg", log_level="warning"),
            sources=(
                SourceConfig(
                    id="obs",
                    name="obs",
                    enabled=False,
                    host="0.0.0.0",
                    port=1935,
                    app="live",
                    stream="stream",
                ),
            ),
            destinations=(
                DestinationConfig(
                    id="twitch",
                    name="twitch",
                    enabled=True,
                    service="twitch",
                    stream_key="twitch-key",
                    url="rtmp://live.twitch.tv/app/twitch-key",
                ),
            ),
            pipelines=(
                PipelineConfig(
                    name="twitch",
                    enabled=True,
                    source_id="obs",
                    destination_id="twitch",
                    transcodes=(),
                ),
            ),
        )

        with self.assertRaisesRegex(ConfigError, "Source"):
            build_ffmpeg_command(config)

    def test_build_ffmpeg_command_accepts_enabled_source_without_pipelines(self):
        config = RelayConfig(
            ffmpeg=FfmpegConfig(binary="ffmpeg", log_level="warning"),
            sources=(
                SourceConfig(
                    id="obs",
                    name="obs",
                    enabled=True,
                    host="0.0.0.0",
                    port=1935,
                    app="live",
                    stream="stream",
                ),
            ),
            destinations=(),
            pipelines=(),
        )

        command = build_ffmpeg_command(config)

        self.assertIn("rtmp://0.0.0.0:1935/live/stream", command)
        self.assertEqual(command[-5:], ["-c", "copy", "-f", "null", "-"])

    def test_build_ffmpeg_command_can_pull_from_nginx_ingest(self):
        config = RelayConfig(
            ffmpeg=FfmpegConfig(binary="ffmpeg", log_level="warning"),
            sources=(
                SourceConfig(
                    id="obs",
                    name="obs",
                    enabled=True,
                    host="0.0.0.0",
                    port=1935,
                    app="live",
                    stream="stream",
                ),
            ),
            destinations=(),
            pipelines=(),
        )

        command = build_ffmpeg_command(
            config,
            input_url="rtmp://127.0.0.1:1935/live/stream",
            listen=False,
        )

        self.assertNotIn("-listen", command)
        self.assertIn("rtmp://127.0.0.1:1935/live/stream", command)

    def test_build_ffmpeg_command_supports_file_destination(self):
        config = RelayConfig(
            ffmpeg=FfmpegConfig(binary="ffmpeg", log_level="warning"),
            sources=(
                SourceConfig(
                    id="obs",
                    name="obs",
                    enabled=True,
                    host="0.0.0.0",
                    port=1935,
                    app="live",
                    stream="stream",
                ),
            ),
            destinations=(
                DestinationConfig(
                    id="recordings",
                    name="recordings",
                    enabled=True,
                    service="file",
                    stream_key="",
                    url="/config/recordings",
                ),
            ),
            pipelines=(
                PipelineConfig(
                    name="save",
                    enabled=True,
                    source_id="obs",
                    destination_id="recordings",
                    transcodes=(),
                ),
            ),
        )

        command = build_ffmpeg_command(config)

        self.assertIn("-f", command)
        self.assertIn("segment", command)
        self.assertIn("-strftime", command)
        self.assertIn("/config/recordings/stream-%Y%m%d-%H%M%S.mkv", command)

    def test_build_ffmpeg_command_can_add_preview_output(self):
        config = RelayConfig(
            ffmpeg=FfmpegConfig(binary="ffmpeg", log_level="warning"),
            sources=(
                SourceConfig(
                    id="obs",
                    name="obs",
                    enabled=True,
                    host="0.0.0.0",
                    port=1935,
                    app="live",
                    stream="stream",
                ),
            ),
            destinations=(),
            pipelines=(),
        )

        command = build_ffmpeg_command(config, preview_path=Path("/tmp/preview.jpg"))

        self.assertIn("fps=1,scale=640:-2", command)
        self.assertIn("-update", command)
        self.assertEqual(command[-1], "/tmp/preview.jpg")


if __name__ == "__main__":
    unittest.main()
