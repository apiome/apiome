"""Each producer routes its findings to the owner team — CDG-2.3 (#5962).

The routing itself is ``test_owner_routing``; this pins the wiring. Every producer calls the owner
router with the right entity, finding type, deep link and actor, after its own work, and never lets a
routing failure reach its caller:

* lint gate → ``owner_finding`` on the project (or the MCP endpoint of a snapshot);
* refresh breaking change → ``owner_breaking_change``, excluding the users the caller already told;
* verification drift → ``owner_verification_drift`` on the project the ``versionRef`` names;
* deploy gate ``fail`` (only ``fail``) → ``owner_gate_blocked``;
* MCP trust drift → ``owner_trust_drift`` behind the existing kill switch;
* new shadow APIs → ``owner_shadow_api`` on the connector, even with no tenant channels;
* connector sync failure → ``owner_sync_failed`` with the redacted error, never on success.
"""

from __future__ import annotations

from typing import Any, List
from unittest.mock import patch

import pytest

from app import owner_routing
from app.owner_routing import OwnerFinding, RoutingOutcome

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_ENDPOINT = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def routed(monkeypatch) -> List[OwnerFinding]:
    """Capture every finding the producers route; resolve every projects row as a catalog item."""
    seen: List[OwnerFinding] = []

    def _route(db: Any, finding: OwnerFinding) -> RoutingOutcome:
        seen.append(finding)
        return RoutingOutcome(status="routed", team_slug="payments", inbox_rows=2)

    monkeypatch.setattr(owner_routing, "route_owner_finding_safely", _route)
    monkeypatch.setattr(owner_routing, "entity_kind_of", lambda db, t, kind, i: "catalog_item")
    return seen


# ---------------------------------------------------------------------------------------------
# lint gate
# ---------------------------------------------------------------------------------------------


def _gate(subject_type: str, subject_id: str, regressions: List[dict]):
    from app.lint_gate import GateEvaluation

    return GateEvaluation(
        subject_type=subject_type,
        subject_id=subject_id,
        project_id=_PROJECT if subject_type == "catalog_revision" else None,
        tenant_slug="acme",
        policy_version={"id": "p1"},
        evaluation=None,
        evaluation_id="eval-1",
        gate_evaluation=None,
        gate_passed=False,
        new_only=True,
        baseline_subject_id=None,
        findings=regressions,
        new_fingerprints=[],
        regressions=regressions,
        scanners=[],
    )


def test_new_error_findings_reach_the_projects_owner(routed) -> None:
    from app import lint_gate

    regressions = [
        {"source_fingerprint": "fp1", "rule_id": "operation-id"},
        {"source_fingerprint": "fp2", "rule_id": "no-ref-siblings"},
    ]
    lint_gate._route_regressions_to_owner(
        _gate("catalog_revision", "44444444-4444-4444-8444-444444444444", regressions),
        tenant_id=_TENANT,
    )
    (finding,) = routed
    assert finding.finding_type == "owner_finding" and finding.entity_kind == "project"
    assert finding.entity_id == _PROJECT
    assert finding.summary == "2 new error-level lint findings"
    assert finding.link == f"/ade/dashboard/catalog/{_PROJECT}?tab=lint"
    assert finding.details["rules"] == ["no-ref-siblings", "operation-id"]
    assert finding.finding_id == "eval-1"


def test_an_mcp_snapshots_findings_reach_the_endpoints_owner(routed) -> None:
    from app import lint_gate

    with patch.object(lint_gate.db, "execute_query", return_value=[{"endpoint_id": _ENDPOINT}]):
        lint_gate._route_regressions_to_owner(
            _gate("mcp_endpoint_version", "v-1", [{"source_fingerprint": "fp1"}]), tenant_id=_TENANT
        )
    assert routed[0].entity_kind == "mcp_endpoint" and routed[0].entity_id == _ENDPOINT
    assert routed[0].version_id is None


# ---------------------------------------------------------------------------------------------
# refresh breaking change
# ---------------------------------------------------------------------------------------------


class _QuietChannels:
    """A database double with no webhook channels, mutes or throttle claims to worry about."""

    def list_active_push_webhook_subscription_channels(self, tenant_id):
        return []

    def list_muted_repository_notification_events(self, *args, **kwargs):
        return []


def test_a_breaking_change_reaches_the_owner_without_repeating_the_requester(routed) -> None:
    from app.repository_event_notifications import notify_repository_breaking_change

    notify_repository_breaking_change(
        _QuietChannels(),
        tenant_id=_TENANT,
        repository_id="r-1",
        repository_full_name="acme/pets",
        project_id=_PROJECT,
        version_id="44444444-4444-4444-8444-444444444444",
        change_report_id="cr-1",
        max_severity="breaking",
        breaking_change_count=2,
        actor_id=_ACTOR,
        already_notified=["requester-1"],
    )
    (finding,) = routed
    assert finding.finding_type == "owner_breaking_change"
    assert finding.entity_id == _PROJECT and finding.finding_id == "cr-1"
    assert finding.actor_id == _ACTOR and finding.already_notified == ("requester-1",)
    assert finding.details["breakingChangeCount"] == 2


def test_a_breaking_change_without_a_project_routes_nothing(routed) -> None:
    from app.repository_event_notifications import notify_repository_breaking_change

    notify_repository_breaking_change(_QuietChannels(), tenant_id=_TENANT, repository_id="r-1")
    assert routed == []


# ---------------------------------------------------------------------------------------------
# verification drift
# ---------------------------------------------------------------------------------------------


def test_verification_drift_reaches_the_owner_of_the_verified_project(routed, monkeypatch) -> None:
    from app import verification_schedule_notifications as notes

    monkeypatch.setattr(notes, "enqueue_event", lambda *a, **k: ["d1"])
    monkeypatch.setattr(owner_routing, "project_id_for_version_ref", lambda db, t, ref: _PROJECT)
    ids = notes.notify_verification_drift(
        object(),
        tenant_id=_TENANT,
        payload={"versionRef": "project/petstore/1.0.0", "scheduleName": "Nightly prod",
                 "driftCount": 3, "reportId": "rep-1", "target": {"environment": "prod"}},
    )
    assert ids == ["d1"]
    (finding,) = routed
    assert finding.finding_type == "owner_verification_drift"
    assert finding.summary == "Nightly prod found drift (3 operations)"
    assert finding.details["environment"] == "prod" and finding.finding_id == "rep-1"


def test_drift_on_an_unresolvable_ref_routes_nothing(routed, monkeypatch) -> None:
    from app import verification_schedule_notifications as notes

    monkeypatch.setattr(notes, "enqueue_event", lambda *a, **k: [])
    monkeypatch.setattr(owner_routing, "project_id_for_version_ref", lambda db, t, ref: None)
    notes.notify_verification_drift(object(), tenant_id=_TENANT, payload={"versionRef": "x"})
    assert routed == []


# ---------------------------------------------------------------------------------------------
# deploy gate
# ---------------------------------------------------------------------------------------------


def _gate_report(status: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        status=status, project_id=_PROJECT, project_slug="petstore", revision_id="rev-1",
        version_label="1.2.0", summary="lint failed",
        signals=[SimpleNamespace(signal="lint", status=status),
                 SimpleNamespace(signal="breaking", status="pass")],
    )


def test_a_failing_gate_reaches_the_owner(routed) -> None:
    from app.deploy_gate_service import route_blocked_gate

    route_blocked_gate(_gate_report("fail"), tenant_id=_TENANT, actor_id=_ACTOR)
    (finding,) = routed
    assert finding.finding_type == "owner_gate_blocked"
    assert finding.details["failing_signals"] == ["lint"]
    assert finding.actor_id == _ACTOR and finding.summary.startswith("Deploy gate failed for petstore 1.2.0")


@pytest.mark.parametrize("status", ["pass", "warn", "not_configured", "unknown"])
def test_a_gate_that_lets_a_deploy_through_routes_nothing(routed, status) -> None:
    from app.deploy_gate_service import route_blocked_gate

    route_blocked_gate(_gate_report(status), tenant_id=_TENANT)
    assert routed == []


def test_the_gate_route_routes_after_building_the_verdict(routed) -> None:
    from fastapi.testclient import TestClient
    from test_deploy_gate_routes import _report

    from app.auth import validate_authentication
    from app.main import app

    report = _report("fail")
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt",
    }
    try:
        with patch("app.deploy_gate_routes.enforce_permission", return_value=_ACTOR), patch(
            "app.deploy_gate_routes.has_permission", return_value=True
        ), patch("app.deploy_gate_routes.build_project_gate", return_value=report), patch(
            "app.deploy_gate_routes.route_blocked_gate"
        ) as route:
            response = TestClient(app).get(f"/v1/projects/acme/{_PROJECT}/gate")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200 and response.json()["status"] == "fail"
    assert route.call_args.args == (report,)
    assert route.call_args.kwargs == {"tenant_id": _TENANT, "actor_id": _ACTOR}


# ---------------------------------------------------------------------------------------------
# MCP trust drift
# ---------------------------------------------------------------------------------------------


def test_mcp_endpoint_problems_route_as_trust_drift(routed) -> None:
    owner_routing.route_mcp_endpoint_problem(
        object(), tenant_id=_TENANT, endpoint={"id": _ENDPOINT, "name": "Tools"},
        summary="Tools drifted", finding_id="fp-2",
    )
    (finding,) = routed
    assert finding.finding_type == "owner_trust_drift" and finding.entity_kind == "mcp_endpoint"
    assert finding.link == f"/ade/dashboard/mcp/{_ENDPOINT}"


# ---------------------------------------------------------------------------------------------
# shadow APIs and sync failures
# ---------------------------------------------------------------------------------------------


def test_new_shadow_apis_reach_the_connectors_owner_with_no_tenant_channels(routed, monkeypatch) -> None:
    from app import shadow_api_notifications as shadow

    monkeypatch.setattr(shadow, "load_catalog_entries", lambda db, t: [])
    monkeypatch.setattr(shadow, "resolve_channels", lambda db, t: [])
    connector = {"id": "66666666-6666-4666-8666-666666666666", "tenant_id": _TENANT,
                 "name": "Prod Kong", "kind": "kong-admin"}
    result = shadow.notify_new_shadow_apis(
        object(), connector, [{"remote_id": "svc-1", "name": "Orders", "status": "discovered"}]
    )
    assert result["suppressed"] == "no-channels" and result["owner"] == "routed"
    (finding,) = routed
    assert finding.finding_type == "owner_shadow_api" and finding.entity_kind == "connector"
    assert finding.link.startswith("/ade/dashboard/connectors/shadow")


def test_a_failed_sync_reaches_the_connectors_owner_with_the_redacted_error(monkeypatch) -> None:
    from types import SimpleNamespace

    from app import catalog_connector_sync as sync

    seen: List[OwnerFinding] = []
    monkeypatch.setattr(sync, "owner_router", lambda db, finding: seen.append(finding))
    connector = {"id": "66666666-6666-4666-8666-666666666666", "tenant_id": _TENANT,
                 "name": "Prod Kong", "kind": "kong-admin"}
    result = SimpleNamespace(error_class="auth", http_status=401, error_message="401 from provider")
    sync._route_sync_failure(object(), connector, result, "run-1", _ACTOR)
    (finding,) = seen
    assert finding.finding_type == "owner_sync_failed"
    assert finding.summary == "Prod Kong failed to sync (auth)"
    assert finding.details == {"connector_kind": "kong-admin", "error_class": "auth",
                               "http_status": 401, "error_message": "401 from provider"}
    assert finding.link.endswith("?tab=runs") and finding.finding_id == "run-1"
