"""Bi-directional verdicts in the matrix against a live Postgres — PFX-2.3 (#6927).

What only the real schema and the real routes prove (apiome-db V439):

* **either side publishing runs the comparison**: a pact published after the provider contract,
  and a contract published after the pact, each store a ``verification_result`` with
  ``kind = bidirectional`` and the comparison payload, read back like any result;
* **the matrix and can-i-deploy read it exactly as a native result** and mark its kind: a passing
  comparison lets the consumer deploy, a failing one stops it with the comparison named;
* the latest result wins whatever its kind, so a native failure after a comparison still blocks;
* **one comparison per pair**: republishing either side compares nothing again;
* **a new contract on a branch re-runs** the pacts compared with that branch's earlier contract;
* a bi-directional success does not take a pact out of pending for the provider's verifier;
* nothing crosses a tenant, and the kind's columns are kept together by the database.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_matrix_db``).
Skipped when no database is reachable or V439 is not applied.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from unittest.mock import patch

import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.provider_contract import prepare_contract
from app.provider_contract_store import publish_provider_contract
from tests import test_pact_environment_db as environment_db
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE
PAIR = publication_db.PAIR
FIXTURES = Path(__file__).parent / "fixtures" / "provider_contracts"
ACTOR = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")


@pytest.fixture
def bdct(broker: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The matrix stack, with the provider-contract routes on the same transaction."""
    broker["cursor"].execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'apiome' "
        "AND table_name = 'verification_result' AND column_name = 'kind'"
    )
    if not broker["cursor"].fetchone():
        pytest.skip("V439 not applied")
    with (
        patch("app.provider_contract_routes.db", broker["db"]),
        patch("app.provider_contract_routes.enforce_permission", return_value=None),
    ):
        yield broker


def _oas() -> Dict[str, Any]:
    return json.loads((FIXTURES / "ledger-api-3.1.json").read_bytes())


#: A passing Dredd report (PFX-2.4): the self-verification evidence every contract here carries
#: unless a test says otherwise.
_PASSING_EVIDENCE = {
    "success": True,
    "verifier": "dredd",
    "contentType": "application/xml",
    "content": base64.b64encode((FIXTURES / "evidence" / "dredd-pass.xml").read_bytes()).decode(),
}


def _contract(
    stack: Dict[str, Any],
    version: str,
    branch: str = "main",
    document: Any = None,
    evidence: Optional[Dict[str, Any]] = _PASSING_EVIDENCE,
) -> Dict[str, Any]:
    """Ledger API ``version`` publishes its provider contract; returns the response body."""
    raw = json.dumps(document or _oas()).encode()
    body: Dict[str, Any] = {
        "content": base64.b64encode(raw).decode(),
        "contentType": "application/json",
        "branch": branch,
    }
    if evidence is not None:
        body["verificationResults"] = evidence
    response = stack["client"].put(f"{BASE}/contracts/provider/Ledger API/version/{version}", json=body)
    assert response.status_code in (200, 201), response.text
    return response.json()


def _publish(stack: Dict[str, Any], version: str, total: Any = 1999, branch: str = "main") -> Dict[str, Any]:
    """Billing Service ``version`` publishes its pact; returns the publish response body."""
    document = publication_db._pact(total=total)
    response = stack["client"].post(
        f"{BASE}/contracts/publish", json=publication_db._bulk(version, document, branch=branch)
    )
    assert response.status_code == 200, response.text
    return response.json()


def _sha(body: Dict[str, Any]) -> str:
    return body["_links"]["pb:contracts"][0]["pactVersionSha"]


def _rows(stack: Dict[str, Any]) -> List[Dict[str, Any]]:
    stack["cursor"].execute(
        """
        SELECT r.kind, r.number, r.success, v.number AS provider_version, pv.sha, r.provider_branch,
               r.comparison->>'verdict' AS verdict, r.verified_by_implementation
        FROM apiome.verification_result r
        JOIN apiome.pacticipant_version v ON v.id = r.provider_version_id
        JOIN apiome.pact_version pv ON pv.id = r.pact_version_id
        WHERE r.tenant_id = %s::uuid ORDER BY r.seq
        """,
        (stack["seed"]["tenant"],),
    )
    return [dict(row) for row in stack["cursor"].fetchall()]


@pytest.fixture
def production(bdct: Dict[str, Any]) -> Dict[str, Any]:
    """A production environment where Ledger API p-1 (which published its contract) runs."""
    environment_db._create_environment(bdct, "production", production=True)
    _contract(bdct, "p-1")
    matrix_db._deploy(bdct, "Ledger API", "p-1")
    return bdct


# --- either side publishing --------------------------------------------------------------------


def test_a_pact_published_after_the_contract_is_compared_and_can_deploy(production: Dict[str, Any]) -> None:
    body = _publish(production, "1.0.0")
    assert body["comparisons"]["compared"] == 1
    [entry] = body["comparisons"]["results"]
    assert (entry["providerVersion"], entry["status"], entry["verdict"]) == ("p-1", "compared", "pass")
    assert body["notices"][-1]["type"] == "success"
    assert body["notices"][-1]["text"].startswith("Bi-directional comparison of the pact between Billing Service 1.0.0")

    [row] = _rows(production)
    assert (row["kind"], row["number"], row["success"], row["verdict"]) == ("bidirectional", 1, True, "pass")
    assert row["provider_branch"] == "main"
    assert row["verified_by_implementation"] == "Apiome bi-directional comparison"

    matrix = matrix_db._cli(production, "Billing Service", "1.0.0").json()
    assert matrix["summary"]["deployable"] is True
    assert matrix["summary"]["reason"] == "All required verification results are published and successful"
    [line] = matrix["matrix"]
    assert line["verificationResult"]["kind"] == "bidirectional"
    assert line["reason"] == {"code": "verified", "text": "verified by bi-directional comparison"}


def test_a_contract_published_after_the_pact_is_compared_and_reads_back(bdct: Dict[str, Any]) -> None:
    sha = _sha(_publish(bdct, "1.0.0"))
    assert _rows(bdct) == []
    body = _contract(bdct, "p-1")
    assert body["comparisons"]["compared"] == 1
    assert body["comparisons"]["results"][0]["pactVersionSha"] == sha

    result = bdct["client"].get(f"{PAIR}/pact-version/{sha}/verification-results/latest")
    assert result.status_code == 200, result.text
    document = result.json()
    assert document["kind"] == "bidirectional"
    assert document["success"] is True
    assert document["providerApplicationVersion"] == "p-1"
    assert document["comparison"]["verdict"] == "pass"
    assert document["comparison"]["providerContractSha"] == body["contentSha"]
    assert document["testResults"] == [
        {"interactionDescription": "a request for an invoice", "success": True, "verdict": "pass"}
    ]
    assert document["_links"]["pb:provider-contract"]["href"].endswith("/contracts/provider/ledger-api/version/p-1")


# --- PFX-2.4: self-verification evidence ---------------------------------------------------------


@pytest.fixture
def unverified(bdct: Dict[str, Any]) -> Dict[str, Any]:
    """Production runs Ledger API p-1, whose contract was published without evidence."""
    environment_db._create_environment(bdct, "production", production=True)
    body = _contract(bdct, "p-1", evidence=None)
    assert body["selfVerification"]["status"] == "missing"
    assert body["selfVerification"]["providerContractVerified"] is False
    matrix_db._deploy(bdct, "Ledger API", "p-1")
    return bdct


def test_an_unverified_contract_warns_but_deploys_under_warn(unverified: Dict[str, Any]) -> None:
    with patch("app.bidirectional_store.settings.pact_unverified_provider_contract", "warn"):
        body = _publish(unverified, "1.0.0")
    [entry] = body["comparisons"]["results"]
    assert (entry["verdict"], entry["success"]) == ("unverified", True)
    assert body["notices"][-1]["type"] == "warning"
    [row] = _rows(unverified)
    assert (row["success"], row["verdict"]) == (True, "unverified")

    matrix = matrix_db._cli(unverified, "Billing Service", "1.0.0").json()
    assert matrix["summary"]["deployable"] is True
    [line] = matrix["matrix"]
    assert line["verificationResult"]["providerContractVerified"] is False
    assert line["reason"]["text"] == "verified by bi-directional comparison; provider contract unverified"
    assert any(notice.get("code") == "provider-contract-unverified" for notice in matrix["notices"])


def test_an_unverified_contract_stops_the_deploy_under_fail(unverified: Dict[str, Any]) -> None:
    with patch("app.bidirectional_store.settings.pact_unverified_provider_contract", "fail"):
        body = _publish(unverified, "1.0.0")
    assert body["comparisons"]["results"][0]["success"] is False
    assert body["notices"][-1]["type"] == "error"
    matrix = matrix_db._cli(unverified, "Billing Service", "1.0.0").json()
    assert matrix["summary"]["deployable"] is False
    assert matrix["matrix"][0]["reason"]["text"] == "bi-directional comparison failed: provider contract unverified"


def test_a_failing_self_verification_is_recorded_with_its_digest(bdct: Dict[str, Any]) -> None:
    raw = (FIXTURES / "evidence" / "schemathesis-fail.junit.xml").read_bytes()
    evidence = {
        "success": True,
        "verifier": "schemathesis",
        "contentType": "application/xml",
        "content": base64.b64encode(raw).decode(),
    }
    body = _contract(bdct, "p-1", evidence=evidence)
    verification = body["selfVerification"]
    assert (verification["status"], verification["kind"], verification["tool"]) == ("failed", "junit", "schemathesis")
    assert verification["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    again = bdct["client"].get(f"{BASE}/contracts/provider/Ledger API/version/p-1").json()
    assert again["selfVerification"] == verification


def test_a_contract_published_before_evidence_republishes_as_the_same(bdct: Dict[str, Any]) -> None:
    # A PFX-2.1 publication stored no `evidence`; publishing the same results again is still a no-op.
    _contract(bdct, "p-1")
    bdct["cursor"].execute(
        "UPDATE apiome.provider_contract_publication SET verification_results = verification_results - 'evidence' "
        "WHERE tenant_id = %s::uuid",
        (bdct["seed"]["tenant"],),
    )
    raw = json.dumps(_oas()).encode()
    response = bdct["client"].put(
        f"{BASE}/contracts/provider/Ledger API/version/p-1",
        json={
            "content": base64.b64encode(raw).decode(),
            "contentType": "application/json",
            "branch": "main",
            "verificationResults": _PASSING_EVIDENCE,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["selfVerification"]["status"] == "verified"


def test_a_failing_comparison_stops_the_deploy_and_says_why(production: Dict[str, Any]) -> None:
    body = _publish(production, "1.0.0", total="lots")
    assert body["comparisons"]["results"][0]["verdict"] == "fail"
    assert body["notices"][-1]["type"] == "error"
    matrix = matrix_db._cli(production, "Billing Service", "1.0.0").json()
    assert matrix["summary"]["deployable"] is False
    assert matrix["summary"]["reason"] == (
        "The bi-directional comparison of the pact between version 1.0.0 of Billing Service and the version "
        "of Ledger API currently in production (p-1) with its provider contract failed"
    )
    assert matrix["notices"][-1]["code"] == "verification-failed"
    assert matrix["matrix"][0]["reason"] == {"code": "verification-failed", "text": "bi-directional comparison failed"}


def test_the_latest_result_wins_whatever_its_kind(production: Dict[str, Any]) -> None:
    sha = _sha(_publish(production, "1.0.0"))
    matrix_db._verify(production, sha, "p-1", False)
    matrix = matrix_db._cli(production, "Billing Service", "1.0.0").json()
    assert matrix["summary"]["deployable"] is False
    [line] = matrix["matrix"]
    assert line["verificationResult"]["kind"] == "native"
    assert [row["kind"] for row in _rows(production)] == ["bidirectional", "native"]
    assert [row["number"] for row in _rows(production)] == [1, 2]


# --- one comparison per pair, and the re-run ---------------------------------------------------


def test_republishing_either_side_compares_nothing_again(production: Dict[str, Any]) -> None:
    _publish(production, "1.0.0")
    again = _contract(production, "p-1")
    assert (again["comparisons"]["compared"], again["comparisons"]["alreadyCompared"]) == (0, 1)
    # A new consumer version with the same content is the same pact version: already compared.
    same = _publish(production, "1.0.1")
    assert same["comparisons"]["results"][0]["status"] == "already-compared"
    assert not any(n["text"].startswith("Bi-directional") for n in same["notices"])
    assert len(_rows(production)) == 1


def test_a_new_contract_on_the_branch_re_runs_the_pacts_compared_before(bdct: Dict[str, Any]) -> None:
    old = _sha(_publish(bdct, "1.0.0", total=1))
    _contract(bdct, "p-1")
    new = _sha(_publish(bdct, "2.0.0", total=2))
    assert {(row["sha"], row["provider_version"]) for row in _rows(bdct)} == {(old, "p-1"), (new, "p-1")}

    changed = _oas()
    changed["info"]["version"] = "1.5.0"
    body = _contract(bdct, "p-2", document=changed)
    compared = {(entry["pactVersionSha"], entry["status"]) for entry in body["comparisons"]["results"]}
    # 2.0.0 is the consumer's main-branch head; 1.0.0 was compared with p-1 on main, so it re-runs.
    assert compared == {(new, "compared"), (old, "compared")}
    assert {(row["sha"], row["provider_version"]) for row in _rows(bdct)} == {
        (old, "p-1"),
        (new, "p-1"),
        (old, "p-2"),
        (new, "p-2"),
    }


# --- pending, tenancy and the schema -----------------------------------------------------------


def test_a_comparison_does_not_take_a_pact_out_of_pending(bdct: Dict[str, Any]) -> None:
    _contract(bdct, "p-1")
    _publish(bdct, "1.0.0")
    assert _rows(bdct)[0]["success"] is True
    listed = bdct["client"].post(
        f"{BASE}/pacts/provider/ledger-api/for-verification",
        json={"consumerVersionSelectors": [{"latest": True}], "includePendingStatus": True},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["_embedded"]["pacts"][0]["verificationProperties"]["pending"] is True


def test_another_workspace_s_contract_is_never_compared(bdct: Dict[str, Any]) -> None:
    other = bdct["other"]["tenant"]
    publish_provider_contract(
        bdct["db"],
        other,
        provider_name="Ledger API",
        version_number="p-1",
        contract=prepare_contract(_oas(), content_type="application/json"),
        actor=ACTOR,
        branch="main",
    )
    body = _publish(bdct, "1.0.0")
    assert "comparisons" not in body
    assert _rows(bdct) == []


def test_the_database_keeps_a_kind_s_columns_together_and_one_comparison_per_pair(
    production: Dict[str, Any],
) -> None:
    _publish(production, "1.0.0")
    cursor = production["cursor"]

    def refused(sql: str) -> type:
        cursor.execute("SAVEPOINT shape")
        try:
            cursor.execute(sql)
        except psycopg2.Error as exc:
            cursor.execute("ROLLBACK TO SAVEPOINT shape")
            return type(exc)
        raise AssertionError("the statement was accepted")

    copy = """
        INSERT INTO apiome.verification_result (tenant_id, consumer_id, provider_id, pact_version_id,
            provider_version_id, number, success, kind, provider_contract_id, comparison)
        SELECT tenant_id, consumer_id, provider_id, pact_version_id, provider_version_id, number + 10, success,
               {kind}, {contract}, {comparison}
        FROM apiome.verification_result WHERE kind = 'bidirectional'
    """
    assert refused(copy.format(kind="'native'", contract="provider_contract_id", comparison="comparison")) is (
        psycopg2.errors.CheckViolation
    )
    assert refused(copy.format(kind="'bidirectional'", contract="NULL", comparison="comparison")) is (
        psycopg2.errors.CheckViolation
    )
    assert refused(copy.format(kind="'bidirectional'", contract="provider_contract_id", comparison="comparison")) is (
        psycopg2.errors.UniqueViolation
    )
    assert refused("UPDATE apiome.verification_result SET comparison = '{}'::jsonb") is (
        psycopg2.errors.RestrictViolation
    )
