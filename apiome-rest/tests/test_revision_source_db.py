"""Reading captured sources against Postgres — COA-5.4 (#7080).

Runs the three reads of :mod:`app.revision_source` and the version queries that leave the source
text out on the real tables (V402, V403). Skips when no database with V403 is reachable. Like
``test_original_documents_db`` these tests commit; the fixtures remove what they wrote.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from app.original_documents import store_original, store_original_fileset
from app.revision_source import (
    ORIGIN_LEGACY,
    ORIGIN_STORE,
    attach_revision_source,
    has_revision_source,
    revision_source,
    source_from_row,
)
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision
from tests.test_original_documents_db import _sha
from tests.test_original_documents_db import ctx as documents_ctx  # noqa: F401 - adds the db-backed store

pytestmark = pytest.mark.requires_db


@pytest.fixture
def ctx(documents_ctx: Dict[str, Any]) -> Dict[str, Any]:  # noqa: F811
    """The seeded tenant, project and revision with a ``db``-backed document store."""
    return documents_ctx

SDL = "type Query { ping: String }"
OPENAPI = "openapi: 3.1.0\ninfo:\n  title: Pets\n  version: 1.0.0\npaths: {}\n"


def _set_metadata(ctx: Dict[str, Any], format_metadata: Dict[str, Any], source_format: str = "graphql") -> None:
    """Write the revision's ``source_format`` and ``format_metadata`` and commit."""
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "UPDATE apiome.versions SET source_format = %s, format_metadata = %s::jsonb WHERE id = %s::uuid",
            (source_format, json.dumps(format_metadata), ctx["version"]),
        )
    ctx["conn"].commit()


def _capture(ctx: Dict[str, Any], text: str) -> None:
    """Store ``text`` as the revision's original and record the pointer, as an adapter import does."""
    stored = store_original(ctx["tenant"], ctx["version"], text, database=ctx["db"], store=ctx["store"])
    assert stored is not None
    _set_metadata(ctx, {"sourceLabel": "schema.graphql", "sourceDocument": stored.pointer()})


def _read(ctx: Dict[str, Any], **kwargs: Any):
    return revision_source(ctx["db"], ctx["store"], ctx["tenant"], ctx["version"], **kwargs)


def test_a_stored_original_is_read_from_the_store(ctx) -> None:
    _capture(ctx, SDL)
    source = _read(ctx)
    assert (source.text, source.origin, source.format) == (SDL, ORIGIN_STORE, "graphql")
    assert source.digest == _sha(SDL.encode()) and not source.decomposed


def test_a_stored_fileset_is_read_with_its_files(ctx) -> None:
    stored = store_original_fileset(
        ctx["tenant"],
        ctx["version"],
        {"a.proto": b'syntax = "proto3";\n', "b.proto": b'syntax = "proto3";\nmessage B {}\n'},
        root="a.proto",
        database=ctx["db"],
        store=ctx["store"],
    )
    _set_metadata(ctx, {"intakeKind": "archive", "sourceDocument": stored.pointer()}, "protobuf")
    source = _read(ctx)
    assert source.root == "a.proto" and set(source.members) == {"a.proto", "b.proto"}
    assert source.text == 'syntax = "proto3";\n' and source.digest == stored.content_sha256


def test_the_legacy_column_is_read_when_there_is_no_original(ctx) -> None:
    _set_metadata(ctx, {"sourceContent": SDL, "intakeKind": "file"})
    source = _read(ctx)
    assert (source.text, source.origin) == (SDL, ORIGIN_LEGACY)


def test_a_decomposed_import_is_only_read_for_provenance(ctx) -> None:
    store_original(ctx["tenant"], ctx["version"], OPENAPI, database=ctx["db"], store=ctx["store"])
    assert _read(ctx) is None
    assert _read(ctx, decomposed=True).text == OPENAPI
    assert has_revision_source(ctx["db"], ctx["tenant"], ctx["version"]) is False
    assert has_revision_source(ctx["db"], ctx["tenant"], ctx["version"], decomposed=True) is True


def test_the_snapshot_column_is_the_fallback_for_a_decomposed_import(ctx) -> None:
    ctx["db"].record_import_snapshot(
        tenant_id=ctx["tenant"],
        version_id=ctx["version"],
        source_file="pets.yaml",
        source_format="yaml",
        source_digest="sha256:" + _sha(OPENAPI.encode()),
        source_text=OPENAPI,
        canonical_document={"openapi": "3.1.0"},
        scrub_report={},
        created_by=None,
    )
    ctx["conn"].commit()
    try:
        source = _read(ctx, decomposed=True)
        assert (source.text, source.origin, source.decomposed) == (OPENAPI, ORIGIN_LEGACY, True)
        snapshot, chain = ctx["db"].get_import_snapshot_lineage(ctx["version"], ctx["tenant"])
        assert chain == [ctx["version"]] and "source_text" not in snapshot
        assert snapshot["source_file"] == "pets.yaml"
    finally:
        with ctx["conn"].cursor() as cur:
            cur.execute("DELETE FROM apiome.version_import_snapshots WHERE version_id = %s::uuid", (ctx["version"],))
        ctx["conn"].commit()


def test_another_tenant_reads_nothing(ctx) -> None:
    _capture(ctx, SDL)
    other = "00000000-0000-4000-8000-000000000000"
    assert revision_source(ctx["db"], ctx["store"], other, ctx["version"]) is None
    assert has_revision_source(ctx["db"], other, ctx["version"], decomposed=True) is False


def test_version_projections_leave_the_source_text_out(ctx) -> None:
    _set_metadata(ctx, {"sourceContent": SDL, "sourceLabel": "schema.graphql"})
    projection = ctx["db"].get_version_source_projection(ctx["version"], ctx["tenant"])
    assert projection["format_metadata"] == {"sourceLabel": "schema.graphql"}
    row = ctx["db"].get_revision_source_row(ctx["version"], ctx["tenant"])
    assert row["format_metadata"] == {"sourceLabel": "schema.graphql"}
    attached = attach_revision_source(
        projection, tenant_id=ctx["tenant"], version_id=ctx["version"], db=ctx["db"], store=ctx["store"]
    )
    assert source_from_row(attached).text == SDL


def test_catalog_rows_say_a_source_is_captured_without_carrying_it(ctx) -> None:
    conn, db, tenant = ctx["conn"], ctx["db"], ctx["tenant"]
    with conn.cursor() as cur:
        # ``publishable`` cannot change after insert, so the catalog item is seeded as one.
        cur.execute(
            "INSERT INTO apiome.projects (tenant_id, creator_id, name, slug, publishable) "
            "VALUES (%s, %s, 'Ping', %s, false) RETURNING id::text AS id",
            (tenant, ctx["user"], f"ping-{ctx['project'][:8]}"),
        )
        item_id = cur.fetchone()["id"]
    conn.commit()
    version = str(db.create_version(item_id, ctx["user"], "1.0.0")["id"])
    item_ctx = {**ctx, "project": item_id, "version": version}
    try:
        _set_metadata(item_ctx, {"sourceLabel": "schema.graphql"})
        item = db.get_catalog_item_by_id(item_id, tenant)
        assert item["source_captured"] is False and item["latest_version_id"] == version

        _capture(item_ctx, SDL)
        item = db.get_catalog_item_by_id(item_id, tenant)
        assert item["source_captured"] is True and "sourceContent" not in item["format_metadata"]
        # A catalog item row is enough for the row readers: the source comes from the store.
        assert revision_source(db, ctx["store"], tenant, item["latest_version_id"]).text == SDL
        listed = [row for row in db.get_catalog_items_for_tenant(tenant) if str(row["id"]) == item_id]
        assert listed and listed[0]["source_captured"] is True

        _set_metadata(item_ctx, {"sourceContent": SDL})
        item = db.get_catalog_item_by_id(item_id, tenant)
        assert item["source_captured"] is True and item["format_metadata"] == {}
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM apiome.version_documents WHERE version_id = %s::uuid", (version,)
            )
            cur.execute("DELETE FROM apiome.versions WHERE project_id = %s::uuid", (item_id,))
            cur.execute("DELETE FROM apiome.projects WHERE id = %s::uuid", (item_id,))
        conn.commit()
