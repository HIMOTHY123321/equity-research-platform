# Phase 16 (§78): production image for the FastAPI API process. The same
# image also runs the standalone worker (see app/worker.py) -- only the
# container CMD differs; see docker-compose.yml and docs/deployment.md.

FROM python:3.11-slim AS base

# psycopg (Postgres driver) needs libpq at runtime; build-essential only
# for its optional C extensions build step, removed from the final layer
# by using a single stage with --no-install-recommends and apt cleanup.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Never run as root in production.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')" || exit 1

# No --reload in production (§80). Override with `python -m app.worker`
# (or set WORKER_MODE=worker and keep this same CMD) to run the worker
# variant instead of the HTTP API.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
