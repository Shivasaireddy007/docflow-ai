"""The AWS pipeline and the review app as one system: a document uploaded through the API is
processed by the Lambda steps (against moto's S3 and DynamoDB) and their signed report lands in
the real callback endpoint, where the tenant's rules decide it."""

from typing import Any

import httpx
import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from documents.models import Document
from lambdas import handlers
from review.models import AuditEvent
from tests.aws_fixtures import BUCKET
from tests.conftest import RECEIPT_FIELDS, Models, image_bytes, upload

SECRET = "integration-secret"


@pytest.fixture
def delivered_to_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Lambda's HTTPS call, delivered to the Django test client instead of the network."""
    monkeypatch.setenv("CALLBACK_URL", "https://review.example.com/api/v1/internal/pipeline-results")
    monkeypatch.setenv("CALLBACK_SECRET", SECRET)
    app = APIClient()

    def deliver(url: str, content: bytes, headers: dict[str, str], timeout: float) -> httpx.Response:
        response = app.generic(
            "POST",
            "/api/v1/internal/pipeline-results",
            content.decode(),
            content_type="application/json",
            headers=headers,
        )
        return httpx.Response(response.status_code, content=response.content)

    monkeypatch.setattr(httpx, "post", deliver)


def run_pipeline(cloud: dict[str, Any], document: Document, data: bytes) -> dict[str, Any]:
    cloud["s3"].put_object(Bucket=BUCKET, Key=document.storage_key, Body=data)  # what the API stored in S3
    state = handlers.prepare({"bucket": BUCKET, "key": document.storage_key})
    for step in (handlers.ocr, handlers.extract, handlers.decide):
        state = step(state)
    return state


@pytest.mark.usefixtures("delivered_to_app")
@override_settings(PROCESSING_BACKEND="stepfunctions", CALLBACK_SECRET=SECRET)
def test_an_upload_is_processed_on_aws_and_decided_by_the_app(api: APIClient, cloud: dict[str, Any]) -> None:
    data = image_bytes()
    document = Document.objects.get(pk=upload(api, data).json()["id"])

    final = run_pipeline(cloud, document, data)

    assert final["status"] == "reported"
    body = api.get(f"/api/v1/documents/{document.id}").json()
    assert body["status"] == "approved"
    assert (body["decision"]["decided_by"], body["decision"]["rules_version"]) == ("rules", 1)
    assert body["extraction"]["fields"]["total"]["value"] == RECEIPT_FIELDS["total"]
    actors = list(AuditEvent.objects.filter(document=document).values_list("action", "actor"))
    assert actors[1:] == [("extracted", "pipeline:aws"), ("auto_approved", "pipeline")]


@pytest.mark.usefixtures("delivered_to_app")
@override_settings(PROCESSING_BACKEND="stepfunctions", CALLBACK_SECRET=SECRET)
def test_a_doubtful_document_reaches_the_review_queue(
    api: APIClient,
    cloud: dict[str, Any],
    models: Models,
    tenant: Any,
) -> None:
    cloud["fakes"]["extract"].result = {**RECEIPT_FIELDS, "total": 194000}
    data = image_bytes()
    document = Document.objects.get(pk=upload(api, data).json()["id"])

    run_pipeline(cloud, document, data)

    document.refresh_from_db()
    assert document.status == Document.Status.NEEDS_REVIEW
    failed = [r["rule_id"] for r in document.decisions.get().rule_results if not r["passed"]]
    assert failed == ["confident", "totals-add-up"]
