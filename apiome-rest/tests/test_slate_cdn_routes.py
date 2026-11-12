"""CDN / edge provider REST surface — Slate 10.2 (private-suite#120).

Route-level tests over :mod:`app.slate_cdn_routes` and the CDN half of
``POST .../cache/purge`` (:mod:`app.slate_cache_routes`), following the ``test_slate_cache_routes``
precedent: a module-level ``TestClient``, a mock auth dict, collaborators patched where used.

The claims that matter most:

* **No response ever carries the credential**, on read or on write.
* **A deployment that cannot encrypt refuses to store** — 409 ``cdn-vault-not-configured`` — rather
  than keeping a credential in the clear.
* **A manual purge is ``dispatched`` only when the CDN accepted it.**
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.slate_auth import validate_slate_authentication
from app.slate_cdn_dispatch import CdnPurgeOutcome

client = TestClient(app)

TENANT = "11111111-1111-1111-1111-111111111111"
SITE = "22222222-2222-2222-2222-222222222222"
ENV = "33333333-3333-3333-3333-333333333333"
RELEASE = "55555555-5555-5555-5555-555555555555"
ZONE = "0123456789abcdef0123456789abcdef"
SECRET = "tok_super_secret_value"

_MOCK_JWT: Dict[str, Any] = {
    "tenant_id": TENANT,
    "user_id": "user-1",
    "email": "ken@example.com",
    "auth_type": "jwt",
}

PROVIDER_ROW: Dict[str, Any] = {
    "id": "p-1",
    "provider": "cloudflare",
    "target": ZONE,
    "auth_header_name": None,
    "credential_ciphertext": b"sealed-bytes",
    "credential_key_version": 1,
    "purge_on_deploy": True,
    "updated_at": "2026-11-11T10:00:00+00:00",
    "updated_by_actor_name": "ken@example.com",
}

DISPATCH_ROW: Dict[str, Any] = {
    "id": "d-1",
    "trigger": "deploy",
    "provider": "cloudflare",
    "mode": "urls",
    "url_count": 3,
    "sample_urls": ["https://docs.example.com/a"],
    "status": "succeeded",
    "http_status": 200,
    "error_code": None,
    "error_message": None,
    "release_id": RELEASE,
    "cache_purge_id": None,
    "actor_name": "ken@example.com",
    "dispatched_at": "2026-11-11T10:05:00+00:00",
}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_slate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_slate_authentication, None)


@pytest.fixture(autouse=True)
def _permissions():
    with patch("app.slate_cdn_routes.enforce_permission") as enforce:
        yield enforce


@pytest.fixture(autouse=True)
def _lane():
    with patch(
        "app.slate_cdn_routes.get_environment_scope",
        return_value={"id": ENV, "site_id": SITE, "tenant_id": TENANT},
    ), patch("app.slate_cdn_routes.unseal_cdn_credential", return_value=SECRET):
        yield


def url(suffix: str = "") -> str:
    return f"/v1/slate/environments/{ENV}/cdn{suffix}"


class TestRead:
    def test_an_unconfigured_lane_says_so(self) -> None:
        with patch("app.slate_cdn_routes.get_provider", return_value=None), \
             patch("app.slate_cdn_routes.list_dispatches", return_value=[]), \
             patch("app.slate_cdn_routes.cdn_vault_configured", return_value=True):
            body = client.get(url()).json()
        assert body["configured"] is False
        assert body["edgeAttached"] is False
        assert body["provider"] is None
        assert body["vaultConfigured"] is True

    def test_a_configured_lane_never_returns_the_credential(self) -> None:
        with patch("app.slate_cdn_routes.get_provider", return_value=dict(PROVIDER_ROW)), \
             patch("app.slate_cdn_routes.list_dispatches", return_value=[dict(DISPATCH_ROW)]), \
             patch("app.slate_cdn_routes.cdn_vault_configured", return_value=True):
            response = client.get(url())
        assert response.status_code == 200
        assert SECRET not in response.text
        assert "sealed" not in response.text
        body = response.json()
        assert body["provider"]["credentialSet"] is True
        assert body["provider"]["credentialReadable"] is True
        assert body["provider"]["target"] == ZONE
        assert body["lastDispatch"]["sentence"] == "3 URLs purged at Cloudflare."

    def test_reading_requires_view(self, _permissions) -> None:
        with patch("app.slate_cdn_routes.get_provider", return_value=None), \
             patch("app.slate_cdn_routes.list_dispatches", return_value=[]):
            client.get(url())
        assert _permissions.mock_calls[0].args[3] == "view"

    def test_another_tenants_lane_is_a_404(self) -> None:
        with patch("app.slate_cdn_routes.get_environment_scope", return_value=None):
            response = client.get(url())
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "environment_not_found"


def save_body(**overrides) -> Dict[str, Any]:
    body = {"provider": "cloudflare", "target": ZONE, "credential": SECRET, "purgeOnDeploy": True}
    body.update(overrides)
    return body


class TestSave:
    def test_a_save_seals_the_credential_before_storing_it(self) -> None:
        with patch("app.slate_cdn_routes.get_provider", side_effect=[None, dict(PROVIDER_ROW)]), \
             patch("app.slate_cdn_routes.list_dispatches", return_value=[]), \
             patch("app.slate_cdn_routes.cdn_vault_configured", return_value=True), \
             patch("app.slate_cdn_routes.seal_cdn_credential", return_value=(b"c", 1)) as sealed, \
             patch("app.slate_cdn_routes.save_provider") as saved:
            response = client.post(url(), json=save_body())
        assert response.status_code == 200
        sealed.assert_called_once_with(SECRET)
        kwargs = saved.call_args.kwargs
        assert kwargs["sealed_credential"] == (b"c", 1)
        assert kwargs["site_id"] == SITE
        assert SECRET not in str(kwargs)
        assert SECRET not in response.text
        assert response.json()["configured"] is True

    def test_saving_requires_publish(self, _permissions) -> None:
        with patch("app.slate_cdn_routes.get_provider", return_value=None), \
             patch("app.slate_cdn_routes.cdn_vault_configured", return_value=False):
            client.post(url(), json=save_body())
        assert _permissions.mock_calls[0].args[3] == "publish"

    def test_no_vault_refuses_with_409_and_stores_nothing(self) -> None:
        with patch("app.slate_cdn_routes.get_provider", return_value=None), \
             patch("app.slate_cdn_routes.cdn_vault_configured", return_value=False), \
             patch("app.slate_cdn_routes.save_provider") as saved:
            response = client.post(url(), json=save_body())
        assert response.status_code == 409
        detail = response.json()["detail"]
        assert detail["code"] == "cdn-vault-not-configured"
        assert "APIOME_SLATE_CDN_CREDENTIAL_ENCRYPTION_KEYS" in detail["message"]
        saved.assert_not_called()

    def test_an_invalid_configuration_lists_every_field(self) -> None:
        with patch("app.slate_cdn_routes.get_provider", return_value=None), \
             patch("app.slate_cdn_routes.save_provider") as saved:
            response = client.post(
                url(),
                json=save_body(provider="custom", target="http://x", authHeaderName="Host"),
            )
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert detail["code"] == "cdn-config-invalid"
        assert len(detail["errors"]) == 2
        saved.assert_not_called()

    def test_a_blank_credential_keeps_the_stored_one(self) -> None:
        with patch("app.slate_cdn_routes.get_provider", return_value=dict(PROVIDER_ROW)), \
             patch("app.slate_cdn_routes.list_dispatches", return_value=[]), \
             patch("app.slate_cdn_routes.seal_cdn_credential") as sealed, \
             patch("app.slate_cdn_routes.save_provider") as saved:
            response = client.post(url(), json=save_body(credential="", purgeOnDeploy=False))
        assert response.status_code == 200
        sealed.assert_not_called()
        assert saved.call_args.kwargs["sealed_credential"] is None
        assert saved.call_args.kwargs["purge_on_deploy"] is False

    def test_a_first_save_without_a_credential_is_refused(self) -> None:
        with patch("app.slate_cdn_routes.get_provider", return_value=None):
            response = client.post(url(), json=save_body(credential=None))
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "cdn-credential-required"


class TestDetachAndHistory:
    def test_detaching_removes_the_provider(self) -> None:
        with patch("app.slate_cdn_routes.delete_provider", return_value=True) as deleted:
            response = client.delete(url())
        assert response.status_code == 200
        assert response.json() == {"environmentId": ENV, "detached": True}
        assert deleted.call_args.kwargs["tenant_id"] == TENANT

    def test_detaching_nothing_is_a_404(self) -> None:
        with patch("app.slate_cdn_routes.delete_provider", return_value=False):
            response = client.delete(url())
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "cdn-not-configured"

    def test_history_lists_dispatches_with_sentences(self) -> None:
        failed = {**DISPATCH_ROW, "id": "d-2", "status": "failed", "error_code": "cdn-rate-limited"}
        with patch(
            "app.slate_cdn_routes.list_dispatches", return_value=[failed, dict(DISPATCH_ROW)]
        ):
            body = client.get(url("/dispatches")).json()
        assert [d["id"] for d in body["dispatches"]] == ["d-2", "d-1"]
        assert "rate-limited" in body["dispatches"][0]["sentence"]


# ─── The cache plane's purge, with a CDN attached ─────────────────────────────

CACHE_ENV = {"id": ENV, "site_id": SITE, "tenant_id": TENANT, "active_release_id": RELEASE}
CACHE_POLICY = {
    "id": "policy-1",
    "environment_id": ENV,
    "preset": "standard",
    "policy_version": 3,
    "edge_attached": True,
    "edge_provider": "cloudflare",
}


@pytest.fixture
def attached_lane():
    with patch("app.slate_cache_routes.enforce_permission"), \
         patch("app.slate_cache_routes.get_environment", return_value=dict(CACHE_ENV)), \
         patch("app.slate_cache_routes.ensure_policy", return_value=dict(CACHE_POLICY)), \
         patch("app.slate_cache_routes.routes_for_release", return_value=["/docs/a", "/docs/b"]), \
         patch("app.slate_cache_routes.get_cdn_provider", return_value=dict(PROVIDER_ROW)), \
         patch("app.slate_cache_routes.verified_hosts", return_value=["docs.example.com", "www.example.com"]), \
         patch("app.slate_cache_routes.append_audit") as audit, \
         patch("app.slate_cache_routes.record_purge", return_value={"id": "purge-1"}) as purge, \
         patch("app.slate_cache_routes.record_cdn_dispatch", return_value={"id": "d-9"}) as dispatch:
        yield {"audit": audit, "purge": purge, "dispatch": dispatch}


def purge(body: Dict[str, Any]):
    return client.post(f"/v1/slate/environments/{ENV}/cache/purge", json=body)


class TestManualPurgeDispatch:
    def test_an_accepted_purge_is_dispatched(self, attached_lane) -> None:
        sent = AsyncMock(
            return_value=CdnPurgeOutcome(
                status="succeeded", provider="cloudflare", mode="urls", url_count=4
            )
        )
        with patch("app.slate_cache_routes.send_purge", sent):
            response = purge({"scopeKind": "prefix", "scopeValue": "/docs", "reason": "stale"})
        assert response.status_code == 200
        body = response.json()
        assert body["outcome"] == "dispatched"
        assert body["delivery"]["dispatched"] is True
        assert body["cdnPurge"]["dispatchId"] == "d-9"
        plan = sent.call_args.args[1]
        assert plan.url_count == 4
        assert attached_lane["purge"].call_args.kwargs["outcome"] == "dispatched"
        assert attached_lane["purge"].call_args.kwargs["edge_attached"] is True
        assert attached_lane["dispatch"].call_args.kwargs["cache_purge_id"] == "purge-1"
        assert attached_lane["dispatch"].call_args.kwargs["trigger"] == "manual"

    def test_a_refused_purge_stays_recorded_and_names_the_error(self, attached_lane) -> None:
        sent = AsyncMock(
            return_value=CdnPurgeOutcome(
                status="failed", provider="cloudflare", mode="urls", error_code="cdn-auth-rejected"
            )
        )
        with patch("app.slate_cache_routes.send_purge", sent):
            body = purge({"scopeKind": "prefix", "scopeValue": "/docs", "reason": "x"}).json()
        assert body["outcome"] == "recorded"
        assert body["delivery"]["dispatched"] is False
        assert "nothing was evicted at the CDN" in body["delivery"]["sentence"]
        assert body["cdnPurge"]["errorCode"] == "cdn-auth-rejected"

    def test_a_host_purge_only_purges_that_host(self, attached_lane) -> None:
        sent = AsyncMock(
            return_value=CdnPurgeOutcome(status="succeeded", provider="cloudflare", mode="urls")
        )
        with patch("app.slate_cache_routes.routes_for_host", return_value=["/a"]), \
             patch("app.slate_cache_routes.send_purge", sent):
            purge({"scopeKind": "host", "scopeValue": "www.example.com", "reason": "x"})
        assert sent.call_args.args[1].urls == ("https://www.example.com/a",)

    def test_a_dry_run_sends_nothing(self, attached_lane) -> None:
        sent = AsyncMock()
        with patch("app.slate_cache_routes.send_purge", sent):
            body = purge(
                {"scopeKind": "prefix", "scopeValue": "/docs", "reason": "x", "dryRun": True}
            ).json()
        sent.assert_not_called()
        assert body["outcome"] == "estimated"
        assert "Confirming it sends the purge" in body["delivery"]["sentence"]
        attached_lane["dispatch"].assert_not_called()

    def test_the_policy_never_claims_its_rules_are_enforced(self, attached_lane) -> None:
        with patch("app.slate_cache_routes.list_rules", return_value=[]):
            body = client.get(f"/v1/slate/environments/{ENV}/cache").json()
        assert body["edgeAttached"] is True
        assert body["enforcement"]["enforced"] is False
        assert "dispatched to the attached CDN" in body["enforcement"]["sentence"]
