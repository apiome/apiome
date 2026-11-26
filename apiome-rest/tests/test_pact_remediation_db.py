"""Stale-pact remediation and verification settings against a live Postgres — PFX-6.2 (#6954).

What only the real schema proves (apiome-db V448):

* settings read the defaults until saved, and the database keeps their ranges and cadences;
* an override is one per provider and one per pair, replaced in place, removed by id, and never
  visible to (or removable by) another workspace; a cross-workspace reference is refused;
* a stale pact opens exactly one re-publish request (``unlinked`` when its consumer names no owner),
  which is acknowledged, expired (and not reopened), cleared by a verification, or republished;
* only one request per pair is open at a time; another workspace never reads it;
* the status read shows the pact as overdue with its open request;
* the widened lists accept ``trigger = 'scheduled'`` and the four remediation webhook events.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_matrix_db``).
Skipped when no database is reachable or V448 is not applied.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator

import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_remediation import (
    CODE_OVERRIDE_NOT_FOUND,
    CODE_REQUEST_CLOSED,
    CODE_REQUEST_NOT_FOUND,
    OverrideInput,
    RemediationError,
    VerificationSettingsInput,
)
from app.pact_remediation_store import (
    acknowledge_request,
    delete_override,
    get_request,
    get_settings,
    list_overrides,
    list_requests,
    put_override,
    resolve_republished_on_publish,
    save_settings,
    staleness_for_provider,
)
from app.pact_remediation_sweep import SweepCounts, remediate_provider
from app.pact_verification_ops import verification_status
from app.pacticipant_store import get_pacticipant
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ops@example.com", kind="user")


@pytest.fixture
def remediation(broker: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The broker stack, skipped before V448."""
    broker["cursor"].execute("SELECT to_regclass('apiome.pact_republish_request') AS t")
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


def _sweep(stack: Dict[str, Any], days: float) -> SweepCounts:
    """One remediation pass over Ledger API, ``days`` from now."""
    ids = _ids(stack)
    counts = SweepCounts()
    remediate_provider(
        stack["db"],
        ids["tenant"],
        "t",
        ids["provider"],
        get_settings(stack["db"], ids["tenant"]),
        now=datetime.now(timezone.utc) + timedelta(days=days),
        counts=counts,
    )
    return counts


def _refused(cursor: Any, error: type, sql: str, params: tuple) -> None:
    cursor.execute("SAVEPOINT refused")
    with pytest.raises(error):
        cursor.execute(sql, params)
    cursor.execute("ROLLBACK TO SAVEPOINT refused")


# ---------------------------------------------------------------------------
# Settings and overrides
# ---------------------------------------------------------------------------


def test_settings_read_the_defaults_until_saved(remediation: Dict[str, Any]) -> None:
    db, tenant = remediation["db"], remediation["seed"]["tenant"]
    assert get_settings(db, tenant).customised is False
    body = VerificationSettingsInput(
        cadence="nightly",
        stale_threshold_hours=24,
        max_concurrent_runs=4,
        request_window_hours=12,
        republish_requests_enabled=False,
    )
    saved = save_settings(db, tenant, body, actor=ACTOR)
    assert saved.customised is True and saved.cadence == "nightly"
    again = save_settings(db, tenant, body.model_copy(update={"cadence": "hourly"}), actor=ACTOR)
    assert get_settings(db, tenant).cadence == again.cadence == "hourly"
    assert get_settings(db, remediation["other"]["tenant"]).customised is False


@pytest.mark.parametrize(
    ("column", "value"),
    [("cadence", "weekly"), ("stale_threshold_hours", 0), ("max_concurrent_runs", 11), ("request_window_hours", 721)],
)
def test_the_database_keeps_the_settings_ranges(remediation: Dict[str, Any], column: str, value: Any) -> None:
    _refused(
        remediation["cursor"],
        psycopg2.errors.CheckViolation,
        f"INSERT INTO apiome.pact_verification_settings (tenant_id, {column}) VALUES (%s::uuid, %s)",
        (remediation["seed"]["tenant"], value),
    )


def test_an_override_is_one_per_provider_and_per_pair_and_replaced_in_place(remediation: Dict[str, Any]) -> None:
    matrix_db._publish(remediation, "1.0.0", branch="main")
    db, tenant = remediation["db"], remediation["seed"]["tenant"]
    put_override(db, tenant, OverrideInput(provider="ledger-api", cadence="hourly"), actor=ACTOR)
    put_override(db, tenant, OverrideInput(provider="ledger-api", cadence="nightly"), actor=ACTOR)
    pair = put_override(
        db,
        tenant,
        OverrideInput(provider="ledger-api", consumer="billing-service", stale_threshold_hours=24),
        actor=ACTOR,
    )
    listed = list_overrides(db, tenant).overrides
    assert [(o.consumer, o.cadence, o.stale_threshold_hours) for o in listed] == [
        (None, "nightly", None),
        ("billing-service", None, 24),
    ]
    assert list_overrides(db, remediation["other"]["tenant"]).overrides == []
    with pytest.raises(RemediationError) as caught:
        delete_override(db, remediation["other"]["tenant"], pair.id)
    assert caught.value.code == CODE_OVERRIDE_NOT_FOUND
    delete_override(db, tenant, pair.id)
    assert len(list_overrides(db, tenant).overrides) == 1
    with pytest.raises(RemediationError):
        delete_override(db, tenant, "not-a-uuid")


def test_an_override_cannot_name_another_workspaces_provider(remediation: Dict[str, Any]) -> None:
    matrix_db._publish(remediation, "1.0.0", branch="main")
    ids = _ids(remediation)
    _refused(
        remediation["cursor"],
        psycopg2.errors.ForeignKeyViolation,
        "INSERT INTO apiome.pact_verification_override (tenant_id, provider_id, cadence)"
        " VALUES (%s::uuid, %s::uuid, 'hourly')",
        (remediation["other"]["tenant"], ids["provider"]),
    )
    _refused(
        remediation["cursor"],
        psycopg2.errors.CheckViolation,
        "INSERT INTO apiome.pact_verification_override (tenant_id, provider_id) VALUES (%s::uuid, %s::uuid)",
        (ids["tenant"], ids["provider"]),
    )


# ---------------------------------------------------------------------------
# The remediation loop
# ---------------------------------------------------------------------------


def test_a_stale_pact_opens_one_request_which_is_acknowledged_then_expires(remediation: Dict[str, Any]) -> None:
    sha = matrix_db._publish(remediation, "1.0.0", branch="main")
    db, ids = remediation["db"], _ids(remediation)
    # The transaction's clock stands still: a 10-day window keeps the request open on day 4.
    save_settings(
        db,
        ids["tenant"],
        VerificationSettingsInput(
            cadence="manual-only",
            stale_threshold_hours=72,
            max_concurrent_runs=2,
            request_window_hours=240,
            republish_requests_enabled=True,
        ),
        actor=ACTOR,
    )

    assert _sweep(remediation, days=1).requests_opened == 0
    counts = _sweep(remediation, days=4)
    assert (counts.became_stale, counts.requests_opened) == (1, 1)
    (request,) = list_requests(db, ids["tenant"], state="open").requests
    assert (request.state, request.pact_version_sha, request.consumer_version) == ("requested", sha, "1.0.0")
    assert request.notification_status == "unlinked"
    assert staleness_for_provider(db, ids["tenant"], ids["provider"])[ids["consumer"]]["stale"] is True

    # The next pass neither duplicates it nor fires the stale event again.
    again = _sweep(remediation, days=4)
    assert (again.became_stale, again.requests_opened) == (0, 0)

    acknowledged = acknowledge_request(db, ids["tenant"], request.id, "re-publishing Friday", actor=ACTOR)
    assert (acknowledged.state, acknowledged.note, acknowledged.acknowledged_by) == (
        "acknowledged",
        "re-publishing Friday",
        "ops@example.com",
    )
    with pytest.raises(RemediationError) as caught:
        get_request(db, remediation["other"]["tenant"], request.id)
    assert caught.value.code == CODE_REQUEST_NOT_FOUND

    expired = _sweep(remediation, days=11)
    assert expired.requests_closed == {"expired": 1} and expired.requests_opened == 0
    closed = get_request(db, ids["tenant"], request.id)
    assert closed.state == "expired" and closed.resolved_at and closed.escalation_status == "unlinked"
    with pytest.raises(RemediationError) as refused:
        acknowledge_request(db, ids["tenant"], request.id, None, actor=ACTOR)
    assert refused.value.code == CODE_REQUEST_CLOSED
    # Not asked again for the same pact version.
    assert _sweep(remediation, days=12).requests_opened == 0


def test_a_verification_clears_the_request_and_the_stale_state(remediation: Dict[str, Any]) -> None:
    sha = matrix_db._publish(remediation, "1.0.0", branch="main")
    db, ids = remediation["db"], _ids(remediation)
    _sweep(remediation, days=4)
    matrix_db._verify(remediation, sha, "p-1", True)
    counts = _sweep(remediation, days=0)
    assert counts.requests_closed == {"cleared": 1} and counts.no_longer_stale == 1
    assert list_requests(db, ids["tenant"], state="open").requests == []


def test_publishing_again_republishes_the_open_request(remediation: Dict[str, Any]) -> None:
    matrix_db._publish(remediation, "1.0.0", branch="main")
    db, ids = remediation["db"], _ids(remediation)
    _sweep(remediation, days=4)
    assert resolve_republished_on_publish(db, ids["tenant"], ids["consumer"], ids["provider"], "1.0.1") == 1
    (request,) = list_requests(db, ids["tenant"]).requests
    assert (request.state, request.resolved_consumer_version) == ("republished", "1.0.1")


def test_only_one_request_per_pair_is_open(remediation: Dict[str, Any]) -> None:
    sha = matrix_db._publish(remediation, "1.0.0", branch="main")
    ids = _ids(remediation)
    _sweep(remediation, days=4)
    _refused(
        remediation["cursor"],
        psycopg2.errors.UniqueViolation,
        """
        INSERT INTO apiome.pact_republish_request
            (tenant_id, provider_id, consumer_id, sha, consumer_version, threshold_hours, reference_at, expires_at)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, '1.0.0', 72, now(), now() + interval '1 hour')
        """,
        (ids["tenant"], ids["provider"], ids["consumer"], sha),
    )


def test_the_status_shows_the_pact_overdue_with_its_request(remediation: Dict[str, Any]) -> None:
    matrix_db._publish(remediation, "1.0.0", branch="main")
    db, tenant = remediation["db"], remediation["seed"]["tenant"]
    (entry,) = verification_status(db, tenant, "ledger-api").pacts
    assert entry.overdue is False and entry.republish_request is None
    assert entry.settings is not None and entry.settings.stale_threshold_hours == 72

    save_settings(
        db,
        tenant,
        VerificationSettingsInput(
            cadence="manual-only",
            stale_threshold_hours=1,
            max_concurrent_runs=2,
            request_window_hours=72,
            republish_requests_enabled=True,
        ),
        actor=ACTOR,
    )
    _sweep(remediation, days=1)
    status = verification_status(db, tenant, "ledger-api")
    assert status.counts.republish_requests == 1
    (entry,) = status.pacts
    assert entry.republish_request is not None and entry.republish_request.state == "requested"


# ---------------------------------------------------------------------------
# Widened lists
# ---------------------------------------------------------------------------


def test_the_widened_lists_accept_scheduled_results_and_remediation_events(remediation: Dict[str, Any]) -> None:
    cursor = remediation["cursor"]
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conname = 'verification_result_trigger_check'"
    )
    assert "'scheduled'" in cursor.fetchone()["def"]
    cursor.execute(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conname = 'pact_webhook_events_check'"
    )
    definition = cursor.fetchone()["def"]
    for event in (
        "contract_became_stale",
        "contract_no_longer_stale",
        "contract_republish_requested",
        "contract_republish_request_expired",
    ):
        assert event in definition
