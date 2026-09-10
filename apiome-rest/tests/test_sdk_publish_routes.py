"""Package publishing endpoints — SDK-4.1 (#4495).

Authentication is overridden and every collaborator below the route is patched, so these tests
assert the HTTP contract only: which permission each route enforces, how a scope is addressed, how
a refusal maps to a status, that every mutation is audited — and, for the two routes that touch a
credential, that no response body can carry one.
"""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.envelope_crypto import EnvelopeEncryptionError
from app.export_source import ExportSourceError
from app.main import app
from app.permissions import Action, Resource
from app.sdk_publish_pipeline import (
    RUN_STATUS_DRY_RUN,
    RUN_STATUS_PUBLISHED,
    PublishError,
    PublishOutcome,
)
from app.sdk_registry_credentials import RegistryCredentialError, RegistryCredentialOut

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "user_id": "33333333-3333-4333-8333-333333333333",
    "auth_method": "jwt",
}
_TENANT_SLUG = "acme"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_PROJECT_ROW = {"id": _PROJECT, "slug": "widgets"}
_REVISION = "44444444-4444-4444-8444-444444444444"
_RUN = "55555555-5555-4555-8555-555555555555"
_TOKEN = "npm_supersecrettokenvalue"

_PROJECT_CREDS = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-registry-credentials"
_TENANT_CREDS = f"/v1/tenants/{_TENANT_SLUG}/governance/sdk-registry-credentials"
_PUBLISH = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-publish"
_RUNS = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-publish-runs"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request; permission enforcement is asserted per test."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _project_lookup():
    """Patch the project resolver's two accessors to answer for ``_PROJECT``."""
    return patch(
        "app.sdk_publish_routes.db.get_project_by_id", return_value=dict(_PROJECT_ROW)
    )


def _credential(**fields: Any) -> RegistryCredentialOut:
    """A stored credential's metadata."""
    values: Dict[str, Any] = {
        "ecosystem": "npm",
        "scope": "tenant",
        "registry_url": "https://registry.npmjs.org",
        "token_prefix": "npm_",
        "token_length": len(_TOKEN),
        "token_fingerprint": "sha256:0123456789abcdef",
        "key_version": 1,
        "readable": True,
    }
    values.update(fields)
    return RegistryCredentialOut(**values)


def _outcome(**fields: Any) -> PublishOutcome:
    """A pipeline outcome to return from a patched pipeline."""
    values: Dict[str, Any] = {
        "run_id": _RUN,
        "status": RUN_STATUS_DRY_RUN,
        "dry_run": True,
        "ecosystem": "npm",
        "package_name": "@acme/widgets-sdk",
        "package_version": "1.4.3",
        "release_series": "1.4",
        "regen_counter": 3,
        "version_line": "1.4.2",
        "registry_url": "https://registry.npmjs.org",
        "credential_scope": "tenant",
        "artifact_filename": "acme-widgets-sdk-1.4.3.tgz",
        "artifact_sha256": "a" * 64,
        "artifact_bytes": 2048,
        "operation_count": 1,
    }
    values.update(fields)
    return PublishOutcome(**values)


class _Source:
    """A stand-in for the loaded export source."""

    api = object()
    version_record_id = _REVISION
    version_label = "1.4.2"
    source_text = "{}"
    source_format = "openapi-3.1"


def _publishable():
    """Patch the source loader and the revision lookup so a publish can proceed."""
    return (
        patch("app.sdk_publish_routes.load_export_source", return_value=_Source()),
        patch(
            "app.sdk_publish_routes.db.get_version_by_id",
            return_value={"id": _REVISION, "published": True},
        ),
    )


# ============================================================================
# Credentials — listing
# ============================================================================
def test_listing_tenant_credentials_requires_projects_view():
    with patch("app.sdk_publish_routes.enforce_permission") as guard, patch(
        "app.sdk_publish_routes.list_credentials", return_value=[]
    ), patch("app.sdk_publish_routes.credential_encryption_configured", return_value=True):
        response = client.get(_TENANT_CREDS)
    assert response.status_code == 200
    guard.assert_called_once()
    assert guard.call_args.args[2:] == (Resource.PROJECTS, Action.VIEW)
    body = response.json()
    assert body["scope"] == "tenant"
    assert body["ecosystems"] == ["npm", "pypi"]
    assert body["encryptionConfigured"] is True


def test_listing_project_credentials_shows_both_scopes():
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_publish_routes.list_credentials",
        return_value=[_credential(), _credential(scope="project", project_id=_PROJECT)],
    ), patch("app.sdk_publish_routes.credential_encryption_configured", return_value=True):
        response = client.get(_PROJECT_CREDS)
    assert response.status_code == 200
    assert [row["scope"] for row in response.json()["credentials"]] == ["tenant", "project"]


def test_a_credential_response_never_carries_a_token():
    """There is no reveal route, and the listing projection has no field that could hold one."""
    with patch("app.sdk_publish_routes.enforce_permission"), patch(
        "app.sdk_publish_routes.list_credentials", return_value=[_credential()]
    ), patch("app.sdk_publish_routes.credential_encryption_configured", return_value=True):
        response = client.get(_TENANT_CREDS)
    assert _TOKEN not in response.text
    assert "token" not in json.dumps(response.json()["credentials"][0]).replace(
        "tokenPrefix", ""
    ).replace("tokenLength", "").replace("tokenFingerprint", "")


def test_listing_a_project_that_does_not_exist_is_404():
    with patch("app.sdk_publish_routes.enforce_permission"), patch(
        "app.sdk_publish_routes.db.get_project_by_id", return_value=None
    ), patch("app.sdk_publish_routes.db.get_project_by_slug", return_value=None):
        response = client.get(_PROJECT_CREDS)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "project-not-found"


# ============================================================================
# Credentials — storing
# ============================================================================
def test_storing_a_tenant_credential_requires_projects_edit_and_is_audited():
    with patch("app.sdk_publish_routes.enforce_permission") as guard, patch(
        "app.sdk_publish_routes.save_credential", return_value=_credential()
    ) as save, patch("app.sdk_publish_routes.db.write_access_audit") as audit:
        response = client.put(f"{_TENANT_CREDS}/npm", json={"token": _TOKEN})
    assert response.status_code == 200
    assert guard.call_args.args[2:] == (Resource.PROJECTS, Action.EDIT)
    assert save.call_args.kwargs["project_id"] is None
    detail = audit.call_args.kwargs["detail"]
    assert audit.call_args.kwargs["action"] == "governance.sdk_registry_credential.update"
    # The audit row records the fingerprint, never the token.
    assert detail["tokenFingerprint"] == "sha256:0123456789abcdef"
    assert _TOKEN not in json.dumps(detail)


def test_storing_a_project_credential_names_the_project():
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_publish_routes.save_credential",
        return_value=_credential(scope="project", project_id=_PROJECT),
    ) as save, patch("app.sdk_publish_routes.db.write_access_audit"):
        response = client.put(
            f"{_PROJECT_CREDS}/npm",
            json={"token": _TOKEN, "registryUrl": "https://npm.acme.dev/"},
        )
    assert response.status_code == 200
    assert save.call_args.kwargs["project_id"] == _PROJECT
    assert save.call_args.kwargs["registry_url"] == "https://npm.acme.dev/"


def test_an_invalid_token_is_a_422_listing_every_problem():
    with patch("app.sdk_publish_routes.enforce_permission"), patch(
        "app.sdk_publish_routes.save_credential",
        side_effect=RegistryCredentialError("token is required", "registryUrl must be https"),
    ):
        response = client.put(f"{_TENANT_CREDS}/npm", json={"token": "x" * 9})
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "sdk-registry-credential-invalid"
    assert len(detail["errors"]) == 2


def test_an_unconfigured_deployment_answers_503_naming_the_variable():
    with patch("app.sdk_publish_routes.enforce_permission"), patch(
        "app.sdk_publish_routes.save_credential",
        side_effect=EnvelopeEncryptionError("encryption is not configured"),
    ):
        response = client.put(f"{_TENANT_CREDS}/npm", json={"token": _TOKEN})
    assert response.status_code == 503
    assert "APIOME_SDK_REGISTRY_CREDENTIAL_ENCRYPTION_KEYS" in response.json()["detail"]["message"]


def test_a_body_naming_an_unknown_field_is_rejected():
    """``extra="forbid"``: a mis-spelled ``registry_url`` must not silently store a default."""
    with patch("app.sdk_publish_routes.enforce_permission"):
        response = client.put(
            f"{_TENANT_CREDS}/npm", json={"token": _TOKEN, "registry": "https://x.dev"}
        )
    assert response.status_code == 422


# ============================================================================
# Credentials — clearing
# ============================================================================
def test_clearing_a_credential_is_audited_only_when_one_was_stored():
    with patch("app.sdk_publish_routes.enforce_permission"), patch(
        "app.sdk_publish_routes.delete_credential", return_value=True
    ), patch("app.sdk_publish_routes.db.write_access_audit") as audit:
        assert client.delete(f"{_TENANT_CREDS}/npm").json() == {"cleared": True}
    assert audit.call_args.kwargs["action"] == "governance.sdk_registry_credential.clear"

    with patch("app.sdk_publish_routes.enforce_permission"), patch(
        "app.sdk_publish_routes.delete_credential", return_value=False
    ), patch("app.sdk_publish_routes.db.write_access_audit") as audit:
        assert client.delete(f"{_TENANT_CREDS}/npm").json() == {"cleared": False}
    audit.assert_not_called()


def test_clearing_an_unknown_ecosystem_is_422():
    with patch("app.sdk_publish_routes.enforce_permission"), patch(
        "app.sdk_publish_routes.delete_credential",
        side_effect=RegistryCredentialError("ecosystem must be one of npm, pypi"),
    ):
        response = client.delete(f"{_TENANT_CREDS}/gomod")
    assert response.status_code == 422


# ============================================================================
# Publishing
# ============================================================================
def test_publishing_requires_versions_publish():
    source, revision = _publishable()
    with patch("app.sdk_publish_routes.enforce_permission") as guard, _project_lookup(), \
        source, revision, patch(
            "app.sdk_publish_routes.publish", return_value=_outcome()
        ), patch("app.sdk_publish_routes.db.write_access_audit"):
        response = client.post(_PUBLISH, json={"ecosystem": "npm"})
    assert response.status_code == 200
    assert guard.call_args.args[2:] == (Resource.VERSIONS, Action.PUBLISH)


def test_a_publish_defaults_to_a_dry_run():
    """Uploading to a public registry is irreversible, so it is never the default."""
    source, revision = _publishable()
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), source, \
        revision, patch(
            "app.sdk_publish_routes.publish", return_value=_outcome()
        ) as run, patch("app.sdk_publish_routes.db.write_access_audit"):
        client.post(_PUBLISH, json={"ecosystem": "npm"})
    assert run.call_args.kwargs["dry_run"] is True


def test_publishing_for_real_is_the_deliberate_choice():
    source, revision = _publishable()
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), source, \
        revision, patch(
            "app.sdk_publish_routes.publish",
            return_value=_outcome(status=RUN_STATUS_PUBLISHED, dry_run=False),
        ) as run, patch("app.sdk_publish_routes.db.write_access_audit") as audit:
        response = client.post(_PUBLISH, json={"ecosystem": "npm", "dryRun": False})
    assert run.call_args.kwargs["dry_run"] is False
    body = response.json()
    assert body["status"] == "published"
    assert body["packageVersion"] == "1.4.3"
    assert body["releaseSeries"] == "1.4"
    assert body["regenCounter"] == 3
    assert audit.call_args.kwargs["action"] == "sdk.package_publish"
    assert audit.call_args.kwargs["detail"]["packageName"] == "@acme/widgets-sdk"


def test_an_unpublished_revision_cannot_be_released():
    source, _ = _publishable()
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), source, patch(
        "app.sdk_publish_routes.db.get_version_by_id",
        return_value={"id": _REVISION, "published": False},
    ):
        response = client.post(_PUBLISH, json={"ecosystem": "npm"})
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "sdk-publish-not-published"


def test_an_unresolvable_version_keeps_the_source_loaders_status():
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_publish_routes.load_export_source",
        side_effect=ExportSourceError("Version '9.9' was not found.", status_code=404),
    ):
        response = client.post(_PUBLISH, json={"ecosystem": "npm", "version": "9.9"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "sdk-publish-source-unavailable"


@pytest.mark.parametrize(
    "code, status",
    [
        ("sdk-publish-ecosystem-unsupported", 400),
        ("sdk-publish-credential-missing", 422),
        ("sdk-publish-version-unavailable", 409),
        ("sdk-publish-encryption-unconfigured", 503),
    ],
)
def test_a_pipeline_refusal_keeps_its_code_and_status(code, status):
    source, revision = _publishable()
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), source, \
        revision, patch(
            "app.sdk_publish_routes.publish",
            side_effect=PublishError(code, "nope", status_code=status, detail={"ecosystem": "npm"}),
        ):
        response = client.post(_PUBLISH, json={"ecosystem": "npm"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["ecosystem"] == "npm"


def test_a_forbidden_caller_never_reaches_the_pipeline():
    with patch(
        "app.sdk_publish_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="denied"),
    ), patch("app.sdk_publish_routes.publish") as run:
        assert client.post(_PUBLISH, json={"ecosystem": "npm"}).status_code == 403
    run.assert_not_called()


# ============================================================================
# History
# ============================================================================
def test_listing_runs_requires_versions_view_and_pages():
    row = {
        "id": _RUN,
        "status": RUN_STATUS_PUBLISHED,
        "dry_run": False,
        "ecosystem": "npm",
        "package_name": "@acme/widgets-sdk",
        "package_version": "1.4.3",
        "release_series": "1.4",
        "regen_counter": 3,
        "project_id": _PROJECT,
    }
    with patch("app.sdk_publish_routes.enforce_permission") as guard, _project_lookup(), patch(
        "app.sdk_publish_routes.db.list_sdk_publish_runs", return_value=[row]
    ) as listed, patch("app.sdk_publish_routes.db.count_sdk_publish_runs", return_value=1):
        response = client.get(f"{_RUNS}?ecosystem=npm&limit=10&offset=5")
    assert response.status_code == 200
    assert guard.call_args.args[2:] == (Resource.VERSIONS, Action.VIEW)
    assert listed.call_args.kwargs == {"ecosystem": "npm", "limit": 10, "offset": 5}
    body = response.json()
    assert body["total"] == 1
    assert body["runs"][0]["packageVersion"] == "1.4.3"


def test_reading_a_run_belonging_to_another_project_is_404():
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_publish_routes.db.get_sdk_publish_run",
        return_value={"id": _RUN, "project_id": "99999999-9999-4999-8999-999999999999"},
    ):
        response = client.get(f"{_RUNS}/{_RUN}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "sdk-publish-run-not-found"


def test_reading_a_run_returns_its_log():
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_publish_routes.db.get_sdk_publish_run",
        return_value={
            "id": _RUN,
            "project_id": _PROJECT,
            "status": RUN_STATUS_PUBLISHED,
            "dry_run": False,
            "ecosystem": "npm",
            "package_name": "@acme/widgets-sdk",
            "package_version": "1.4.3",
            "release_series": "1.4",
            "regen_counter": 3,
            "log": [{"step": "upload", "message": "Published @acme/widgets-sdk@1.4.3."}],
        },
    ):
        response = client.get(f"{_RUNS}/{_RUN}")
    assert response.status_code == 200
    assert response.json()["log"][0]["step"] == "upload"


def test_the_history_page_size_is_bounded():
    with patch("app.sdk_publish_routes.enforce_permission"), _project_lookup():
        assert client.get(f"{_RUNS}?limit=5000").status_code == 422
