#!/bin/sh
# Starts the demo: fresh schema and data on every boot, so visitors' reviews don't pile up.
set -eu
host="${RENDER_EXTERNAL_HOSTNAME:-localhost}"
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-$host,localhost,127.0.0.1}"
export CSRF_TRUSTED_ORIGINS="${CSRF_TRUSTED_ORIGINS:-https://$host}"
python manage.py migrate --noinput -v0
python manage.py load_demo
exec gunicorn config.wsgi -c gunicorn.conf.py --bind "0.0.0.0:${PORT:-10000}"
