"""Export object-storage delivery: the rules and the routes — MFX-38.3 (#4330).

The pure half (:mod:`app.export_object_storage_delivery`): credential and request validation, the partitioned
layout, key-safe segments, the deterministic manifest and its content address, and redaction. Then the routes
(:mod:`app.export_object_storage_delivery_routes`): the write-only vault (sealed on arrival, described without a
secret, 409 / 503 / 400 refusals, audits without secrets), and the delivery (permissions, tenant scoping, which
jobs can be delivered, where the files come from, the run and its history). The upload is
``test_export_object_storage_delivery_pipeline.py``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from psycopg2 import errors as pg_errors

from app.auth import validate_authentication
from app.config import settings
from app.emitter import EmitResult, EmittedFile
from app.export_git_delivery import BundleFile, DeliverySubject
from app.export_object_storage_delivery import (
    ExportObjectStorageRequestError,
    ObjectStorageDeliveryRequest,
    StorageCredentialCreate,
    manifest_document,
    manifest_keys,
    normalize_credential,
    normalize_request,
    object_prefix,
    partition_segment,
    plan_objects,
    redact,
)
from app.main import app
from app.mcp_credential_crypto import unseal_credential_payload
from app.permissions import Action, Resource
from app.ssrf_guard import SSRFError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ARTIFACT = "22222222-2222-4222-8222-222222222222"
_CREDENTIAL = "66666666-6666-4666-8666-666666666666"
_RUN = "44444444-4444-4444-8444-444444444444"
_JOB = "job-0001"
_KEY_ID = "AKIAEXAMPLEKEY12WXYZ"
_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
_AUTH = {"tenant_id": _TENANT, "user_id": "u1", "auth_method": "jwt", "user_email": "ada@example.com"}
_CREDENTIALS = "/v1/export/acme/storage-credentials"
_DELIVER = f"/v1/export/acme/jobs/{_JOB}/deliveries/object-storage"


def _subject(**fields: Any) -> DeliverySubject:
    values: Dict[str, Any] = dict(
        tenant_slug="acme", job_id=_JOB, artifact_id=_ARTIFACT, artifact_slug="orders", artifact_name="Orders API",
        version_record_id="r1", version_label="1.4.0", target="openapi-3.1", targets=(), snapshot_hash="sha256:abc",
        fidelity={"tier": "lossy"}, report_url=None,
    )
    values.update(fields)
    return DeliverySubject(**values)


def _create(**fields: Any) -> StorageCredentialCreate:
    values: Dict[str, Any] = {"name": "lake", "accessKeyId": _KEY_ID, "secretAccessKey": _SECRET}
    values.update(fields)
    return StorageCredentialCreate(**values)


# ===========================================================================
# The credential
# ===========================================================================


def test_a_credential_is_normalised_and_only_the_secret_half_is_sealed() -> None:
    credential = normalize_credential(_create(name=" lake ", endpointUrl="https://minio.example.com/",
                                              region="eu-west-1", forcePathStyle=True, sessionToken="tok-123"))
    assert (credential.name, credential.endpoint_url, credential.region, credential.force_path_style) == (
        "lake", "https://minio.example.com", "eu-west-1", True)
    assert credential.access_key_hint == "WXYZ"
    assert credential.secret_payload == {"accessKeyId": _KEY_ID, "secretAccessKey": _SECRET, "sessionToken": "tok-123"}
    assert normalize_credential(_create()).endpoint_url is None


def test_secrets_are_not_shown_in_the_model_repr() -> None:
    assert _SECRET not in repr(_create()) and _KEY_ID not in repr(_create())


@pytest.mark.parametrize(("fields", "needle"), [
    ({"name": ""}, "name"),
    ({"accessKeyId": "a b"}, "accessKeyId"),
    ({"secretAccessKey": " padded "}, "secretAccessKey"),
    ({"region": "EU West"}, "region"),
    ({"endpointUrl": "file:///etc"}, "scheme"),
    ({"endpointUrl": "https://u:p@minio.example.com"}, "credentials"),
    ({"endpointUrl": "https://minio.example.com/?x=1"}, "query"),
])
def test_a_bad_credential_names_the_field_without_echoing_a_secret(fields: Dict[str, Any], needle: str) -> None:
    with pytest.raises(ExportObjectStorageRequestError) as caught:
        normalize_credential(_create(**fields))
    assert any(needle in error for error in caught.value.errors)
    assert _SECRET not in str(caught.value)


# ===========================================================================
# The request and the layout
# ===========================================================================


def test_a_request_is_normalised_with_the_default_partitioning() -> None:
    request = normalize_request(ObjectStorageDeliveryRequest(credentialId=_CREDENTIAL, bucket="data-lake",
                                                             prefix="/exports//apis/"))
    assert (request.bucket, request.prefix, request.partitioning) == ("data-lake", "exports/apis",
                                                                      ("artifact", "version", "target"))


@pytest.mark.parametrize(("fields", "needle"), [
    ({"bucket": "Data_Lake"}, "bucket"),
    ({"bucket": "ab"}, "bucket"),
    ({"bucket": "192.168.1.1"}, "bucket"),
    ({"bucket": "a..b"}, "bucket"),
    ({"prefix": "exports/../secrets"}, "'..'"),
    ({"prefix": "a\\b"}, "backslash"),
    ({"prefix": "x" * 513}, "longer than"),
    ({"partitioning": ["artifact", "artifact"]}, "twice"),
    ({"credentialId": " "}, "credentialId"),
])
def test_a_bad_request_names_every_problem(fields: Dict[str, Any], needle: str) -> None:
    values = {"credentialId": _CREDENTIAL, "bucket": "data-lake", **fields}
    with pytest.raises(ExportObjectStorageRequestError) as caught:
        normalize_request(ObjectStorageDeliveryRequest(**values))
    assert any(needle in error for error in caught.value.errors)


def test_an_unknown_partition_is_refused() -> None:
    with pytest.raises(ValueError):
        ObjectStorageDeliveryRequest(credentialId=_CREDENTIAL, bucket="data-lake", partitioning=["tenant"])


@pytest.mark.parametrize(("raw", "segment"), [
    ("orders", "orders"), ("1.4.0", "1.4.0"), ("v1 / beta", "v1-beta"), ("..", "x"), ("", "x"), ("a/../b", "a-..-b"),
])
def test_partition_segments_are_key_safe(raw: str, segment: str) -> None:
    assert partition_segment(raw, "x") == segment


def test_the_layout_falls_back_when_coordinates_are_missing() -> None:
    subject = _subject(artifact_slug=None, version_label=None, version_record_id=None, target="multi")
    assert object_prefix("lake", ("artifact", "version", "target"), subject) == f"lake/{_ARTIFACT}/unversioned/multi"


def test_the_manifest_is_deterministic_and_content_addressed() -> None:
    objects = plan_objects("p", [BundleFile("b.yaml", "b"), BundleFile("a.json", "{}")], {"a.json": "application/x"})
    assert [o.key for o in objects] == ["p/a.json", "p/b.yaml"] and objects[0].content_type == "application/x"
    manifest = manifest_document(_subject(), "p", objects)
    assert manifest == manifest_document(_subject(job_id="other-job"), "p", objects)
    addressed, latest, digest = manifest_keys("p", manifest)
    assert digest == hashlib.sha256(manifest).hexdigest()
    assert (addressed, latest) == (f"p/manifests/{digest}.json", "p/manifest.json")
    assert manifest_keys("", manifest)[1] == "manifest.json"
    assert json.loads(manifest)["objects"][1] == {"key": "p/b.yaml", "sizeBytes": 1,
                                                  "sha256": hashlib.sha256(b"b").hexdigest(),
                                                  "contentType": "application/yaml; charset=utf-8"}


def test_redaction_replaces_every_secret_longest_first() -> None:
    assert redact(f"key {_KEY_ID} secret {_SECRET}", [_KEY_ID, _SECRET, None, "ab"]) == (
        "key [redacted] secret [redacted]")


# ===========================================================================
# The vault routes
# ===========================================================================


@pytest.fixture(autouse=True)
def _auth(monkeypatch):
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys",
                        json.dumps({"1": base64.b64encode(os.urandom(32)).decode()}))
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _credential_row(**fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(id=_CREDENTIAL, tenant_id=_TENANT, name="lake", provider="s3", endpoint_url=None,
                                  region="us-east-1", force_path_style=False, access_key_hint="WXYZ", key_version=1)
    values.update(fields)
    return values


def _tenant():
    return patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT})


def test_storing_a_credential_seals_it_and_answers_without_a_secret() -> None:
    with patch("app.export_object_storage_delivery_routes.enforce_permission") as guard, _tenant(), \
            patch("app.export_object_storage_delivery_routes.validate_url") as ssrf, \
            patch("app.export_object_storage_delivery_routes.db.insert_export_storage_credential",
                  return_value=_credential_row(endpoint_url="https://minio.example.com")) as insert, \
            patch("app.export_object_storage_delivery_routes.write_audit") as audit:
        response = client.post(_CREDENTIALS, json={"name": "lake", "accessKeyId": _KEY_ID, "secretAccessKey": _SECRET,
                                                   "endpointUrl": "https://minio.example.com"})
    assert response.status_code == 201, response.text
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.EDIT)]
    ssrf.assert_called_once_with("https://minio.example.com")
    body = response.json()
    assert (body["accessKeyHint"], body["endpointUrl"]) == ("WXYZ", "https://minio.example.com")
    assert _SECRET not in response.text and _KEY_ID not in response.text
    kwargs = insert.call_args.kwargs
    assert _SECRET.encode() not in kwargs["encrypted_payload"]
    assert unseal_credential_payload(kwargs["encrypted_payload"], kwargs["key_version"])["secretAccessKey"] == _SECRET
    assert _SECRET not in json.dumps(audit.call_args.kwargs["detail"])
    assert _KEY_ID not in json.dumps(audit.call_args.kwargs["detail"])


def test_a_refused_endpoint_is_400_and_nothing_is_stored() -> None:
    with patch("app.export_object_storage_delivery_routes.enforce_permission"), _tenant(), \
            patch("app.export_object_storage_delivery_routes.validate_url", side_effect=SSRFError("private")), \
            patch("app.export_object_storage_delivery_routes.db.insert_export_storage_credential") as insert:
        response = client.post(_CREDENTIALS, json={"name": "lake", "accessKeyId": _KEY_ID, "secretAccessKey": _SECRET,
                                                   "endpointUrl": "http://minio.internal"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export-object-storage-endpoint-refused"
    assert not insert.called


def test_a_taken_name_is_409_and_no_encryption_key_503(monkeypatch) -> None:
    body = {"name": "lake", "accessKeyId": _KEY_ID, "secretAccessKey": _SECRET}
    with patch("app.export_object_storage_delivery_routes.enforce_permission"), _tenant(), \
            patch("app.export_object_storage_delivery_routes.db.insert_export_storage_credential",
                  side_effect=pg_errors.UniqueViolation("dup")):
        taken = client.post(_CREDENTIALS, json=body)
    assert taken.status_code == 409
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", None)
    with patch("app.export_object_storage_delivery_routes.enforce_permission"), _tenant(), \
            patch("app.export_object_storage_delivery_routes.db.insert_export_storage_credential") as insert:
        unsealed = client.post(_CREDENTIALS, json=body)
    assert unsealed.status_code == 503 and not insert.called
    assert _SECRET not in taken.text + unsealed.text


def test_listing_and_deleting_credentials() -> None:
    with patch("app.export_object_storage_delivery_routes.enforce_permission") as guard, _tenant(), \
            patch("app.export_object_storage_delivery_routes.db.list_export_storage_credentials",
                  return_value=[_credential_row()]):
        listed = client.get(_CREDENTIALS)
    assert listed.status_code == 200 and listed.json()["credentials"][0]["name"] == "lake"
    assert "encrypted" not in listed.text
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    with patch("app.export_object_storage_delivery_routes.enforce_permission"), _tenant(), \
            patch("app.export_object_storage_delivery_routes.write_audit"), \
            patch("app.export_object_storage_delivery_routes.db.delete_export_storage_credential",
                  side_effect=[True, False]):
        assert client.delete(f"{_CREDENTIALS}/{_CREDENTIAL}").status_code == 204
        assert client.delete(f"{_CREDENTIALS}/{_CREDENTIAL}").status_code == 404


def test_another_tenant_s_slug_is_404_for_the_vault() -> None:
    with patch("app.export_object_storage_delivery_routes.enforce_permission"), \
            patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": "other"}):
        assert client.get(_CREDENTIALS).status_code == 404


# ===========================================================================
# The delivery routes
# ===========================================================================


def _result(**fields: Any) -> SimpleNamespace:
    values: Dict[str, Any] = dict(
        artifact=_ARTIFACT, version_record_id="r1", version_label="1.4.0", target="openapi-3.1", dry_run=False,
        snapshot_hash="sha256:abc", targets=None,
        files=[SimpleNamespace(path="openapi.yaml", media_type="application/yaml", size_bytes=15)],
        fidelity=SimpleNamespace(model_dump=lambda mode: {"summary": {"tier": "lossy", "preserved_percent": 87}}),
    )
    values.update(fields)
    return SimpleNamespace(**values)


def _status(state: str = "completed", result: Any = "default") -> SimpleNamespace:
    return SimpleNamespace(state=state, result=_result() if result == "default" else result)


def _run(**fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(
        id=_RUN, status="delivered", job_id=_JOB, credential_id=_CREDENTIAL, endpoint_url=None, bucket="data-lake",
        key_prefix="exports/orders/1.4.0/openapi-3.1", partitioning=["artifact", "version", "target"],
        objects=[{"key": "exports/orders/1.4.0/openapi-3.1/openapi.yaml", "sizeBytes": 15, "sha256": "ab" * 32,
                  "contentType": "application/yaml"}],
        manifest_key="exports/orders/1.4.0/openapi-3.1/manifests/" + "cd" * 32 + ".json", manifest_sha256="cd" * 32,
        fidelity={"tier": "lossy"}, error_code=None, error_message=None,
    )
    values.update(fields)
    return values


class _Patches:
    """Every collaborator of the delivery route, with sensible defaults."""

    def __init__(self, *, status: Any = None, emitted: Any = "default") -> None:
        emit = EmitResult(files=[EmittedFile(path="openapi.yaml", content="openapi: 3.1.0\n")])
        self.patches = [
            patch("app.export_object_storage_delivery_routes.enforce_permission"),
            _tenant(),
            patch("app.export_object_storage_delivery_routes.get_export_job_status",
                  new=AsyncMock(return_value=status or _status())),
            patch("app.export_object_storage_delivery_routes.get_export_job_emit_result",
                  return_value=emit if emitted == "default" else emitted),
            patch("app.export_object_storage_delivery_routes.resolve_export_download"),
            patch("app.export_git_delivery_routes.db.get_project_by_id",
                  return_value={"id": _ARTIFACT, "slug": "orders", "name": "Orders API"}),
            patch("app.export_object_storage_delivery_routes.deliver_to_object_storage", return_value=_run()),
            patch("app.export_object_storage_delivery_routes.write_audit"),
        ]
        self.mocks: Dict[str, Any] = {}

    def __enter__(self) -> "_Patches":
        names = ["guard", "tenant", "status", "emitted", "download", "project", "deliver", "audit"]
        for name, item in zip(names, self.patches):
            self.mocks[name] = item.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        for item in reversed(self.patches):
            item.__exit__(*exc)


def _body(**fields: Any) -> Dict[str, Any]:
    return {"credentialId": _CREDENTIAL, "bucket": "data-lake", "prefix": "exports", **fields}


def test_delivering_requires_versions_publish_and_returns_the_run() -> None:
    with _Patches() as p:
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 200, response.text
    assert [call.args[2:] for call in p.mocks["guard"].call_args_list] == [(Resource.VERSIONS, Action.PUBLISH)]
    body = response.json()
    assert (body["status"], body["keyPrefix"], body["manifestSha256"]) == (
        "delivered", "exports/orders/1.4.0/openapi-3.1", "cd" * 32)
    assert body["objects"][0]["sizeBytes"] == 15
    kwargs = p.mocks["deliver"].call_args.kwargs
    assert kwargs["tenant_id"] == _TENANT and kwargs["request"].prefix == "exports"
    assert [f.path for f in kwargs["files"]] == ["openapi.yaml"]
    assert kwargs["media_types"] == {"openapi.yaml": "application/yaml"}
    assert (kwargs["subject"].artifact_slug, kwargs["subject"].fidelity["tier"]) == ("orders", "lossy")
    audit = p.mocks["audit"].call_args.kwargs
    assert audit["action"] == "export.object_storage_delivery" and audit["detail"]["objectCount"] == 1


def test_a_forbidden_caller_is_refused_before_anything_runs() -> None:
    with _Patches() as p:
        p.mocks["guard"].side_effect = HTTPException(status_code=403, detail="forbidden")
        assert client.post(_DELIVER, json=_body()).status_code == 403
    assert not p.mocks["deliver"].called


def test_an_invalid_request_is_400_with_every_problem() -> None:
    with _Patches() as p:
        response = client.post(_DELIVER, json=_body(bucket="Bad_Bucket", prefix="../x"))
    assert response.status_code == 400 and len(response.json()["detail"]["errors"]) == 2
    assert not p.mocks["deliver"].called


@pytest.mark.parametrize(("status", "code"), [
    (_status(state="running", result=None), "export-object-storage-delivery-job-not-completed"),
    (_status(result=_result(dry_run=True)), "export-object-storage-delivery-dry-run"),
])
def test_a_job_that_cannot_be_delivered_is_409(status: Any, code: str) -> None:
    with _Patches(status=status) as p:
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    assert not p.mocks["deliver"].called


def test_another_instance_reads_the_stored_artifact_and_an_expired_one_is_410() -> None:
    with _Patches(emitted=None) as p:
        p.mocks["download"].return_value = SimpleNamespace(body="openapi: 3.1.0\n", media_type="application/yaml")
        assert client.post(_DELIVER, json=_body()).status_code == 200
    assert [f.path for f in p.mocks["deliver"].call_args.kwargs["files"]] == ["openapi.yaml"]
    with _Patches(emitted=None) as p:
        p.mocks["download"].side_effect = HTTPException(status_code=410, detail="expired")
        assert client.post(_DELIVER, json=_body()).status_code == 410
    assert not p.mocks["deliver"].called


def test_a_failed_delivery_is_200_with_its_code() -> None:
    with _Patches() as p:
        p.mocks["deliver"].return_value = _run(
            status="failed", error_code="export-object-storage-delivery-bucket-missing", objects=[], manifest_key=None,
            manifest_sha256=None)
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 200
    assert response.json()["errorCode"] == "export-object-storage-delivery-bucket-missing"


def test_listing_a_job_s_deliveries_needs_projects_view() -> None:
    with patch("app.export_object_storage_delivery_routes.enforce_permission") as guard, _tenant(), \
            patch("app.export_object_storage_delivery_routes.db.list_export_object_storage_delivery_runs",
                  return_value=[_run()]) as listing:
        response = client.get(_DELIVER)
    assert response.status_code == 200 and response.json()["runs"][0]["runId"] == _RUN
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    listing.assert_called_once_with(_TENANT, _JOB)
