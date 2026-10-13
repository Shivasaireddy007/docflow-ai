from django.test import Client
from prometheus_client import REGISTRY
from rest_framework.test import APIClient

from documents import jobs
from tests.conftest import Models, image_bytes, upload


def value(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def test_processing_and_requests_are_measured(api: APIClient, models: Models) -> None:
    approved_before = value("docflow_documents_total", outcome="auto_approved")
    upload(api, image_bytes())
    jobs.run_once()
    api.get("/api/v1/documents")

    assert value("docflow_documents_total", outcome="auto_approved") == approved_before + 1
    assert value("docflow_step_seconds_count", step="ocr") >= 1
    assert value("docflow_model_cache_total", step="ocr", result="miss") >= 1
    assert (
        value("docflow_http_request_seconds_count", method="GET", route="api/v1/documents", status="200") >= 1
    )


def test_metrics_include_queue_depth_from_the_database(api: APIClient, models: Models) -> None:
    upload(api, image_bytes())

    body = Client().get("/metrics").content.decode()

    assert 'docflow_documents_by_status{status="queued"} 1.0' in body
    assert "docflow_step_seconds_bucket" in body


def test_route_labels_are_readable_patterns() -> None:
    from core.metrics import route_label

    assert (
        route_label("api/v1/documents/(?P<pk>[^/.]+)/pages/(?P<number>\\d+)$")
        == "api/v1/documents/<pk>/pages/<number>"
    )
