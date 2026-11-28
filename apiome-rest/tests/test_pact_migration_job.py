"""A broker migration run as a job — PFX-8.16 (#7313).

No database and no network: the source is an httpx mock transport, the run store is in memory
(``tests/pact_migration_fakes.py``) and the import store is a recorder. Records still go through the
real :func:`app.pact_migration.parse_import_request`, so what the job sends is what an import reads.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

from app.consumer_contract_store import ConsumerActor
from app.pact_migration import CODE_MIGRATION_CONFLICT, MigrationOutcome
from app.pact_migration_job import (
    MAX_FAILURES,
    PactMigrationRunOptions,
    RunOptionError,
    cleanup_removals,
    latest_result_removals,
    run_migration,
    run_view,
    strip_labels_and_tags,
    validate_options,
)
from app.pact_migration_plan import KINDS, Plan
from app.pact_migration_source import SourceBroker, read_source
from app.pact_retention import RetentionKeep
from tests.pact_migration_fakes import SOURCE, FakeApiomeMatrix, FakeSource, FakeStore, documents

TOKEN = "s3cr3t-read-token"
ACTOR = ConsumerActor(user_id=None, label="ada@example.com")
NOW = datetime(2026, 11, 27, 14, 21, 7, tzinfo=timezone.utc)
KEEP = RetentionKeep(latest_per_main_branch=1)


class Importer:
    """Stands in for the import store: records what it is given and answers as told.

    Attributes:
        written: ``kind:key`` of every record written, in order (a repeat would be a duplicate). The key
            is the import's natural key — slugs, e.g. ``version:web/2`` — not the source key.
        checked: ``kind:key`` of every record checked.
        replace: The ``replace_conflicts`` each import was called with.
        refuse: ``{key: (code, message)}`` to refuse.
        records: Every record written, by key.
    """

    def __init__(self) -> None:
        self.written: List[str] = []
        self.checked: List[str] = []
        self.replace: List[bool] = []
        self.refuse: Dict[str, Any] = {}
        self.records: Dict[str, Any] = {}
        self.explode_on: Optional[str] = None

    @staticmethod
    def ident(record: Any) -> str:
        """``kind:key`` of a read record."""
        return f"{record.kind}:{record.key}"

    def _outcome(self, record: Any, done: str) -> MigrationOutcome:
        if self.ident(record) in self.refuse:
            code, message = self.refuse[self.ident(record)]
            return MigrationOutcome(
                index=record.index, kind=record.kind, key=record.key, outcome="refused", code=code, message=message
            )
        return MigrationOutcome(index=record.index, kind=record.kind, key=record.key, outcome=done)

    def import_records(self, _db: Any, tenant_id: str, request: Any, *, actor: Any, replace_conflicts: bool) -> Any:
        assert tenant_id == "tenant-acme" and actor is ACTOR
        self.replace.append(replace_conflicts)
        results = []
        for record in request.records:
            if record.kind == self.explode_on:
                raise RuntimeError("the database went away")
            outcome = self._outcome(record, "unchanged" if self.ident(record) in self.written else "created")
            if outcome.outcome != "refused":
                self.written.append(self.ident(record))
                self.records[self.ident(record)] = record
            results.append(outcome)
        return results

    def check_records(self, _db: Any, _tenant_id: str, request: Any) -> Any:
        self.checked += [self.ident(record) for record in request.records]
        return [
            self._outcome(record, "exists" if record.kind == "pacticipant" else "would-create")
            for record in request.records
        ]


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """A source, a run store and an import recorder, wired into the job."""
    store, importer, source = FakeStore(), Importer(), FakeSource()
    monkeypatch.setattr("app.pact_migration_job.store", store)
    monkeypatch.setattr("app.pact_migration_job.import_records", importer.import_records)
    monkeypatch.setattr("app.pact_migration_job.check_records", importer.check_records)
    monkeypatch.setattr("app.pact_webhook.validate_host", lambda _host: None)
    monkeypatch.setattr("app.pact_migration_job._FLUSH_SECONDS", 0.0)
    matrix = FakeApiomeMatrix(importer)
    latest: Dict[str, Any] = {}
    monkeypatch.setattr("app.pact_migration_job.apiome_answer", matrix)
    monkeypatch.setattr("app.pact_migration_job.apiome_latest", lambda _db, _tenant, names: dict(latest))

    def run(
        mode: str = "copy", options: Optional[Dict[str, Any]] = None, *, keep: Any = None, run_id: str = "run-1"
    ) -> Any:
        row = store.row(mode, PactMigrationRunOptions(**(options or {})).model_dump(), run_id=run_id)
        broker = SourceBroker(SOURCE, token=TOKEN, transport=source.transport())
        status = run_migration(None, row, broker, actor=ACTOR, keep=keep, clock=lambda: NOW)
        return status, run_view(store.rows[run_id])

    return {"store": store, "importer": importer, "source": source, "run": run, "matrix": matrix, "latest": latest}


def _counts(view: Any) -> Dict[str, Dict[str, int]]:
    return {kind.kind: kind.model_dump(exclude={"kind"}) for kind in view.kinds}


def _plan(kinds: Any = KINDS) -> Plan:
    plan = Plan()
    with SourceBroker(SOURCE, token=TOKEN, transport=FakeSource().transport()) as broker:
        read_source(broker, plan, kinds=kinds)
    return plan


# ---------------------------------------------------------------------------------------------
# The choices, as pure functions
# ---------------------------------------------------------------------------------------------


def test_only_the_latest_result_of_each_pact_is_kept() -> None:
    assert latest_result_removals(_plan()) == {"verification:API/Web/1/1"}


def test_labels_and_tags_are_left_off() -> None:
    plan = _plan()
    assert strip_labels_and_tags(plan) == (1, 1)
    assert all(record["labels"] == [] for _key, record in plan.records["pacticipant"])
    assert all(record["tags"] == [] for _key, record in plan.records["version"])


def test_clean_up_keeps_the_latest_the_deployed_and_what_the_rules_name() -> None:
    """Web: 3 is the latest of main, 2 is deployed, 1 goes. API: 10 is its latest."""
    assert cleanup_removals(_plan(), KEEP, now=NOW) == {("Web", "1")}
    assert cleanup_removals(_plan(), RetentionKeep(tags=["prod"]), now=NOW) == {("Web", "1")}
    assert cleanup_removals(_plan(), RetentionKeep(latest_per_main_branch=5), now=NOW) == set()


def test_clean_up_with_no_versions_removes_nothing() -> None:
    assert cleanup_removals(Plan(), KEEP, now=NOW) == set()


def test_choices_that_cannot_be_honoured_are_refused() -> None:
    kept = PactMigrationRunOptions(versions="kept")
    validate_options(kept, mode="copy", keep=KEEP)
    validate_options(kept, mode="dry-run", keep=None)
    with pytest.raises(RunOptionError, match="clean-up rules"):
        validate_options(kept, mode="copy", keep=None)
    with pytest.raises(RunOptionError, match="'version' must be among kinds"):
        validate_options(PactMigrationRunOptions(versions="kept", kinds=["pact"]), mode="copy", keep=KEEP)


@pytest.mark.parametrize(
    "options",
    [{"kinds": []}, {"kinds": ["pact", "teams"]}, {"kinds": ["pact", "pact"]}, {"results": "some"}, {"token": "x"}],
)
def test_unknown_choices_are_refused_not_ignored(options: Dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        PactMigrationRunOptions(**options)


def test_kinds_are_answered_in_copying_order() -> None:
    assert PactMigrationRunOptions(kinds=["webhook", "pact", "pacticipant"]).kinds == ["pacticipant", "pact", "webhook"]


# ---------------------------------------------------------------------------------------------
# A dry run
# ---------------------------------------------------------------------------------------------


def test_a_dry_run_counts_everything_and_writes_nothing(world: Dict[str, Any]) -> None:
    status, view = world["run"]("dry-run", keep=KEEP)
    assert status == "completed" and view.status == "completed" and view.phase == "done" and view.percent == 100
    assert world["importer"].written == [] and world["store"].done == {}
    counts = _counts(view)
    assert {kind: counts[kind]["total"] for kind in KINDS} == {
        "pacticipant": 2,
        "environment": 1,
        "version": 4,
        "pact": 3,
        "verification": 3,
        "deployment": 1,
        "release": 0,
        "webhook": 1,
    }
    assert counts["pacticipant"]["exists"] == 2 and counts["pact"]["would_create"] == 3
    assert view.facts["cleanup_would_skip"] == 1 and view.facts["results_not_latest"] == 1
    assert view.facts["labels_and_tags"] == 2
    assert view.can_resume is False


def test_a_dry_run_ignores_the_choices_so_the_counts_are_whole(world: Dict[str, Any]) -> None:
    _status, view = world["run"]("dry-run", {"kinds": ["pact"], "results": "none"})
    assert len(view.kinds) == len(KINDS) and len(world["importer"].checked) == 15
    assert view.facts["cleanup_would_skip"] is None


def test_what_cannot_be_carried_over_is_reported(world: Dict[str, Any]) -> None:
    _status, view = world["run"]("dry-run")
    assert {(finding.kind, finding.subject) for finding in view.findings} == {("pacticipant", "API"), ("webhook", "ci")}
    assert any("waiting for a value" in finding.detail for finding in view.findings)
    assert view.not_read and "teams" in " ".join(view.not_read)


# ---------------------------------------------------------------------------------------------
# A copy
# ---------------------------------------------------------------------------------------------


def test_a_copy_writes_every_record_once_in_order(world: Dict[str, Any]) -> None:
    status, view = world["run"]()
    assert status == "completed" and view.percent == 100 and view.failures == []
    written = world["importer"].written
    assert len(written) == len(set(written)) == 15
    kinds = [key.split(":", 1)[0] for key in written]
    assert kinds == sorted(kinds, key=KINDS.index)
    assert len(world["store"].done["run-1"]) == 15
    assert all(kind.copied == kind.total and kind.done == kind.total for kind in view.kinds)
    assert world["importer"].replace and not any(world["importer"].replace)


def test_the_token_is_never_written_to_the_run(world: Dict[str, Any]) -> None:
    world["run"]()
    assert TOKEN not in repr(world["store"].saves) and TOKEN not in repr(world["store"].rows)


def test_only_the_chosen_kinds_are_read_and_copied(world: Dict[str, Any]) -> None:
    _status, view = world["run"](options={"kinds": ["environment", "webhook"]})
    assert [kind.kind for kind in view.kinds] == ["environment", "webhook"]
    assert {key.split(":", 1)[0] for key in world["importer"].written} == {"environment", "webhook"}
    assert not any(path.startswith(("/pacticipants", "/matrix")) for path in world["source"].paths())


def test_labels_and_tags_left_behind_are_said_in_the_log(world: Dict[str, Any]) -> None:
    _status, view = world["run"](options={"labels_and_tags": False})
    records = world["importer"].records
    assert records["pacticipant:web"].labels == [] or not records["pacticipant:web"].labels
    assert not records["version:web/2"].tags
    assert any("1 label(s) and 1 tag(s) behind" in line.text for line in view.log)


@pytest.mark.parametrize("results,skipped", [("all", 0), ("latest", 1), ("none", 3)])
def test_result_history_depth(world: Dict[str, Any], results: str, skipped: int) -> None:
    _status, view = world["run"](options={"results": results})
    counts = _counts(view)["verification"]
    assert counts["skipped"] == skipped and counts["copied"] == 3 - skipped and counts["done"] == 3
    if skipped:
        assert any("verification" in line.text and "skipped" in line.text for line in view.log)


def test_versions_clean_up_would_remove_stay_behind_with_their_pacts_and_results(world: Dict[str, Any]) -> None:
    _status, view = world["run"](options={"versions": "kept"}, keep=KEEP)
    counts = _counts(view)
    assert counts["version"]["skipped"] == 1 and counts["version"]["copied"] == 3
    assert counts["pact"]["skipped"] == 1 and counts["verification"]["skipped"] == 2
    written = world["importer"].written
    assert "version:web/1" not in written and "pact:api/web/1" not in written
    assert "deployment:web/2@production" in written
    assert any("clean-up would remove" in line.text for line in view.log)


def test_a_result_for_a_provider_version_left_behind_is_skipped(world: Dict[str, Any]) -> None:
    """Web 1 is the provider version of API → Web's result here; clean-up leaves Web 1 behind."""
    docs = documents()
    docs["/pacts/provider/API/consumer/Web/version/2/verification-results/3"]["providerApplicationVersion"] = "1"
    docs["/pacts/provider/API/consumer/Web/version/2/verification-results/3"]["success"] = True
    world["source"].docs = docs
    # Make "API" the pacticipant whose version 1 is removed: give it two versions on main.
    docs["/pacticipants/API/versions"]["_embedded"]["versions"] = [
        {"number": "10", "createdAt": "2025-03-02T09:00:00Z", "_embedded": {"branchVersions": [{"name": "main"}]}},
        {"number": "1", "createdAt": "2025-03-01T09:00:00Z", "_embedded": {"branchVersions": [{"name": "main"}]}},
    ]
    docs["/pacticipants"]["_embedded"]["pacticipants"][1]["mainBranch"] = "main"
    _status, view = world["run"](options={"versions": "kept"}, keep=KEEP)
    assert "verification:api/web/2/3" not in world["importer"].written
    assert any("clean-up would remove its provider version" in line.text for line in view.log)
    assert _counts(view)["verification"]["done"] == 3


def test_a_conflict_keeps_apiomes_record_and_is_not_a_failure(world: Dict[str, Any]) -> None:
    world["importer"].refuse["pact:api/web/2"] = (CODE_MIGRATION_CONFLICT, "Apiome has another pact for it")
    status, view = world["run"]()
    counts = _counts(view)["pact"]
    assert status == "completed" and view.failures == [] and view.can_resume is False
    assert counts["skipped"] == 1 and counts["failed"] == 0 and view.facts["conflicts_kept"] == 1
    assert any("kept Apiome's" in line.text for line in view.log)


def test_replace_is_passed_to_the_import_and_a_conflict_left_is_a_failure(world: Dict[str, Any]) -> None:
    world["importer"].refuse["verification:api/web/1/2"] = (CODE_MIGRATION_CONFLICT, "another result has number 2")
    _status, view = world["run"](options={"conflicts": "replace"})
    assert all(world["importer"].replace)
    assert [(failure.kind, failure.key, failure.code) for failure in view.failures] == [
        ("verification", "API/Web/1/2", CODE_MIGRATION_CONFLICT)
    ]
    assert view.can_resume is True


def test_a_refused_record_is_listed_with_its_reason_and_the_rest_is_copied(world: Dict[str, Any]) -> None:
    world["importer"].refuse["version:web/2"] = ("pact-version-invalid", "the number is not usable")
    status, view = world["run"]()
    assert status == "completed" and len(world["importer"].written) == 14
    assert [failure.model_dump() for failure in view.failures] == [
        {"kind": "version", "key": "Web/2", "code": "pact-version-invalid", "message": "the number is not usable"}
    ]
    assert _counts(view)["version"]["failed"] == 1 and view.can_resume is True
    assert "version:Web/2" not in world["store"].done["run-1"]
    assert any("failed: the number is not usable" in line.text for line in view.log)


def test_a_document_the_source_lost_is_a_failure_with_the_reason(world: Dict[str, Any]) -> None:
    del world["source"].docs["/pacts/provider/API/consumer/Web/version/3"]
    _status, view = world["run"]()
    assert [(failure.key, failure.code) for failure in view.failures] == [("API/Web/3", "source-unreadable")]
    assert "404" in view.failures[0].message


def test_more_failures_than_are_kept_are_counted_not_dropped(world: Dict[str, Any]) -> None:
    versions = [{"number": str(n), "createdAt": "2025-03-01T09:00:00Z"} for n in range(MAX_FAILURES + 5)]
    world["source"].docs["/pacticipants/Web/versions"] = {"_embedded": {"versions": versions}}
    world["importer"].refuse = {f"version:web/{n}": ("pact-version-invalid", "no") for n in range(MAX_FAILURES + 5)}
    _status, view = world["run"](options={"kinds": ["version"]})
    assert len(view.failures) == MAX_FAILURES and view.failures_dropped == 5
    assert _counts(view)["version"]["failed"] == MAX_FAILURES + 5


# ---------------------------------------------------------------------------------------------
# Stopping, resuming, failing
# ---------------------------------------------------------------------------------------------


def test_a_stopped_run_resumes_without_duplicates(world: Dict[str, Any]) -> None:
    store, importer = world["store"], world["importer"]
    store.stop_when = lambda: len(importer.written) >= 5
    status, view = world["run"]()
    assert status == "stopped" and view.status == "stopped" and view.can_resume is True
    first = list(importer.written)
    assert 0 < len(first) < 15 and len(store.done["run-1"]) == len(first)

    store.stop_when = None
    status, view = world["run"]()
    assert status == "completed"
    assert len(importer.written) == len(set(importer.written)) == 15
    assert sum(kind.skipped for kind in view.kinds) == len(first)
    assert any("an earlier run copied it" in line.text for line in view.log)


def test_from_scratch_sends_everything_again(world: Dict[str, Any]) -> None:
    world["run"]()
    world["run"](options={"restart": True}, run_id="run-2")
    assert len(world["importer"].written) == 30


def test_a_second_run_from_the_same_source_copies_only_what_is_new(world: Dict[str, Any]) -> None:
    world["run"]()
    world["source"].docs["/pacticipants/API/versions"]["_embedded"]["versions"].insert(
        0, {"number": "11", "createdAt": "2025-03-04T09:00:00Z"}
    )
    _status, view = world["run"](run_id="run-2")
    assert world["importer"].written[15:] == ["version:api/11"]
    assert _counts(view)["version"] == {**_counts(view)["version"], "copied": 1, "skipped": 4, "total": 5}


def test_a_source_that_refuses_the_token_fails_the_run_with_the_reason(world: Dict[str, Any]) -> None:
    world["source"].docs["/pacticipants"] = 401
    status, view = world["run"]()
    assert status == "failed" and view.can_resume is True
    assert view.error == "Could not sign in to broker.example.com (401). Check the token."
    assert world["importer"].written == []


def test_a_break_on_apiomes_side_ends_the_run_as_failed_and_resumable(world: Dict[str, Any]) -> None:
    world["importer"].explode_on = "pact"
    status, view = world["run"]()
    assert status == "failed" and "RuntimeError" in (view.error or "") and view.can_resume is True
    assert "the database went away" not in (view.error or "")
    assert {key.split(":", 1)[0] for key in world["importer"].written} == {"pacticipant", "environment", "version"}


def test_a_dry_run_cannot_be_resumed(world: Dict[str, Any]) -> None:
    world["source"].docs["/pacticipants"] = 500
    status, view = world["run"]("dry-run")
    assert status == "failed" and view.can_resume is False


def test_the_log_keeps_its_newest_lines_and_numbers_them(world: Dict[str, Any]) -> None:
    _status, view = world["run"]()
    assert view.log_seq == view.log[-1].seq and view.log[0].text.startswith("14:21:07 Reading broker.example.com")
    newer = run_view(world["store"].rows["run-1"], after=view.log_seq - 2)
    assert [line.seq for line in newer.log] == [view.log_seq - 1, view.log_seq]


# ---------------------------------------------------------------------------------------------
# The registry of running jobs
# ---------------------------------------------------------------------------------------------


def test_jobs_run_on_their_own_thread_and_free_their_slot() -> None:
    import threading

    from app.pact_migration_job import MigrationJobs

    jobs = MigrationJobs(limit=1)
    release, started, names = threading.Event(), threading.Event(), []

    def work() -> None:
        names.append((threading.current_thread().name, threading.current_thread().daemon))
        started.set()
        release.wait(5)

    assert jobs.has_room()
    jobs.start(work)
    assert started.wait(5) and not jobs.has_room()
    release.set()
    for _ in range(200):
        if jobs.has_room():
            break
        threading.Event().wait(0.01)
    assert jobs.has_room() and names == [("pact-migration", True)]


def test_a_job_that_raises_still_frees_its_slot() -> None:
    import threading

    from app.pact_migration_job import MigrationJobs

    jobs = MigrationJobs(limit=1)

    def work() -> None:
        raise RuntimeError("broke")

    hook, threading.excepthook = threading.excepthook, lambda _args: None
    try:
        jobs.start(work)
        for _ in range(200):
            if jobs.has_room():
                break
            threading.Event().wait(0.01)
    finally:
        threading.excepthook = hook
    assert jobs.has_room()


# ---------------------------------------------------------------------------------------------
# Switch over: the agreement check and who has moved — PFX-8.17 (#7314)
# ---------------------------------------------------------------------------------------------


def _question_paths(source: FakeSource) -> List[str]:
    return [str(request.url) for request in source.requests if "latestby=cvp" in str(request.url)]


def test_after_a_copy_both_brokers_are_asked_the_same_questions_and_agree(world: Dict[str, Any]) -> None:
    status, view = world["run"]()
    assert status == "completed"
    agreement = view.facts["agreement"]
    assert agreement["asked"] == 3 and agreement["agree"] == 3 and agreement["differences"] == []
    assert agreement["checked_at"] == "2026-11-27T14:21:07Z"
    asked = [question.label() for question in world["matrix"].asked]
    assert asked == ["Web 2 → production", "Web 3 → production", "API 10 → production"]
    assert len(_question_paths(world["source"])) == 3  # the same three, asked of the source
    assert any("3 of 3 can-i-deploy answer(s) agree" in line.text for line in view.log)


def test_a_deliberately_missing_result_is_reported_as_a_difference(world: Dict[str, Any]) -> None:
    world["importer"].refuse["verification:api/web/2/3"] = ("pact-migration-invalid", "its result is malformed")
    _status, view = world["run"]()
    agreement = view.facts["agreement"]
    assert agreement["asked"] == 3 and agreement["agree"] == 1
    web = next(d for d in agreement["differences"] if d["question"] == "Web 2 → production")
    assert web["source"] == "yes" and web["apiome"] == "unknown"
    assert web["cause"] == "the verification result of Web 2 by API 10 was not copied: its result is malformed"
    api = next(d for d in agreement["differences"] if d["question"] == "API 10 → production")
    assert "verification result of Web 2 by API 10 was not copied" in api["cause"]


def test_without_versions_the_latest_pact_of_each_consumer_is_asked_about(world: Dict[str, Any]) -> None:
    _status, view = world["run"](options={"kinds": [kind for kind in KINDS if kind != "version"]})
    # Without versions read, the latest of each comes from the pacts: Web 3 only, plus the deployment.
    assert [d["question"] for d in view.facts["agreement"]["differences"]] == []
    assert view.facts["agreement"]["asked"] == 2


def test_a_question_the_old_broker_cannot_answer_is_a_difference_not_dropped(world: Dict[str, Any]) -> None:
    world["source"].docs["/matrix?q[][pacticipant]=Web&q[][version]=3&latestby=cvp&environment=production"] = 400
    _status, view = world["run"]()
    agreement = view.facts["agreement"]
    assert agreement["asked"] == 3 and agreement["agree"] == 2
    [difference] = agreement["differences"]
    assert difference["source"] == "no answer" and difference["apiome"] == "unknown"
    assert difference["cause"].startswith("broker.example.com could not answer it — a selector it does not support?")


def test_the_check_can_be_skipped_and_a_dry_run_never_asks(world: Dict[str, Any]) -> None:
    _status, view = world["run"](options={"agreement_questions": 0})
    assert "agreement" not in view.facts and _question_paths(world["source"]) == []
    assert "moved" in view.facts  # who has moved is still listed
    _status, dry = world["run"]("dry-run", run_id="run-2")
    assert "agreement" not in dry.facts and "moved" not in dry.facts and _question_paths(world["source"]) == []


def test_the_limit_caps_the_questions_and_says_how_many_were_left_out(world: Dict[str, Any]) -> None:
    _status, view = world["run"](options={"agreement_questions": 1})
    assert view.facts["agreement"]["asked"] == 1 and view.facts["agreement"]["not_asked"] == 2


def test_a_broken_check_is_said_and_the_copy_stands(world: Dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*_args: Any) -> Any:
        raise RuntimeError("the matrix went away")

    monkeypatch.setattr("app.pact_migration_job.apiome_answer", explode)
    monkeypatch.setattr("app.pact_migration_job.apiome_latest", explode)
    status, view = world["run"]()
    assert status == "completed"
    assert view.facts["agreement"] == {"error": "the agreement check could not run (RuntimeError)"}
    assert view.facts["moved"] == {"error": "who has moved could not be read (RuntimeError)"}


def test_who_has_moved_lists_where_each_pacticipant_last_published(world: Dict[str, Any]) -> None:
    world["latest"]["API"] = datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc)  # verified in Apiome since
    world["latest"]["Web"] = datetime(2025, 3, 3, 9, 0, tzinfo=timezone.utc)  # only its copied pact
    _status, view = world["run"]()
    moved = view.facts["moved"]
    assert moved["total"] == 2 and moved["moved"] == 1
    assert moved["pacticipants"] == [
        {"name": "Web", "last": "source", "apiome_at": "2025-03-03T09:00:00Z", "source_at": "2025-03-03T09:00:00Z"},
        {"name": "API", "last": "apiome", "apiome_at": "2026-11-27T09:00:00Z", "source_at": "2025-03-02T09:00:00Z"},
    ]


def test_a_stop_asked_for_during_the_check_still_stops_the_run(world: Dict[str, Any]) -> None:
    world["store"].stop_when = lambda: world["store"].rows["run-1"].get("phase") == "checking"
    status, view = world["run"]()
    assert status == "stopped" and "agreement" not in view.facts


def _documents_fetched(source: FakeSource) -> List[str]:
    return [path for path in source.paths() if path.startswith("/pacts/")]


def test_an_incremental_run_fetches_and_copies_only_what_is_new_by_request_count(world: Dict[str, Any]) -> None:
    source = world["source"]
    world["run"]()
    assert len(_documents_fetched(source)) == 6  # 3 pacts and 3 results
    written = len(world["importer"].written)

    source.requests.clear()
    world["run"](run_id="run-1b")
    assert _documents_fetched(source) == []  # nothing new: no document is read again
    assert len(world["importer"].written) == written  # and nothing is written

    pact = "/pacts/provider/API/consumer/Web/version/"
    source.docs["/matrix"]["matrix"].append(
        {
            "consumer": {"name": "Web", "version": {"number": "4"}},
            "provider": {"name": "API"},
            "pact": {"createdAt": "2025-03-05T09:00:00Z", "_links": {"self": {"href": pact + "4"}}},
        }
    )
    source.docs[pact + "4"] = {**source.docs[pact + "3"], "createdAt": "2025-03-05T09:00:00Z"}
    source.requests.clear()
    _status, view = world["run"](run_id="run-1c")
    assert _documents_fetched(source) == [pact + "4"]  # one request for the one new pact
    assert world["importer"].written[written:] == ["pact:api/web/4"]
    assert _counts(view)["pact"]["copied"] == 1 and _counts(view)["pact"]["skipped"] == 3
