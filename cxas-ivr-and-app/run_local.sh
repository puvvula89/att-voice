#!/usr/bin/env bash
# Run the unified voice+chat client locally against the CXAS app.
#
#   bash run_local.sh
#   -> relay   on http://localhost:8000
#   -> UI      on http://localhost:8080/chat.html
#
# Uses ADC for the CXAS websocket, so run `gcloud auth application-default login`
# once first. Config comes from .env (VOICE_APP_ID / CXAS_PROJECT / CXAS_LOCATION).
set -euo pipefail
cd "$(dirname "$0")"

PY="${PY:-../cxas-to-adk-a2a/.venv/bin/python}"
[ -x "$PY" ] || { echo "python not found at $PY — set PY=/path/to/python"; exit 1; }
# Absolutise: the UI runs from frontend/, so a relative interpreter path breaks.
PY="$(cd "$(dirname "$PY")" && pwd)/$(basename "$PY")"

# The page talks to the relay over ws://localhost:8000.
printf 'window.RELAY_URL = "ws://localhost:8000";\n' > frontend/config.js

echo "starting relay on :8000"
"$PY" -m uvicorn backend.relay:app --host 127.0.0.1 --port 8000 &
RELAY_PID=$!
trap 'kill $RELAY_PID 2>/dev/null || true' EXIT

echo "starting UI on :8080"
( cd frontend && PORT=8080 "$PY" serve.py ) &
UI_PID=$!
trap 'kill $RELAY_PID $UI_PID 2>/dev/null || true' EXIT

echo
echo "open http://localhost:8080/chat.html"
echo "  · Generate a session id, press Start"
echo "  · tap the mic to talk, or just type — same session either way"
echo
wait
