"""The Contracts landing's integrations list against a live Postgres — PFX-8.1 (#7298).

What only the real schema proves:

* a published pact is one integration, with its newest consumer version, and with no result it
  reads ``no-provider-contract`` and pending;
* a failed then a passed native result: the newest verdict wins, and the provider version is read;
* a deployment of both sides into one environment lists it; one side alone does not;
* the stale-pact sweep's record counts only for the newest content;
* the read is capped and says how many pairs it left out;
* the ``mine`` filter follows confirmed owner teams the caller is on;
* another workspace never sees the integration.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_matrix_db``).
Skipped when no database is reachable.
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from app.pact_integrations import parse_query
from app.pact_integrations_store import list_integrations
from app.pacticipant_store import get_pacticipant
from tests import test_pact_environment_db as environment_db
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_owner_routing_db as owner_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker

pytestmark = pytest.mark.requires_db


def _tenant(stack: Dict[str, Any]) -> str:
    return stack["seed"]["tenant"]


def _read(stack: Dict[str, Any], **query: Any) -> Any:
    user_id = query.pop("user_id", None)
    cap = query.pop("cap", None)
    extra = {"cap": cap} if cap else {}
    return list_integrations(stack["db"], _tenant(stack), parse_query(**query), user_id=user_id, **extra)


def test_a_published_pact_is_one_integration_awaiting_a_provider_contract(broker: Dict[str, Any]) -> None:
    matrix_db._publish(broker, "1.0.0")
    matrix_db._publish(broker, "1.1.0")
    page = _read(broker)
    assert page.counts.integrations == 1 and page.total == 1
    row = page.integrations[0]
    assert (row.consumer, row.provider, row.consumer_version) == ("billing-service", "ledger-api", "1.1.0")
    assert (row.kind, row.verdict, row.pending, row.verified_at) == ("pact", "no-provider-contract", True, None)
    assert page.attention.no_provider_contract[0].consumer == "billing-service"
    assert page.pacticipants >= 2


def test_the_newest_native_result_is_the_verdict(broker: Dict[str, Any]) -> None:
    sha = matrix_db._publish(broker, "1.0.0")
    matrix_db._provider_version(broker, "2.0.0")
    matrix_db._verify(broker, sha, "2.0.0", False)
    assert _read(broker).integrations[0].verdict == "failing"
    matrix_db._provider_version(broker, "2.0.1")
    matrix_db._verify(broker, sha, "2.0.1", True)
    row = _read(broker).integrations[0]
    assert (row.verdict, row.provider_version, row.pending, row.kind) == ("verified", "2.0.1", False, "pact")
    assert row.verified_at is not None


def test_environments_both_sides_are_deployed_in_are_listed(broker: Dict[str, Any]) -> None:
    environment_db._create_environment(broker, "production", production=True)
    environment_db._create_environment(broker, "staging")
    sha = matrix_db._publish(broker, "1.0.0")
    matrix_db._provider_version(broker, "p-1")
    matrix_db._verify(broker, sha, "p-1", True)
    matrix_db._deploy(broker, "Ledger API", "p-1", "production")
    matrix_db._deploy(broker, "Ledger API", "p-1", "staging")
    matrix_db._deploy(broker, "Billing Service", "1.0.0", "production")
    page = _read(broker)
    assert page.integrations[0].environments == ["production"]
    assert page.environments == 2


def test_the_sweeps_record_counts_only_for_the_newest_content(broker: Dict[str, Any]) -> None:
    sha = matrix_db._publish(broker, "1.0.0")
    tenant = _tenant(broker)
    provider = get_pacticipant(broker["db"], tenant, "ledger-api").id
    consumer = get_pacticipant(broker["db"], tenant, "billing-service").id
    broker["cursor"].execute(
        """
        INSERT INTO apiome.pact_staleness
            (tenant_id, provider_id, consumer_id, sha, stale, reference_at, threshold_hours)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, TRUE, now() - interval '100 hours', 72)
        """,
        (tenant, provider, consumer, sha),
    )
    assert _read(broker).integrations[0].verdict == "stale"
    broker["cursor"].execute("UPDATE apiome.pact_staleness SET sha = %s WHERE tenant_id = %s::uuid", ("b" * 64, tenant))
    assert _read(broker).integrations[0].verdict == "no-provider-contract"


def _publish_for_tax_api(stack: Dict[str, Any]) -> None:
    """Billing Service 9.0.0 also publishes a pact for Tax API: a second integration."""
    document = publication_db._pact(total=5)
    document["provider"] = {"name": "Tax API"}
    response = stack["client"].post(
        f"{publication_db.BASE}/contracts/publish", json=publication_db._bulk("9.0.0", document)
    )
    assert response.status_code == 200, response.text


def test_a_capped_read_says_how_many_pairs_it_left_out(broker: Dict[str, Any]) -> None:
    matrix_db._publish(broker, "1.0.0")
    assert _read(broker, cap=1).truncated is False
    _publish_for_tax_api(broker)
    assert _read(broker).counts.integrations == 2
    page = _read(broker, cap=1)
    assert (page.counts.integrations, page.truncated, page.omitted_integrations) == (1, True, 1)


def test_mine_follows_the_owner_teams_the_caller_is_on(broker: Dict[str, Any]) -> None:
    broker["cursor"].execute(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conname = 'entity_owners_kind_check'"
    )
    row = broker["cursor"].fetchone()
    if not row or "pacticipant" not in row["def"]:
        pytest.skip("V451 not applied")
    matrix_db._publish(broker, "1.0.0")
    _publish_for_tax_api(broker)
    tenant = _tenant(broker)
    team = owner_db._team(broker["cursor"], tenant, "ledger-team")
    assert _read(broker, filter="mine", user_id=team["user"]).total == 0
    owner_db._own(broker["cursor"], tenant, get_pacticipant(broker["db"], tenant, "ledger-api").id, team["team"])
    page = _read(broker, filter="mine", user_id=team["user"])
    assert [row.provider for row in page.integrations] == ["ledger-api"]
    assert page.integrations[0].mine is True and page.counts.mine == 1 and page.mine_available is True


def test_another_workspace_never_sees_the_integration(broker: Dict[str, Any]) -> None:
    matrix_db._publish(broker, "1.0.0")
    other = broker["other"]["tenant"]
    page = list_integrations(broker["db"], other, parse_query())
    assert page.counts.integrations == 0 and page.integrations == []
