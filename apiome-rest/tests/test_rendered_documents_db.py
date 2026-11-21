"""The rendered document cache against Postgres — COA-5.5 (#7081).

Runs :mod:`app.rendered_documents` on the real ``version_documents`` / ``document_objects`` tables
(V403), the real content stamp triggers and the ``db`` document store backend (V402), plus the
frozen schema object (V404). Three acceptance criteria are checked here:

* the second request for a revision issues no class, property or path query;
* an edit bumps the stamp and the next read renders again, leaving the old object in place;
* across the OpenAPI corpus the cached bytes equal the bytes of the per-class generation path
  that ``/v1/schema`` used before the cache.

Skips when no database with V404 is reachable. Like ``test_original_documents_db`` these tests
commit; the fixtures remove what they wrote.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Iterator, List, Optional

import pytest
import yaml

import app.database as database_module
from app.openapi_generator import generate_openapi_spec
from app.rendered_documents import (
    KIND_OPENAPI,
    ROLE_FROZEN_SCHEMA,
    ROLE_RENDERED_OPENAPI,
    open_frozen_schema,
    rendered_document,
    store_frozen_schema,
    warm_rendered_documents,
)
from app.spec_snapshot import load_classes_and_properties, render_spec_bytes, sha256_hex
from tests.corpus_loader import load_corpus
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision
from tests.test_original_documents_db import ctx as documents_ctx  # noqa: F401 - adds the db-backed store

pytestmark = pytest.mark.requires_db

_METHODS = ("get", "post", "put", "patch", "delete")
_CONTENT_TABLES = ("apiome.classes", "apiome.class_properties", "apiome.version_path", "apiome.path_operation")


@pytest.fixture
def ctx(documents_ctx: Dict[str, Any], monkeypatch) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded revision with a ``db``-backed store, and a log of every read the database runs.

    The generator loads paths, servers and pins through the process-wide database handle, so that
    handle is pointed at the test's connection. ``ctx["queries"]`` collects the SQL of each
    ``execute_query`` call.
    """
    with documents_ctx["conn"].cursor() as cur:
        cur.execute(
            "SELECT is_nullable FROM information_schema.columns WHERE table_schema = 'apiome' "
            "AND table_name = 'version_spec_snapshots' AND column_name = 'content'"
        )
        found = cur.fetchone()
    documents_ctx["conn"].commit()
    if not found or found["is_nullable"] != "YES":
        pytest.skip("V404 not applied")

    db = documents_ctx["db"]
    queries: List[str] = []
    run = db.execute_query

    def logged(query: str, params: tuple = None) -> list:
        queries.append(" ".join(query.split()))
        return run(query, params)

    monkeypatch.setattr(db, "execute_query", logged)
    monkeypatch.setattr(database_module, "db", db)
    documents_ctx["queries"] = queries
    with documents_ctx["conn"].cursor() as cur:
        cur.execute("SELECT slug FROM apiome.tenants WHERE id = %s::uuid", (documents_ctx["tenant"],))
        documents_ctx["tenant_slug"] = cur.fetchone()["slug"]
        cur.execute("SELECT slug FROM apiome.projects WHERE id = %s::uuid", (documents_ctx["project"],))
        documents_ctx["project_slug"] = cur.fetchone()["slug"]
    documents_ctx["conn"].commit()
    try:
        yield documents_ctx
    finally:
        documents_ctx["conn"].rollback()
        with documents_ctx["conn"].cursor() as cur:
            cur.execute(
                "DELETE FROM apiome.version_spec_snapshots s USING apiome.versions v "
                "WHERE v.id = s.version_id AND v.project_id = %s::uuid",
                (documents_ctx["project"],),
            )
        documents_ctx["conn"].commit()


def _read(ctx: Dict[str, Any], version: Optional[str] = None, kind: str = KIND_OPENAPI):
    return rendered_document(
        version or ctx["version"], kind, tenant_id=ctx["tenant"], database=ctx["db"], store=ctx["store"]
    )


def _touching(ctx: Dict[str, Any], *tables: str) -> List[str]:
    """The logged queries that name any of ``tables`` (matched as whole table names)."""
    return [q for q in ctx["queries"] if any(f"{table} " in f"{q} " for table in tables)]


def _add_property(
    ctx: Dict[str, Any], class_id: str, name: str, data: Dict[str, Any],
    parent_id: Optional[str] = None, description: Optional[str] = None,
) -> str:
    """Add a property to a class through a new project library property; return the row id."""
    db = ctx["db"]
    library = str(db.create_property(ctx["project"], f"{name}-{uuid.uuid4().hex[:12]}", None, data)["id"])
    return str(db.add_property_to_class(class_id, library, name, description, data, parent_id=parent_id)["id"])


def _seed_order(ctx: Dict[str, Any], version: Optional[str] = None) -> str:
    """Give a revision two classes with nested properties and a path; return the first class id."""
    db, version = ctx["db"], version or ctx["version"]
    order = str(db.create_class(version, "Order", {"type": "object"}, "An order")["id"])
    _add_property(ctx, order, "id", {"type": "string", "format": "uuid"}, description="Identifier")
    customer = _add_property(ctx, order, "customer", {"type": "object"})
    _add_property(ctx, order, "email", {"type": "string"}, parent_id=customer)
    line = str(db.create_class(version, "Line", {"type": "object"})["id"])
    _add_property(ctx, line, "sku", {"type": "string"})
    path = str(db.create_path(version, "/orders", {"summary": "Orders"})["id"])
    operation = str(db.create_operation(path, "GET")["id"])
    db.create_operation_description(operation, "List orders", None, "listOrders")
    return order


def _per_class_bytes(ctx: Dict[str, Any], version: str, label: str) -> bytes:
    """The document as ``/v1/schema`` built it before the cache: one property query per class."""
    db = ctx["db"]
    row = db.get_version_by_slugs(ctx["tenant_slug"], ctx["project_slug"], label)
    classes = db.get_classes_for_version(version)
    all_properties = {c["id"]: db.get_properties_for_class(c["id"]) for c in classes}
    return render_spec_bytes(
        generate_openapi_spec(
            ctx["tenant_slug"],
            ctx["project_slug"],
            label,
            classes,
            all_properties,
            row.get("project_description"),
            version_db_id=row["id"],
            revision_metadata=row.get("metadata"),
            project_metadata=row.get("project_metadata"),
        )
    )


# ───────────────────────────── acceptance: query count ─────────────────────────────


def test_the_second_request_issues_no_class_property_or_path_queries(ctx) -> None:
    _seed_order(ctx)

    first = _read(ctx)
    cold = list(ctx["queries"])
    ctx["queries"].clear()
    second = _read(ctx)

    assert first.cached is False and first.stored is True
    # Cold: one query for the classes and one for every class's properties.
    assert len([q for q in cold if "FROM apiome.classes WHERE version_id" in q]) == 1
    assert len([q for q in cold if "FROM apiome.class_properties cp" in q]) == 1
    # Warm: the context, the cache row and the db store's existence check; nothing from the
    # revision's content.
    assert second.cached is True
    assert _touching(ctx, *_CONTENT_TABLES) == []
    assert len(ctx["queries"]) == 3 and "apiome.document_store_blob" in ctx["queries"][2]
    assert second.content() == first.content()
    assert second.sha256 == first.sha256 == sha256_hex(first.content())


def test_the_cached_bytes_equal_the_per_class_generation(ctx) -> None:
    _seed_order(ctx)
    expected = _per_class_bytes(ctx, ctx["version"], "1.0.0")

    assert _read(ctx).content() == expected
    assert _read(ctx).content() == expected
    document = json.loads(expected)
    assert set(document["components"]["schemas"]) == {"Order", "Line"}
    assert "/orders" in document["paths"]


def test_the_batched_property_load_matches_the_per_class_load(ctx) -> None:
    _seed_order(ctx)
    db = ctx["db"]

    classes, batched = load_classes_and_properties(db, ctx["version"])

    assert len(classes) == 2
    for class_row in classes:
        assert batched[class_row["id"]] == db.get_properties_for_class(class_row["id"])
    assert db.get_properties_for_classes([]) == {}


# ───────────────────────────── acceptance: an edit re-renders ─────────────────────────────


def test_an_edit_bumps_the_stamp_and_the_next_read_renders_again(ctx) -> None:
    order = _seed_order(ctx)
    before = _read(ctx)
    stamp = ctx["db"].get_version_content_stamp(ctx["version"])

    _add_property(ctx, order, "total", {"type": "number"})
    after = _read(ctx)

    assert ctx["db"].get_version_content_stamp(ctx["version"]) == stamp + 1
    assert after.cached is False and after.content_stamp == stamp + 1
    assert after.sha256 != before.sha256 and b'"total"' in after.content()
    assert _read(ctx).cached is True
    # The old row and object are left for the lifecycle job.
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "SELECT d.content_stamp, o.sha256 FROM apiome.version_documents d "
            "JOIN apiome.document_objects o ON o.id = d.object_id "
            "WHERE d.version_id = %s::uuid AND d.role = %s ORDER BY d.content_stamp",
            (ctx["version"], ROLE_RENDERED_OPENAPI),
        )
        rows = cur.fetchall()
    ctx["conn"].commit()
    assert [(r["content_stamp"], r["sha256"]) for r in rows] == [(stamp, before.sha256), (stamp + 1, after.sha256)]
    assert ctx["store"].get(ctx["tenant"], before.sha256) == before.content()


def test_reading_does_not_bump_the_stamp(ctx) -> None:
    _seed_order(ctx)
    stamp = ctx["db"].get_version_content_stamp(ctx["version"])
    _read(ctx)
    _read(ctx)
    assert ctx["db"].get_version_content_stamp(ctx["version"]) == stamp


def test_a_project_rename_renders_again_although_the_stamp_did_not_move(ctx) -> None:
    _seed_order(ctx)
    before = _read(ctx)
    stamp = ctx["db"].get_version_content_stamp(ctx["version"])
    with ctx["conn"].cursor() as cur:
        cur.execute("UPDATE apiome.projects SET description = 'Renamed' WHERE id = %s::uuid", (ctx["project"],))
    ctx["conn"].commit()

    after = _read(ctx)

    assert ctx["db"].get_version_content_stamp(ctx["version"]) == stamp
    assert after.cached is False and after.sha256 != before.sha256
    assert json.loads(after.content())["info"]["description"] == "Renamed"


# ───────────────────────────── tenancy ─────────────────────────────


def test_another_tenant_cannot_read_or_record_the_revision(ctx) -> None:
    _seed_order(ctx)
    document = _read(ctx)
    with ctx["conn"].cursor() as cur:
        cur.execute("SELECT id::text AS id FROM apiome.tenants WHERE id <> %s::uuid LIMIT 1", (ctx["tenant"],))
        other = cur.fetchone()
        cur.execute(
            "SELECT id::text AS id FROM apiome.document_objects WHERE tenant_id = %s AND sha256 = %s",
            (ctx["tenant"], document.sha256),
        )
        object_id = cur.fetchone()["id"]
    ctx["conn"].commit()
    stranger = other["id"] if other else "00000000-0000-4000-8000-000000000000"

    assert rendered_document(ctx["version"], tenant_id=stranger, database=ctx["db"], store=ctx["store"]) is None
    assert ctx["db"].get_rendered_document_context(tenant_id=stranger, version_id=ctx["version"]) is None
    assert ctx["db"].get_rendered_document_context(tenant_id=ctx["tenant"], version_id="not-a-uuid") is None
    assert not ctx["db"].set_version_document(
        tenant_id=stranger, version_id=ctx["version"], role=ROLE_FROZEN_SCHEMA, object_id=object_id
    )


# ───────────────────────────── publish ─────────────────────────────


def test_warming_after_publish_serves_the_published_revision_from_the_store(ctx) -> None:
    _seed_order(ctx)
    draft = _read(ctx)
    published = ctx["db"].publish_version(ctx["version"], ctx["tenant"], ctx["user"], "public")
    assert published and published["published"]

    assert warm_rendered_documents(ctx["tenant"], ctx["version"], database=ctx["db"], store=ctx["store"]) == 1
    ctx["queries"].clear()
    document = _read(ctx)

    assert document.cached is True and document.content_stamp > draft.content_stamp
    assert _touching(ctx, *_CONTENT_TABLES) == []
    row = ctx["db"].get_version_by_slugs(ctx["tenant_slug"], ctx["project_slug"], "1.0.0")
    assert row["tenant_id"] == ctx["tenant"] and row["published"]


# ───────────────────────────── frozen schema object ─────────────────────────────


def test_a_frozen_schema_lives_in_the_store_and_the_row_keeps_the_metadata(ctx) -> None:
    _seed_order(ctx)
    db = ctx["db"]
    content = _read(ctx).content()
    sha256 = sha256_hex(content)

    row = db.insert_spec_snapshot(
        ctx["version"], content=content, sha256=sha256,
        class_count=2, property_count=4, path_count=1, frozen_by=ctx["user"],
    )
    assert store_frozen_schema(ctx["tenant"], ctx["version"], content, database=db, store=ctx["store"])
    assert db.clear_spec_snapshot_content(ctx["version"]) is True

    assert row["size_bytes"] == len(content) and str(row["sha256"]).strip() == sha256
    stored = db.get_spec_snapshot(ctx["version"], with_content=True)
    assert stored["content"] is None and stored["class_count"] == 2
    assert stored["size_bytes"] == len(content) and str(stored["sha256"]).strip() == sha256
    with open_frozen_schema(ctx["tenant"], sha256, store=ctx["store"]) as stream:
        assert stream.read() == content
    found = db.find_version_document(tenant_id=ctx["tenant"], version_id=ctx["version"], role=ROLE_FROZEN_SCHEMA)
    assert found["sha256"] == sha256 and found["size_bytes"] == len(content)

    # Unfreeze removes the row and the link; the object stays for the lifecycle job.
    assert db.delete_spec_snapshot(ctx["version"])["version_id"] is not None
    assert db.get_spec_snapshot(ctx["version"]) is None
    assert db.find_version_document(tenant_id=ctx["tenant"], version_id=ctx["version"], role=ROLE_FROZEN_SCHEMA) is None
    assert ctx["store"].exists(ctx["tenant"], sha256)
    # The rendered document of the same bytes is untouched by the unfreeze.
    assert _read(ctx).cached is True


def test_a_snapshot_row_keeps_its_bytes_until_they_are_cleared(ctx) -> None:
    db = ctx["db"]
    row = db.insert_spec_snapshot(
        ctx["version"], content=b"{}", sha256=sha256_hex(b"{}"),
        class_count=0, property_count=0, path_count=0, frozen_by=ctx["user"],
    )
    assert row["size_bytes"] == 2
    assert db.get_spec_snapshot(ctx["version"], with_content=True)["content"] == b"{}"
    assert db.clear_spec_snapshot_content("00000000-0000-4000-8000-000000000000") is False


# ───────────────────────────── acceptance: the OpenAPI corpus ─────────────────────────────


def _corpus_documents() -> List[Any]:
    """Every OpenAPI corpus file that parses to a document with schemas or paths."""
    documents = []
    for entry in load_corpus(format="openapi"):
        try:
            parsed = yaml.safe_load(entry.read_text())
        except Exception:  # noqa: BLE001 - negative and binary fixtures are not documents
            continue
        if not isinstance(parsed, dict) or "openapi" not in parsed:
            continue
        schemas = (parsed.get("components") or {}).get("schemas") or {}
        if isinstance(schemas, dict) and (schemas or parsed.get("paths")):
            documents.append(pytest.param(parsed, id=entry.path))
    return documents


def _seed_properties(
    ctx: Dict[str, Any], class_id: str, schema: Any, parent_id: Optional[str] = None, depth: int = 0
) -> None:
    """Write a schema's properties as class property rows, object children nested under them."""
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or depth > 3:
        return
    for name, child in properties.items():
        if not str(name).strip():
            continue
        data = child if isinstance(child, dict) else {"const": child}
        description = data.get("description") if isinstance(data.get("description"), str) else None
        row_id = _add_property(ctx, class_id, str(name), data, parent_id=parent_id, description=description)
        _seed_properties(ctx, class_id, data, row_id, depth + 1)


def _seed_document(ctx: Dict[str, Any], version: str, document: Dict[str, Any]) -> None:
    """Decompose an OpenAPI document into the rows the generator reads: classes, properties, paths."""
    db = ctx["db"]
    schemas = (document.get("components") or {}).get("schemas") or {}
    for name, schema in schemas.items():
        body = schema if isinstance(schema, dict) else {}
        description = body.get("description") if isinstance(body.get("description"), str) else None
        class_id = str(db.create_class(version, str(name), body, description)["id"])
        _seed_properties(ctx, class_id, body)
    paths = document.get("paths") or {}
    for pathname, item in paths.items() if isinstance(paths, dict) else []:
        item = item if isinstance(item, dict) else {}
        path_id = str(db.create_path(version, str(pathname), {"summary": item.get("summary")})["id"])
        for method in _METHODS:
            operation = item.get(method)
            if not isinstance(operation, dict):
                continue
            operation_id = str(db.create_operation(path_id, method.upper())["id"])
            db.create_operation_description(
                operation_id, operation.get("summary"), operation.get("description"), operation.get("operationId")
            )


@pytest.mark.parametrize("document", _corpus_documents())
def test_corpus_documents_render_byte_for_byte_like_the_per_class_generator(ctx, document) -> None:
    version = str(ctx["db"].create_version(ctx["project"], ctx["user"], "9.9.9")["id"])
    _seed_document(ctx, version, document)
    with ctx["conn"].cursor() as cur:
        cur.execute("UPDATE apiome.versions SET published = true WHERE id = %s::uuid", (version,))
    ctx["conn"].commit()
    expected = _per_class_bytes(ctx, version, "9.9.9")

    rendered = _read(ctx, version)
    cached = _read(ctx, version)

    assert rendered.cached is False and cached.cached is True
    assert rendered.content() == expected
    assert cached.content() == expected
    assert cached.sha256 == sha256_hex(expected) and cached.size_bytes == len(expected)
