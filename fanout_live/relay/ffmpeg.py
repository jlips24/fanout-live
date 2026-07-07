from __future__ import annotations

from pathlib import Path

from ..config import (
    ConfigError,
    DestinationConfig,
    PipelineConfig,
    RelayConfig,
    SourceConfig,
    TranscodeConfig,
)


def build_ffmpeg_command(config: RelayConfig, *, preview_path: Path | None = None) -> list[str]:
    enabled = config.enabled_pipelines
    source = _active_source(config)

    command = [
        config.ffmpeg.binary,
        "-hide_banner",
        "-loglevel",
        config.ffmpeg.log_level,
        "-listen",
        "1",
        "-i",
        source.listen_url,
    ]

    for pipeline in enabled:
        destination = config.destination_by_id(pipeline.destination_id)
        if not destination.enabled:
            raise ConfigError(
                f"Destination '{destination.name}' must be enabled before starting the relay."
            )
        command.extend(_output_args(pipeline, destination))

    if not enabled:
        command.extend(["-map", "0", "-c", "copy", "-f", "null", "-"])

    if preview_path is not None:
        command.extend(_preview_output_args(preview_path))

    return command


def redact_command(command: list[str]) -> list[str]:
    return [_redact_arg(arg) for arg in command]


def prepare_file_destinations(config: RelayConfig) -> None:
    for pipeline in config.enabled_pipelines:
        destination = config.destination_by_id(pipeline.destination_id)
        if destination.enabled and destination.service == "file":
            _recording_directory(destination.url).mkdir(parents=True, exist_ok=True)


def _active_source(config: RelayConfig) -> SourceConfig:
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


def _output_args(pipeline: PipelineConfig, destination: DestinationConfig) -> list[str]:
    args = [
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
    ]
    if not pipeline.transcodes:
        args.extend(["-c:v", "copy", "-c:a", "copy"])
    else:
        transcode = pipeline.transcodes[-1]
        args.extend(_transcode_args(transcode))
    if destination.service == "file":
        args.extend(
            [
                "-f",
                "segment",
                "-segment_time",
                "3600",
                "-strftime",
                "1",
                "-reset_timestamps",
                "1",
                str(_recording_output_path(destination.url)),
            ]
        )
    else:
        args.extend(["-f", "flv", destination.url])
    return args


def _preview_output_args(path: Path) -> list[str]:
    return [
        "-map",
        "0:v:0",
        "-an",
        "-vf",
        "fps=1,scale=640:-2",
        "-q:v",
        "5",
        "-update",
        "1",
        str(path),
    ]


def _recording_directory(path: str) -> Path:
    destination = Path(path).expanduser()
    if destination.suffix:
        return destination.parent
    return destination


def _recording_output_path(path: str) -> Path:
    destination = Path(path).expanduser()
    if destination.suffix:
        return destination.with_name(
            f"{destination.stem}-%Y%m%d-%H%M%S{destination.suffix}"
        )
    return destination / "stream-%Y%m%d-%H%M%S.mkv"


def _transcode_args(transcode: TranscodeConfig) -> list[str]:
    codec_args = {
        "h264": ["-c:v", "libx264", "-preset", transcode.preset, "-pix_fmt", "yuv420p"],
        "hevc": ["-c:v", "libx265", "-preset", transcode.preset, "-pix_fmt", "yuv420p"],
        "av1": ["-c:v", "libsvtav1", "-preset", transcode.preset, "-pix_fmt", "yuv420p"],
    }[transcode.codec]

    video_bitrate = f"{transcode.video_bitrate_kbps}k"
    audio_bitrate = f"{transcode.audio_bitrate_kbps}k"
    return [
        *codec_args,
        "-b:v",
        video_bitrate,
        "-maxrate",
        video_bitrate,
        "-bufsize",
        f"{transcode.video_bitrate_kbps * 2}k",
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
    ]


def _redact_arg(arg: str) -> str:
    if "rtmp://" not in arg and "rtmps://" not in arg:
        return arg

    parts = []
    for target in arg.split("|"):
        if "/" not in target:
            parts.append(target)
            continue
        prefix, _key = target.rsplit("/", 1)
        parts.append(f"{prefix}/***")
    return "|".join(parts)
