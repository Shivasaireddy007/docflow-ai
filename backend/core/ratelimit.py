"""Token-bucket rate limits shared by every process, kept in Redis.

A bucket holds up to `capacity` tokens and refills at `rate` per second; each request takes one.
The check-and-take is one Lua script, so concurrent API processes and workers can't both take
the last token, and it uses Redis's clock, so servers with drifting clocks agree.

If Redis is unreachable the limit is skipped (fail open): losing the limiter shouldn't take the
API down with it.
"""

import logging
import time
from dataclasses import dataclass

from redis import Redis
from redis.exceptions import RedisError

from core.redis import get_redis

log = logging.getLogger(__name__)

TAKE = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local now_parts = redis.call('TIME')
local now = tonumber(now_parts[1]) * 1000 + math.floor(tonumber(now_parts[2]) / 1000)
local state = redis.call('HMGET', KEYS[1], 'tokens', 'at')
local tokens = tonumber(state[1]) or capacity
local at = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + (now - at) / 1000 * rate)
local allowed = 0
local wait_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  wait_ms = math.ceil((1 - tokens) / rate * 1000)
end
redis.call('HSET', KEYS[1], 'tokens', tostring(tokens), 'at', now)
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate * 1000) + 1000)
return {allowed, wait_ms}
"""


@dataclass(frozen=True)
class Bucket:
    capacity: float
    rate: float

    @classmethod
    def parse(cls, spec: str) -> "Bucket":
        """ "30/0.5" -> up to 30 at once, refilling 0.5 per second."""
        capacity, rate = spec.split("/")
        return cls(float(capacity), float(rate))


class RateLimiter:
    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._take = redis.register_script(TAKE)

    def take(self, key: str, bucket: Bucket) -> float:
        """Takes a token. Returns 0 if allowed, otherwise the seconds until one is available."""
        try:
            allowed, wait_ms = self._take(keys=[f"docflow:limit:{key}"], args=[bucket.capacity, bucket.rate])
        except RedisError:
            log.warning("Rate limiter unavailable; allowing %s", key, exc_info=True)
            return 0.0
        return 0.0 if allowed else wait_ms / 1000

    def wait(self, key: str, bucket: Bucket, timeout: float) -> bool:
        """Blocks until a token is available or `timeout` seconds pass (for workers calling models)."""
        deadline = time.monotonic() + timeout
        while (wait := self.take(key, bucket)) > 0:
            if time.monotonic() + wait > deadline:
                return False
            time.sleep(wait)
        return True


def get_limiter() -> RateLimiter:
    return RateLimiter(get_redis())
