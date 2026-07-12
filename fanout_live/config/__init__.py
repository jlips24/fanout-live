from __future__ import annotations

import os
import re
import secrets
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConfigError(Exception):
    """Raised when the relay configuration is invalid."""


ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True)
class SourceConfig:
    id: str
    name: str
    enabled: bool
    host: str
    port: int
    app: str
    stream: str

    @property
    def listen_url(self) -> str:
        return f"rtmp://{self.host}:{self.port}/{self.app}/{self.stream}"

    @property
    def public_url(self) -> str:
        host = "RELAY_PUBLIC_IP" if self.host == "0.0.0.0" else self.host
        return f"rtmp://{host}:{self.port}/{self.app}"


@dataclass(frozen=True)
class FfmpegConfig:
    binary: str
    log_level: str


@dataclass(frozen=True)
class DestinationConfig:
    id: str
    name: str
    enabled: bool
    service: str
    stream_key: str
    url: str

    @property
    def redacted_url(self) -> str:
        if self.service == "file":
            return self.url
        if "/" not in self.url:
            return self.url
        prefix, _key = self.url.rsplit("/", 1)
        return f"{prefix}/***"


@dataclass(frozen=True)
class TranscodeConfig:
    codec: str
    video_bitrate_kbps: int
    audio_bitrate_kbps: int
    preset: str


@dataclass(frozen=True)
class PanelConfig:
    title: str
    url: str
    enabled: bool = True
    columns: int = 6
    rows: int = 4
    order: int = 0


@dataclass(frozen=True)
class PipelineConfig:
    name: str
    enabled: bool
    source_id: str
    destination_id: str
    transcodes: tuple[TranscodeConfig, ...]
    panels: tuple[PanelConfig, ...] = ()


@dataclass(frozen=True)
class RelayConfig:
    ffmpeg: FfmpegConfig
    sources: tuple[SourceConfig, ...]
    destinations: tuple[DestinationConfig, ...]
    pipelines: tuple[PipelineConfig, ...]

    @property
    def enabled_pipelines(self) -> tuple[PipelineConfig, ...]:
        return tuple(pipeline for pipeline in self.pipelines if pipeline.enabled)

    def source_by_name(self, name: str) -> SourceConfig:
        for source in self.sources:
            if source.name == name:
                return source
        raise ConfigError(f"Unknown source: {name}")

    def source_by_id(self, id: str) -> SourceConfig:
        for source in self.sources:
            if source.id == id:
                return source
        raise ConfigError(f"Unknown source ID: {id}")

    def destination_by_name(self, name: str) -> DestinationConfig:
        for destination in self.destinations:
            if destination.name == name:
                return destination
        raise ConfigError(f"Unknown destination: {name}")

    def destination_by_id(self, id: str) -> DestinationConfig:
        for destination in self.destinations:
            if destination.id == id:
                return destination
        raise ConfigError(f"Unknown destination ID: {id}")


def load_config(
    path: Path, *, require_ready: bool = True, expand_environment: bool = True
) -> RelayConfig:
    if not path.exists():
        raise ConfigError(f"Config file not found: {path}")

    with path.open("rb") as file:
        raw = tomllib.load(file)

    config = parse_config(raw, expand_environment=expand_environment)
    if require_ready:
        _validate_ready(config)
    return config


def parse_config(raw: dict[str, Any], *, expand_environment: bool = True) -> RelayConfig:
    raw = _migrate_legacy_config(raw)
    ffmpeg = _parse_ffmpeg(raw.get("ffmpeg", {}))
    sources = _parse_sources(raw.get("sources", []))
    destinations = _parse_destinations(
        raw.get("destinations", []),
        expand_environment=expand_environment,
    )
    pipelines = _parse_pipelines(
        raw.get("pipelines", []),
        sources=sources,
        destinations=destinations,
    )
    config = RelayConfig(
        ffmpeg=ffmpeg,
        sources=sources,
        destinations=destinations,
        pipelines=pipelines,
    )
    _validate_references(config)
    return config


def _validate_ready(config: RelayConfig) -> None:
    enabled = config.enabled_pipelines
    if enabled:
        active_source_ids = {pipeline.source_id for pipeline in enabled}
    else:
        active_source_ids = {source.id for source in config.sources if source.enabled}

    if not active_source_ids:
        raise ConfigError("At least one source must be enabled.")
    if len(active_source_ids) > 1:
        raise ConfigError("Only one active RTMP source is supported per relay process right now.")

    source = config.source_by_id(next(iter(active_source_ids)))
    if not source.enabled:
        raise ConfigError(f"Source '{source.name}' must be enabled before starting the relay.")

    for pipeline in enabled:
        destination = config.destination_by_id(pipeline.destination_id)
        if not destination.enabled:
            raise ConfigError(
                f"Destination '{destination.name}' must be enabled before starting the relay."
            )
        if destination.service in {"twitch", "youtube"} and not destination.stream_key:
            raise ConfigError(
                f"Destination '{destination.name}' needs a stream key before starting the relay."
            )


def _validate_references(config: RelayConfig) -> None:
    source_ids = {source.id for source in config.sources}
    destination_ids = {destination.id for destination in config.destinations}

    for pipeline in config.pipelines:
        if pipeline.source_id not in source_ids:
            raise ConfigError(
                f"Pipeline '{pipeline.name}' references unknown source ID '{pipeline.source_id}'."
            )
        if pipeline.destination_id not in destination_ids:
            raise ConfigError(
                f"Pipeline '{pipeline.name}' references unknown destination ID "
                f"'{pipeline.destination_id}'."
            )


def _migrate_legacy_config(raw: dict[str, Any]) -> dict[str, Any]:
    if "sources" in raw or "pipelines" in raw:
        return raw

    if "ingest" not in raw:
        return raw

    migrated = dict(raw)
    ingest = migrated.pop("ingest")
    destinations = migrated.get("destinations", [])
    migrated["sources"] = [{"name": "obs", **ingest}]
    migrated["pipelines"] = [
        {
            "name": f"{destination.get('name', f'destination-{index}')}-direct",
            "enabled": destination.get("enabled", True),
            "source": "obs",
            "destination": destination.get("name", f"destination-{index}"),
            "transcodes": [],
        }
        for index, destination in enumerate(destinations, 1)
    ]
    return migrated


def _parse_sources(raw: list[dict[str, Any]]) -> tuple[SourceConfig, ...]:
    if not isinstance(raw, list):
        raise ConfigError("sources must be a TOML array of tables.")

    sources: list[SourceConfig] = []
    for index, item in enumerate(raw, start=1):
        context = f"sources[{index}]"
        sources.append(
            SourceConfig(
                id=_string(
                    item,
                    "id",
                    default=_string(item, "name", context=context),
                    context=context,
                ),
                name=_string(item, "name", context=context),
                enabled=_boolean(item, "enabled", default=True, context=context),
                host=_string(item, "host", default="0.0.0.0", context=context),
                port=_integer(item, "port", default=1935, context=context),
                app=_path_part(
                    _string(item, "app", default="live", context=context),
                    f"{context}.app",
                ),
                stream=_path_part(_source_stream(item), f"{context}.stream"),
            )
        )
    _validate_unique_ids("sources", [source.id for source in sources])
    _validate_unique_names("sources", [source.name for source in sources])
    return tuple(sources)


def _parse_ffmpeg(raw: dict[str, Any]) -> FfmpegConfig:
    binary = _string(raw, "binary", default="ffmpeg")
    log_level = _string(raw, "log_level", default="info")
    return FfmpegConfig(binary=binary, log_level=log_level)


def _parse_destinations(
    raw: list[dict[str, Any]], *, expand_environment: bool
) -> tuple[DestinationConfig, ...]:
    if not isinstance(raw, list):
        raise ConfigError("destinations must be a TOML array of tables.")

    destinations: list[DestinationConfig] = []
    for index, item in enumerate(raw, start=1):
        context = f"destinations[{index}]"
        name = _string(item, "name", context=context)
        enabled = _boolean(item, "enabled", default=True, context=context)
        service = _string(item, "service", default="custom", context=context).lower()
        if service not in {"custom", "file", "twitch", "youtube"}:
            raise ConfigError(f"{context}.service must be custom, file, twitch, or youtube.")
        stream_key = _string(item, "stream_key", default="", context=context, allow_empty=True)
        if expand_environment and stream_key:
            stream_key = _expand_env(stream_key)
        url = _destination_url(item, service, stream_key, context)
        if expand_environment:
            url = _expand_env(url)
        if enabled and service == "file" and not url:
            raise ConfigError(f"Destination '{name}' needs a recording path.")
        if enabled and service != "file" and not url.startswith(("rtmp://", "rtmps://")):
            raise ConfigError(f"Destination '{name}' must use an RTMP or RTMPS URL.")
        destinations.append(
            DestinationConfig(
                id=_string(item, "id", default=name, context=context),
                name=name,
                enabled=enabled,
                service=service,
                stream_key=stream_key,
                url=url,
            )
        )

    _validate_unique_ids("destinations", [destination.id for destination in destinations])
    _validate_unique_names("destinations", [destination.name for destination in destinations])
    return tuple(destinations)


def _parse_pipelines(
    raw: list[dict[str, Any]],
    *,
    sources: tuple[SourceConfig, ...],
    destinations: tuple[DestinationConfig, ...],
) -> tuple[PipelineConfig, ...]:
    if not isinstance(raw, list):
        raise ConfigError("pipelines must be a TOML array of tables.")

    pipelines: list[PipelineConfig] = []
    for index, item in enumerate(raw, start=1):
        context = f"pipelines[{index}]"
        transcodes = item.get("transcodes", [])
        if not isinstance(transcodes, list):
            raise ConfigError(f"{context}.transcodes must be an array.")
        panels = item.get("panels", [])
        if not isinstance(panels, list):
            raise ConfigError(f"{context}.panels must be an array.")
        pipelines.append(
            PipelineConfig(
                name=_string(item, "name", context=context),
                enabled=_boolean(item, "enabled", default=True, context=context),
                source_id=_reference_id(
                    item,
                    "source_id",
                    "source",
                    items=sources,
                    context=context,
                ),
                destination_id=_reference_id(
                    item,
                    "destination_id",
                    "destination",
                    items=destinations,
                    context=context,
                ),
                transcodes=tuple(
                    _parse_transcode(transcode, f"{context}.transcodes[{transcode_index}]")
                    for transcode_index, transcode in enumerate(transcodes, 1)
                ),
                panels=tuple(
                    _parse_panel(panel, f"{context}.panels[{panel_index}]")
                    for panel_index, panel in enumerate(panels, 1)
                ),
            )
        )
    _validate_unique_names("pipelines", [pipeline.name for pipeline in pipelines])
    return tuple(pipelines)


def _parse_transcode(raw: dict[str, Any], context: str) -> TranscodeConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{context} must be a table.")
    codec = _string(raw, "codec", context=context).lower()
    if codec not in {"h264", "hevc", "av1"}:
        raise ConfigError(f"{context}.codec must be h264, hevc, or av1.")
    return TranscodeConfig(
        codec=codec,
        video_bitrate_kbps=_integer(raw, "video_bitrate_kbps", default=6000, context=context),
        audio_bitrate_kbps=_integer(raw, "audio_bitrate_kbps", default=160, context=context),
        preset=_string(raw, "preset", default="veryfast", context=context),
    )


def _parse_panel(raw: dict[str, Any], context: str) -> PanelConfig:
    if not isinstance(raw, dict):
        raise ConfigError(f"{context} must be a table.")
    url = _string(raw, "url", context=context)
    if not url.startswith(("http://", "https://")):
        raise ConfigError(f"{context}.url must start with http:// or https://.")
    return PanelConfig(
        title=_string(raw, "title", default="Panel", context=context),
        url=url,
        enabled=_boolean(raw, "enabled", default=True, context=context),
        columns=_bounded_integer(raw, "columns", default=6, minimum=1, maximum=12, context=context),
        rows=_bounded_integer(raw, "rows", default=4, minimum=1, maximum=6, context=context),
        order=_bounded_integer(raw, "order", default=0, minimum=0, maximum=10000, context=context),
    )


def _bounded_integer(
    raw: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
    context: str | None = None,
) -> int:
    value = raw.get(key, default)
    if not isinstance(value, int) or value < minimum or value > maximum:
        raise ConfigError(f"{_label(context, key)} must be a number from {minimum} to {maximum}.")
    return value


def _expand_env(value: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ConfigError(f"Environment variable is required but not set: {name}")
        return os.environ[name]

    return ENV_PATTERN.sub(replace, value)


def _source_stream(raw: dict[str, Any]) -> str:
    stream = _string(raw, "stream", default="", allow_empty=True)
    return stream or f"rms_{secrets.token_urlsafe(32)}"


def _destination_url(raw: dict[str, Any], service: str, stream_key: str, context: str) -> str:
    if service == "twitch":
        return f"rtmp://live.twitch.tv/app/{stream_key}"
    if service == "youtube":
        return f"rtmp://a.rtmp.youtube.com/live2/{stream_key}"
    return _string(raw, "url", context=context, allow_empty=True)


def _string(
    raw: dict[str, Any],
    key: str,
    *,
    default: str | None = None,
    context: str | None = None,
    allow_empty: bool = False,
) -> str:
    if key not in raw:
        if default is not None:
            return default
        raise ConfigError(f"Missing required setting: {_label(context, key)}")
    value = raw[key]
    if not isinstance(value, str):
        raise ConfigError(f"{_label(context, key)} must be a string.")
    if not allow_empty and not value.strip():
        raise ConfigError(f"{_label(context, key)} must be a non-empty string.")
    return value.strip()


def _integer(raw: dict[str, Any], key: str, *, default: int, context: str | None = None) -> int:
    value = raw.get(key, default)
    if not isinstance(value, int) or value < 1 or value > 65535:
        raise ConfigError(f"{_label(context, key)} must be a number from 1 to 65535.")
    return value


def _boolean(
    raw: dict[str, Any], key: str, *, default: bool, context: str | None = None
) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{_label(context, key)} must be true or false.")
    return value


def _reference_id(
    raw: dict[str, Any],
    key: str,
    legacy_key: str,
    *,
    items: tuple[SourceConfig, ...] | tuple[DestinationConfig, ...],
    context: str | None = None,
) -> str:
    if key in raw:
        return _string(raw, key, context=context)
    reference = _string(raw, legacy_key, context=context)
    for item in items:
        if reference == item.id or reference == item.name:
            return item.id
    return reference


def _path_part(value: str, label: str) -> str:
    if "/" in value:
        raise ConfigError(f"{label} must not contain '/'.")
    return value


def _validate_unique_names(label: str, names: list[str]) -> None:
    if len(names) != len(set(names)):
        raise ConfigError(f"{label} names must be unique.")


def _validate_unique_ids(label: str, ids: list[str]) -> None:
    if len(ids) != len(set(ids)):
        raise ConfigError(f"{label} IDs must be unique.")


def _label(context: str | None, key: str) -> str:
    return f"{context}.{key}" if context else key
