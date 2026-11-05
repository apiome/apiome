"""The export object-storage delivery pipeline — MFX-38.3 (#4330).

:func:`app.export_object_storage_delivery_pipeline.deliver_to_object_storage` against a moto S3 bucket and an
in-memory run table, with the credential sealed in the real vault envelope: the bundle and the content-addressed
manifest land under the configured prefix, the run records every object, and every failure — missing or
unreadable credential, refused endpoint, unknown bucket, rejected key, unreachable endpoint — is a ``failed``
run whose message (and the log) never carries a secret.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any, Dict, List, Optional

import boto3
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from moto import mock_aws

from app import export_object_storage_delivery_pipeline as pipeline
from app.config import settings
from app.export_git_delivery import BundleFile, DeliverySubject
from app.export_object_storage_delivery import NormalizedDeliveryRequest
from app.mcp_credential_crypto import seal_credential_payload

_TENANT = "11111111-1111-4111-8111-111111111111"
_CREDENTIAL = "66666666-6666-4666-8666-666666666666"
_RUN = "44444444-4444-4444-8444-444444444444"
_KEY_ID = "AKIAEXAMPLEKEY12WXYZ"
_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
_TOKEN = "session-token-of-some-length"
_BUCKET = "data-lake"


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys",
                        json.dumps({"1": base64.b64encode(os.urandom(32)).decode()}))


class FakeDatabase:
    """The credential lookup and the three run-table calls, in memory."""

    def __init__(self, credential: Optional[Dict[str, Any]] = None) -> None:
        self.credential = credential
        self.runs: Dict[str, Dict[str, Any]] = {}

    def get_export_storage_credential(self, tenant_id: str, credential_id: str) -> Optional[Dict[str, Any]]:
        if self.credential and tenant_id == _TENANT and credential_id == self.credential["id"]:
            return dict(self.credential)
        return None

    def insert_export_object_storage_delivery_run(self, **fields: Any) -> Dict[str, Any]:
        row = {"id": _RUN, "status": "in_progress", "objects": [], "manifest_key": None, "manifest_sha256": None,
               "error_code": None, "error_message": None, **fields}
        row["job_id"] = fields["job_id"]
        self.runs[_RUN] = row
        return dict(row)

    def finish_export_object_storage_delivery_run(self, run_id: str, tenant_id: str, **outcome: Any) -> Dict[str, Any]:
        assert tenant_id == _TENANT
        self.runs[run_id].update({k: v for k, v in outcome.items() if v is not None or k.startswith("error")})
        return dict(self.runs[run_id])


def _credential(endpoint: Optional[str] = None, payload: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    sealed, version = seal_credential_payload(payload or {"accessKeyId": _KEY_ID, "secretAccessKey": _SECRET,
                                                          "sessionToken": _TOKEN})
    return {"id": _CREDENTIAL, "name": "lake", "endpoint_url": endpoint, "region": "us-east-1",
            "force_path_style": False, "access_key_hint": _KEY_ID[-4:], "encrypted_payload": sealed,
            "key_version": version}


def _subject(**fields: Any) -> DeliverySubject:
    values: Dict[str, Any] = dict(
        tenant_slug="acme", job_id="job-1", artifact_id="a1", artifact_slug="orders", artifact_name="Orders API",
        version_record_id="r1", version_label="1.4.0", target="openapi-3.1", targets=(), snapshot_hash="sha256:abc",
        fidelity={"tier": "lossy", "preservedPercent": 87}, report_url=None,
    )
    values.update(fields)
    return DeliverySubject(**values)


def _request(**fields: Any) -> NormalizedDeliveryRequest:
    values: Dict[str, Any] = dict(credential_id=_CREDENTIAL, bucket=_BUCKET, prefix="exports/apis",
                                  partitioning=("artifact", "version", "target"))
    values.update(fields)
    return NormalizedDeliveryRequest(**values)


_FILES = [BundleFile("openapi.yaml", "openapi: 3.1.0\n"), BundleFile("schemas/pet.json", '{"type":"object"}')]


def _deliver(database: FakeDatabase, **fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(tenant_id=_TENANT, actor_id=None, subject=_subject(), request=_request(),
                                  files=_FILES, database=database)
    values.update(fields)
    return pipeline.deliver_to_object_storage(**values)


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1", aws_access_key_id=_KEY_ID,
                              aws_secret_access_key=_SECRET)
        client.create_bucket(Bucket=_BUCKET)
        yield client


def _keys_in(client: Any) -> List[str]:
    return sorted(item["Key"] for item in client.list_objects_v2(Bucket=_BUCKET).get("Contents", []))


# ===========================================================================
# Delivered
# ===========================================================================


def test_the_bundle_and_manifest_land_under_the_partitioned_prefix(s3) -> None:
    database = FakeDatabase(_credential())
    row = _deliver(database)
    assert row["status"] == "delivered", row
    base = "exports/apis/orders/1.4.0/openapi-3.1"
    manifest_sha = row["manifest_sha256"]
    assert _keys_in(s3) == sorted([f"{base}/openapi.yaml", f"{base}/schemas/pet.json", f"{base}/manifest.json",
                                   f"{base}/manifests/{manifest_sha}.json"])
    assert row["key_prefix"] == base and row["manifest_key"] == f"{base}/manifests/{manifest_sha}.json"
    head = s3.head_object(Bucket=_BUCKET, Key=f"{base}/openapi.yaml")
    assert head["Metadata"]["sha256"] == hashlib.sha256(b"openapi: 3.1.0\n").hexdigest()
    assert head["ContentType"].startswith("application/yaml")
    assert [o["key"] for o in row["objects"]] == [f"{base}/openapi.yaml", f"{base}/schemas/pet.json"]


def test_the_manifest_is_content_addressed_and_lists_every_object(s3) -> None:
    row = _deliver(FakeDatabase(_credential()))
    addressed = s3.get_object(Bucket=_BUCKET, Key=row["manifest_key"])["Body"].read()
    latest = s3.get_object(Bucket=_BUCKET, Key=f"{row['key_prefix']}/manifest.json")["Body"].read()
    assert addressed == latest and hashlib.sha256(addressed).hexdigest() == row["manifest_sha256"]
    document = json.loads(addressed)
    assert document["schemaVersion"] == "export.object-storage-delivery.v1"
    assert (document["artifact"], document["version"], document["target"]) == ("orders", "1.4.0", "openapi-3.1")
    assert document["fidelity"]["tier"] == "lossy"
    for entry in document["objects"]:
        body = s3.get_object(Bucket=_BUCKET, Key=entry["key"])["Body"].read()
        assert hashlib.sha256(body).hexdigest() == entry["sha256"] and len(body) == entry["sizeBytes"]


def test_the_same_export_writes_the_same_manifest_address(s3) -> None:
    first = _deliver(FakeDatabase(_credential()))
    second = _deliver(FakeDatabase(_credential()), subject=_subject(job_id="job-2"))
    assert first["manifest_key"] == second["manifest_key"]


@pytest.mark.parametrize(("prefix", "partitioning", "base"), [
    ("", (), ""),
    ("", ("target",), "openapi-3.1"),
    ("lake", ("version", "artifact"), "lake/1.4.0/orders"),
])
def test_partitioning_is_configurable(s3, prefix: str, partitioning: Any, base: str) -> None:
    row = _deliver(FakeDatabase(_credential()), request=_request(prefix=prefix, partitioning=partitioning))
    assert row["status"] == "delivered" and row["key_prefix"] == base
    assert (f"{base}/openapi.yaml" if base else "openapi.yaml") in _keys_in(s3)


# ===========================================================================
# Failed, and never leaking a secret
# ===========================================================================


def test_an_unknown_credential_fails_the_run() -> None:
    row = _deliver(FakeDatabase(None))
    assert (row["status"], row["error_code"]) == ("failed", pipeline.ERROR_CREDENTIAL_MISSING)


def test_a_credential_that_cannot_be_opened_fails_the_run(monkeypatch) -> None:
    credential = _credential()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys",
                        json.dumps({"1": base64.b64encode(os.urandom(32)).decode()}))
    row = _deliver(FakeDatabase(credential))
    assert (row["status"], row["error_code"]) == ("failed", pipeline.ERROR_CREDENTIAL_UNAVAILABLE)


def test_an_internal_endpoint_is_refused_before_any_upload() -> None:
    calls: List[Any] = []
    row = _deliver(FakeDatabase(_credential(endpoint="http://127.0.0.1:9000")),
                   client_factory=lambda *a: calls.append(a))
    assert (row["status"], row["error_code"]) == ("failed", pipeline.ERROR_ENDPOINT_REFUSED)
    assert calls == []


def test_an_unknown_bucket_fails_the_run(s3) -> None:
    row = _deliver(FakeDatabase(_credential()), request=_request(bucket="no-such-bucket"))
    assert (row["status"], row["error_code"]) == ("failed", pipeline.ERROR_BUCKET_MISSING)
    assert row["objects"] == []


class _FailingClient:
    """An S3 client whose second upload fails with ``error``."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.keys: List[str] = []

    def put_object(self, **kwargs: Any) -> None:
        if self.keys:
            raise self.error
        self.keys.append(kwargs["Key"])


def _client_error(code: str, message: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "PutObject")


@pytest.mark.parametrize(("error", "code"), [
    (_client_error("InvalidAccessKeyId", f"The key {_KEY_ID} with secret {_SECRET} is unknown"),
     pipeline.ERROR_CREDENTIAL_REJECTED),
    (_client_error("SignatureDoesNotMatch", f"signed with {_SECRET}"), pipeline.ERROR_CREDENTIAL_REJECTED),
    (_client_error("AccessDenied", f"token {_TOKEN} may not write"), pipeline.ERROR_PERMISSION_DENIED),
    (_client_error("InternalError", f"boom {_SECRET}"), pipeline.ERROR_UPLOAD_FAILED),
    (EndpointConnectionError(endpoint_url=f"https://x/{_SECRET}"), pipeline.ERROR_ENDPOINT_UNREACHABLE),
])
def test_provider_failures_map_to_codes_and_are_redacted(caplog, error: Exception, code: str) -> None:
    client = _FailingClient(error)
    with caplog.at_level(logging.DEBUG):
        row = _deliver(FakeDatabase(_credential()), client_factory=lambda *_a: client)
    assert (row["status"], row["error_code"]) == ("failed", code)
    assert len(row["objects"]) == 1, "the object written before the failure is listed"
    for secret in (_KEY_ID, _SECRET, _TOKEN):
        assert secret not in row["error_message"]
        assert secret not in caplog.text
    assert "[redacted]" in row["error_message"] or code == pipeline.ERROR_ENDPOINT_UNREACHABLE


def test_an_unexpected_fault_is_a_failed_run_without_its_message(caplog) -> None:
    def boom(*_a: Any) -> Any:
        raise RuntimeError(f"leaky {_SECRET}")

    with caplog.at_level(logging.DEBUG):
        row = _deliver(FakeDatabase(_credential()), client_factory=boom)
    assert (row["status"], row["error_code"]) == ("failed", pipeline.ERROR_INTERNAL)
    assert _SECRET not in row["error_message"] and _SECRET not in caplog.text


def test_an_empty_bundle_fails_the_run(s3) -> None:
    row = _deliver(FakeDatabase(_credential()), files=[])
    assert (row["status"], row["error_code"]) == ("failed", pipeline.ERROR_EMPTY_BUNDLE)


def test_the_client_uses_the_credential_s_endpoint_region_and_addressing() -> None:
    client = pipeline.build_s3_client(
        {"endpoint_url": "https://minio.example.com", "region": "eu-west-1", "force_path_style": True},
        {"accessKeyId": _KEY_ID, "secretAccessKey": _SECRET},
    )
    assert client.meta.endpoint_url == "https://minio.example.com"
    assert client.meta.region_name == "eu-west-1"
    assert client.meta.config.s3["addressing_style"] == "path"
