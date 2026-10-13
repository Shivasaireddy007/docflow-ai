import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()

from core import telemetry  # noqa: E402  (after Django is set up)

telemetry.install("docflow-api")
