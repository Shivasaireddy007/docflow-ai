import json
from typing import Any

import boto3
import pytest
from django.test import override_settings
from moto import mock_aws
from rest_framework.test import APIClient

from core import signing
from documents import processing
from documents.models import Document, Job
from review.models import AuditEvent
from tenants.models import Tenant
from tests.conftest import RECEIPT_TEXT, image_bytes, upload

SECRET = "callback-test-secret"
URL = "/api/v1/internal/pipeline-results"

pytestmark = pytest.mark.usefixtures("aws_mode")


@pytest.fixture
def aws_mode() -> Any:
    with override_settings(PROCESSING_BACKEND="stepfunctions", CALLBACK_SECRET=SECRET):
        yield


def scored_result() -> dict[str, Any]:
    from pipeline import confidence, schema
    from tests.conftest import RECEIPT_FIELDS

    fields, items, conf = confidence.score(schema.coerce(RECEIPT_FIELDS), RECEIPT_TEXT)
    return {
        "pipeline_version": "ocr=x;llm=y;prompt=2;ocr-prompt=1", "ocr_text": RECEIPT_TEXT, "fields": fields,
        "line_items": items, "confidence": conf, "ocr_ms": 7000, "extraction_ms": 8000,
        "ocr_cached": False, "extraction_cached": True,
    }  # fmt: skip


def post(payload: dict[str, Any], secret: str = SECRET) -> Any:
    body = json.dumps(payload).encode()
    headers = signing.sign(secret, body)
    return APIClient().generic("POST", URL, body.decode(), content_type="application/json", headers=headers)


def uploaded(api: APIClient) -> Document:
    return Document.objects.get(pk=upload(api, image_bytes()).json()["id"])


def test_on_aws_an_upload_waits_for_the_pipeline_instead_of_a_local_job(api: APIClient) -> None:
    document = uploaded(api)

    assert document.status == Document.Status.QUEUED
    assert not Job.objects.exists()


def test_a_reported_result_goes_through_the_rules(api: APIClient, tenant: Tenant) -> None:
    document = uploaded(api)

    response = post(
        {
            "tenant_id": str(tenant.id),
            "sha256": document.sha256,
            "execution": "exec-1",
            "result": scored_result(),
        }
    )

    assert response.json() == {"status": "auto_approved"}
    document.refresh_from_db()
    assert document.status == Document.Status.APPROVED
    extraction = document.extractions.get()
    assert (extraction.ocr_ms, extraction.extraction_cached) == (7000, True)
    event = AuditEvent.objects.get(document=document, action="extracted")
    assert (event.actor, event.data["execution"]) == ("pipeline:aws", "exec-1")


def test_a_repeated_delivery_changes_nothing(api: APIClient, tenant: Tenant) -> None:
    document = uploaded(api)
    report = {"tenant_id": str(tenant.id), "sha256": document.sha256, "result": scored_result()}
    post(report)

    again = post(report)

    assert again.json() == {"duplicate": True}
    assert document.extractions.count() == 1


def test_forged_and_unknown_reports_are_refused(api: APIClient, tenant: Tenant) -> None:
    document = uploaded(api)
    report = {"tenant_id": str(tenant.id), "sha256": document.sha256, "result": scored_result()}

    assert post(report, secret="guessed").status_code == 401
    assert post({**report, "sha256": "0" * 64}).status_code == 404
    document.refresh_from_db()
    assert document.status == Document.Status.QUEUED


def test_a_reported_failure_marks_the_document(api: APIClient, tenant: Tenant) -> None:
    document = uploaded(api)

    post({"tenant_id": str(tenant.id), "sha256": document.sha256, "error": "ModelRepetition: looped"})

    document.refresh_from_db()
    assert (document.status, document.error) == (Document.Status.FAILED, "ModelRepetition: looped")


def test_reprocessing_on_aws_starts_an_execution(
    api: APIClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = uploaded(api)
    post({"tenant_id": str(tenant.id), "sha256": document.sha256, "error": "ModelError: down"})
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    with mock_aws():
        processing._states.cache_clear()
        states = boto3.client("stepfunctions")
        arn = states.create_state_machine(
            name="docflow", definition='{"StartAt": "Done", "States": {"Done": {"Type": "Succeed"}}}',
            roleArn="arn:aws:iam::123456789012:role/docflow",
        )["stateMachineArn"]  # fmt: skip
        with override_settings(STATE_MACHINE_ARN=arn, S3_BUCKET="docs"):
            response = api.post(f"/api/v1/documents/{document.id}/reprocess")
        executions = states.list_executions(stateMachineArn=arn)["executions"]
        started = json.loads(states.describe_execution(executionArn=executions[0]["executionArn"])["input"])
    processing._states.cache_clear()

    assert response.status_code == 202
    assert started == {"bucket": "docs", "key": document.storage_key, "force": True}
