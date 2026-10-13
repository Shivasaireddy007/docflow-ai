"""Settings, read from environment variables so the same image runs locally, in Docker and on AWS."""

import os
from pathlib import Path
from urllib.parse import unquote, urlparse

import django_stubs_ext

# Lets classes like ModelAdmin[Tenant] carry their type parameters at runtime.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def env_bool(name: str, default: bool = False) -> bool:
    return env(name, str(default)).lower() in {"1", "true", "yes", "on"}


def database_from_url(url: str) -> dict[str, object]:
    """postgresql://user:password@host:5432/name -> Django's DATABASES entry."""
    parts = urlparse(url)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": parts.path.lstrip("/"),
        "USER": unquote(parts.username or ""),
        "PASSWORD": unquote(parts.password or ""),
        "HOST": parts.hostname or "",
        "PORT": str(parts.port or 5432),
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
    }


DEBUG = env_bool("DEBUG")
SECRET_KEY = env("SECRET_KEY", "local-development-only-not-secret")
ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "drf_spectacular",
    "tenants",
    "documents",
    "review",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",  # admin and API docs assets under Gunicorn
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": database_from_url(env("DATABASE_URL", "postgresql://postgres@127.0.0.1:5432/docflow"))
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_TZ = True
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

REST_FRAMEWORK = {
    # Machines use API keys; reviewers sign in and use a session cookie (CSRF-protected).
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "tenants.auth.ApiKeyAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["tenants.access.HasTenant"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 25,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "UNAUTHENTICATED_USER": None,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "docflow API",
    "DESCRIPTION": (
        "Upload receipts and invoices; they are OCR'd and their fields extracted by self-hosted models, "
        "each field with a confidence score.\n\n**Authentication:** send your tenant's API key as "
        "`Authorization: Api-Key <key>`."
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# Reviewer sessions: the web app is served from the same origin as the API.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 12 * 60 * 60
SESSION_COOKIE_SECURE = env_bool("SECURE_COOKIES")
CSRF_COOKIE_SECURE = env_bool("SECURE_COOKIES")
CSRF_TRUSTED_ORIGINS = [o.strip() for o in env("CSRF_TRUSTED_ORIGINS").split(",") if o.strip()]

# Uploads
MAX_UPLOAD_BYTES = int(env("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
MAX_PAGES = int(env("MAX_PAGES", "10"))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES + 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES + 1024 * 1024

# Document storage: "s3" (AWS S3 or any S3-compatible server) or "filesystem" (local development and tests).
STORAGE_BACKEND = env("STORAGE_BACKEND", "filesystem")
STORAGE_ROOT = Path(env("STORAGE_ROOT", str(BASE_DIR / ".storage")))
S3_BUCKET = env("S3_BUCKET", "docflow-documents")
S3_ENDPOINT_URL = env("S3_ENDPOINT_URL") or None  # RustFS locally; empty for AWS

# Models, served by Ollama locally and vLLM for the GPU benchmark.
# "ollama" (Ollama's own API) or "openai" (the OpenAI-compatible API that vLLM serves).
MODEL_API = env("MODEL_API", "ollama")
MODEL_URL = env("MODEL_URL") or env("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL_API_KEY = env("MODEL_API_KEY")
OCR_MODEL = env("OCR_MODEL", "qwen2.5vl:3b")
EXTRACTION_MODEL = env("EXTRACTION_MODEL", "qwen2.5:7b")
MODEL_TIMEOUT_SECONDS = float(env("MODEL_TIMEOUT_SECONDS", "180"))
# Bump when prompts or the schema change, so cached and stored results are tied to what produced them.
PROMPT_VERSION = env("PROMPT_VERSION", "2")
OCR_PROMPT_VERSION = env("OCR_PROMPT_VERSION", "1")

# Redis: the model-result cache and rate limits. Both keep working (uncached, unlimited) if it's down.
REDIS_URL = env("REDIS_URL", "redis://127.0.0.1:6379/2")
RESULT_CACHE_ENABLED = env_bool("RESULT_CACHE_ENABLED", True)
RESULT_CACHE_SECONDS = int(env("RESULT_CACHE_SECONDS", str(30 * 24 * 3600)))

# Token buckets: "<capacity>/<refill per second>"
UPLOAD_RATE = env("UPLOAD_RATE", "30/0.5")  # per tenant: bursts of 30, then one every 2 s
LOGIN_RATE = env("LOGIN_RATE", "5/0.0167")  # per username and address: 5, then one a minute
MODEL_RATE = env("MODEL_RATE", "8/4")  # per model, across all workers: protects the model server

# Where documents are processed: "worker" (the PostgreSQL job queue and `run_worker`) or
# "stepfunctions" (AWS: an upload to S3 starts the state machine, which reports back to
# /api/v1/internal/pipeline-results, signed with CALLBACK_SECRET).
PROCESSING_BACKEND = env("PROCESSING_BACKEND", "worker")
STATE_MACHINE_ARN = env("STATE_MACHINE_ARN")
CALLBACK_SECRET = env("CALLBACK_SECRET")

# Processing jobs
JOB_MAX_ATTEMPTS = int(env("JOB_MAX_ATTEMPTS", "4"))
JOB_LOCK_TIMEOUT_SECONDS = int(env("JOB_LOCK_TIMEOUT_SECONDS", "600"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {"httpx": {"level": "WARNING"}, "httpcore": {"level": "WARNING"}},
}
