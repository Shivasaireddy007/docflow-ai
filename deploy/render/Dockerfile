# syntax=docker/dockerfile:1
# The public demo: one container serving the API and the built review app, with its own
# PostgreSQL and Redis and the reviewed receipts loaded at start. Build from the repository root:
#   docker build -f deploy/render/Dockerfile .

FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN VITE_DEMO=true npm run build

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY backend/ ./
COPY --from=web /web/dist /app/web
RUN DJANGO_SETTINGS_MODULE=config.settings /app/.venv/bin/python manage.py collectstatic --noinput -v0

FROM python:3.12-slim
# Every visitor signs in as "demo", so the per-account sign-in limit is loosened.
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" \
    WEB_DIR=/app/web DEMO_MODE=true SECURE_COOKIES=true WEB_CONCURRENCY=2 \
    LOGIN_RATE=120/2
# PostgreSQL and Redis run inside the container: the demo reloads its data on every start, so
# nothing needs to outlive it, and it fits in a single free web service.
RUN apt-get update && apt-get install -y --no-install-recommends postgresql redis-server \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --system --uid 10001 --home /app app
WORKDIR /app
COPY --from=build --chown=10001:10001 /app /app
COPY --chmod=755 deploy/render/start.sh /start.sh
RUN install -d -o 10001 -g 10001 /app/.prometheus /app/.storage
USER 10001
EXPOSE 10000
CMD ["/start.sh"]
