"""Unit tests for the shared export artifact store driver (IXH-6.1, #5120; COA-5.1, #7077)."""

from __future__ import annotations

from datetime import datetime, timezone

import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.document_store import DbDocumentStore, FilesystemDocumentStore, S3DocumentStore, set_document_store
from app.export_artifact_store import (
    BACKEND_DB,
    BACKEND_OBJECT_STORE,
    DefaultExportArtifactStore,
    ExportArtifactExpired,
    ExportArtifactNotFound,
    ExportArtifactStoreNotConfigured,
    ExportArtifactTooLarge,
    ObjectStoreExportArtifactBackend,
    body_as_bytes,
    content_sha256_hex,
    content_sha256_hex_only,
    digest_header_value,
)


def test_content_sha256_and_digest_headers_round_trip():
    data = b"hello-export"
    digest = content_sha256_hex(data)
    assert digest.startswith("sha256:")
    assert len(content_sha256_hex_only(digest)) == 64
    header = digest_header_value(digest)
    assert header.startswith("sha-256=")


def test_put_and_get_via_db_backend():
    store = DefaultExportArtifactStore()
    body = b'{"openapi":"3.1.0"}'
    record = store.put(
        job_id="job-1",
        tenant_slug="acme",
        body=body,
        media_type="application/json",
        filename="openapi.json",
        expires_at=None,
    )
    assert record.backend == BACKEND_DB
    assert record.content_sha256 == content_sha256_hex(body)
    loaded = store.get("acme", "job-1")
    assert loaded.content == body
    assert loaded.filename == "openapi.json"


def test_get_wrong_tenant_is_not_found():
    store = DefaultExportArtifactStore()
    store.put(
        job_id="job-2",
        tenant_slug="acme",
        body=b"secret",
        media_type="text/plain",
        filename="x.txt",
        expires_at=None,
    )
    with pytest.raises(ExportArtifactNotFound):
        store.get("other", "job-2")


def test_get_expired_raises():
    store = DefaultExportArtifactStore()
    store.put(
        job_id="job-3",
        tenant_slug="acme",
        body=b"stale",
        media_type="text/plain",
        filename="x.txt",
        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ExportArtifactExpired):
        store.get("acme", "job-3")


def test_size_cap_raises_too_large(monkeypatch):
    monkeypatch.setattr(settings, "export_artifact_max_bytes", 10)
    monkeypatch.setattr(settings, "export_artifact_db_max_bytes", 10)
    store = DefaultExportArtifactStore()
    with pytest.raises(ExportArtifactTooLarge) as excinfo:
        store.put(
            job_id="job-4",
            tenant_slug="acme",
            body=b"x" * 20,
            media_type="text/plain",
            filename="x.txt",
            expires_at=None,
        )
    assert excinfo.value.size_bytes == 20
    assert excinfo.value.max_bytes == 10


def test_above_db_max_without_an_object_store_is_a_configuration_error(monkeypatch):
    """APIOME_DOCUMENT_STORE=db has no object store: a large artifact fails clearly (#7077)."""
    monkeypatch.setattr(settings, "export_artifact_max_bytes", 1000)
    monkeypatch.setattr(settings, "export_artifact_db_max_bytes", 10)
    store = DefaultExportArtifactStore(
        object_store_backend=ObjectStoreExportArtifactBackend(DbDocumentStore(database=object()))
    )
    with pytest.raises(ExportArtifactStoreNotConfigured) as excinfo:
        store.put(
            job_id="job-5",
            tenant_slug="acme",
            body=b"x" * 50,
            media_type="text/plain",
            filename="x.txt",
            expires_at=None,
        )
    assert "APIOME_DOCUMENT_STORE" in str(excinfo.value)
    assert excinfo.value.size_bytes == 50


def test_default_document_store_setting_selects_no_object_store(monkeypatch):
    monkeypatch.setattr(settings, "export_artifact_max_bytes", 1000)
    monkeypatch.setattr(settings, "export_artifact_db_max_bytes", 10)
    set_document_store(None)
    with pytest.raises(ExportArtifactStoreNotConfigured):
        DefaultExportArtifactStore().put(
            job_id="job-5b",
            tenant_slug="acme",
            body=b"x" * 50,
            media_type="text/plain",
            filename="x.txt",
            expires_at=None,
        )


@pytest.fixture
def s3_document_store():
    """An S3 document store on an in-process moto bucket."""
    with mock_aws():
        client = boto3.client(
            "s3", region_name="us-east-1", aws_access_key_id="AKIAEXAMPLE", aws_secret_access_key="secret-example"
        )
        client.create_bucket(Bucket="apiome-documents")
        yield S3DocumentStore(bucket="apiome-documents", prefix="apiome", client_factory=lambda: client), client


def _object_store(document_store) -> DefaultExportArtifactStore:
    return DefaultExportArtifactStore(object_store_backend=ObjectStoreExportArtifactBackend(document_store))


def test_export_above_db_max_succeeds_with_s3(monkeypatch, s3_document_store):
    """Acceptance (#7077): an export larger than the DB threshold is stored in the bucket."""
    document_store, client = s3_document_store
    monkeypatch.setattr(settings, "export_artifact_max_bytes", 1000)
    monkeypatch.setattr(settings, "export_artifact_db_max_bytes", 10)
    store = _object_store(document_store)
    body = b'{"openapi":"3.1.0","info":{"title":"Large"}}'
    record = store.put(
        job_id="job-6",
        tenant_slug="acme",
        body=body,
        media_type="application/json",
        filename="openapi.json",
        expires_at=None,
    )
    digest = content_sha256_hex_only(content_sha256_hex(body))
    key = f"apiome/tenants/acme/objects/sha256/{digest[:2]}/{digest}"
    assert record.backend == BACKEND_OBJECT_STORE
    assert record.content is None
    assert record.storage_uri == f"s3://apiome-documents/{key}"
    assert client.get_object(Bucket="apiome-documents", Key=key)["Body"].read() == body

    loaded = store.get("acme", "job-6")
    assert loaded.content == body
    assert loaded.backend == BACKEND_OBJECT_STORE
    assert loaded.content_sha256 == content_sha256_hex(body)
    assert loaded.filename == "openapi.json"


def test_small_export_stays_in_the_db_when_s3_is_configured(monkeypatch, s3_document_store):
    document_store, client = s3_document_store
    monkeypatch.setattr(settings, "export_artifact_db_max_bytes", 10)
    record = _object_store(document_store).put(
        job_id="job-7", tenant_slug="acme", body=b"tiny", media_type="text/plain", filename="x.txt", expires_at=None
    )
    assert record.backend == BACKEND_DB
    assert client.list_objects_v2(Bucket="apiome-documents")["KeyCount"] == 0


def test_object_store_artifact_respects_tenant_scope_and_expiry(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "export_artifact_db_max_bytes", 1)
    store = _object_store(FilesystemDocumentStore(path=str(tmp_path)))
    store.put(
        job_id="job-8", tenant_slug="acme", body=b"private", media_type="text/plain", filename="x", expires_at=None
    )
    with pytest.raises(ExportArtifactNotFound):
        store.get("other", "job-8")
    store.put(
        job_id="job-9",
        tenant_slug="acme",
        body=b"stale bytes",
        media_type="text/plain",
        filename="x",
        expires_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    with pytest.raises(ExportArtifactExpired):
        store.get("acme", "job-9")


def test_object_store_artifact_with_a_missing_or_altered_object_is_gone(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "export_artifact_db_max_bytes", 1)
    document_store = FilesystemDocumentStore(path=str(tmp_path))
    store = _object_store(document_store)
    record = store.put(
        job_id="job-10", tenant_slug="acme", body=b"payload", media_type="text/plain", filename="x", expires_at=None
    )
    digest = content_sha256_hex_only(record.content_sha256)
    target = tmp_path / document_store.key_for("acme", digest)
    target.write_bytes(b"tampered")
    with pytest.raises(ExportArtifactExpired):
        store.get("acme", "job-10")
    assert document_store.delete("acme", digest) is True
    with pytest.raises(ExportArtifactExpired):
        store.get("acme", "job-10")


def test_deleting_an_object_store_artifact_keeps_the_shared_object(monkeypatch, tmp_path):
    """Equal bytes from two jobs share one object, so deleting one job must not remove it."""
    monkeypatch.setattr(settings, "export_artifact_db_max_bytes", 1)
    document_store = FilesystemDocumentStore(path=str(tmp_path))
    store = _object_store(document_store)
    for job_id in ("job-11", "job-12"):
        store.put(
            job_id=job_id, tenant_slug="acme", body=b"shared", media_type="text/plain", filename="x", expires_at=None
        )
    assert store.delete("acme", "job-11") is True
    with pytest.raises(ExportArtifactNotFound):
        store.get("acme", "job-11")
    assert store.get("acme", "job-12").content == b"shared"


def test_body_as_bytes_encodes_str():
    assert body_as_bytes("abc") == b"abc"
    assert body_as_bytes(b"abc") == b"abc"
