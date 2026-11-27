"""The provider-contract pre-publish check against a live Postgres — PFX-8.6 (#7303).

What only the real schema and the real routes prove:

* **a check persists nothing**: no pacticipant, version, contract, publication or verification
  result appears;
* **the check's verdict for a consumer pact is the one the publish then records** — for a
  passing and for a failing pact;
* the operations no pact uses are named, and a version that already published a different
  contract is reported (a publish would be ``409``);
* another workspace's provider and pacts are never read.

Runs inside one always-rolled-back transaction (the ``bdct`` fixture of ``test_bidirectional_db``).
Skipped when no database is reachable.
"""

from __future__ import annotations

import base64
import json
from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest

from app.main import app
from app.pact_broker_auth import validate_broker_authentication
from tests import test_bidirectional_db as bidirectional_db
from tests import test_pact_check_db as pact_check_db
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker
bdct = bidirectional_db.bdct

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE


@pytest.fixture
def checking(bdct: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The bi-directional stack with the check route on the same transaction."""
    with (
        patch("app.provider_contract_check_routes.db", bdct["db"]),
        patch("app.provider_contract_check_routes.enforce_permission", return_value=None),
    ):
        yield bdct


def _document(extra_path: bool = False) -> Dict[str, Any]:
    document = bidirectional_db._oas()
    if extra_path:
        document["paths"]["/invoices"] = {"delete": {"responses": {"204": {"description": "Gone"}}}}
    return document


def _check(stack: Dict[str, Any], version: str, document: Any = None) -> Dict[str, Any]:
    raw = json.dumps(document or _document()).encode()
    body = {
        "content": base64.b64encode(raw).decode(),
        "contentType": "application/json",
        "branch": "main",
        "verificationResults": bidirectional_db._PASSING_EVIDENCE,
    }
    response = stack["client"].post(f"{BASE}/contracts/provider/Ledger API/version/{version}/check", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_check_persists_nothing(checking: Dict[str, Any]) -> None:
    bidirectional_db._publish(checking, "1.0.0")
    before = pact_check_db._counts(checking)
    answer = _check(checking, "p-9")
    assert answer["results"], answer
    assert pact_check_db._counts(checking) == before


@pytest.mark.parametrize("total, success", [(1999, True), ("not a number", False)])
def test_the_check_verdict_is_the_one_the_publish_records(checking: Dict[str, Any], total: Any, success: bool) -> None:
    sha = bidirectional_db._sha(bidirectional_db._publish(checking, "1.0.0", total=total))
    checked = _check(checking, "p-1")
    [result] = checked["results"]
    assert (result["consumer"], result["consumerVersion"], result["sha"]) == ("Billing Service", "1.0.0", sha)
    assert result["success"] is success
    assert bool(result["failures"]) is not success
    assert checked["summary"]["compatible" if success else "incompatible"] == 1
    assert checked["selfVerification"]["status"] == "verified"

    bidirectional_db._contract(checking, "p-1")
    [stored] = bidirectional_db._rows(checking)
    assert (stored["success"], stored["verdict"], stored["sha"]) == (result["success"], result["verdict"], sha)


def test_unused_operations_and_a_conflicting_contract_are_reported(checking: Dict[str, Any]) -> None:
    bidirectional_db._publish(checking, "1.0.0")
    bidirectional_db._contract(checking, "p-1")
    answer = _check(checking, "p-1", document=_document(extra_path=True))
    assert answer["coverage"]["operations"] == 2
    assert answer["coverage"]["used"] == 1
    assert answer["coverage"]["unused"] == [{"method": "DELETE", "path": "/invoices", "operationId": None}]
    assert answer["existing"]["sameContent"] is False
    assert answer["summary"]["publishable"] is False

    same = _check(checking, "p-1")
    assert same["existing"]["sameContent"] is True
    assert same["summary"]["publishable"] is True


def test_another_workspace_provider_and_pacts_are_not_read(checking: Dict[str, Any]) -> None:
    bidirectional_db._publish(checking, "1.0.0")
    other = {"tenant_id": checking["other"]["tenant"], "user_id": None, "auth_method": "jwt"}
    app.dependency_overrides[validate_broker_authentication] = lambda: other
    answer = _check(checking, "p-1")
    assert answer["provider"] == {"name": "Ledger API", "exists": False}
    assert answer["results"] == []
    assert answer["existing"] is None
