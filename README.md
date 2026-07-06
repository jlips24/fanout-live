# Remote Multi-Streamer

A lightweight RTMP relay for sending one OBS stream to multiple platforms.

The intended setup is:

1. OBS streams once to a small computer on a faster connection.
2. This app listens for that RTMP stream.
3. Pipelines copy or transcode the incoming audio/video to destinations like Twitch and YouTube.

That keeps your home upload usage to one stream while the remote host does the outbound fan-out. Direct-copy pipelines stay very lightweight; transcode pipelines need more CPU/GPU depending on codec and resolution.

## Requirements

- Python 3.11 or newer
- FFmpeg with RTMP support
- TCP port `1935` reachable from your OBS computer

On Ubuntu/Debian:

```bash
sudo apt update
sudo apt install ffmpeg python3
```

## Docker

Build and start the web UI plus RTMP relay controller:

```bash
mkdir -p data
docker compose up -d --build
```

Then open:

```text
http://RELAY_PUBLIC_IP:8080
```

The compose setup publishes:

- `8080/tcp` for the web UI
- `1935/tcp` for OBS RTMP ingest

When the app starts, it also starts the RTMP source listener automatically if a
source is enabled. Pipelines are not required just to connect OBS.

It stores the editable config at:

```text
data/config.toml
```

OBS settings for the Docker setup are the same:

- Service: `Custom...`
- Server: `rtmp://RELAY_PUBLIC_IP:1935/live`
- Stream Key: copy the generated OBS key from the dashboard

You can also run it directly with Docker:

```bash
docker build -t remote-multistreamer .
docker run --rm \
  -p 1935:1935 \
  -p 8080:8080 \
  -v "$PWD/data:/config" \
  remote-multistreamer
```

## Make Targets

Common workflows are wrapped in `make` targets:

```bash
make help
make init
make deps-dev
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
make docker-build IMAGE=remote-multistreamer TAG=dev
```

## Web UI

Start the web app:

```bash
python3 -m remote_multistreamer --web --config config.toml --web-host 0.0.0.0 --web-port 8080
```

Then open:

```text
http://RELAY_PUBLIC_IP:8080
```

The web UI can:

- Show whether the relay is stopped, waiting, or receiving input
- Show configured pipelines on the main dashboard
- Enable, disable, and edit pipelines
- Configure sources, destinations, and FFmpeg settings in Settings
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

By default, the app starts with one OBS RTMP source and no destinations or pipelines. Add destinations first, then create pipelines that use them.

The OBS source stream key is generated automatically, stored in the persistent config file, and can be revealed or copied from the dashboard. Rotate it from Settings if it ever leaks.

Example pipeline setup:

- `YouTube Direct`: copy the incoming stream directly to a YouTube destination
- `Twitch H.264`: transcode to H.264 at 6000 Kbps, then send to a Twitch destination
- `Local Recording`: copy the incoming stream to a file destination such as `/config/recordings`

File destinations write timestamped Matroska segments. In Docker, `/config/recordings`
is persisted on the host at `./data/recordings`.

Only one active RTMP source is supported per relay process right now, but multiple pipelines can use that same source.

## Manual Configure

Copy the sample config:

```bash
cp config.example.toml config.toml
```

For Twitch and YouTube, the web UI can store the stream key directly. If you prefer environment variables in a manually edited config, set them on the relay machine:

```bash
export TWITCH_STREAM_KEY="live_..."
export YOUTUBE_STREAM_KEY="xxxx-xxxx-xxxx-xxxx"
```

Environment variable references such as `${YOUTUBE_STREAM_KEY}` are still supported in saved config files.

## Run

```bash
python3 -m remote_multistreamer --config config.toml
```

OBS settings:

- Service: `Custom...`
- Server: `rtmp://RELAY_PUBLIC_IP:1935/live`
- Stream Key: copy the generated OBS key from the dashboard

If the relay and OBS are on the same LAN during testing, use the relay computer's local IP instead of the public IP.

## Bitrate Notes

This relay does not transcode. If OBS sends 8 Mbps, your home uploads 8 Mbps once. The relay machine uploads about 16 Mbps total for Twitch plus YouTube, plus protocol overhead.

Recommended first OBS settings for standard 16:9 streaming:

- Canvas/output: `1920x1080` or `1280x720`
- FPS: `60` or `30`
- Video bitrate: `6000 Kbps` for Twitch compatibility
- Keyframe interval: `2 seconds`
- Audio: `160 Kbps` or `192 Kbps`

YouTube can accept higher bitrates, but Twitch compatibility usually makes `6000 Kbps` a good first shared setting.

## Install as a Linux Service

Edit `deploy/remote-multistreamer.service` and adjust:

- `WorkingDirectory`
- `--web-host` if the UI should only bind to a private VPN address

Then:

```bash
sudo cp deploy/remote-multistreamer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now remote-multistreamer
sudo journalctl -u remote-multistreamer -f
```

## Security

The RTMP listener accepts a fixed path from `config.toml`. Keep the stream name/key private, and avoid exposing port `1935` broadly unless you trust the network path. The web UI currently has no authentication, so bind it to `127.0.0.1` or a private VPN address unless the machine is already protected. A VPN such as Tailscale is a good next step before putting this on the open internet.
