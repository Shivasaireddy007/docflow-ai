"""Gunicorn for the API container. Several worker processes share Prometheus metrics through
PROMETHEUS_MULTIPROC_DIR, which must start empty and learn about processes that exit."""

import os
import shutil
from typing import Any

from prometheus_client import multiprocess

bind = "0.0.0.0:8000"
workers = int(os.environ.get("WEB_CONCURRENCY", "3"))
accesslog = "-"
METRICS_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR")


def on_starting(server: Any) -> None:
    if METRICS_DIR:
        shutil.rmtree(METRICS_DIR, ignore_errors=True)
        os.makedirs(METRICS_DIR, exist_ok=True)


def child_exit(server: Any, worker: Any) -> None:
    if METRICS_DIR:
        multiprocess.mark_process_dead(worker.pid)  # type: ignore[no-untyped-call]
