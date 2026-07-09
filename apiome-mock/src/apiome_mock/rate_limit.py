"""Token-bucket rate limiter keyed by tenant + client IP (#4420, SIM-1.5)."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_update: float


class TokenBucketRateLimiter:
    """Thread-safe in-process token bucket.

    Each key receives ``rate_per_second`` sustained throughput with a burst capacity of one
    second's worth of tokens (minimum 1).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}

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
