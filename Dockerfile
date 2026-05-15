FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency files first to maximise layer cache reuse
COPY requirements.txt pyproject.toml README.md ./

# Install Python dependencies (cached unless requirements change)
RUN pip install --no-cache-dir -r requirements.txt && pip install --no-cache-dir -e .

# Copy application code (layer invalidated only when code changes)
COPY runtime/ ./runtime/

# Create data directories
RUN mkdir -p /app/data/memory /app/config

# Run as non-root user for container security
RUN adduser --disabled-password --gecos '' appuser \
    && chown -R appuser:appuser /app
USER appuser

# Expose Brain API port
EXPOSE 8800

# Health check against the Brain API port
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8800/health || exit 1

# Run the NCL Brain service
CMD ["uvicorn", "runtime.api.routes:app", "--host", "0.0.0.0", "--port", "8800"]
