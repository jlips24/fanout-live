# Fanout Live

Self-hosted live stream relay for homelabs. Send one OBS stream to Fanout Live,
then route it to Twitch, YouTube, recordings, or custom RTMP destinations from a
web UI.

Fanout Live is meant to run as a small Docker appliance on a machine with a good
upload connection:

1. OBS streams once to your Fanout Live host.
2. Fanout Live listens for that RTMP stream.
3. Pipelines copy or transcode the incoming audio/video to destinations like
   Twitch, YouTube, custom RTMP endpoints, and local recordings.

That keeps your OBS-side upload usage to one stream while the Fanout Live host
does the outbound fan-out. Direct-copy pipelines stay very lightweight;
transcode pipelines need more CPU/GPU depending on codec and resolution.

## What It Does

- Receives an OBS RTMP stream on port `1935`
- Provides a browser-based dashboard on port `8080`
- Routes one source stream to multiple destinations
- Supports Twitch, YouTube, custom RTMP/RTMPS destinations, and file recordings
- Stores editable configuration in a persistent `/config` volume
- Generates and rotates OBS source stream keys from the web UI

## Requirements

- Docker or Docker Compose
- TCP port `1935` reachable from your OBS computer
- TCP port `8080` reachable from your browser or private network

## Quick Start

Start a released Fanout Live image with Docker Compose:

```bash
mkdir -p data
FANOUT_LIVE_TAG=0.1.0 docker compose up -d
```

Replace `0.1.0` with the release tag you want to deploy or roll back to.

Then open:

```text
http://RELAY_PUBLIC_IP:8080
```

The Compose setup publishes:

- `8080/tcp` for the web UI
- `1935/tcp` for OBS RTMP ingest

When Fanout Live starts, it also starts the RTMP source listener automatically
if a source is enabled. Pipelines are not required just to connect OBS.

It stores the editable config at:

```text
data/config.toml
```

Point OBS at Fanout Live:

- Service: `Custom...`
- Server: `rtmp://RELAY_PUBLIC_IP:1935/live`
- Stream Key: copy the generated OBS key from the dashboard

If OBS and Fanout Live are on the same LAN during testing, use the Fanout Live
host's local IP instead of the public IP.

## Docker

Build and run the image directly:

```bash
docker build -t fanout-live .
docker run --rm \
  -p 1935:1935 \
  -p 8080:8080 \
  -v "$PWD/data:/config" \
  fanout-live
```

For a published image, the intended deployment shape is:

```yaml
services:
  remote-multistreamer:
    image: ghcr.io/YOUR_GITHUB_USERNAME/fanout-live:${FANOUT_LIVE_TAG:?Set FANOUT_LIVE_TAG to a released version}
    container_name: remote-multistreamer
    restart: unless-stopped
    ports:
      - "1935:1935"
      - "8080:8080"
    volumes:
      - ./data:/config
```

## Web UI

The web UI can:

- Show whether the relay is stopped, waiting, or receiving input
- Show configured pipelines on the main dashboard
- Enable, disable, and edit pipelines
- Configure sources, destinations, and FFmpeg settings
- Add Twitch or YouTube destinations with just a stream key
- Add custom RTMP/RTMPS destinations with a full URL
- Add file destinations that record the incoming stream to disk
- Reveal, copy, and rotate generated OBS source stream keys
- Save the config file
- Start and stop the relay process

## Pipelines

A pipeline has:

- A source, such as the OBS RTMP listener
- Optional transcodes, such as H.264 at 6000 Kbps
- A destination, such as Twitch or YouTube

By default, Fanout Live starts with one OBS RTMP source and no destinations or
pipelines. Add destinations first, then create pipelines that use them.

The OBS source stream key is generated automatically, stored in the persistent
config file, and can be revealed or copied from the dashboard. Rotate it from
Settings if it ever leaks.

Example pipeline setup:

- `YouTube Direct`: copy the incoming stream directly to a YouTube destination
- `Twitch H.264`: transcode to H.264 at 6000 Kbps, then send to a Twitch destination
- `Local Recording`: copy the incoming stream to a file destination such as `/config/recordings`

File destinations write timestamped Matroska segments. In Docker,
`/config/recordings` is persisted on the host at `./data/recordings`.

Only one active RTMP source is supported per relay process right now, but
multiple pipelines can use that same source.

## Bitrate Notes

If OBS sends 8 Mbps, your OBS-side network uploads 8 Mbps once. The Fanout Live
host uploads about 16 Mbps total for Twitch plus YouTube, plus protocol
overhead.

Recommended first OBS settings for standard 16:9 streaming:

- Canvas/output: `1920x1080` or `1280x720`
- FPS: `60` or `30`
- Video bitrate: `6000 Kbps` for Twitch compatibility
- Keyframe interval: `2 seconds`
- Audio: `160 Kbps` or `192 Kbps`

YouTube can accept higher bitrates, but Twitch compatibility usually makes
`6000 Kbps` a good first shared setting.

## Security

The RTMP listener accepts a fixed path and stream key from the config file. Keep
the stream key private, and avoid exposing port `1935` broadly unless you trust
the network path.

The web UI currently has no authentication, so bind it to a private network,
VPN, or reverse proxy with authentication before exposing it outside your
homelab. A VPN such as Tailscale is a good next step before putting the
dashboard on the open internet.

## Development

For local development, install Python 3.11 or newer and FFmpeg with RTMP
support. Common workflows are wrapped in `make` targets:

```bash
make lint
make test
make check
make run-web
make docker-up
make docker-logs
make docker-down
```

Useful overrides:

```bash
make run-web WEB_PORT=9090
make dry-run CONFIG=data/config.toml
make docker-build IMAGE=fanout-live TAG=dev
make docker-up FANOUT_LIVE_TAG=0.1.0
```

The web UI is the preferred way to edit configuration. The persisted config is
stored at `data/config.toml` when using the default Compose setup.
