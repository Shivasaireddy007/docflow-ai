"""Hands documents to whichever processing backend is configured.

- "worker": a row in the jobs table, picked up by `run_worker` (local, Docker Compose).
- "stepfunctions": nothing to do on upload, because the object landing in S3 starts the state
  machine; reprocessing starts an execution directly, with `force` so the pipeline doesn't skip a
  file it has seen before.
"""

import json
from functools import cache
from typing import Any

from django.conf import settings

from documents import jobs
from documents.models import Document


@cache
def _states() -> Any:
    import boto3

    return boto3.client("stepfunctions")


def submit(document: Document) -> None:
    """A new upload, inside the transaction that created it."""
    if settings.PROCESSING_BACKEND == "worker":
        jobs.enqueue(document)


def resubmit(document: Document) -> None:
    """Process an existing document again (e.g. after a model or prompt change)."""
    if settings.PROCESSING_BACKEND == "worker":
        jobs.enqueue(document)
        return
    _states().start_execution(
        stateMachineArn=settings.STATE_MACHINE_ARN,
        input=json.dumps({"bucket": settings.S3_BUCKET, "key": document.storage_key, "force": True}),
    )
