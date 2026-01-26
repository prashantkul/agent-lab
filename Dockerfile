FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8000

# Run the application
CMD ["sh", "-c", "echo 'Running migrations...' && alembic upgrade head && echo 'Migrations done. Starting uvicorn on port ${PORT:-8000}...' && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level debug"]
