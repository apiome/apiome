"""The what-is-where board, the history, undeployment and support-ended against a live Postgres — PFX-8.13 (#7310).

Starts from the PFX-5.7 story (:func:`tests.test_pact_deployments_db.world`):

* **production** runs Billing Service 1.0.0 and Ledger API p-1; **staging** runs 2.0.0 and p-2;
* p-1 failed pact B (Billing Service 2.0.0), so 2.0.0 cannot go to production; p-2 can.

The board lists staging before production (promotion order), offers 2.0.0 and p-2 as each row's
*next* version for production, and every verdict on it equals the deploy simulator's for the same
question. Recording stores can-i-deploy's answer at the time (V455); undeploying and ending support
store who did it, and the history tells each event once.

Skipped when no database is reachable or V455 is not applied.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from tests import test_pact_deployments_db as deployments_db
from tests import test_pact_environment_db as environment_db
from tests import test_pact_matrix_db as matrix_db

tx = deployments_db.tx
stack = deployments_db.stack
broker = deployments_db.broker
world = deployments_db.world

pytestmark = pytest.mark.requires_db

ENVIRONMENTS = deployments_db.ENVIRONMENTS


@pytest.fixture(autouse=True)
def _needs_v455(broker: Dict[str, Any]) -> None:
    broker["cursor"].execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'apiome' "
        "AND table_name = 'deployed_version' AND column_name = 'recorded_verdict'"
    )
    if not broker["cursor"].fetchone():
        pytest.skip("V455 not applied")


def _board(stack: Dict[str, Any]) -> Dict[str, Any]:
    response = stack["client"].get(f"{ENVIRONMENTS}/board")
    assert response.status_code == 200, response.text
    return response.json()


def _row(board: Dict[str, Any], name: str) -> Dict[str, Any]:
    return next(row for row in board["rows"] if row["pacticipant"]["name"] == name)


def _cell(board: Dict[str, Any], row: Dict[str, Any], environment: str) -> Dict[str, Any]:
    index = [e["name"] for e in board["environments"]].index(environment)
    return row["cells"][index]


def _history(stack: Dict[str, Any], **params: Any) -> Dict[str, Any]:
    response = stack["client"].get(f"{ENVIRONMENTS}/history", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _deployed_rows(stack: Dict[str, Any]) -> List[Dict[str, Any]]:
    return environment_db._rows(stack, "deployed_version")


# --- Board ---------------------------------------------------------------------------------------


def test_the_board_lists_non_production_first_and_offers_the_next_version(world: Dict[str, Any]) -> None:
    board = _board(world)
    assert [e["name"] for e in board["environments"]] == ["staging", "production"]
    assert board["truncated"] is False and board["notChecked"] == 0

    billing = _row(board, "Billing Service")
    production = _cell(board, billing, "production")
    assert [(v["version"], v["verdict"]["deployable"]) for v in production["deployed"]] == [("1.0.0", True)]
    assert production["next"]["version"] == "2.0.0"
    assert production["next"]["from"] == "staging"
    assert production["next"]["verdict"]["deployable"] is False

    ledger = _row(board, "Ledger API")
    assert _cell(board, ledger, "production")["next"]["version"] == "p-2"
    assert _cell(board, ledger, "production")["next"]["verdict"]["deployable"] is True
    # Nothing to the left of the first column.
    assert _cell(board, ledger, "staging")["next"] is None


def test_each_next_verdict_is_the_simulators_answer(world: Dict[str, Any]) -> None:
    board = _board(world)
    for name, version in (("Billing Service", "2.0.0"), ("Ledger API", "p-2")):
        cell = _cell(board, _row(board, name), "production")
        simulated = deployments_db._simulate(world, name, version)
        assert cell["next"]["verdict"]["deployable"] == simulated["verdict"]["deployable"]
        assert cell["next"]["verdict"]["reason"] == simulated["verdict"]["reason"]


def test_an_over_budget_board_says_what_it_did_not_check(world: Dict[str, Any]) -> None:
    from app import pact_environment_board

    board = pact_environment_board.read_board(world["db"], world["seed"]["tenant"], max_checks=1)
    assert board.checks == 1
    assert board.not_checked > 0
    reasons = [
        version.not_checked
        for row in board.rows
        for cell in row.cells
        for version in cell.deployed
        if version.check is None
    ]
    assert reasons and all("Only 100 versions are checked" in reason for reason in reasons)


def test_a_pacticipant_with_nothing_anywhere_is_an_idle_row(world: Dict[str, Any]) -> None:
    matrix_db._provider_version(world, "x-1")  # Ledger API exists; add a brand-new pacticipant instead.
    world["cursor"].execute(
        "INSERT INTO apiome.pacticipant (tenant_id, slug, name) VALUES (%s::uuid, 'mobile-app', 'Mobile App')",
        (world["seed"]["tenant"],),
    )
    row = _row(_board(world), "Mobile App")
    assert row["idle"] is True
    assert all(cell["deployed"] == [] and cell["next"] is None for cell in row["cells"])


# --- Recording keeps the verdict and the actor ------------------------------------------------------


def test_a_deployment_stores_the_verdict_at_the_time_and_what_it_replaced(world: Dict[str, Any]) -> None:
    matrix_db._deploy(world, "Billing Service", "2.0.0", "production")  # can-i-deploy said no.
    rows = [r for r in _deployed_rows(world) if r["currently_deployed"] or r["ended_reason"]]
    newest = rows[-1]
    assert newest["recorded_verdict"] == "not-deployable"
    replaced = next(r for r in rows if r["id"] == newest["replaced_id"])
    assert (replaced["currently_deployed"], replaced["ended_reason"]) == (False, "replaced")

    matrix_db._deploy(world, "Ledger API", "p-2", "production")  # can-i-deploy said yes.
    assert _deployed_rows(world)[-1]["recorded_verdict"] == "deployable"


def test_an_undeployment_is_kept_with_who_did_it(world: Dict[str, Any]) -> None:
    responses = environment_db._undeploy(world, "Ledger API", "production")
    assert [r.status_code for r in responses] == [200]
    ended = next(r for r in _deployed_rows(world) if r["ended_reason"] == "undeployed")
    assert ended["currently_deployed"] is False and ended["undeployed_at"] is not None

    board = _board(world)
    assert _cell(board, _row(board, "Ledger API"), "production")["deployed"] == []


def test_ending_support_removes_the_version_from_can_i_deploys_required_set(world: Dict[str, Any]) -> None:
    # Billing Service 2.0.0 released to production: p-1 failed its pact, so p-1 is not deployable there.
    environment_db._record(world, "pb:record-release", "Billing Service", "2.0.0", "production")
    assert deployments_db._can_i_deploy(world, "Ledger API", "p-1") is False

    env = environment_db._environment_resource(world, "production")
    supported = world["client"].get(
        environment_db._path(env["_links"]["pb:currently-supported-released-versions"]["href"]),
        params={"pacticipant": "Billing Service", "version": "2.0.0"},
    )
    entry = supported.json()["_embedded"]["releasedVersions"][0]
    ended = world["client"].patch(
        environment_db._path(entry["_links"]["self"]["href"]), json={"currentlySupported": False}
    )
    assert ended.status_code == 200
    assert deployments_db._can_i_deploy(world, "Ledger API", "p-1") is True


# --- History -------------------------------------------------------------------------------------


def test_the_history_tells_each_event_once(world: Dict[str, Any]) -> None:
    matrix_db._deploy(world, "Ledger API", "p-2", "production")  # replaces p-1
    environment_db._undeploy(world, "Billing Service", "staging")
    environment_db._record(world, "pb:record-release", "Billing Service", "1.0.0", "production")

    events = _history(world)["events"]
    kinds = sorted((e["kind"], e["pacticipant"]["name"], e["version"], e["environment"]["name"]) for e in events)
    assert kinds == [
        ("deployed", "Billing Service", "1.0.0", "production"),
        ("deployed", "Billing Service", "2.0.0", "staging"),
        ("deployed", "Ledger API", "p-1", "production"),
        ("deployed", "Ledger API", "p-2", "production"),
        ("deployed", "Ledger API", "p-2", "staging"),
        ("released", "Billing Service", "1.0.0", "production"),
        ("undeployed", "Billing Service", "2.0.0", "staging"),
    ]
    replacing = next(
        e
        for e in events
        if e["kind"] == "deployed" and e["version"] == "p-2" and e["environment"]["name"] == "production"
    )
    assert replacing["replaces"] == "p-1"
    assert replacing["verdict"] == "deployable"


def test_the_history_narrows_and_pages_without_losing_an_event(world: Dict[str, Any]) -> None:
    only = _history(world, environment="staging")["events"]
    assert {e["environment"]["name"] for e in only} == {"staging"}
    ledger = _history(world, pacticipant="Ledger API")["events"]
    assert {e["pacticipant"]["name"] for e in ledger} == {"Ledger API"}

    seen: List[str] = []
    page = _history(world, limit=1)
    while True:
        seen += [f"{e['kind']}:{e['uuid']}" for e in page["events"]]
        if not page["nextCursor"]:
            break
        page = _history(world, limit=1, cursor=page["nextCursor"])
    everything = [f"{e['kind']}:{e['uuid']}" for e in _history(world)["events"]]
    assert seen == everything
    assert len(seen) == 4


def test_the_history_refuses_a_bad_cursor_and_unknown_filters(world: Dict[str, Any]) -> None:
    assert world["client"].get(f"{ENVIRONMENTS}/history", params={"cursor": "nope"}).status_code == 400
    assert world["client"].get(f"{ENVIRONMENTS}/history", params={"environment": "moon"}).status_code == 404
    assert world["client"].get(f"{ENVIRONMENTS}/history", params={"pacticipant": "Nobody"}).status_code == 404


def test_the_guard_still_refuses_reviving_a_deployment(world: Dict[str, Any]) -> None:
    import psycopg2

    environment_db._undeploy(world, "Ledger API", "production")
    ended = next(r for r in _deployed_rows(world) if r["ended_reason"] == "undeployed")
    world["cursor"].execute("SAVEPOINT guard")
    with pytest.raises(psycopg2.Error):
        world["cursor"].execute(
            "UPDATE apiome.deployed_version SET ended_actor_label = 'someone else' WHERE id = %s", (ended["id"],)
        )
    world["cursor"].execute("ROLLBACK TO SAVEPOINT guard")
