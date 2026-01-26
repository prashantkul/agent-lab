# Deploying to Railway

## Prerequisites

- GitHub repository with your code
- Railway account linked to GitHub

## Required Files

### 1. Dockerfile

```dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8000

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Make startup script executable
RUN chmod +x start.sh

EXPOSE 8000

CMD ["./start.sh"]
```

### 2. start.sh

```bash
#!/bin/bash
set -e

echo "=== Starting Application ==="
echo "PORT: $PORT"

echo "=== Running migrations ==="
alembic upgrade head

echo "=== Starting uvicorn ==="
exec uvicorn app.main:app --host 0.0.0.0 --port $PORT --log-level info
```

### 3. railway.toml

```toml
[build]
builder = "dockerfile"

[deploy]
healthcheckPath = "/health"
healthcheckTimeout = 100
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
```

**Important:** Set `builder = "dockerfile"` explicitly to avoid conflicts with nixpacks.

### 4. Health Check Endpoint

Your app must have a `/health` endpoint:

```python
@app.get("/health")
async def health_check():
    return {"status": "healthy"}
```

## Environment Variables

Set these in Railway dashboard (Settings → Variables):

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | Railway provides this automatically when you add PostgreSQL |
| `SECRET_KEY` | Random string for session encryption |
| `GOOGLE_CLIENT_ID` | OAuth credentials |
| `GOOGLE_CLIENT_SECRET` | OAuth credentials |
| `GOOGLE_REDIRECT_URI` | `https://<your-app>.up.railway.app/auth/google/callback` |

**Note:** Railway automatically injects `PORT` at runtime - you don't need to set it manually.

## Deployment Steps

1. **Create Railway Project**
   - Go to [railway.app](https://railway.app)
   - Create new project → Deploy from GitHub repo

2. **Add PostgreSQL**
   - Click "New" → "Database" → "PostgreSQL"
   - Railway auto-creates `DATABASE_URL` variable

3. **Set Environment Variables**
   - Go to your service → Variables tab
   - Add all required variables from table above

4. **Deploy**
   - Railway auto-deploys on push to main
   - Or click "Deploy" button manually

## Common Issues

### Issue: `${PORT:-8000}` is not a valid integer

**Cause:** Custom Start Command set in Railway UI overrides Dockerfile CMD.

**Fix:**
1. Go to Settings → Deploy section
2. Clear the "Custom Start Command" field
3. Redeploy

### Issue: Build uses cached layers

**Cause:** Railway aggressively caches Docker layers.

**Fix:**
1. Go to Settings → Build section
2. Click "Clear build cache"
3. Redeploy

### Issue: Health check failing

**Cause:** App not starting within timeout.

**Fix:**
1. Check deploy logs for actual error
2. Ensure `/health` endpoint exists
3. Increase `healthcheckTimeout` in railway.toml

### Issue: Migrations not running

**Cause:** Using Procfile or nixpacks instead of Dockerfile.

**Fix:**
1. Ensure `builder = "dockerfile"` in railway.toml
2. Delete Procfile if it exists
3. Run migrations in start.sh before uvicorn

## Debugging

1. **Build Logs** - Show Docker build process
2. **Deploy Logs** - Show runtime output (start.sh echo statements, uvicorn startup)

Add verbose logging to start.sh to debug issues:
```bash
echo "PORT: $PORT"
echo "DATABASE_URL is set: $([ -n "$DATABASE_URL" ] && echo 'yes' || echo 'no')"
```

## Reference

Based on working deployment pattern from `help-math` backend.
