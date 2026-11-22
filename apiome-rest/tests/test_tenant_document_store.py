"""Per-tenant bring-your-own buckets without a database — COA-5.15 (#7092).

Validation of submitted settings, the SSRF guard on a tenant endpoint, the routing rules of
:class:`TenantRoutingDocumentStore` with in-memory stores, the permission vocabulary and the
migration's promises. The end-to-end behaviour (isolation, the move, outages, the routes) is in
``test_tenant_document_store_db.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from app import document_store as store_module
from app import document_store_router as router_module
from app import tenant_document_store as tds
from app.config import settings
from app.document_store import DocumentNotFound, DocumentStoreError, FilesystemDocumentStore
from app.document_store_router import TenantRoutingDocumentStore
from app.permissions import ACTIONS, RESOURCES, Action, Resource, permission_key
from app.tenant_document_store import TenantStoreInputError, TenantStoreSettings, normalize_settings

TENANT = "11111111-1111-1111-1111-111111111111"
CREDENTIAL = {"id": "22222222-2222-2222-2222-222222222222", "name": "documents", "endpoint_url": None}
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _payload(**overrides: Any) -> Dict[str, Any]:
    payload = {"mode": "tenant", "credential_id": CREDENTIAL["id"], "bucket": "acme-documents"}
    payload.update(overrides)
    return payload


# ── Validation ────────────────────────────────────────────────────────────────────────────────


def test_a_complete_bucket_is_normalized_with_defaults() -> None:
    values = normalize_settings(
        _payload(prefix="/teams/apiome/", sse="KMS", kms_key_id=" alias/docs "), credential=CREDENTIAL
    )
    assert values == {
        "mode": "tenant",
        "credential_id": CREDENTIAL["id"],
        "bucket": "acme-documents",
        "prefix": "teams/apiome",
        "region": "",
        "endpoint_url": "",
        "addressing_style": "auto",
        "sse": "kms",
        "kms_key_id": "alias/docs",
    }
    assert normalize_settings(_payload(), credential=CREDENTIAL)["prefix"] == "apiome"
    assert normalize_settings(_payload(prefix=""), credential=CREDENTIAL)["prefix"] == ""


def test_the_platform_mode_needs_no_bucket() -> None:
    values = normalize_settings({"mode": "platform"}, credential=None)
    assert (values["mode"], values["bucket"], values["credential_id"]) == ("platform", None, None)


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"bucket": None}, "bucket"),
        ({"bucket": "Has_Upper"}, "bucket"),
        ({"bucket": "ab"}, "bucket"),
        ({"bucket": "a..b-bucket"}, "bucket"),
        ({"credential_id": None}, "credentialId"),
        ({"prefix": "a/../b"}, "prefix"),
        ({"addressing_style": "subdomain"}, "addressingStyle"),
        ({"sse": "aes"}, "sse"),
        ({"kms_key_id": "alias/docs"}, "kmsKeyId"),
        ({"region": "us east"}, "region"),
    ],
)
def test_a_bad_field_is_named(overrides: Dict[str, Any], field: str) -> None:
    with pytest.raises(TenantStoreInputError) as raised:
        normalize_settings(_payload(**overrides), credential=CREDENTIAL)
    assert raised.value.code == "tenant-document-store-invalid"
    assert any(error.startswith(f"{field}:") for error in raised.value.errors)


def test_an_unknown_credential_and_mode_are_refused() -> None:
    with pytest.raises(TenantStoreInputError, match="no storage credential"):
        normalize_settings(_payload(), credential=None)
    with pytest.raises(TenantStoreInputError, match="mode"):
        normalize_settings(_payload(mode="both"), credential=CREDENTIAL)


@pytest.mark.parametrize("endpoint", ["http://169.254.169.254/latest", "http://127.0.0.1:9000", "ftp://minio.example"])
def test_a_tenant_endpoint_passes_the_ssrf_guard(endpoint: str, monkeypatch) -> None:
    monkeypatch.setattr(settings, "document_store_tenant_allow_private", False)
    monkeypatch.setattr(settings, "ssrf_allow_private", False, raising=False)
    with pytest.raises(TenantStoreInputError) as raised:
        normalize_settings(_payload(endpoint_url=endpoint), credential=CREDENTIAL)
    assert raised.value.code == "tenant-document-store-endpoint-refused"


def test_the_credentials_own_endpoint_is_guarded_too(monkeypatch) -> None:
    monkeypatch.setattr(settings, "document_store_tenant_allow_private", False)
    monkeypatch.setattr(settings, "ssrf_allow_private", False, raising=False)
    with pytest.raises(TenantStoreInputError):
        normalize_settings(_payload(), credential={**CREDENTIAL, "endpoint_url": "http://10.0.0.5:9000"})


def test_a_private_endpoint_needs_the_platform_setting(monkeypatch) -> None:
    monkeypatch.setattr(settings, "document_store_tenant_allow_private", True)
    values = normalize_settings(_payload(endpoint_url="http://10.0.0.5:9000"), credential=CREDENTIAL)
    assert values["endpoint_url"] == "http://10.0.0.5:9000"
    # Scheme and credentials-in-URL rules still apply.
    with pytest.raises(TenantStoreInputError):
        normalize_settings(_payload(endpoint_url="http://user:pass@10.0.0.5:9000"), credential=CREDENTIAL)


def test_an_unavailable_error_caps_its_reason() -> None:
    error = tds.TenantDocumentStoreUnavailable(TENANT, "x" * 5000)
    assert len(error.reason) == 500 and error.code == "tenant-document-store-unavailable"
    assert isinstance(error, DocumentStoreError)


# ── Routing ───────────────────────────────────────────────────────────────────────────────────


class _TenantBucket(FilesystemDocumentStore):
    """A stand-in for a tenant's bucket: a directory, recorded as ``tenant_s3``."""

    backend = "tenant_s3"

    def _uri(self, key: str) -> str:
        return f"s3://tenant-bucket/{key}"


@pytest.fixture
def stores(tmp_path, monkeypatch):
    """A platform store, a tenant bucket, and a router whose settings and index are in memory."""
    platform = FilesystemDocumentStore(path=str(tmp_path / "platform"), prefix="apiome")
    bucket = _TenantBucket(path=str(tmp_path / "bucket"), prefix="apiome")
    state: Dict[str, Any] = {"settings": None, "index": {}, "loads": 0, "outages": [], "recoveries": 0}

    def load(_db: Any, _tenant: str) -> Optional[TenantStoreSettings]:
        state["loads"] += 1
        return state["settings"]

    monkeypatch.setattr(router_module, "load_settings", load)
    monkeypatch.setattr(router_module, "record_outage", lambda _db, tenant, reason: state["outages"].append(reason))
    monkeypatch.setattr(
        router_module,
        "record_recovery",
        lambda _db, _tenant, flagged=False: state.__setitem__("recoveries", state["recoveries"] + 1),
    )
    router = TenantRoutingDocumentStore(
        platform, database=object(), build=lambda _db, _settings: bucket, ttl_seconds=60, active=lambda: True
    )
    monkeypatch.setattr(router, "_indexed_backend", lambda _tenant, sha: state["index"].get(sha))
    return platform, bucket, router, state


def _on_bucket(mode: str = "tenant") -> TenantStoreSettings:
    return TenantStoreSettings(tenant_id=TENANT, mode=mode, credential_id=CREDENTIAL["id"], bucket="tenant-bucket")


def test_a_tenant_without_settings_goes_to_the_platform_store(stores) -> None:
    platform, bucket, router, state = stores
    ref = router.put(TENANT, b"document")
    assert ref.backend == "filesystem" and platform.exists(TENANT, ref.sha256) and not bucket.exists(TENANT, ref.sha256)
    assert router.get(TENANT, ref.sha256) == b"document"
    assert router.target_backend(TENANT) == "filesystem"
    # Settings are cached: many calls, one read.
    assert state["loads"] == 1


def test_writes_follow_the_mode_and_reads_follow_the_index(stores) -> None:
    platform, bucket, router, state = stores
    old = platform.put(TENANT, b"written before the switch")
    state["index"][old.sha256] = "filesystem"
    state["settings"] = _on_bucket()

    new = router.put(TENANT, b"written after the switch")
    assert new.backend == "tenant_s3" and bucket.exists(TENANT, new.sha256) and not platform.exists(TENANT, new.sha256)
    state["index"][new.sha256] = "tenant_s3"
    assert router.target_backend(TENANT) == "tenant_s3"

    assert router.get(TENANT, old.sha256) == b"written before the switch"
    assert router.get(TENANT, new.sha256) == b"written after the switch"
    assert router.head(TENANT, new.sha256).uri.startswith("s3://tenant-bucket/")
    assert router.delete(TENANT, old.sha256) is True and not platform.exists(TENANT, old.sha256)


def test_an_object_with_no_index_row_is_looked_for_in_both_places(stores) -> None:
    platform, bucket, router, state = stores
    state["settings"] = _on_bucket()
    stray = platform.put(TENANT, b"stored on stale settings, not indexed yet")
    assert router.get(TENANT, stray.sha256) == b"stored on stale settings, not indexed yet"
    assert router.exists(TENANT, stray.sha256)
    with pytest.raises(DocumentNotFound):
        router.get(TENANT, "0" * 64)
    assert router.head(TENANT, "0" * 64) is None and router.delete(TENANT, "0" * 64) is False


def test_a_failing_bucket_is_an_outage_and_never_falls_back_for_writes(stores, monkeypatch, tmp_path) -> None:
    platform, bucket, router, state = stores
    state["settings"] = _on_bucket()

    def fail(*_args: Any, **_kwargs: Any) -> Any:
        raise DocumentStoreError("Apiome could not write to bucket 'tenant-bucket' (AccessDenied).")

    monkeypatch.setattr(bucket, "put", fail)
    with pytest.raises(tds.TenantDocumentStoreUnavailable, match="AccessDenied"):
        router.put(TENANT, b"document")
    assert state["outages"] == ["Apiome could not write to bucket 'tenant-bucket' (AccessDenied)."]
    # Nothing was written to the platform store instead.
    assert not any(item.is_file() for item in (tmp_path / "platform").rglob("*"))


def test_a_successful_call_reports_recovery(stores) -> None:
    _platform, _bucket, router, state = stores
    state["settings"] = _on_bucket()
    router.put(TENANT, b"document")
    assert state["recoveries"] == 1 and state["outages"] == []


def test_a_credential_that_cannot_be_opened_is_recorded_once_per_settings_read(stores) -> None:
    platform, _bucket, _router, state = stores
    state["settings"] = _on_bucket()

    def build(_db: Any, _settings: TenantStoreSettings) -> Any:
        raise tds.TenantDocumentStoreUnavailable(TENANT, "The storage credential cannot be opened.")

    router = TenantRoutingDocumentStore(platform, database=object(), build=build, ttl_seconds=60, active=lambda: True)
    for _attempt in range(3):
        with pytest.raises(tds.TenantDocumentStoreUnavailable, match="cannot be opened"):
            router.put(TENANT, b"document")
    assert state["outages"] == ["The storage credential cannot be opened."]


def test_invalidate_re_reads_the_settings(stores) -> None:
    _platform, _bucket, router, state = stores
    assert router.target_backend(TENANT) == "filesystem"
    state["settings"] = _on_bucket()
    assert router.target_backend(TENANT) == "filesystem"  # still cached
    router.invalidate(TENANT)
    assert router.target_backend(TENANT) == "tenant_s3"


def test_a_tenant_back_on_the_platform_store_still_reads_what_is_left_in_its_bucket(stores) -> None:
    platform, bucket, router, state = stores
    left = bucket.put(TENANT, b"not moved back yet")
    state["index"][left.sha256] = "tenant_s3"
    state["settings"] = _on_bucket(mode="platform")
    assert router.get(TENANT, left.sha256) == b"not moved back yet"
    assert router.put(TENANT, b"new").backend == "filesystem"


def test_routing_is_off_until_the_install_allows_buckets_or_a_tenant_has_one(tmp_path, monkeypatch) -> None:
    platform = FilesystemDocumentStore(path=str(tmp_path / "platform"), prefix="apiome")
    monkeypatch.setattr(settings, "document_store_allow_tenant_buckets", False)
    monkeypatch.setattr(router_module, "_tenant_rows_seen", False)
    monkeypatch.setattr(router_module, "load_settings", lambda *_a: pytest.fail("the database must not be asked"))
    store_module.set_document_store(platform)
    try:
        # The platform store itself: no wrapper, no per-tenant lookup.
        assert store_module.get_document_store() is platform
        assert TenantRoutingDocumentStore(platform).put(TENANT, b"x").backend == "filesystem"

        monkeypatch.setattr(settings, "document_store_allow_tenant_buckets", True)
        routed = store_module.get_document_store()
        assert isinstance(routed, TenantRoutingDocumentStore) and routed.platform is platform
        assert store_module.get_document_store() is routed
        assert store_module.get_platform_document_store() is platform
        assert routed.prefix == "apiome"  # platform settings read through

        # A tenant that already has a bucket keeps routing on with the setting off.
        monkeypatch.setattr(settings, "document_store_allow_tenant_buckets", False)
        monkeypatch.setattr(router_module, "_tenant_rows_seen", True)
        assert router_module.routing_active() is True
    finally:
        store_module.set_document_store(None)


def test_a_failed_startup_check_turns_routing_on(monkeypatch) -> None:
    class Broken:
        def connect(self) -> Any:
            raise RuntimeError("database is down")

    monkeypatch.setattr(settings, "document_store_allow_tenant_buckets", False)
    monkeypatch.setattr(router_module, "_tenant_rows_seen", False)
    assert router_module.refresh_routing(Broken()) is True


# ── Permission and migration ──────────────────────────────────────────────────────────────────


def test_document_store_manage_is_in_the_permission_vocabulary() -> None:
    assert Resource.DOCUMENT_STORE in RESOURCES and Action.MANAGE in ACTIONS
    assert permission_key(Resource.DOCUMENT_STORE, Action.MANAGE) == "document_store:manage"


def test_the_migration_keeps_its_promises() -> None:
    sql = (_REPO_ROOT / "apiome-db/scripts/V408__tenant_document_stores_7092.sql").read_text()
    ddl = " ".join(line.split("--")[0] for line in sql.splitlines()).lower()
    assert "create table if not exists apiome.tenant_document_stores" in ddl
    assert "check (backend in ('db', 's3', 'filesystem', 'tenant_s3'))" in ddl
    # Owner and Admin get the grant; Editor and Viewer do not.
    assert "(v_owner, 'document_store', 'manage')" in ddl and "(v_admin, 'document_store', 'manage')" in ddl
    assert "v_editor, 'document_store'" not in ddl and "v_viewer, 'document_store'" not in ddl
    assert "'document_store'" not in ddl.split("all_resources text[] := array[")[1].split("];")[0]
    # The table never holds a key: the credential is referenced, not copied.
    assert "secret" not in ddl and "access_key" not in ddl
    assert "references apiome.export_storage_credentials(id) on delete no action" in ddl
