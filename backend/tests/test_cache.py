from collections.abc import Iterator

import pytest
from django.test import override_settings
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from rest_framework.test import APIClient

from documents import jobs
from documents.models import Document, Extraction
from pipeline import run
from pipeline.cache import RedisStore, ResultCache
from tenants.models import Tenant
from tests.conftest import Models, client_for, image_bytes, upload


@pytest.fixture
def cache_on() -> Iterator[None]:
    with override_settings(RESULT_CACHE_ENABLED=True):
        yield


def process_again(document_id: str) -> Extraction:
    document = Document.objects.get(pk=document_id)
    return run.process(document)


@pytest.mark.usefixtures("cache_on")
def test_the_same_content_is_not_sent_to_the_models_twice(api: APIClient, models: Models) -> None:
    ocr, _ = models()
    document_id = upload(api, image_bytes()).json()["id"]
    jobs.run_once()

    again = process_again(document_id)

    assert len(ocr.calls) == 1
    assert (again.ocr_cached, again.extraction_cached) == (True, True)
    assert again.fields["total"]["value"] == 56100


@pytest.mark.usefixtures("cache_on")
def test_a_new_prompt_reruns_extraction_but_reuses_the_ocr(api: APIClient, models: Models) -> None:
    models()
    document_id = upload(api, image_bytes()).json()["id"]
    jobs.run_once()
    models(result={"total": 56100})  # what the new prompt returns

    with override_settings(PROMPT_VERSION="2"):
        again = process_again(document_id)

    assert (again.ocr_cached, again.extraction_cached) == (True, False)
    assert again.fields["total"]["value"] == 56100
    assert "prompt=2" in again.pipeline_version


@pytest.mark.usefixtures("cache_on")
def test_a_new_ocr_model_reruns_everything(api: APIClient, models: Models) -> None:
    document_id = upload(api, image_bytes()).json()["id"]
    jobs.run_once()

    with override_settings(OCR_MODEL="dots.ocr"):
        again = process_again(document_id)

    assert again.ocr_cached is False
    assert again.extraction_cached is True, "same OCR text, same extraction step"


@pytest.mark.usefixtures("cache_on")
def test_tenants_never_share_cached_results(api: APIClient, models: Models, db: None) -> None:
    upload(api, image_bytes())
    jobs.run_once()
    other = client_for(Tenant.objects.create(name="Other", slug="other"))

    other_id = upload(other, image_bytes()).json()["id"]
    jobs.run_once()

    assert Document.objects.get(pk=other_id).extractions.get().ocr_cached is False


def test_without_redis_results_are_computed() -> None:
    down = Redis(port=1, socket_connect_timeout=0.1, retry=Retry(NoBackoff(), 0))
    cache = ResultCache(RedisStore(down), ttl_seconds=60)
    calls: list[int] = []

    def compute() -> dict[str, int]:
        calls.append(1)
        return {"total": 1}

    result = cache.get_or_compute("k", compute)

    assert (result.value, result.hit, calls) == ({"total": 1}, False, [1])


def test_keys_carry_the_tenant_and_a_version_digest() -> None:
    key = ResultCache.key("ocr", "t1", "qwen2.5vl:3b;ocr-prompt=1", "abc")

    assert key.startswith("docflow:ocr:t1:") and key.endswith(":abc")
    assert key != ResultCache.key("ocr", "t1", "qwen2.5vl:3b;ocr-prompt=2", "abc")
