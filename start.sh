#!/bin/bash
set -e

echo "=== Starting Application ==="
echo "PORT: ${PORT:-8000}"
echo "DATABASE_URL is set: $([ -n "$DATABASE_URL" ] && echo 'yes' || echo 'no')"

echo "=== Running migrations ==="
alembic upgrade head

echo "=== Starting uvicorn ==="
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level debug
