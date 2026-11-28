"""Contracts settings against a live Postgres — PFX-8.15 (#7312).

What only the real schema (apiome-db V457) and the real routes prove:

* the switches save and read back per workspace, and another workspace keeps its defaults;
* with **Statuses on the provider's commit** off, a verification writes the consumer's status and
  records the provider's as ``suppressed`` with the reason — nothing is sent for it;
* a placeholder secret has no value, a webhook referring to it is stored turned off and waiting, it
  cannot be turned on, delivery refuses to resolve it, and setting the value turns the webhook on;
* the database itself refuses a waiting secret with a value and a waiting webhook that is on.

Runs inside one always-rolled-back transaction. Skipped when no database is reachable or V457 is
not applied.
"""

from __future__ import annotations

from typing import Any, Dict, Iterator

import psycopg2
import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_contract_settings import CommitStatusSettings, read_settings, save_commit_statuses
from app.pact_secret import CODE_SECRET_NO_VALUE, PactSecretError, SecretUpdate
from app.pact_secret_store import create_placeholder_tx, get_secret, resolve_secrets, update_secret
from tests import test_pact_cleanup_db as cleanup_db
from tests import test_pact_commit_status_db as status_db
from tests import test_pact_secret_db as secret_db

tx = status_db.tx
stack = status_db.stack
broker = status_db.broker
statuses = status_db.statuses
vault = secret_db.vault

pytestmark = pytest.mark.requires_db

ACTOR = ConsumerActor(user_id=None, label="ada@example.com")
WEBHOOKS = f"{secret_db.BASE}/webhooks"


@pytest.fixture
def settings_stack(statuses: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    statuses["cursor"].execute("SELECT to_regclass('apiome.pact_contract_settings') AS t")
    if not statuses["cursor"].fetchone()["t"]:
        pytest.skip("V457 not applied")
    yield statuses


def test_the_switches_save_per_workspace(settings_stack: Dict[str, Any]) -> None:
    database, tenant = settings_stack["db"], settings_stack["seed"]["tenant"]
    assert read_settings(database.execute_query, tenant).configured is False
    save_commit_statuses(database, tenant, CommitStatusSettings(bidirectional=True, provider_commit=False), actor=ACTOR)
    stored = read_settings(database.execute_query, tenant)
    assert stored.configured and stored.commit_statuses.bidirectional and not stored.commit_statuses.provider_commit
    # Saving the statuses leaves the agents' defaults as they are.
    assert stored.agents.read and not stored.agents.record
    other = read_settings(database.execute_query, settings_stack["other"]["tenant"])
    assert other.configured is False and other.commit_statuses.provider_commit is True


def test_a_switched_off_provider_status_is_recorded_but_not_sent(settings_stack: Dict[str, Any]) -> None:
    status_db._wire_up(settings_stack)
    database, tenant = settings_stack["db"], settings_stack["seed"]["tenant"]
    save_commit_statuses(database, tenant, CommitStatusSettings(provider_commit=False), actor=ACTOR)
    github = settings_stack["github"]
    status_db._publish(settings_stack, status_db.CONSUMER_SHA)
    github.requests.clear()

    status_db._verify(settings_stack, status_db.CONSUMER_SHA, success=True)
    assert github.urls() == [f"https://api.github.com/repos/acme/billing-service/statuses/{status_db.CONSUMER_SHA}"]
    provider = [row for row in status_db._rows(settings_stack) if row["side"] == "provider"]
    assert [(row["outcome"], row["reason_code"]) for row in provider] == [("suppressed", "pact-status-switched-off")]
    assert "provider's commit are switched off" in provider[0]["message"]


@pytest.fixture
def waiting(vault: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    vault["cursor"].execute("SELECT to_regclass('apiome.pact_contract_settings') AS t")
    if not vault["cursor"].fetchone()["t"]:
        pytest.skip("V457 not applied")
    yield vault


def _placeholder(stack: Dict[str, Any], name: str) -> None:
    assert stack["db"]._guarded_tx(
        lambda cursor: create_placeholder_tx(cursor, stack["seed"]["tenant"], name, "Waiting for a value", ACTOR)
    )


def test_a_migrated_webhook_waits_for_its_secret_and_comes_on_when_it_is_set(waiting: Dict[str, Any]) -> None:
    client, database, tenant = waiting["client"], waiting["db"], waiting["seed"]["tenant"]
    _placeholder(waiting, "migrated_ab12cd34_password")
    secrets = client.get(secret_db.SECRETS).json()["secrets"]
    (placeholder,) = [s for s in secrets if s["name"] == "migrated_ab12cd34_password"]
    assert placeholder["has_value"] is False and placeholder["origin"] == "migration"

    body = {
        "events": [{"name": "contract_published"}],
        "enabled": True,
        "request": {
            "method": "POST",
            "url": "https://ci.example.com/hooks/verify",
            "username": "ci",
            "password": "${user.migrated_ab12cd34_password}",
        },
    }
    refused = client.post(WEBHOOKS, json=body)
    assert refused.status_code in (400, 422), refused.text
    assert "migrated_ab12cd34_password has no value yet" in refused.text

    created = client.post(WEBHOOKS, json={**body, "enabled": False})
    assert created.status_code in (200, 201), created.text
    waiting["cursor"].execute(
        "SELECT enabled, awaiting_secrets FROM apiome.pact_webhook WHERE tenant_id = %s::uuid", (tenant,)
    )
    assert [dict(row) for row in waiting["cursor"].fetchall()] == [{"enabled": False, "awaiting_secrets": True}]

    with pytest.raises(PactSecretError) as caught:
        resolve_secrets(database, tenant, ["migrated_ab12cd34_password"])
    assert caught.value.code == CODE_SECRET_NO_VALUE

    update_secret(database, tenant, placeholder["id"], SecretUpdate(value="the-real-password"), actor=ACTOR)
    assert get_secret(database, tenant, placeholder["id"]).has_value is True
    waiting["cursor"].execute(
        "SELECT enabled, awaiting_secrets FROM apiome.pact_webhook WHERE tenant_id = %s::uuid", (tenant,)
    )
    assert [dict(row) for row in waiting["cursor"].fetchall()] == [{"enabled": True, "awaiting_secrets": False}]
    assert resolve_secrets(database, tenant, ["migrated_ab12cd34_password"]) == {
        "migrated_ab12cd34_password": "the-real-password"
    }


def test_the_database_keeps_waiting_rows_consistent(waiting: Dict[str, Any]) -> None:
    cursor, tenant = waiting["cursor"], waiting["seed"]["tenant"]
    with cleanup_db._refused(cursor, psycopg2.errors.CheckViolation):
        cursor.execute(
            """
            INSERT INTO apiome.pact_secret (tenant_id, name, secret_ciphertext, key_version, awaiting_value)
            VALUES (%s::uuid, 'brokenOne', '\\x00'::bytea, 1, TRUE)
            """,
            (tenant,),
        )
    with cleanup_db._refused(cursor, psycopg2.errors.CheckViolation):
        cursor.execute(
            "INSERT INTO apiome.pact_secret (tenant_id, name) VALUES (%s::uuid, 'noValueNotWaiting')", (tenant,)
        )
    secret_db._secret(waiting)
    created = waiting["client"].post(WEBHOOKS, json=secret_db._webhook())
    assert created.status_code in (200, 201), created.text
    with cleanup_db._refused(cursor, psycopg2.errors.CheckViolation):
        cursor.execute(
            "UPDATE apiome.pact_webhook SET awaiting_secrets = TRUE, enabled = TRUE WHERE tenant_id = %s::uuid",
            (tenant,),
        )
