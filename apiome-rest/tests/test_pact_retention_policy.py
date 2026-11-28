"""Stored clean-up rules — PFX-8.14 (#7311).

The models and schedule (:mod:`app.pact_retention_policy`) are pure; the store
(:mod:`app.pact_retention_policy_store`) is run against a fake database that answers by SQL text
(``test_pact_retention_policy_db`` runs it against the real schema). Pinned here:

* a rule set that would remove a deployed or released version is refused, never saved;
* an unknown field, a repeated tag and an age without a count are refused with the reason;
* the nightly run is due once a day after 02:00 UTC, and the next run time follows;
* **the preview equals what the next nightly sweep removes**;
* the nightly run skips a workspace another replica holds or that already ran, and stores why a
  refused run deleted nothing;
* Recently deleted merges pacticipants and versions newest first, pages with a cursor, refuses a
  forged cursor, and dates each purge by the workspace's window;
* saving is audited in the same transaction.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import pytest
from pydantic import ValidationError

from app import pact_retention_policy_store as store
from app.consumer_contract_store import ConsumerActor
from app.pact_retention import RetentionError
from app.pact_retention_policy import (
    CODE_KEEPS_IN_USE,
    RetentionRules,
    is_due,
    keep_of,
    next_run_at,
    rules_from_row,
)

TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "99999999-9999-4999-8999-999999999999"
P1 = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2026, 11, 28, 3, 0, tzinfo=timezone.utc)
ACTOR = ConsumerActor(user_id="33333333-3333-4333-8333-333333333333", label="ada@example.com")


# ---------------------------------------------------------------------------------------------
# Models and schedule
# ---------------------------------------------------------------------------------------------


def test_deployed_and_released_versions_cannot_be_turned_off() -> None:
    with pytest.raises(RetentionError) as caught:
        keep_of(RetentionRules(keep_deployed_or_released=False))
    assert caught.value.code == CODE_KEEPS_IN_USE
    assert "Deployed and released versions are always kept." in str(caught.value)


def test_rules_map_to_the_keep_selectors() -> None:
    keep = keep_of(
        RetentionRules(
            keep_main_branch_latest=5, keep_other_branch_latest=1, keep_other_branch_days=90, keep_tags=["keep"]
        )
    )
    assert keep.deployed_or_released is True
    assert (keep.latest_per_main_branch, keep.latest_per_other_branch, keep.other_branch_days) == (5, 1, 90)
    assert keep.tags == ["keep"] and keep.latest_per_branch is None and keep.created_within_days is None


def test_bad_rules_are_refused_with_a_reason() -> None:
    with pytest.raises(ValidationError, match="extra"):
        RetentionRules(keep_everything=True)
    with pytest.raises(ValidationError, match="keep_other_branch_days needs keep_other_branch_latest"):
        RetentionRules(keep_other_branch_days=30)
    with pytest.raises(ValidationError, match="more than once"):
        RetentionRules(keep_tags=["prod", "prod"])
    with pytest.raises(ValidationError):
        RetentionRules(restore_window_days=0)
    with pytest.raises(ValidationError):
        RetentionRules(restore_window_days=366)
    with pytest.raises(ValidationError):
        RetentionRules(keep_main_branch_latest=1001)


def test_the_defaults_keep_clean_up_off() -> None:
    rules = RetentionRules()
    assert rules.nightly_enabled is False and rules.restore_window_days == 30 and rules.keep_tags == []
    assert rules_from_row(None) == rules


def test_the_nightly_run_is_due_once_a_day_after_two() -> None:
    before = datetime(2026, 11, 28, 1, 59, tzinfo=timezone.utc)
    after = datetime(2026, 11, 28, 2, 1, tzinfo=timezone.utc)
    assert not is_due(before, None)
    assert is_due(after, None)
    assert is_due(after, datetime(2026, 11, 27, 2, 5, tzinfo=timezone.utc))
    assert not is_due(after, datetime(2026, 11, 28, 2, 0, 30, tzinfo=timezone.utc))


def test_the_next_run_time() -> None:
    before = datetime(2026, 11, 28, 1, 0, tzinfo=timezone.utc)
    assert next_run_at(before, None, enabled=False) is None
    assert next_run_at(before, None, enabled=True) == datetime(2026, 11, 28, 2, 0, tzinfo=timezone.utc)
    assert next_run_at(NOW, None, enabled=True) == NOW  # due: runs on the next tick
    ran = datetime(2026, 11, 28, 2, 3, tzinfo=timezone.utc)
    assert next_run_at(NOW, ran, enabled=True) == datetime(2026, 11, 29, 2, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------
# A fake database that answers by SQL text
# ---------------------------------------------------------------------------------------------

Answer = Callable[[str, Tuple[Any, ...]], List[Dict[str, Any]]]


class _Cursor:
    """A cursor whose answers come from the fake database's routes."""

    def __init__(self, db: "_Db") -> None:
        self.db = db
        self._rows: List[Dict[str, Any]] = []
        self.rowcount = 0

    def execute(self, query: str, params: Tuple[Any, ...] = ()) -> None:
        self.db.statements.append((query, params))
        self._rows = self.db.answer(query, params)
        self.rowcount = len(self._rows)

    def fetchall(self) -> List[Dict[str, Any]]:
        return self._rows

    def fetchone(self) -> Optional[Dict[str, Any]]:
        return self._rows[0] if self._rows else None


class _Db:
    """``execute_query`` / ``_guarded_tx`` over a list of ``(sql fragment, answer)`` routes."""

    def __init__(self, routes: Sequence[Tuple[str, Any]]) -> None:
        self.routes = list(routes)
        self.statements: List[Tuple[str, Tuple[Any, ...]]] = []
        self.audits: List[Dict[str, Any]] = []
        self.committed = 0

    def answer(self, query: str, params: Tuple[Any, ...]) -> List[Dict[str, Any]]:
        for fragment, answer in self.routes:
            if fragment in query:
                return answer(query, params) if callable(answer) else list(answer)
        return []

    def execute_query(self, query: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        self.statements.append((query, params))
        return self.answer(query, params)

    def _guarded_tx(self, work: Callable[[Any], Any]) -> Any:
        result = work(_Cursor(self))
        if result is not None:
            self.committed += 1
        return result

    def _append_access_audit(self, cursor: Any, **row: Any) -> None:
        self.audits.append(row)


def _pacticipant_row(main_branch: Optional[str] = "main") -> Dict[str, Any]:
    return {"id": P1, "tenant_id": TENANT, "slug": "orders-ui", "name": "Orders UI", "main_branch": main_branch}


def _version(
    number: str, seq: int, *, branches: Sequence[str] = ("main",), days_old: int = 100, **extra: Any
) -> Dict[str, Any]:
    return {
        "id": f"00000000-0000-4000-8000-{seq:012d}",
        "pacticipant_id": P1,
        "number": number,
        "seq": seq,
        "created_at": NOW - timedelta(days=days_old),
        "branches": list(branches),
        "in_use": extra.get("in_use", False),
        "tags": extra.get("tags", []),
    }


VERSIONS = [
    _version("3.2.1", 1, in_use=True),
    _version("3.2.2", 2),
    _version("3.2.3", 3),
    _version("3.2.4", 4, tags=["keep"]),
    _version("f-1", 5, branches=("feat/x",), days_old=200),
    _version("f-2", 6, branches=("feat/y",), days_old=2),
    _version("3.2.9", 7),
]

POLICY_ROW = {
    "keep_main_branch_latest": 1,
    "keep_other_branch_latest": 1,
    "keep_other_branch_days": 90,
    "keep_tags": ["keep"],
    "nightly_enabled": True,
    "restore_window_days": 14,
    "last_run_at": None,
    "last_run_deleted": None,
    "last_run_remaining": None,
    "last_run_error": None,
    "updated_by_label": "ada@example.com",
    "updated_at": NOW - timedelta(days=1),
}


def _registry(policy: Optional[Dict[str, Any]] = POLICY_ROW, versions: Sequence[Dict[str, Any]] = VERSIONS) -> _Db:
    """A database holding one pacticipant, its versions and the policy row."""

    def soft_delete(_query: str, params: Tuple[Any, ...]) -> List[Dict[str, Any]]:
        return [{"id": vid} for vid in params[5]]

    return _Db(
        [
            ("FOR UPDATE SKIP LOCKED", [policy] if policy else []),
            ("FROM apiome.pact_retention_policy WHERE tenant_id", [policy] if policy else []),
            ("SELECT tenant_id::text AS tenant_id\n    FROM apiome.pact_retention_policy", [{"tenant_id": TENANT}]),
            ("UPDATE apiome.pact_retention_policy", [{"tenant_id": TENANT}]),
            ("UPDATE apiome.pacticipant_version", soft_delete),
            ("FROM apiome.pacticipant_version v\n    WHERE v.pacticipant_id = ANY", list(versions)),
            (
                "FROM apiome.pacticipant_version v\n    WHERE v.id = ANY",
                lambda _q, p: [{"id": vid, "pacts": 2, "results": 3} for vid in p[0]],
            ),
            ("FROM apiome.pacticipant", [_pacticipant_row()]),
        ]
    )


# ---------------------------------------------------------------------------------------------
# Read and save
# ---------------------------------------------------------------------------------------------


def test_a_workspace_without_rules_reads_the_defaults() -> None:
    policy = store.get_policy(_Db([]), TENANT, can_edit=False, now=NOW)
    assert policy.configured is False and policy.nightly_enabled is False and policy.can_edit is False
    assert policy.next_run_at is None and policy.last_run is None


def test_a_saved_policy_reads_back_with_its_next_run() -> None:
    policy = store.get_policy(_registry(), TENANT, can_edit=True, now=NOW)
    assert policy.configured and policy.keep_tags == ["keep"] and policy.restore_window_days == 14
    assert policy.updated_by == "ada@example.com" and policy.next_run_at == NOW.isoformat()


def test_saving_a_rule_set_that_removes_deployed_versions_writes_nothing() -> None:
    db = _registry()
    with pytest.raises(RetentionError) as caught:
        store.save_policy(db, TENANT, RetentionRules(keep_deployed_or_released=False), actor=ACTOR)
    assert caught.value.code == CODE_KEEPS_IN_USE
    assert db.statements == [] and db.audits == []


def test_saving_upserts_for_the_callers_tenant_and_audits_in_the_transaction() -> None:
    db = _Db([("INSERT INTO apiome.pact_retention_policy", [POLICY_ROW])])
    rules = RetentionRules(keep_main_branch_latest=5, keep_tags=["keep"], nightly_enabled=True)
    saved = store.save_policy(db, TENANT, rules, actor=ACTOR, now=NOW)
    ((query, params),) = db.statements
    assert params[0] == TENANT and params[4] == ["keep"] and params[7] == ACTOR.user_id
    assert db.audits[0]["action"] == "pacts.retention.policy" and db.audits[0]["tenant_id"] == TENANT
    assert db.audits[0]["detail"]["keep_main_branch_latest"] == 5
    assert saved.can_edit is True and saved.configured is True


# ---------------------------------------------------------------------------------------------
# The preview is the next sweep
# ---------------------------------------------------------------------------------------------


def _deleted_ids(db: _Db) -> List[str]:
    return sorted(
        vid for query, params in db.statements if "UPDATE apiome.pacticipant_version" in query for vid in params[5]
    )


def test_the_preview_equals_what_the_next_nightly_sweep_removes() -> None:
    preview = store.preview_policy(_registry(), TENANT, now=NOW)
    previewed = sorted(d.number for row in preview.plan.pacticipants for d in row.deletions)

    sweep_db = _registry()
    totals = store.run_nightly_clean_up(sweep_db, now=NOW)
    by_id = {row["id"]: row["number"] for row in VERSIONS}
    swept = sorted(by_id[vid] for vid in _deleted_ids(sweep_db))

    assert previewed == swept == ["3.2.2", "3.2.3", "f-1"]
    assert totals == {"tenants": 1, "deleted": 3, "refused": 0}
    assert preview.plan.deleted == 3 and preview.plan.evaluated == len(VERSIONS)
    # Deployed (3.2.1), tagged (3.2.4), the latest of main (3.2.9) and of a recent branch (f-2) stay.
    assert preview.plan.matched_by["deployed_or_released"] == 1 and preview.plan.matched_by["tagged"] == 1


def test_a_draft_preview_does_not_need_saving_and_counts_what_goes_with_it() -> None:
    preview = store.preview_policy(_registry(), TENANT, RetentionRules(keep_main_branch_latest=10), now=NOW)
    assert preview.draft is True and preview.nightly_enabled is False and preview.next_run_at is None
    assert preview.plan.deleted == 2  # f-1 and f-2: no other-branch or tag rule in the draft
    assert (preview.plan.pacts, preview.plan.results) == (4, 6)
    listed = preview.plan.pacticipants[0].deletions
    assert {(d.number, d.pacts, d.results) for d in listed} == {("f-1", 2, 3), ("f-2", 2, 3)}
    assert preview.plan.grace_days == 30


def test_a_draft_that_removes_deployed_versions_is_refused() -> None:
    with pytest.raises(RetentionError) as caught:
        store.preview_policy(_registry(), TENANT, RetentionRules(keep_deployed_or_released=False), now=NOW)
    assert caught.value.code == CODE_KEEPS_IN_USE


# ---------------------------------------------------------------------------------------------
# The nightly run
# ---------------------------------------------------------------------------------------------


def test_the_nightly_run_records_what_it_did_and_who_deleted() -> None:
    db = _registry()
    store.run_nightly_clean_up(db, now=NOW)
    deletes = [params for query, params in db.statements if "UPDATE apiome.pacticipant_version" in query]
    assert deletes and deletes[0][1] == "Clean-up" and deletes[0][2] == store.NIGHTLY_REASON
    record = [params for query, params in db.statements if "SET last_run_at" in query]
    assert record == [(NOW, 3, 0, None, TENANT)]
    assert [audit["action"] for audit in db.audits] == ["pacts.retention.nightly"]


def test_nothing_runs_before_two_utc() -> None:
    db = _registry()
    assert store.run_nightly_clean_up(db, now=NOW.replace(hour=1)) == {"tenants": 0, "deleted": 0, "refused": 0}
    assert db.statements == []


def test_a_workspace_another_replica_holds_or_that_already_ran_is_skipped() -> None:
    held = _registry()
    held.routes[0] = ("FOR UPDATE SKIP LOCKED", [])
    assert store.run_nightly_clean_up(held, now=NOW)["tenants"] == 0
    assert _deleted_ids(held) == []

    ran = _registry(policy={**POLICY_ROW, "last_run_at": NOW - timedelta(minutes=30)})
    assert store.run_nightly_clean_up(ran, now=NOW)["tenants"] == 0
    assert _deleted_ids(ran) == []


def test_a_refused_run_deletes_nothing_and_says_why() -> None:
    db = _registry()
    original = store.plan_tx

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise RetentionError("pact-retention-too-many-versions", "more than 100000 live versions")

    store.plan_tx = refuse  # type: ignore[assignment]
    try:
        totals = store.run_nightly_clean_up(db, now=NOW)
    finally:
        store.plan_tx = original  # type: ignore[assignment]
    assert totals["refused"] == 1 and _deleted_ids(db) == []
    record = [params for query, params in db.statements if "SET last_run_at" in query]
    assert record == [(NOW, 0, None, "more than 100000 live versions", TENANT)]


# ---------------------------------------------------------------------------------------------
# Recently deleted
# ---------------------------------------------------------------------------------------------


def _deleted_row(kind: str, item_id: str, hours_ago: int, **extra: Any) -> Dict[str, Any]:
    return {
        "kind": kind,
        "id": item_id,
        "pacticipant_id": P1,
        "pacticipant_slug": "orders-ui",
        "pacticipant_name": "Orders UI",
        "number": extra.get("number"),
        "deleted_at": NOW - timedelta(hours=hours_ago),
        "deleted_by": extra.get("deleted_by"),
        "cause": extra.get("cause", kind),
        "reason": None,
        "versions": extra.get("versions", 0),
        "pacts": 1,
        "results": 2,
    }


def _deleted_db(pacticipants: List[Dict[str, Any]], versions: List[Dict[str, Any]]) -> _Db:
    return _Db(
        [
            ("FROM apiome.pact_retention_policy WHERE tenant_id", [POLICY_ROW]),
            ("SELECT 'pacticipant' AS kind", pacticipants),
            ("SELECT 'version' AS kind", versions),
        ]
    )


def test_recently_deleted_merges_newest_first_and_dates_the_purge_by_the_window() -> None:
    db = _deleted_db(
        [_deleted_row("pacticipant", "aaaaaaaa-0000-4000-8000-000000000001", 11 * 24, versions=41, deleted_by="Ada")],
        [_deleted_row("version", "bbbbbbbb-0000-4000-8000-000000000002", 48, number="3.2.9", cause="retention")],
    )
    page = store.list_recently_deleted(db, TENANT, can_restore=True)
    assert [item.kind for item in page.items] == ["version", "pacticipant"]
    version, pacticipant = page.items
    assert version.deleted_by == "Clean-up" and version.number == "3.2.9"
    assert pacticipant.versions == 41 and pacticipant.deleted_by == "Ada"
    assert version.purge_after == (NOW - timedelta(hours=48) + timedelta(days=14)).isoformat()
    assert page.restore_window_days == 14 and page.can_restore is True and page.has_more is False
    # Both reads are scoped to the caller's tenant.
    reads = [params for query, params in db.statements if "AS kind" in query]
    assert all(params[0] == TENANT for params in reads)


def test_recently_deleted_pages_with_a_cursor() -> None:
    versions = [
        _deleted_row("version", f"bbbbbbbb-0000-4000-8000-00000000000{n}", n, number=f"1.{n}") for n in range(1, 4)
    ]
    db = _deleted_db([], versions)
    first = store.list_recently_deleted(db, TENANT, limit=2)
    assert [item.number for item in first.items] == ["1.1", "1.2"] and first.has_more and first.next_cursor
    store.list_recently_deleted(db, TENANT, limit=2, after=first.next_cursor)
    keyset = [params for query, params in db.statements if "(%s::timestamptz, %s::uuid)" in query]
    assert len(keyset) == 2 and keyset[0][0] == TENANT and keyset[0][2] == first.items[-1].id


@pytest.mark.parametrize("cursor", ["not-base64!", "bm90IGEgY3Vyc29y", "MjAyNi0xMS0yOHxub3QtYS11dWlk"])
def test_a_forged_cursor_is_refused(cursor: str) -> None:
    with pytest.raises(RetentionError) as caught:
        store.list_recently_deleted(_deleted_db([], []), TENANT, after=cursor)
    assert caught.value.code == store.CODE_BAD_CURSOR


def test_recently_deleted_without_a_tenant_reads_nothing() -> None:
    db = _deleted_db([_deleted_row("pacticipant", "aaaaaaaa-0000-4000-8000-000000000001", 1)], [])
    page = store.list_recently_deleted(db, "not-a-tenant")
    assert page.items == [] and not any("AS kind" in query for query, _ in db.statements)
