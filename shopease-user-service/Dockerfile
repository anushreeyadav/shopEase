# ShopEase User Service
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
ENV APP_ENV=production \
    LOG_LEVEL=INFO

USER app

EXPOSE 8002

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=2).status == 200 else 1)"]

# Migrations finish before Uvicorn opens the port, and a failed migration stops the container.
# exec makes Uvicorn PID 1, so that it receives stop signals and shuts down cleanly.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8002"]
