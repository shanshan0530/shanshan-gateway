#!/usr/bin/env bash
set -euo pipefail

mkdir -p "${OMBRE_BUCKETS_DIR:-/app/data/buckets}" "${OMBRE_STATE_DIR:-/app/data/state}"
python /app/generate_config.py

envsubst '${PORT}' < /app/nginx.conf.template > /tmp/nginx.conf

cd /app/ombre
python server.py &
BRAIN_PID=$!
python gateway.py &
GATEWAY_PID=$!
nginx -c /tmp/nginx.conf -g 'daemon off;' &
NGINX_PID=$!

cleanup() {
  kill "$BRAIN_PID" "$GATEWAY_PID" "$NGINX_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null \
    && curl -fsS http://127.0.0.1:8010/health >/dev/null; then
    echo "Ombre Brain and Gateway are ready"
    break
  fi
  if ! kill -0 "$BRAIN_PID" 2>/dev/null || ! kill -0 "$GATEWAY_PID" 2>/dev/null; then
    echo "Ombre process exited during startup" >&2
    exit 1
  fi
  sleep 2
done

wait -n "$BRAIN_PID" "$GATEWAY_PID" "$NGINX_PID"
