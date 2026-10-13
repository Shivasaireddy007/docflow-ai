import threading
from datetime import timedelta

import pytest
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from documents import jobs
from documents.models import Document, Job
from pipeline.providers import ModelError, ModelRepetition
from tenants.models import Tenant
from tests.conftest import Models, client_for, image_bytes, upload


def queued_document(api: APIClient) -> Document:
    return Document.objects.get(pk=upload(api, image_bytes()).json()["id"])


def test_a_job_extracts_the_document(api: APIClient, models: Models) -> None:
    document = queued_document(api)

    assert jobs.run_once() is True

    document.refresh_from_db()
    assert document.status == Document.Status.APPROVED, "every default rule passes"
    assert document.jobs.get().status == Job.Status.SUCCEEDED
    extraction = document.extractions.get()
    assert extraction.fields["total"]["checks"] == {"grounded": True, "valid": True, "consistent": True}
    assert extraction.confidence > 0.9
    assert jobs.run_once() is False, "nothing left to do"


def test_a_failing_model_is_retried_with_backoff(api: APIClient, models: Models) -> None:
    models(result=ModelError("connection refused"))
    document = queued_document(api)

    jobs.run_once()

    job = document.jobs.get()
    document.refresh_from_db()
    assert (job.status, job.attempts) == (Job.Status.QUEUED, 1)
    assert job.run_after > timezone.now() + timedelta(seconds=10)
    assert (document.status, document.error) == (Document.Status.QUEUED, "connection refused")
    assert jobs.run_once() is False, "not due yet"


def test_a_job_gives_up_after_the_last_attempt(api: APIClient, models: Models, settings: object) -> None:
    models(result=ModelError("out of memory"))
    document = queued_document(api)

    for _ in range(4):
        Job.objects.filter(document=document).update(run_after=timezone.now())
        jobs.run_once()

    job = document.jobs.get()
    document.refresh_from_db()
    assert (job.status, job.attempts) == (Job.Status.FAILED, 4)
    assert document.status == Document.Status.FAILED
    assert document.error.startswith("Gave up after 4 attempts")


def test_a_job_abandoned_by_a_crashed_worker_is_taken_over(api: APIClient, models: Models) -> None:
    document = queued_document(api)
    job = document.jobs.get()
    Job.objects.filter(pk=job.pk).update(
        status=Job.Status.RUNNING, locked_at=timezone.now() - timedelta(minutes=5)
    )
    assert jobs.claim() is None, "the worker may still be busy"

    Job.objects.filter(pk=job.pk).update(locked_at=timezone.now() - timedelta(hours=1))
    reclaimed = jobs.claim()

    assert reclaimed is not None and reclaimed.pk == job.pk
    assert reclaimed.attempts == 1


def test_backoff_doubles_up_to_a_limit() -> None:
    assert [jobs.backoff(n).seconds for n in (1, 2, 3, 10)] == [15, 30, 60, 600]


@pytest.mark.django_db(transaction=True)
def test_workers_skip_jobs_another_worker_has_locked(models: Models) -> None:
    api = client_for(Tenant.objects.create(name="Acme", slug="acme"))
    first = queued_document(api).jobs.get()
    second = queued_document_with(api, "second").jobs.get()
    locked, release = threading.Event(), threading.Event()

    def other_worker() -> None:
        with transaction.atomic():
            Job.objects.select_for_update().get(pk=first.pk)
            locked.set()
            release.wait(5)
        connection.close()  # this thread's own connection

    thread = threading.Thread(target=other_worker)
    thread.start()
    locked.wait(5)
    try:
        claimed = jobs.claim()
    finally:
        release.set()
        thread.join()

    assert claimed is not None and claimed.pk == second.pk, "took the free job instead of waiting"


def queued_document_with(api: APIClient, text: str) -> Document:
    return Document.objects.get(pk=upload(api, image_bytes(text)).json()["id"])


def test_a_document_the_model_cannot_read_fails_without_wasting_retries(
    api: APIClient, models: Models
) -> None:
    models(result=ModelRepetition("qwen2.5:7b ran past 1024 tokens"))
    document = queued_document(api)

    jobs.run_once()

    job = document.jobs.get()
    document.refresh_from_db()
    assert (job.status, job.attempts) == (Job.Status.FAILED, 1)
    assert document.error.startswith("The model couldn't read this document")
