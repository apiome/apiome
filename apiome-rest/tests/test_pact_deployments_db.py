"""Environments, deployment history and the deploy simulator against a live Postgres — PFX-5.7 (#6951).

The story every test starts from (:func:`world`):

* **production** runs Billing Service 1.0.0 (pact A) and Ledger API p-1, which verified pact A;
* **staging** runs Billing Service 2.0.0 (pact B) and Ledger API p-2;
* p-1 **failed** pact B; p-2 verified both A and B.

So Billing Service 2.0.0 cannot go to production while p-1 is there. Simulating p-2 into
production predicts it **clears**; simulating a p-3 that failed pact A **breaks** the running
Billing Service 1.0.0. Every answer must agree with ``can-i-deploy`` asked after a real deployment.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of
``test_pact_publication_db``). Skipped when no database is reachable or V435 is not applied.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest

from tests import test_pact_environment_db as environment_db
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

ENVIRONMENTS = "/v1/tenants/t/pact-environments"


@pytest.fixture
def broker(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The publication stack with the verification, environment, matrix and deployment routes on its transaction."""
    stack["cursor"].execute("SELECT to_regclass('apiome.deployed_version') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V435 not applied")
    modules = (
        "pact_broker_verification_routes",
        "pact_broker_environment_routes",
        "pact_broker_matrix_routes",
        "pact_deployment_routes",
    )
    patches = [patch(f"app.{module}.db", stack["db"]) for module in modules]
    patches += [patch(f"app.{module}.enforce_permission", return_value=None) for module in modules]
    for item in patches:
        item.start()
    try:
        yield stack
    finally:
        for item in patches:
            item.stop()


@pytest.fixture
def world(broker: Dict[str, Any]) -> Dict[str, Any]:
    """Production and staging as the module docstring describes."""
    environment_db._create_environment(broker, "production", production=True)
    environment_db._create_environment(broker, "staging")
    sha_a = matrix_db._publish(broker, "1.0.0", total=1999, branch="main")
    sha_b = matrix_db._publish(broker, "2.0.0", total=2000, branch="main")
    for version in ("p-1", "p-2", "p-3"):
        matrix_db._provider_version(broker, version)
    matrix_db._verify(broker, sha_a, "p-1", True)
    matrix_db._verify(broker, sha_b, "p-1", False)
    matrix_db._verify(broker, sha_a, "p-2", True)
    matrix_db._verify(broker, sha_b, "p-2", True)
    matrix_db._verify(broker, sha_a, "p-3", False)
    matrix_db._deploy(broker, "Ledger API", "p-1", "production")
    matrix_db._deploy(broker, "Billing Service", "1.0.0", "production")
    matrix_db._deploy(broker, "Ledger API", "p-2", "staging")
    matrix_db._deploy(broker, "Billing Service", "2.0.0", "staging")
    return broker


def _simulate(
    stack: Dict[str, Any], pacticipant: str, version: str, environment: str = "production", **extra: str
) -> Dict[str, Any]:
    response = stack["client"].get(
        f"{ENVIRONMENTS}/{environment}/simulate", params={"pacticipant": pacticipant, "version": version, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _impact(body: Dict[str, Any], name: str, version: str) -> Dict[str, Any]:
    return next(i for i in body["impacts"] if i["pacticipant"]["name"] == name and i["version"] == version)


def _can_i_deploy(stack: Dict[str, Any], pacticipant: str, version: str) -> Any:
    response = stack["client"].get(
        f"{matrix_db.BASE}/can-i-deploy",
        params={"pacticipant": pacticipant, "version": version, "toEnvironment": "production"},
    )
    assert response.status_code == 200, response.text
    return response.json()["summary"]["deployable"]


# --- Topology ------------------------------------------------------------------------------------


def test_the_topology_lists_each_environment_with_what_runs_there(world: Dict[str, Any]) -> None:
    body = world["client"].get(ENVIRONMENTS).json()
    assert body["truncated"] is False
    by_name = {e["name"]: e for e in body["environments"]}
    assert list(by_name) == ["production", "staging"]
    assert by_name["production"]["production"] is True
    assert sorted((d["pacticipant"]["name"], d["version"]) for d in by_name["production"]["deployed"]) == [
        ("Billing Service", "1.0.0"),
        ("Ledger API", "p-1"),
    ]
    assert sorted((d["pacticipant"]["name"], d["version"]) for d in by_name["staging"]["deployed"]) == [
        ("Billing Service", "2.0.0"),
        ("Ledger API", "p-2"),
    ]
    environment_db._record(world, "pb:record-release", "Billing Service", "1.0.0", "staging")
    released = world["client"].get(ENVIRONMENTS).json()["environments"][1]["released"]
    assert [(r["pacticipant"]["name"], r["version"]) for r in released] == [("Billing Service", "1.0.0")]


# --- History -------------------------------------------------------------------------------------


def test_the_history_lists_every_deployment_newest_first_with_replaced_ones(world: Dict[str, Any]) -> None:
    matrix_db._deploy(world, "Ledger API", "p-2", "production")
    body = world["client"].get(f"{ENVIRONMENTS}/production/deployments").json()
    assert body["environment"]["name"] == "production"
    assert [(d["pacticipant"]["name"], d["version"], d["currentlyDeployed"]) for d in body["deployments"]] == [
        ("Ledger API", "p-2", True),
        ("Billing Service", "1.0.0", True),
        ("Ledger API", "p-1", False),
    ]
    assert body["deployments"][2]["undeployedAt"] is not None
    assert body["deployments"][0]["undeployedAt"] is None
    assert body["nextCursor"] is None


def test_the_history_pages_and_narrows_by_pacticipant(world: Dict[str, Any]) -> None:
    matrix_db._deploy(world, "Ledger API", "p-2", "production")
    first = world["client"].get(f"{ENVIRONMENTS}/production/deployments", params={"limit": 2}).json()
    assert len(first["deployments"]) == 2 and first["nextCursor"]
    second = (
        world["client"]
        .get(f"{ENVIRONMENTS}/production/deployments", params={"limit": 2, "cursor": first["nextCursor"]})
        .json()
    )
    assert [d["version"] for d in second["deployments"]] == ["p-1"] and second["nextCursor"] is None
    ledger = world["client"].get(f"{ENVIRONMENTS}/production/deployments", params={"pacticipant": "ledger-api"}).json()
    assert [d["version"] for d in ledger["deployments"]] == ["p-2", "p-1"]


def test_history_refusals(world: Dict[str, Any]) -> None:
    client = world["client"]
    unknown = client.get(f"{ENVIRONMENTS}/nowhere/deployments")
    assert (unknown.status_code, unknown.json()["detail"]["code"]) == (404, "pact-environment-not-found")
    stranger = client.get(f"{ENVIRONMENTS}/production/deployments", params={"pacticipant": "nobody"})
    assert (stranger.status_code, stranger.json()["detail"]["code"]) == (404, "pacticipant-not-found")
    bad = client.get(f"{ENVIRONMENTS}/production/deployments", params={"cursor": "zz"})
    assert (bad.status_code, bad.json()["detail"]["code"]) == (400, "pact-deployment-cursor-invalid")


# --- Simulator -----------------------------------------------------------------------------------


def test_promoting_the_staging_provider_clears_the_staging_consumer(world: Dict[str, Any]) -> None:
    body = _simulate(world, "ledger-api", "p-2")
    assert body["verdict"]["deployable"] is True
    assert (body["replaces"], body["alreadyDeployed"], body["applicationInstance"]) == ("p-1", False, None)
    running = _impact(body, "Billing Service", "1.0.0")
    assert (running["placement"], running["effect"], running["roles"]) == ("running", "unchanged", ["consumer"])
    pending = _impact(body, "Billing Service", "2.0.0")
    assert (pending["placement"], pending["environments"]) == ("pending", ["staging"])
    assert (pending["before"]["deployable"], pending["after"]["deployable"], pending["effect"]) == (
        False,
        True,
        "clears",
    )
    assert body["summary"] == {"unchanged": 1, "clears": 1}
    assert body["notChecked"] == []

    # The prediction is what can-i-deploy answers once the deployment really happens.
    assert _can_i_deploy(world, "Billing Service", "2.0.0") is False
    matrix_db._deploy(world, "Ledger API", "p-2", "production")
    assert _can_i_deploy(world, "Billing Service", "2.0.0") is True


def test_a_provider_that_failed_the_running_pact_breaks_its_consumer(world: Dict[str, Any]) -> None:
    body = _simulate(world, "Ledger API", "p-3")
    assert body["verdict"]["deployable"] is False
    running = _impact(body, "Billing Service", "1.0.0")
    assert (running["before"]["deployable"], running["after"]["deployable"], running["effect"]) == (
        True,
        False,
        "breaks",
    )
    assert "failed" in running["after"]["reason"]
    pending = _impact(body, "Billing Service", "2.0.0")
    assert (pending["before"]["deployable"], pending["after"]["deployable"], pending["effect"]) == (
        False,
        None,
        "changes",
    )


def test_simulating_what_is_already_deployed_changes_nothing(world: Dict[str, Any]) -> None:
    body = _simulate(world, "ledger-api", "p-1")
    assert body["alreadyDeployed"] is True and body["replaces"] == "p-1"
    assert {impact["effect"] for impact in body["impacts"]} == {"unchanged"}


def test_another_instance_keeps_the_version_it_runs(world: Dict[str, Any]) -> None:
    # p-1 stays in the unnamed instance, so Billing Service 2.0.0 still meets a provider that failed it.
    body = _simulate(world, "ledger-api", "p-2", applicationInstance="eu-1")
    assert (body["replaces"], body["applicationInstance"]) == (None, "eu-1")
    pending = _impact(body, "Billing Service", "2.0.0")
    assert pending["after"]["deployable"] is False and pending["effect"] == "unchanged"


def test_a_consumer_candidate_is_checked_against_the_running_provider(world: Dict[str, Any]) -> None:
    body = _simulate(world, "billing-service", "2.0.0")
    assert body["verdict"]["deployable"] is False
    provider = _impact(body, "Ledger API", "p-1")
    assert (provider["placement"], provider["roles"]) == ("running", ["provider"])
    # Ledger API p-1 would then serve a consumer whose pact it failed.
    assert (provider["before"]["deployable"], provider["after"]["deployable"], provider["effect"]) == (
        True,
        False,
        "breaks",
    )


def test_simulation_refusals(world: Dict[str, Any]) -> None:
    client = world["client"]
    cases = [
        ("nowhere", {"pacticipant": "ledger-api", "version": "p-2"}, 404, "pact-environment-not-found"),
        ("production", {"pacticipant": "nobody", "version": "1"}, 404, "pacticipant-not-found"),
        ("production", {"pacticipant": "ledger-api", "version": "p-9"}, 404, "pacticipant-version-not-found"),
        (
            "production",
            {"pacticipant": "ledger-api", "version": "p-2", "applicationInstance": " eu"},
            400,
            "pact-simulation-invalid",
        ),
    ]
    for environment, params, status, code in cases:
        response = client.get(f"{ENVIRONMENTS}/{environment}/simulate", params=params)
        assert (response.status_code, response.json()["detail"]["code"]) == (status, code), params


def test_nothing_of_another_tenant_is_read(world: Dict[str, Any]) -> None:
    other = {"tenant_id": world["other"]["tenant"], "user_id": None, "auth_method": "jwt"}
    from app.auth import validate_authentication
    from app.main import app

    app.dependency_overrides[validate_authentication] = lambda: other
    try:
        topology = world["client"].get(ENVIRONMENTS).json()
        history = world["client"].get(f"{ENVIRONMENTS}/production/deployments")
        simulation = world["client"].get(
            f"{ENVIRONMENTS}/production/simulate", params={"pacticipant": "ledger-api", "version": "p-2"}
        )
    finally:
        app.dependency_overrides[validate_authentication] = lambda: {
            "tenant_id": world["seed"]["tenant"],
            "user_id": None,
            "auth_method": "jwt",
        }
    assert topology == {"environments": [], "truncated": False}
    assert history.status_code == 404
    assert simulation.status_code == 404
