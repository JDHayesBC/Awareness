# Pattern Persistence System - MCP Server
# Provides semantic memory tools for Claude Code

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
COPY docker/requirements-docker.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt -r requirements-docker.txt

# Copy application code
COPY layers/ ./layers/
COPY server.py .
COPY docker/server_http.py .

# Create directories for mounted volumes
RUN mkdir -p /app/memories /app/data /app/journals /app/spaces /app/crystals

# Expose port for HTTP server
EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run HTTP wrapper (for Docker) instead of stdio
CMD ["python", "server_http.py"]
