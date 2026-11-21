"""The document migration job against Postgres — COA-5.8 (#7084).

Runs :mod:`app.document_migration` on the real tables (``versions.format_metadata``,
``version_import_snapshots``, ``version_spec_snapshots``, ``export_job_artifact``, the document
object tables of V403 and the checkpoints of V405) with a filesystem document store in a temporary
directory. Checks the acceptance criteria:

* every migrated object verifies (its bytes hash to its SHA-256 and decode to the database copy,
  and ``verified_at`` is stamped);
* re-running is a no-op;
* an interrupted run resumes after its last checkpoint;
* ``--purge-db-copies`` drops a database copy only after the stored object verifies, is refused
  on the ``db`` backend, and leaves every reader working.

Skips when no database with V405 is reachable. These tests commit; the fixture removes what they wrote.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import uuid
import zipfile
from typing import Any, Dict, Iterator

import pytest

import app.document_migration as migration
from app.document_migration import (
    ADAPTER_SOURCE,
    EXPORT_ARTIFACT,
    FROZEN_SCHEMA,
    IMPORT_SNAPSHOT,
    MigrationOptions,
    MigrationRefused,
    run_document_migration,
)
from app.document_store import DbDocumentStore, FilesystemDocumentStore
from app.original_documents import decode_original
from app.revision_source import ORIGIN_STORE, revision_source
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision

pytestmark = pytest.mark.requires_db

OPENAPI = "openapi: 3.1.0\ninfo:\n  title: Orders\n  version: 1.0.0\npaths: {}\n"
GRAPHQL = "type Query { order(id: ID!): Order }\ntype Order { id: ID! }\n"
FROZEN = b'{"openapi":"3.1.0","info":{"title":"Orders","version":"1.0.0"},"paths":{}}'
EXPORT = b"syntax = \"proto3\";\nmessage Order { string id = 1; }\n"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip(members: Dict[str, str]) -> str:
    """A base64 zip archive holding ``members``, as an archive import keeps it."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, text in members.items():
            archive.writestr(path, text)
    return base64.standard_b64encode(buffer.getvalue()).decode("ascii")


@pytest.fixture
def ctx(stamp_env: Dict[str, Any], tmp_path, monkeypatch) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded tenant with a filesystem store and four revisions holding database copies.

    * ``adapter`` — a GraphQL source in ``format_metadata.sourceContent``;
    * ``archive`` — a base64 zip of two protobuf files;
    * ``snapshot`` — an OpenAPI import snapshot's ``source_text``;
    * ``frozen`` — a frozen schema in ``version_spec_snapshots.content``;
    plus an export artifact on the ``db`` backend.
    """
    conn, db = stamp_env["conn"], stamp_env["db"]
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('apiome.document_migration_checkpoints') AS t")
        found = cur.fetchone()
    conn.commit()
    if not found["t"]:
        pytest.skip("V405 not applied")
    monkeypatch.setattr(migration, "MAX_LISTED_ROWS", 100)

    tenant, project, user = stamp_env["tenant"], stamp_env["project"], stamp_env["user"]
    versions = {name: str(db.create_version(project, user, f"{index + 2}.0.0")["id"])
                for index, name in enumerate(("adapter", "archive", "snapshot", "frozen"))}
    archive = _zip({"api/orders.proto": 'syntax = "proto3";\nimport "api/common.proto";\n',
                    "api/common.proto": "message Id {}\n"})
    job_id = f"export-{uuid.uuid4().hex[:12]}"
    with conn.cursor() as cur:
        cur.execute("SELECT slug FROM apiome.tenants WHERE id = %s::uuid", (tenant,))
        slug = cur.fetchone()["slug"]
        cur.execute(
            "UPDATE apiome.versions SET format_metadata = %s::jsonb, source_format = 'graphql' WHERE id = %s::uuid",
            (json.dumps({"sourceContent": GRAPHQL, "sourceLabel": "orders.graphql"}), versions["adapter"]),
        )
        cur.execute(
            "UPDATE apiome.versions SET format_metadata = %s::jsonb, source_format = 'protobuf' WHERE id = %s::uuid",
            (json.dumps({"sourceContent": archive, "sourceEncoding": "base64", "intakeKind": "archive",
                         "filesetRoot": "api/orders.proto"}), versions["archive"]),
        )
        cur.execute(
            "INSERT INTO apiome.version_import_snapshots (tenant_id, version_id, source_file, source_format, "
            "source_digest, source_text, canonical_document) VALUES (%s, %s, 'orders.yaml', 'yaml', %s, %s, '{}')",
            (tenant, versions["snapshot"], "sha256:" + _sha(OPENAPI.encode()), OPENAPI),
        )
        cur.execute(
            "INSERT INTO apiome.version_spec_snapshots (version_id, content, sha256, size_bytes) "
            "VALUES (%s, %s, %s, %s)",
            (versions["frozen"], FROZEN, _sha(FROZEN), len(FROZEN)),
        )
        cur.execute(
            "INSERT INTO apiome.async_job (job_id, kind, tenant_slug, state, status) "
            "VALUES (%s, 'export', %s, 'completed', '{}')",
            (job_id, slug),
        )
        cur.execute(
            "INSERT INTO apiome.export_job_artifact (job_id, tenant_slug, content_sha256, size_bytes, media_type, "
            "filename, backend, content) VALUES (%s, %s, %s, %s, 'text/plain', 'orders.proto', 'db', %s)",
            (job_id, slug, "sha256:" + _sha(EXPORT), len(EXPORT), EXPORT),
        )
    conn.commit()
    stamp_env.update(
        versions=versions, job_id=job_id, slug=slug, archive=archive,
        store=FilesystemDocumentStore(path=str(tmp_path / "store"), prefix="apiome"),
    )
    try:
        yield stamp_env
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM apiome.async_job WHERE job_id = %s", (job_id,))
            cur.execute("DELETE FROM apiome.version_spec_snapshots WHERE version_id = ANY(%s::uuid[])",
                        (list(versions.values()),))
            cur.execute(
                "DELETE FROM apiome.version_documents d USING apiome.document_objects o "
                "WHERE o.id = d.object_id AND o.tenant_id = %s", (tenant,),
            )
            cur.execute("DELETE FROM apiome.document_objects WHERE tenant_id = %s", (tenant,))
            cur.execute("DELETE FROM apiome.document_store_blob WHERE tenant_id = %s", (tenant,))
            cur.execute("DELETE FROM apiome.document_migration_checkpoints WHERE scope = %s", (tenant,))
        conn.commit()


def _run(ctx: Dict[str, Any], **kwargs: Any):
    """Run one step for the seeded tenant only, unthrottled."""
    store = kwargs.pop("store", None) or ctx["store"]
    return run_document_migration(ctx["db"], store, MigrationOptions(tenant_id=ctx["tenant"], rate=0, **kwargs))


def _one(ctx: Dict[str, Any], sql: str, params: tuple) -> Dict[str, Any]:
    rows = ctx["db"].execute_query(sql, params)
    return dict(rows[0]) if rows else {}


def _originals(ctx: Dict[str, Any], version: str) -> list:
    return ctx["db"].execute_query(
        "SELECT d.role, d.part_path, o.sha256, o.encoding, o.backend, o.verified_at FROM apiome.version_documents d "
        "JOIN apiome.document_objects o ON o.id = d.object_id WHERE d.version_id = %s::uuid "
        "ORDER BY (d.role = 'original') DESC, d.part_path",
        (version,),
    )


def _stamps(ctx: Dict[str, Any]) -> Dict[str, int]:
    return {name: ctx["db"].get_version_content_stamp(version) for name, version in ctx["versions"].items()}


def test_copy_stores_every_source_verified_and_links_it(ctx) -> None:
    stamps = _stamps(ctx)
    report = _run(ctx).as_dict()

    assert report["failed"] == 0 and report["skipped"] == 0
    assert {name: s["counts"].get("copied", 0) for name, s in report["sources"].items()} == {
        ADAPTER_SOURCE: 2, IMPORT_SNAPSHOT: 1, FROZEN_SCHEMA: 1, EXPORT_ARTIFACT: 1,
    }
    store, tenant = ctx["store"], ctx["tenant"]

    adapter = _originals(ctx, ctx["versions"]["adapter"])
    assert [(row["role"], row["backend"]) for row in adapter] == [("original", "filesystem")]
    assert adapter[0]["verified_at"] is not None
    assert decode_original(store.get(tenant, adapter[0]["sha256"]), adapter[0]["encoding"]).decode() == GRAPHQL
    pointer = _one(ctx, "SELECT format_metadata -> 'sourceDocument' AS p FROM apiome.versions WHERE id = %s::uuid",
                   (ctx["versions"]["adapter"],))["p"]
    assert pointer["sha256"] == adapter[0]["sha256"] and pointer["contentSha256"] == _sha(GRAPHQL.encode())

    archive = _originals(ctx, ctx["versions"]["archive"])
    assert [(row["role"], row["part_path"]) for row in archive] == [
        ("original", None), ("original_part", "api/common.proto"), ("original_part", "api/orders.proto"),
    ]
    assert all(row["verified_at"] is not None for row in archive)
    source = revision_source(ctx["db"], store, tenant, ctx["versions"]["archive"])
    assert source.origin == ORIGIN_STORE and source.root == "api/orders.proto"
    assert source.members["api/common.proto"] == b"message Id {}\n"

    snapshot = _originals(ctx, ctx["versions"]["snapshot"])
    assert len(snapshot) == 1
    assert store.get(tenant, snapshot[0]["sha256"]).decode() == OPENAPI

    frozen = _one(ctx, "SELECT o.sha256, o.verified_at FROM apiome.version_documents d JOIN apiome.document_objects o "
                       "ON o.id = d.object_id WHERE d.version_id = %s::uuid AND d.role = 'frozen_schema'",
                  (ctx["versions"]["frozen"],))
    assert frozen["sha256"] == _sha(FROZEN) and frozen["verified_at"] is not None
    assert store.get(tenant, frozen["sha256"]) == FROZEN

    artifact = _one(ctx, "SELECT backend, content, storage_uri FROM apiome.export_job_artifact WHERE job_id = %s",
                    (ctx["job_id"],))
    assert artifact["backend"] == "db" and bytes(artifact["content"]) == EXPORT and artifact["storage_uri"]
    assert store.get(ctx["slug"], _sha(EXPORT)) == EXPORT

    # The copy keeps every database copy and never moves a content stamp.
    assert _one(ctx, "SELECT format_metadata ->> 'sourceContent' AS c FROM apiome.versions WHERE id = %s::uuid",
                (ctx["versions"]["adapter"],))["c"] == GRAPHQL
    assert _stamps(ctx) == stamps


def test_re_running_the_copy_is_a_no_op(ctx) -> None:
    _run(ctx)
    objects = _one(ctx, "SELECT count(*) AS n FROM apiome.document_objects WHERE tenant_id = %s", (ctx["tenant"],))

    again = _run(ctx).as_dict()

    assert again["scanned"] == 0 and again["done"] == 0
    assert _one(ctx, "SELECT count(*) AS n FROM apiome.document_objects WHERE tenant_id = %s",
                (ctx["tenant"],)) == objects


def test_a_dry_run_reports_and_writes_nothing(ctx) -> None:
    report = _run(ctx, dry_run=True).as_dict()

    assert report["done"] == 5 and report["dry_run"] is True
    assert _originals(ctx, ctx["versions"]["adapter"]) == []
    assert _one(ctx, "SELECT count(*) AS n FROM apiome.document_migration_checkpoints WHERE scope = %s",
                (ctx["tenant"],))["n"] == 0


def test_an_interrupted_run_resumes_after_its_checkpoint(ctx, monkeypatch) -> None:
    real = migration._process
    seen = []

    def interrupting(run_ctx, source, key, limiter):
        if source == ADAPTER_SOURCE and len(seen) == 1:
            raise KeyboardInterrupt
        seen.append(key)
        return real(run_ctx, source, key, limiter)

    monkeypatch.setattr(migration, "_process", interrupting)
    with pytest.raises(KeyboardInterrupt):
        _run(ctx, batch_size=1)
    checkpoint = _one(ctx, "SELECT last_key, counts, completed_at FROM apiome.document_migration_checkpoints "
                           "WHERE scope = %s AND step = 'copy' AND source = %s", (ctx["tenant"], ADAPTER_SOURCE))
    assert checkpoint["last_key"] == seen[0] and checkpoint["completed_at"] is None
    assert checkpoint["counts"]["copied"] == 1

    monkeypatch.setattr(migration, "_process", real)
    resumed = _run(ctx, batch_size=1).as_dict()

    adapter = resumed["sources"][ADAPTER_SOURCE]
    assert adapter["resumed_after"] == seen[0]
    assert adapter["counts"] == {"scanned": 1, "copied": 1, "bytes": adapter["counts"]["bytes"]}
    assert resumed["failed"] == 0
    checkpoint = _one(ctx, "SELECT counts, completed_at FROM apiome.document_migration_checkpoints "
                           "WHERE scope = %s AND step = 'copy' AND source = %s", (ctx["tenant"], ADAPTER_SOURCE))
    assert checkpoint["counts"]["copied"] == 2 and checkpoint["completed_at"] is not None


def test_a_store_copy_that_does_not_read_back_fails_and_links_nothing(ctx, monkeypatch) -> None:
    store = ctx["store"]
    real_get = store.get
    monkeypatch.setattr(store, "get", lambda tenant, sha256: real_get(tenant, sha256) + b"corrupt")

    report = _run(ctx, sources=(ADAPTER_SOURCE,)).as_dict()

    assert report["failed"] == 2 and report["done"] == 0
    assert {row["status"] for row in report["rows"]} == {"failed"}
    assert _originals(ctx, ctx["versions"]["adapter"]) == []


def test_a_revision_whose_stored_original_differs_is_skipped(ctx) -> None:
    from app.original_documents import store_original

    store_original(ctx["tenant"], ctx["versions"]["adapter"], "type Query { other: String }\n",
                   database=ctx["db"], store=DbDocumentStore(prefix="apiome", database=ctx["db"]))

    report = _run(ctx, sources=(ADAPTER_SOURCE,)).as_dict()

    rows = {row["key"]: row for row in report["rows"]}
    assert rows[ctx["versions"]["adapter"]]["detail"] == "original-differs"
    assert [row["backend"] for row in _originals(ctx, ctx["versions"]["adapter"])] == ["db"]


def test_purge_drops_database_copies_only_after_they_verify(ctx) -> None:
    _run(ctx)
    stamps = _stamps(ctx)

    dry = _run(ctx, purge_db_copies=True, dry_run=True).as_dict()
    assert dry["done"] == 5
    report = _run(ctx, purge_db_copies=True).as_dict()

    assert report["done"] == 5 and report["failed"] == 0 and report["skipped"] == 0
    fmd = _one(ctx, "SELECT format_metadata AS f FROM apiome.versions WHERE id = %s::uuid",
               (ctx["versions"]["archive"],))["f"]
    assert "sourceContent" not in fmd and "sourceEncoding" not in fmd and fmd["sourceDocument"]["parts"] == 2
    assert _one(ctx, "SELECT source_text FROM apiome.version_import_snapshots WHERE version_id = %s::uuid",
                (ctx["versions"]["snapshot"],))["source_text"] is None
    assert _one(ctx, "SELECT content FROM apiome.version_spec_snapshots WHERE version_id = %s::uuid",
                (ctx["versions"]["frozen"],))["content"] is None
    artifact = _one(ctx, "SELECT backend, content FROM apiome.export_job_artifact WHERE job_id = %s", (ctx["job_id"],))
    assert artifact == {"backend": "object_store", "content": None}
    assert _stamps(ctx) == stamps

    # Every reader still finds its document, now only in the store.
    source = revision_source(ctx["db"], ctx["store"], ctx["tenant"], ctx["versions"]["adapter"])
    assert source.origin == ORIGIN_STORE and source.text == GRAPHQL
    snapshot = revision_source(ctx["db"], ctx["store"], ctx["tenant"], ctx["versions"]["snapshot"], decomposed=True)
    assert snapshot.text == OPENAPI

    assert _run(ctx, purge_db_copies=True).as_dict()["scanned"] == 0


def test_purge_keeps_a_database_copy_whose_object_is_missing(ctx) -> None:
    _run(ctx, sources=(FROZEN_SCHEMA,))
    ctx["store"].delete(ctx["tenant"], _sha(FROZEN))

    report = _run(ctx, purge_db_copies=True, sources=(FROZEN_SCHEMA,)).as_dict()

    assert report["failed"] == 1 and report["done"] == 0
    assert bytes(_one(ctx, "SELECT content FROM apiome.version_spec_snapshots WHERE version_id = %s::uuid",
                      (ctx["versions"]["frozen"],))["content"]) == FROZEN


def test_purge_is_refused_on_the_db_backend(ctx) -> None:
    with pytest.raises(MigrationRefused):
        _run(ctx, purge_db_copies=True, store=DbDocumentStore(prefix="apiome", database=ctx["db"]))


def test_the_db_backend_copies_originals_but_not_export_artifacts(ctx) -> None:
    report = _run(ctx, store=DbDocumentStore(prefix="apiome", database=ctx["db"])).as_dict()

    assert report["sources"][ADAPTER_SOURCE]["counts"]["copied"] == 2
    assert report["sources"][EXPORT_ARTIFACT]["note"]
    assert _one(ctx, "SELECT storage_uri FROM apiome.export_job_artifact WHERE job_id = %s",
                (ctx["job_id"],))["storage_uri"] is None


def test_originals_on_another_backend_are_copied_to_the_current_one(ctx) -> None:
    _run(ctx, sources=(ADAPTER_SOURCE,), store=DbDocumentStore(prefix="apiome", database=ctx["db"]))
    assert {row["backend"] for row in _originals(ctx, ctx["versions"]["adapter"])} == {"db"}

    report = _run(ctx, sources=(ADAPTER_SOURCE,)).as_dict()

    assert report["sources"][ADAPTER_SOURCE]["counts"]["copied"] == 2
    assert {row["backend"] for row in _originals(ctx, ctx["versions"]["adapter"])} == {"filesystem"}
