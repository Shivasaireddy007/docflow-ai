import threading

import pytest
from django.test import override_settings
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from rest_framework.test import APIClient

from core.ratelimit import Bucket, RateLimiter, get_limiter
from documents import jobs
from documents.models import Document, Job
from pipeline import providers
from pipeline.providers import ModelBusy
from tests.conftest import Models, image_bytes, upload


def test_a_bucket_allows_a_burst_then_refills() -> None:
    limiter = get_limiter()
    bucket = Bucket(capacity=3, rate=1000)  # refills fast enough to watch

    assert [limiter.take("burst", Bucket(3, 0.001)) == 0 for _ in range(4)] == [True, True, True, False]
    assert limiter.take("refill", bucket) == 0


def test_the_wait_says_when_the_next_token_comes() -> None:
    limiter = get_limiter()
    bucket = Bucket(capacity=1, rate=0.5)
    limiter.take("slow", bucket)

    wait = limiter.take("slow", bucket)

    assert 1.5 < wait <= 2.0


def test_concurrent_takers_never_exceed_the_capacity() -> None:
    limiter = get_limiter()
    bucket = Bucket(capacity=10, rate=0.001)
    granted: list[bool] = []

    def worker() -> None:
        for _ in range(5):
            granted.append(limiter.take("shared", bucket) == 0)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert granted.count(True) == 10


def test_without_redis_requests_are_allowed() -> None:
    down = Redis(port=1, socket_connect_timeout=0.1, retry=Retry(NoBackoff(), 0))

    assert RateLimiter(down).take("anything", Bucket(1, 1)) == 0


@override_settings(UPLOAD_RATE="2/0.001")
def test_uploads_past_the_tenant_rate_get_429_with_retry_after(api: APIClient) -> None:
    upload(api, image_bytes("1"))
    upload(api, image_bytes("2"))

    response = upload(api, image_bytes("3"))

    assert response.status_code == 429
    assert int(response["Retry-After"]) > 0
    assert Document.objects.count() == 2


@override_settings(LOGIN_RATE="2/0.001")
def test_repeated_sign_in_attempts_are_slowed_down(db: None) -> None:
    client = APIClient()
    attempts = [
        client.post(
            "/api/v1/auth/login", {"username": "asha", "password": "guess"}, format="json"
        ).status_code
        for _ in range(3)
    ]

    assert attempts == [400, 400, 429]


@override_settings(MODEL_RATE="1/0.001")
def test_a_busy_model_is_retried_later_instead_of_piling_on(
    api: APIClient, models: Models, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.ratelimit.RateLimiter.wait", lambda self, key, bucket, timeout: False)

    with pytest.raises(ModelBusy):
        providers._rate_limited("qwen2.5:7b")
    models(result=ModelBusy("qwen2.5:7b is at its request limit"))
    upload(api, image_bytes())
    jobs.run_once()

    assert Job.objects.get().status == Job.Status.QUEUED, "retried with backoff"
