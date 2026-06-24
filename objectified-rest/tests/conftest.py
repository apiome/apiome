"""Shared pytest fixtures for objectified-rest tests."""

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Monorepo root (parent of ``objectified-rest/``)."""
    return Path(__file__).resolve().parents[2]


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
    """
    # Some test modules import the app as ``app.*`` and others as ``src.app.*``; these resolve to
    # distinct module objects with distinct ``db`` singletons. Stub the guard predicate on whichever
    # are importable so the default-allow holds regardless of import style.
    allow = lambda *a, **k: True  # noqa: E731 - tiny stub
    for module_path in ("app.database", "src.app.database"):
        try:
            module = __import__(module_path, fromlist=["db"])
        except Exception:
            continue
        monkeypatch.setattr(module.db, "user_has_permission", allow)
    yield
