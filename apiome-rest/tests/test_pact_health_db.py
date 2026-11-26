"""The contract health rollup against a live Postgres — PFX-6.3 (#6955).

What only the real schema proves (apiome-db V449 and the PFX tables it reads):

* the newest pact of a pair, its newest verdict, and the window's runs, passes and verdict flips
  (``lag`` over the pair's results) come out of SQL as the pure half expects;
* a result outside the window is not counted, though the newest verdict still reads it;
* the stale-pact sweep's record and an open re-publish request are fused for the newest pact only;
* the trend puts today's results in the last bucket;
* another workspace never sees the pair, and cannot name its pacticipants.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_matrix_db``).
Skipped when no database is reachable or V448 is not applied.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator

import pytest

from app.pact_health import CODE_PAIR_NOT_FOUND, HealthError
from app.pact_health_store import pair_health, workspace_health
from app.pacticipant import PacticipantValidationError
from app.pacticipant_store import get_pacticipant
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker

pytestmark = pytest.mark.requires_db


@pytest.fixture
def health(broker: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The broker stack, skipped before V448 (staleness and re-publish requests)."""
    broker["cursor"].execute("SELECT to_regclass('apiome.pact_staleness') AS t")
    if not broker["cursor"].fetchone()["t"]:
        pytest.skip("V448 not applied")
    yield broker


def _ids(stack: Dict[str, Any]) -> Dict[str, str]:
    tenant = stack["seed"]["tenant"]
    return {
        "tenant": tenant,
        "provider": get_pacticipant(stack["db"], tenant, "ledger-api").id,
        "consumer": get_pacticipant(stack["db"], tenant, "billing-service").id,
    }


def _verify_sequence(stack: Dict[str, Any], sha: str, verdicts: list) -> None:
    for index, success in enumerate(verdicts):
        version = f"2.0.{index}"
        matrix_db._provider_version(stack, version)
        matrix_db._verify(stack, sha, version, success)


def _age_results(stack: Dict[str, Any], tenant: str, days: int, count: int) -> None:
    """Move the oldest ``count`` results ``days`` days into the past (results are immutable, so the
    V434 guard is bypassed for the test transaction only)."""
    cursor = stack["cursor"]
    cursor.execute("SET LOCAL session_replication_role = replica")
    cursor.execute(
        """
        UPDATE apiome.verification_result SET created_at = created_at - make_interval(days => %s)
        WHERE id IN (SELECT id FROM apiome.verification_result WHERE tenant_id = %s::uuid ORDER BY seq LIMIT %s)
        """,
        (days, tenant, count),
    )
    cursor.execute("SET LOCAL session_replication_role = origin")


def test_the_rollup_counts_runs_passes_and_flips_of_the_newest_pact(health: Dict[str, Any]) -> None:
    sha = matrix_db._publish(health, "1.0.0")
    _verify_sequence(health, sha, [True, False, True, True])
    ids = _ids(health)

    overview = workspace_health(health["db"], ids["tenant"], window="7d")
    assert overview.counts.pairs == 1
    pair = overview.pairs[0]
    assert (pair.provider, pair.consumer, pair.pact_version_sha) == ("ledger-api", "billing-service", sha)
    assert (pair.metrics.runs, pair.metrics.passed, pair.metrics.flips) == (4, 3, 2)
    assert pair.metrics.flakiness == pytest.approx(2 / 3)
    assert pair.metrics.timed_runs == 0  # published results carry no duration
    assert pair.latest_success is True
    components = {component.key: component for component in pair.components}
    assert components["latest-verdict"].status == "ok"
    assert components["pass-rate"].status == "fail"  # 75%
    assert components["flakiness"].status == "fail"
    assert components["overdue"].status == "unknown"  # the sweep never looked
    assert pair.state == "failing"
    assert overview.totals.runs == 4


def test_results_outside_the_window_are_not_counted_but_the_newest_verdict_still_reads(
    health: Dict[str, Any],
) -> None:
    sha = matrix_db._publish(health, "1.0.0")
    _verify_sequence(health, sha, [False, True])
    ids = _ids(health)
    _age_results(health, ids["tenant"], days=40, count=2)

    pair = workspace_health(health["db"], ids["tenant"], window="30d").pairs[0]
    assert pair.metrics.runs == 0 and pair.metrics.pass_rate is None
    assert pair.latest_success is True
    assert workspace_health(health["db"], ids["tenant"], window="90d").pairs[0].metrics.runs == 2


def test_staleness_and_an_open_request_are_fused_for_the_newest_pact(health: Dict[str, Any]) -> None:
    sha = matrix_db._publish(health, "1.0.0")
    _verify_sequence(health, sha, [True])
    ids = _ids(health)
    cursor = health["cursor"]
    cursor.execute(
        """
        INSERT INTO apiome.pact_staleness
            (tenant_id, provider_id, consumer_id, sha, stale, reference_at, threshold_hours)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, TRUE, now() - interval '100 hours', 72)
        """,
        (ids["tenant"], ids["provider"], ids["consumer"], sha),
    )
    cursor.execute(
        """
        INSERT INTO apiome.pact_republish_request
            (tenant_id, provider_id, consumer_id, sha, consumer_version, threshold_hours, reference_at, expires_at)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, '1.0.0', 72, now() - interval '100 hours', now() + interval '1 day')
        RETURNING id::text AS id
        """,
        (ids["tenant"], ids["provider"], ids["consumer"], sha),
    )
    request_id = cursor.fetchone()["id"]

    pair = workspace_health(health["db"], ids["tenant"]).pairs[0]
    components = {component.key: component for component in pair.components}
    assert components["overdue"].code == "pact-health-overdue"
    assert components["republish-request"].status == "warn"
    assert pair.republish_request_id == request_id
    assert pair.state == "degraded"
    assert workspace_health(health["db"], ids["tenant"], state="healthy").pairs == []
    assert workspace_health(health["db"], ids["tenant"], state="healthy").counts.degraded == 1


def test_the_trend_puts_todays_results_in_the_last_bucket(health: Dict[str, Any]) -> None:
    sha = matrix_db._publish(health, "1.0.0")
    _verify_sequence(health, sha, [True, False])
    ids = _ids(health)

    detail = pair_health(health["db"], ids["tenant"], "ledger-api", "billing-service", window="7d")
    assert len(detail.trend) == 7
    assert detail.trend[-1].metrics.runs == 2 and detail.trend[-1].metrics.flips == 1
    assert sum(bucket.metrics.runs for bucket in detail.trend[:-1]) == 0
    assert detail.pair.metrics.runs == 2


def test_a_pair_without_a_pact_is_not_found(health: Dict[str, Any]) -> None:
    matrix_db._publish(health, "1.0.0")
    ids = _ids(health)
    with pytest.raises(HealthError) as caught:
        pair_health(health["db"], ids["tenant"], "billing-service", "ledger-api")
    assert caught.value.code == CODE_PAIR_NOT_FOUND


def test_another_workspace_never_sees_the_pair(health: Dict[str, Any]) -> None:
    sha = matrix_db._publish(health, "1.0.0")
    _verify_sequence(health, sha, [True])
    other = health["other"]["tenant"]
    assert workspace_health(health["db"], other).counts.pairs == 0
    with pytest.raises(PacticipantValidationError):
        workspace_health(health["db"], other, provider_ref="ledger-api")
    with pytest.raises(PacticipantValidationError):
        pair_health(health["db"], other, "ledger-api", "billing-service")
