"""REST features read a revision's document through the cache — COA-5.14 (#7090).

The readers every feature now uses, with the in-memory database and the filesystem store of
``tests/test_rendered_documents.py``:

* :func:`app.rendered_documents.revision_openapi` — a warm read loads no class or property row,
  a cold read stores the document, and a revision the cache cannot serve is rendered directly;
* :func:`app.compatibility_engine.openapi_for_revision` — the same, and a component-pin override
  is rendered without the cache and never stored;
* :func:`app.rendered_documents.render_uncached` — refuses an undeclared reason;
* :func:`app.rendered_documents.write_through` — stores the document of a just-written revision;
* the helpers of the mock, preservation, source review, versions and Swagger UI routes read
  through :func:`revision_openapi`.

The same reads against Postgres, with the query count, are in
``tests/test_revision_openapi_readers_db.py``.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

import app.compatibility_engine as engine
import app.rendered_documents as rendered
from app.rendered_documents import (
    REASON_COMPONENT_PINS_OVERRIDE,
    REASON_SOURCE_APPLY,
    render_uncached,
    revision_openapi,
    write_through,
)
from tests.test_rendered_documents import TENANT, VERSION, FakeDatabase
from tests.test_rendered_documents import db as fake_db  # noqa: F401 - the in-memory database
from tests.test_rendered_documents import store as fs_store  # noqa: F401 - a filesystem store

#: The row a route passes: what ``get_version_by_id`` returns (no project description/metadata).
ROW: Dict[str, Any] = {
    "id": VERSION,
    "version_id": "1.0.0",
    "project_id": "project-1",
    "project_slug": "orders",
    "metadata": None,
}


@pytest.fixture
def db(fake_db: FakeDatabase) -> FakeDatabase:  # noqa: F811
    """The fake database with the project lookup ``openapi_for_revision`` falls back to."""
    fake_db.get_project_by_id = lambda project_id, tenant_id: {  # type: ignore[attr-defined]
        "slug": "orders",
        "description": "Orders API",
        "metadata": {"team": "payments"},
    }
    return fake_db


@pytest.fixture
def store(fs_store, monkeypatch):  # noqa: F811
    """The filesystem store, installed as the process-wide document store."""
    monkeypatch.setattr(rendered, "get_document_store", lambda: fs_store)
    return fs_store


# ───────────────────────────── revision_openapi ─────────────────────────────


def test_a_cold_read_renders_and_stores_and_a_warm_read_loads_no_rows(db, store) -> None:
    cold = revision_openapi(ROW, "acme", TENANT, database=db)

    assert cold["info"]["title"] == "orders API"
    assert cold["info"]["description"] == "Orders API"
    assert cold["components"]["schemas"]["Order"]["properties"]["id"] == {"type": "string"}
    assert db.renders() == 1 and len(db.documents) == 1

    db.calls.clear()
    warm = revision_openapi(ROW, "acme", TENANT, database=db)

    assert warm == cold
    assert db.calls == ["context", "find"]


def test_each_read_is_a_fresh_copy_the_caller_may_change(db, store) -> None:
    first = revision_openapi(ROW, "acme", TENANT, database=db)
    first["info"]["title"] = "changed"

    assert revision_openapi(ROW, "acme", TENANT, database=db)["info"]["title"] == "orders API"


def test_a_revision_the_cache_does_not_know_is_rendered_from_the_row(db, store) -> None:
    db.context = None
    row = dict(ROW, project_description="From the row", project_metadata=None)

    spec = revision_openapi(row, "acme", TENANT, database=db)

    assert spec["info"] == {"title": "orders API", "version": "1.0.0", "description": "From the row"}
    assert db.documents == {}


def test_without_a_tenant_the_cache_is_skipped(db, store) -> None:
    spec = revision_openapi(ROW, "acme", None, database=db)

    assert spec["info"]["title"] == "orders API"
    assert "context" not in db.calls and db.documents == {}


def test_the_direct_render_uses_the_slug_and_label_the_caller_gives(db, store) -> None:
    db.context = None
    row = {"id": VERSION, "metadata": None}

    spec = revision_openapi(row, "acme", TENANT, database=db, project_slug="billing", version_label="2.0.0")

    assert (spec["info"]["title"], spec["info"]["version"]) == ("billing API", "2.0.0")


def test_a_failing_cached_render_falls_back_and_raises_the_generators_error(db, store, monkeypatch) -> None:
    def explode(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("generator failed")

    monkeypatch.setattr(rendered, "build_live_spec", explode)

    with pytest.raises(RuntimeError, match="generator failed"):
        revision_openapi(ROW, "acme", TENANT, database=db)


def test_a_stand_in_database_is_not_mistaken_for_a_cached_revision(store) -> None:
    """A ``MagicMock`` database answers every call; the cache must not serve from it."""
    stand_in = MagicMock()
    stand_in.get_classes_for_version.return_value = []
    stand_in.get_properties_for_classes.return_value = {}

    assert rendered.rendered_document(VERSION, tenant_id=TENANT, database=stand_in, store=store) is None
    stand_in.find_version_document.assert_not_called()


# ───────────────────────────── openapi_for_revision ─────────────────────────────


def test_openapi_for_revision_reads_a_warm_revision_without_loading_rows(db, store) -> None:
    with patch.object(engine, "db", db):
        cold = engine.openapi_for_revision(dict(ROW), "acme", TENANT)
        db.calls.clear()
        warm = engine.openapi_for_revision(dict(ROW), "acme", TENANT)

    assert warm == cold
    assert db.calls == ["context", "find"]


def test_openapi_for_revision_generates_when_the_cache_cannot_serve(db, store) -> None:
    db.context = None

    with patch.object(engine, "db", db):
        spec = engine.openapi_for_revision(dict(ROW), "acme", TENANT)

    assert spec["info"]["description"] == "Orders API"
    assert spec["x-metadata"] == {"team": "payments"}
    assert db.documents == {}


def test_openapi_for_revision_raises_404_when_the_project_is_gone(db, store) -> None:
    db.context = None
    db.get_project_by_id = lambda project_id, tenant_id: None  # type: ignore[attr-defined]

    with patch.object(engine, "db", db), pytest.raises(HTTPException) as raised:
        engine.openapi_for_revision(dict(ROW), "acme", TENANT)

    assert raised.value.status_code == 404


def test_a_pin_override_is_rendered_without_the_cache_and_never_stored(db, store) -> None:
    with patch.object(engine, "db", db), patch.object(engine, "render_uncached", wraps=render_uncached) as uncached:
        engine.openapi_for_revision(dict(ROW), "acme", TENANT)
        stored = dict(db.documents)
        db.calls.clear()

        spec = engine.openapi_for_revision(dict(ROW), "acme", TENANT, component_pin_rows=[])

    assert spec["components"]["schemas"]["Order"]
    assert "context" not in db.calls and "find" not in db.calls
    assert db.documents == stored
    assert uncached.call_args.kwargs["reason"] == REASON_COMPONENT_PINS_OVERRIDE
    assert uncached.call_args.kwargs["component_pin_rows"] == []


def test_read_revision_openapi_reports_a_hit_for_a_document_another_reader_stored(db, store) -> None:
    with patch.object(engine, "db", db):
        engine.openapi_for_revision(dict(ROW), "acme", TENANT)
        read = engine.read_revision_openapi(dict(ROW), "acme", TENANT)

    assert read.cache == engine.CACHE_HIT and read.sha256


# ───────────────────────────── render_uncached, write_through ─────────────────────────────


def test_render_uncached_refuses_a_reason_that_is_not_declared() -> None:
    with pytest.raises(ValueError, match="Unknown uncached render reason"):
        render_uncached(
            reason="because", tenant_slug="acme", project_slug="orders", version_label="1.0.0",
            classes=[], all_properties={},
        )


def test_render_uncached_generates_from_the_rows_it_is_given() -> None:
    spec = render_uncached(
        reason=REASON_SOURCE_APPLY,
        tenant_slug="acme",
        project_slug="orders",
        version_label="1.0.0",
        classes=[{"id": "c1", "name": "Order", "description": None, "schema": {"type": "object"}}],
        all_properties={"c1": []},
        project_description="Orders",
        paths_data=[],
        security_scheme_rows=[],
        server_rows=[{"url": "https://api.example.com"}],
    )

    assert spec["info"] == {"title": "orders API", "version": "1.0.0", "description": "Orders"}
    assert spec["servers"] == [{"url": "https://api.example.com"}]
    assert list(spec["components"]["schemas"]) == ["Order"]


def test_write_through_stores_the_document_so_the_next_read_is_warm(db, store) -> None:
    assert write_through(TENANT, VERSION, database=db) is True
    db.calls.clear()

    revision_openapi(ROW, "acme", TENANT, database=db)

    assert db.calls == ["context", "find"]


def test_write_through_never_raises(db, store, monkeypatch) -> None:
    monkeypatch.setattr(rendered, "build_live_spec", MagicMock(side_effect=RuntimeError("boom")))

    assert write_through(TENANT, VERSION, database=db) is False
    assert write_through(TENANT, "00000000-0000-4000-8000-000000000000", database=db) is False


# ───────────────────────────── the route helpers ─────────────────────────────


@pytest.mark.parametrize(
    ("module", "call"),
    [
        (
            "app.mock_routes",
            lambda m, row: m._build_spec_for_version(dict(row, tenant_id=TENANT), "acme", "orders", "1.0.0"),
        ),
        ("app.preservation_routes", lambda m, row: m._generated_canonical_document(row, "acme", TENANT)),
        ("app.source_review_routes", lambda m, row: m._generated_canonical_document(row, "acme", TENANT)),
        ("app.versions_routes", lambda m, row: m._generated_spec_for_version(row, "acme", TENANT)),
    ],
)
def test_the_route_helpers_read_a_warm_revision_without_loading_rows(db, store, module, call) -> None:
    import importlib

    target = importlib.import_module(module)
    with patch.object(target, "db", db):
        cold = call(target, dict(ROW))
        db.calls.clear()
        warm = call(target, dict(ROW))

    assert warm == cold and warm["info"]["description"] == "Orders API"
    assert db.calls == ["context", "find"]


def test_a_source_apply_writes_the_new_document_through(db, store) -> None:
    """The route stores the applied revision's document before it answers."""
    import asyncio

    import app.source_review_routes as routes

    body = routes.SourceApplyRequest(
        source_text='{"openapi": "3.1.0", "info": {"title": "t", "version": "1"}, "paths": {}}',
        source_format="json",
        base_digest="a" * 64,
        change_set_digest="b" * 64,
    )
    db.apply_source_change_set = MagicMock(  # type: ignore[attr-defined]
        return_value={"applied": True, "resultDigest": "c" * 64, "auditId": None, "claimCount": 0}
    )
    with patch.object(routes, "db", db), patch.object(routes, "enforce_permission"), patch.object(
        routes, "_version_or_404", return_value=dict(ROW)
    ), patch.object(routes, "_parse_candidate", return_value={}), patch.object(
        routes, "_stored_dialect", return_value="3.1"
    ), patch.object(routes, "get_authenticated_user_id", return_value="user-1"):
        asyncio.run(routes.apply_source_changes("acme", "project-1", VERSION, body, {"tenant_id": TENANT}))

    assert len(db.documents) == 1
    db.calls.clear()
    revision_openapi(ROW, "acme", TENANT, database=db)
    assert db.calls == ["context", "find"]


def test_a_source_apply_that_changed_nothing_renders_nothing(db, store) -> None:
    import asyncio

    import app.source_review_routes as routes

    body = routes.SourceApplyRequest(
        source_text="{}", source_format="json", base_digest="a" * 64, change_set_digest="b" * 64
    )
    db.apply_source_change_set = MagicMock(  # type: ignore[attr-defined]
        return_value={"applied": False, "noChanges": True, "resultDigest": "c" * 64}
    )
    with patch.object(routes, "db", db), patch.object(routes, "enforce_permission"), patch.object(
        routes, "_version_or_404", return_value=dict(ROW)
    ), patch.object(routes, "_parse_candidate", return_value={}), patch.object(
        routes, "_stored_dialect", return_value="3.1"
    ), patch.object(routes, "get_authenticated_user_id", return_value="user-1"):
        asyncio.run(routes.apply_source_changes("acme", "project-1", VERSION, body, {"tenant_id": TENANT}))

    assert db.documents == {} and db.renders() == 0
