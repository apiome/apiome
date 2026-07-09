"""Token-bucket rate limiter keyed by tenant + client IP (#4420, SIM-1.5)."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

_BUCKET_TTL_SECONDS: float = 300.0
_MAX_BUCKETS: int = 50_000


@dataclass
class _Bucket:
    tokens: float
    last_update: float


class TokenBucketRateLimiter:
    """Thread-safe in-process token bucket.

    Each key receives ``rate_per_second`` sustained throughput with a burst capacity of one
    second's worth of tokens (minimum 1).

    To prevent unbounded memory growth from uniquely-keyed callers, buckets that have not
    been accessed for ``_BUCKET_TTL_SECONDS`` seconds are evicted on each access, and the
    map is capped at ``_MAX_BUCKETS`` entries (oldest-by-last_update evicted first).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        self._evict_counter: int = 0
        self._evict_interval: int = 1000

    def _evict_stale(self, now: float) -> None:
        """Remove buckets inactive for longer than TTL. Called while lock is held."""
        cutoff = now - _BUCKET_TTL_SECONDS
        stale = [k for k, b in self._buckets.items() if b.last_update < cutoff]
        for k in stale:
            del self._buckets[k]

        if len(self._buckets) > _MAX_BUCKETS:
            sorted_keys = sorted(self._buckets, key=lambda k: self._buckets[k].last_update)
            for k in sorted_keys[: len(self._buckets) - _MAX_BUCKETS]:
                del self._buckets[k]

    def check(self, key: str, rate_per_second: float, now: float | None = None) -> tuple[bool, int]:
        """Consume one token when allowed.

        Returns:
            ``(allowed, retry_after_seconds)`` — ``retry_after_seconds`` is ``0`` when allowed.
        """
        if rate_per_second <= 0:
            return True, 0

        if now is None:
            now = time.monotonic()

        capacity = max(1.0, float(rate_per_second))

        with self._lock:
            self._evict_counter += 1
            if self._evict_counter >= self._evict_interval:
                self._evict_counter = 0
                self._evict_stale(now)

            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=capacity, last_update=now)
                self._buckets[key] = bucket

            elapsed = max(0.0, now - bucket.last_update)
            bucket.tokens = min(capacity, bucket.tokens + elapsed * rate_per_second)
            bucket.last_update = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0

            deficit = 1.0 - bucket.tokens
            retry_after = max(1, int(math.ceil(deficit / rate_per_second)))
            return False, retry_after
