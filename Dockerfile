FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency manifests first for better layer caching
COPY pyproject.toml uv.lock ./

# Install production dependencies into the system Python (no venv needed in containers)
RUN uv sync --extra prod --no-dev --system

# Copy application source
COPY wsgi.py manage_users.py ./
COPY app/ app/

# Create non-root user matching the service account convention
RUN useradd --system --no-create-home --shell /sbin/nologin appuser \
    && mkdir -p /app/certs \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8100

CMD ["gunicorn", \
     "--workers", "2", \
     "--threads", "4", \
     "--worker-class", "gthread", \
     "--bind", "0.0.0.0:8100", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "wsgi:app"]
