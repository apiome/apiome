"""Keep-in-sync against a live Postgres — PFX-8.17 (#7314).

What only the real schema (V459) proves:

* switching on stores the credentials sealed (never the token itself), read back by the tenant only;
  switching off clears them — and the database refuses an enabled row without them;
* a workspace keeps one migration in sync at a time;
* the sweep claims a pass once it is due, moving the next one an interval on;
* the 24-hour clock of an unreachable source starts once and is cleared by a pass that copies;
* who-has-moved reads the newest pact and result of each pacticipant, and Apiome answers a
  can-i-deploy question from the matrix of its own workspace.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of ``test_pact_publication_db``).
Skipped when no database is reachable or V459 is not applied.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, Iterator

import psycopg2
import pytest

from app import pact_migration_run_store as run_store
from app import pact_migration_sync_store as store
from app.config import settings
from app.consumer_contract_store import ConsumerActor
from app.pact_migration_agreement import Question, apiome_answer
from app.pact_migration_job import PactMigrationRunOptions
from app.pact_migration_moved import apiome_latest
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

SOURCE = "https://broker.example.com"
TOKEN = "s3cr3t-read-token"
ACTOR = ConsumerActor(user_id=None, label="ada@example.com")


@pytest.fixture
def syncs(stack: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> Iterator[Dict[str, Any]]:
    """The publication stack, once V459 is there, with a master key."""
    stack["cursor"].execute("SELECT to_regclass('apiome.pact_migration_sync') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V459 not applied")
    monkeypatch.setattr(
        settings, "mcp_credential_encryption_keys", json.dumps({"1": base64.b64encode(os.urandom(32)).decode()})
    )
    monkeypatch.setattr(settings, "mcp_credential_active_key_version", None)
    yield stack


def _run(syncs: Dict[str, Any], tenant: str = "seed") -> Dict[str, Any]:
    row = run_store.create_run(
        syncs["db"],
        syncs[tenant]["tenant"],
        source=SOURCE,
        auth_kind="token",
        mode="copy",
        options=PactMigrationRunOptions().model_dump(),
        facts={},
        actor=ACTOR,
    )
    run_store.finish_run(syncs["db"], row["id"], "completed")
    return row


def _enable(syncs: Dict[str, Any], run: Dict[str, Any], tenant: str = "seed", interval: int = 900) -> Dict[str, Any]:
    ciphertext, version = store.seal_credentials({"token": TOKEN})
    return store.enable_sync(
        syncs["db"],
        syncs[tenant]["tenant"],
        run["id"],
        ciphertext=ciphertext,
        key_version=version,
        interval_seconds=interval,
        actor=ACTOR,
    )


def test_credentials_are_kept_sealed_while_on_and_cleared_when_off(syncs: Dict[str, Any]) -> None:
    run = _run(syncs)
    row = _enable(syncs, run)
    assert row["enabled"] and row["enabled_by_label"] == "ada@example.com"
    assert TOKEN.encode() not in bytes(row["credential_ciphertext"])
    assert store.unseal_credentials(row["credential_ciphertext"], row["key_version"]) == {"token": TOKEN}
    assert store.get_sync(syncs["db"], syncs["other"]["tenant"], run["id"]) is None
    off = store.disable_sync(syncs["db"], syncs["seed"]["tenant"], run["id"])
    assert (
        off is not None and not off["enabled"] and off["credential_ciphertext"] is None and off["key_version"] is None
    )
    assert store.disable_sync(syncs["db"], syncs["other"]["tenant"], run["id"]) is None


def test_the_database_refuses_an_enabled_sync_without_credentials(syncs: Dict[str, Any]) -> None:
    run = _run(syncs)
    syncs["cursor"].execute("SAVEPOINT bad")
    with pytest.raises(psycopg2.errors.CheckViolation):
        syncs["cursor"].execute(
            "INSERT INTO apiome.pact_migration_sync (run_id, tenant_id, enabled) VALUES (%s::uuid, %s::uuid, TRUE)",
            (run["id"], syncs["seed"]["tenant"]),
        )
    syncs["cursor"].execute("ROLLBACK TO SAVEPOINT bad")


def test_one_migration_per_workspace_is_kept_in_sync(syncs: Dict[str, Any]) -> None:
    first, second = _run(syncs), _run(syncs)
    _enable(syncs, first)
    syncs["cursor"].execute("SAVEPOINT second")
    with pytest.raises(store.SyncActiveError):
        _enable(syncs, second)
    syncs["cursor"].execute("ROLLBACK TO SAVEPOINT second")
    store.disable_sync(syncs["db"], syncs["seed"]["tenant"], first["id"])
    assert _enable(syncs, second)["enabled"]
    assert _enable(syncs, _run(syncs, "other"), "other")["enabled"]  # another workspace is not counted


def test_a_due_pass_is_claimed_and_the_next_moved_an_interval_on(syncs: Dict[str, Any]) -> None:
    run = _run(syncs)
    _enable(syncs, run)
    assert [row["run_id"] for row in store.claim_due(syncs["db"], limit=5)] == []  # due in 15 minutes
    syncs["cursor"].execute(
        "UPDATE apiome.pact_migration_sync SET next_run_at = CURRENT_TIMESTAMP - interval '1 minute' "
        "WHERE run_id = %s::uuid",
        (run["id"],),
    )
    [claimed] = store.claim_due(syncs["db"], limit=5)
    assert claimed["run_id"] == run["id"] and claimed["credential_ciphertext"] is not None
    syncs["cursor"].execute(
        "SELECT next_run_at - CURRENT_TIMESTAMP AS wait FROM apiome.pact_migration_sync WHERE run_id = %s::uuid",
        (run["id"],),
    )
    assert syncs["cursor"].fetchone()["wait"].total_seconds() == 900
    store.disable_sync(syncs["db"], syncs["seed"]["tenant"], run["id"])
    syncs["cursor"].execute("UPDATE apiome.pact_migration_sync SET next_run_at = CURRENT_TIMESTAMP - interval '1 hour'")
    assert store.claim_due(syncs["db"], limit=5) == []  # a disabled sync is never claimed


def test_the_unreachable_clock_starts_once_and_a_good_pass_clears_it(syncs: Dict[str, Any]) -> None:
    run = _run(syncs)
    _enable(syncs, run)
    first = store.record_pass(syncs["db"], run["id"], ok=False, error="HTTP 503", unreachable=True)
    assert first is not None and first["unreachable_since"] is not None and first["passes"] == 0
    syncs["cursor"].execute(
        "UPDATE apiome.pact_migration_sync SET unreachable_since = unreachable_since - interval '3 hours'"
    )
    again = store.record_pass(syncs["db"], run["id"], ok=False, error="HTTP 503", unreachable=True)
    assert again is not None and again["unreachable_since"] < first["unreachable_since"]  # kept, not restarted
    good = store.record_pass(syncs["db"], run["id"], ok=True)
    assert good is not None and good["unreachable_since"] is None and good["last_error"] is None and good["passes"] == 1


def test_who_has_moved_and_apiomes_answer_come_from_what_was_published(syncs: Dict[str, Any]) -> None:
    published = syncs["client"].put(f"{publication_db.PAIR}/version/1.0.0", json=publication_db._pact())
    assert published.status_code == 201, published.text
    seed = syncs["seed"]["tenant"]
    found = apiome_latest(syncs["db"], seed, ["Billing Service", "Ledger API", "Nobody Here"])
    assert set(found) == {"Billing Service", "Ledger API"}  # a name Apiome does not have is left out
    assert found["Billing Service"] is not None and found["Billing Service"].tzinfo is not None
    assert found["Ledger API"] is None  # it has verified nothing
    assert apiome_latest(syncs["db"], syncs["other"]["tenant"], ["Billing Service"]) == {}

    answer = apiome_answer(syncs["db"], seed, Question("Billing Service", "1.0.0"))
    assert answer.error is None and answer.deployable is None  # a pact with no result yet
    assert answer.rows == frozenset({("billing-service", "1.0.0", "ledger-api", None, None, None)})
    missing = apiome_answer(syncs["db"], syncs["other"]["tenant"], Question("Billing Service", "1.0.0"))
    assert missing.deployable is not True  # another workspace knows nothing of it
