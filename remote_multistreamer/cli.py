from __future__ import annotations

import argparse
import signal
import subprocess
import sys
from pathlib import Path

from .config import ConfigError, load_config
from .config_store import ensure_config_file
from .ffmpeg import build_ffmpeg_command, prepare_file_destinations, redact_command
from .web import run_web_server


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="remote-multistreamer",
        description="Accept one RTMP stream and rebroadcast it to configured RTMP destinations.",
    )
    parser.add_argument(
        "--config",
        default="config.toml",
        type=Path,
        help="Path to TOML config file. Defaults to ./config.toml.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated ffmpeg command without starting the relay.",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Create the config file with generated defaults, then exit.",
    )
    parser.add_argument(
        "--web",
        action="store_true",
        help="Start the web UI instead of starting the relay immediately.",
    )
    parser.add_argument(
        "--web-host",
        default="127.0.0.1",
        help="Web UI bind address. Defaults to 127.0.0.1.",
    )
    parser.add_argument(
        "--web-port",
        default=8080,
        type=int,
        help="Web UI port. Defaults to 8080.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    if args.init_config:
        config = ensure_config_file(args.config)
        print(f"Config ready: {args.config}")
        if config.get("sources"):
            print(f"Generated OBS stream key for source: {config['sources'][0]['name']}")
        return 0

    if args.web:
        run_web_server(args.config, args.web_host, args.web_port)
        return 0

    try:
        config = load_config(args.config)
        command = build_ffmpeg_command(config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2

    print("Ingest URL for OBS:")
    active_source = _active_source_name_for_display(config)
    print(f"  {active_source.public_url}")
    print("OBS stream key:")
    print(f"  {active_source.stream}")
    print("Enabled pipelines:")
    if config.enabled_pipelines:
        for pipeline in config.enabled_pipelines:
            destination = config.destination_by_id(pipeline.destination_id)
            mode = (
                "copy"
                if not pipeline.transcodes
                else f"transcode to {pipeline.transcodes[-1].codec}"
            )
            print(f"  - {pipeline.name}: {mode} -> {destination.name} ({destination.redacted_url})")
    else:
        print("  none; accepting the source stream without rebroadcasting")
    print()
    print("ffmpeg command:")
    print(f"  {' '.join(redact_command(command))}")

    if args.dry_run:
        return 0

    prepare_file_destinations(config)
    process = subprocess.Popen(command)

    def stop_process(signum: int, _frame: object) -> None:
        print(f"Received signal {signum}; stopping relay...", file=sys.stderr)
        process.terminate()

    signal.signal(signal.SIGINT, stop_process)
    signal.signal(signal.SIGTERM, stop_process)

    return process.wait()


def _active_source_name_for_display(config):
    if config.enabled_pipelines:
        return config.source_by_id(config.enabled_pipelines[0].source_id)
    enabled_sources = [source for source in config.sources if source.enabled]
    return enabled_sources[0]
