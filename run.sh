#!/bin/bash
# ── DataBro local dev server ──────────────────────────────────────────────────
# Usage: ./run.sh
# On Render/Railway $PORT is injected automatically

set -e

cd "$(dirname "$0")/backend"

# Load .env if present
if [ -f .env ]; then
  echo "Loading .env..."
  export $(grep -v '^#' .env | xargs)
fi

PORT=${PORT:-8000}
echo "Starting DataBro API on port $PORT..."
exec uvicorn main:app --host 0.0.0.0 --port "$PORT" --reload
