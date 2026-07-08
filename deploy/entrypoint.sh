#!/bin/sh
set -eu

mkdir -p /config/logs /config/preview /config/recordings

nginx -c /etc/nginx/nginx.conf -g "daemon off;" &
NGINX_PID="$!"

python -m fanout_live --web --config /config/config.toml --web-host 0.0.0.0 --web-port 8080 &
PYTHON_PID="$!"

stop() {
    kill "$PYTHON_PID" "$NGINX_PID" 2>/dev/null || true
    wait "$PYTHON_PID" "$NGINX_PID" 2>/dev/null || true
}

trap stop INT TERM

wait "$PYTHON_PID"
stop
