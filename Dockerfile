# Dockerfile — Athena Assistant
# Multi-stage aware single-stage build.
# Targets Python 3.11-slim for a lightweight image.
# Build args allow overriding Python version for Raspberry Pi / ARM.

ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

# Create a non-root user for security
RUN groupadd -r athena && useradd -r -g athena athena

WORKDIR /app

# Install dependencies in a cached layer before copying source
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source (respect .dockerignore)
COPY . .

# Create runtime directories and set ownership
RUN mkdir -p logs audit data/carddav_staged && \
    chown -R athena:athena /app

# Drop to non-root
USER athena

EXPOSE 8000

# Use exec form so uvicorn receives signals properly (graceful shutdown)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
