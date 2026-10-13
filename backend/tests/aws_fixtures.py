"""moto-backed S3 and DynamoDB shaped like infra/, with fake models: the `cloud` fixture."""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from lambdas import aws, handlers
from tests.conftest import RECEIPT_FIELDS, RECEIPT_TEXT, FakeExtractor, FakeOcr

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
