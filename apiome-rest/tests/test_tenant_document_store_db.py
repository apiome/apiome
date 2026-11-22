"""Per-tenant bring-your-own buckets against Postgres and an in-process S3 — COA-5.15 (#7092).

Runs on the real V408 tables with three moto buckets (the platform bucket and one per tenant):

* two tenants on different buckets never see each other's objects, and neither writes to the
  platform bucket;
* a move from the platform store to a tenant bucket and back leaves every object verified, with
  every object readable at every step, and old copies are only deleted on request;
* a revoked credential turns into ``TenantDocumentStoreUnavailable``, flags the tenant for the
  ops health check, notifies its administrators once, and rendered documents still answer;
* no key or secret appears in a response, an error, a notification, a log line or an audit row;
* the REST routes: the platform switch, the permission, the bucket test, the move and the cleanup.

Skips when no database with V408 is reachable. These tests commit; the fixture removes what they wrote.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import uuid
from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws

from app import document_store_move as move
from app import tenant_document_store as tds
from app import tenant_document_store_routes as routes
from app.auth import validate_authentication
from app.config import settings
from app.document_store import DocumentNotFound, S3DocumentStore
from app.document_store_health import health_detail, tenant_buckets
from app.document_store_router import TenantRoutingDocumentStore
from app.main import app
from app.mcp_credential_crypto import seal_credential_payload
from tests.test_content_stamp_db import env as stamp_env  # noqa: F401 - the seeded tenant/project/revision

pytestmark = pytest.mark.requires_db

PLATFORM_BUCKET = "apiome-platform"
PLATFORM_KEY, PLATFORM_SECRET = "AKIAPLATFORMKEY00001", "platform-secret-key-0000000000000001"
TENANT_KEY, TENANT_SECRET = "AKIATENANTKEY0000001", "tenant-secret-key-00000000000000000001"
MEDIA = "application/yaml"


def _one(ctx: Dict[str, Any], sql: str, params: tuple = ()) -> Dict[str, Any]:
    """Run one statement in its own committed transaction and return its first row (or ``{}``)."""
    with ctx["conn"].cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone() if cur.description else None
    ctx["conn"].commit()
    return dict(row) if row else {}


def _all(ctx: Dict[str, Any], sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    with ctx["conn"].cursor() as cur:
        cur.execute(sql, params)
        rows = [dict(row) for row in cur.fetchall()]
    ctx["conn"].commit()
    return rows


def _keys(client: Any, bucket: str) -> List[str]:
    return [item["Key"] for item in client.list_objects_v2(Bucket=bucket).get("Contents", [])]


def _credential(ctx: Dict[str, Any], tenant: str, name: str = "documents") -> str:
    sealed, version = seal_credential_payload({"accessKeyId": TENANT_KEY, "secretAccessKey": TENANT_SECRET})
    row = ctx["db"].insert_export_storage_credential(
        tenant_id=tenant,
        name=name,
        endpoint_url=None,
        region="us-east-1",
        force_path_style=False,
        access_key_hint=TENANT_KEY[-4:],
        encrypted_payload=sealed,
        key_version=version,
    )
    return str(row["id"])


def _use_bucket(ctx: Dict[str, Any], tenant: str, bucket: str, *, mode: str = "tenant") -> None:
    """Point ``tenant`` at ``bucket`` (settings only; no move)."""
    values = {
        "mode": mode,
        "credential_id": _credential(ctx, tenant, f"documents-{uuid.uuid4().hex[:6]}"),
        "bucket": bucket,
        "prefix": "apiome",
        "region": "",
        "endpoint_url": "",
        "addressing_style": "auto",
        "sse": "",
        "kms_key_id": "",
    }
    tds.save_settings(ctx["db"], tenant, values, actor_id=ctx["user"])
    ctx["router"].invalidate(tenant)


def _put(ctx: Dict[str, Any], tenant: str, text: str) -> str:
    """Store ``text`` for ``tenant`` through the router and index it; return its SHA-256."""
    ref = ctx["router"].put(tenant, text.encode(), MEDIA)
    ctx["db"].upsert_document_object(
        tenant_id=tenant,
        sha256=ref.sha256,
        size_bytes=ref.size_bytes,
        media_type=MEDIA,
        encoding="identity",
        backend=ref.backend,
        storage_key=ref.key,
    )
    return ref.sha256


def _objects(ctx: Dict[str, Any], tenant: str) -> List[Dict[str, Any]]:
    return _all(
        ctx,
        "SELECT sha256, backend, storage_key, verified_at FROM apiome.document_objects "
        "WHERE tenant_id = %s ORDER BY sha256",
        (tenant,),
    )


def _row(ctx: Dict[str, Any], tenant: str) -> Dict[str, Any]:
    return _one(ctx, "SELECT * FROM apiome.tenant_document_stores WHERE tenant_id = %s::uuid", (tenant,))


def _run_move(ctx: Dict[str, Any], tenant: str, target: str) -> move.MoveReport:
    move.begin_move(ctx["db"], tenant, target)
    report = move.run_move(ctx["db"], ctx["router"], tenant, settle_seconds=0, sleep=lambda _s: None)
    assert report is not None
    return report


@pytest.fixture
def ctx(stamp_env: Dict[str, Any], monkeypatch) -> Iterator[Dict[str, Any]]:  # noqa: F811
    """Tenant A (seeded) and tenant B, three buckets, and a router over the platform bucket."""
    if not _one(stamp_env, "SELECT to_regclass('apiome.tenant_document_stores') AS t").get("t"):
        pytest.skip("V408 not applied")
    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", json.dumps({"1": base64.b64encode(os.urandom(32)).decode()})
    )
    monkeypatch.setattr(settings, "document_store_allow_tenant_buckets", True)
    tds.reset_outage_memory()
    suffix = uuid.uuid4().hex[:10]
    tenant_b = _one(
        stamp_env,
        "INSERT INTO apiome.tenants (name, slug) VALUES (%s, %s) RETURNING id::text AS id",
        (f"byob {suffix}", f"byob-{suffix}"),
    )["id"]
    tenant_a = stamp_env["tenant"]
    # The seeded user administers tenant A, so it passes document_store:manage and is notified.
    _one(
        stamp_env,
        "INSERT INTO apiome.tenant_users (tenant_id, user_id) VALUES (%s::uuid, %s::uuid)",
        (tenant_a, stamp_env["user"]),
    )
    _one(
        stamp_env,
        "INSERT INTO apiome.tenant_administrators (tenant_id, user_id) VALUES (%s::uuid, %s::uuid)",
        (tenant_a, stamp_env["user"]),
    )
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id=PLATFORM_KEY,
            aws_secret_access_key=PLATFORM_SECRET,
            config=Config(signature_version="s3v4"),
        )
        buckets = {"a": f"tenant-a-{suffix}", "b": f"tenant-b-{suffix}"}
        for name in (PLATFORM_BUCKET, *buckets.values()):
            client.create_bucket(Bucket=name)
        platform = S3DocumentStore(
            bucket=PLATFORM_BUCKET,
            prefix="apiome",
            access_key_id=PLATFORM_KEY,
            secret_access_key=PLATFORM_SECRET,
            client_factory=lambda: client,
        )
        factories = {"client": lambda: client}

        def build(database: Any, store_settings: tds.TenantStoreSettings) -> Any:
            return tds.build_tenant_store(database, store_settings, client_factory=lambda: factories["client"]())

        stamp_env.update(
            tenant_b=tenant_b,
            client=client,
            buckets=buckets,
            platform=platform,
            factories=factories,
            router=TenantRoutingDocumentStore(
                platform, database=stamp_env["db"], build=build, ttl_seconds=0, active=lambda: True
            ),
        )
        try:
            yield stamp_env
        finally:
            stamp_env["conn"].rollback()
            for tenant in (tenant_a, tenant_b):
                _one(stamp_env, "DELETE FROM apiome.notifications WHERE tenant_id = %s::uuid", (tenant,))
                _one(stamp_env, "DELETE FROM apiome.tenant_document_stores WHERE tenant_id = %s::uuid", (tenant,))
                _one(stamp_env, "DELETE FROM apiome.export_storage_credentials WHERE tenant_id = %s::uuid", (tenant,))
                _one(stamp_env, "DELETE FROM apiome.document_objects WHERE tenant_id = %s", (tenant,))
                _one(stamp_env, "DELETE FROM apiome.access_audit WHERE tenant_id = %s::uuid", (tenant,))
            _one(stamp_env, "DELETE FROM apiome.tenant_administrators WHERE tenant_id = %s::uuid", (tenant_a,))
            _one(stamp_env, "DELETE FROM apiome.tenant_users WHERE tenant_id = %s::uuid", (tenant_a,))
            _one(stamp_env, "DELETE FROM apiome.tenants WHERE id = %s::uuid", (tenant_b,))
            tds.reset_outage_memory()


# ── Isolation ─────────────────────────────────────────────────────────────────────────────────


def test_two_tenants_on_their_own_buckets_never_share_an_object(ctx) -> None:
    a, b = ctx["tenant"], ctx["tenant_b"]
    _use_bucket(ctx, a, ctx["buckets"]["a"])
    _use_bucket(ctx, b, ctx["buckets"]["b"])

    sha_a = _put(ctx, a, "openapi: 3.1.0\ninfo: {title: A}\n")
    sha_b = _put(ctx, b, "openapi: 3.1.0\ninfo: {title: B}\n")
    same = "openapi: 3.1.0\ninfo: {title: Same bytes in both}\n"
    assert _put(ctx, a, same) == _put(ctx, b, same)

    keys_a, keys_b = _keys(ctx["client"], ctx["buckets"]["a"]), _keys(ctx["client"], ctx["buckets"]["b"])
    assert len(keys_a) == 2 and all(f"/tenants/{a}/" in key for key in keys_a)
    assert len(keys_b) == 2 and all(f"/tenants/{b}/" in key for key in keys_b)
    assert _keys(ctx["client"], PLATFORM_BUCKET) == []
    assert {row["backend"] for row in _objects(ctx, a) + _objects(ctx, b)} == {"tenant_s3"}

    assert ctx["router"].get(a, sha_a).startswith(b"openapi")
    # B's object does not exist for A, in A's bucket or anywhere else.
    with pytest.raises(DocumentNotFound):
        ctx["router"].get(a, sha_b)
    assert ctx["router"].head(b, sha_a) is None


def test_a_tenant_store_refuses_another_tenants_key(ctx) -> None:
    a, b = ctx["tenant"], ctx["tenant_b"]
    _use_bucket(ctx, a, ctx["buckets"]["a"])
    store = ctx["router"].tenant_store(a)
    with pytest.raises(tds.DocumentStoreError, match="only holds that tenant"):
        store.put(b, b"not yours", MEDIA)
    assert _keys(ctx["client"], ctx["buckets"]["a"]) == []


def test_a_tenant_without_settings_uses_the_platform_store(ctx) -> None:
    sha = _put(ctx, ctx["tenant"], "openapi: 3.1.0\n")
    assert len(_keys(ctx["client"], PLATFORM_BUCKET)) == 1
    assert _objects(ctx, ctx["tenant"])[0]["backend"] == "s3"
    assert ctx["router"].exists(ctx["tenant"], sha)


# ── The move ──────────────────────────────────────────────────────────────────────────────────


def test_a_move_to_the_tenant_bucket_and_back_verifies_every_object(ctx, monkeypatch) -> None:
    tenant, bucket = ctx["tenant"], ctx["buckets"]["a"]
    shas = [_put(ctx, tenant, f"openapi: 3.1.0\ninfo: {{title: Doc {n}}}\n") for n in range(5)]
    _use_bucket(ctx, tenant, bucket)

    # Every object answers before each single object is moved: nothing fails during the move.
    real_move_one = move._move_one
    reads: List[int] = []

    def checked(db, router, tenant_id, target, row):
        reads.append(sum(1 for sha in shas if router.get(tenant_id, sha)))
        return real_move_one(db, router, tenant_id, target, row)

    monkeypatch.setattr(move, "_move_one", checked)

    report = _run_move(ctx, tenant, "tenant")
    assert (report.state, report.total, report.moved, report.failed) == ("completed", 5, 5, 0)
    assert reads == [5] * 5
    rows = _objects(ctx, tenant)
    assert {row["backend"] for row in rows} == {"tenant_s3"} and all(row["verified_at"] for row in rows)
    assert len(_keys(ctx["client"], bucket)) == 5
    # The old copies stay until someone confirms.
    assert len(_keys(ctx["client"], PLATFORM_BUCKET)) == 5
    state = _row(ctx, tenant)
    assert state["move_state"] == "completed" and state["cleanup_pending"] is True
    assert state["move_counts"] == {"total": 5, "moved": 5, "failed": 0}

    assert move.cleanup_old_copies(ctx["db"], ctx["router"], tenant) == {"checked": 5, "deleted": 5}
    assert _keys(ctx["client"], PLATFORM_BUCKET) == []
    assert all(ctx["router"].get(tenant, sha) for sha in shas)
    assert _row(ctx, tenant)["cleanup_pending"] is False

    # A document written while on the tenant bucket moves back with the rest.
    shas.append(_put(ctx, tenant, "openapi: 3.1.0\ninfo: {title: Written in the bucket}\n"))
    _one(ctx, "UPDATE apiome.tenant_document_stores SET mode = 'platform' WHERE tenant_id = %s::uuid", (tenant,))
    ctx["router"].invalidate(tenant)
    reads.clear()
    back = _run_move(ctx, tenant, "platform")
    assert (back.state, back.moved, back.failed) == ("completed", 6, 0)
    assert reads == [6] * 6
    rows = _objects(ctx, tenant)
    assert {row["backend"] for row in rows} == {"s3"} and all(row["verified_at"] for row in rows)
    assert len(_keys(ctx["client"], PLATFORM_BUCKET)) == 6
    assert move.cleanup_old_copies(ctx["db"], ctx["router"], tenant)["deleted"] == 6
    assert _keys(ctx["client"], bucket) == []
    assert all(ctx["router"].get(tenant, sha) for sha in shas)


def test_a_move_resumes_after_the_last_object_it_finished(ctx, monkeypatch) -> None:
    tenant = ctx["tenant"]
    for n in range(4):
        _put(ctx, tenant, f"doc {n}\n")
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    move.begin_move(ctx["db"], tenant, "tenant")

    real_move_one, calls = move._move_one, []

    def crash_on_third(db, router, tenant_id, target, row):
        calls.append(row["id"])
        if len(calls) == 3:
            raise KeyboardInterrupt  # the process dies mid-run
        return real_move_one(db, router, tenant_id, target, row)

    monkeypatch.setattr(move, "_move_one", crash_on_third)
    with pytest.raises(KeyboardInterrupt):
        move.run_move(ctx["db"], ctx["router"], tenant, batch_size=1, settle_seconds=0, sleep=lambda _s: None)
    assert _row(ctx, tenant)["move_state"] == "running"
    assert [row["backend"] for row in _objects(ctx, tenant)].count("tenant_s3") == 2

    monkeypatch.setattr(move, "_move_one", real_move_one)
    report = move.run_move(ctx["db"], ctx["router"], tenant, batch_size=1, settle_seconds=0, sleep=lambda _s: None)
    assert (report.state, report.moved, report.total) == ("completed", 4, 4)
    assert {row["backend"] for row in _objects(ctx, tenant)} == {"tenant_s3"}


def test_an_object_that_cannot_be_moved_keeps_working_and_is_never_cleaned_up(ctx) -> None:
    tenant = ctx["tenant"]
    good = _put(ctx, tenant, "good\n")
    bad = _put(ctx, tenant, "bad\n")
    # Corrupt the platform copy of one object: its bytes no longer match its SHA-256.
    ctx["client"].put_object(Bucket=PLATFORM_BUCKET, Key=ctx["platform"].key_for(tenant, bad), Body=b"tampered")
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])

    report = _run_move(ctx, tenant, "tenant")
    assert (report.state, report.moved, report.failed) == ("failed", 1, 1)
    assert "SHA-256" in (report.error or "")
    by_sha = {row["sha256"]: row["backend"] for row in _objects(ctx, tenant)}
    assert by_sha == {good: "tenant_s3", bad: "s3"}
    # The unmoved object is still read from the platform store, and cleanup leaves it there.
    assert ctx["router"].get(tenant, bad) == b"tampered"
    assert move.cleanup_old_copies(ctx["db"], ctx["router"], tenant) == {"checked": 1, "deleted": 1}
    assert _keys(ctx["client"], PLATFORM_BUCKET) == [ctx["platform"].key_for(tenant, bad)]


def test_only_one_move_of_a_tenant_runs_at_a_time(ctx) -> None:
    tenant = ctx["tenant"]
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    move.begin_move(ctx["db"], tenant, "tenant")
    with patch.object(move, "_try_lock", return_value=False):
        with pytest.raises(move.MoveBusy):
            move.run_move(ctx["db"], ctx["router"], tenant, settle_seconds=0)
        with pytest.raises(move.MoveBusy):
            move.cleanup_old_copies(ctx["db"], ctx["router"], tenant)


# ── An unavailable bucket ─────────────────────────────────────────────────────────────────────


class _RevokedClient:
    """An S3 client whose credential was revoked: every call is refused."""

    def __getattr__(self, operation: str) -> Any:
        def refuse(*_args: Any, **_kwargs: Any) -> Any:
            raise ClientError(
                {
                    "Error": {"Code": "InvalidAccessKeyId", "Message": f"The key {TENANT_KEY} does not exist."},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                operation,
            )

        return refuse


def _notifications(ctx: Dict[str, Any], tenant: str) -> List[Dict[str, Any]]:
    return _all(
        ctx,
        "SELECT user_id::text AS user_id, type, payload FROM apiome.notifications WHERE tenant_id = %s::uuid",
        (tenant,),
    )


def test_a_revoked_credential_flags_the_tenant_and_notifies_its_admins_once(ctx, caplog) -> None:
    tenant = ctx["tenant"]
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    sha = _put(ctx, tenant, "openapi: 3.1.0\n")
    assert health_detail(None, database=ctx["db"]) == health_detail(None, database=ctx["db"])  # stable
    assert tenant_buckets(ctx["db"])[0]["unavailableSince"] is None

    ctx["factories"]["client"] = lambda: _RevokedClient()
    ctx["router"].invalidate(tenant)
    caplog.set_level(logging.DEBUG)
    for _attempt in range(3):
        with pytest.raises(tds.TenantDocumentStoreUnavailable) as raised:
            ctx["router"].get(tenant, sha)
    with pytest.raises(tds.TenantDocumentStoreUnavailable):
        ctx["router"].put(tenant, b"new document", MEDIA)

    reason = raised.value.reason
    assert "InvalidAccessKeyId" in reason and ctx["buckets"]["a"] in reason
    # No secret anywhere: the reason, the row, the notification, the logs.
    row = _row(ctx, tenant)
    sent = _notifications(ctx, tenant)
    everything = json.dumps([reason, row["last_error"], sent, caplog.text], default=str)
    assert TENANT_KEY not in everything and TENANT_SECRET not in everything
    assert "[redacted]" in reason

    assert row["unavailable_since"] is not None and "InvalidAccessKeyId" in row["last_error"]
    assert [(n["user_id"], n["type"]) for n in sent] == [(ctx["user"], "document_store_unavailable")]
    assert sent[0]["payload"]["link"] == tds.SETTINGS_LINK

    # The ops plane sees the tenant; the unauthenticated health check sees only a count.
    listed = [item for item in tenant_buckets(ctx["db"]) if item["tenantId"] == tenant]
    assert listed and listed[0]["unavailableSince"] and "InvalidAccessKeyId" in listed[0]["lastError"]
    detail = health_detail(None, database=ctx["db"])
    assert detail["tenant_buckets_unavailable"] >= 1 and detail["status"] in ("degraded", "unavailable")

    # Nothing fell back to the platform bucket.
    assert _keys(ctx["client"], PLATFORM_BUCKET) == []

    # The credential is restored: the next call clears the flag, and a new outage notifies again.
    ctx["factories"]["client"] = lambda: ctx["client"]
    ctx["router"].invalidate(tenant)
    assert ctx["router"].get(tenant, sha) == b"openapi: 3.1.0\n"
    cleared = _row(ctx, tenant)
    assert cleared["unavailable_since"] is None and cleared["last_error"] is None
    assert cleared["last_notified_at"] is None


def test_a_deleted_credential_is_an_outage_not_a_crash(ctx) -> None:
    tenant = ctx["tenant"]
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    # The foreign key refuses to delete a credential in use; break it the way key rotation can.
    monkeypatch_keys = json.dumps({"1": base64.b64encode(os.urandom(32)).decode()})
    with patch.object(settings, "mcp_credential_encryption_keys", monkeypatch_keys):
        ctx["router"].invalidate(tenant)
        with pytest.raises(tds.TenantDocumentStoreUnavailable, match="cannot be opened"):
            ctx["router"].put(tenant, b"document", MEDIA)
    assert _row(ctx, tenant)["unavailable_since"] is not None


def test_a_credential_in_use_cannot_be_deleted(ctx) -> None:
    import psycopg2

    tenant = ctx["tenant"]
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    credential = _row(ctx, tenant)["credential_id"]
    with pytest.raises(psycopg2.errors.ForeignKeyViolation):
        ctx["db"].delete_export_storage_credential(tenant, str(credential))


def test_rendered_documents_still_answer_while_the_bucket_is_down(ctx) -> None:
    from app.rendered_documents import KIND_OPENAPI, rendered_document

    tenant = ctx["tenant"]
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    ctx["factories"]["client"] = lambda: _RevokedClient()
    ctx["router"].invalidate(tenant)

    document = rendered_document(
        ctx["version"], KIND_OPENAPI, tenant_id=tenant, database=ctx["db"], store=ctx["router"]
    )
    assert document is not None and json.loads(document.content())["openapi"].startswith("3.")
    assert (document.cached, document.stored) == (False, False)
    # It was rendered, not cached: nothing was stored anywhere.
    assert _objects(ctx, tenant) == []
    assert _keys(ctx["client"], PLATFORM_BUCKET) == []
    assert _row(ctx, tenant)["unavailable_since"] is not None


def test_deleting_a_tenant_empties_only_apiomes_folder_in_its_bucket(ctx) -> None:
    tenant, bucket = ctx["tenant"], ctx["buckets"]["a"]
    _use_bucket(ctx, tenant, bucket)
    _put(ctx, tenant, "openapi: 3.1.0\n")
    ctx["client"].put_object(Bucket=bucket, Key="their-own/data.csv", Body=b"not ours")
    ctx["client"].put_object(Bucket=bucket, Key="apiome/tenants/someone-else/objects/x", Body=b"not ours either")

    assert ctx["router"].delete_tenant_objects(tenant) == 1
    assert sorted(_keys(ctx["client"], bucket)) == ["apiome/tenants/someone-else/objects/x", "their-own/data.csv"]
    assert ctx["client"].head_bucket(Bucket=bucket)["ResponseMetadata"]["HTTPStatusCode"] == 200


def test_the_lifecycle_purges_an_object_from_the_tenant_bucket(ctx) -> None:
    from app import document_lifecycle as lifecycle

    tenant = ctx["tenant"]
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    sha = _put(ctx, tenant, "unreferenced\n")
    object_id = _one(
        ctx, "SELECT id::text AS id FROM apiome.document_objects WHERE tenant_id = %s AND sha256 = %s", (tenant, sha)
    )["id"]
    purged = lifecycle.purge_object(ctx["db"], ctx["router"], object_id, reason="unreferenced")
    assert purged is not None and purged["backend"] == "tenant_s3"
    assert _keys(ctx["client"], ctx["buckets"]["a"]) == []
    _one(ctx, "DELETE FROM apiome.document_lifecycle_events WHERE tenant_id = %s", (tenant,))


# ── The REST routes ───────────────────────────────────────────────────────────────────────────


@pytest.fixture
def api(ctx, monkeypatch) -> Iterator[TestClient]:
    """The routes on the test database and router, authenticated as tenant A's administrator."""
    auth = {"tenant_id": ctx["tenant"], "user_id": ctx["user"], "auth_method": "jwt", "user_email": "admin@acme.io"}
    monkeypatch.setattr(routes, "db", ctx["db"])
    monkeypatch.setattr("app.sdk_publish_routes.db", ctx["db"])
    monkeypatch.setattr(routes, "get_document_store", lambda: ctx["router"])
    monkeypatch.setattr(
        routes,
        "build_tenant_store",
        lambda database, store_settings: tds.build_tenant_store(
            database, store_settings, client_factory=lambda: ctx["factories"]["client"]()
        ),
    )
    # The move runs in the request instead of a background thread: the test connection is shared.
    monkeypatch.setattr(
        routes,
        "start_move_thread",
        lambda database, router, tenant: bool(
            move.run_move(database, router, tenant, settle_seconds=0, sleep=lambda _s: None)
        ),
    )
    app.dependency_overrides[validate_authentication] = lambda: auth
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)


def _url(ctx: Dict[str, Any], suffix: str = "") -> str:
    return f"/v1/tenants/acme/document-store{suffix}"


def test_routes_read_the_default_and_refuse_changes_when_the_install_does_not_offer_buckets(
    ctx, api, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "document_store_allow_tenant_buckets", False)
    body = api.get(_url(ctx)).json()
    assert body["allowed"] is False and body["mode"] == "platform" and body["bucket"] is None
    assert body["health"] == {"available": True, "unavailableSince": None, "error": None}
    for response in (
        api.put(_url(ctx), json={"mode": "tenant", "bucket": "x-bucket"}),
        api.post(_url(ctx, "/test")),
        api.post(_url(ctx, "/cleanup"), json={"confirm": True}),
    ):
        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "tenant-document-store-disabled"


def test_routes_need_document_store_manage(ctx, api) -> None:
    _one(ctx, "DELETE FROM apiome.tenant_administrators WHERE tenant_id = %s::uuid", (ctx["tenant"],))
    assert api.get(_url(ctx)).status_code == 403
    assert api.put(_url(ctx), json={"mode": "platform"}).status_code == 403
    assert api.post(_url(ctx, "/cleanup"), json={"confirm": True}).status_code == 403


def test_put_validates_tests_saves_moves_and_audits_without_a_secret(ctx, api) -> None:
    tenant, bucket = ctx["tenant"], ctx["buckets"]["a"]
    shas = [_put(ctx, tenant, f"doc {n}\n") for n in range(3)]
    credential = _credential(ctx, tenant)

    invalid = api.put(_url(ctx), json={"mode": "tenant", "bucket": "Not_A_Bucket", "credentialId": credential})
    assert invalid.status_code == 400 and invalid.json()["detail"]["code"] == "tenant-document-store-invalid"
    missing = api.put(_url(ctx), json={"mode": "tenant", "bucket": bucket, "credentialId": str(uuid.uuid4())})
    assert missing.status_code == 400 and "credentialId" in missing.json()["detail"]["errors"][0]
    absent = api.put(_url(ctx), json={"mode": "tenant", "bucket": "no-such-bucket-here", "credentialId": credential})
    assert absent.status_code == 400 and absent.json()["detail"]["code"] == "tenant-document-store-test-failed"
    assert _row(ctx, tenant) == {}

    tested = api.post(_url(ctx, "/test"), json={"mode": "tenant", "bucket": bucket, "credentialId": credential})
    assert tested.status_code == 200 and tested.json()["ok"] is True
    assert [step["name"] for step in tested.json()["steps"]] == ["write", "read", "delete"]
    assert _keys(ctx["client"], bucket) == []  # the probe cleaned up after itself

    saved = api.put(_url(ctx), json={"mode": "tenant", "bucket": bucket, "credentialId": credential, "sse": "s3"})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["mode"], body["bucket"], body["credentialName"], body["sse"]) == ("tenant", bucket, "documents", "s3")
    assert body["move"]["state"] == "completed" and body["move"]["moved"] == 3 and body["cleanupPending"] is True
    assert all(ctx["router"].get(tenant, sha) for sha in shas)
    assert {row["backend"] for row in _objects(ctx, tenant)} == {"tenant_s3"}

    # The bucket cannot be swapped while documents are in it.
    swapped = api.put(_url(ctx), json={"mode": "tenant", "bucket": ctx["buckets"]["b"], "credentialId": credential})
    assert swapped.status_code == 409 and swapped.json()["detail"]["code"] == "tenant-document-store-bucket-in-use"

    unconfirmed = api.post(_url(ctx, "/cleanup"), json={})
    assert unconfirmed.status_code == 400
    assert unconfirmed.json()["detail"]["code"] == "tenant-document-store-confirm-required"
    assert len(_keys(ctx["client"], PLATFORM_BUCKET)) == 3
    cleaned = api.post(_url(ctx, "/cleanup"), json={"confirm": True})
    assert cleaned.status_code == 200 and cleaned.json() == {"checked": 3, "deleted": 3}
    assert _keys(ctx["client"], PLATFORM_BUCKET) == []

    back = api.put(_url(ctx), json={"mode": "platform"})
    assert back.status_code == 200 and back.json()["mode"] == "platform" and back.json()["bucket"] == bucket
    assert {row["backend"] for row in _objects(ctx, tenant)} == {"s3"}

    audit = _all(
        ctx, "SELECT action, detail FROM apiome.access_audit WHERE tenant_id = %s::uuid ORDER BY created_at", (tenant,)
    )
    assert [row["action"] for row in audit] == [
        "document_store.settings_updated",
        "document_store.old_copies_deleted",
        "document_store.settings_updated",
    ]
    assert audit[0]["detail"]["bucket"] == bucket and audit[0]["detail"]["moveStarted"] is True
    everything = json.dumps([audit, saved.json(), tested.json(), back.json(), api.get(_url(ctx)).json()], default=str)
    assert TENANT_KEY not in everything and TENANT_SECRET not in everything


def test_put_is_refused_while_a_move_runs_here(ctx, api, monkeypatch) -> None:
    tenant = ctx["tenant"]
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    move.begin_move(ctx["db"], tenant, "tenant")
    monkeypatch.setattr(routes, "move_running_here", lambda _tenant: True)
    response = api.put(_url(ctx), json={"mode": "platform"})
    assert response.status_code == 409 and response.json()["detail"]["code"] == "tenant-document-store-move-running"


def test_an_unavailable_bucket_answers_503_with_the_reason_and_no_secret(ctx, api) -> None:
    from fastapi import APIRouter

    tenant = ctx["tenant"]
    _use_bucket(ctx, tenant, ctx["buckets"]["a"])
    sha = hashlib.sha256(b"x").hexdigest()
    ctx["factories"]["client"] = lambda: _RevokedClient()
    ctx["router"].invalidate(tenant)

    probe = APIRouter()

    @probe.get("/_test/tenant-document")
    def read() -> bytes:
        return ctx["router"].get(tenant, sha)

    app.include_router(probe)
    try:
        response = api.get("/_test/tenant-document")
    finally:
        app.router.routes[:] = [
            route for route in app.router.routes if getattr(route, "path", "") != "/_test/tenant-document"
        ]
    assert response.status_code == 503 and response.headers["retry-after"] == "60"
    detail = response.json()["detail"]
    assert detail["code"] == "tenant-document-store-unavailable" and "InvalidAccessKeyId" in detail["reason"]
    assert TENANT_KEY not in response.text and TENANT_SECRET not in response.text

    status = api.get(_url(ctx)).json()
    assert status["health"]["available"] is False and "InvalidAccessKeyId" in status["health"]["error"]
    tested = api.post(_url(ctx, "/test")).json()
    assert tested["ok"] is False and TENANT_KEY not in json.dumps(tested)
