#!/bin/bash
# Smoke test Zomic: start server, hit endpoints, report, stop.
cd "$(dirname "$0")/.."
set -u
PORT="${PORT:-18080}"
LOG=/tmp/zomic-smoke.log
PORT="$PORT" IMAGE_CACHE_DIR=/tmp/zomic-smoke-cache .venv/bin/python app.py > "$LOG" 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
sleep 6

report() {
  for ep in "/" "/health" "/api/latest" "/api/popular" "/api/recommended" "/api/colored" "/api/genres" \
            "/api/catalog?page=1" "/api/catalog?page=1&type=manga" "/api/catalog?page=1&type=manhwa" \
            "/api/catalog?page=1&type=manhua" "/api/search?q=naruto" "/api/genre/action?page=1"; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 "http://localhost:$PORT$ep" 2>/dev/null)
    printf "%s -> %s\n" "$ep" "$CODE"
  done
}

report
echo "--- health body ---"
curl -s --max-time 20 "http://localhost:$PORT/health"
echo
echo "--- server log tail ---"
tail -8 "$LOG"