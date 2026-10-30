# Build from the repository root:  docker build -f services/payment_service/Dockerfile .
# Maintained Debian-based Python image; the dependency pins are verified on Python 3.12.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

# Dependencies first (cached layer), then the shared package, then this component's code.
COPY services/payment_service/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY shared /tmp/shared
RUN pip install --no-deps /tmp/shared && rm -rf /tmp/shared

COPY services/payment_service/app ./app
# Migrations ship with the image and run as a one-off job with the migration user
# (the *_migrate services in docker-compose.yml), never when the service starts.
COPY services/payment_service/alembic.ini ./alembic.ini
COPY services/payment_service/migrations ./migrations

# Unprivileged runtime user without a login shell; the code stays owned by root (read-only).
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin shopease
USER 10001

EXPOSE 8005
# Liveness only; Compose adds a readiness check (database reachable) for business services.
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8005/health', timeout=2)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8005", "--no-access-log"]
