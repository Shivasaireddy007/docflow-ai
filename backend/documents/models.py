import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone

from tenants.models import Tenant


class Document(models.Model):
    """An uploaded file. Stored once per tenant per content hash, so re-uploads are free."""

    class Status(models.TextChoices):
        QUEUED = "queued"
        PROCESSING = "processing"
        NEEDS_REVIEW = "needs_review"
        APPROVED = "approved"
        REJECTED = "rejected"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="documents")
    sha256 = models.CharField(max_length=64)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size_bytes = models.PositiveIntegerField()
    page_count = models.PositiveSmallIntegerField(null=True, blank=True)
    storage_key = models.CharField(max_length=512)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    error = models.TextField(blank=True)
    # A reviewer's lease on the document, so two people never review the same one.
    claimed_by = models.ForeignKey(
        "auth.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="claimed_documents"
    )
    claim_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "sha256"], name="uniq_document_per_tenant")]
        indexes = [
            models.Index(fields=["tenant", "-created_at"], name="doc_tenant_recent"),
            models.Index(fields=["tenant", "status"], name="doc_tenant_status"),
        ]

    def __str__(self) -> str:
        return f"{self.filename} ({self.status})"

    def latest_extraction(self) -> "Extraction | None":
        return self.extractions.order_by("-created_at").first()


class Job(models.Model):
    """One request to process a document, claimed by workers with SKIP LOCKED.

    A job that fails is retried with backoff; after `JOB_MAX_ATTEMPTS` it stops as failed. A
    worker that dies mid-job leaves it `running` with an old `locked_at`, and another worker
    reclaims it once the lock times out.
    """

    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="jobs")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    attempts = models.PositiveSmallIntegerField(default=0)
    run_after = models.DateTimeField(default=timezone.now)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            # Only claimable rows are indexed, so the claim query stays fast as finished jobs pile up.
            models.Index(
                fields=["run_after"], name="job_claimable", condition=Q(status__in=["queued", "running"])
            ),
        ]

    def __str__(self) -> str:
        return f"Job {self.pk} for {self.document_id} ({self.status})"


class Extraction(models.Model):
    """The fields extracted from a document by one version of the pipeline."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="extractions")
    pipeline_version = models.CharField(max_length=200)
    ocr_text = models.TextField()
    fields = models.JSONField(
        help_text='{"total": {"value": 12500, "confidence": 0.93, "checks": {...}}, ...}'
    )
    line_items = models.JSONField(default=list)
    confidence = models.FloatField(help_text="Lowest confidence among the fields that were found")
    ocr_ms = models.PositiveIntegerField()
    extraction_ms = models.PositiveIntegerField()
    ocr_cached = models.BooleanField(default=False, help_text="OCR came from the result cache")
    extraction_cached = models.BooleanField(default=False, help_text="Fields came from the result cache")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["document", "-created_at"], name="extraction_latest")]

    def __str__(self) -> str:
        return f"Extraction of {self.document_id} by {self.pipeline_version}"
