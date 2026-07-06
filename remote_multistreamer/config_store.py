from __future__ import annotations

import secrets
import tomllib
from pathlib import Path
from typing import Any

from .config import ConfigError, parse_config

DEFAULT_CONFIG: dict[str, Any] = {
    "sources": [
        {
            "id": "obs",
            "name": "obs",
            "enabled": True,
            "host": "0.0.0.0",
            "port": 1935,
            "app": "live",
            "stream": "",
        }
    ],
    "ffmpeg": {
        "binary": "ffmpeg",
        "log_level": "info",
    },
    "destinations": [],
    "pipelines": [],
}


def load_raw_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _copy_default_config()

    with path.open("rb") as file:
        raw = tomllib.load(file)

    return normalize_config(raw)


def normalize_config(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError("Config must be a table.")

    raw = _migrate_legacy_config(raw)
    sources = [
        _normalize_source(item, index)
        for index, item in enumerate(raw.get("sources", []), 1)
    ]
    destinations = [
        _normalize_destination(item, index)
        for index, item in enumerate(raw.get("destinations", []), 1)
    ]
    normalized = {
        "sources": sources,
        "ffmpeg": _normalize_ffmpeg(raw.get("ffmpeg", {})),
        "destinations": destinations,
        "pipelines": [
            _normalize_pipeline(item, index, sources=sources, destinations=destinations)
            for index, item in enumerate(raw.get("pipelines", []), 1)
        ],
    }
    parse_config(normalized, expand_environment=False)
    return normalized


def save_raw_config(path: Path, raw: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize_config(raw)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_to_toml(normalized), encoding="utf-8")
    return normalized


def ensure_config_file(path: Path) -> dict[str, Any]:
    config = load_raw_config(path)
    if not path.exists():
        config = save_raw_config(path, config)
    return config


def rotate_source_stream_key(path: Path, source_id: str) -> dict[str, Any]:
    config = load_raw_config(path)
    for source in config["sources"]:
        if source["id"] == source_id:
            source["stream"] = generate_stream_key()
            return save_raw_config(path, config)
    raise ConfigError(f"Unknown source ID: {source_id}")


def generate_stream_key() -> str:
    return f"rms_{secrets.token_urlsafe(32)}"


def _migrate_legacy_config(raw: dict[str, Any]) -> dict[str, Any]:
    if "sources" in raw or "pipelines" in raw:
        return raw
    if "ingest" not in raw:
        return raw

    migrated = dict(raw)
    ingest = migrated.pop("ingest")
    destinations = migrated.get("destinations", [])
    migrated["sources"] = [{"id": "obs", "name": "obs", **ingest}]
    migrated["pipelines"] = [
        {
            "name": f"{destination.get('name', f'destination-{index}')}-direct",
            "enabled": destination.get("enabled", True),
            "source_id": "obs",
            "destination_id": destination.get(
                "id",
                destination.get("name", f"destination-{index}"),
            ),
            "transcodes": [],
        }
        for index, destination in enumerate(destinations, 1)
    ]
    return migrated


def _normalize_source(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"sources[{index}] must be a table.")
    stream = _optional_text(raw.get("stream", ""), f"sources[{index}].stream")
    if not stream:
        stream = generate_stream_key()
    return {
        "id": _text(
            raw.get("id", _default_id(raw.get("name", ""), "source", index)),
            f"sources[{index}].id",
        ),
        "name": _text(raw.get("name", ""), f"sources[{index}].name"),
        "enabled": _bool(raw.get("enabled", True), f"sources[{index}].enabled"),
        "host": _text(raw.get("host", "0.0.0.0"), f"sources[{index}].host"),
        "port": _port(raw.get("port", 1935), f"sources[{index}].port"),
        "app": _path_part(
            _text(raw.get("app", "live"), f"sources[{index}].app"),
            f"sources[{index}].app",
        ),
        "stream": _path_part(stream, f"sources[{index}].stream"),
    }


def _normalize_ffmpeg(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError("ffmpeg must be a table.")
    return {
        "binary": _text(raw.get("binary", "ffmpeg"), "ffmpeg.binary"),
        "log_level": _text(raw.get("log_level", "info"), "ffmpeg.log_level"),
    }


def _normalize_destination(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"destinations[{index}] must be a table.")

    name = _text(raw.get("name", ""), f"destinations[{index}].name")
    enabled = _bool(raw.get("enabled", True), f"destinations[{index}].enabled")
    service = _text(
        raw.get("service", _guess_service(raw)),
        f"destinations[{index}].service",
    ).lower()
    if service not in {"custom", "file", "twitch", "youtube"}:
        raise ConfigError(
            f"destinations[{index}].service must be custom, file, twitch, or youtube."
        )
    stream_key = _optional_text(raw.get("stream_key", ""), f"destinations[{index}].stream_key")
    url = _optional_text(raw.get("url", ""), f"destinations[{index}].url")
    if not stream_key and service in {"twitch", "youtube"}:
        stream_key = _stream_key_from_legacy_url(url, service)
    if service == "custom" and enabled and not url.startswith(("rtmp://", "rtmps://")):
        raise ConfigError(f"Destination '{name}' must use an RTMP or RTMPS URL.")
    if service == "file" and enabled and not url:
        raise ConfigError(f"Destination '{name}' needs a recording path.")
    return {
        "id": _text(
            raw.get("id", _default_id(raw.get("name", ""), "destination", index)),
            f"destinations[{index}].id",
        ),
        "name": name,
        "enabled": enabled,
        "service": service,
        "stream_key": stream_key,
        "url": url if service in {"custom", "file"} else "",
    }


def _normalize_pipeline(
    raw: Any,
    index: int,
    *,
    sources: list[dict[str, Any]],
    destinations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"pipelines[{index}] must be a table.")
    transcodes = raw.get("transcodes", [])
    if not isinstance(transcodes, list):
        raise ConfigError(f"pipelines[{index}].transcodes must be an array.")
    return {
        "name": _text(raw.get("name", ""), f"pipelines[{index}].name"),
        "enabled": _bool(raw.get("enabled", True), f"pipelines[{index}].enabled"),
        "source_id": _normalize_reference(
            raw,
            key="source_id",
            legacy_key="source",
            label=f"pipelines[{index}].source_id",
            items=sources,
        ),
        "destination_id": _normalize_reference(
            raw,
            key="destination_id",
            legacy_key="destination",
            label=f"pipelines[{index}].destination_id",
            items=destinations,
        ),
        "transcodes": [
            _normalize_transcode(item, transcode_index)
            for transcode_index, item in enumerate(transcodes, 1)
        ],
    }


def _normalize_transcode(raw: Any, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError(f"transcodes[{index}] must be a table.")
    codec = _text(raw.get("codec", "h264"), f"transcodes[{index}].codec").lower()
    if codec not in {"h264", "hevc", "av1"}:
        raise ConfigError(f"transcodes[{index}].codec must be h264, hevc, or av1.")
    return {
        "codec": codec,
        "video_bitrate_kbps": _port(
            raw.get("video_bitrate_kbps", 6000),
            f"transcodes[{index}].video_bitrate_kbps",
        ),
        "audio_bitrate_kbps": _port(
            raw.get("audio_bitrate_kbps", 160),
            f"transcodes[{index}].audio_bitrate_kbps",
        ),
        "preset": _text(raw.get("preset", "veryfast"), f"transcodes[{index}].preset"),
    }


def _copy_default_config() -> dict[str, Any]:
    sources = [dict(source) for source in DEFAULT_CONFIG["sources"]]
    for source in sources:
        if not source.get("stream"):
            source["stream"] = generate_stream_key()
    return {
        "sources": sources,
        "ffmpeg": dict(DEFAULT_CONFIG["ffmpeg"]),
        "destinations": [dict(destination) for destination in DEFAULT_CONFIG["destinations"]],
        "pipelines": [
            {
                **pipeline,
                "transcodes": [dict(transcode) for transcode in pipeline["transcodes"]],
            }
            for pipeline in DEFAULT_CONFIG["pipelines"]
        ],
    }


def _to_toml(config: dict[str, Any]) -> str:
    lines = [
        "[ffmpeg]",
        f"binary = {_toml_string(config['ffmpeg']['binary'])}",
        f"log_level = {_toml_string(config['ffmpeg']['log_level'])}",
        "",
    ]

    for source in config["sources"]:
        lines.extend(
            [
                "[[sources]]",
                f"id = {_toml_string(source['id'])}",
                f"name = {_toml_string(source['name'])}",
                f"enabled = {_toml_bool(source['enabled'])}",
                f"host = {_toml_string(source['host'])}",
                f"port = {source['port']}",
                f"app = {_toml_string(source['app'])}",
                f"stream = {_toml_string(source['stream'])}",
                "",
            ]
        )

    for destination in config["destinations"]:
        lines.extend(
            [
                "[[destinations]]",
                f"id = {_toml_string(destination['id'])}",
                f"name = {_toml_string(destination['name'])}",
                f"enabled = {_toml_bool(destination['enabled'])}",
                f"service = {_toml_string(destination['service'])}",
                f"stream_key = {_toml_string(destination['stream_key'])}",
                f"url = {_toml_string(destination['url'])}",
                "",
            ]
        )

    for pipeline in config["pipelines"]:
        lines.extend(
            [
                "[[pipelines]]",
                f"name = {_toml_string(pipeline['name'])}",
                f"enabled = {_toml_bool(pipeline['enabled'])}",
                f"source_id = {_toml_string(pipeline['source_id'])}",
                f"destination_id = {_toml_string(pipeline['destination_id'])}",
                "",
            ]
        )
        for transcode in pipeline["transcodes"]:
            lines.extend(
                [
                    "[[pipelines.transcodes]]",
                    f"codec = {_toml_string(transcode['codec'])}",
                    f"video_bitrate_kbps = {transcode['video_bitrate_kbps']}",
                    f"audio_bitrate_kbps = {transcode['audio_bitrate_kbps']}",
                    f"preset = {_toml_string(transcode['preset'])}",
                    "",
                ]
            )

    return "\n".join(lines)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{label} must be a non-empty string.")
    return value.strip()


def _optional_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a string.")
    return value.strip()


def _bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be true or false.")
    return value


def _port(value: Any, label: str) -> int:
    if not isinstance(value, int) or value < 1 or value > 65535:
        raise ConfigError(f"{label} must be a number from 1 to 65535.")
    return value


def _path_part(value: str, label: str) -> str:
    if "/" in value:
        raise ConfigError(f"{label} must not contain '/'.")
    return value


def _default_id(value: Any, prefix: str, index: int) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"{prefix}-{index}"


def _normalize_reference(
    raw: dict[str, Any],
    *,
    key: str,
    legacy_key: str,
    label: str,
    items: list[dict[str, Any]],
) -> str:
    if key in raw:
        return _text(raw[key], label)

    reference = _text(raw.get(legacy_key, ""), label)
    for item in items:
        if reference == item["id"] or reference == item["name"]:
            return item["id"]
    return reference


def _toml_bool(value: bool) -> str:
    return "true" if value else "false"


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _guess_service(raw: dict[str, Any]) -> str:
    service = raw.get("service")
    if isinstance(service, str) and service.strip():
        return service
    url = raw.get("url", "")
    if isinstance(url, str):
        if "live.twitch.tv/app/" in url:
            return "twitch"
        if "rtmp.youtube.com/live2/" in url:
            return "youtube"
    return "custom"


def _stream_key_from_legacy_url(url: str, service: str) -> str:
    if service == "twitch" and "live.twitch.tv/app/" in url:
        return url.rsplit("/", 1)[-1]
    if service == "youtube" and "rtmp.youtube.com/live2/" in url:
        return url.rsplit("/", 1)[-1]
    return ""
