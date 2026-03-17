# Stage 1 — build / install dependencies
FROM python:3.11-slim AS deps

WORKDIR /app

# Install dependencies only (layer caching)
COPY requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt


# Stage 2 — runtime image
FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="NCL Relay Server"
LABEL org.opencontainers.image.description="NUREALCORTEXLINK v3.0 event ingestion relay"
LABEL org.opencontainers.image.source="https://github.com/ResonanceEnergy/NCL"

WORKDIR /app

# Copy installed packages from deps stage
COPY --from=deps /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy application code
COPY . .

# Run as non-root user
RUN useradd --create-home --shell /bin/bash --uid 1001 ncl \
    && mkdir -p /data/event_log /data/quarantine /data/spool /data/memory \
    && chown -R ncl:ncl /app /data

USER ncl

# Expose relay port
EXPOSE 8787

# Health check — polls /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8787/health', timeout=4)"

# Environment defaults (override via docker run -e or docker-compose)
ENV NCL_DATA_DIR=/data \
    NCL_RELAY_HOST=0.0.0.0 \
    NCL_RELAY_PORT=8787 \
    NCL_API_KEYS_REQUIRED=false \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Default command: relay server
CMD ["python", "-m", "ncl_agency_runtime.runtime.relay_server", \
     "--host", "0.0.0.0", "--port", "8787"]
