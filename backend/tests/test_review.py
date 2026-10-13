from datetime import timedelta
from typing import Any

import pytest
from django.contrib.auth.models import User
from django.db import DatabaseError, transaction
from django.utils import timezone
from rest_framework.test import APIClient

from documents import jobs
from documents.models import Document
from review.models import AuditEvent, Decision
from tenants.models import Membership, Tenant
from tests.conftest import RECEIPT_FIELDS, Models, client_for, image_bytes, upload


def reviewer(tenant: Tenant, name: str = "asha", role: str = "reviewer") -> APIClient:
    user = User.objects.create_user(name, password="review-password")
    Membership.objects.create(user=user, tenant=tenant, role=role)
    client = APIClient()
    client.force_login(user)
    return client


def needs_review(api: APIClient, models: Models, text: str = "receipt") -> str:
    """A processed document the rules sent to review: its total is not on the receipt."""
    models(result={**RECEIPT_FIELDS, "total": 194000})
    document_id: str = upload(api, image_bytes(text)).json()["id"]
    jobs.run_once()
    return document_id


@pytest.fixture
def asha(tenant: Tenant) -> APIClient:
    return reviewer(tenant)


def test_confident_documents_are_approved_and_others_explain_why_not(
    api: APIClient, asha: APIClient, models: Models
) -> None:
    upload(api, image_bytes("good"))
    jobs.run_once()
    review_id = needs_review(api, models, "bad")

    queue = asha.get("/api/v1/review/queue").json()

    assert [item["id"] for item in queue] == [review_id]
    assert queue[0]["failed_rules"] == ["confident", "totals-add-up"]
    assert Document.objects.filter(status="approved").count() == 1


def test_a_reviewer_corrects_and_approves(api: APIClient, asha: APIClient, models: Models) -> None:
    document_id = needs_review(api, models)
    assert asha.post("/api/v1/review/next").json() == {"id": document_id}

    response = asha.post(
        f"/api/v1/review/documents/{document_id}/decision",
        {"approve": True, "corrections": {"total": "56.100"}},
        format="json",
    )

    assert response.status_code == 201
    assert response.json()["corrections"] == {"total": {"from": 194000.0, "to": 56100.0}}
    body = api.get(f"/api/v1/documents/{document_id}").json()
    assert (body["status"], body["decision"]["decided_by"]) == ("approved", "asha")
    assert body["decision"]["final_fields"]["total"] == 56100.0
    actions = list(AuditEvent.objects.filter(document_id=document_id).values_list("action", "actor"))
    assert [a for a, _ in actions] == ["uploaded", "extracted", "sent_to_review", "claimed", "approved"]
    assert actions[-1][1] == "user:asha"


def test_rejecting_needs_a_reason(api: APIClient, asha: APIClient, models: Models) -> None:
    document_id = needs_review(api, models)
    url = f"/api/v1/review/documents/{document_id}/decision"

    assert asha.post(url, {"approve": False}, format="json").status_code == 400
    response = asha.post(url, {"approve": False, "reason": "Personal expense"}, format="json")

    assert (response.status_code, response.json()["outcome"]) == (201, "rejected")


def test_two_reviewers_never_get_the_same_document(
    api: APIClient, asha: APIClient, tenant: Tenant, models: Models
) -> None:
    first, second = needs_review(api, models, "one"), needs_review(api, models, "two")
    ravi = reviewer(tenant, "ravi")

    assert asha.post("/api/v1/review/next").json()["id"] == first
    assert ravi.post("/api/v1/review/next").json()["id"] == second
    assert asha.post("/api/v1/review/next").json()["id"] == first, "keeps her current document"
    assert reviewer(tenant, "meera").post("/api/v1/review/next").status_code == 204


def test_an_abandoned_claim_expires(api: APIClient, asha: APIClient, tenant: Tenant, models: Models) -> None:
    document_id = needs_review(api, models)
    asha.post("/api/v1/review/next")
    ravi = reviewer(tenant, "ravi")
    url = f"/api/v1/review/documents/{document_id}/decision"

    blocked = ravi.post(url, {"approve": True}, format="json")
    Document.objects.filter(pk=document_id).update(claim_expires_at=timezone.now() - timedelta(minutes=1))

    assert (blocked.status_code, blocked.json()["detail"]) == (409, "asha is reviewing this document.")
    assert ravi.post("/api/v1/review/next").json()["id"] == document_id


def test_a_document_is_decided_only_once(
    api: APIClient, asha: APIClient, tenant: Tenant, models: Models
) -> None:
    document_id = needs_review(api, models)
    url = f"/api/v1/review/documents/{document_id}/decision"
    asha.post(url, {"approve": True}, format="json")

    late = reviewer(tenant, "ravi").post(url, {"approve": False, "reason": "No"}, format="json")

    assert (late.status_code, late.json()["detail"]) == (409, "This document is already approved.")
    assert Decision.objects.filter(document_id=document_id).count() == 2, "rules, then asha"


def test_a_second_copy_of_an_approved_receipt_goes_to_review(
    api: APIClient, asha: APIClient, models: Models
) -> None:
    upload(api, image_bytes("photo one"))
    jobs.run_once()
    upload(api, image_bytes("photo two of the same receipt"))
    jobs.run_once()

    queue = asha.get("/api/v1/review/queue").json()

    assert [item["failed_rules"] for item in queue] == [["not-a-duplicate"]]


def test_reviewers_see_only_their_tenant(api: APIClient, models: Models, db: None) -> None:
    document_id = needs_review(api, models)
    outsider = reviewer(Tenant.objects.create(name="Other", slug="other"), "outsider")

    assert outsider.get("/api/v1/review/queue").json() == []
    assert outsider.get(f"/api/v1/review/documents/{document_id}").status_code == 404
    assert (
        outsider.post(
            f"/api/v1/review/documents/{document_id}/decision", {"approve": True}, format="json"
        ).status_code
        == 404
    )


def test_api_keys_cannot_review(api: APIClient, models: Models) -> None:
    document_id = needs_review(api, models)

    assert api.get("/api/v1/review/queue").status_code == 403
    assert (
        api.post(
            f"/api/v1/review/documents/{document_id}/decision", {"approve": True}, format="json"
        ).status_code
        == 403
    )


def test_review_detail_has_the_history(api: APIClient, asha: APIClient, models: Models) -> None:
    document_id = needs_review(api, models)

    body: dict[str, Any] = asha.get(f"/api/v1/review/documents/{document_id}").json()

    assert body["extraction"]["fields"]["total"]["checks"]["grounded"] is False
    assert [d["outcome"] for d in body["decisions"]] == ["needs_review"]
    assert body["decisions"][0]["rules_version"] == 1
    assert body["audit"][0]["action"] == "uploaded"


def test_only_admins_change_the_rules(asha: APIClient, tenant: Tenant) -> None:
    admin = reviewer(tenant, "admin", role="admin")
    new_rules = [{"id": "total", "type": "required", "field": "total"}]

    assert asha.post("/api/v1/rules", {"rules": new_rules}, format="json").status_code == 403
    bad = admin.post("/api/v1/rules", {"rules": [{"id": "x", "type": "nope"}]}, format="json")
    good = admin.post("/api/v1/rules", {"rules": new_rules, "note": "Only a total"}, format="json")

    assert (bad.status_code, bad.json()["rules"]) == (
        400,
        "x: unknown type 'nope'; use one of " + bad.json()["rules"].split("use one of ")[1],
    )
    assert (good.status_code, good.json()["version"]) == (201, 2)
    listing = asha.get("/api/v1/rules").json()
    assert [v["version"] for v in listing["versions"]] == [2, 1]
    assert "unique_receipt" in listing["types"]


def test_new_rules_apply_to_the_next_decision(api: APIClient, tenant: Tenant, models: Models) -> None:
    admin = reviewer(tenant, "admin", role="admin")
    admin.post(
        "/api/v1/rules", {"rules": [{"id": "total", "type": "required", "field": "total"}]}, format="json"
    )

    document_id = needs_review(api, models)

    decision = api.get(f"/api/v1/documents/{document_id}").json()["decision"]
    assert (decision["outcome"], decision["rules_version"]) == ("auto_approved", 2)


def test_stats(api: APIClient, asha: APIClient, models: Models) -> None:
    upload(api, image_bytes("good"))
    jobs.run_once()
    document_id = needs_review(api, models)
    asha.post(
        f"/api/v1/review/documents/{document_id}/decision",
        {"approve": True, "corrections": {"total": 56100}},
        format="json",
    )

    stats = asha.get("/api/v1/review/stats").json()

    assert stats["by_status"] == {"approved": 2}
    assert (stats["auto_approved_7d"], stats["decided_by_rules_7d"], stats["auto_approve_rate_7d"]) == (
        1,
        2,
        0.5,
    )
    assert (stats["reviewed_7d"], stats["corrected_7d"]) == (1, 1)


def test_the_audit_log_cannot_be_rewritten(api: APIClient, models: Models) -> None:
    needs_review(api, models)
    event = AuditEvent.objects.first()
    assert event is not None

    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        AuditEvent.objects.filter(pk=event.pk).update(action="nothing happened")
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        AuditEvent.objects.filter(pk=event.pk).delete()


def test_sign_in_flow_with_csrf(tenant: Tenant) -> None:
    user = User.objects.create_user("asha", password="review-password")
    Membership.objects.create(user=user, tenant=tenant)
    browser = APIClient(enforce_csrf_checks=True)

    wrong = browser.post("/api/v1/auth/login", {"username": "asha", "password": "nope"}, format="json")
    browser.get("/api/v1/auth/csrf")
    token = browser.cookies["csrftoken"].value
    signed_in = browser.post(
        "/api/v1/auth/login",
        {"username": "asha", "password": "review-password"},
        format="json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert (wrong.status_code, wrong.json()["detail"]) == (400, "Wrong username or password.")
    assert signed_in.json() == {
        "username": "asha",
        "role": "reviewer",
        "tenant": {"id": str(tenant.id), "name": "Acme Expenses"},
    }
    assert browser.get("/api/v1/auth/me").status_code == 200
    assert browser.post("/api/v1/review/next").status_code == 403, "unsafe requests need the CSRF header"
    token = browser.cookies["csrftoken"].value
    assert browser.post("/api/v1/review/next", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert browser.post("/api/v1/auth/logout", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert browser.get("/api/v1/auth/me").status_code == 401, "signed out"


def test_people_outside_any_tenant_cannot_sign_in(db: None) -> None:
    User.objects.create_user("stranger", password="pw-123456")

    response = APIClient().post(
        "/api/v1/auth/login", {"username": "stranger", "password": "pw-123456"}, format="json"
    )

    assert response.status_code == 400


def test_other_tenant_api_keys_see_nothing(api: APIClient, models: Models, db: None) -> None:
    document_id = needs_review(api, models)
    other = client_for(Tenant.objects.create(name="Other", slug="other"))

    assert other.get(f"/api/v1/documents/{document_id}/pages/1").status_code == 404
