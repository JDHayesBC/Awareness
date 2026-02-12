FROM python:3.12-slim

WORKDIR /app

COPY haven/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY haven/ /app/haven/

# Data directory for SQLite
RUN mkdir -p /app/data

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=5s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

CMD ["uvicorn", "haven.server:app", "--host", "0.0.0.0", "--port", "8000"]
