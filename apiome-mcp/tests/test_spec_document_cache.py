"""DBP-1.22 (#7205): the size-bounded LRU of built OpenAPI documents."""

from __future__ import annotations

from apiome_mcp.spec_document_cache import DOCUMENT_CACHE, SpecDocumentCache, compact_json_size


def test_compact_json_size_counts_utf8_bytes_of_compact_json() -> None:
    assert compact_json_size({"a": 1, "b": [1, 2]}) == len('{"a":1,"b":[1,2]}')
    # Not ASCII-escaped: "é" is two bytes, as in the tool's response.
    assert compact_json_size("é") == 4


def test_get_returns_the_stored_object_and_its_size() -> None:
    cache = SpecDocumentCache(max_bytes=lambda: 100)
    doc = {"openapi": "3.1.0"}
    cache.put("k", doc, 10)
    hit = cache.get("k")
    assert hit is not None
    assert hit[0] is doc and hit[1] == 10
    assert cache.get("other") is None
    assert len(cache) == 1 and cache.size_bytes == 10


def test_least_recently_used_entries_are_dropped_to_stay_in_budget() -> None:
    cache = SpecDocumentCache(max_bytes=lambda: 100)
    cache.put("a", "A", 40)
    cache.put("b", "B", 40)
    assert cache.get("a") is not None  # a is now the most recently used
    cache.put("c", "C", 40)  # 120 > 100: b goes
    assert cache.get("b") is None
    assert cache.get("a") is not None and cache.get("c") is not None
    assert cache.size_bytes == 80


def test_a_value_larger_than_the_budget_is_not_kept() -> None:
    cache = SpecDocumentCache(max_bytes=lambda: 100)
    cache.put("small", "s", 30)
    cache.put("huge", "h", 101)
    assert cache.get("huge") is None
    assert cache.get("small") is not None  # and it evicted nothing


def test_replacing_a_key_replaces_its_size() -> None:
    cache = SpecDocumentCache(max_bytes=lambda: 100)
    cache.put("k", "v1", 60)
    cache.put("k", "v2", 20)
    assert cache.size_bytes == 20
    assert cache.get("k") == ("v2", 20)


def test_budget_zero_turns_the_cache_off() -> None:
    budget = [100]
    cache = SpecDocumentCache(max_bytes=lambda: budget[0])
    cache.put("k", "v", 10)
    budget[0] = 0  # read on every call: an operator change applies at once
    assert cache.get("k") is None
    cache.put("j", "v", 10)
    assert cache.get("j") is None


def test_clear_forgets_everything() -> None:
    cache = SpecDocumentCache(max_bytes=lambda: 100)
    cache.put("k", "v", 10)
    cache.clear()
    assert len(cache) == 0 and cache.size_bytes == 0


def test_shared_cache_defaults_to_the_setting() -> None:
    """Without a configured environment the default budget (64 MiB) applies."""
    DOCUMENT_CACHE.put("k", "v", 1)
    assert DOCUMENT_CACHE.get("k") == ("v", 1)
