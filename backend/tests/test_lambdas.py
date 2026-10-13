"""The AWS steps against moto's S3 and DynamoDB, with tables shaped like infra/dynamodb.tf."""

import json
import time
from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from lambdas import aws, handlers
from pipeline.files import UnsupportedFile
from tests.conftest import RECEIPT_FIELDS, RECEIPT_TEXT, FakeExtractor, FakeOcr, image_bytes

BUCKET = "docflow-test-documents"


@pytest.fixture
def cloud(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")
    monkeypatch.setenv("DOCUMENTS_BUCKET", BUCKET)
    monkeypatch.setenv("RESULTS_TABLE", "docflow-results")
    monkeypatch.setenv("CACHE_TABLE", "docflow-cache")
    with mock_aws():
        aws.s3.cache_clear()
        aws.dynamodb.cache_clear()
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
        s3.put_bucket_versioning(Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"})
        db = boto3.client("dynamodb")
        db.create_table(
            TableName="docflow-results",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}],
            AttributeDefinitions=[
                {"AttributeName": n, "AttributeType": "S"}
                for n in ("pk", "tenant_id", "status", "uploaded_at")
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": name,
                    "KeySchema": [
                        {"AttributeName": h, "KeyType": "HASH"},
                        {"AttributeName": "uploaded_at", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
                for name, h in (("by_tenant", "tenant_id"), ("by_status", "status"))
            ],
        )
        db.create_table(
            TableName="docflow-cache",
            BillingMode="PAY_PER_REQUEST",
            KeySchema=[{"AttributeName": "key", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "key", "AttributeType": "S"}],
        )
        fakes = {"ocr": FakeOcr(RECEIPT_TEXT), "extract": FakeExtractor(RECEIPT_FIELDS)}
        monkeypatch.setattr(handlers, "providers", lambda: (fakes["ocr"], fakes["extract"]))
        yield {"s3": s3, "fakes": fakes}
    aws.s3.cache_clear()
    aws.dynamodb.cache_clear()


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
