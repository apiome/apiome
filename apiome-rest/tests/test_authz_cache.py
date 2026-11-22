"""Unit tests for the authorization and API-key caches — DBP-1.3 (#7186).

The database-backed behaviour (one statement, same answers, revocation) is in
``test_authz_context_db.py``; this file covers the cache mechanics without Postgres.
"""

from __future__ import annotations

from typing import Any, List
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app import authz_cache
from app.authz_cache import ApiKeyCacheEntry, AuthorizationContext, RequestMemo, TtlCache
from app.config import settings
from app.observability import ObservabilityMiddleware

TENANT = "11111111-1111-1111-1111-111111111111"
OTHER_TENANT = "22222222-2222-2222-2222-222222222222"
USER = "33333333-3333-3333-3333-333333333333"
OTHER_USER = "44444444-4444-4444-4444-444444444444"


def _ctx(*, tenant: str = TENANT, user: str = USER, slug: str = "acme", active: bool = True, **kw: Any):
    return AuthorizationContext(
        tenant_id=tenant,
        tenant_slug=slug,
        tenant_name=slug.title(),
        tenant_active=active,
        user_id=user,
        is_admin=kw.get("is_admin", False),
        is_active_member=kw.get("is_active_member", True),
        permissions=frozenset(kw.get("permissions", {"projects:view"})),
    )


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


# ───────────────────────────── AuthorizationContext ─────────────────────────────


def test_context_access_and_permissions() -> None:
    member = _ctx()
    assert member.has_tenant_access
    assert member.allows("projects", "view") and not member.allows("projects", "create")
    admin = _ctx(is_admin=True, is_active_member=False, permissions=set())
    assert admin.has_tenant_access and admin.allows("billing", "edit")
    assert not _ctx(is_active_member=False).has_tenant_access
    assert not _ctx(active=False).has_tenant_access
    assert member.tenant_row() == {"tenant_id": TENANT, "tenant_slug": "acme", "tenant_name": "Acme"}


# ───────────────────────────── TtlCache ─────────────────────────────


def test_entries_expire_after_the_ttl() -> None:
    clock = _Clock()
    cache = TtlCache(lambda: 30, lambda: 100, clock=clock)
    cache.put("k", "v")
    clock.now += 29.9
    assert cache.get("k") == "v"
    clock.now += 0.2
    assert cache.get("k") is None
    assert len(cache) == 0


def test_a_zero_ttl_disables_the_cache() -> None:
    ttl = [0]
    cache = TtlCache(lambda: ttl[0], lambda: 100)
    cache.put("k", "v")
    assert cache.get("k") is None and not cache.enabled
    ttl[0] = 5
    cache.put("k", "v")
    assert cache.get("k") == "v"
    ttl[0] = 0
    assert cache.get("k") is None


def test_a_full_cache_drops_expired_entries_then_the_oldest() -> None:
    clock = _Clock()
    cache = TtlCache(lambda: 10, lambda: 3, clock=clock)
    cache.put("old", 1)
    clock.now += 11  # "old" has expired
    cache.put("a", 2)
    cache.put("b", 3)
    cache.put("c", 4)  # room was made by dropping the expired "old"
    assert [cache.get(k) for k in ("a", "b", "c")] == [2, 3, 4]
    cache.put("d", 5)  # full of live entries: the oldest ("a") goes
    assert cache.get("a") is None and cache.get("d") == 5
    assert len(cache) == 3


def test_discard_where_and_clear() -> None:
    cache = TtlCache(lambda: 10, lambda: 0)
    for i in range(5):
        cache.put(i, i)
    assert cache.discard_where(lambda k, _v: k % 2 == 0) == 3
    assert sorted(k for k in range(5) if cache.get(k) is not None) == [1, 3]
    cache.clear()
    assert len(cache) == 0


# ───────────────────────────── resolve + invalidation ─────────────────────────────


def test_resolve_loads_once_and_serves_both_keys() -> None:
    loads: List[int] = []

    def load():
        loads.append(1)
        return _ctx()

    by_slug = authz_cache.resolve(authz_cache.slug_key(USER, "acme"), load)
    by_id = authz_cache.resolve(authz_cache.id_key(USER, TENANT.upper()), load)
    assert by_slug is by_id and len(loads) == 1


def test_resolve_does_not_remember_an_unknown_tenant() -> None:
    loads: List[int] = []

    def load():
        loads.append(1)
        return None

    key = authz_cache.slug_key(USER, "nope")
    assert authz_cache.resolve(key, load) is None
    assert authz_cache.resolve(key, load) is None
    assert len(loads) == 2


def test_an_inactive_tenant_is_never_found_by_slug() -> None:
    authz_cache.resolve(authz_cache.id_key(USER, TENANT), lambda: _ctx(active=False))
    assert authz_cache.resolve(authz_cache.slug_key(USER, "acme"), lambda: _ctx(active=False)) is None
    assert authz_cache.resolve(authz_cache.id_key(USER, TENANT), lambda: None) is not None


def test_invalidate_member_tenant_and_all() -> None:
    for tenant, slug in ((TENANT, "acme"), (OTHER_TENANT, "other")):
        for user in (USER, OTHER_USER):
            authz_cache.resolve(authz_cache.id_key(user, tenant), lambda t=tenant, u=user, s=slug: _ctx(tenant=t, user=u, slug=s))

    def cached(user: str, tenant: str) -> bool:
        return authz_cache._authz.get(authz_cache.id_key(user, tenant)) is not None

    authz_cache.invalidate_member(TENANT, USER.upper())
    assert not cached(USER, TENANT) and cached(OTHER_USER, TENANT) and cached(USER, OTHER_TENANT)
    authz_cache.invalidate_tenant(OTHER_TENANT)
    assert not cached(USER, OTHER_TENANT) and not cached(OTHER_USER, OTHER_TENANT) and cached(OTHER_USER, TENANT)
    authz_cache.invalidate_all()
    assert len(authz_cache._authz) == 0


# ───────────────────────────── the per-request memo ─────────────────────────────


def test_the_request_memo_serves_a_request_with_the_process_cache_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "auth_cache_ttl_seconds", 0)
    loads: List[int] = []

    def load():
        loads.append(1)
        return _ctx()

    memo, token = authz_cache.begin_request()
    try:
        authz_cache.resolve(authz_cache.slug_key(USER, "acme"), load)
        authz_cache.resolve(authz_cache.id_key(USER, TENANT), load)
        assert len(loads) == 1
        # A change made during the request is seen by the rest of it.
        authz_cache.invalidate_member(TENANT, USER)
        authz_cache.resolve(authz_cache.id_key(USER, TENANT), load)
        assert len(loads) == 2
    finally:
        authz_cache.end_request(memo, token)
    assert authz_cache.current_memo() is None
    authz_cache.resolve(authz_cache.id_key(USER, TENANT), load)
    assert len(loads) == 3


def test_a_closed_memo_forgets_and_stops_remembering() -> None:
    memo = RequestMemo()
    memo.put("k", _ctx())
    memo.close()
    assert memo.get("k") is None
    memo.put("k", _ctx())
    assert memo.get("k") is None


def test_the_middleware_gives_each_request_its_own_memo_and_closes_it() -> None:
    seen: List[RequestMemo] = []
    app = FastAPI()
    app.add_middleware(ObservabilityMiddleware)

    @app.get("/probe")
    def probe(request: Request) -> dict:  # a sync route runs on a worker thread
        memo = authz_cache.current_memo()
        assert memo is request.state.authz_memo
        seen.append(memo)
        return {}

    client = TestClient(app)
    assert client.get("/probe").status_code == 200
    assert client.get("/probe").status_code == 200
    assert len(seen) == 2 and seen[0] is not seen[1]
    assert all(m._closed for m in seen)


# ───────────────────────────── API keys ─────────────────────────────


def _entry(key_id: str = "k1", tenant: str = TENANT) -> ApiKeyCacheEntry:
    return ApiKeyCacheEntry(key_id=key_id, key_hash="h", tenant_id=tenant, stamped_at=0.0)


def test_api_keys_are_cached_by_digest_never_by_secret() -> None:
    authz_cache.remember_api_key("sk_secret_value", _entry())
    assert authz_cache.get_api_key("sk_secret_value").key_id == "k1"
    assert authz_cache.get_api_key("sk_secret_valuf") is None
    assert all("sk_secret_value" not in str(k) for k in authz_cache._api_keys._entries)
    assert authz_cache.api_key_digest("x") == authz_cache.api_key_digest("x") != authz_cache.api_key_digest("y")


def test_api_key_invalidation_by_key_tenant_and_secret() -> None:
    authz_cache.remember_api_key("sk_a", _entry("k1", TENANT))
    authz_cache.remember_api_key("sk_b", _entry("k2", TENANT))
    authz_cache.remember_api_key("sk_c", _entry("k3", OTHER_TENANT))
    authz_cache.invalidate_api_keys(key_id="K1")
    assert authz_cache.get_api_key("sk_a") is None and authz_cache.get_api_key("sk_b") is not None
    authz_cache.invalidate_tenant(TENANT)
    assert authz_cache.get_api_key("sk_b") is None and authz_cache.get_api_key("sk_c") is not None
    authz_cache.forget_api_key("sk_c")
    assert authz_cache.get_api_key("sk_c") is None


# ───────────────────────────── the database layer, without a database ─────────────────────────────


def test_malformed_ids_resolve_to_nothing_without_a_statement() -> None:
    from app.database import Database

    db = Database()
    db.execute_query = MagicMock(side_effect=AssertionError("no statement expected"))
    assert db.get_authorization_context("not-a-uuid", tenant_slug="acme") is None
    assert db.get_authorization_context(USER, tenant_id="t1") is None
    assert db.get_authorization_context(USER) is None
    assert db.is_user_tenant_admin("t1", USER) is False
    assert db.user_has_permission("t1", USER, "projects", "view") is False
    assert db.get_effective_permissions("t1", None) == set()


def test_a_cached_key_whose_row_no_longer_matches_is_verified_from_scratch(monkeypatch) -> None:
    from app import database as database_module
    from app.database import Database

    db = Database()
    authz_cache.remember_api_key("sk_" + "a" * 40, _entry())
    calls: List[str] = []

    def execute_query(query: str, params: Any = None):
        calls.append("by-id" if "ak.id = %s::uuid" in query else "by-prefix")
        return []

    db.execute_query = execute_query
    checkpw = MagicMock(return_value=False)
    monkeypatch.setattr(database_module.bcrypt, "checkpw", checkpw)
    assert db.validate_api_key("sk_" + "a" * 40) is None
    assert calls == ["by-id", "by-prefix"]
    assert authz_cache.get_api_key("sk_" + "a" * 40) is None


@pytest.mark.parametrize("ttl", [0, 30])
def test_the_ttl_settings_have_documented_defaults(ttl) -> None:
    from app.config import Settings

    assert Settings().auth_cache_ttl_seconds == 30.0
    assert Settings().api_key_cache_ttl_seconds == 60.0
    assert Settings(auth_cache_ttl_seconds=ttl).auth_cache_ttl_seconds == ttl
