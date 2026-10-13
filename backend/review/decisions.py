"""Turning extractions into decisions: automatically by the rules, or by a reviewer."""

from datetime import timedelta
from typing import Any

from django.contrib.auth.models import User
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from documents.models import Document, Extraction
from pipeline import schema
from review import audit
from review import rules as rule_engine
from review.models import Decision, RuleSet

CLAIM_MINUTES = 15


class Conflict(Exception):
    """The document changed under the caller: already decided, or claimed by someone else."""


def _values(extraction: Extraction) -> dict[str, Any]:
    return {name: field.get("value") for name, field in extraction.fields.items()}


def _duplicate_of(document: Document, fingerprint: str | None) -> str | None:
    if fingerprint is None:
        return None
    match = (
        Decision.objects.filter(
            tenant=document.tenant, fingerprint=fingerprint, outcome__in=Decision.APPROVED_OUTCOMES
        )
        .exclude(document=document)
        .values_list("document_id", flat=True)
        .first()
    )
    return str(match) if match else None


def _lock_fingerprint(document: Document, fingerprint: str | None) -> None:
    """Serialises decisions on the same receipt, so two copies processed at once can't both pass
    the duplicate check. A transaction-scoped advisory lock: released on commit or rollback."""
    if fingerprint is not None:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))", [f"{document.tenant_id}:{fingerprint}"]
            )


def decide_automatically(document: Document, extraction: Extraction) -> Decision:
    """Applies the tenant's active rules: approved if every rule passes, otherwise sent to review."""
    rule_set = RuleSet.active_for(document.tenant)
    fingerprint = rule_engine.fingerprint(extraction.fields)
    with transaction.atomic():
        _lock_fingerprint(document, fingerprint)
        context = rule_engine.Context(
            document_confidence=extraction.confidence,
            find_duplicate=lambda _fields: _duplicate_of(document, fingerprint),
            today=timezone.localdate(),
        )
        results = rule_engine.evaluate(rule_set.rules, extraction.fields, context)
        approved = all(r.passed for r in results)
        decision = Decision.objects.create(
            tenant=document.tenant,
            document=document,
            extraction=extraction,
            rule_set=rule_set,
            outcome=Decision.Outcome.AUTO_APPROVED if approved else Decision.Outcome.NEEDS_REVIEW,
            rule_results=[r.as_dict() for r in results],
            final_fields=_values(extraction),
            final_line_items=extraction.line_items,
            fingerprint=fingerprint if approved else None,
        )
        Document.objects.filter(pk=document.pk).update(
            status=Document.Status.APPROVED if approved else Document.Status.NEEDS_REVIEW,
            claimed_by=None,
            claim_expires_at=None,
        )
        audit.record(
            document.tenant,
            audit.PIPELINE,
            "auto_approved" if approved else "sent_to_review",
            document,
            rules_version=rule_set.version,
            confidence=extraction.confidence,
            failed=[r.rule_id for r in results if not r.passed],
        )
    return decision


def claim_next(user: User) -> Document | None:
    """The reviewer's current document, or the oldest unclaimed one in their tenant's queue.

    Claims are leases: one abandoned in a closed browser tab is free again after CLAIM_MINUTES.
    SKIP LOCKED lets several reviewers ask at once without waiting on each other.
    """
    tenant = user.membership.tenant
    now = timezone.now()
    queue = Document.objects.filter(tenant=tenant, status=Document.Status.NEEDS_REVIEW)
    with transaction.atomic():
        mine = queue.select_for_update().filter(claimed_by=user, claim_expires_at__gt=now).first()
        document = mine or (
            queue.select_for_update(skip_locked=True)
            .filter(Q(claimed_by__isnull=True) | Q(claim_expires_at__lte=now))
            .order_by("created_at")
            .first()
        )
        if document is None:
            return None
        document.claimed_by = user
        document.claim_expires_at = now + timedelta(minutes=CLAIM_MINUTES)
        document.save(update_fields=["claimed_by", "claim_expires_at", "updated_at"])
        if mine is None:
            audit.record(tenant, audit.actor_of(user), "claimed", document)
    return document


def _correct(name: str, value: Any) -> Any:
    """Reviewer input goes through the same parsing as model output."""
    if name in schema.AMOUNT_FIELDS:
        return schema.to_amount(value)
    if name in schema.DATE_FIELDS:
        return schema.to_date(value)
    return schema.to_text(value)


def decide_by_reviewer(
    document_id: str, user: User, *, approve: bool, corrections: dict[str, Any], reason: str = ""
) -> Decision:
    """Records a reviewer's approve/reject. Raises Conflict if the document was decided already
    or is claimed by someone else, so two people can't overwrite each other's decision."""
    tenant = user.membership.tenant
    with transaction.atomic():
        document = Document.objects.select_for_update().filter(tenant=tenant, pk=document_id).first()
        if document is None:
            raise Document.DoesNotExist
        if document.status != Document.Status.NEEDS_REVIEW:
            raise Conflict(f"This document is already {document.status.replace('_', ' ')}.")
        if document.claimed_by_id not in (None, user.pk) and (
            document.claim_expires_at is not None and document.claim_expires_at > timezone.now()
        ):
            raise Conflict(f"{document.claimed_by} is reviewing this document.")

        previous = document.decisions.select_related("extraction").order_by("-created_at").first()
        if previous is None:
            raise Conflict("This document has no extraction to review yet.")
        final = dict(previous.final_fields)
        changes: dict[str, dict[str, Any]] = {}
        for name, raw in corrections.items():
            value = _correct(name, raw)
            if final.get(name) != value:
                changes[name] = {"from": final.get(name), "to": value}
                final[name] = value

        fingerprint = (
            rule_engine.fingerprint({k: {"value": v} for k, v in final.items()}) if approve else None
        )
        decision = Decision.objects.create(
            tenant=tenant,
            document=document,
            extraction=previous.extraction,
            rule_set=previous.rule_set,
            outcome=Decision.Outcome.APPROVED if approve else Decision.Outcome.REJECTED,
            rule_results=previous.rule_results,
            final_fields=final,
            final_line_items=previous.final_line_items,
            corrections=changes,
            reason=reason,
            decided_by=user,
            fingerprint=fingerprint,
        )
        document.status = Document.Status.APPROVED if approve else Document.Status.REJECTED
        document.claimed_by = None
        document.claim_expires_at = None
        document.save(update_fields=["status", "claimed_by", "claim_expires_at", "updated_at"])
        audit.record(
            tenant,
            audit.actor_of(user),
            "approved" if approve else "rejected",
            document,
            corrections=changes,
            reason=reason,
        )
    return decision
