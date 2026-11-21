"""Originals in the document store against Postgres — COA-5.3 (#7079).

Runs :mod:`app.original_documents` on the real ``document_objects`` / ``version_documents`` tables
(V403) with the ``db`` backend's real blob table (V402). Skips when no database with V403 is
reachable. Like ``test_content_stamp_db`` these tests commit; the fixture removes what they wrote.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterator

import pytest

from app.config import settings
from app.document_store import DbDocumentStore
from app.original_documents import (
    ENCODING_GZIP,
    MANIFEST_MEDIA_TYPE,
    clear_originals,
    decode_original,
    store_original,
    store_original_fileset,
)
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision

pytestmark = pytest.mark.requires_db


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def ctx(stamp_env: Dict[str, Any]) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded revision plus a ``db``-backed store; removes the tenant's objects afterwards."""
    stamp_env["store"] = DbDocumentStore(prefix="apiome", database=stamp_env["db"])
    try:
        yield stamp_env
    finally:
        conn = stamp_env["conn"]
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM apiome.version_documents d USING apiome.document_objects o "
                "WHERE o.id = d.object_id AND o.tenant_id = %s",
                (stamp_env["tenant"],),
            )
            cur.execute("DELETE FROM apiome.document_objects WHERE tenant_id = %s", (stamp_env["tenant"],))
            cur.execute("DELETE FROM apiome.document_store_blob WHERE tenant_id = %s", (stamp_env["tenant"],))
        conn.commit()


def _rows(ctx: Dict[str, Any], version: str | None = None) -> list:
    return ctx["db"].list_version_original_documents(tenant_id=ctx["tenant"], version_id=version or ctx["version"])


def _store(ctx: Dict[str, Any], text: str, version: str | None = None, **kwargs: Any):
    return store_original(
        ctx["tenant"], version or ctx["version"], text, database=ctx["db"], store=ctx["store"], **kwargs
    )


def test_an_import_records_one_original_whose_digest_matches_the_text(ctx) -> None:
    text = "openapi: 3.1.0\ninfo:\n  title: Pets\npaths: {}\n"
    stored = _store(ctx, text, filename="pets.yaml")

    assert stored is not None and stored.created is True
    rows = _rows(ctx)
    assert len(rows) == 1
    row = rows[0]
    assert (row["role"], row["part_path"]) == ("original", None)
    assert row["sha256"] == _sha(text.encode()) == stored.sha256
    assert (row["backend"], row["encoding"], row["media_type"]) == ("db", "identity", "application/yaml")
    assert row["size_bytes"] == len(text.encode())
    assert row["storage_key"] == ctx["store"].key_for(ctx["tenant"], row["sha256"])
    assert ctx["store"].get(ctx["tenant"], row["sha256"]).decode() == text


def test_storing_an_original_does_not_bump_the_content_stamp(ctx) -> None:
    before = ctx["db"].get_version_content_stamp(ctx["version"])
    _store(ctx, "a: 1\n")
    assert ctx["db"].get_version_content_stamp(ctx["version"]) == before


def test_identical_bytes_on_another_revision_reuse_the_object(ctx) -> None:
    other = str(ctx["db"].create_version(ctx["project"], ctx["user"], "1.1.0")["id"])
    first = _store(ctx, "a: 1\n")
    second = _store(ctx, "a: 1\n", other)

    assert first.created is True and second.created is False
    assert first.object_id == second.object_id
    assert _rows(ctx)[0]["object_id"] == _rows(ctx, other)[0]["object_id"]


def test_a_new_document_replaces_the_original_and_keep_existing_does_not(ctx) -> None:
    _store(ctx, "a: 1\n")
    _store(ctx, "a: 2\n")
    assert [row["sha256"] for row in _rows(ctx)] == [_sha(b"a: 2\n")]

    assert _store(ctx, "a: 3\n", keep_existing=True) is None
    assert [row["sha256"] for row in _rows(ctx)] == [_sha(b"a: 2\n")]


def test_large_text_is_gzip_coded(ctx, monkeypatch) -> None:
    monkeypatch.setattr(settings, "document_store_gzip_min_bytes", 512)
    text = "paths:\n" + "  /pets: {}\n" * 500
    stored = _store(ctx, text)

    row = _rows(ctx)[0]
    assert row["encoding"] == ENCODING_GZIP == stored.encoding
    blob = ctx["store"].get(ctx["tenant"], row["sha256"])
    assert _sha(blob) == row["sha256"] and len(blob) == row["size_bytes"]
    assert decode_original(blob, row["encoding"]).decode() == text


def test_a_fileset_is_a_manifest_plus_parts_and_a_smaller_set_drops_parts(ctx) -> None:
    members = {"api/orders.proto": b'syntax = "proto3";\n', "api/common.proto": b"message Id {}\n"}
    stored = store_original_fileset(
        ctx["tenant"], ctx["version"], members, root="api/orders.proto", database=ctx["db"], store=ctx["store"]
    )

    rows = _rows(ctx)
    assert stored.parts == 2
    assert [(row["role"], row["part_path"]) for row in rows] == [
        ("original", None),
        ("original_part", "api/common.proto"),
        ("original_part", "api/orders.proto"),
    ]
    assert rows[0]["media_type"] == MANIFEST_MEDIA_TYPE
    assert {row["part_path"]: row["sha256"] for row in rows[1:]} == {p: _sha(b) for p, b in members.items()}
    manifest = json.loads(ctx["store"].get(ctx["tenant"], rows[0]["sha256"]))
    assert manifest["root"] == "api/orders.proto" and len(manifest["members"]) == 2

    store_original_fileset(
        ctx["tenant"],
        ctx["version"],
        {"api/orders.proto": b"syntax = 'proto3';\n"},
        root="api/orders.proto",
        database=ctx["db"],
        store=ctx["store"],
    )
    assert [(row["role"], row["part_path"]) for row in _rows(ctx)] == [
        ("original", None),
        ("original_part", "api/orders.proto"),
    ]

    # A single document after a set leaves no parts behind.
    _store(ctx, "a: 1\n")
    assert [(row["role"], row["part_path"]) for row in _rows(ctx)] == [("original", None)]


def test_a_revision_of_another_tenant_is_never_linked(ctx) -> None:
    with ctx["conn"].cursor() as cur:
        cur.execute(
            "INSERT INTO apiome.tenants (name, slug) VALUES ('other', %s) RETURNING id::text AS id",
            (f"other-{ctx['tenant'][:8]}",),
        )
        other_tenant = cur.fetchone()["id"]
    ctx["conn"].commit()
    try:
        assert store_original(other_tenant, ctx["version"], "a: 1\n", database=ctx["db"], store=ctx["store"]) is None
        assert _rows(ctx) == []
        assert ctx["db"].clear_version_original_documents(tenant_id=other_tenant, version_id=ctx["version"]) == 0
    finally:
        with ctx["conn"].cursor() as cur:
            cur.execute("DELETE FROM apiome.document_objects WHERE tenant_id = %s", (other_tenant,))
            cur.execute("DELETE FROM apiome.document_store_blob WHERE tenant_id = %s", (other_tenant,))
            cur.execute("DELETE FROM apiome.tenants WHERE id = %s::uuid", (other_tenant,))
        ctx["conn"].commit()


def test_clearing_removes_the_rows_and_keeps_the_object(ctx) -> None:
    stored = _store(ctx, "a: 1\n")
    assert clear_originals(ctx["tenant"], ctx["version"], database=ctx["db"]) is True
    assert _rows(ctx) == []
    assert ctx["store"].exists(ctx["tenant"], stored.sha256)
    assert clear_originals(ctx["tenant"], ctx["version"], database=ctx["db"]) is False


def test_a_repeat_points_the_object_row_at_the_current_backend(ctx) -> None:
    kwargs = dict(tenant_id=ctx["tenant"], sha256="a" * 64, size_bytes=1, media_type="text/plain", encoding="identity")
    first = ctx["db"].upsert_document_object(backend="db", storage_key="apiome/old", **kwargs)
    second = ctx["db"].upsert_document_object(backend="filesystem", storage_key="apiome/new", **kwargs)

    assert first == second
    with ctx["conn"].cursor() as cur:
        cur.execute("SELECT backend, storage_key FROM apiome.document_objects WHERE id = %s::uuid", (first,))
        row = cur.fetchone()
    ctx["conn"].commit()
    assert (row["backend"], row["storage_key"]) == ("filesystem", "apiome/new")
