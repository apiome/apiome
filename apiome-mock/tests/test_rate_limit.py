"""Tests for the token-bucket rate limiter (#4420, SIM-1.5)."""

from __future__ import annotations

from apiome_mock.rate_limit import TokenBucketRateLimiter


def test_token_bucket_allows_sustained_rate() -> None:
    limiter = TokenBucketRateLimiter()
    now = 1000.0
    allowed, retry = limiter.check("demo:1.2.3.4", 5.0, now=now)
    assert allowed is True
    assert retry == 0


def test_token_bucket_blocks_burst_over_capacity() -> None:
    limiter = TokenBucketRateLimiter()
    now = 2000.0
    key = "demo:9.9.9.9"
    for _ in range(5):
        allowed, _ = limiter.check(key, 5.0, now=now)
        assert allowed is True
    allowed, retry = limiter.check(key, 5.0, now=now)
    assert allowed is False
    assert retry >= 1


def test_token_bucket_refills_over_time() -> None:
    limiter = TokenBucketRateLimiter()
    key = "demo:127.0.0.1"
    now = 3000.0
    for _ in range(5):
        limiter.check(key, 5.0, now=now)
    allowed, _ = limiter.check(key, 5.0, now=now)
    assert allowed is False
    allowed, retry = limiter.check(key, 5.0, now=now + 1.0)
    assert allowed is True
    assert retry == 0
