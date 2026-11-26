"""Verification results and operations against a live Postgres — PFX-5.5 (#6949).

What only the real schema proves (apiome-db V444):

* a result a Pact verifier publishes records ``trigger: published`` and reads back with it; the
  database refuses a trigger outside the closed list and a negative duration;
* a stored result carries the hosted run's duration and evidence run id;
* the status read marks a consumer's newest pact stale until its pact version has a result, and a
  new pact version is stale again;
* the history is newest first, pages by cursor, narrows by consumer, and never shows another
  tenant's results; one result is read only through its own provider and tenant;
* the routes answer the same over HTTP.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_matrix_db``).
Skipped when no database is reachable or V444 is not applied.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import patch

import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_publication import PactPublicationError
from app.pact_verification_ops import list_results, verification_status
from app.pacticipant_store import get_pacticipant
from app.verification_result import VerificationRequest
from app.verification_result_store import get_provider_result, publish_verification_result
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ops@example.com", kind="user")
_OPS = "/v1/tenants/t/pact-verifier/pacts/provider/ledger-api"
_EVIDENCE = "55555555-5555-4555-8555-555555555555"


@pytest.fixture
def ops(broker: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The matrix stack with the verification operations routes on the same transaction."""
    broker["cursor"].execute(
        "SELECT 1 FROM information_schema.columns WHERE table_schema = 'apiome' "
        "AND table_name = 'verification_result' AND column_name = 'trigger'"
    )
    if not broker["cursor"].fetchone():
        pytest.skip("V444 not applied")
    with (
        patch("app.pact_verification_ops_routes.db", broker["db"]),
        patch("app.pact_verification_ops_routes.enforce_permission", return_value=None),
        patch("app.pact_verification_ops_routes.has_permission", return_value=False),
    ):
        yield broker


def _hosted(ops: Dict[str, Any], sha: str, version: str, success: bool) -> str:
    """Store a hosted-verifier result directly (the store call the verifier makes); returns its id."""
    record = publish_verification_result(
        ops["db"],
        ops["seed"]["tenant"],
        "ledger-api",
        "billing-service",
        sha,
        VerificationRequest(
            success=success,
            provider_version=version,
            test_results=[{"interactionDescription": "a request for an invoice", "success": success}],
            verified_by={"implementation": "apiome-pact-verifier", "version": "1"},
        ),
        actor=ACTOR,
        trigger="manual",
        duration_ms=1840,
        evidence_run_id=_EVIDENCE,
    )
    return record.id


def test_a_verifier_result_records_trigger_published(ops: Dict[str, Any]) -> None:
    sha = matrix_db._publish(ops, "1.0.0", branch="main")
    matrix_db._verify(ops, sha, "p-1", True)
    page = list_results(ops["db"], ops["seed"]["tenant"], "ledger-api")
    (result,) = page.results
    assert (result.trigger, result.duration_ms, result.evidence_run_id) == ("published", None, None)
    assert (result.provider_version, result.success, result.counts.total) == ("p-1", True, 0)


def test_a_hosted_result_keeps_its_duration_and_evidence_run(ops: Dict[str, Any]) -> None:
    sha = matrix_db._publish(ops, "1.0.0", branch="main")
    result_id = _hosted(ops, sha, "p-2", False)
    provider = get_pacticipant(ops["db"], ops["seed"]["tenant"], "ledger-api")
    record = get_provider_result(ops["db"], ops["seed"]["tenant"], provider, result_id)
    assert (record.trigger, record.duration_ms, record.evidence_run_id) == ("manual", 1840, _EVIDENCE)
    assert record.seq is not None and record.success is False


@pytest.mark.parametrize(
    ("column", "value"),
    [("trigger", "nightly"), ("duration_ms", -1)],
)
def test_the_database_keeps_the_trigger_list_and_durations(ops: Dict[str, Any], column: str, value: Any) -> None:
    sha = matrix_db._publish(ops, "1.0.0", branch="main")
    result_id = _hosted(ops, sha, "p-1", True)
    cursor = ops["cursor"]
    cursor.execute("SAVEPOINT bad_insert")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            f"""
            INSERT INTO apiome.verification_result (
                tenant_id, consumer_id, provider_id, pact_version_id, provider_version_id, number, success, {column}
            )
            SELECT tenant_id, consumer_id, provider_id, pact_version_id, provider_version_id, number + 1, success, %s
            FROM apiome.verification_result WHERE id = %s::uuid
            """,
            (value, result_id),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT bad_insert")


def test_the_newest_pact_is_stale_until_its_pact_version_has_a_result(ops: Dict[str, Any]) -> None:
    tenant = ops["seed"]["tenant"]
    first = matrix_db._publish(ops, "1.0.0", branch="main")
    status = verification_status(ops["db"], tenant, "ledger-api")
    (entry,) = status.pacts
    assert (entry.consumer, entry.pact_version_sha, entry.stale) == ("billing-service", first, True)
    assert (status.counts.pacts, status.counts.stale, status.counts.verified) == (1, 1, 0)

    matrix_db._verify(ops, first, "p-1", True)
    status = verification_status(ops["db"], tenant, "ledger-api")
    (entry,) = status.pacts
    assert entry.stale is False and entry.latest_result is not None and entry.latest_result.success is True
    assert (status.counts.stale, status.counts.verified) == (0, 1)

    # A changed pact is a new pact version, with no result yet: stale again.
    second = matrix_db._publish(ops, "1.1.0", total=2500, branch="main")
    assert second != first
    (entry,) = verification_status(ops["db"], tenant, "ledger-api").pacts
    assert (entry.pact_version_sha, entry.consumer_version, entry.stale) == (second, "1.1.0", True)


def test_the_history_is_newest_first_pages_by_cursor_and_stays_in_its_tenant(ops: Dict[str, Any]) -> None:
    tenant = ops["seed"]["tenant"]
    sha = matrix_db._publish(ops, "1.0.0", branch="main")
    for version in ("p-1", "p-2", "p-3"):
        matrix_db._verify(ops, sha, version, True)
    first = list_results(ops["db"], tenant, "ledger-api", limit=2)
    assert [result.provider_version for result in first.results] == ["p-3", "p-2"]
    assert first.next_cursor is not None
    rest = list_results(ops["db"], tenant, "ledger-api", cursor=first.next_cursor, limit=2)
    assert [result.provider_version for result in rest.results] == ["p-1"] and rest.next_cursor is None
    narrowed = list_results(ops["db"], tenant, "ledger-api", consumer_ref="billing-service")
    assert len(narrowed.results) == 3

    # Another tenant has no such provider, and cannot read the result by id.
    with pytest.raises(Exception):
        list_results(ops["db"], ops["other"]["tenant"], "ledger-api")
    provider = get_pacticipant(ops["db"], tenant, "ledger-api")
    with pytest.raises(PactPublicationError):
        get_provider_result(ops["db"], ops["other"]["tenant"], provider, first.results[0].id)


def test_the_routes_answer_over_http(ops: Dict[str, Any]) -> None:
    sha = matrix_db._publish(ops, "1.0.0", branch="main")
    result_id = _hosted(ops, sha, "p-1", True)
    client = ops["client"]

    status = client.get(f"{_OPS}/verification-status")
    assert status.status_code == 200, status.text
    assert status.json()["pacts"][0]["stale"] is False

    history = client.get(f"{_OPS}/results")
    assert history.status_code == 200 and history.json()["results"][0]["id"] == result_id

    detail = client.get(f"{_OPS}/results/{result_id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    # The caller lacks verification_evidence:view here.
    assert (body["evidence_status"], body["evidence"]) == ("forbidden", None)
    assert body["test_results"][0]["interactionDescription"] == "a request for an invoice"

    assert client.get(f"{_OPS}/results/not-a-uuid").status_code == 404
    assert client.get(f"{_OPS}/results", params={"cursor": "zzz"}).status_code == 400
    assert client.get("/v1/tenants/t/pact-verifier/pacts/provider/nobody/verification-status").status_code == 404
