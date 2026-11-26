"""HTTP contract and unit tests for environments and deployments — PFX-5.7 (#6951).

The routes of :mod:`app.pact_deployment_routes` with the store faked
(``test_pact_deployments_db`` runs them against the real schema), and the pure parts of
:mod:`app.pact_deployments`:

* every route is gated on ``pacts:view`` before anything is read;
* the topology groups each current deployment and release under its environment;
* the history renders each deployment and passes its filters and cursor through;
* the simulator renders the verdict, the impacts, what was not checked and a summary;
* refusals map to their status (400 cursor / instance, 404 environment / pacticipant / version);
* :func:`classify_effect`, :func:`plan_checks`, the cursor and instance checks.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.pact_deployments import (
    CODE_DEPLOYMENT_CURSOR_INVALID,
    CODE_SIMULATION_INVALID,
    EFFECT_BLOCKS,
    EFFECT_BREAKS,
    EFFECT_CHANGES,
    EFFECT_CLEARS,
    EFFECT_FIXES,
    EFFECT_UNCHANGED,
    PLACEMENT_PENDING,
    PLACEMENT_RUNNING,
    Check,
    HistoryEntry,
    HistoryPage,
    Impact,
    NotChecked,
    Placement,
    Simulation,
    Topology,
    TopologyEntry,
    _placements,
    classify_effect,
    decode_history_cursor,
    environment_by_name,
    plan_checks,
    validate_application_instance,
)
from app.pact_environment import CODE_ENVIRONMENT_NOT_FOUND, EnvironmentRecord
from app.pact_publication import PactPublicationError
from app.pacticipant import CODE_NOT_FOUND, CODE_VERSION_NOT_FOUND, PacticipantRecord, PacticipantValidationError
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_AUTH = {"tenant_id": _TENANT, "user_id": "test-user-id", "auth_method": "jwt"}
_BASE = "/v1/tenants/acme/pact-environments"
_ROUTES = "app.pact_deployment_routes"
_PROD = EnvironmentRecord(
    id="22222222-2222-4222-8222-222222222222", name="production", display_name="Production", production=True
)
_STAGING = EnvironmentRecord(id="33333333-3333-4333-8333-333333333333", name="staging", display_name="Staging")


@pytest.fixture(autouse=True)
def _auth() -> Iterator[None]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def allowed() -> Iterator[MagicMock]:
    with patch(f"{_ROUTES}.enforce_permission", return_value="test-user-id") as enforce:
        yield enforce


def _denied(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=403, detail="Permission denied")


def _entry(environment: EnvironmentRecord, name: str, version: str, instance: Any = None) -> TopologyEntry:
    return TopologyEntry(
        environment_id=environment.id,
        pacticipant_slug=name.lower().replace(" ", "-"),
        pacticipant_name=name,
        version_number=version,
        application_instance=instance,
        recorded_at="2026-11-25T10:00:00+00:00",
    )


def _check(deployable: Any, text: str = "All required verification results are published and successful") -> Check:
    return Check(
        deployable=deployable,
        reasons=[{"type": "success" if deployable else "error", "code": "verified", "text": text}],
        counts={"success": 1, "failed": 0, "unknown": 0},
    )


def _placement(name: str, version: str, placement: str, environments: tuple = ()) -> Placement:
    return Placement("id-" + name, name.lower().replace(" ", "-"), name, version, placement, environments)


# --- Permissions ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [_BASE, f"{_BASE}/production/deployments", f"{_BASE}/production/simulate?pacticipant=a&version=1"],
)
def test_every_route_needs_pacts_view_before_reading(path: str) -> None:
    with (
        patch(f"{_ROUTES}.enforce_permission", side_effect=_denied) as enforce,
        patch(f"{_ROUTES}.read_topology") as topology,
        patch(f"{_ROUTES}.list_deployment_history") as history,
        patch(f"{_ROUTES}.simulate_deployment") as simulate,
    ):
        response = client.get(path)
    assert response.status_code == 403
    assert enforce.call_args.args[2:] == (Resource.PACTS, Action.VIEW)
    topology.assert_not_called()
    history.assert_not_called()
    simulate.assert_not_called()


def test_a_credential_without_a_tenant_is_refused(allowed: MagicMock) -> None:
    app.dependency_overrides[validate_authentication] = lambda: {"user_id": "u"}
    with patch(f"{_ROUTES}.read_topology") as topology:
        response = client.get(_BASE)
    assert response.status_code == 403
    topology.assert_not_called()


# --- Topology ------------------------------------------------------------------------------------


def test_the_topology_groups_deployments_and_releases_by_environment(allowed: MagicMock) -> None:
    topology = Topology(
        environments=[_PROD, _STAGING],
        deployed=[_entry(_PROD, "Ledger API", "p-1", "eu-1"), _entry(_STAGING, "Ledger API", "p-2")],
        released=[_entry(_PROD, "Mobile App", "3.1")],
        truncated=False,
    )
    with patch(f"{_ROUTES}.read_topology", return_value=topology) as read:
        response = client.get(_BASE)
    assert response.status_code == 200, response.text
    assert read.call_args.args[1] == _TENANT
    body = response.json()
    assert body["truncated"] is False
    production, staging = body["environments"]
    assert production == {
        "uuid": _PROD.id,
        "name": "production",
        "displayName": "Production",
        "production": True,
        "contractRequired": False,
        "deployed": [
            {
                "pacticipant": {"name": "Ledger API", "slug": "ledger-api"},
                "version": "p-1",
                "applicationInstance": "eu-1",
                "deployedAt": "2026-11-25T10:00:00+00:00",
            }
        ],
        "released": [
            {
                "pacticipant": {"name": "Mobile App", "slug": "mobile-app"},
                "version": "3.1",
                "releasedAt": "2026-11-25T10:00:00+00:00",
            }
        ],
    }
    assert [d["version"] for d in staging["deployed"]] == ["p-2"] and staging["released"] == []


def test_the_topology_says_when_it_was_truncated(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.read_topology", return_value=Topology([], [], [], True)):
        assert client.get(_BASE).json() == {"environments": [], "truncated": True}


# --- History -------------------------------------------------------------------------------------


def test_the_history_renders_each_deployment_and_passes_its_filters(allowed: MagicMock) -> None:
    page = HistoryPage(
        environment=_PROD,
        deployments=[
            HistoryEntry(
                id="d-1",
                pacticipant_slug="ledger-api",
                pacticipant_name="Ledger API",
                version_number="p-1",
                application_instance=None,
                currently_deployed=False,
                deployed_at="2026-11-24T10:00:00+00:00",
                undeployed_at="2026-11-25T10:00:00+00:00",
                recorded_by="ci",
            )
        ],
        next_cursor="41",
    )
    with patch(f"{_ROUTES}.list_deployment_history", return_value=page) as listing:
        response = client.get(
            f"{_BASE}/production/deployments", params={"pacticipant": "ledger-api", "cursor": "42", "limit": 5}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["environment"]["name"] == "production"
    assert body["nextCursor"] == "41"
    assert body["deployments"] == [
        {
            "uuid": "d-1",
            "pacticipant": {"name": "Ledger API", "slug": "ledger-api"},
            "version": "p-1",
            "applicationInstance": None,
            "currentlyDeployed": False,
            "deployedAt": "2026-11-24T10:00:00+00:00",
            "undeployedAt": "2026-11-25T10:00:00+00:00",
            "recordedBy": "ci",
        }
    ]
    assert listing.call_args.args[1:] == (_TENANT, "production")
    assert listing.call_args.kwargs == {"pacticipant_ref": "ledger-api", "cursor": "42", "limit": 5}


@pytest.mark.parametrize("limit", [0, 51])
def test_a_history_page_outside_1_to_50_is_refused(allowed: MagicMock, limit: int) -> None:
    with patch(f"{_ROUTES}.list_deployment_history") as listing:
        assert client.get(f"{_BASE}/production/deployments", params={"limit": limit}).status_code == 422
    listing.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PactPublicationError(CODE_DEPLOYMENT_CURSOR_INVALID, "bad cursor", pointer="/cursor"), 400),
        (PactPublicationError(CODE_ENVIRONMENT_NOT_FOUND, "no such environment"), 404),
        (PacticipantValidationError(CODE_NOT_FOUND, "no such pacticipant"), 404),
    ],
)
def test_history_refusals_keep_their_code_and_status(allowed: MagicMock, error: Exception, status: int) -> None:
    with patch(f"{_ROUTES}.list_deployment_history", side_effect=error):
        response = client.get(f"{_BASE}/production/deployments")
    assert response.status_code == status
    assert response.json()["detail"]["code"] == error.code  # type: ignore[attr-defined]


# --- Simulator -----------------------------------------------------------------------------------


def _simulation() -> Simulation:
    return Simulation(
        environment=_PROD,
        pacticipant=PacticipantRecord(id="id-ledger", tenant_id=_TENANT, slug="ledger-api", name="Ledger API"),
        version_number="p-2",
        application_instance=None,
        replaces="p-1",
        already_deployed=False,
        verdict=_check(True),
        impacts=[
            Impact(
                placement=_placement("Billing Service", "2.0.0", PLACEMENT_PENDING, ("staging",)),
                roles=("consumer",),
                before=_check(False, "The verification for the pact between … failed"),
                after=_check(True),
                effect=EFFECT_CLEARS,
            ),
            Impact(
                placement=_placement("Billing Service", "1.0.0", PLACEMENT_RUNNING),
                roles=("consumer",),
                before=_check(True),
                after=_check(True),
                effect=EFFECT_UNCHANGED,
            ),
        ],
        not_checked=[
            NotChecked(
                placement=_placement("Mobile App", "3.1", PLACEMENT_PENDING, ("staging",)),
                code="pact-simulation-over-limit",
                reason="Only 20 counterpart versions are checked per simulation.",
            )
        ],
        evaluated_at="2026-11-25T12:00:00+00:00",
    )


def test_the_simulation_renders_verdict_impacts_and_what_was_not_checked(allowed: MagicMock) -> None:
    with patch(f"{_ROUTES}.simulate_deployment", return_value=_simulation()) as simulate:
        response = client.get(
            f"{_BASE}/production/simulate",
            params={"pacticipant": "ledger-api", "version": "p-2", "applicationInstance": "eu-1"},
        )
    assert response.status_code == 200, response.text
    assert simulate.call_args.args[1:] == (_TENANT, "production", "ledger-api", "p-2")
    assert simulate.call_args.kwargs == {"application_instance": "eu-1"}
    body = response.json()
    assert body["environment"]["name"] == "production"
    assert body["pacticipant"] == {"name": "Ledger API", "slug": "ledger-api"}
    assert (body["version"], body["replaces"], body["alreadyDeployed"]) == ("p-2", "p-1", False)
    assert body["evaluatedAt"] == "2026-11-25T12:00:00+00:00"
    assert body["verdict"]["deployable"] is True
    assert body["verdict"]["reason"] == "All required verification results are published and successful"
    assert body["summary"] == {"clears": 1, "unchanged": 1}
    cleared = body["impacts"][0]
    assert cleared["pacticipant"] == {"name": "Billing Service", "slug": "billing-service"}
    assert (cleared["placement"], cleared["environments"], cleared["roles"]) == ("pending", ["staging"], ["consumer"])
    assert (cleared["before"]["deployable"], cleared["after"]["deployable"], cleared["effect"]) == (
        False,
        True,
        "clears",
    )
    assert body["notChecked"] == [
        {
            "pacticipant": {"name": "Mobile App", "slug": "mobile-app"},
            "version": "3.1",
            "placement": "pending",
            "environments": ["staging"],
            "code": "pact-simulation-over-limit",
            "reason": "Only 20 counterpart versions are checked per simulation.",
        }
    ]


@pytest.mark.parametrize("params", [{"version": "1"}, {"pacticipant": "a"}, {"pacticipant": "", "version": "1"}])
def test_the_simulation_needs_a_pacticipant_and_a_version(allowed: MagicMock, params: Dict[str, str]) -> None:
    with patch(f"{_ROUTES}.simulate_deployment") as simulate:
        assert client.get(f"{_BASE}/production/simulate", params=params).status_code == 422
    simulate.assert_not_called()


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (PactPublicationError(CODE_SIMULATION_INVALID, "bad instance", pointer="/applicationInstance"), 400),
        (PactPublicationError(CODE_ENVIRONMENT_NOT_FOUND, "no such environment"), 404),
        (PacticipantValidationError(CODE_NOT_FOUND, "no such pacticipant"), 404),
        (PacticipantValidationError(CODE_VERSION_NOT_FOUND, "no such version"), 404),
    ],
)
def test_simulation_refusals_keep_their_code_and_status(allowed: MagicMock, error: Exception, status: int) -> None:
    with patch(f"{_ROUTES}.simulate_deployment", side_effect=error):
        response = client.get(f"{_BASE}/production/simulate", params={"pacticipant": "a", "version": "1"})
    assert response.status_code == status
    detail = response.json()["detail"]
    assert detail["code"] == error.code  # type: ignore[attr-defined]
    assert detail["message"] == str(error)


# --- The pure parts ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("placement", "before", "after", "effect"),
    [
        (PLACEMENT_RUNNING, True, True, EFFECT_UNCHANGED),
        (PLACEMENT_RUNNING, False, False, EFFECT_UNCHANGED),
        (PLACEMENT_RUNNING, None, None, EFFECT_UNCHANGED),
        (PLACEMENT_RUNNING, True, False, EFFECT_BREAKS),
        (PLACEMENT_RUNNING, True, None, EFFECT_BREAKS),
        (PLACEMENT_RUNNING, False, True, EFFECT_FIXES),
        (PLACEMENT_RUNNING, None, True, EFFECT_FIXES),
        (PLACEMENT_RUNNING, False, None, EFFECT_CHANGES),
        (PLACEMENT_PENDING, False, True, EFFECT_CLEARS),
        (PLACEMENT_PENDING, None, True, EFFECT_CLEARS),
        (PLACEMENT_PENDING, True, False, EFFECT_BLOCKS),
        (PLACEMENT_PENDING, True, None, EFFECT_BLOCKS),
        (PLACEMENT_PENDING, None, False, EFFECT_CHANGES),
        (PLACEMENT_PENDING, True, True, EFFECT_UNCHANGED),
    ],
)
def test_classify_effect(placement: str, before: Any, after: Any, effect: str) -> None:
    assert classify_effect(placement, before, after) == effect


def test_plan_checks_takes_running_versions_first_and_returns_the_rest() -> None:
    placements = [
        _placement("Zed", "1", PLACEMENT_PENDING),
        _placement("Alpha", "1", PLACEMENT_PENDING),
        _placement("Mid", "1", PLACEMENT_RUNNING),
    ]
    checked, rest = plan_checks(placements, limit=2)
    assert [(p.pacticipant_name, p.placement) for p in checked] == [("Mid", "running"), ("Alpha", "pending")]
    assert [p.pacticipant_name for p in rest] == ["Zed"]


def test_placements_split_running_from_pending_and_collect_environments() -> None:
    names = {"b": ("billing", "Billing")}
    placed = [
        {
            "pacticipant_id": "b",
            "version_id": "v2",
            "number": "2",
            "environment_id": "stg",
            "environment_name": "staging",
        },
        {"pacticipant_id": "b", "version_id": "v2", "number": "2", "environment_id": "qa", "environment_name": "qa"},
        {
            "pacticipant_id": "b",
            "version_id": "v1",
            "number": "1",
            "environment_id": "prod",
            "environment_name": "production",
        },
        # Running here and elsewhere: running only.
        {
            "pacticipant_id": "b",
            "version_id": "v1",
            "number": "1",
            "environment_id": "stg",
            "environment_name": "staging",
        },
        # Not a counterpart (the candidate's own pacticipant): ignored.
        {
            "pacticipant_id": "x",
            "version_id": "vx",
            "number": "9",
            "environment_id": "prod",
            "environment_name": "production",
        },
    ]
    result = _placements(placed, names, "prod")
    assert [(p.version_number, p.placement, p.environments) for p in result] == [
        ("1", "running", ()),
        ("2", "pending", ("qa", "staging")),
    ]


@pytest.mark.parametrize("value", ["", " eu-1", "eu-1 ", "a\tb", "x" * 256])
def test_a_malformed_application_instance_is_refused(value: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        validate_application_instance(value)
    assert caught.value.code == CODE_SIMULATION_INVALID


def test_a_well_formed_application_instance_is_kept() -> None:
    assert validate_application_instance(None) is None
    assert validate_application_instance("eu-west 1") == "eu-west 1"


@pytest.mark.parametrize("cursor", ["", "abc", "-1", "0", "1" * 20])
def test_an_unreadable_history_cursor_is_refused(cursor: str) -> None:
    with pytest.raises(PactPublicationError) as caught:
        decode_history_cursor(cursor)
    assert caught.value.code == CODE_DEPLOYMENT_CURSOR_INVALID


def test_a_history_cursor_reads_back() -> None:
    assert decode_history_cursor(None) is None
    assert decode_history_cursor("42") == 42


@pytest.mark.parametrize("name", ["", "   ", "x" * 256])
def test_an_empty_or_over_long_environment_name_is_not_found_without_reading(name: str) -> None:
    database = MagicMock()
    with pytest.raises(PactPublicationError) as caught:
        environment_by_name(database, _TENANT, name)
    assert caught.value.code == CODE_ENVIRONMENT_NOT_FOUND
    database.execute_query.assert_not_called()
