"""Where uploaded files live: S3 (or MinIO) in deployments, a local folder in development and tests.

Keys are content-addressed per tenant (`tenants/<tenant>/uploads/<sha256>`), so storing the same
file twice is harmless and a half-finished upload can simply be retried. On AWS, an object
arriving under uploads/ is what starts the processing pipeline.
"""

from functools import cache
from pathlib import Path
from typing import Any, Protocol

from django.conf import settings


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...


class FilesystemStorage:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise ValueError(f"Key escapes the storage root: {key}")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()


class S3Storage:
    def __init__(self, bucket: str, client: Any) -> None:
        self.bucket = bucket
        self.client = client

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        body: bytes = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return body


def document_key(tenant_id: object, sha256: str) -> str:
    return f"tenants/{tenant_id}/uploads/{sha256}"


@cache
def get_storage() -> Storage:
    if settings.STORAGE_BACKEND == "s3":
        import boto3

        return S3Storage(settings.S3_BUCKET, boto3.client("s3", endpoint_url=settings.S3_ENDPOINT_URL))
    return FilesystemStorage(Path(settings.STORAGE_ROOT))
