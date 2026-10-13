# syntax=docker/dockerfile:1

# --- Build: install locked dependencies into a virtualenv ----------------------------
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-install-project
COPY . .
RUN DJANGO_SETTINGS_MODULE=config.settings /app/.venv/bin/python manage.py collectstatic --noinput -v0

# --- Runtime: slim image, non-root user ------------------------------------------------
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN useradd --system --uid 10001 --home /app app
WORKDIR /app
COPY --from=build --chown=10001:10001 /app /app
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"
# The same image runs the worker: `python manage.py run_worker` (metrics on WORKER_METRICS_PORT).
CMD ["gunicorn", "config.wsgi", "-c", "gunicorn.conf.py"]
