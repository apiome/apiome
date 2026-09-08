"""Generation-settings endpoints — SDK-3.4 (#4494).

Authentication is overridden and the store layer is patched, so these tests assert the HTTP
contract only: which permission each route enforces, how the two scopes are addressed, how a
refusal maps to a status, and that every mutation is audited.
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.permissions import Action, Resource
from app.sdk_generation_settings import (
    SETTINGS_SOURCE_DEFAULT,
    SETTINGS_SOURCE_TENANT,
    PatternContext,
    ResolvedBrandingOut,
    SdkGenerationSettings,
    SdkGenerationSettingsOut,
    SdkSettingsError,
    resolve_branding,
    settings_content_fingerprint,
)

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "user_id": "33333333-3333-4333-8333-333333333333",
    "auth_method": "jwt",
}
_TENANT_SLUG = "acme"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_PROJECT_ROW = {"id": _PROJECT, "slug": "petstore"}

_PROJECT_URL = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/sdk-settings"
_TENANT_URL = f"/v1/tenants/{_TENANT_SLUG}/governance/sdk-generation-settings"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request; permission enforcement is asserted per test."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _settings(
    source: str = SETTINGS_SOURCE_DEFAULT, **fields: Any
) -> SdkGenerationSettingsOut:
    """A settings response with the given merged values."""
    merged = SdkGenerationSettings(**fields)
    resolved = resolve_branding(
        merged, PatternContext(tenant=_TENANT_SLUG, project="petstore")
    )
    return SdkGenerationSettingsOut(
        source=source,
        content_fingerprint=settings_content_fingerprint(merged),
        settings=merged,
        resolved=ResolvedBrandingOut(
            package_names=resolved.package_names,
            license_header=resolved.license_header,
            user_agent=resolved.user_agent,
        ),
        scope="project",
    )


def _project_lookup():
    """Patch the project resolver's two accessors to answer for ``_PROJECT``."""
    return patch(
        "app.sdk_generation_settings_routes.db.get_project_by_id",
        return_value=dict(_PROJECT_ROW),
    )


# ===========================================================================
# Project scope
# ===========================================================================


def test_reading_a_project_needs_projects_view() -> None:
    with patch(
        "app.sdk_generation_settings_routes.enforce_permission"
    ) as enforce, _project_lookup(), patch(
        "app.sdk_generation_settings_routes.load_settings", return_value=_settings()
    ):
        resp = client.get(_PROJECT_URL)
    assert resp.status_code == 200
    assert enforce.call_args.args[2:] == (Resource.PROJECTS, Action.VIEW)


def test_a_project_read_resolves_the_slug_into_the_pattern_context() -> None:
    """``{project}`` must substitute the project's slug, not the reference the caller used."""
    with patch("app.sdk_generation_settings_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_generation_settings_routes.load_settings", return_value=_settings()
    ) as load:
        client.get(_PROJECT_URL)
    context = load.call_args.args[2]
    assert context.tenant == _TENANT_SLUG
    assert context.project == "petstore"


def test_an_unknown_project_is_404() -> None:
    with patch("app.sdk_generation_settings_routes.enforce_permission"), patch(
        "app.sdk_generation_settings_routes.db.get_project_by_id", return_value=None
    ), patch(
        "app.sdk_generation_settings_routes.db.get_project_by_slug", return_value=None
    ):
        resp = client.get(_PROJECT_URL)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "project-not-found"


def test_a_project_can_be_addressed_by_slug() -> None:
    with patch("app.sdk_generation_settings_routes.enforce_permission"), patch(
        "app.sdk_generation_settings_routes.db.get_project_by_slug",
        return_value=dict(_PROJECT_ROW),
    ) as by_slug, patch(
        "app.sdk_generation_settings_routes.load_settings", return_value=_settings()
    ):
        resp = client.get(f"/v1/projects/{_TENANT_SLUG}/petstore/sdk-settings")
    assert resp.status_code == 200
    by_slug.assert_called_once_with("petstore", _MOCK_AUTH["tenant_id"])


def test_saving_a_project_needs_projects_edit_and_is_audited() -> None:
    saved = _settings(SETTINGS_SOURCE_TENANT, user_agent="petstore-sdk/2.0")
    with patch(
        "app.sdk_generation_settings_routes.enforce_permission"
    ) as enforce, _project_lookup(), patch(
        "app.sdk_generation_settings_routes.save_settings", return_value=saved
    ) as save, patch(
        "app.sdk_generation_settings_routes.db.write_access_audit"
    ) as audit:
        resp = client.put(
            _PROJECT_URL, json={"settings": {"userAgent": "petstore-sdk/2.0"}}
        )
    assert resp.status_code == 200
    assert enforce.call_args.args[2:] == (Resource.PROJECTS, Action.EDIT)
    assert save.call_args.kwargs["body"] == {"userAgent": "petstore-sdk/2.0"}
    assert save.call_args.kwargs["project_id"] == _PROJECT
    assert audit.call_args.kwargs["action"] == "governance.sdk_generation_settings.update"
    assert audit.call_args.kwargs["detail"]["projectId"] == _PROJECT


def test_an_invalid_body_is_422_with_every_problem() -> None:
    with patch("app.sdk_generation_settings_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_generation_settings_routes.save_settings",
        side_effect=SdkSettingsError(["userAgent: bad", "licenseHeader: bad"]),
    ):
        resp = client.put(_PROJECT_URL, json={"settings": {"userAgent": "x"}})
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "sdk-generation-settings-invalid"
    assert len(detail["errors"]) == 2


def test_an_unknown_request_key_is_refused() -> None:
    """``extra="forbid"``: a typo in the wrapper must not be silently dropped."""
    with patch("app.sdk_generation_settings_routes.enforce_permission"), _project_lookup():
        resp = client.put(_PROJECT_URL, json={"setting": {}})
    assert resp.status_code == 422


def test_deleting_a_project_override_returns_what_is_now_in_force() -> None:
    """Not a bare 204: the caller needs to see what it fell back to."""
    inherited = _settings(SETTINGS_SOURCE_TENANT, user_agent="acme-sdk/1.0")
    with patch("app.sdk_generation_settings_routes.enforce_permission") as enforce, _project_lookup(), patch(
        "app.sdk_generation_settings_routes.clear_settings", return_value=True
    ), patch(
        "app.sdk_generation_settings_routes.load_settings", return_value=inherited
    ), patch(
        "app.sdk_generation_settings_routes.db.write_access_audit"
    ) as audit:
        resp = client.delete(_PROJECT_URL)
    assert resp.status_code == 200
    assert resp.json()["settings"]["userAgent"] == "acme-sdk/1.0"
    assert enforce.call_args.args[2:] == (Resource.PROJECTS, Action.EDIT)
    assert audit.call_args.kwargs["action"] == "governance.sdk_generation_settings.clear"


def test_deleting_nothing_is_not_audited() -> None:
    """An audit row for a no-op would make the ledger unreadable."""
    with patch("app.sdk_generation_settings_routes.enforce_permission"), _project_lookup(), patch(
        "app.sdk_generation_settings_routes.clear_settings", return_value=False
    ), patch(
        "app.sdk_generation_settings_routes.load_settings", return_value=_settings()
    ), patch(
        "app.sdk_generation_settings_routes.db.write_access_audit"
    ) as audit:
        resp = client.delete(_PROJECT_URL)
    assert resp.status_code == 200
    audit.assert_not_called()


# ===========================================================================
# Tenant scope
# ===========================================================================


def test_reading_the_workspace_defaults_needs_projects_view() -> None:
    with patch("app.sdk_generation_settings_routes.enforce_permission") as enforce, patch(
        "app.sdk_generation_settings_routes.load_settings", return_value=_settings()
    ) as load:
        resp = client.get(_TENANT_URL)
    assert resp.status_code == 200
    assert enforce.call_args.args[2:] == (Resource.PROJECTS, Action.VIEW)
    # No project is resolved at tenant scope.
    assert load.call_args.args[1] is None


def test_saving_the_workspace_defaults_is_scoped_to_no_project() -> None:
    with patch("app.sdk_generation_settings_routes.enforce_permission"), patch(
        "app.sdk_generation_settings_routes.save_settings",
        return_value=_settings(SETTINGS_SOURCE_TENANT, user_agent="acme-sdk/1.0"),
    ) as save, patch("app.sdk_generation_settings_routes.db.write_access_audit"):
        resp = client.put(_TENANT_URL, json={"settings": {"userAgent": "acme-sdk/1.0"}})
    assert resp.status_code == 200
    assert save.call_args.kwargs["project_id"] is None


def test_clearing_the_workspace_defaults_does_not_touch_projects() -> None:
    with patch("app.sdk_generation_settings_routes.enforce_permission"), patch(
        "app.sdk_generation_settings_routes.clear_settings", return_value=True
    ) as clear, patch(
        "app.sdk_generation_settings_routes.load_settings", return_value=_settings()
    ), patch("app.sdk_generation_settings_routes.db.write_access_audit"):
        resp = client.delete(_TENANT_URL)
    assert resp.status_code == 200
    assert clear.call_args.kwargs["project_id"] is None


def test_an_empty_put_body_is_accepted_and_clears_nothing() -> None:
    """A body naming no key configures no key — it does not wipe the scope."""
    with patch("app.sdk_generation_settings_routes.enforce_permission"), patch(
        "app.sdk_generation_settings_routes.save_settings", return_value=_settings()
    ) as save, patch("app.sdk_generation_settings_routes.db.write_access_audit"):
        resp = client.put(_TENANT_URL, json={})
    assert resp.status_code == 200
    assert save.call_args.kwargs["body"] == {}


# ===========================================================================
# Cross-cutting
# ===========================================================================


def test_a_credential_without_a_tenant_is_refused() -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"auth_method": "jwt"}
    with patch("app.sdk_generation_settings_routes.enforce_permission"):
        resp = client.get(_TENANT_URL)
    assert resp.status_code == 403


def test_a_denied_permission_is_403() -> None:
    with patch(
        "app.sdk_generation_settings_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="denied"),
    ):
        assert client.get(_TENANT_URL).status_code == 403
        assert client.put(_TENANT_URL, json={}).status_code == 403
        assert client.delete(_TENANT_URL).status_code == 403


def test_an_audit_failure_never_fails_the_save() -> None:
    with patch("app.sdk_generation_settings_routes.enforce_permission"), patch(
        "app.sdk_generation_settings_routes.save_settings", return_value=_settings()
    ), patch(
        "app.sdk_generation_settings_routes.db.write_access_audit",
        side_effect=RuntimeError("ledger down"),
    ):
        resp = client.put(_TENANT_URL, json={"settings": {}})
    assert resp.status_code == 200


def test_the_response_is_camel_case() -> None:
    with patch("app.sdk_generation_settings_routes.enforce_permission"), patch(
        "app.sdk_generation_settings_routes.load_settings",
        return_value=_settings(user_agent="acme/1.0"),
    ):
        body: Dict[str, Any] = client.get(_TENANT_URL).json()
    assert body["contentFingerprint"].startswith("sha256:")
    assert body["schemaVersion"] == "sdk.generation-settings.v1"
    assert body["settings"]["userAgent"] == "acme/1.0"
    assert "packageNames" in body["resolved"]


def test_the_project_router_is_registered_after_the_projects_router() -> None:
    """Otherwise ``/{tenant}/by-slug/{slug}`` loses to a project slugged ``sdk-settings``."""
    paths = [getattr(route, "path", "") for route in app.routes]
    projects_index = min(
        i for i, path in enumerate(paths) if path.endswith("/by-slug/{project_slug}")
    )
    settings_index = min(i for i, path in enumerate(paths) if path.endswith("/sdk-settings"))
    assert projects_index < settings_index
