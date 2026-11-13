# ShopEase Product Catalog Service
# Build and run with the database:  docker compose up --build

FROM python:3.11-slim-bookworm

# No .pyc files, unbuffered logs, no pip cache or version check in the image.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: this layer is reused until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Unprivileged user that owns nothing it could modify.
RUN groupadd --system app && useradd --system --gid app --no-create-home app

# Application and migration code only; .dockerignore keeps .env, .venv, caches and Git data out.
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini .

# Container defaults. Secrets have no defaults and must be supplied at run time.
# 0.0.0.0 inside the container, so that the published port reaches the service.
ENV APP_ENV=production \
    LOG_LEVEL=INFO \
    SERVICE_HOST=0.0.0.0 \
    SERVICE_PORT=8006

USER app

EXPOSE 8006

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ['SERVICE_PORT'], timeout=2).status == 200 else 1)"]

# Start-up, each step only if the previous one succeeded:
#   1. wait until MySQL accepts this service's user (up to 60 s; Compose also waits for its health check)
#   2. apply pending migrations (a failed migration stops the container before the port opens)
#   3. start the server; exec makes Python PID 1, so it receives stop signals and shuts down cleanly
CMD ["sh", "-c", "python -m app.database.wait --timeout 60 && alembic upgrade head && exec python -m app"]
