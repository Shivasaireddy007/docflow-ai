import json
from pathlib import Path

import pytest
from django.core.management import call_command
from django.test import Client, override_settings
from rest_framework.test import APIClient

from documents import jobs
from documents.models import Document
from review.models import AuditEvent
from tenants.models import Tenant
from tests.conftest import RECEIPT_FIELDS, Models, image_bytes, upload


@pytest.mark.django_db(transaction=True)  # load_demo truncates, as it does on a fresh server
def test_demo_data_round_trips_through_export_and_load(
    api: APIClient, models: Models, tmp_path: Path, tenant: Tenant
) -> None:
    upload(api, image_bytes("good"))
    jobs.run_once()
    models(result={**RECEIPT_FIELDS, "total": 194000})
    upload(api, image_bytes("doubtful"))
    jobs.run_once()
    fixture = tmp_path / "documents.json"

    call_command("export_demo", "acme", "--out", str(fixture))
    call_command("load_demo", "--data", str(fixture))

    assert len(json.loads(fixture.read_text())["documents"]) == 2
    demo = Tenant.objects.get()
    assert demo.slug == "demo"
    statuses = sorted(Document.objects.filter(tenant=demo).values_list("status", flat=True))
    assert statuses == ["approved", "needs_review"], "decided again by the rules"
    assert AuditEvent.objects.filter(action="extracted").count() == 2
    browser = Client()
    assert browser.post("/api/v1/auth/login", {"username": "demo", "password": "demo-password"},
                        content_type="application/json").status_code == 200  # fmt: skip


@override_settings(DEMO_MODE=True)
def test_the_demo_refuses_uploads_and_reprocessing(api: APIClient, tenant: Tenant) -> None:
    response = upload(api, image_bytes())

    assert response.status_code == 403
    assert "no models" in response.json()["detail"]


def test_the_review_app_is_served_for_its_routes(tmp_path: Path, db: None) -> None:
    (tmp_path / "index.html").write_text('<div id="root"></div>')

    with override_settings(WEB_DIR=str(tmp_path)):
        from importlib import reload

        import config.urls

        reload(config.urls)
        from django.urls import clear_url_caches

        clear_url_caches()
        try:
            page = Client().get("/review/123")
            api = Client().get("/api/v1/nothing-here")
        finally:
            with override_settings(WEB_DIR=None):
                reload(config.urls)
                clear_url_caches()

    assert b'<div id="root">' in b"".join(page.streaming_content)  # type: ignore[attr-defined]
    assert api.status_code in (401, 404), "API paths never fall through to the app"
