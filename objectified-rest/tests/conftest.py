"""Shared pytest fixtures for objectified-rest tests."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _disable_rate_limiting(monkeypatch):
    """
    Disable the per-tenant rate-limit middleware (#3612) for the test session.

    ``RateLimitMiddleware`` keeps an in-process fixed-window counter that is shared across every
    request the app handles. The route tests reuse one ``TestClient`` / app per module and hammer the
    same API-key bucket, so the cumulative request count trips the ``429`` limit partway through the
    full suite — making otherwise-passing tests fail purely as a function of suite ordering and size.
    Route tests assert endpoint behaviour, not throttling, so the limiter is switched off by default
    here. The dedicated coverage in ``test_rate_limit.py`` re-enables it explicitly (it builds its own
    app and monkeypatches ``settings`` per-test), so this default does not weaken limiter coverage.
    """
    try:
        from app.config import settings
    except Exception:
        return
    monkeypatch.setattr(settings, "rate_limit_enabled", False)


@pytest.fixture
def repo_root() -> Path:
    """Monorepo root (parent of ``objectified-rest/``)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _restore_dependency_overrides():
    """
    Snapshot and restore FastAPI dependency overrides around every test.

    Many route tests install ``app.dependency_overrides[...]`` to stub authentication and clear it in
    their own teardown. If a test body raises *before* that cleanup runs (e.g. a ``patch()`` whose
    target was renamed away in the product code), the override leaks into subsequent, unrelated tests
    and corrupts their auth context — producing order-dependent failures that pass in isolation.
    Snapshotting the overrides before the test and restoring them afterwards makes the suite
    deterministic regardless of per-test cleanup discipline.
    """
    try:
        from app.main import app
    except Exception:
        # If the app cannot be imported (pure-unit modules that never touch FastAPI), there is
        # nothing to guard; let the test run untouched.
        yield
        return
    saved = dict(app.dependency_overrides)
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(saved)


@pytest.fixture(autouse=True)
def _allow_permissions_by_default(monkeypatch):
    """
    Default the RBAC permission guard (#3611) to "allow" for route unit tests.

    Every mutating route now calls ``db.user_has_permission(...)`` via the central guard. Route unit
    tests that exercise the real ``db`` singleton (patching only the specific data methods they care
    about) would otherwise drive the guard into Postgres with synthetic ids (e.g. ``"t1"``). These
    tests assert route behaviour, not authorization, so the guard is stubbed to allow here. Tests
    that replace the whole module-level ``db`` with a mock are unaffected (the guard uses that mock),
    and the dedicated guard tests in ``test_permission_guard.py`` exercise the real predicate.

    The guard (and ``get_authenticated_user_id``) also resolve an *acting* user id before authorizing.
    For keyless (legacy) API-key callers that id comes from
    ``db.get_fallback_creator_user_id_for_tenant(tenant_id)`` — a real Postgres lookup. It is stubbed
    to return ``None`` (the "no legacy fallback user" default), which keeps the guard out of the
    database and preserves the JWT-only routes' behaviour: a keyless API key resolves to no user and
    is rejected with ``403``. Tests that need a resolvable API-key actor set ``user_id`` on their auth
    payload or patch their module-level ``db`` directly, so this default does not affect them.
    """
    allow = lambda *a, **k: True  # noqa: E731 - tiny stub
    no_fallback_actor = lambda *a, **k: None  # noqa: E731
    try:
        module = __import__("app.database", fromlist=["db"])
    except Exception:
        yield
        return
    monkeypatch.setattr(module.db, "user_has_permission", allow)
    monkeypatch.setattr(module.db, "get_fallback_creator_user_id_for_tenant", no_fallback_actor)
    yield
