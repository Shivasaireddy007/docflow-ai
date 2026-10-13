"""Gunicorn for the API container. Several worker processes share Prometheus metrics through
PROMETHEUS_MULTIPROC_DIR, which must start empty and learn about processes that exit."""

import os
import shutil
from typing import Any

# Set here, not in the image: the worker runs from the same image as a single process, without it.
# It must be set before prometheus_client is imported, which picks its storage at import time.
METRICS_DIR = os.environ.setdefault(
    "PROMETHEUS_MULTIPROC_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".prometheus")
)

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
accesslog = "-"


def on_starting(server: Any) -> None:
    """Empties the folder (files from a previous run would be counted again); the folder itself
    may sit in a directory the app can't write to, so it is kept rather than recreated."""
    os.makedirs(METRICS_DIR, exist_ok=True)
    for name in os.listdir(METRICS_DIR):
        path = os.path.join(METRICS_DIR, name)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)


def child_exit(server: Any, worker: Any) -> None:
    from prometheus_client import multiprocess

    multiprocess.mark_process_dead(worker.pid)  # type: ignore[no-untyped-call]
