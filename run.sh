#!/usr/bin/env bash
# Start the Robocall TCPA Logger locally.
set -euo pipefail

HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

echo "Starting Robocall TCPA Logger on http://${HOST}:${PORT}"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload
