"""Verification-result publication against a live Postgres — PFX-1.4 (#6917).

What only the real schema and the real routes prove (apiome-db V434):

* the Pact verifier's whole flow works: fetch the pacts for verification, follow the pact's
  ``pb:provider`` to record the provider branch with ``pb:branch-version``, then post the result to
  ``pb:publish-verification-results`` — and the result records the branch and the pending flag;
* results are numbered 1, 2 … per pact version, the latest is the last published, and a failed
  result keeps its test detail;
* a result never changes, and it goes when its pact version goes;
* a CTG-4.3 report is linked, not copied: only this workspace's reports can be linked, and
  deleting the report clears the link and keeps the result.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of
``test_pact_publication_db``). Skipped when no database is reachable or V434 is not applied.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterator
from unittest.mock import patch

import psycopg2
import pytest

from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

BASE = publication_db.BASE
PROVIDER = f"{BASE}/pacts/provider/ledger-api"

_FAILED = {
    "success": False,
    "providerApplicationVersion": "p-1",
    "buildUrl": "https://ci.example.com/builds/77",
    "testResults": [
        {
            "interactionId": "a1",
            "interactionDescription": "a request for an invoice",
            "success": False,
            "mismatches": [{"attribute": "status", "description": "expected 200 but was 404"}],
        }
    ],
    "verifiedBy": {"implementation": "Pact-Rust", "version": "1.2.0"},
}


@pytest.fixture
def broker(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The publication stack, with the verification routes on the same transaction."""
    stack["cursor"].execute("SELECT to_regclass('apiome.verification_result') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V434 not applied")
    with (
        patch("app.pact_broker_verification_routes.db", stack["db"]),
        patch("app.pact_broker_verification_routes.enforce_permission", return_value=None),
    ):
        yield stack


def _path(href: str) -> str:
    """The path of an absolute link, for the test client."""
    return href[href.index("/v1/") :]


@pytest.fixture
def published(broker: Dict[str, Any]) -> Dict[str, Any]:
    """Billing Service 1.0.0 on main published its pact for Ledger API."""
    response = broker["client"].post(
        f"{BASE}/contracts/publish", json=publication_db._bulk("1.0.0", publication_db._pact(), branch="main")
    )
    assert response.status_code == 200, response.text
    return broker


def _verify_like_pact_core(stack: Dict[str, Any], body: Dict[str, Any], branch: str = "main") -> Dict[str, Any]:
    """What a Pact verifier does: fetch, follow the links, record the branch, publish."""
    client = stack["client"]
    listed = client.post(
        f"{PROVIDER}/for-verification",
        json={"consumerVersionSelectors": [{"latest": True}], "includePendingStatus": True},
    )
    assert listed.status_code == 200, listed.text
    pact = client.get(_path(listed.json()["_embedded"]["pacts"][0]["_links"]["self"]["href"]))
    assert pact.status_code == 200, pact.text
    links = pact.json()["_links"]
    provider = client.get(_path(links["pb:provider"]["href"])).json()
    template = provider["_links"]["pb:branch-version"]["href"]
    recorded = client.put(
        _path(template.replace("{branch}", branch).replace("{version}", body["providerApplicationVersion"])), json={}
    )
    assert recorded.status_code in (200, 201), recorded.text
    response = client.post(_path(links["pb:publish-verification-results"]["href"]), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def _count(stack: Dict[str, Any]) -> int:
    stack["cursor"].execute(
        "SELECT count(*) AS n FROM apiome.verification_result WHERE tenant_id = %s::uuid", (stack["seed"]["tenant"],)
    )
    return int(stack["cursor"].fetchone()["n"])


def test_the_verifier_flow_publishes_a_result_with_branch_and_pending(published: Dict[str, Any]) -> None:
    result = _verify_like_pact_core(published, _FAILED)
    assert result["success"] is False
    assert result["providerApplicationVersion"] == "p-1"
    assert result["providerVersionBranch"] == "main"
    assert result["testResults"] == _FAILED["testResults"]
    assert result["verifiedBy"] == {"implementation": "Pact-Rust", "version": "1.2.0"}
    assert result["_links"]["self"]["href"].endswith("/verification-results/1")
    published["cursor"].execute(
        "SELECT pact_pending, wip, provider_branch FROM apiome.verification_result WHERE tenant_id = %s::uuid",
        (published["seed"]["tenant"],),
    )
    row = published["cursor"].fetchone()
    assert (row["pact_pending"], row["wip"], row["provider_branch"]) == (True, False, "main")


def test_results_are_numbered_and_the_latest_is_the_last(published: Dict[str, Any]) -> None:
    first = _verify_like_pact_core(published, _FAILED)
    second = _verify_like_pact_core(
        published, {"success": True, "providerApplicationVersion": "p-2", "testResults": []}, branch="feat/x"
    )
    assert first["_links"]["self"]["href"].endswith("/1")
    assert second["_links"]["self"]["href"].endswith("/2")
    assert second["providerVersionBranch"] == "feat/x"
    client = published["client"]
    latest = client.get(_path(second["_links"]["pb:pact-version"]["href"]) + "/verification-results/latest")
    assert latest.json()["providerApplicationVersion"] == "p-2"
    # The failed result keeps its detail.
    one = client.get(_path(first["_links"]["self"]["href"]))
    assert one.status_code == 200
    assert one.json()["testResults"][0]["mismatches"][0]["description"] == "expected 200 but was 404"
    assert client.get(_path(first["_links"]["self"]["href"])[:-1] + "9").status_code == 404


def test_a_result_for_an_unknown_pact_version_is_a_404_and_stores_nothing(published: Dict[str, Any]) -> None:
    response = published["client"].post(
        f"{PROVIDER}/consumer/billing-service/pact-version/{'0' * 64}/verification-results", json=_FAILED
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "pact-not-found"
    assert _count(published) == 0


def test_a_result_never_changes_and_goes_with_its_pact(published: Dict[str, Any]) -> None:
    _verify_like_pact_core(published, _FAILED)
    cursor = published["cursor"]
    cursor.execute("SAVEPOINT immutable")
    with pytest.raises(psycopg2.Error) as caught:
        cursor.execute(
            "UPDATE apiome.verification_result SET success = TRUE WHERE tenant_id = %s::uuid",
            (published["seed"]["tenant"],),
        )
    assert "immutable" in str(caught.value)
    cursor.execute("ROLLBACK TO SAVEPOINT immutable")
    assert published["client"].delete("/v1/tenants/t/pacticipants/billing-service").status_code in (200, 204)
    assert _count(published) == 0


def _report(cursor: Any, tenant: str) -> str:
    """A minimal passed CTG-4.3 run and its conformance report, for ``tenant``."""
    run_id, report_id = str(uuid.uuid4()), str(uuid.uuid4())
    cursor.execute(
        """
        INSERT INTO apiome.verification_run (
            id, tenant_id, suite_digest, target_slug, target_environment, target_base_url, runner_name,
            started_at, finished_at, duration_ms, outcome
        )
        VALUES (%s::uuid, %s::uuid, 'sha256:' || repeat('a', 64), 'staging', 'staging',
                'https://staging.example.com', 'test', now(), now(), 0, 'passed')
        """,
        (run_id, tenant),
    )
    cursor.execute(
        """
        INSERT INTO apiome.provider_verification_report (
            id, tenant_id, run_id, version_ref, suite_digest, target_slug, target_environment,
            target_base_url, outcome
        )
        VALUES (%s::uuid, %s::uuid, %s::uuid, 'project/ledger/1.0.0', 'sha256:' || repeat('a', 64),
                'staging', 'staging', 'https://staging.example.com', 'passed')
        """,
        (report_id, tenant, run_id),
    )
    return report_id


def test_a_ctg_report_is_linked_not_copied(published: Dict[str, Any]) -> None:
    cursor = published["cursor"]
    mine = _report(cursor, published["seed"]["tenant"])
    theirs = _report(cursor, published["other"]["tenant"])

    listed = published["client"].post(
        f"{PROVIDER}/for-verification", json={"consumerVersionSelectors": [{"latest": True}]}
    )
    sha_path = _path(listed.json()["_embedded"]["pacts"][0]["_links"]["self"]["href"])
    publish_at = _path(published["client"].get(sha_path).json()["_links"]["pb:publish-verification-results"]["href"])

    other = published["client"].post(publish_at, json={**_FAILED, "providerVerificationReportId": theirs})
    assert other.status_code == 422
    assert other.json()["detail"]["code"] == "pact-verification-report-not-found"
    assert _count(published) == 0

    linked = published["client"].post(publish_at, json={**_FAILED, "providerVerificationReportId": mine})
    assert linked.status_code == 201, linked.text
    assert linked.json()["_links"]["pb:provider-verification-report"]["href"].endswith(
        f"/provider-verifications/{mine}"
    )

    # Deleting the report keeps the result and clears only the link.
    cursor.execute("DELETE FROM apiome.provider_verification_report WHERE id = %s::uuid", (mine,))
    cursor.execute(
        "SELECT provider_verification_report_id, success FROM apiome.verification_result WHERE tenant_id = %s::uuid",
        (published["seed"]["tenant"],),
    )
    row = cursor.fetchone()
    assert row["provider_verification_report_id"] is None and row["success"] is False


def test_branch_and_tag_puts_create_the_pacticipant_and_version(broker: Dict[str, Any]) -> None:
    client = broker["client"]
    created = client.put(f"{BASE}/pacticipants/Inventory%20API/branches/feat/x/versions/9a8b", json={})
    assert created.status_code == 201, created.text
    assert created.json()["_embedded"]["branchVersions"] == [{"name": "feat/x"}]
    again = client.put(f"{BASE}/pacticipants/inventory-api/versions/9a8b/tags/prod", json={})
    assert again.status_code == 200, again.text
    assert again.json()["_embedded"]["tags"] == [{"name": "prod"}]
    assert client.get(f"{BASE}/pacticipants/inventory-api").json()["name"] == "Inventory API"
    unknown_id = client.put(f"{BASE}/pacticipants/{uuid.uuid4()}/versions/1/tags/prod", json={})
    assert unknown_id.status_code == 404
    assert unknown_id.json()["detail"]["code"] == "pacticipant-not-found"
