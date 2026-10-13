from functools import cache

from django.conf import settings
from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry


@cache
def get_redis() -> Redis:
    # No retries: when Redis is down, callers fall back at once (cache bypassed, limits open)
    # instead of stalling every request.
    return Redis.from_url(
        settings.REDIS_URL, socket_connect_timeout=1, socket_timeout=1, retry=Retry(NoBackoff(), 0)
    )
