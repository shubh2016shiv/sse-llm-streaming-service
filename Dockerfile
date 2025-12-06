# ============================================================================
# Multi-stage Dockerfile for SSE Streaming Microservice
# ============================================================================

FROM python:3.11-slim as base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Copy .env file if it exists (optional, as env vars can come from docker-compose)
COPY .env* ./

# Create logs directory
RUN mkdir -p /app/logs

# Set PYTHONPATH to /app so imports work correctly
ENV PYTHONPATH=/app

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')"

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "src.app:app", "--host", "0.0.0.0", "--port", "8000"]
