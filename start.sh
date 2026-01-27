#!/bin/bash
set -e

echo "=== Starting Application ==="
echo "PORT: $PORT"
echo "DATABASE_URL is set: $([ -n "$DATABASE_URL" ] && echo 'yes' || echo 'no')"

echo "=== Running migrations ==="
alembic upgrade head

echo "=== Starting uvicorn on port $PORT ==="
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --log-level info
