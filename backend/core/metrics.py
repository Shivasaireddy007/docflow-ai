"""Prometheus metrics: what the pipeline and reviewers do, and how long it takes.

The API serves them at /metrics (internal: nginx doesn't proxy it). Gunicorn's processes share
them through PROMETHEUS_MULTIPROC_DIR; the worker serves its own on WORKER_METRICS_PORT. Queue
depth is read from the database at scrape time, so it is right whichever process asks.
"""

import os
import re
import time
from collections.abc import Callable, Iterator

from django.http import HttpRequest, HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

DOCUMENTS = Counter("docflow_documents", "Documents that finished processing, by outcome", ["outcome"])
STEP_SECONDS = Histogram(
    "docflow_step_seconds",
    "Time per pipeline step",
    ["step"],
    buckets=(0.005, 0.05, 0.25, 1, 2.5, 5, 10, 20, 30, 60, 120),
)
MODEL_CACHE = Counter("docflow_model_cache", "Model-result cache lookups", ["step", "result"])
REVIEWS = Counter("docflow_reviews", "Reviewer decisions", ["decision", "corrected"])
HTTP_SECONDS = Histogram(
    "docflow_http_request_seconds",
    "API request latency by route",
    ["method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5),
)


def _registry() -> CollectorRegistry:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        return registry
    return REGISTRY


class StatusCollector(Collector):
    """Documents in each status, counted at scrape time. A plain family rather than a Gauge: in
    multiprocess mode a Gauge is written to a file per process, so every Gunicorn worker that had
    answered a scrape would report it again and the sum would multiply."""

    def describe(self) -> list[GaugeMetricFamily]:
        return []  # registering would otherwise run collect(), a query, just to learn the name

    def collect(self) -> Iterator[GaugeMetricFamily]:
        from django.db.models import Count

        from documents.models import Document

        family = GaugeMetricFamily(
            "docflow_documents_by_status", "Documents in each status", labels=["status"]
        )
        for status, count in Document.objects.values_list("status").annotate(n=Count("id")):
            family.add_metric([status], count)
        yield family


def metrics_view(request: HttpRequest) -> HttpResponse:
    depth = CollectorRegistry()
    depth.register(StatusCollector())
    return HttpResponse(
        generate_latest(_registry()) + generate_latest(depth), content_type=CONTENT_TYPE_LATEST
    )


def route_label(route: str) -> str:
    """Router regexes as readable patterns: "api/v1/documents/(?P<pk>[^/.]+)$" -> "api/v1/documents/<pk>"."""
    return re.sub(r"\(\?P<(\w+)>[^)]*\)", r"<\1>", route).replace("^", "").replace("$", "")


class RequestMetricsMiddleware:
    """Latency by route pattern (`api/v1/documents/<pk>`), not raw path, so label values stay few."""

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        started = time.perf_counter()
        response = self.get_response(request)
        match = request.resolver_match
        route = route_label(match.route) if match else "unmatched"
        if route.startswith("api/"):
            HTTP_SECONDS.labels(request.method, route, str(response.status_code)).observe(
                time.perf_counter() - started
            )
        return response
