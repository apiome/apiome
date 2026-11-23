"""The public Browse directory cache and the route that reads through it (DBP-1.16, #7199).

``GET /v1/browse/tenants`` is anonymous and used to recount the public catalog on every call. These
tests pin the contract: one read per interval and query, nothing stored on failure, an interval of
``0`` turns it off, and the response's ``Cache-Control`` says the same thing the cache does.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import browse_public_cache
from app.config import settings
from app.main import app

client = TestClient(app)

_STATS = {"tenant_count": 2, "project_count": 5, "version_count": 12}


def _tenant(slug: str) -> dict:
    """A tenant row as ``Database.list_public_browse_tenants`` returns it."""
    return {
        "slug": slug,
        "name": slug.title(),
        "project_count": 1,
        "published_versions": 1,
        "latest_version": "1.0.0",
        "latest_activity_at": None,
        "protocols": ["rest"],
        "formats": ["openapi-3.1"],
    }


def _seed(mock_db, slugs=("acme",)) -> None:
    """Give the patched database a directory to return."""
    mock_db.get_public_browse_directory_stats.return_value = dict(_STATS)
    mock_db.list_public_browse_tenants.return_value = [_tenant(s) for s in slugs]
    mock_db.get_public_browse_tenant_facets.return_value = {"protocols": {"rest": 1}, "formats": {}}


# ─────────────────────────────── the cache itself ───────────────────────────────


def test_a_value_is_loaded_once_and_then_served():
    calls = []

    def load():
        calls.append(1)
        return {"n": len(calls)}

    assert browse_public_cache.cached("k", load) == {"n": 1}
    assert browse_public_cache.cached("k", load) == {"n": 1}
    assert len(calls) == 1
    assert browse_public_cache.cache_size() == 1


@pytest.mark.parametrize("empty", [None, [], {}, 0])
def test_an_empty_value_is_a_hit_too(empty):
    calls = []

    def load():
        calls.append(1)
        return empty

    assert browse_public_cache.cached("empty", load) == empty
    assert browse_public_cache.cached("empty", load) == empty
    assert len(calls) == 1, "an empty directory must not be re-read on every request"


def test_keys_are_kept_apart():
    assert browse_public_cache.cached(("tenants", "a"), lambda: "A") == "A"
    assert browse_public_cache.cached(("tenants", "b"), lambda: "B") == "B"
    assert browse_public_cache.cached(("tenants", "a"), lambda: "changed") == "A"


def test_a_failed_load_is_not_stored():
    def boom():
        raise RuntimeError("database is down")

    with pytest.raises(RuntimeError):
        browse_public_cache.cached("k", boom)
    assert browse_public_cache.cache_size() == 0
    assert browse_public_cache.cached("k", lambda: "recovered") == "recovered"


def test_an_interval_of_zero_turns_the_cache_off(monkeypatch):
    monkeypatch.setattr(settings, "browse_public_cache_ttl_seconds", 0)
    calls = []
    for _ in range(3):
        browse_public_cache.cached("k", lambda: calls.append(1))
    assert len(calls) == 3
    assert browse_public_cache.cache_size() == 0
    assert browse_public_cache.cache_control_header() == "no-store"


@pytest.mark.parametrize(
    "configured,expected",
    [(120, 120.0), (60.5, 60.5), (3600, 300.0), (-5, 0.0), (0, 0.0), ("soon", 0.0), (None, 0.0)],
)
def test_the_interval_is_clamped_to_zero_through_five_minutes(monkeypatch, configured, expected):
    monkeypatch.setattr(settings, "browse_public_cache_ttl_seconds", configured)
    assert browse_public_cache.ttl_seconds() == expected


def test_the_default_interval_is_two_minutes():
    assert settings.browse_public_cache_ttl_seconds == 120.0
    assert browse_public_cache.cache_control_header() == "public, max-age=120"


def test_the_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(settings, "browse_public_cache_max_entries", 3)
    for i in range(10):
        browse_public_cache.cached(("tenants", i), lambda i=i: i)
    assert browse_public_cache.cache_size() <= 3


def test_invalidate_all_drops_every_value():
    browse_public_cache.cached("k", lambda: 1)
    browse_public_cache.invalidate_all()
    assert browse_public_cache.cache_size() == 0


# ─────────────────────────────── the route ───────────────────────────────


def test_a_repeated_directory_request_runs_no_query():
    """The statement budget: a warm request reads nothing from the database."""
    with patch("app.browse_public_routes.db") as mock_db:
        _seed(mock_db)
        first = client.get("/v1/browse/tenants")
        second = client.get("/v1/browse/tenants")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert mock_db.get_public_browse_directory_stats.call_count == 1
    assert mock_db.list_public_browse_tenants.call_count == 1
    assert mock_db.get_public_browse_tenant_facets.call_count == 1


def test_the_response_states_the_cache_interval(monkeypatch):
    with patch("app.browse_public_routes.db") as mock_db:
        _seed(mock_db)
        assert client.get("/v1/browse/tenants").headers["cache-control"] == "public, max-age=120"
        monkeypatch.setattr(settings, "browse_public_cache_ttl_seconds", 60)
        assert client.get("/v1/browse/tenants").headers["cache-control"] == "public, max-age=60"
        monkeypatch.setattr(settings, "browse_public_cache_ttl_seconds", 0)
        assert client.get("/v1/browse/tenants").headers["cache-control"] == "no-store"


def test_with_the_cache_off_every_request_reads_the_database(monkeypatch):
    monkeypatch.setattr(settings, "browse_public_cache_ttl_seconds", 0)
    with patch("app.browse_public_routes.db") as mock_db:
        _seed(mock_db)
        client.get("/v1/browse/tenants")
        client.get("/v1/browse/tenants")
    assert mock_db.get_public_browse_directory_stats.call_count == 2
    assert mock_db.list_public_browse_tenants.call_count == 2


def test_each_query_has_its_own_window_and_shares_the_statistics():
    with patch("app.browse_public_routes.db") as mock_db:
        _seed(mock_db)
        for query in (
            "",
            "?sort=projects",
            "?search=acme",
            "?protocol=rest",
            "?format=openapi-3.1",
            "?limit=10",
            "?limit=10&offset=10",
        ):
            assert client.get(f"/v1/browse/tenants{query}").status_code == 200
    # Seven distinct windows, one statistics read, and one facet count per distinct search.
    assert mock_db.list_public_browse_tenants.call_count == 7
    assert mock_db.get_public_browse_directory_stats.call_count == 1
    assert mock_db.get_public_browse_tenant_facets.call_count == 2


def test_a_search_that_differs_only_by_surrounding_spaces_is_the_same_window():
    with patch("app.browse_public_routes.db") as mock_db:
        _seed(mock_db)
        client.get("/v1/browse/tenants", params={"search": "acme"})
        client.get("/v1/browse/tenants", params={"search": "  acme  "})
        client.get("/v1/browse/tenants", params={"search": "   "})
        client.get("/v1/browse/tenants")
    # "acme" twice → one read; blank and absent → one read.
    assert mock_db.list_public_browse_tenants.call_count == 2


def test_a_cached_window_keeps_its_has_more_answer():
    with patch("app.browse_public_routes.db") as mock_db:
        _seed(mock_db, slugs=("a", "b", "c"))
        first = client.get("/v1/browse/tenants?limit=2").json()
        second = client.get("/v1/browse/tenants?limit=2").json()
    assert first["has_more"] is True and second["has_more"] is True
    assert [t["slug"] for t in second["tenants"]] == ["a", "b"]
    # The stored rows were not shortened by the first response.
    assert mock_db.list_public_browse_tenants.return_value[2]["slug"] == "c"


def test_a_database_error_is_not_cached():
    with patch("app.browse_public_routes.db") as mock_db:
        _seed(mock_db)
        mock_db.get_public_browse_directory_stats.side_effect = RuntimeError("database is down")
        with pytest.raises(RuntimeError):
            client.get("/v1/browse/tenants")
        mock_db.get_public_browse_directory_stats.side_effect = None
        assert client.get("/v1/browse/tenants").status_code == 200
    assert mock_db.get_public_browse_directory_stats.call_count == 2


def test_member_scoped_project_lists_are_not_cached():
    """Only the anonymous directory is cached: a project list depends on who asks."""
    import inspect

    from app import browse_public_routes

    source = inspect.getsource(browse_public_routes.list_public_browse_projects)
    assert "browse_public_cache" not in source
