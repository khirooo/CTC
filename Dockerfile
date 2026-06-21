# Backend image — shared by both Python services (proxy + control-plane).
# docker-compose runs it twice with different commands.
FROM python:3.12-slim

# No .pyc, unbuffered logs.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install runtime deps first (better layer caching).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Application code (only what the servers need at runtime).
COPY ctc/ ./ctc/
COPY proxy.py api_server.py ./

# Run as a non-root user. Pre-create the volume mountpoints owned by ctc so the
# named volumes (ctcdata:/data, ctccerts:/certs) inherit ctc ownership when Docker
# first initializes them from the image — otherwise they're created root-owned and
# the non-root process can't open/create the SQLite DB at /data/ctc.db.
RUN useradd --create-home --uid 10001 ctc \
 && mkdir -p /data /certs \
 && chown -R ctc:ctc /app /data /certs
USER ctc

# Default command is overridden per-service in docker-compose.yml.
CMD ["python", "api_server.py"]
