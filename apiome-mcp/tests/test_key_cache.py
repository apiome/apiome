"""DBP-1.21 (#7204): the verified-key cache and the ``last_used_at`` throttle."""

from __future__ import annotations

from apiome_mcp.key_cache import CachedKey, LastUsedThrottle, VerifiedKeyCache, secret_digest

_SECRET = "apiome_mcp_" + "s" * 40


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_an_entry_lives_for_the_ttl_and_is_keyed_by_digest_not_secret() -> None:
    clock = _Clock()
    cache = VerifiedKeyCache(ttl_seconds=lambda: 60, max_entries=lambda: 10, clock=clock)
    entry = CachedKey(key_id="k1", key_hash="$2b$hash")
    cache.put(_SECRET, entry)
    assert cache.get(_SECRET) == entry
    assert _SECRET not in repr(cache._entries)  # only the digest is stored
    assert secret_digest(_SECRET) in cache._entries
    clock.now += 61
    assert cache.get(_SECRET) is None


def test_a_zero_ttl_turns_the_cache_off() -> None:
    cache = VerifiedKeyCache(ttl_seconds=lambda: 0, max_entries=lambda: 10)
    cache.put(_SECRET, CachedKey("k1", "h"))
    assert cache.get(_SECRET) is None
    assert len(cache) == 0


def test_invalidate_forgets_every_secret_of_a_key() -> None:
    cache = VerifiedKeyCache(ttl_seconds=lambda: 60, max_entries=lambda: 10)
    cache.put(_SECRET, CachedKey("k1", "h"))
    cache.put(_SECRET + "2", CachedKey("k1", "h"))
    cache.put(_SECRET + "3", CachedKey("k2", "h"))
    cache.invalidate("k1")
    assert cache.get(_SECRET) is None and cache.get(_SECRET + "2") is None
    assert cache.get(_SECRET + "3") == CachedKey("k2", "h")


def test_the_cache_is_bounded_oldest_first() -> None:
    cache = VerifiedKeyCache(ttl_seconds=lambda: 60, max_entries=lambda: 2)
    for n in range(3):
        cache.put(f"{_SECRET}{n}", CachedKey(f"k{n}", "h"))
    assert len(cache) == 2
    assert cache.get(f"{_SECRET}0") is None
    assert cache.get(f"{_SECRET}2") is not None


def test_last_used_is_due_once_per_interval() -> None:
    clock = _Clock()
    throttle = LastUsedThrottle(interval_seconds=60, clock=clock)
    assert throttle.due("k1") is True
    assert throttle.due("k1") is False
    assert throttle.due("k2") is True
    clock.now += 59
    assert throttle.due("k1") is False
    clock.now += 2
    assert throttle.due("k1") is True
