"""Export webhook delivery: the rules and the routes — MFX-38.2 (#4329).

The pure half (:mod:`app.export_webhook_delivery`): request validation (the SSRF shape rules and the secret),
the body (manifest, fidelity, the bundle inline or as a fetch link), the signature, the fetch link, and the URL
as the API shows it. Then the routes (:mod:`app.export_webhook_delivery_routes`): permissions, tenant scoping,
the SSRF refusal, which jobs can be delivered, inline vs fetch, auditing without the URL's token, the history
listing, and the signed fetch route. The pipeline is ``test_export_webhook_delivery_pipeline.py``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.config import settings
from app.export_git_delivery import DeliverySubject
from app.export_job_engine import ExportDownloadArtifact
from app.export_webhook_delivery import (
    PAYLOAD_SCHEMA_VERSION,
    BundleArtifact,
    ExportWebhookDeliveryRequestError,
    WebhookDeliveryRequest,
    build_payload,
    display_url,
    fetch_signature,
    fetch_url,
    normalize_request,
    sign_body,
    stable_body,
    verify_fetch_signature,
)
from app.main import app
from app.permissions import Action, Resource
from app.ssrf_guard import SSRFError

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ARTIFACT = "22222222-2222-4222-8222-222222222222"
_REVISION = "33333333-3333-4333-8333-333333333333"
_RUN = "44444444-4444-4444-8444-444444444444"
_JOB = "job-0001"
_SECRET = "a-shared-secret-of-length"
_AUTH = {"tenant_id": _TENANT, "user_id": "u1", "auth_method": "jwt", "user_email": "ada@example.com"}
_DELIVER = f"/v1/export/acme/jobs/{_JOB}/deliveries/webhook"
_KEY = b"k" * 32


def _subject(**fields: Any) -> DeliverySubject:
    values: Dict[str, Any] = dict(
        tenant_slug="acme", job_id=_JOB, artifact_id=_ARTIFACT, artifact_slug="orders", artifact_name="Orders API",
        version_record_id=_REVISION, version_label="1.4.0", target="openapi-3.1", targets=(),
        snapshot_hash="sha256:abc", fidelity={"tier": "lossy", "preservedPercent": 87},
        report_url="https://ui.example/ade/dashboard/export/studio?artifact=a&step=review",
    )
    values.update(fields)
    return DeliverySubject(**values)


# ===========================================================================
# The request
# ===========================================================================


def test_a_request_is_normalised() -> None:
    request = normalize_request(WebhookDeliveryRequest(url=" https://hooks.example/in ", secret=_SECRET))
    assert (request.url, request.secret, request.artifact) == ("https://hooks.example/in", _SECRET, "auto")


@pytest.mark.parametrize(("fields", "needle"), [
    ({"url": "", "secret": _SECRET}, "url is required"),
    ({"url": "ftp://hooks.example/in", "secret": _SECRET}, "scheme"),
    ({"url": "file:///etc/passwd", "secret": _SECRET}, "scheme"),
    ({"url": "https://user:pw@hooks.example/in", "secret": _SECRET}, "credentials"),
    ({"url": "https://hooks.example/" + "a" * 2100, "secret": _SECRET}, "longer than"),
    ({"url": "https://hooks.example/in", "secret": "short"}, "secret must be"),
    ({"url": "https://hooks.example/in", "secret": "x" * 513}, "secret must be"),
])
def test_a_bad_request_names_every_problem(fields: Dict[str, Any], needle: str) -> None:
    with pytest.raises(ExportWebhookDeliveryRequestError) as caught:
        normalize_request(WebhookDeliveryRequest(**fields))
    assert any(needle in error for error in caught.value.errors)


def test_an_unknown_artifact_mode_or_field_is_refused() -> None:
    with pytest.raises(ValueError):
        WebhookDeliveryRequest(url="https://hooks.example/in", secret=_SECRET, artifact="email")
    with pytest.raises(ValueError):
        WebhookDeliveryRequest(url="https://hooks.example/in", secret=_SECRET, headers={"x": "y"})


def test_the_url_is_shown_without_its_query_string() -> None:
    assert display_url("https://hooks.slack.example/services/T/B?token=xyz#f") == "https://hooks.slack.example/services/T/B?…"
    assert display_url("https://hooks.example/in") == "https://hooks.example/in"


# ===========================================================================
# The body and the signature
# ===========================================================================


def _payload(artifact: BundleArtifact, *, inline: bool = True, fetch: Any = None) -> Dict[str, Any]:
    return build_payload(
        delivery_id=_RUN, created_at=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc), subject=_subject(),
        files=[{"path": "openapi.yaml", "sizeBytes": 16}], fidelity_report={"summary": {"tier": "lossy"}},
        download_path=f"/v1/export/acme/jobs/{_JOB}/download", artifact=artifact, inline=inline, fetch=fetch,
    )


def test_a_text_bundle_rides_inline_with_the_manifest_and_fidelity() -> None:
    body = _payload(BundleArtifact("openapi.yaml", "application/yaml", "openapi: 3.1.0\n"))
    assert (body["schemaVersion"], body["event"], body["deliveryId"]) == (PAYLOAD_SCHEMA_VERSION,
                                                                          "export.delivered", _RUN)
    assert body["createdAt"] == "2026-11-04T12:00:00Z"
    assert body["export"]["target"] == "openapi-3.1" and body["export"]["versionLabel"] == "1.4.0"
    assert body["manifest"]["files"] == [{"path": "openapi.yaml", "sizeBytes": 16}]
    assert body["fidelity"]["summary"]["tier"] == "lossy" and body["fidelity"]["report"] is not None
    assert "step=review" in body["fidelity"]["reportUrl"]
    bundle = body["artifact"]
    assert (bundle["delivery"], bundle["encoding"], bundle["content"]) == ("inline", "utf-8", "openapi: 3.1.0\n")
    assert bundle["sha256"] == hashlib.sha256(b"openapi: 3.1.0\n").hexdigest()
    assert bundle["sizeBytes"] == 15


def test_a_zip_bundle_rides_inline_as_base64() -> None:
    zipped = BundleArtifact("wsdl.zip", "application/zip", b"PK\x03\x04data", "sha256:" + "f" * 64)
    bundle = _payload(zipped)["artifact"]
    assert bundle["encoding"] == "base64" and base64.b64decode(bundle["content"]) == b"PK\x03\x04data"
    assert bundle["sha256"] == "f" * 64


def test_a_fetch_bundle_carries_the_link_not_the_content() -> None:
    bundle = _payload(BundleArtifact("big.zip", "application/zip", b"PK..."), inline=False,
                      fetch={"url": "https://api.example/x", "expiresAt": "2026-11-05T12:00:00Z"})["artifact"]
    assert (bundle["delivery"], bundle["url"]) == ("fetch", "https://api.example/x")
    assert "content" not in bundle


def test_the_body_is_stable_and_signed_with_hmac_sha256() -> None:
    payload = _payload(BundleArtifact("openapi.yaml", "application/yaml", "openapi: 3.1.0\n"))
    body = stable_body(payload)
    assert body == stable_body(json.loads(body))
    assert sign_body(_SECRET, body) == "sha256=" + hmac.new(_SECRET.encode(), body, hashlib.sha256).hexdigest()


# ===========================================================================
# The fetch link
# ===========================================================================


def test_a_fetch_link_verifies_and_any_change_breaks_it() -> None:
    url = fetch_url("https://api.example/", _KEY, "acme", _JOB, _RUN, 2_000_000_000)
    parts = urlsplit(url)
    assert parts.path == f"/v1/export/acme/jobs/{_JOB}/deliveries/webhook/{_RUN}/bundle"
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert verify_fetch_signature(_KEY, "acme", _JOB, _RUN, int(query["expires"]), query["signature"])
    assert not verify_fetch_signature(_KEY, "acme", "job-other", _RUN, 2_000_000_000, query["signature"])
    assert not verify_fetch_signature(_KEY, "acme", _JOB, _RUN, 2_000_000_001, query["signature"])
    assert not verify_fetch_signature(b"other-key", "acme", _JOB, _RUN, 2_000_000_000, query["signature"])


def test_the_default_fetch_key_is_derived_not_the_jwt_secret() -> None:
    with patch.object(settings, "export_fetch_url_signing_key", None):
        key = settings.effective_export_fetch_url_signing_key
    assert key != settings.effective_jwt_secret.encode() and len(key) == 32
    with patch.object(settings, "export_fetch_url_signing_key", "configured"):
        assert settings.effective_export_fetch_url_signing_key == b"configured"


# ===========================================================================
# The routes
# ===========================================================================


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.clear()


def _result(**fields: Any) -> SimpleNamespace:
    values: Dict[str, Any] = dict(
        artifact=_ARTIFACT, version_record_id=_REVISION, version_label="1.4.0", target="openapi-3.1", dry_run=False,
        snapshot_hash="sha256:abc", targets=None, fidelity_rollup=None,
        download_path=f"/v1/export/acme/jobs/{_JOB}/download", download_expires_at=None,
        files=[SimpleNamespace(path="openapi.yaml", size_bytes=15, media_type="application/yaml", subject=None)],
        fidelity=SimpleNamespace(model_dump=lambda mode: {"summary": {"tier": "lossy", "preserved_percent": 87}}),
    )
    values.update(fields)
    return SimpleNamespace(**values)


def _status(state: str = "completed", result: Any = "default") -> SimpleNamespace:
    return SimpleNamespace(state=state, result=_result() if result == "default" else result)


def _row(**fields: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = dict(
        id=_RUN, status="delivered", job_id=_JOB, target_url="https://hooks.example/in?token=secret-token",
        artifact_delivery="inline", payload_sha256="ab" * 32, attempt_count=1, max_attempts=4,
        attempts=[{"attempt": 1, "at": "2026-11-04T12:00:00Z", "httpStatus": 200, "latencyMs": 12, "error": None,
                   "responsePreview": "ok"}],
        next_attempt_at=None, last_http_status=200, fidelity={"tier": "lossy"}, error_code=None, error_message=None,
        started_at=datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc), finished_at=None,
    )
    values.update(fields)
    return values


def _download(body: Any = "openapi: 3.1.0\n") -> ExportDownloadArtifact:
    return ExportDownloadArtifact(filename="openapi.yaml", media_type="application/yaml", body=body,
                                  content_sha256="sha256:" + hashlib.sha256(
                                      body.encode() if isinstance(body, str) else body).hexdigest())


class _Patches:
    """Every collaborator of the delivery route, with sensible defaults."""

    def __init__(self, *, status: Any = None, tenant: Any = "default", download: Any = None) -> None:
        self.patches = [
            patch("app.export_webhook_delivery_routes.enforce_permission"),
            patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug",
                  return_value={"id": _TENANT} if tenant == "default" else tenant),
            patch("app.export_webhook_delivery_routes.validate_url"),
            patch("app.export_webhook_delivery_routes.get_export_job_status",
                  new=AsyncMock(return_value=status or _status())),
            patch("app.export_webhook_delivery_routes.resolve_export_download", return_value=download or _download()),
            patch("app.export_git_delivery_routes.db.get_project_by_id",
                  return_value={"id": _ARTIFACT, "slug": "orders", "name": "Orders API"}),
            patch("app.export_webhook_delivery_routes.start_delivery", return_value=_row()),
            patch("app.export_webhook_delivery_routes.write_audit"),
        ]
        self.mocks: Dict[str, Any] = {}

    def __enter__(self) -> "_Patches":
        names = ["guard", "tenant", "ssrf", "status", "download", "project", "start", "audit"]
        for name, item in zip(names, self.patches):
            self.mocks[name] = item.__enter__()
        return self

    def __exit__(self, *exc: Any) -> None:
        for item in reversed(self.patches):
            item.__exit__(*exc)

    def sent(self) -> Dict[str, Any]:
        """The body the route handed the pipeline, parsed."""
        return json.loads(self.mocks["start"].call_args.kwargs["payload"])


def _body(**fields: Any) -> Dict[str, Any]:
    return {"url": "https://hooks.example/in?token=secret-token", "secret": _SECRET, **fields}


def test_delivering_requires_versions_publish_and_returns_the_run() -> None:
    with _Patches() as p:
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 200, response.text
    assert [call.args[2:] for call in p.mocks["guard"].call_args_list] == [(Resource.VERSIONS, Action.PUBLISH)]
    body = response.json()
    assert (body["runId"], body["status"], body["attemptCount"], body["lastHttpStatus"]) == (_RUN, "delivered", 1, 200)
    assert body["targetUrl"] == "https://hooks.example/in?…"
    assert body["attempts"][0]["httpStatus"] == 200
    p.mocks["ssrf"].assert_called_once_with("https://hooks.example/in?token=secret-token")


def test_the_pipeline_gets_the_signed_body_and_never_the_secret() -> None:
    with _Patches() as p:
        client.post(_DELIVER, json=_body())
    kwargs = p.mocks["start"].call_args.kwargs
    assert _SECRET not in json.dumps({k: v for k, v in kwargs.items() if k != "payload"}, default=str)
    assert _SECRET.encode() not in kwargs["payload"]
    assert kwargs["signature"] == sign_body(_SECRET, kwargs["payload"])
    assert kwargs["payload_sha256"] == hashlib.sha256(kwargs["payload"]).hexdigest()
    assert (kwargs["tenant_id"], kwargs["job_id"], kwargs["artifact_delivery"]) == (_TENANT, _JOB, "inline")
    sent = p.sent()
    assert sent["deliveryId"] == kwargs["run_id"]
    assert sent["artifact"]["content"] == "openapi: 3.1.0\n"
    assert sent["manifest"]["files"] == [{"path": "openapi.yaml", "sizeBytes": 15, "mediaType": "application/yaml"}]
    assert sent["export"]["artifactSlug"] == "orders" and sent["fidelity"]["summary"]["tier"] == "lossy"


def test_the_audit_names_the_host_but_not_the_url_token() -> None:
    with _Patches() as p:
        client.post(_DELIVER, json=_body())
    audit = p.mocks["audit"].call_args.kwargs
    assert audit["action"] == "export.webhook_delivery"
    assert audit["detail"]["receiverHost"] == "hooks.example"
    assert "secret-token" not in json.dumps(audit["detail"]) and _SECRET not in json.dumps(audit["detail"])


def test_a_forbidden_caller_is_refused_before_anything_runs() -> None:
    with _Patches() as p:
        p.mocks["guard"].side_effect = HTTPException(status_code=403, detail="forbidden")
        assert client.post(_DELIVER, json=_body()).status_code == 403
    assert not p.mocks["start"].called


def test_another_tenant_s_slug_is_404() -> None:
    with _Patches(tenant={"id": "99999999-9999-4999-8999-999999999999"}) as p:
        assert client.post(_DELIVER, json=_body()).status_code == 404
    assert not p.mocks["start"].called


def test_an_invalid_request_is_400_with_every_problem() -> None:
    with _Patches() as p:
        response = client.post(_DELIVER, json={"url": "ftp://x", "secret": "short"})
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "export-webhook-delivery-request-invalid" and len(detail["errors"]) == 2
    assert not p.mocks["start"].called


def test_a_destination_the_ssrf_guard_refuses_is_400() -> None:
    with _Patches() as p:
        p.mocks["ssrf"].side_effect = SSRFError("host 'internal' resolves to non-public address 10.0.0.5")
        response = client.post(_DELIVER, json=_body(url="https://internal.example/in"))
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "export-webhook-delivery-destination-refused"
    assert not p.mocks["start"].called


@pytest.mark.parametrize(("status", "code"), [
    (_status(state="running", result=None), "export-webhook-delivery-job-not-completed"),
    (_status(result=_result(dry_run=True)), "export-webhook-delivery-dry-run"),
])
def test_a_job_that_cannot_be_delivered_is_409(status: Any, code: str) -> None:
    with _Patches(status=status) as p:
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 409 and response.json()["detail"]["code"] == code
    assert not p.mocks["start"].called


def test_an_expired_artifact_is_410() -> None:
    with _Patches() as p:
        p.mocks["download"].side_effect = HTTPException(status_code=410, detail="expired")
        assert client.post(_DELIVER, json=_body()).status_code == 410
    assert not p.mocks["start"].called


def test_a_large_bundle_travels_as_a_signed_fetch_link_capped_by_artifact_expiry() -> None:
    artifact_expiry = int(time.time()) + 3600
    with _Patches(status=_status(result=_result(download_expires_at=artifact_expiry * 1000)),
                  download=_download(b"PK" + b"x" * 64)) as p, \
            patch.object(settings, "export_webhook_inline_max_bytes", 10), \
            patch.object(settings, "api_public_url", "https://api.example"):
        assert client.post(_DELIVER, json=_body()).status_code == 200
    assert p.mocks["start"].call_args.kwargs["artifact_delivery"] == "fetch"
    bundle = p.sent()["artifact"]
    assert bundle["delivery"] == "fetch" and "content" not in bundle
    parts = urlsplit(bundle["url"])
    assert parts.netloc == "api.example" and parts.path.endswith(f"/deliveries/webhook/{p.sent()['deliveryId']}/bundle")
    query = {key: values[0] for key, values in parse_qs(parts.query).items()}
    assert int(query["expires"]) == artifact_expiry
    assert verify_fetch_signature(settings.effective_export_fetch_url_signing_key, "acme", _JOB,
                                  p.sent()["deliveryId"], int(query["expires"]), query["signature"])


def test_artifact_fetch_always_sends_the_link() -> None:
    with _Patches() as p, patch.object(settings, "api_public_url", "https://api.example"):
        assert client.post(_DELIVER, json=_body(artifact="fetch")).status_code == 200
    assert p.sent()["artifact"]["delivery"] == "fetch"


def test_a_fetch_link_without_a_public_address_is_409() -> None:
    with _Patches() as p, patch.object(settings, "api_public_url", ""), \
            patch.object(settings, "repository_webhook_base_url", ""):
        response = client.post(_DELIVER, json=_body(artifact="fetch"))
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "export-webhook-delivery-fetch-url-unavailable"
    assert not p.mocks["start"].called


def test_a_multi_target_job_carries_every_target_s_report() -> None:
    def _target(name: str, percent: int) -> SimpleNamespace:
        return SimpleNamespace(target=name, fidelity=SimpleNamespace(
            model_dump=lambda mode: {"summary": {"tier": "lossy", "preserved_percent": percent}}))

    result = _result(target=None, fidelity=None, targets=[_target("openapi-3.1", 100), _target("proto3", 60)])
    with _Patches(status=_status(result=result)) as p:
        assert client.post(_DELIVER, json=_body()).status_code == 200
    sent = p.sent()
    assert sent["export"]["target"] == "multi" and sent["export"]["targets"] == ["openapi-3.1", "proto3"]
    assert [t["target"] for t in sent["fidelity"]["report"]["targets"]] == ["openapi-3.1", "proto3"]
    assert sent["fidelity"]["summary"]["preservedPercent"] == 60


def test_a_failed_delivery_is_200_with_its_code() -> None:
    with _Patches() as p:
        p.mocks["start"].return_value = _row(status="failed", error_code="export-webhook-delivery-rejected",
                                             error_message="HTTP 401", last_http_status=401)
        response = client.post(_DELIVER, json=_body())
    assert response.status_code == 200
    assert (response.json()["status"], response.json()["errorCode"]) == ("failed", "export-webhook-delivery-rejected")


def test_listing_a_job_s_deliveries_needs_projects_view() -> None:
    rows = [_row(), _row(id="55555555-5555-4555-8555-555555555555", status="retrying",
                         next_attempt_at=datetime(2026, 11, 4, 12, 1, tzinfo=timezone.utc))]
    with patch("app.export_webhook_delivery_routes.enforce_permission") as guard, \
            patch("app.export_git_delivery_routes.db.get_tenant_row_by_slug", return_value={"id": _TENANT}), \
            patch("app.export_webhook_delivery_routes.db.list_export_webhook_delivery_runs",
                  return_value=rows) as listing:
        response = client.get(_DELIVER)
    assert response.status_code == 200
    assert [call.args[2:] for call in guard.call_args_list] == [(Resource.PROJECTS, Action.VIEW)]
    listing.assert_called_once_with(_TENANT, _JOB)
    runs = response.json()["runs"]
    assert [r["status"] for r in runs] == ["delivered", "retrying"] and runs[1]["nextAttemptAt"]
    assert all("secret-token" not in r["targetUrl"] for r in runs)


# ===========================================================================
# The fetch route
# ===========================================================================


def _fetch(expires: int, *, signature: Any = None, job: str = _JOB) -> Any:
    key = settings.effective_export_fetch_url_signing_key
    sig = signature or fetch_signature(key, "acme", _JOB, _RUN, expires)
    return client.get(f"/v1/export/acme/jobs/{job}/deliveries/webhook/{_RUN}/bundle",
                      params={"expires": expires, "signature": sig})


def test_a_signed_link_streams_the_bundle_without_credentials() -> None:
    app.dependency_overrides.clear()
    with patch("app.export_webhook_delivery_routes.resolve_export_download", return_value=_download()) as resolve:
        response = _fetch(int(time.time()) + 600)
    assert response.status_code == 200, response.text
    assert response.content == b"openapi: 3.1.0\n"
    assert response.headers["X-Content-SHA256"] == hashlib.sha256(b"openapi: 3.1.0\n").hexdigest()
    assert "openapi.yaml" in response.headers["Content-Disposition"]
    resolve.assert_called_once_with("acme", _JOB)


def test_a_tampered_link_is_403_and_an_expired_one_410() -> None:
    with patch("app.export_webhook_delivery_routes.resolve_export_download", return_value=_download()) as resolve:
        assert _fetch(int(time.time()) + 600, signature="0" * 64).status_code == 403
        assert _fetch(int(time.time()) + 600, job="job-other").status_code == 403
        expired = _fetch(int(time.time()) - 1)
    assert expired.status_code == 410
    assert expired.json()["detail"]["code"] == "export-webhook-delivery-fetch-link-expired"
    assert not resolve.called
