FROM python:3.12-slim

WORKDIR /app

COPY haven/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY haven/ /app/haven/

# Data directory for SQLite
RUN mkdir -p /app/data

# Entrypoint gate: waits for WSL2 NTFS mount before starting (Issue #169)
COPY haven/docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
