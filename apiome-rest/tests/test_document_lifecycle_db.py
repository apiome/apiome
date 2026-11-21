"""The document lifecycle against Postgres — COA-5.10 (#7086).

Runs on the real V403/V406 tables with a filesystem document store in a temporary directory:

* V406's triggers keep ``document_objects.ref_count`` equal to the live references, through link
  inserts, re-points and deletes, revision deletion and tenant deletion;
* deleting one of two revisions that share an original keeps the object; deleting both removes it
  from the index and the store;
* a deleted tenant's prefix is emptied once the grace period has passed;
* replaced renders are dropped, never-linked rows are collected, and an integrity run stamps,
  flags and audits.

Skips when no database with V406 is reachable. These tests commit; the fixture removes what they wrote.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any, Dict, Iterator

import pytest

from app import document_lifecycle as lc
from app.document_lifecycle import LifecycleOptions, LifecycleReport
from app.document_store import FilesystemDocumentStore
from app.original_documents import store_original
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision

pytestmark = pytest.mark.requires_db

OPENAPI = "openapi: 3.1.0\ninfo:\n  title: Orders\n  version: 1.0.0\npaths: {}\n"


def _one(ctx: Dict[str, Any], sql: str, params: tuple = ()) -> Dict[str, Any]:
    """Run one statement in its own committed transaction and return its first row (or ``{}``)."""
    with ctx["conn"].cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone() if cur.description else None
    ctx["conn"].commit()
    return dict(row) if row else {}


@pytest.fixture
def ctx(stamp_env: Dict[str, Any], tmp_path) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """The seeded tenant, a second revision, and a filesystem store; skip without V406."""
    if not _one(stamp_env, "SELECT to_regclass('apiome.document_lifecycle_events') AS t").get("t"):
        pytest.skip("V406 not applied")
    db = stamp_env["db"]
    stamp_env["version2"] = str(db.create_version(stamp_env["project"], stamp_env["user"], "2.0.0")["id"])
    stamp_env["store"] = FilesystemDocumentStore(path=str(tmp_path / "store"), prefix="apiome")
    try:
        yield stamp_env
    finally:
        stamp_env["conn"].rollback()
        tenant = stamp_env["tenant"]
        _one(
            stamp_env,
            "DELETE FROM apiome.version_documents d USING apiome.document_objects o "
            "WHERE o.id = d.object_id AND o.tenant_id = %s",
            (tenant,),
        )
        _one(stamp_env, "DELETE FROM apiome.document_objects WHERE tenant_id = %s", (tenant,))
        _one(stamp_env, "DELETE FROM apiome.document_lifecycle_events WHERE tenant_id = %s", (tenant,))
        _one(stamp_env, "DELETE FROM apiome.document_tenant_purges WHERE tenant_id = %s::uuid", (tenant,))
        _one(stamp_env, "UPDATE apiome.tenants SET deleted_at = NULL WHERE id = %s::uuid", (tenant,))


def _store_original(ctx, version: str, text: str = OPENAPI):
    stored = store_original(
        ctx["tenant"], version, text, filename="openapi.yaml", database=ctx["db"], store=ctx["store"]
    )
    assert stored is not None
    return stored


def _object(ctx, object_id: str) -> Dict[str, Any]:
    return _one(
        ctx,
        "SELECT ref_count, unreferenced_at, integrity_failed_at, verified_at, sha256, tenant_id "
        "FROM apiome.document_objects WHERE id = %s::uuid",
        (object_id,),
    )


def _delete_version(ctx, version: str) -> None:
    _one(ctx, "UPDATE apiome.versions SET deleted_at = now() WHERE id = %s::uuid", (version,))


def test_two_revisions_share_an_original_until_both_are_deleted(ctx) -> None:
    first = _store_original(ctx, ctx["version"])
    second = _store_original(ctx, ctx["version2"])
    assert first.object_id == second.object_id
    object_id, store, db = first.object_id, ctx["store"], ctx["db"]
    row = _object(ctx, object_id)
    assert row["ref_count"] == 2 and row["unreferenced_at"] is None

    _delete_version(ctx, ctx["version"])
    assert _object(ctx, object_id)["ref_count"] == 1
    assert lc.release_versions(db, [ctx["version"]], store=store) == 0
    assert store.exists(ctx["tenant"], row["sha256"])

    _delete_version(ctx, ctx["version2"])
    assert _object(ctx, object_id)["ref_count"] == 0
    assert lc.release_versions(db, [ctx["version2"]], store=store) == 1
    assert _object(ctx, object_id) == {}
    assert not store.exists(ctx["tenant"], row["sha256"])
    event = _one(
        ctx,
        "SELECT event, reason, sha256 FROM apiome.document_lifecycle_events " "WHERE object_id = %s::uuid",
        (object_id,),
    )
    assert event == {"event": "object_purged", "reason": "version-deleted", "sha256": row["sha256"]}


def test_restoring_a_revision_restores_its_count(ctx) -> None:
    object_id = _store_original(ctx, ctx["version"]).object_id
    _delete_version(ctx, ctx["version"])
    assert _object(ctx, object_id)["unreferenced_at"] is not None
    _one(ctx, "UPDATE apiome.versions SET deleted_at = NULL WHERE id = %s::uuid", (ctx["version"],))
    row = _object(ctx, object_id)
    assert row["ref_count"] == 1 and row["unreferenced_at"] is None


def test_re_pointing_a_link_moves_the_count(ctx) -> None:
    first = _store_original(ctx, ctx["version"]).object_id
    second = _store_original(ctx, ctx["version"], OPENAPI + "# changed\n").object_id
    assert first != second
    assert _object(ctx, first)["ref_count"] == 0
    assert _object(ctx, second)["ref_count"] == 1


def test_a_deleted_tenant_leaves_nothing_under_its_prefix(ctx) -> None:
    stored = _store_original(ctx, ctx["version"])
    ctx["store"].put(ctx["tenant"], b"an unindexed leftover")
    _one(ctx, "UPDATE apiome.tenants SET deleted_at = now() - interval '2 hours' WHERE id = %s::uuid", (ctx["tenant"],))
    assert _object(ctx, stored.object_id)["ref_count"] == 0

    report = LifecycleReport()
    lc.purge_deleted_tenants(ctx["db"], ctx["store"], LifecycleOptions(grace=timedelta(hours=1)), report)
    assert report.tenants_purged == 1
    folder = ctx["store"].root / ctx["store"].tenant_prefix(ctx["tenant"])
    assert not folder.exists()
    assert _object(ctx, stored.object_id) == {}
    purge = _one(
        ctx, "SELECT objects_deleted FROM apiome.document_tenant_purges WHERE tenant_id = %s::uuid", (ctx["tenant"],)
    )
    assert purge["objects_deleted"] == 2

    # Purged once: a second run does not list the tenant again.
    again = LifecycleReport()
    lc.purge_deleted_tenants(ctx["db"], ctx["store"], LifecycleOptions(grace=timedelta(hours=1)), again)
    assert again.tenants_purged == 0


def test_a_tenant_inside_the_grace_period_is_kept(ctx) -> None:
    stored = _store_original(ctx, ctx["version"])
    _one(ctx, "UPDATE apiome.tenants SET deleted_at = now() WHERE id = %s::uuid", (ctx["tenant"],))
    report = LifecycleReport()
    lc.purge_deleted_tenants(ctx["db"], ctx["store"], LifecycleOptions(grace=timedelta(hours=1)), report)
    assert report.tenants_purged == 0 and _object(ctx, stored.object_id) != {}


def test_replaced_renders_and_never_linked_rows_are_collected(ctx) -> None:
    db, store, tenant = ctx["db"], ctx["store"], ctx["tenant"]
    ids = []
    for stamp, body in ((1, b'{"v":1}'), (2, b'{"v":2}')):
        ref = store.put(tenant, body, "application/json")
        object_id = db.upsert_document_object(
            tenant_id=tenant,
            sha256=ref.sha256,
            size_bytes=ref.size_bytes,
            media_type="application/json",
            encoding="identity",
            backend=ref.backend,
            storage_key=ref.key,
        )
        assert db.set_version_document(
            tenant_id=tenant,
            version_id=ctx["version"],
            role="rendered_openapi",
            object_id=object_id,
            content_stamp=stamp,
            generator="test",
            generator_version="1",
        )
        ids.append(object_id)
    _one(
        ctx,
        "UPDATE apiome.version_documents SET created_at = now() - interval '3 hours' " "WHERE object_id = %s::uuid",
        (ids[0],),
    )
    orphan_ref = store.put(tenant, b"never linked")
    orphan = db.upsert_document_object(
        tenant_id=tenant,
        sha256=orphan_ref.sha256,
        size_bytes=orphan_ref.size_bytes,
        media_type="text/plain",
        encoding="identity",
        backend=orphan_ref.backend,
        storage_key=orphan_ref.key,
    )
    _one(
        ctx, "UPDATE apiome.document_objects SET created_at = now() - interval '3 hours' WHERE id = %s::uuid", (orphan,)
    )

    report = lc.run_document_lifecycle(
        db,
        LifecycleOptions(grace=timedelta(hours=1), integrity_sample=0),
        store=store,
    )
    assert not report.locked
    assert report.stale_renders_dropped == 1
    assert _object(ctx, ids[0]) == {} and _object(ctx, ids[1])["ref_count"] == 1
    assert _object(ctx, orphan) == {}
    assert not store.exists(tenant, orphan_ref.sha256)


def test_integrity_stamps_flags_and_audits(ctx) -> None:
    good = _store_original(ctx, ctx["version"])
    bad = _store_original(ctx, ctx["version2"], OPENAPI + "# second\n")
    sha = _object(ctx, bad.object_id)["sha256"]
    path = ctx["store"]._path(ctx["tenant"], sha)
    path.write_bytes(b"tampered")

    report = LifecycleReport()
    rows = [
        r
        for r in ctx["db"].list_document_objects_for_integrity(limit=10_000, oldest_first=False)
        if r["tenant_id"] == ctx["tenant"]
    ]
    for row in rows:
        lc._check_one(ctx["db"], ctx["store"], row, report, dry_run=False)
    assert report.objects_verified == 1 and report.integrity_failures == 1
    assert _object(ctx, good.object_id)["verified_at"] is not None
    flagged = _object(ctx, bad.object_id)
    assert flagged["integrity_failed_at"] is not None
    event = _one(
        ctx,
        "SELECT event, reason, detail FROM apiome.document_lifecycle_events " "WHERE object_id = %s::uuid",
        (bad.object_id,),
    )
    assert event["event"] == "integrity_failed" and event["reason"] == "mismatch"
    assert event["detail"]["actualSha256"] == hashlib.sha256(b"tampered").hexdigest()
    assert event["detail"]["roles"] == ["original"]

    # Bytes restored: the next check clears the flag.
    path.write_bytes((OPENAPI + "# second\n").encode("utf-8"))
    rows = ctx["db"].list_document_objects_for_integrity(limit=10_000, oldest_first=False)
    lc._check_one(ctx["db"], ctx["store"], next(r for r in rows if r["id"] == bad.object_id), LifecycleReport(), False)
    assert _object(ctx, bad.object_id)["integrity_failed_at"] is None
