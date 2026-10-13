"""Content-addressed cache for model results.

A key is (tenant, step version, SHA-256 of exactly what the model sees):

    docflow:ocr:<tenant>:<sha256 of model+prompt version>:<sha256 of the page images>
    docflow:extraction:<tenant>:<...>:<sha256 of the OCR text>

So the same content is never sent to a model twice; changing a model or a prompt changes the
version part and invalidates exactly the results that step produced (a new extraction prompt
re-runs extraction but reuses the OCR). Keys are per tenant, so one tenant can't learn from
timing what another has uploaded. If Redis is down, results are computed as if uncached.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from django.conf import settings
from redis import Redis
from redis.exceptions import RedisError

from core.redis import get_redis

log = logging.getLogger(__name__)
T = TypeVar("T")


def sha256(*parts: bytes) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update(hashlib.sha256(part).digest())
    return digest.hexdigest()


@dataclass(frozen=True)
class Cached:
    value: Any
    hit: bool


class ResultCache:
    def __init__(self, redis: Redis | None, ttl_seconds: int) -> None:
        self.redis = redis
        self.ttl = ttl_seconds

    @staticmethod
    def key(step: str, tenant_id: object, version: str, content_hash: str) -> str:
        version_hash = hashlib.sha256(version.encode()).hexdigest()[:16]
        return f"docflow:{step}:{tenant_id}:{version_hash}:{content_hash}"

    def get_or_compute(self, key: str, compute: Callable[[], T]) -> Cached:
        if self.redis is not None:
            try:
                if (stored := self.redis.get(key)) is not None:
                    return Cached(json.loads(stored), hit=True)
            except RedisError:
                log.warning("Result cache unavailable; computing %s", key, exc_info=True)
        value = compute()
        if self.redis is not None:
            try:
                self.redis.set(key, json.dumps(value), ex=self.ttl)
            except RedisError:
                log.warning("Could not store %s in the result cache", key, exc_info=True)
        return Cached(value, hit=False)


def get_result_cache() -> ResultCache:
    return ResultCache(get_redis() if settings.RESULT_CACHE_ENABLED else None, settings.RESULT_CACHE_SECONDS)
