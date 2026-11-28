"""Keep-in-sync passes — PFX-8.17 (#7314).

No database and no network: the run and sync stores are in memory, the source is an httpx mock
transport, and the real job (:func:`app.pact_migration_job.run_migration`) copies into the import
recorder of ``test_pact_migration_job``. What is asserted: a pass copies only what is new (by the
number of requests to the source), an unreachable source is waited for and — after 24 hours — the
sync stops itself and says so, and every other way a pass can end is recorded, never dropped. The
stored rows are ``test_pact_migration_sync_db``.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from app import pact_migration_sync as sync
from app.pact_migration_job import PactMigrationRunOptions, run_migration
from app.pact_migration_run_store import RunActiveError, as_utc
from app.pact_migration_source import SourceBroker
from tests.pact_migration_fakes import SOURCE, FakeApiomeMatrix, FakeSource, FakeStore
from tests.test_pact_migration_job import ACTOR, Importer

NOW = datetime(2026, 11, 28, 9, 0, tzinfo=timezone.utc)
CREDENTIALS = {"token": "s3cr3t-read-token"}
PACT = "/pacts/provider/API/consumer/Web/version/"


class FakeRuns(FakeStore):
    """The run store, with the reads and the reopen a pass uses."""

    RunActiveError = RunActiveError

    def __init__(self) -> None:
        super().__init__()
        self.busy = False

    def get_run(self, _db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        row = self.rows.get(run_id)
        return copy.deepcopy(row) if row and row["tenant_id"] == tenant_id else None

    def reopen_run(self, _db: Any, tenant_id: str, run_id: str) -> Optional[Dict[str, Any]]:
        if self.busy:
            raise RunActiveError("this workspace already has a migration running")
        row = self.rows.get(run_id)
        if row is None or row["tenant_id"] != tenant_id or row["mode"] != "copy":
            return None
        row.update(status="running", phase="reading", counts={}, failures=[], error=None, finished_at=None)
        return copy.deepcopy(row)


class FakeSyncs:
    """``app.pact_migration_sync_store``, in memory, keeping the database's rules."""

    def __init__(self, clock: List[datetime]) -> None:
        self.clock = clock
        self.rows: Dict[str, Dict[str, Any]] = {}
        self.opened: Optional[Dict[str, Any]] = dict(CREDENTIALS)

    def add(self, run_id: str = "run-1", **fields: Any) -> Dict[str, Any]:
        row = {
            "run_id": run_id,
            "tenant_id": "tenant-acme",
            "enabled": True,
            "interval_seconds": 900,
            "credential_ciphertext": b"sealed",
            "key_version": 1,
            "next_run_at": self.clock[0],
            "unreachable_since": None,
            "last_success_at": None,
            "passes": 0,
            "last_error": None,
            "stopped_reason": None,
            "enabled_by": None,
            "enabled_by_label": "ada@example.com",
            **fields,
        }
        self.rows[run_id] = row
        return dict(row)

    def unseal_credentials(self, ciphertext: Any, _key_version: Any) -> Optional[Dict[str, Any]]:
        return dict(self.opened) if ciphertext is not None and self.opened is not None else None

    def record_pass(
        self, _db: Any, run_id: str, *, ok: bool, error: Optional[str] = None, unreachable: bool = False
    ) -> Dict[str, Any]:
        row = self.rows[run_id]
        if ok:
            row.update(passes=row["passes"] + 1, last_success_at=self.clock[0], unreachable_since=None, last_error=None)
        else:
            row["last_error"] = error
            if unreachable and row["unreachable_since"] is None:
                row["unreachable_since"] = self.clock[0]
        return dict(row)

    def disable_sync(self, _db: Any, tenant_id: str, run_id: str, *, reason: Optional[str] = None) -> Any:
        row = self.rows[run_id]
        assert row["tenant_id"] == tenant_id
        row.update(enabled=False, credential_ciphertext=None, key_version=None, stopped_reason=reason)
        return dict(row)

    def claim_due(self, _db: Any, *, limit: int) -> List[Dict[str, Any]]:
        due = [row for row in self.rows.values() if row["enabled"] and row["next_run_at"] <= self.clock[0]][:limit]
        for row in due:
            row["next_run_at"] = self.clock[0] + timedelta(seconds=row["interval_seconds"])
        return [dict(row) for row in due]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """A finished copy from the source, kept in sync."""
    clock = [NOW]
    runs, syncs, importer, source = FakeRuns(), FakeSyncs(clock), Importer(), FakeSource()
    monkeypatch.setattr("app.pact_migration_job.store", runs)
    monkeypatch.setattr("app.pact_migration_job.import_records", importer.import_records)
    monkeypatch.setattr("app.pact_migration_job.apiome_answer", FakeApiomeMatrix(importer))
    monkeypatch.setattr("app.pact_migration_job.apiome_latest", lambda _db, _tenant, _names: {})
    monkeypatch.setattr("app.pact_migration_job._FLUSH_SECONDS", 0.0)
    monkeypatch.setattr(sync, "run_store", runs)
    monkeypatch.setattr(sync, "sync_store", syncs)
    monkeypatch.setattr(sync, "workspace_keep", lambda _db, _tenant: None)
    actors: List[Any] = []
    real_import = importer.import_records

    def import_records(db: Any, tenant_id: str, request: Any, *, actor: Any, replace_conflicts: bool) -> Any:
        actors.append(actor)
        return real_import(db, tenant_id, request, actor=ACTOR, replace_conflicts=replace_conflicts)

    monkeypatch.setattr("app.pact_migration_job.import_records", import_records)
    given: List[Dict[str, Any]] = []

    def broker(url: str, credentials: Dict[str, Any]) -> SourceBroker:
        given.append(credentials)
        return SourceBroker(url, token=credentials.get("token"), transport=source.transport())

    row = runs.row("copy", PactMigrationRunOptions().model_dump())
    run_migration(None, row, broker(SOURCE, CREDENTIALS), actor=ACTOR, clock=lambda: clock[0])
    syncs.add()

    def run_pass() -> str:
        claimed = syncs.claim_due(None, limit=5)
        assert len(claimed) == 1
        return sync.run_sync_pass(None, claimed[0], broker_factory=broker, clock=lambda: clock[0])

    return {
        "clock": clock,
        "runs": runs,
        "syncs": syncs,
        "importer": importer,
        "source": source,
        "pass": run_pass,
        "actors": actors,
        "given": given,
    }


def _publish_a_new_pact(source: FakeSource) -> None:
    """The old broker receives Web 4's pact after the copy."""
    source.docs["/matrix"]["matrix"].append(
        {
            "consumer": {"name": "Web", "version": {"number": "4"}},
            "provider": {"name": "API"},
            "pact": {"createdAt": "2026-11-28T08:00:00Z", "_links": {"self": {"href": PACT + "4"}}},
        }
    )
    source.docs[PACT + "4"] = {**source.docs[PACT + "3"], "createdAt": "2026-11-28T08:00:00Z"}


def _fetched(source: FakeSource) -> List[str]:
    return [path for path in source.paths() if path.startswith("/pacts/")]


def _later(world: Dict[str, Any], **delta: float) -> None:
    world["clock"][0] = world["clock"][0] + timedelta(**delta)


# ---------------------------------------------------------------------------------------------
# A pass copies only what is new
# ---------------------------------------------------------------------------------------------


def test_a_pass_with_nothing_new_reads_no_document_and_writes_nothing(world: Dict[str, Any]) -> None:
    written = len(world["importer"].written)
    world["source"].requests.clear()
    assert world["pass"]() == sync.OUTCOME_COPIED
    assert _fetched(world["source"]) == [] and len(world["importer"].written) == written
    assert world["source"].paths()[0] == "/"  # it asked whether the source is there first
    row = world["syncs"].rows["run-1"]
    assert row["passes"] == 1 and row["last_success_at"] == NOW and row["last_error"] is None


def test_a_pass_copies_only_what_was_published_since_by_request_count(world: Dict[str, Any]) -> None:
    written = len(world["importer"].written)
    _publish_a_new_pact(world["source"])
    world["source"].requests.clear()
    assert world["pass"]() == sync.OUTCOME_COPIED
    assert _fetched(world["source"]) == [PACT + "4"]  # one request for the one new document
    assert world["importer"].written[written:] == ["pact:api/web/4"]
    run = world["runs"].rows["run-1"]
    assert run["status"] == "completed" and run["counts"]["pact"]["copied"] == 1
    assert run["facts"]["agreement"]["asked"] == 3  # the switch-over facts are refreshed
    assert world["given"][-1] == CREDENTIALS  # the opened credentials, given to the client only


def test_a_pass_writes_as_keep_in_sync_for_whoever_switched_it_on(world: Dict[str, Any]) -> None:
    _publish_a_new_pact(world["source"])
    world["actors"].clear()
    world["pass"]()
    assert {actor.label for actor in world["actors"]} == {"keep-in-sync (ada@example.com)"}


def test_a_pass_never_starts_from_scratch_even_for_a_run_that_did(world: Dict[str, Any]) -> None:
    world["runs"].rows["run-1"]["options"]["restart"] = True
    written = len(world["importer"].written)
    world["pass"]()
    assert len(world["importer"].written) == written


# ---------------------------------------------------------------------------------------------
# An unreachable source
# ---------------------------------------------------------------------------------------------


def test_an_unreachable_source_is_waited_for_and_nothing_is_reopened(world: Dict[str, Any]) -> None:
    world["source"].docs["/"] = 503
    assert world["pass"]() == sync.OUTCOME_UNREACHABLE
    row = world["syncs"].rows["run-1"]
    assert row["enabled"] and row["unreachable_since"] == NOW
    assert "HTTP 503" in row["last_error"]
    assert world["runs"].rows["run-1"]["status"] == "completed"  # the run was not set running


def test_after_24_hours_unreachable_the_sync_stops_itself_and_says_so(world: Dict[str, Any]) -> None:
    world["source"].docs["/"] = 503
    world["pass"]()
    _later(world, hours=23, minutes=50)
    assert world["pass"]() == sync.OUTCOME_UNREACHABLE  # not yet a day
    _later(world, minutes=15)
    assert world["pass"]() == sync.OUTCOME_STOPPED
    row = world["syncs"].rows["run-1"]
    assert not row["enabled"] and row["credential_ciphertext"] is None
    assert row["stopped_reason"].startswith(
        "Keep-in-sync stopped itself: broker.example.com could not be read for 24 hours (last: "
    )
    assert row["stopped_reason"].endswith("switch it on again once the old broker answers.")
    assert world["syncs"].claim_due(None, limit=5) == []  # no pass is claimed any more


def test_a_source_that_answers_again_resets_the_clock(world: Dict[str, Any]) -> None:
    world["source"].docs["/"] = 503
    world["pass"]()
    _later(world, hours=20)
    world["source"].docs["/"] = {"_links": {}}
    assert world["pass"]() == sync.OUTCOME_COPIED
    assert world["syncs"].rows["run-1"]["unreachable_since"] is None
    world["source"].docs["/"] = 503
    _later(world, hours=20)
    assert world["pass"]() == sync.OUTCOME_UNREACHABLE  # a new day starts


def test_a_source_that_breaks_during_the_pass_counts_as_unreachable(world: Dict[str, Any]) -> None:
    world["source"].docs["/integrations"] = 502
    assert world["pass"]() == sync.OUTCOME_UNREACHABLE
    assert world["syncs"].rows["run-1"]["unreachable_since"] == NOW
    assert world["runs"].rows["run-1"]["status"] == "failed"


def test_a_refused_token_counts_toward_the_24_hours_too(world: Dict[str, Any]) -> None:
    world["source"].docs["/"] = 401
    assert world["pass"]() == sync.OUTCOME_UNREACHABLE
    assert "Could not sign in" in world["syncs"].rows["run-1"]["last_error"]


# ---------------------------------------------------------------------------------------------
# Every other way a pass ends
# ---------------------------------------------------------------------------------------------


def test_credentials_that_cannot_be_opened_stop_the_sync_with_the_reason(world: Dict[str, Any]) -> None:
    world["syncs"].opened = None
    assert world["pass"]() == sync.OUTCOME_STOPPED
    assert "can no longer be opened" in world["syncs"].rows["run-1"]["stopped_reason"]


def test_a_running_migration_makes_the_pass_wait(world: Dict[str, Any]) -> None:
    world["runs"].busy = True
    assert world["pass"]() == sync.OUTCOME_BUSY
    row = world["syncs"].rows["run-1"]
    assert row["enabled"] and "waits for the next" in row["last_error"]


def test_a_run_that_is_gone_stops_the_sync(world: Dict[str, Any]) -> None:
    del world["runs"].rows["run-1"]
    assert world["pass"]() == sync.OUTCOME_STOPPED
    assert world["syncs"].rows["run-1"]["stopped_reason"] == "Keep-in-sync stopped: the migration it copied is gone."


def test_a_failure_on_apiomes_side_is_recorded_and_the_sync_carries_on(world: Dict[str, Any]) -> None:
    _publish_a_new_pact(world["source"])
    world["importer"].explode_on = "pact"
    assert world["pass"]() == sync.OUTCOME_FAILED
    row = world["syncs"].rows["run-1"]
    assert row["enabled"] and row["unreachable_since"] is None and "Apiome could not go on" in row["last_error"]


def test_thinning_by_clean_up_rules_that_were_removed_stops_the_sync(world: Dict[str, Any]) -> None:
    world["runs"].rows["run-1"]["options"]["versions"] = "kept"
    assert world["pass"]() == sync.OUTCOME_STOPPED
    assert "clean-up rules" in world["syncs"].rows["run-1"]["stopped_reason"]
    assert world["runs"].rows["run-1"]["status"] == "failed"


# ---------------------------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------------------------


def test_the_sweep_runs_what_is_due_and_one_broken_pass_does_not_stop_the_others(world: Dict[str, Any]) -> None:
    syncs = world["syncs"]
    syncs.add("run-2")
    syncs.add("run-3", next_run_at=NOW + timedelta(minutes=5))
    seen: List[str] = []

    def run_pass(_db: Any, row: Dict[str, Any]) -> str:
        seen.append(row["run_id"])
        if row["run_id"] == "run-1":
            raise RuntimeError("boom")
        return sync.OUTCOME_COPIED

    counts = sync.process_migration_sync_sweep(None, limit=5, run_pass=run_pass)
    assert seen == ["run-1", "run-2"]  # run-3 is not due yet
    assert counts.outcomes == {sync.OUTCOME_FAILED: 1, sync.OUTCOME_COPIED: 1}
    assert as_utc(syncs.rows["run-1"]["next_run_at"]) == NOW + timedelta(minutes=15)
