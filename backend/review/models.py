from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.db.models import Q

from documents.models import Document, Extraction
from review import rules as rule_engine
from tenants.models import Tenant


class RuleSet(models.Model):
    """One version of a tenant's rules. Versions are never edited; publishing creates the next one."""

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="rule_sets")
    version = models.PositiveIntegerField()
    rules = models.JSONField()
    is_active = models.BooleanField(default=True)
    note = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "version"], name="uniq_rule_set_version"),
            models.UniqueConstraint(
                fields=["tenant"], condition=Q(is_active=True), name="one_active_rule_set"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.tenant} rules v{self.version}"

    @classmethod
    def active_for(cls, tenant: Tenant) -> "RuleSet":
        """The tenant's active rules; a tenant without any starts on the defaults."""
        if active := cls.objects.filter(tenant=tenant, is_active=True).first():
            return active
        return cls.publish(tenant, rule_engine.DEFAULT_RULES, user=None, note="Default rules")

    @classmethod
    def publish(cls, tenant: Tenant, rules: list[dict[str, Any]], user: Any, note: str = "") -> "RuleSet":
        rule_engine.validate(rules)
        if rules is not rule_engine.DEFAULT_RULES:
            cls.active_for(tenant)  # the history starts with the defaults the tenant ran on
        with transaction.atomic():
            # Locking the tenant row serialises publishes, so two can't take the same version number.
            Tenant.objects.select_for_update().get(pk=tenant.pk)
            latest = cls.objects.filter(tenant=tenant).order_by("-version").first()
            cls.objects.filter(tenant=tenant, is_active=True).update(is_active=False)
            return cls.objects.create(
                tenant=tenant,
                version=(latest.version + 1) if latest else 1,
                rules=rules,
                note=note,
                created_by=user,
            )


class Decision(models.Model):
    """What happened to a document after an extraction: decided by the rules or by a reviewer.

    Rows are never updated; a reviewer's decision is a new row after the automatic one, so the
    history of every document can be replayed.
    """

    class Outcome(models.TextChoices):
        AUTO_APPROVED = "auto_approved"
        NEEDS_REVIEW = "needs_review"
        APPROVED = "approved"
        REJECTED = "rejected"

    APPROVED_OUTCOMES = (Outcome.AUTO_APPROVED, Outcome.APPROVED)

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="decisions")
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="decisions")
    extraction = models.ForeignKey(Extraction, on_delete=models.CASCADE, related_name="decisions")
    rule_set = models.ForeignKey(RuleSet, on_delete=models.PROTECT, related_name="decisions")
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    rule_results = models.JSONField(default=list)
    final_fields = models.JSONField(default=dict, help_text="The values the decision stands on")
    final_line_items = models.JSONField(default=list)
    corrections = models.JSONField(default=dict, help_text='{"total": {"from": 194000, "to": 174600}}')
    reason = models.TextField(blank=True)
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    # NULL, not "": a receipt without merchant/date/total has nothing to compare for duplicates.
    fingerprint = models.CharField(max_length=300, null=True, blank=True)  # noqa: DJ001
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["document", "-created_at"], name="decision_latest"),
            models.Index(
                fields=["tenant", "fingerprint"],
                name="decision_approved_fingerprint",
                condition=Q(outcome__in=["auto_approved", "approved"]),
            ),
        ]

    def __str__(self) -> str:
        return f"{self.document_id}: {self.outcome}"


class AuditEvent(models.Model):
    """Who did what to which document, and when. Append-only: a database trigger refuses
    UPDATE and DELETE, so not even a bug or a careless admin can rewrite history."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, related_name="audit_events")
    document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.PROTECT, related_name="audit_events"
    )
    actor = models.CharField(max_length=120, help_text='"pipeline", "api-key:<prefix>" or "user:<username>"')
    action = models.CharField(max_length=40)
    data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["document", "created_at"], name="audit_document"),
            models.Index(fields=["tenant", "-created_at"], name="audit_tenant_recent"),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor} {self.action}"
