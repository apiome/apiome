"""Deploy-gate endpoints — CTG-4.5 (#4502).

Authentication is overridden and the service/store layers are patched, so these tests assert the
HTTP contract only: which permission each route enforces, that a failing verdict is still a ``200``,
how the refusals map to statuses, and that the consumer signal is gated on the caller's registry
permission rather than on the project's configuration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.deploy_gate import (
    DEFAULT_THRESHOLDS,
    SIGNAL_LINT,
    STATUS_FAIL,
    STATUS_PASS,
    DeployGatePolicyOut,
    GateSignal,
    GateThresholdError,
    build_gate_report,
    thresholds_content_fingerprint,
)
from app.deploy_gate_service import (
    CODE_NO_PUBLISHED_REVISION,
    CODE_PROJECT_NOT_FOUND,
    DeployGateError,
)
from app.main import app
from app.permissions import Action, Resource

client = TestClient(app)

_MOCK_AUTH = {
    "tenant_id": "11111111-1111-4111-8111-111111111111",
    "user_id": "33333333-3333-4333-8333-333333333333",
    "auth_method": "jwt",
}
_TENANT_SLUG = "acme"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_REVISION = "44444444-4444-4444-8444-444444444444"
_NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)

_GATE = f"/v1/projects/{_TENANT_SLUG}/{_PROJECT}/gate"
_POLICY = f"{_GATE}/policy"
_TENANT_POLICY = f"/v1/tenants/{_TENANT_SLUG}/governance/deploy-gate-policy"


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request; permission enforcement is asserted per test."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


def _policy(source: str = "default") -> DeployGatePolicyOut:
    """The default policy, as a response carries it."""
    return DeployGatePolicyOut(
        source=source,
        content_fingerprint=thresholds_content_fingerprint(DEFAULT_THRESHOLDS),
        thresholds=DEFAULT_THRESHOLDS,
    )


def _report(status: str = STATUS_PASS):
    """A gate report with one signal carrying the given status."""
    return build_gate_report(
        project_id=_PROJECT,
        project_slug="petstore",
        revision_id=_REVISION,
        version_label="1.2.0",
        version_ref="project/petstore/1.2.0",
        published_at=_NOW,
        signals=[
            GateSignal(
                signal=SIGNAL_LINT,
                status=status,
                satisfied=status == STATUS_PASS,
                reason="lint-grade-meets-thresholds",
                detail="Lint grade A meets the configured thresholds.",
            )
        ],
        policy=_policy(),
        evaluated_at=_NOW,
    )


def _kwargs(mock) -> Dict[str, Any]:
    """Keyword arguments of the last call to ``mock``."""
    return mock.call_args.kwargs


# ---------------------------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------------------------


def test_reading_the_gate_needs_versions_view():
    """A gate is the status of a published version, which is what a CI key resolves to."""
    with patch(
        "app.deploy_gate_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.deploy_gate_routes.has_permission", return_value=True
    ), patch(
        "app.deploy_gate_routes.build_project_gate", return_value=_report()
    ):
        assert client.get(_GATE).status_code == 200
    assert enforce.call_args.args[2:] == (Resource.VERSIONS, Action.VIEW)


def test_a_failing_verdict_is_still_a_200():
    """A 409 on a failing build would make a network fault and a breaking change look alike."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes.has_permission", return_value=True
    ), patch("app.deploy_gate_routes.build_project_gate", return_value=_report(STATUS_FAIL)):
        response = client.get(_GATE)
    assert response.status_code == 200
    assert response.json()["status"] == STATUS_FAIL


def test_the_response_body_is_camel_case_for_a_one_line_curl():
    """The wire keys are the contract a pipeline pipes through `jq`."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes.has_permission", return_value=True
    ), patch("app.deploy_gate_routes.build_project_gate", return_value=_report()):
        body = client.get(_GATE).json()
    assert body["schemaVersion"] == "ctg.gate.v1"
    assert body["evaluatedSignals"] == 1
    assert body["versionRef"] == "project/petstore/1.2.0"
    assert body["signals"][0]["signal"] == SIGNAL_LINT
    assert body["policy"]["source"] == "default"


def test_the_consumer_signal_is_gated_on_the_callers_registry_permission():
    """The service is told what the caller may see; it does not guess."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes.has_permission", return_value=False
    ) as permitted, patch(
        "app.deploy_gate_routes.build_project_gate", return_value=_report()
    ) as build:
        assert client.get(_GATE).status_code == 200
    assert permitted.call_args.args[2:] == (Resource.CONSUMER_CONTRACTS, Action.VIEW)
    assert _kwargs(build)["consumers_permitted"] is False


def test_an_explicit_revision_is_forwarded():
    """`revisionId` gates a specific publish instead of the newest one."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes.has_permission", return_value=True
    ), patch(
        "app.deploy_gate_routes.build_project_gate", return_value=_report()
    ) as build:
        assert client.get(_GATE, params={"revisionId": _REVISION}).status_code == 200
    assert _kwargs(build)["revision_id"] == _REVISION


def test_a_service_refusal_keeps_its_status_and_its_code():
    """A pipeline branches on the code without parsing prose."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes.has_permission", return_value=True
    ), patch(
        "app.deploy_gate_routes.build_project_gate",
        side_effect=DeployGateError(
            CODE_NO_PUBLISHED_REVISION, "nothing to promote", status_code=409
        ),
    ):
        response = client.get(_GATE)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == CODE_NO_PUBLISHED_REVISION


def test_a_denied_permission_is_a_403():
    """The enforcement call is what refuses; the route does not second-guess it."""
    with patch(
        "app.deploy_gate_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="nope"),
    ):
        assert client.get(_GATE).status_code == 403


# ---------------------------------------------------------------------------------------------
# Policy
# ---------------------------------------------------------------------------------------------


def test_reading_a_policy_needs_only_what_reading_the_gate_needs():
    """A verdict nobody can explain is not a gate."""
    with patch(
        "app.deploy_gate_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.deploy_gate_routes._require_project_id", return_value=_PROJECT
    ), patch(
        "app.deploy_gate_routes.load_policy", return_value=_policy()
    ):
        assert client.get(_POLICY).status_code == 200
    assert enforce.call_args.args[2:] == (Resource.VERSIONS, Action.VIEW)


def test_moving_the_bar_needs_verification_target_edit():
    """The same class of decision as deciding where verification points — not an Editor's call."""
    with patch(
        "app.deploy_gate_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.deploy_gate_routes._require_project_id", return_value=_PROJECT
    ), patch(
        "app.deploy_gate_routes.save_policy", return_value=_policy("project")
    ), patch(
        "app.deploy_gate_routes.db.write_access_audit"
    ):
        response = client.put(_POLICY, json={"thresholds": {"lint": {"failBelowGrade": "C"}}})
    assert response.status_code == 200
    assert enforce.call_args.args[2:] == (Resource.VERIFICATION_TARGETS, Action.EDIT)


def test_a_project_policy_write_is_scoped_to_that_project_and_audited():
    """An override must not be written as the tenant-wide policy by accident."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes._require_project_id", return_value=_PROJECT
    ), patch(
        "app.deploy_gate_routes.save_policy", return_value=_policy("project")
    ) as save, patch(
        "app.deploy_gate_routes.db.write_access_audit"
    ) as audit:
        client.put(_POLICY, json={"thresholds": {}})
    assert _kwargs(save)["project_id"] == _PROJECT
    assert audit.call_args.kwargs["action"] == "governance.deploy_gate_policy.update"
    assert audit.call_args.kwargs["detail"]["projectId"] == _PROJECT


def test_a_tenant_policy_write_is_scoped_to_no_project():
    """`project_id=None` is what makes a row the tenant-wide default."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes.save_policy", return_value=_policy("tenant")
    ) as save, patch("app.deploy_gate_routes.db.write_access_audit"):
        assert client.put(_TENANT_POLICY, json={"thresholds": {}}).status_code == 200
    assert _kwargs(save)["project_id"] is None


def test_an_incoherent_policy_is_a_422_listing_every_problem():
    """One round trip should be enough to fix a bad policy."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes._require_project_id", return_value=_PROJECT
    ), patch(
        "app.deploy_gate_routes.save_policy",
        side_effect=GateThresholdError(["first problem", "second problem"]),
    ):
        response = client.put(_POLICY, json={"thresholds": {"lint": {}}})
    assert response.status_code == 422
    assert response.json()["detail"]["errors"] == ["first problem", "second problem"]


def test_an_unknown_body_key_is_refused_before_it_reaches_the_store():
    """`extra="forbid"` on the request body, so a typo is never silently a no-op."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes._require_project_id", return_value=_PROJECT
    ), patch("app.deploy_gate_routes.save_policy") as save:
        response = client.put(_POLICY, json={"threshold": {}})
    assert response.status_code == 422
    save.assert_not_called()


def test_clearing_an_override_returns_what_now_governs():
    """A caller should not have to ask a second time what it fell back to."""
    with patch(
        "app.deploy_gate_routes.enforce_permission", return_value="u"
    ) as enforce, patch(
        "app.deploy_gate_routes._require_project_id", return_value=_PROJECT
    ), patch(
        "app.deploy_gate_routes.clear_policy", return_value=True
    ), patch(
        "app.deploy_gate_routes.load_policy", return_value=_policy("tenant")
    ), patch(
        "app.deploy_gate_routes.db.write_access_audit"
    ) as audit:
        response = client.delete(_POLICY)
    assert response.status_code == 200
    assert response.json()["source"] == "tenant"
    assert enforce.call_args.args[2:] == (Resource.VERIFICATION_TARGETS, Action.DELETE)
    assert audit.call_args.kwargs["action"] == "governance.deploy_gate_policy.clear"


def test_clearing_a_policy_that_was_never_saved_is_not_audited():
    """An audit row for a change that did not happen is noise in a governance ledger."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes._require_project_id", return_value=_PROJECT
    ), patch("app.deploy_gate_routes.clear_policy", return_value=False), patch(
        "app.deploy_gate_routes.load_policy", return_value=_policy()
    ), patch(
        "app.deploy_gate_routes.db.write_access_audit"
    ) as audit:
        assert client.delete(_POLICY).status_code == 200
    audit.assert_not_called()


def test_an_unknown_project_is_a_404_on_the_policy_routes_too():
    """The policy surface resolves the same subject the gate does, through the same resolver."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_service.db.get_project_by_id", return_value=None
    ), patch("app.deploy_gate_service.db.get_project_by_slug", return_value=None):
        response = client.get(_POLICY)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == CODE_PROJECT_NOT_FOUND


def test_the_by_slug_route_still_wins_for_a_project_actually_named_gate():
    """Both routes match `/v1/projects/{tenant}/by-slug/gate`; registration order decides.

    A project whose slug is literally `gate` is far likelier than one referenced as `by-slug`, so
    `projects_router` is registered first and this URL reads a project rather than a verdict.
    """
    routes = [route for route in app.routes if getattr(route, "path", "").startswith("/v1/projects")]
    by_slug = next(
        i for i, r in enumerate(routes) if r.path == "/v1/projects/{tenant_slug}/by-slug/{project_slug}"
    )
    gate = next(
        i for i, r in enumerate(routes) if r.path == "/v1/projects/{tenant_slug}/{project_ref}/gate"
    )
    assert by_slug < gate, "the by-slug route must be matched before the gate route"


def test_an_audit_failure_never_fails_the_policy_change():
    """The write succeeded; reporting it as a failure would invite a second, duplicate write."""
    with patch("app.deploy_gate_routes.enforce_permission", return_value="u"), patch(
        "app.deploy_gate_routes._require_project_id", return_value=_PROJECT
    ), patch(
        "app.deploy_gate_routes.save_policy", return_value=_policy("project")
    ), patch(
        "app.deploy_gate_routes.db.write_access_audit", side_effect=RuntimeError("no audit")
    ):
        assert client.put(_POLICY, json={"thresholds": {}}).status_code == 200
