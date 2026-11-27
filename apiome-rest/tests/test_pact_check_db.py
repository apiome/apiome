"""The pre-publish pact check against a live Postgres — PFX-8.4 (#7301).

What only the real schema and the real routes prove:

* **a check persists nothing**: no pacticipant, version, pact, publication, verification result,
  contract or audit row appears, whatever the selectors name;
* **the check's verdict for a version is the one a publish then records** against it — for a
  passing and for a failing pact;
* ``main``, ``deployed:<env>`` and ``version:<n>`` resolve to the right provider versions, a
  version two selectors name is compared once, and selectors that name nothing are reported with
  a reason;
* another workspace's provider is not found.

Runs inside one always-rolled-back transaction (the ``bdct`` fixture of ``test_bidirectional_db``).
Skipped when no database is reachable.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List
from unittest.mock import patch

import pytest

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from tests import test_bidirectional_db as bidirectional_db
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker
bdct = bidirectional_db.bdct
production = bidirectional_db.production

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE

#: Every table a check could conceivably write, counted for the test's tenants.
_TABLES = (
    "pacticipant",
    "pacticipant_version",
    "pacticipant_branch",
    "pact_version",
    "pact_publication",
    "verification_result",
    "provider_contract",
    "provider_contract_publication",
    "pact_environment",
    "deployed_version",
)


@pytest.fixture
def checking(production: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The production stack with the check route on the same transaction."""
    with (
        patch("app.pact_check_routes.db", production["db"]),
        patch("app.pact_check_routes.enforce_permission", return_value=None),
    ):
        yield production


def _counts(stack: Dict[str, Any]) -> Dict[str, int]:
    """Row counts per table for both tenants, and the audit rows written since the test began."""
    tenants = [stack["seed"]["tenant"], stack["other"]["tenant"]]
    counts: Dict[str, int] = {}
    for table in _TABLES:
        stack["cursor"].execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'apiome' "
            "AND table_name = %s AND column_name = 'tenant_id'",
            (table,),
        )
        if stack["cursor"].fetchone():
            stack["cursor"].execute(
                f"SELECT count(*) AS n FROM apiome.{table} WHERE tenant_id = ANY(%s::uuid[])", (tenants,)
            )
        else:
            stack["cursor"].execute(f"SELECT count(*) AS n FROM apiome.{table}")
        counts[table] = int(stack["cursor"].fetchone()["n"])
    stack["cursor"].execute("SELECT to_regclass('apiome.access_audit') AS t")
    if stack["cursor"].fetchone()["t"]:
        stack["cursor"].execute("SELECT count(*) AS n FROM apiome.access_audit")
        counts["access_audit"] = int(stack["cursor"].fetchone()["n"])
    return counts


def _check(stack: Dict[str, Any], against: List[str], total: Any = 1999) -> Dict[str, Any]:
    response = stack["client"].post(
        f"{BASE}/pacts/check", json={"pact": publication_db._pact(total=total), "against": against}
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_a_check_persists_nothing(checking: Dict[str, Any]) -> None:
    before = _counts(checking)
    answer = _check(checking, ["version:p-1", "deployed:production", "deployed:staging", "main"])
    assert answer["results"], answer
    assert _counts(checking) == before


@pytest.mark.parametrize("total, success", [(1999, True), ("not a number", False)])
def test_the_check_verdict_is_the_one_a_publish_records(checking: Dict[str, Any], total: Any, success: bool) -> None:
    checked = _check(checking, ["version:p-1"], total=total)
    [result] = checked["results"]
    assert result["success"] is success

    bidirectional_db._publish(checking, "c-1", total=total)
    [stored] = [row for row in bidirectional_db._rows(checking) if row["provider_version"] == "p-1"]
    assert stored["kind"] == "bidirectional"
    assert stored["success"] == result["success"]
    assert stored["verdict"] == result["verdict"]
    assert stored["sha"] == checked["pactVersionSha"]


def test_selectors_resolve_and_a_version_named_twice_is_compared_once(checking: Dict[str, Any]) -> None:
    answer = _check(checking, ["main", "deployed:production", "version:p-1"])
    [result] = answer["results"]
    assert result["providerVersion"] == "p-1"
    assert result["selectors"] == ["main", "deployed:production", "version:p-1"]
    assert result["reasons"] == ["main branch main", "deployed to production", "version p-1"]
    assert result["counts"] == {"match": 1, "differs": 0, "notInSpec": 0}
    assert answer["summary"]["success"] is True


def test_selectors_that_name_nothing_are_reported(checking: Dict[str, Any]) -> None:
    checking["cursor"].execute(
        "UPDATE apiome.pacticipant SET main_branch = NULL WHERE tenant_id = %s::uuid AND slug = 'ledger-api'",
        (checking["seed"]["tenant"],),
    )
    answer = _check(checking, ["main", "deployed:staging", "version:9.9.9", "draft:latest"])
    assert answer["results"] == []
    reasons = {entry["selector"]: entry["reason"] for entry in answer["unresolved"]}
    assert "no main branch" in reasons["main"]
    assert "'staging'" in reasons["deployed:staging"]
    assert "'9.9.9'" in reasons["version:9.9.9"]
    assert "not bound to an Apiome project" in reasons["draft:latest"]
    assert answer["summary"]["success"] is False


def test_another_workspace_provider_is_not_found(checking: Dict[str, Any]) -> None:
    other = {"tenant_id": checking["other"]["tenant"], "user_id": None, "auth_method": "jwt"}
    app.dependency_overrides[validate_broker_authentication] = lambda: other
    answer = _check(checking, ["version:p-1"])
    assert answer["provider"]["registered"] is False
    assert answer["results"] == []
    assert "not registered" in answer["unresolved"][0]["reason"]
