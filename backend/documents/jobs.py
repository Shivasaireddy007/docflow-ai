"""The processing queue: a jobs table claimed with SELECT ... FOR UPDATE SKIP LOCKED.

Several workers can run side by side. Each claims a different job without blocking the others,
and the model call happens outside any transaction, so no row lock is held for the seconds a
model takes.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.metrics import DOCUMENTS
from documents.models import Document, Job
from pipeline import run
from pipeline.files import UnsupportedFile
from pipeline.providers import ModelRepetition
from review import audit
from review.decisions import decide_automatically

log = logging.getLogger(__name__)

BACKOFF_BASE_SECONDS = 15
BACKOFF_MAX_SECONDS = 600


def backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(BACKOFF_BASE_SECONDS * 2 ** (attempts - 1), BACKOFF_MAX_SECONDS))


def enqueue(document: Document) -> Job:
    return Job.objects.create(document=document)


def claim() -> Job | None:
    """Takes the next due job, or one whose worker has stopped responding."""
    now = timezone.now()
    stale = now - timedelta(seconds=settings.JOB_LOCK_TIMEOUT_SECONDS)
    with transaction.atomic():
        job = (
            Job.objects.select_for_update(skip_locked=True)
            .filter(
                Q(status=Job.Status.QUEUED, run_after__lte=now)
                | Q(status=Job.Status.RUNNING, locked_at__lt=stale)
            )
            .order_by("run_after")
            .first()
        )
        if job is None:
            return None
        job.status = Job.Status.RUNNING
        job.locked_at = now
        job.attempts += 1
        job.save(update_fields=["status", "locked_at", "attempts"])
        Document.objects.filter(pk=job.document_id).update(status=Document.Status.PROCESSING, error="")
    return job


def execute(job: Job) -> None:
    """Processes a claimed job and records the outcome: done, retry later, or give up."""
    document = Document.objects.get(pk=job.document_id)
    try:
        extraction = run.process(document)
    except UnsupportedFile as exc:
        # Retrying can't fix a broken file.
        _fail(job, document, str(exc))
        return
    except ModelRepetition as exc:
        # Already retried with anti-repetition sampling; the same input would loop again.
        _fail(job, document, f"The model couldn't read this document: {exc}")
        return
    except Exception as exc:
        log.exception("Job %s for document %s failed (attempt %s)", job.pk, document.pk, job.attempts)
        if job.attempts >= settings.JOB_MAX_ATTEMPTS:
            _fail(job, document, f"Gave up after {job.attempts} attempts: {exc}")
        else:
            Job.objects.filter(pk=job.pk).update(
                status=Job.Status.QUEUED,
                run_after=timezone.now() + backoff(job.attempts),
                last_error=str(exc),
            )
            Document.objects.filter(pk=document.pk).update(status=Document.Status.QUEUED, error=str(exc))
        return
    log.info("Extracted %s in %s+%s ms", document.pk, extraction.ocr_ms, extraction.extraction_ms)
    audit.record(
        document.tenant,
        audit.PIPELINE,
        "extracted",
        document,
        pipeline_version=extraction.pipeline_version,
        confidence=extraction.confidence,
        ms=extraction.ocr_ms + extraction.extraction_ms,
        cached={"ocr": extraction.ocr_cached, "extraction": extraction.extraction_cached},
    )
    decide_automatically(document, extraction)  # sets the document's status
    Job.objects.filter(pk=job.pk).update(
        status=Job.Status.SUCCEEDED, finished_at=timezone.now(), last_error=""
    )


def _fail(job: Job, document: Document, error: str) -> None:
    DOCUMENTS.labels("failed").inc()
    Job.objects.filter(pk=job.pk).update(
        status=Job.Status.FAILED, finished_at=timezone.now(), last_error=error
    )
    Document.objects.filter(pk=document.pk).update(status=Document.Status.FAILED, error=error)
    audit.record(document.tenant, audit.PIPELINE, "failed", document, error=error)


def run_once() -> bool:
    """Claims and runs one job. False when there was nothing to do."""
    job = claim()
    if job is None:
        return False
    execute(job)
    return True
