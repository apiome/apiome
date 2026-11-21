"""Tests for document store settings, health and the connection test (COA-5.9, #7085).

* :func:`initialize_document_store` — fail fast with a redacted message, or fall back to ``db``
  only when ``APIOME_DOCUMENT_STORE_FALLBACK=db``.
* :func:`check_reachable`, :func:`store_health` (cached) and :func:`health_detail`.
* :func:`describe_store` — non-secret settings and index usage.
* :func:`probe_store` — write, read back, delete; failures are reported per step and redacted.
* The routes on both planes: ``/v1/ops/document-store`` (platform admin) and
  ``/v1/admin/document-store`` (super-admin session).
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import patch

import boto3
import pytest
from botocore.config import Config
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from moto import mock_aws

from app import document_store_health as health
from app import document_store_routes as routes
from app.auth import validate_authentication
from app.config import settings
from app.document_store import (
    DbDocumentStore,
    DocumentStoreConfigError,
    FilesystemDocumentStore,
    S3DocumentStore,
)
from app.main import app

BUCKET = "apiome-documents"
ACCESS_KEY = "AKIAEXAMPLEKEY000001"
SECRET_KEY = "s3cr3t-Example/Key+Value0123456789abcdef"
_ADMIN_SECRET = "test-admin-session-secret"
_AUTH = {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "user_id": "22222222-2222-2222-2222-222222222222",
    "auth_method": "jwt",
    "user_email": "ops@acme.io",
}


class FakeBlobDatabase:
    """In-memory ``*_document_store_blob`` methods, plus the usage summary and a probe query."""

    def __init__(self, usage=None, fail_query: bool = False) -> None:
        self.rows: dict = {}
        self.usage = usage or []
        self.fail_query = fail_query

    def put_document_store_blob(self, *, tenant_id, sha256, size_bytes, media_type, content):
        if (tenant_id, sha256) in self.rows:
            return False
        self.rows[(tenant_id, sha256)] = {"size_bytes": size_bytes, "media_type": media_type, "content": content}
        return True

    def head_document_store_blob(self, tenant_id, sha256):
        row = self.rows.get((tenant_id, sha256))
        return None if row is None else {"size_bytes": row["size_bytes"], "media_type": row["media_type"]}

    def get_document_store_blob(self, tenant_id, sha256):
        row = self.rows.get((tenant_id, sha256))
        return None if row is None else row["content"]

    def delete_document_store_blob(self, tenant_id, sha256):
        return self.rows.pop((tenant_id, sha256), None) is not None

    def execute_query(self, query, params=None):
        if self.fail_query:
            raise RuntimeError("relation does not exist")
        return [{"ok": 1}]

    def document_store_usage(self):
        if self.fail_query:
            raise RuntimeError("relation does not exist")
        return self.usage


def _config(**overrides):
    """Settings with the database backend; override any ``document_store*`` field."""
    values = dict(
        document_store="db",
        document_store_bucket="",
        document_store_prefix="apiome",
        document_store_path="",
        document_store_region="",
        document_store_endpoint_url="",
        document_store_addressing_style="auto",
        document_store_sse="",
        document_store_kms_key_id="",
        document_store_access_key_id="",
        document_store_secret_access_key="",
        document_store_presign_ttl_seconds=300,
        document_store_db_max_bytes=1024,
        document_store_allow_private=False,
        document_store_fallback="",
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture(autouse=True)
def _reset():
    """Every test starts without a startup resolution or a cached health result."""
    health.reset_document_store_health()
    yield
    health.reset_document_store_health()


@pytest.fixture
def s3_client():
    """A boto3 client bound to an in-process moto S3 with the test bucket created."""
    with mock_aws():
        client = boto3.client(
            "s3",
            region_name="us-east-1",
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
            config=Config(signature_version="s3v4"),
        )
        client.create_bucket(Bucket=BUCKET)
        yield client


def _s3_store(client, **overrides) -> S3DocumentStore:
    options = dict(
        bucket=BUCKET,
        prefix="apiome",
        access_key_id=ACCESS_KEY,
        secret_access_key=SECRET_KEY,
        client_factory=lambda: client,
    )
    options.update(overrides)
    return S3DocumentStore(**options)


class _FailingClient:
    """An S3 client whose every call fails with an error quoting both keys."""

    def __getattr__(self, name):
        def _fail(*args, **kwargs):
            raise ClientError(
                {"Error": {"Code": "InvalidAccessKeyId", "Message": f"key {ACCESS_KEY} / {SECRET_KEY}"}},
                "HeadBucket",
            )

        return _fail


# ───────────────────────────── startup ─────────────────────────────


class TestInitialize:
    def test_the_db_backend_starts_without_touching_the_database(self):
        installed = []
        resolution = health.initialize_document_store(_config(), install=installed.append)
        assert resolution == health.StoreResolution("db", "db")
        assert isinstance(installed[0], DbDocumentStore)
        assert health.current_resolution().fallback is False

    def test_a_reachable_bucket_starts_on_s3(self, s3_client):
        installed = []
        cfg = _config(
            document_store="s3",
            document_store_bucket=BUCKET,
            document_store_access_key_id=ACCESS_KEY,
            document_store_secret_access_key=SECRET_KEY,
        )
        resolution = health.initialize_document_store(cfg, install=installed.append)
        assert resolution.active_backend == "s3" and not resolution.fallback
        assert isinstance(installed[0], S3DocumentStore)

    def test_a_missing_bucket_fails_fast_with_a_redacted_actionable_message(self, s3_client, caplog):
        cfg = _config(
            document_store="s3",
            document_store_bucket="no-such-bucket",
            document_store_access_key_id=ACCESS_KEY,
            document_store_secret_access_key=SECRET_KEY,
        )
        installed = []
        # botocore's own DEBUG wire logs are out of scope; Apiome's messages are WARNING and up.
        with caplog.at_level(logging.WARNING), pytest.raises(DocumentStoreConfigError) as excinfo:
            health.initialize_document_store(cfg, install=installed.append)
        message = str(excinfo.value)
        assert "no-such-bucket" in message
        assert "APIOME_DOCUMENT_STORE_FALLBACK=db" in message
        for text in (message, caplog.text):
            assert SECRET_KEY not in text and ACCESS_KEY not in text
        assert installed == []

    def test_a_missing_setting_fails_fast(self):
        with pytest.raises(DocumentStoreConfigError) as excinfo:
            health.initialize_document_store(_config(document_store="s3"), install=lambda s: None)
        assert "APIOME_DOCUMENT_STORE_BUCKET" in str(excinfo.value)

    def test_an_unknown_backend_fails_fast(self):
        with pytest.raises(DocumentStoreConfigError) as excinfo:
            health.initialize_document_store(_config(document_store="gcs"), install=lambda s: None)
        assert "APIOME_DOCUMENT_STORE must be one of" in str(excinfo.value)

    def test_the_fallback_starts_on_db_and_reports_why(self, caplog):
        installed = []
        cfg = _config(document_store="filesystem", document_store_path="", document_store_fallback="DB")
        with caplog.at_level(logging.ERROR):
            resolution = health.initialize_document_store(cfg, install=installed.append)
        assert resolution.configured_backend == "filesystem"
        assert resolution.active_backend == "db" and resolution.fallback
        assert "APIOME_DOCUMENT_STORE_PATH" in resolution.fallback_reason
        assert isinstance(installed[0], DbDocumentStore)
        assert "starting on the database store" in caplog.text
        assert health.current_resolution() == resolution

    def test_the_fallback_redacts_credentials(self):
        cfg = _config(
            document_store="s3",
            document_store_bucket=BUCKET,
            document_store_access_key_id=ACCESS_KEY,
            document_store_secret_access_key=SECRET_KEY,
            document_store_fallback="db",
        )
        with patch.object(S3DocumentStore, "_build_client", lambda self: _FailingClient()):
            resolution = health.initialize_document_store(cfg, install=lambda s: None)
        assert resolution.fallback
        assert SECRET_KEY not in resolution.fallback_reason and ACCESS_KEY not in resolution.fallback_reason

    def test_the_fallback_survives_a_bad_prefix(self):
        installed = []
        cfg = _config(document_store_prefix="../up", document_store="s3", document_store_fallback="db")
        resolution = health.initialize_document_store(cfg, install=installed.append)
        assert resolution.fallback and installed[0].prefix == ""

    def test_a_bad_prefix_on_db_is_not_rescued(self):
        cfg = _config(document_store_prefix="../up", document_store_fallback="db")
        with pytest.raises(DocumentStoreConfigError):
            health.initialize_document_store(cfg, install=lambda s: None)

    def test_an_unknown_fallback_value_is_refused(self):
        with pytest.raises(DocumentStoreConfigError) as excinfo:
            health.initialize_document_store(_config(document_store_fallback="s3"), install=lambda s: None)
        assert "APIOME_DOCUMENT_STORE_FALLBACK" in str(excinfo.value)

    def test_the_fallback_setting_defaults_to_empty(self):
        assert settings.document_store_fallback == ""

    def test_a_writable_directory_starts_on_filesystem(self, tmp_path):
        installed = []
        cfg = _config(document_store="filesystem", document_store_path=str(tmp_path / "store"))
        resolution = health.initialize_document_store(cfg, install=installed.append)
        assert resolution.active_backend == "filesystem"
        assert (tmp_path / "store").is_dir()


# ───────────────────────────── reachability and health ─────────────────────────────


class TestReachability:
    def test_an_unwritable_directory_is_unreachable(self, tmp_path):
        target = tmp_path / "file"
        target.write_text("not a directory")
        store = FilesystemDocumentStore(path=str(target))
        with pytest.raises(Exception) as excinfo:
            health.check_reachable(store)
        assert "APIOME_DOCUMENT_STORE_PATH" in str(excinfo.value)

    def test_the_db_backend_reads_the_blob_table(self):
        health.check_reachable(DbDocumentStore(database=FakeBlobDatabase()))
        with pytest.raises(Exception) as excinfo:
            health.check_reachable(DbDocumentStore(database=FakeBlobDatabase(fail_query=True)))
        assert "V402" in str(excinfo.value)

    def test_the_db_check_can_be_skipped(self):
        health.check_reachable(DbDocumentStore(database=FakeBlobDatabase(fail_query=True)), include_db=False)

    def test_health_is_cached_for_the_ttl(self):
        calls = []
        clock = [1000.0]
        with (
            patch.object(health, "check_reachable", lambda store: calls.append(store)),
            patch.object(health, "get_document_store", return_value=object()),
        ):
            first = health.store_health(now=lambda: clock[0])
            clock[0] += health.HEALTH_TTL_SECONDS - 1
            assert health.store_health(now=lambda: clock[0]) is first
            clock[0] += 2
            health.store_health(now=lambda: clock[0])
            health.store_health(force=True, now=lambda: clock[0])
        assert len(calls) == 3

    def test_health_detail_reports_ok_degraded_and_unavailable(self):
        ok = health.StoreHealth(ok=True, checked_at=0)
        down = health.StoreHealth(ok=False, checked_at=0, error="no")
        assert health.health_detail(ok) == {"status": "ok", "backend": "db", "fallback": False}
        assert health.health_detail(down)["status"] == "unavailable"
        cfg = _config(document_store="s3", document_store_fallback="db")
        health.initialize_document_store(cfg, install=lambda s: None)
        assert health.health_detail(ok) == {"status": "degraded", "backend": "db", "fallback": True}

    def test_health_failures_are_redacted(self, s3_client):
        store = _s3_store(_FailingClient())
        with patch.object(health, "get_document_store", return_value=store):
            result = health.store_health(force=True)
        assert not result.ok
        assert SECRET_KEY not in result.error and ACCESS_KEY not in result.error


# ───────────────────────────── describe ─────────────────────────────


class TestDescribe:
    def test_s3_settings_never_include_credentials(self, s3_client):
        store = _s3_store(s3_client, sse="kms", kms_key_id="alias/apiome", region="eu-west-1")
        body = health.describe_store(FakeBlobDatabase(), store=store)
        assert body["backend"] == "s3" and body["bucket"] == BUCKET
        assert body["prefix"] == "apiome" and body["region"] == "eu-west-1"
        assert body["encryption"] == "sse-kms" and body["kmsKeyId"] == "alias/apiome"
        assert body["credentials"] == "static"
        assert body["health"]["ok"] is True
        text = json.dumps(body)
        assert SECRET_KEY not in text and ACCESS_KEY not in text

    def test_s3_without_keys_uses_the_default_chain(self, s3_client):
        store = _s3_store(s3_client, access_key_id="", secret_access_key="")
        body = health.describe_store(FakeBlobDatabase(), store=store)
        assert body["credentials"] == "default-chain" and body["encryption"] == "none"

    def test_filesystem_and_db_settings(self, tmp_path):
        fs = health.describe_store(FakeBlobDatabase(), store=FilesystemDocumentStore(path=str(tmp_path)))
        assert fs["path"] == str(tmp_path.resolve()) and fs["bucket"] is None
        db_body = health.describe_store(
            FakeBlobDatabase(), store=DbDocumentStore(max_bytes=2048, database=FakeBlobDatabase())
        )
        assert db_body["maxObjectBytes"] == 2048 and db_body["encryption"] is None

    def test_usage_sums_backends_and_reports_the_latest_verification(self):
        verified = datetime(2026, 11, 20, 8, 30, tzinfo=timezone.utc)
        usage = [
            {"backend": "db", "objects": 3, "bytes": 300, "verified_objects": 0, "last_verified_at": None},
            {"backend": "s3", "objects": 7, "bytes": 7000, "verified_objects": 5, "last_verified_at": verified},
        ]
        body = health.describe_store(FakeBlobDatabase(usage=usage), store=DbDocumentStore(database=FakeBlobDatabase()))
        assert body["usage"]["objects"] == 10 and body["usage"]["bytes"] == 7300
        assert body["usage"]["byBackend"][1] == {"backend": "s3", "objects": 7, "bytes": 7000}
        assert body["usage"]["integrity"] == {"lastVerifiedAt": verified.isoformat(), "verifiedObjects": 5}

    def test_an_empty_index_has_no_verification(self):
        body = health.describe_store(FakeBlobDatabase(), store=DbDocumentStore(database=FakeBlobDatabase()))
        assert body["usage"] == {
            "objects": 0,
            "bytes": 0,
            "byBackend": [],
            "integrity": {"lastVerifiedAt": None, "verifiedObjects": 0},
        }

    def test_an_unreadable_index_reports_no_usage(self):
        body = health.describe_store(
            FakeBlobDatabase(fail_query=True), store=DbDocumentStore(database=FakeBlobDatabase())
        )
        assert body["usage"] is None


# ───────────────────────────── probe ─────────────────────────────


class TestProbe:
    @pytest.mark.parametrize("backend", ["db", "filesystem", "s3"])
    def test_the_probe_writes_reads_and_deletes(self, backend, tmp_path, request):
        if backend == "db":
            fake = FakeBlobDatabase()
            store = DbDocumentStore(database=fake)
        elif backend == "filesystem":
            store = FilesystemDocumentStore(path=str(tmp_path))
        else:
            store = _s3_store(request.getfixturevalue("s3_client"))
        result = health.probe_store(store)
        assert result["ok"] is True and result["backend"] == backend
        assert [step["name"] for step in result["steps"]] == ["write", "read", "delete"]
        assert all(step["ok"] and step["error"] is None for step in result["steps"])
        if backend == "db":
            assert fake.rows == {}
        elif backend == "s3":
            listing = request.getfixturevalue("s3_client").list_objects_v2(Bucket=BUCKET)
            assert listing.get("KeyCount", 0) == 0

    def test_every_probe_writes_a_new_object(self):
        fake = FakeBlobDatabase()
        store = DbDocumentStore(database=fake)
        seen = []
        original = fake.put_document_store_blob

        def record(**kwargs):
            seen.append(kwargs["sha256"])
            assert kwargs["tenant_id"] == health.PROBE_TENANT
            return original(**kwargs)

        fake.put_document_store_blob = record
        health.probe_store(store)
        health.probe_store(store)
        assert len(set(seen)) == 2

    def test_a_failed_write_skips_the_rest_and_is_redacted(self):
        result = health.probe_store(_s3_store(_FailingClient()))
        assert result["ok"] is False
        write, read, delete = result["steps"]
        assert write["ok"] is False and "InvalidAccessKeyId" in write["error"]
        assert SECRET_KEY not in json.dumps(result) and ACCESS_KEY not in json.dumps(result)
        assert read["skipped"] and delete["skipped"]

    def test_a_bad_read_still_deletes(self):
        fake = FakeBlobDatabase()
        fake.get_document_store_blob = lambda tenant_id, sha256: b"different"
        result = health.probe_store(DbDocumentStore(database=fake))
        names = {step["name"]: step for step in result["steps"]}
        assert names["read"]["ok"] is False and "different bytes" in names["read"]["error"]
        assert names["delete"]["ok"] is True and fake.rows == {}

    def test_an_unexpected_error_shows_only_its_type(self):
        fake = FakeBlobDatabase()

        def boom(**kwargs):
            raise RuntimeError(f"password={SECRET_KEY}")

        fake.put_document_store_blob = boom
        result = health.probe_store(DbDocumentStore(database=fake))
        assert result["steps"][0]["error"] == "The document store failed (RuntimeError)."

    def test_probing_the_active_store_refreshes_health(self):
        store = DbDocumentStore(database=FakeBlobDatabase())
        with patch.object(health, "get_document_store", return_value=store):
            health.probe_store()
            with patch.object(health, "check_reachable", side_effect=AssertionError("cached")):
                assert health.store_health().ok is True


# ───────────────────────────── routes ─────────────────────────────


def _mint_admin_token(key: str = _ADMIN_SECRET) -> str:
    """A far-future super-admin session token (same recipe as the other admin route tests)."""
    payload = {"v": 1, "sub": "admin", "iat": 0, "exp": 9_999_999_999_999}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    digest = hmac.new(key.encode(), encoded.encode(), sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(digest).rstrip(b'=').decode()}"


@pytest.fixture
def active_store():
    """Make an in-memory database store the process-wide one for the route tests."""
    store = DbDocumentStore(prefix="apiome", database=FakeBlobDatabase())
    with patch.object(health, "get_document_store", return_value=store):
        yield store


@pytest.fixture
def client():
    return TestClient(app)


class TestRoutes:
    def test_ops_routes_require_a_platform_admin(self, client, active_store):
        app.dependency_overrides[validate_authentication] = lambda: _AUTH
        try:
            with patch.object(routes, "db") as mdb:
                mdb.is_platform_admin.return_value = False
                assert client.get("/v1/ops/document-store").status_code == 403
                assert client.post("/v1/ops/document-store/test").status_code == 403
        finally:
            app.dependency_overrides.pop(validate_authentication, None)

    def test_ops_routes_serve_a_platform_admin(self, client, active_store):
        app.dependency_overrides[validate_authentication] = lambda: _AUTH
        try:
            with patch.object(routes, "db") as mdb:
                mdb.is_platform_admin.return_value = True
                mdb.document_store_usage.return_value = []
                status = client.get("/v1/ops/document-store")
                probe = client.post("/v1/ops/document-store/test")
        finally:
            app.dependency_overrides.pop(validate_authentication, None)
        assert status.status_code == 200 and status.headers["cache-control"] == "no-store"
        body = status.json()
        assert body["backend"] == "db" and body["prefix"] == "apiome" and body["health"]["ok"] is True
        assert probe.status_code == 200 and probe.json()["ok"] is True

    def test_admin_routes_require_a_super_admin_session(self, client, active_store, monkeypatch):
        monkeypatch.setattr(settings, "admin_session_secret", _ADMIN_SECRET)
        assert client.get("/v1/admin/document-store").status_code == 401
        forged = {"X-Admin-Session": "forged.token"}
        assert client.post("/v1/admin/document-store/test", headers=forged).status_code == 403

    def test_admin_routes_serve_the_console(self, client, active_store, monkeypatch):
        monkeypatch.setattr(settings, "admin_session_secret", _ADMIN_SECRET)
        monkeypatch.setattr(settings, "admin_password", None)
        headers = {"X-Admin-Session": _mint_admin_token()}
        with patch.object(routes, "db") as mdb:
            mdb.document_store_usage.return_value = []
            status = client.get("/v1/admin/document-store", headers=headers)
            probe = client.post("/v1/admin/document-store/test", headers=headers)
        assert status.status_code == 200 and status.json()["usage"]["objects"] == 0
        assert probe.status_code == 200
        assert [step["name"] for step in probe.json()["steps"]] == ["write", "read", "delete"]

    def test_health_reports_the_store_as_a_dependency(self, client, active_store):
        with patch("app.ops_routes.db") as mdb:
            mdb.execute_query.return_value = [{"ok": 1}]
            body = client.get("/health").json()
        assert body["document_store"] == {"status": "ok", "backend": "db", "fallback": False}

    def test_health_stays_200_when_the_store_is_down(self, client):
        broken = DbDocumentStore(database=FakeBlobDatabase(fail_query=True))
        with patch.object(health, "get_document_store", return_value=broken), patch("app.ops_routes.db") as mdb:
            mdb.execute_query.return_value = [{"ok": 1}]
            response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["document_store"]["status"] == "unavailable"
        assert "error" not in response.json()["document_store"]
