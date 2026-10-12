from pathlib import Path
from typing import Any

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from documents import jobs, views
from documents.models import Document, Job
from tenants.models import Tenant
from tests.conftest import Models, client_for, image_bytes, pdf_bytes, upload


def test_upload_stores_the_file_and_queues_it(api: APIClient, isolated_storage: Path) -> None:
    data = image_bytes()

    response = upload(api, data, "lunch.png")

    assert response.status_code == 201
    body = response.json()
    assert (body["filename"], body["content_type"], body["status"], body["duplicate"]) == (
        "lunch.png", "image/png", "queued", False,
    )  # fmt: skip
    document = Document.objects.get(pk=body["id"])
    assert (isolated_storage / document.storage_key).read_bytes() == data
    assert document.jobs.get().status == Job.Status.QUEUED


def test_uploading_the_same_file_again_returns_the_existing_document(api: APIClient) -> None:
    data = image_bytes()
    first = upload(api, data).json()

    again = upload(api, data, "renamed.png")

    assert again.status_code == 200
    assert (again.json()["id"], again.json()["duplicate"]) == (first["id"], True)
    assert Job.objects.count() == 1


def test_tenants_never_share_documents(api: APIClient, db: None) -> None:
    other = client_for(Tenant.objects.create(name="Other", slug="other"))
    data = image_bytes()
    mine = upload(api, data).json()

    theirs = upload(other, data)

    assert theirs.status_code == 201, "same file, different tenant: a separate document"
    assert other.get(f"/api/v1/documents/{mine['id']}").status_code == 404
    assert [d["id"] for d in other.get("/api/v1/documents").json()["results"]] == [theirs.json()["id"]]


@pytest.mark.parametrize(
    ("data", "status"),
    [
        (b"just some text pretending to be a png", 415),
        (b"\x89PNG\r\n\x1a\n" + b"garbage" * 20, 415),
        (b"%PDF-1.7 not really a pdf", 415),
    ],
)
def test_files_are_checked_by_their_contents(api: APIClient, data: bytes, status: int) -> None:
    assert upload(api, data, "receipt.png").status_code == status
    assert not Document.objects.exists()


def test_large_and_long_documents_are_refused(api: APIClient) -> None:
    with override_settings(MAX_UPLOAD_BYTES=1000):
        assert upload(api, image_bytes(size=(800, 800))).status_code == 413
    with override_settings(MAX_PAGES=3):
        response = upload(api, pdf_bytes(pages=4), "statement.pdf")
    assert response.status_code == 400
    assert "up to 3 pages" in response.json()["file"]


def test_a_pdf_records_its_pages(api: APIClient) -> None:
    body = upload(api, pdf_bytes(pages=2), "invoice.pdf").json()

    assert (body["content_type"], body["page_count"]) == ("application/pdf", 2)


def test_simultaneous_uploads_of_one_file_create_one_document(
    api: APIClient, tenant: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = image_bytes()

    class RacingStorage:
        """Another request inserts the same document while this one is storing the file."""

        def put(self, key: str, payload: bytes, content_type: str) -> None:
            Document.objects.create(
                tenant=tenant, sha256=key.rsplit("/", 1)[1], filename="other.png",
                content_type="image/png", size_bytes=len(payload), storage_key=key,
            )  # fmt: skip

    monkeypatch.setattr(views, "get_storage", lambda: RacingStorage())

    response = upload(api, data)

    assert (response.status_code, response.json()["duplicate"]) == (200, True)
    assert Document.objects.count() == 1


def test_detail_shows_the_latest_extraction(api: APIClient, models: Models) -> None:
    document_id = upload(api, image_bytes()).json()["id"]
    jobs.run_once()

    body: dict[str, Any] = api.get(f"/api/v1/documents/{document_id}").json()

    assert body["status"] == "extracted"
    extraction = body["extraction"]
    assert extraction["fields"]["total"]["value"] == 56100
    assert extraction["fields"]["receipt_date"]["value"] == "2024-03-12"
    assert len(extraction["line_items"]) == 2
    assert extraction["pipeline_version"].startswith("ocr=")


def test_list_filters_by_status(api: APIClient, models: Models) -> None:
    upload(api, image_bytes("one"))
    jobs.run_once()
    upload(api, image_bytes("two"))

    queued = api.get("/api/v1/documents?status=queued").json()
    extracted = api.get("/api/v1/documents?status=extracted").json()

    assert (queued["count"], extracted["count"]) == (1, 1)


def test_reprocess_queues_a_new_run_once(api: APIClient, models: Models) -> None:
    document_id = upload(api, image_bytes()).json()["id"]

    assert api.post(f"/api/v1/documents/{document_id}/reprocess").status_code == 409, "still queued"
    jobs.run_once()
    response = api.post(f"/api/v1/documents/{document_id}/reprocess")

    assert (response.status_code, response.json()["status"]) == (202, "queued")
    assert Job.objects.filter(document_id=document_id).count() == 2
