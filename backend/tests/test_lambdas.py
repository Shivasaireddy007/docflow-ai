"""The AWS steps against moto's S3 and DynamoDB, with tables shaped like infra/dynamodb.tf."""

import json
import time
from typing import Any

import httpx
import pytest

from lambdas import aws, handlers
from pipeline.files import UnsupportedFile
from tests.aws_fixtures import BUCKET
from tests.conftest import RECEIPT_TEXT, image_bytes


def run(cloud: dict[str, Any], data: bytes, key: str = "tenants/acme/uploads/lunch.png") -> dict[str, Any]:
    """Uploads a file and runs the steps the state machine would."""
    cloud["s3"].put_object(Bucket=BUCKET, Key=key, Body=data)
    state = handlers.prepare({"bucket": BUCKET, "key": key})
    if state["skip"]:
        return state
    for step in (handlers.ocr, handlers.extract):
        state = step(state)
    return handlers.decide(state)


def item(pk: str) -> dict[str, Any]:
    found: dict[str, Any] = aws.results_table().get_item(Key={"pk": pk})["Item"]
    return found


def test_a_receipt_goes_through_every_step(cloud: dict[str, Any]) -> None:
    result = run(cloud, image_bytes())

    stored = item(result["pk"])
    assert (result["status"], stored["status"]) == ("auto_approved", "auto_approved")
    assert stored["fields"]["total"]["value"] == 56100
    assert stored["tenant_id"] == "acme" and stored["rules_version"] == "default"
    assert stored["cached"] == {"ocr": False, "extraction": False}
    ocr_text = (
        cloud["s3"].get_object(Bucket=BUCKET, Key=f"work/acme/{stored['doc_hash']}/ocr.txt")["Body"].read()
    )
    assert ocr_text.decode() == RECEIPT_TEXT


def test_the_same_file_is_processed_once(cloud: dict[str, Any]) -> None:
    data = image_bytes()
    run(cloud, data)

    again = run(cloud, data, "tenants/acme/uploads/renamed.png")

    assert again["skip"] is True
    assert len(cloud["fakes"]["ocr"].calls) == 1


def test_a_failed_document_can_be_retried(cloud: dict[str, Any]) -> None:
    data = image_bytes()
    first = run(cloud, data)
    aws.results_table().update_item(
        Key={"pk": first["pk"]}, UpdateExpression="SET #s = :f", ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":f": "failed"},
    )  # fmt: skip

    assert run(cloud, data)["status"] == "auto_approved"


def test_a_second_photo_of_an_approved_receipt_goes_to_review(cloud: dict[str, Any]) -> None:
    first = run(cloud, image_bytes("photo one"))

    second = run(cloud, image_bytes("photo two"), "tenants/acme/uploads/again.png")

    assert second["status"] == "needs_review"
    failed = [r for r in item(second["pk"])["rule_results"] if not r["passed"]]
    assert [(r["rule_id"], r["message"]) for r in failed] == [
        ("not-a-duplicate", f"same merchant, date and total as {first['pk']}")
    ]


def test_tenants_rules_come_from_the_bucket_with_their_version(cloud: dict[str, Any]) -> None:
    rules = [{"id": "small", "type": "max_amount", "field": "total", "max": 10000}]
    put = cloud["s3"].put_object(Bucket=BUCKET, Key="config/rules/acme.json", Body=json.dumps(rules))

    result = run(cloud, image_bytes())

    assert result["status"] == "needs_review"
    assert item(result["pk"])["rules_version"] == put["VersionId"]


def test_model_results_are_cached_in_dynamodb(cloud: dict[str, Any]) -> None:
    data = image_bytes()
    first = run(cloud, data)
    aws.results_table().delete_item(Key={"pk": first["pk"]})  # pretend it was never processed

    run(cloud, data)

    assert item(first["pk"])["cached"] == {"ocr": True, "extraction": True}
    assert len(cloud["fakes"]["ocr"].calls) == 1


@pytest.mark.parametrize(
    ("key", "data"),
    [("tenants/acme/uploads/notes.txt", b"plain text"), ("somewhere/else.png", image_bytes())],
)
def test_unusable_uploads_fail_without_retrying(cloud: dict[str, Any], key: str, data: bytes) -> None:
    cloud["s3"].put_object(Bucket=BUCKET, Key=key, Body=data)

    with pytest.raises(UnsupportedFile):
        handlers.prepare({"bucket": BUCKET, "key": key})


def test_expired_cache_entries_are_misses(cloud: dict[str, Any]) -> None:
    store = aws.DynamoStore(aws.cache_table())
    store.set("k", "v", ttl_seconds=60)
    assert store.get("k") == "v"
    aws.cache_table().put_item(Item={"key": "k", "value": "v", "expires_at": int(time.time()) - 1})

    assert store.get("k") is None


@pytest.fixture
def integrated(cloud: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Integrated mode: reports go to a review app, captured here with their signatures checked."""
    monkeypatch.setenv("CALLBACK_URL", "https://review.example.com/api/v1/internal/pipeline-results")
    monkeypatch.setenv("CALLBACK_SECRET", "s3cret")
    received: list[dict[str, Any]] = []

    def fake_post(url: str, content: bytes, headers: dict[str, str], timeout: float) -> httpx.Response:
        from core import signing

        assert signing.verify(
            "s3cret", content, headers["X-Docflow-Timestamp"], headers["X-Docflow-Signature"]
        )
        received.append(json.loads(content))
        return httpx.Response(200, json={"status": "auto_approved"})

    monkeypatch.setattr(httpx, "post", fake_post)
    return received


def test_integrated_mode_reports_the_extraction_to_the_review_app(
    cloud: dict[str, Any], integrated: list[dict[str, Any]]
) -> None:
    result = run(cloud, image_bytes())

    assert result["status"] == "reported"
    [sent] = integrated
    assert sent["tenant_id"] == "acme" and len(sent["sha256"]) == 64
    assert sent["result"]["fields"]["total"]["value"] == 56100
    assert sent["result"]["ocr_text"] == RECEIPT_TEXT
    assert item(result["pk"])["status"] == "reported"


def test_failures_are_reported_and_delivery_errors_retried(
    cloud: dict[str, Any], integrated: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    handlers.report_failure(
        {"tenant": "acme", "doc_hash": "abc", "error": {"Error": "ModelError", "Cause": "down"}}
    )
    assert integrated == [{"tenant_id": "acme", "sha256": "abc", "error": "ModelError: down"}]

    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(503, text="deploying"))
    with pytest.raises(handlers.CallbackError):
        handlers.report({"tenant_id": "acme", "sha256": "abc", "error": "x"})
    monkeypatch.setattr(httpx, "post", lambda *a, **k: httpx.Response(404))
    handlers.report({"tenant_id": "acme", "sha256": "abc", "error": "x"})  # uploaded outside the app: fine


def test_force_reprocesses_a_known_file(cloud: dict[str, Any]) -> None:
    data = image_bytes()
    run(cloud, data)
    key = "tenants/acme/uploads/lunch.png"

    again = handlers.prepare({"bucket": BUCKET, "key": key, "force": True})

    assert again["skip"] is False
