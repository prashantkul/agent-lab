#!/bin/bash
set -e

# Default to 8000 if PORT not set
PORT="${PORT:-8000}"

echo "=== Starting Application ==="
echo "PORT: $PORT"
echo "DATABASE_URL is set: $([ -n "$DATABASE_URL" ] && echo 'yes' || echo 'no')"

echo "=== Running migrations ==="
alembic upgrade head

echo "=== Starting uvicorn ==="
exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --log-level debug
