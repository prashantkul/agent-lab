#!/bin/bash
set -e

echo "=== Starting Application ==="
echo "PORT env: $PORT"
echo "DATABASE_URL is set: $([ -n "$DATABASE_URL" ] && echo 'yes' || echo 'no')"

echo "=== Running migrations ==="
alembic upgrade head

echo "=== Starting uvicorn on port 8000 ==="
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --log-level debug
