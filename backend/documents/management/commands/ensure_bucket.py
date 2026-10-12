import time
from typing import Any

from botocore.exceptions import ClientError, EndpointConnectionError
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from documents.storage import S3Storage, get_storage


class Command(BaseCommand):
    help = "Create the document bucket if it doesn't exist, waiting for the storage server to start."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--wait-seconds", type=float, default=60)

    def handle(self, *args: Any, **options: Any) -> None:
        storage = get_storage()
        if not isinstance(storage, S3Storage):
            self.stdout.write(f"Storage backend is {settings.STORAGE_BACKEND}; no bucket needed.")
            return

        deadline = time.monotonic() + options["wait_seconds"]
        while True:
            try:
                storage.client.head_bucket(Bucket=storage.bucket)
                self.stdout.write(f"Bucket {storage.bucket} exists.")
                return
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in {"404", "NoSuchBucket", "NotFound"}:
                    raise
                storage.client.create_bucket(Bucket=storage.bucket)
                self.stdout.write(f"Created bucket {storage.bucket}.")
                return
            except EndpointConnectionError as exc:
                if time.monotonic() > deadline:
                    raise CommandError(f"Storage server unreachable: {exc}") from exc
                time.sleep(2)
