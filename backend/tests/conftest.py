import io
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from django.test import override_settings
from PIL import Image, ImageDraw
from rest_framework.test import APIClient

from core.redis import get_redis
from documents.storage import get_storage
from pipeline import run
from tenants.models import ApiKey, Tenant

pytest_plugins = ["tests.aws_fixtures"]

RECEIPT_TEXT = """KOPI KENANGAN
12/03/2024
Es Kopi Susu      2 x 18.000   36.000
Roti Bakar        1 x 15.000   15.000
SUBTOTAL                        51.000
PB1 10%                          5.100
TOTAL                        Rp 56.100
"""

RECEIPT_FIELDS: dict[str, Any] = {
    "merchant_name": "Kopi Kenangan",
    "receipt_date": "12/03/2024",
    "currency": "IDR",
    "subtotal": 51000,
    "tax": 5100,
    "service_charge": None,
    "discount": None,
    "total": 56100,
    "line_items": [
        {"description": "Es Kopi Susu", "quantity": 2, "unit_price": 18000, "amount": 36000},
        {"description": "Roti Bakar", "quantity": 1, "unit_price": 15000, "amount": 15000},
    ],
}


@pytest.fixture(autouse=True)
def isolated_redis() -> Iterator[None]:
    """A Redis database of its own, emptied for every test. The result cache is off unless a
    test turns it on: fake models answer the same text for different files, which the cache
    would (rightly) treat as the same content."""
    url = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:6379/14")
    with override_settings(REDIS_URL=url, RESULT_CACHE_ENABLED=False):
        get_redis.cache_clear()
        get_redis().flushdb()
        yield
    get_redis.cache_clear()


@pytest.fixture(autouse=True)
def isolated_storage(tmp_path: Path) -> Iterator[Path]:
    with override_settings(STORAGE_BACKEND="filesystem", STORAGE_ROOT=tmp_path / "storage"):
        get_storage.cache_clear()
        yield tmp_path / "storage"
    get_storage.cache_clear()


class FakeOcr:
    model = "fake-ocr"

    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[list[bytes]] = []

    def __call__(self, pages: list[bytes]) -> str:
        self.calls.append(pages)
        return self.text


class FakeExtractor:
    model = "fake-llm"

    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result

    def __call__(self, text: str) -> dict[str, Any]:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


Models = Callable[..., tuple[FakeOcr, FakeExtractor]]


@pytest.fixture
def models(monkeypatch: pytest.MonkeyPatch) -> Models:
    """Replaces the model providers: models(text=..., result=...) returns the fakes in use."""

    def install(
        text: str = RECEIPT_TEXT, result: dict[str, Any] | Exception | None = None
    ) -> tuple[FakeOcr, FakeExtractor]:
        fakes = FakeOcr(text), FakeExtractor(RECEIPT_FIELDS if result is None else result)
        monkeypatch.setattr(run, "providers", lambda: fakes)
        return fakes

    install()
    return install


@pytest.fixture
def tenant(db: None) -> Tenant:
    return Tenant.objects.create(name="Acme Expenses", slug="acme")


def client_for(tenant: Tenant) -> APIClient:
    _, plaintext = ApiKey.issue(tenant, "test")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Api-Key {plaintext}")
    return client


@pytest.fixture
def api(tenant: Tenant) -> APIClient:
    return client_for(tenant)


def image_bytes(text: str = "TOTAL 56.100", fmt: str = "PNG", size: tuple[int, int] = (400, 600)) -> bytes:
    image = Image.new("RGB", size, "white")
    ImageDraw.Draw(image).text((20, 20), text, fill="black")
    out = io.BytesIO()
    image.save(out, format=fmt)
    return out.getvalue()


def pdf_bytes(pages: int) -> bytes:
    images = [Image.new("RGB", (300, 400), "white") for _ in range(pages)]
    out = io.BytesIO()
    images[0].save(out, format="PDF", save_all=True, append_images=images[1:])
    return out.getvalue()


def upload(client: APIClient, data: bytes, name: str = "receipt.png") -> Any:
    return client.post("/api/v1/documents", {"file": _named(data, name)}, format="multipart")


def _named(data: bytes, name: str) -> io.BytesIO:
    buffer = io.BytesIO(data)
    buffer.name = name
    return buffer
