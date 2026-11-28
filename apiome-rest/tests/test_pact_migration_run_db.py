"""Migration runs against a live Postgres — PFX-8.16 (#7313).

What only the real schema (V458) proves:

* a run is recorded with its choices and no credential, read back by its tenant only, and listed
  newest first;
* a workspace has one running run at a time — the second is refused, whichever worker asks;
* progress is saved on a running run only, and saving answers whether to stop;
* a run whose worker went away is closed as ``stopped`` and can be reopened; a dry run cannot;
* done keys are remembered once, per source, per tenant — and go with the run;
* ``replace_conflicts`` lets the source's pact take the place of the one Apiome has.

Runs inside one always-rolled-back transaction (the ``stack`` fixture of ``test_pact_publication_db``).
Skipped when no database is reachable or V458 is not applied.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterator

import pytest

from app import pact_migration_run_store as store
from app.consumer_contract_store import ConsumerActor
from app.pact_migration import parse_import_request
from app.pact_migration_job import PactMigrationRunOptions, run_view
from app.pact_migration_store import import_records
from tests import test_pact_publication_db as publication_db

tx = publication_db.tx
stack = publication_db.stack

pytestmark = pytest.mark.requires_db

SOURCE = "https://broker.example.com"
ACTOR = ConsumerActor(user_id=None, label="ada@example.com")


@pytest.fixture
def runs(stack: Dict[str, Any]) -> Iterator[Dict[str, Any]]:
    """The publication stack, once V458 is there."""
    stack["cursor"].execute("SELECT to_regclass('apiome.pact_migration_run') AS t")
    if not stack["cursor"].fetchone()["t"]:
        pytest.skip("V458 not applied")
    yield stack


def _create(runs: Dict[str, Any], tenant: str = "seed", mode: str = "copy", source: str = SOURCE) -> Dict[str, Any]:
    return store.create_run(
        runs["db"],
        runs[tenant]["tenant"],
        source=source,
        auth_kind="token",
        mode=mode,
        options=PactMigrationRunOptions(kinds=["pact"]).model_dump(),
        facts={"product": "Pact Broker"},
        actor=ACTOR,
    )


def _save(runs: Dict[str, Any], run_id: str, **extra: Any) -> bool:
    fields: Dict[str, Any] = dict(
        phase="pact",
        counts={"pact": {"total": 3, "done": 1, "copied": 1}},
        facts={"product": "Pact Broker"},
        findings=[{"kind": "webhook", "subject": "ci", "detail": "waiting"}],
        failures=[{"kind": "pact", "key": "API/Web/1", "code": "x", "message": "no"}],
        failures_dropped=0,
        log=[{"seq": 1, "text": "14:00:00 Reading"}],
        log_seq=1,
    )
    fields.update(extra)
    return store.save_progress(runs["db"], run_id, **fields)


def test_a_run_is_recorded_without_any_credential_and_read_by_its_tenant(runs: Dict[str, Any]) -> None:
    row = _create(runs)
    assert row["status"] == "running" and row["phase"] == "reading" and row["options"]["kinds"] == ["pact"]
    runs["cursor"].execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'apiome' "
        "AND table_name = 'pact_migration_run'"
    )
    columns = {r["column_name"] for r in runs["cursor"].fetchall()}
    assert not {c for c in columns if any(word in c for word in ("token", "password", "secret", "credential"))}
    assert store.get_run(runs["db"], runs["seed"]["tenant"], row["id"])["source"] == SOURCE
    assert store.get_run(runs["db"], runs["other"]["tenant"], row["id"]) is None
    assert store.get_run(runs["db"], runs["seed"]["tenant"], "not-a-uuid") is None
    assert [r["id"] for r in store.list_runs(runs["db"], runs["seed"]["tenant"])] == [row["id"]]
    assert store.list_runs(runs["db"], runs["other"]["tenant"]) == []
    view = run_view(row)
    assert view.host == "broker.example.com" and view.started_by == "ada@example.com" and view.created_at


def test_one_running_run_per_workspace(runs: Dict[str, Any]) -> None:
    _create(runs)
    runs["cursor"].execute("SAVEPOINT second")
    with pytest.raises(store.RunActiveError):
        _create(runs, mode="dry-run")
    runs["cursor"].execute("ROLLBACK TO SAVEPOINT second")
    assert _create(runs, tenant="other")["status"] == "running"


def test_progress_is_saved_and_says_when_to_stop(runs: Dict[str, Any]) -> None:
    row = _create(runs)
    tenant = runs["seed"]["tenant"]
    assert _save(runs, row["id"]) is False
    read = run_view(store.get_run(runs["db"], tenant, row["id"]))
    assert read.phase == "pact" and read.kinds[0].copied == 1 and read.percent == 33
    assert read.findings[0].subject == "ci" and read.failures[0].key == "API/Web/1" and read.log[0].seq == 1

    assert store.request_stop(runs["db"], tenant, row["id"])["stop_requested"] is True
    assert store.request_stop(runs["db"], runs["other"]["tenant"], row["id"]) is None
    assert _save(runs, row["id"]) is True

    store.finish_run(runs["db"], row["id"], "stopped", error="Stopped.")
    stopped = store.get_run(runs["db"], tenant, row["id"])
    assert stopped["status"] == "stopped" and stopped["finished_at"] is not None and stopped["error"] == "Stopped."
    # A run that is no longer running takes no more progress, and says "stop" to a worker still on it.
    assert _save(runs, row["id"], phase="webhook") is True
    assert store.get_run(runs["db"], tenant, row["id"])["phase"] == "pact"


def test_a_completed_run_reads_done(runs: Dict[str, Any]) -> None:
    row = _create(runs)
    store.finish_run(runs["db"], row["id"], "completed")
    read = store.get_run(runs["db"], runs["seed"]["tenant"], row["id"])
    assert read["status"] == "completed" and read["phase"] == "done"


def test_a_run_that_lost_its_worker_is_closed_and_reopened(runs: Dict[str, Any]) -> None:
    row = _create(runs)
    tenant = runs["seed"]["tenant"]
    assert store.close_stale(runs["db"], tenant) == 0
    runs["cursor"].execute(
        "UPDATE apiome.pact_migration_run SET heartbeat_at = CURRENT_TIMESTAMP - interval '1 hour' WHERE id = %s",
        (row["id"],),
    )
    assert store.close_stale(runs["db"], tenant) == 1
    closed = store.get_run(runs["db"], tenant, row["id"])
    assert closed["status"] == "stopped" and closed["error"] == store.STALE_MESSAGE
    assert run_view(closed).can_resume is True

    assert store.reopen_run(runs["db"], runs["other"]["tenant"], row["id"]) is None
    reopened = store.reopen_run(runs["db"], tenant, row["id"])
    assert reopened["status"] == "running" and reopened["finished_at"] is None and reopened["counts"] == {}
    with pytest.raises(store.RunActiveError):
        store.reopen_run(runs["db"], tenant, row["id"])


def test_a_dry_run_is_not_reopened(runs: Dict[str, Any]) -> None:
    row = _create(runs, mode="dry-run")
    store.finish_run(runs["db"], row["id"], "failed", error="no")
    assert store.reopen_run(runs["db"], runs["seed"]["tenant"], row["id"]) is None


def test_done_keys_are_kept_per_source_and_tenant(runs: Dict[str, Any]) -> None:
    row = _create(runs)
    tenant = runs["seed"]["tenant"]
    store.add_done(runs["db"], row["id"], ["pact:API/Web/1", "pact:API/Web/2", ""])
    store.add_done(runs["db"], row["id"], ["pact:API/Web/2", "x" * (store.MAX_DONE_KEY_LENGTH + 1)])
    assert store.done_keys(runs["db"], tenant, SOURCE) == {"pact:API/Web/1", "pact:API/Web/2"}
    assert store.done_keys(runs["db"], tenant, "https://other.example.com") == set()
    assert store.done_keys(runs["db"], runs["other"]["tenant"], SOURCE) == set()

    # A later run from the same source sees what the first imported.
    store.finish_run(runs["db"], row["id"], "completed")
    second = _create(runs)
    store.add_done(runs["db"], second["id"], ["pact:API/Web/3"])
    assert len(store.done_keys(runs["db"], tenant, SOURCE)) == 3

    runs["cursor"].execute("DELETE FROM apiome.pact_migration_run WHERE id = %s", (row["id"],))
    assert store.done_keys(runs["db"], tenant, SOURCE) == {"pact:API/Web/3"}


def test_replace_lets_the_sources_pact_take_the_place_of_apiomes(runs: Dict[str, Any]) -> None:
    tenant = runs["seed"]["tenant"]

    def send(content: Dict[str, Any], *, replace: bool) -> Any:
        record = {
            "kind": "pact",
            "consumer": content["consumer"]["name"],
            "provider": content["provider"]["name"],
            "consumer_version": "1.0.0",
            "content": content,
            "created_at": "2025-03-01T09:00:00Z",
        }
        request = parse_import_request(json.dumps({"records": [record]}).encode(), max_pact_bytes=1_000_000)
        return import_records(runs["db"], tenant, request, actor=ACTOR, replace_conflicts=replace)[0]

    assert send(publication_db._pact(), replace=False).outcome == "created"
    runs["cursor"].execute("SAVEPOINT conflict")
    kept = send(publication_db._pact(total=1), replace=False)
    assert kept.outcome == "refused" and kept.code == "pact-migration-conflict"
    runs["cursor"].execute("ROLLBACK TO SAVEPOINT conflict")
    replaced = send(publication_db._pact(total=1), replace=True)
    assert replaced.outcome == "updated" and "replaced" in (replaced.note or "")
    assert send(publication_db._pact(total=1), replace=True).outcome == "unchanged"
