"""Unit tests for the document lifecycle job (COA-5.10, #7086).

A fake database stands in for the V406 tables, so these pin the job's decisions: what is purged
and in which order, what the audit says, how an integrity failure is handled per role, and how a
deleted tenant's prefix is emptied. ``delete_tenant_objects`` is checked on all three backends
(moto for S3; a real MinIO when ``APIOME_TEST_MINIO_URL`` is set). The SQL and the triggers are
covered by ``tests/test_document_lifecycle_db.py``.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import timedelta
from types import SimpleNamespace
from typing import Any, Dict, List

import boto3
import pytest
from botocore.config import Config
from moto import mock_aws

from app import document_lifecycle as lc
from app.document_lifecycle import LifecycleOptions, LifecycleReport
from app.document_store import (
    DbDocumentStore,
    DocumentStoreError,
    FilesystemDocumentStore,
    S3DocumentStore,
)

TENANT = "0b7e6c1e-4a53-4c8e-9d0e-1f2a3b4c5d6e"
OTHER = "acme"
BUCKET = "apiome-documents"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeDb:
    """In-memory ``document_objects`` / ``version_documents`` / blob / audit methods."""

    def __init__(self) -> None:
        self.objects: Dict[str, Dict[str, Any]] = {}
        self.links: List[Dict[str, Any]] = []
        self.blobs: Dict[tuple, Dict[str, Any]] = {}
        self.events: List[Dict[str, Any]] = []
        self.tenants: List[Dict[str, Any]] = []
        self.purged_tenants: Dict[str, int] = {}
        self.verified: List[str] = []
        self.flagged: List[str] = []
        self.stale: List[str] = []
        self.reindexed: set = set()

    # objects ------------------------------------------------------------------------------
    def add(self, object_id: str, data: bytes, *, tenant: str = TENANT, refs: int = 0, roles=(), backend="db") -> str:
        sha = _sha(data)
        self.objects[object_id] = {
            "id": object_id,
            "tenant_id": tenant,
            "sha256": sha,
            "backend": backend,
            "storage_key": f"apiome/tenants/{tenant}/objects/sha256/{sha[:2]}/{sha}",
            "size_bytes": len(data),
            "ref_count": refs,
            "roles": list(roles),
        }
        return sha

    def document_object_ids_for_versions(self, version_ids):
        return sorted({link["object_id"] for link in self.links if link["version_id"] in version_ids})

    def list_unreferenced_document_objects(self, *, cutoff, object_ids=None, limit=500):
        rows = [o for o in self.objects.values() if o["ref_count"] == 0]
        if object_ids is not None:
            rows = [o for o in rows if o["id"] in object_ids]
        return [dict(o) for o in rows][:limit]

    def purge_unreferenced_document_object(self, object_id):
        row = self.objects.get(object_id)
        if row is None or row["ref_count"] > 0:
            return None
        self.links = [link for link in self.links if link["object_id"] != object_id]
        return dict(self.objects.pop(object_id))

    def document_object_indexed(self, tenant_id, sha256):
        return (tenant_id, sha256) in self.reindexed

    def delete_stale_rendered_documents(self, *, cutoff, limit=500):
        out, self.stale = self.stale, []
        for object_id in out:
            self.objects[object_id]["ref_count"] = 0
        return out

    def list_purgeable_tenants(self, *, cutoff, limit=20):
        return [t for t in self.tenants if t["id"] not in self.purged_tenants]

    def tenant_document_object_ids(self, tenant_id):
        return sorted(o["id"] for o in self.objects.values() if o["tenant_id"] == tenant_id)

    def record_document_tenant_purge(self, tenant_id, objects_deleted):
        self.purged_tenants[tenant_id] = objects_deleted

    def insert_document_lifecycle_event(self, **values):
        self.events.append(values)

    def list_document_objects_for_integrity(self, *, limit, after_id=None, oldest_first=True):
        rows = sorted(self.objects.values(), key=lambda o: o["id"])
        if after_id is not None:
            rows = [o for o in rows if o["id"] > after_id]
        return [dict(o) for o in rows][:limit]

    def mark_document_object_verified(self, object_id):
        self.verified.append(object_id)

    def flag_document_object_integrity(self, object_id):
        self.flagged.append(object_id)

    def drop_rendered_document_object(self, object_id):
        row = self.objects.get(object_id)
        if row is None or any(role not in lc.ROLES_RENDERED for role in row["roles"]):
            return False
        del self.objects[object_id]
        return True

    # db backend blobs -----------------------------------------------------------------------
    def put_document_store_blob(self, *, tenant_id, sha256, size_bytes, media_type, content):
        if (tenant_id, sha256) in self.blobs:
            return False
        self.blobs[(tenant_id, sha256)] = {"size_bytes": size_bytes, "media_type": media_type, "content": content}
        return True

    def head_document_store_blob(self, tenant_id, sha256):
        row = self.blobs.get((tenant_id, sha256))
        return None if row is None else {"size_bytes": row["size_bytes"], "media_type": row["media_type"]}

    def get_document_store_blob(self, tenant_id, sha256):
        row = self.blobs.get((tenant_id, sha256))
        return None if row is None else row["content"]

    def delete_document_store_blob(self, tenant_id, sha256):
        return self.blobs.pop((tenant_id, sha256), None) is not None

    def delete_document_store_blobs_for_tenant(self, tenant_id):
        keys = [key for key in self.blobs if key[0] == tenant_id]
        for key in keys:
            del self.blobs[key]
        return len(keys)


@pytest.fixture
def db() -> FakeDb:
    return FakeDb()


@pytest.fixture
def store(db: FakeDb) -> DbDocumentStore:
    return DbDocumentStore(prefix="apiome", database=db)


def _stored(db: FakeDb, store, object_id: str, data: bytes, **kwargs) -> str:
    """Index an object and write its bytes."""
    store.put(kwargs.get("tenant", TENANT), data)
    return db.add(object_id, data, **kwargs)


def _no_lock_options(**overrides) -> Dict[str, Any]:
    return {"lock": lambda _db: True, "unlock": lambda _db: None, **overrides}


# ───────────────────────────── purge and release ─────────────────────────────


class TestPurge:
    def test_an_unreferenced_object_leaves_the_index_and_the_store(self, db, store):
        sha = _stored(db, store, "o1", b"orders")
        row = lc.purge_object(db, store, "o1", reason=lc.REASON_UNREFERENCED)
        assert row["sha256"] == sha
        assert "o1" not in db.objects and not store.exists(TENANT, sha)
        assert db.events[-1]["event"] == lc.EVENT_PURGED and db.events[-1]["reason"] == "unreferenced"

    def test_a_referenced_object_is_kept(self, db, store):
        sha = _stored(db, store, "o1", b"orders", refs=1)
        assert lc.purge_object(db, store, "o1", reason=lc.REASON_UNREFERENCED) is None
        assert store.exists(TENANT, sha) and db.events == []

    def test_bytes_a_writer_indexed_again_are_kept(self, db, store):
        sha = _stored(db, store, "o1", b"orders")
        db.reindexed.add((TENANT, sha))
        assert lc.purge_object(db, store, "o1", reason=lc.REASON_UNREFERENCED) is not None
        assert store.exists(TENANT, sha)
        assert db.events[-1]["detail"] == {"bytesKept": True}

    def test_a_store_failure_is_audited_not_raised(self, db, store, monkeypatch):
        _stored(db, store, "o1", b"orders")

        def boom(*args):
            raise DocumentStoreError("bucket unreachable")

        monkeypatch.setattr(store, "delete", boom)
        assert lc.purge_object(db, store, "o1", reason=lc.REASON_UNREFERENCED) is not None
        assert db.events[-1]["event"] == lc.EVENT_PURGE_FAILED
        assert db.events[-1]["detail"] == {"error": "bucket unreachable"}
        assert db.events[-1]["storage_key"].endswith(_sha(b"orders"))

    def test_an_object_on_another_backend_is_audited(self, db, store, tmp_path):
        fs = FilesystemDocumentStore(path=str(tmp_path))
        db.add("o1", b"orders", backend="s3")
        lc.purge_object(db, fs, "o1", reason=lc.REASON_UNREFERENCED)
        assert db.events[-1]["event"] == lc.EVENT_PURGE_FAILED

    def test_database_objects_are_purged_after_a_switch_to_another_backend(self, db, store, tmp_path):
        sha = _stored(db, store, "o1", b"orders")
        fs = FilesystemDocumentStore(path=str(tmp_path))
        lc.purge_object(db, fs, "o1", reason=lc.REASON_UNREFERENCED)
        assert not store.exists(TENANT, sha) and db.events[-1]["event"] == lc.EVENT_PURGED

    def test_a_dry_run_purges_nothing(self, db, store):
        _stored(db, store, "o1", b"orders")
        assert lc.purge_object(db, store, "o1", reason="unreferenced", dry_run=True) is None
        assert "o1" in db.objects


class TestRelease:
    def test_deleting_one_of_two_revisions_keeps_a_shared_original(self, db, store):
        sha = _stored(db, store, "shared", b"openapi: 3.1.0", refs=1)
        db.links = [{"version_id": "v1", "object_id": "shared"}, {"version_id": "v2", "object_id": "shared"}]
        assert lc.release_versions(db, ["v1"], store=store) == 0
        assert store.exists(TENANT, sha)

    def test_deleting_both_removes_it(self, db, store):
        sha = _stored(db, store, "shared", b"openapi: 3.1.0", refs=0)
        db.links = [{"version_id": "v1", "object_id": "shared"}, {"version_id": "v2", "object_id": "shared"}]
        assert lc.release_versions(db, ["v2"], store=store) == 1
        assert not store.exists(TENANT, sha)
        assert db.events[-1]["reason"] == lc.REASON_VERSION_DELETED

    def test_release_only_touches_the_revisions_objects(self, db, store):
        _stored(db, store, "mine", b"a")
        _stored(db, store, "other", b"b")
        db.links = [{"version_id": "v1", "object_id": "mine"}]
        lc.release_versions(db, ["v1"], store=store)
        assert set(db.objects) == {"other"}

    def test_the_safe_variant_never_raises(self, db, store):
        def boom(_ids):
            raise RuntimeError("db down")

        db.document_object_ids_for_versions = boom
        assert lc.release_versions_safely(db, ["v1"], store=store) == 0


# ───────────────────────────── the scheduled run ─────────────────────────────


class TestRun:
    def test_collects_unreferenced_objects_and_stale_renders(self, db, store):
        _stored(db, store, "orphan", b"orphan")
        _stored(db, store, "old-render", b'{"openapi":"3.1.0"}', refs=1, roles=["rendered_openapi"])
        _stored(db, store, "live", b"live", refs=1)
        db.stale = ["old-render"]
        report = lc.run_document_lifecycle(db, LifecycleOptions(integrity_sample=0), store=store, **_no_lock_options())
        assert set(db.objects) == {"live"}
        assert report.objects_purged == 2 and report.stale_renders_dropped == 1
        reasons = sorted(e["reason"] for e in db.events if e["event"] == lc.EVENT_PURGED)
        assert reasons == ["stale-render", "unreferenced"]

    def test_a_dry_run_counts_and_changes_nothing(self, db, store):
        _stored(db, store, "orphan", b"orphan")
        report = lc.run_document_lifecycle(
            db, LifecycleOptions(dry_run=True, integrity_sample=10), store=store, **_no_lock_options()
        )
        assert report.objects_purged == 1 and report.dry_run
        assert "orphan" in db.objects and db.verified == [] and db.events == []

    def test_a_held_lock_skips_the_run(self, db, store):
        _stored(db, store, "orphan", b"orphan")
        report = lc.run_document_lifecycle(db, LifecycleOptions(), store=store, lock=lambda _db: False)
        assert report.locked and "orphan" in db.objects

    def test_the_lock_is_released_after_a_failure(self, db, store):
        released = []

        def boom(**kwargs):
            raise RuntimeError("db down")

        db.delete_stale_rendered_documents = boom
        with pytest.raises(RuntimeError):
            lc.run_document_lifecycle(
                db, LifecycleOptions(), store=store, lock=lambda _db: True, unlock=lambda _db: released.append(1)
            )
        assert released == [1]

    def test_gc_can_be_skipped(self, db, store):
        _stored(db, store, "orphan", b"orphan")
        lc.run_document_lifecycle(db, LifecycleOptions(gc=False, integrity_sample=0), store=store, **_no_lock_options())
        assert "orphan" in db.objects

    def test_options_follow_the_settings(self):
        cfg = SimpleNamespace(document_gc_grace_hours=2.5, document_integrity_sample=7)
        options = LifecycleOptions.from_settings(cfg)
        assert options.grace == timedelta(hours=2.5) and options.integrity_sample == 7
        assert options.gc and not options.integrity_all and not options.dry_run


# ───────────────────────────── deleted tenants ─────────────────────────────


class TestTenants:
    def test_a_deleted_tenant_leaves_nothing_under_its_prefix(self, db, store):
        _stored(db, store, "o1", b"one")
        _stored(db, store, "o2", b"two")
        store.put(TENANT, b"probe left behind, not indexed")
        store.put("acme-slug", b"an export download")
        db.tenants = [{"id": TENANT, "slug": "acme-slug", "slug_in_use": False}]
        report = LifecycleReport()
        lc.purge_deleted_tenants(db, store, LifecycleOptions(), report)
        assert db.blobs == {} and db.objects == {}
        assert report.tenants_purged == 1 and report.tenant_objects_deleted == 4
        assert db.purged_tenants == {TENANT: 4}
        event = next(e for e in db.events if e["event"] == lc.EVENT_TENANT_PURGED)
        assert event["detail"]["segments"] == [TENANT, "acme-slug"]

    def test_a_slug_a_live_tenant_reuses_is_left_alone(self, db, store):
        store.put("acme-slug", b"the new tenant's export")
        db.tenants = [{"id": TENANT, "slug": "acme-slug", "slug_in_use": True}]
        lc.purge_deleted_tenants(db, store, LifecycleOptions(), LifecycleReport())
        assert store.exists("acme-slug", _sha(b"the new tenant's export"))

    def test_other_tenants_are_untouched(self, db, store):
        _stored(db, store, "theirs", b"theirs", tenant=OTHER, refs=1)
        db.tenants = [{"id": TENANT, "slug": None, "slug_in_use": False}]
        lc.purge_deleted_tenants(db, store, LifecycleOptions(), LifecycleReport())
        assert store.exists(OTHER, _sha(b"theirs"))

    def test_a_store_failure_retries_next_run(self, db, store, monkeypatch):
        db.tenants = [{"id": TENANT, "slug": None, "slug_in_use": False}]

        def boom(_tenant):
            raise DocumentStoreError("AccessDenied")

        monkeypatch.setattr(store, "delete_tenant_objects", boom)
        report = LifecycleReport()
        lc.purge_deleted_tenants(db, store, LifecycleOptions(), report)
        assert report.tenants_purged == 0 and db.purged_tenants == {}
        assert db.events[-1]["event"] == lc.EVENT_PURGE_FAILED

    def test_a_dry_run_only_counts(self, db, store):
        _stored(db, store, "o1", b"one")
        db.tenants = [{"id": TENANT, "slug": None, "slug_in_use": False}]
        report = LifecycleReport()
        lc.purge_deleted_tenants(db, store, LifecycleOptions(dry_run=True), report)
        assert report.tenants_purged == 1 and "o1" in db.objects


# ───────────────────────────── integrity ─────────────────────────────


class TestIntegrity:
    def test_intact_objects_are_stamped(self, db, store):
        _stored(db, store, "o1", b"one", refs=1, roles=["original"])
        report = LifecycleReport()
        lc.run_integrity(db, store, LifecycleOptions(integrity_sample=10), report)
        assert report.objects_verified == 1 and db.verified == ["o1"]

    def test_a_changed_original_is_flagged_audited_and_alerted(self, db, store, caplog):
        sha = _stored(db, store, "o1", b"one", refs=1, roles=["original"])
        db.blobs[(TENANT, sha)]["content"] = b"tampered"
        report = LifecycleReport()
        with caplog.at_level(logging.ERROR):
            lc.run_integrity(db, store, LifecycleOptions(integrity_sample=10), report)
        assert report.integrity_failures == 1 and db.flagged == ["o1"]
        event = db.events[-1]
        assert event["event"] == lc.EVENT_INTEGRITY_FAILED and event["reason"] == lc.REASON_MISMATCH
        assert event["detail"]["actualSha256"] == _sha(b"tampered")
        assert lc.INTEGRITY_ALERT in caplog.text
        assert "o1" in db.objects

    def test_a_missing_frozen_schema_is_flagged(self, db, store):
        db.add("o1", b"frozen", refs=1, roles=["frozen_schema"])
        report = LifecycleReport()
        lc.run_integrity(db, store, LifecycleOptions(integrity_sample=10), report)
        assert db.flagged == ["o1"] and db.events[-1]["reason"] == lc.REASON_MISSING

    def test_a_changed_rendered_document_is_dropped_for_re_render(self, db, store):
        sha = _stored(db, store, "o1", b'{"openapi":"3.1.0"}', refs=1, roles=["rendered_openapi"])
        db.blobs[(TENANT, sha)]["content"] = b"tampered"
        lc.run_integrity(db, store, LifecycleOptions(integrity_sample=10), LifecycleReport())
        assert "o1" not in db.objects and db.flagged == []
        assert not store.exists(TENANT, sha)
        assert [e["event"] for e in db.events] == [lc.EVENT_INTEGRITY_FAILED, lc.EVENT_RENDERED_DROPPED]

    def test_an_object_shared_by_an_original_and_a_render_is_flagged_not_dropped(self, db, store):
        sha = _stored(db, store, "o1", b"both", refs=2, roles=["original", "rendered_openapi"])
        db.blobs[(TENANT, sha)]["content"] = b"tampered"
        lc.run_integrity(db, store, LifecycleOptions(integrity_sample=10), LifecycleReport())
        assert db.flagged == ["o1"] and "o1" in db.objects

    def test_an_unreadable_store_is_skipped_not_flagged(self, db, store, monkeypatch):
        _stored(db, store, "o1", b"one", refs=1, roles=["original"])

        def boom(*args):
            raise DocumentStoreError("timeout")

        monkeypatch.setattr(store, "open_stream", boom)
        report = LifecycleReport()
        lc.run_integrity(db, store, LifecycleOptions(integrity_sample=10), report)
        assert report.integrity_skipped == 1 and db.flagged == [] and db.events == []

    def test_all_walks_every_object_in_pages(self, db, store, monkeypatch):
        monkeypatch.setattr(lc, "_BATCH", 2)
        for index in range(5):
            _stored(db, store, f"o{index}", f"doc {index}".encode(), refs=1, roles=["original"])
        report = LifecycleReport()
        lc.run_integrity(db, store, LifecycleOptions(integrity_all=True), report)
        assert report.objects_verified == 5 and sorted(db.verified) == [f"o{i}" for i in range(5)]

    def test_a_zero_sample_skips_the_check(self, db, store):
        _stored(db, store, "o1", b"one", refs=1)
        lc.run_integrity(db, store, LifecycleOptions(integrity_sample=0), LifecycleReport())
        assert db.verified == []


# ───────────────────────────── tenant prefixes in each backend ─────────────────────────────


def _put_all(store, tenants=(TENANT, OTHER)) -> None:
    for tenant in tenants:
        for body in (b"one", b"two", b"three"):
            store.put(tenant, body + tenant.encode())


class TestDeleteTenantObjects:
    def test_db(self, db):
        store = DbDocumentStore(prefix="apiome", database=db)
        _put_all(store)
        assert store.delete_tenant_objects(TENANT) == 3
        assert {key[0] for key in db.blobs} == {OTHER}

    def test_filesystem(self, tmp_path):
        store = FilesystemDocumentStore(path=str(tmp_path), prefix="apiome")
        _put_all(store)
        assert store.delete_tenant_objects(TENANT) == 3
        assert not (tmp_path / "apiome" / "tenants" / TENANT).exists()
        assert store.delete_tenant_objects(TENANT) == 0
        assert len(list((tmp_path / "apiome" / "tenants" / OTHER).rglob("*.meta"))) == 3

    def test_filesystem_without_a_prefix(self, tmp_path):
        store = FilesystemDocumentStore(path=str(tmp_path))
        _put_all(store)
        assert store.delete_tenant_objects(TENANT) == 3
        assert (tmp_path / "tenants" / OTHER).exists()

    def test_a_tenant_segment_must_be_safe(self, tmp_path):
        store = FilesystemDocumentStore(path=str(tmp_path))
        with pytest.raises(ValueError):
            store.delete_tenant_objects("..")
        with pytest.raises(ValueError):
            store.delete_tenant_objects("a/b")

    def test_s3_pages_through_large_prefixes(self):
        with mock_aws():
            client = boto3.client("s3", region_name="us-east-1", config=Config(signature_version="s3v4"))
            client.create_bucket(Bucket=BUCKET)
            store = S3DocumentStore(bucket=BUCKET, prefix="apiome", client_factory=lambda: client)
            for index in range(1005):
                client.put_object(Bucket=BUCKET, Key=f"apiome/tenants/{TENANT}/objects/x/{index}", Body=b"x")
            _put_all(store, tenants=(OTHER,))
            assert store.delete_tenant_objects(TENANT) == 1005
            left = client.list_objects_v2(Bucket=BUCKET, Prefix="apiome/tenants/")
            assert {item["Key"].split("/")[2] for item in left["Contents"]} == {OTHER}

    def test_s3_failures_are_redacted(self):
        class Failing:
            def get_paginator(self, name):
                raise RuntimeError("secret-key-123 rejected")

        store = S3DocumentStore(
            bucket=BUCKET, access_key_id="AKIA0000", secret_access_key="secret-key-123", client_factory=Failing
        )
        with pytest.raises(DocumentStoreError) as excinfo:
            store.delete_tenant_objects(TENANT)
        assert "secret-key-123" not in str(excinfo.value)


@pytest.mark.skipif(not os.environ.get("APIOME_TEST_MINIO_URL"), reason="set APIOME_TEST_MINIO_URL to test MinIO")
def test_tenant_deletion_leaves_no_objects_under_its_prefix_on_minio(db):
    """Acceptance (COA-5.10): run against a real MinIO (``APIOME_TEST_MINIO_URL``, ``…_KEY``, ``…_SECRET``)."""
    bucket = os.environ.get("APIOME_TEST_MINIO_BUCKET", "apiome-test")
    store = S3DocumentStore(
        bucket=bucket,
        prefix=f"lifecycle-test-{os.getpid()}",
        endpoint_url=os.environ["APIOME_TEST_MINIO_URL"],
        addressing_style="path",
        access_key_id=os.environ.get("APIOME_TEST_MINIO_KEY", "minioadmin"),
        secret_access_key=os.environ.get("APIOME_TEST_MINIO_SECRET", "minioadmin"),
        allow_private=True,
    )
    try:
        store.client.create_bucket(Bucket=bucket)
    except Exception:  # noqa: BLE001 - already there
        pass
    _put_all(store)
    for index, body in enumerate((b"one", b"two")):
        ref = store.put(TENANT, body)
        db.add(f"o{index}", body, backend="s3")
        assert ref.backend == "s3"
    db.tenants = [{"id": TENANT, "slug": None, "slug_in_use": False}]
    lc.purge_deleted_tenants(db, store, LifecycleOptions(), LifecycleReport())
    listing = store.client.list_objects_v2(Bucket=bucket, Prefix=store.tenant_prefix(TENANT))
    assert listing.get("KeyCount", 0) == 0
    assert store.delete_tenant_objects(OTHER) == 3


# ───────────────────────────── the version delete route ─────────────────────────────


def test_deleting_a_version_releases_its_documents(monkeypatch):
    """``DELETE /v1/versions/{tenant}/{project}/{version}`` releases the revision's objects."""
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from app import versions_routes
    from app.auth import validate_authentication
    from app.main import app

    auth = {"tenant_id": "t-1", "user_id": "u-1", "auth_method": "jwt"}
    fake = MagicMock()
    fake.get_version_by_id.return_value = {"project_id": "p-1", "version_id": "1.0.0"}
    fake.delete_version.return_value = (True, None)
    released = []
    monkeypatch.setattr(versions_routes, "db", fake)
    monkeypatch.setattr(versions_routes, "enforce_permission", lambda *a, **k: None)
    monkeypatch.setattr(lc, "release_versions_safely", lambda db, ids: released.append((db, list(ids))))
    app.dependency_overrides[validate_authentication] = lambda: auth
    try:
        response = TestClient(app).delete("/v1/versions/acme/p-1/v-1")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 200
    assert released == [(fake, ["v-1"])]


def test_a_failed_delete_releases_nothing(monkeypatch):
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from app import versions_routes
    from app.auth import validate_authentication
    from app.main import app

    fake = MagicMock()
    fake.get_version_by_id.return_value = {"project_id": "p-1", "version_id": "1.0.0"}
    fake.delete_version.return_value = (False, "revision_locked")
    released = []
    monkeypatch.setattr(versions_routes, "db", fake)
    monkeypatch.setattr(versions_routes, "enforce_permission", lambda *a, **k: None)
    monkeypatch.setattr(lc, "release_versions_safely", lambda db, ids: released.append(ids))
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t-1", "user_id": "u-1"}
    try:
        response = TestClient(app).delete("/v1/versions/acme/p-1/v-1")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 403 and released == []
