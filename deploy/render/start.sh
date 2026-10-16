#!/bin/sh
# Starts the demo: its own PostgreSQL and Redis (unless DATABASE_URL or REDIS_URL point elsewhere),
# a fresh schema and data on every boot so visitors' reviews don't pile up, then the app.
set -eu
host="${RENDER_EXTERNAL_HOSTNAME:-localhost}"
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-$host,localhost,127.0.0.1}"
export CSRF_TRUSTED_ORIGINS="${CSRF_TRUSTED_ORIGINS:-https://$host}"
run="${DEMO_RUN_DIR:-/tmp/docflow}"
mkdir -p "$run"

if [ -z "${DATABASE_URL:-}" ]; then
  pgbin="${PGBIN:-$(ls -d /usr/lib/postgresql/*/bin | tail -n 1)}"
  "$pgbin/initdb" -D "$run/pg" -U postgres --auth=trust -E UTF8 > /dev/null
  "$pgbin/pg_ctl" -D "$run/pg" -l "$run/pg.log" -w start \
    -o "-k '' -c listen_addresses=127.0.0.1 -p 5432 -c shared_buffers=32MB -c fsync=off" > /dev/null
  "$pgbin/createdb" -h 127.0.0.1 -U postgres docflow
  export DATABASE_URL=postgresql://postgres@127.0.0.1:5432/docflow
fi
if [ -z "${REDIS_URL:-}" ]; then
  "${REDIS_SERVER:-redis-server}" --daemonize yes --bind 127.0.0.1 --port 6379 --save "" \
    --appendonly no --maxmemory 32mb --maxmemory-policy allkeys-lru --logfile "$run/redis.log"
  export REDIS_URL=redis://127.0.0.1:6379/0
fi

python manage.py migrate --noinput -v0
python manage.py load_demo
exec gunicorn config.wsgi -c gunicorn.conf.py --bind "0.0.0.0:${PORT:-10000}"
