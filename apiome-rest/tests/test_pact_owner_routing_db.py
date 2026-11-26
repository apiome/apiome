"""Pacticipant owners against a live Postgres — PFX-6.4 (#6956).

What only the real schema proves (apiome-db V450):

* a pacticipant can be given a confirmed owner team (``entity_kind = 'pacticipant'``), and an
  unknown kind is still refused by the check;
* a failed verification result published through the broker reaches the provider's owner team as an
  inbox notification, and the ownerless consumer is recorded in Unowned findings under itself;
* a passing result notifies nobody;
* purging a deleted pacticipant for good removes its owner rows and unowned findings.

Runs inside one always-rolled-back transaction (the ``broker`` fixture of ``test_pact_matrix_db``).
Skipped when no database is reachable or V450 is not applied.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterator

import psycopg2
import pytest

from app.pact_cleanup_store import purge_deleted
from app.pacticipant_store import get_pacticipant
from tests import test_pact_matrix_db as matrix_db
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack
broker = matrix_db.broker

pytestmark = pytest.mark.requires_db


@pytest.fixture
def owners(broker: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The broker stack, skipped before V450 (the owner kinds lack ``pacticipant``)."""
    broker["cursor"].execute(
        "SELECT pg_get_constraintdef(oid) AS def FROM pg_constraint WHERE conname = 'entity_owners_kind_check'"
    )
    row = broker["cursor"].fetchone()
    if not row or "pacticipant" not in row["def"]:
        pytest.skip("V450 not applied")
    yield broker


def _team(cursor: Any, tenant: str, slug: str) -> Dict[str, str]:
    """A team with one member; returns its id and the member's user id."""
    cursor.execute("SELECT id::text AS id FROM apiome.users ORDER BY created_at LIMIT 1")
    user = cursor.fetchone()["id"]
    cursor.execute(
        "INSERT INTO apiome.teams (tenant_id, slug, name) VALUES (%s::uuid, %s, %s) RETURNING id::text AS id",
        (tenant, slug, slug.title()),
    )
    team = cursor.fetchone()["id"]
    cursor.execute(
        "INSERT INTO apiome.tenant_users (tenant_id, user_id) VALUES (%s::uuid, %s::uuid) ON CONFLICT DO NOTHING",
        (tenant, user),
    )
    cursor.execute(
        "INSERT INTO apiome.team_members (team_id, user_id, role) VALUES (%s::uuid, %s::uuid, 'lead')", (team, user)
    )
    return {"team": team, "user": user}


def _own(cursor: Any, tenant: str, entity_id: str, team: str) -> None:
    """Make ``team`` the confirmed owner of the pacticipant ``entity_id``."""
    cursor.execute(
        """INSERT INTO apiome.entity_owners (tenant_id, entity_kind, entity_id, team_id, status, source, confirmed_at)
           VALUES (%s::uuid, 'pacticipant', %s::uuid, %s::uuid, 'confirmed', 'manual', CURRENT_TIMESTAMP)""",
        (tenant, entity_id, team),
    )


def _drift_notifications(cursor: Any, user: str) -> list:
    cursor.execute(
        "SELECT payload FROM apiome.notifications WHERE user_id = %s::uuid AND type = 'owner_verification_drift'",
        (user,),
    )
    return [row["payload"] for row in cursor.fetchall()]


def test_an_unknown_owner_kind_is_still_refused(owners: Dict[str, Any]) -> None:
    cursor, tenant = owners["cursor"], owners["seed"]["tenant"]
    team = _team(cursor, tenant, "ledger-team")
    cursor.execute("SAVEPOINT refused")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cursor.execute(
            """INSERT INTO apiome.entity_owners (tenant_id, entity_kind, entity_id, team_id, status, source)
               VALUES (%s::uuid, 'widget', gen_random_uuid(), %s::uuid, 'suggested', 'manual')""",
            (tenant, team["team"]),
        )
    cursor.execute("ROLLBACK TO SAVEPOINT refused")


def test_a_failed_verification_reaches_the_provider_owner_and_records_the_ownerless_consumer(
    owners: Dict[str, Any],
) -> None:
    db, cursor, tenant = owners["db"], owners["cursor"], owners["seed"]["tenant"]
    sha = matrix_db._publish(owners, "1.0.0", branch="main")
    provider = get_pacticipant(db, tenant, "ledger-api")
    consumer = get_pacticipant(db, tenant, "billing-service")
    team = _team(cursor, tenant, "ledger-team")
    _own(cursor, tenant, provider.id, team["team"])
    matrix_db._provider_version(owners, "4f1e2d0")

    matrix_db._verify(owners, sha, "4f1e2d0", success=True)
    assert _drift_notifications(cursor, team["user"]) == []

    matrix_db._verify(owners, sha, "4f1e2d1", success=False)
    (payload,) = _drift_notifications(cursor, team["user"])
    assert payload["kind"] == "pact-verification-failed" and payload["role"] == "provider"
    assert payload["entity_kind"] == "pacticipant" and payload["entity_id"] == provider.id
    assert payload["pactVersionSha"] == sha and payload["ownerSource"] == "pacticipant"
    assert payload["link"].startswith("/ade/dashboard/pacts/pacticipants/ledger-api/verification/results/")

    cursor.execute(
        """SELECT entity_kind, finding_type FROM apiome.unowned_findings
           WHERE tenant_id = %s::uuid AND entity_id = %s::uuid""",
        (tenant, consumer.id),
    )
    assert [(r["entity_kind"], r["finding_type"]) for r in cursor.fetchall()] == [
        ("pacticipant", "owner_verification_drift")
    ]


def test_a_purged_pacticipant_takes_its_owner_rows_with_it(owners: Dict[str, Any]) -> None:
    db, cursor, tenant = owners["db"], owners["cursor"], owners["seed"]["tenant"]
    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    cursor.execute(
        """INSERT INTO apiome.pacticipant (tenant_id, slug, name, deleted_at)
           VALUES (%s::uuid, 'retired-app', 'Retired App', %s) RETURNING id::text AS id""",
        (tenant, long_ago),
    )
    retired = cursor.fetchone()["id"]
    team = _team(cursor, tenant, "retired-team")
    _own(cursor, tenant, retired, team["team"])
    cursor.execute(
        """INSERT INTO apiome.unowned_findings (tenant_id, entity_kind, entity_id, finding_type)
           VALUES (%s::uuid, 'pacticipant', %s::uuid, 'owner_verification_drift')""",
        (tenant, retired),
    )

    purge_deleted(db)

    for table in ("entity_owners", "unowned_findings"):
        cursor.execute(f"SELECT count(*) AS n FROM apiome.{table} WHERE entity_id = %s::uuid", (retired,))
        assert cursor.fetchone()["n"] == 0, table
