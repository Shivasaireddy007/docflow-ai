from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from documents.storage import FilesystemStorage, S3Storage, document_key


def test_s3_storage_round_trip() -> None:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="docs")
        storage = S3Storage("docs", client)

        storage.put("tenants/t1/documents/abc", b"%PDF-1.7", "application/pdf")

        assert storage.get("tenants/t1/documents/abc") == b"%PDF-1.7"
        head = client.head_object(Bucket="docs", Key="tenants/t1/documents/abc")
        assert head["ContentType"] == "application/pdf"


def test_filesystem_storage_refuses_keys_outside_its_root(tmp_path: Path) -> None:
    storage = FilesystemStorage(tmp_path)

    with pytest.raises(ValueError, match="escapes"):
        storage.put("../../etc/passwd", b"x", "text/plain")


def test_keys_are_per_tenant_and_content_addressed() -> None:
    assert document_key("t1", "ab12") == "tenants/t1/uploads/ab12"


def test_ensure_bucket_creates_it_once(settings: object) -> None:
    from django.core.management import call_command
    from django.test import override_settings

    from documents.storage import get_storage

    with mock_aws(), override_settings(STORAGE_BACKEND="s3", S3_BUCKET="docflow-test", S3_ENDPOINT_URL=None):
        get_storage.cache_clear()
        call_command("ensure_bucket")
        call_command("ensure_bucket")

        names = [b["Name"] for b in boto3.client("s3", region_name="us-east-1").list_buckets()["Buckets"]]
        assert names == ["docflow-test"]
    get_storage.cache_clear()
