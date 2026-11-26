"""Deleting, restoring and labelling, without a database — PFX-1.11 (#6924).

The database half is ``test_pact_cleanup_db``. Here the store runs on a fake database, to pin what
it decides before any SQL:

* a bad reason or label is refused before anything is written;
* a deployed version (or a pacticipant with one) is refused unless forced, naming the versions;
* every write runs in one transaction that also appends its audit row;
* ``purge_after`` is the deletion time plus the configured grace period;
* restoring something live, or something whose handle is taken, is refused with its own code.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from app import pact_cleanup_store as store
from app.consumer_contract_store import ConsumerActor
from app.pacticipant import (
    CODE_INVALID_LABEL,
    CODE_INVALID_REASON,
    CODE_NOT_DELETED,
    CODE_NOT_FOUND,
    CODE_RESTORE_CONFLICT,
    CODE_VERSION_IN_USE,
    PacticipantRecord,
    PacticipantValidationError,
    PacticipantVersionRecord,
    validate_label,
    validate_reason,
)

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = ConsumerActor(user_id=None, label="ci@example.com", kind="api_key")
PACTICIPANT = PacticipantRecord(
    id="22222222-2222-4222-8222-222222222222", tenant_id=TENANT, slug="billing-service", name="Billing Service"
)
VERSION = PacticipantVersionRecord(
    id="33333333-3333-4333-8333-333333333333", pacticipant_id=PACTICIPANT.id, number="1.0.0", seq=1
)


def _code(fn: Any, *args: Any, **kwargs: Any) -> str:
    with pytest.raises(PacticipantValidationError) as caught:
        fn(*args, **kwargs)
    return caught.value.code


class _Cursor:
    """A cursor that answers each ``execute`` with the next scripted rows."""

    def __init__(self, answers: List[Any]) -> None:
        self.answers = list(answers)
        self.statements: List[str] = []
        self.rowcount = 0
        self._rows: List[Dict[str, Any]] = []

    def execute(self, sql: str, params: Any = None) -> None:
        self.statements.append(" ".join(sql.split()))
        answer = self.answers.pop(0) if self.answers else []
        self._rows = answer if isinstance(answer, list) else [answer]
        self.rowcount = len(self._rows)

    def fetchone(self) -> Any:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> List[Any]:
        return self._rows


def _db(cursor: _Cursor, queries: List[Any] = ()) -> MagicMock:
    db = MagicMock()
    db.execute_query.side_effect = list(queries) or None
    if not queries:
        db.execute_query.return_value = []
    db._guarded_tx.side_effect = lambda work: work(cursor)
    return db


# ---------------------------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------------------------


def test_a_reason_is_trimmed_bounded_and_free_of_control_characters() -> None:
    assert validate_reason(None) is None and validate_reason("   ") is None
    assert validate_reason("  retired\nservice ") == "retired\nservice"
    assert _code(validate_reason, "x" * 501) == CODE_INVALID_REASON
    assert _code(validate_reason, "bad\x00byte") == CODE_INVALID_REASON


def test_a_label_is_stored_exactly_or_refused() -> None:
    assert validate_label("team/billing") == "team/billing"
    for bad in ("", " padded", "x" * 256, "new\nline"):
        assert _code(validate_label, bad) == CODE_INVALID_LABEL


def test_bad_input_is_refused_before_anything_is_written() -> None:
    db = _db(_Cursor([]))
    refused = _code(store.delete_pacticipant, db, TENANT, PACTICIPANT, actor=ACTOR, reason="x" * 600)
    assert refused == CODE_INVALID_REASON
    assert _code(store.add_label, db, TENANT, PACTICIPANT, " bad", actor=ACTOR) == CODE_INVALID_LABEL
    assert db._guarded_tx.call_count == 0


# ---------------------------------------------------------------------------------------------
# Deletes
# ---------------------------------------------------------------------------------------------


def test_a_deployed_version_is_refused_unless_forced() -> None:
    db = _db(_Cursor([]), queries=[[{"number": "1.0.0"}, {"number": "0.9.0"}]])
    with patch.object(store, "get_version", return_value=VERSION):
        with pytest.raises(PacticipantValidationError) as caught:
            store.delete_version(db, TENANT, PACTICIPANT, "1.0.0", actor=ACTOR)
    assert caught.value.code == CODE_VERSION_IN_USE
    assert "1.0.0, 0.9.0" in str(caught.value) and "force=true" in str(caught.value)
    assert db._guarded_tx.call_count == 0


def test_a_forced_version_delete_skips_the_check_and_is_audited_in_the_same_transaction() -> None:
    row = {
        "id": VERSION.id,
        "pacticipant_id": PACTICIPANT.id,
        "number": "1.0.0",
        "seq": 1,
        "deleted_at": "2026-11-24T10:00:00+00:00",
        "delete_cause": "version",
    }
    cursor = _Cursor([[{"id": VERSION.id}], [], row])
    db = _db(cursor)
    with patch.object(store, "get_version", return_value=VERSION):
        deleted = store.delete_version(db, TENANT, PACTICIPANT, "1.0.0", actor=ACTOR, reason="bad build", force=True)
    assert db.execute_query.call_count == 0  # No in-use check.
    assert cursor.statements[0].startswith("UPDATE apiome.pacticipant_version SET deleted_at = CURRENT_TIMESTAMP")
    assert deleted.delete_cause == "version" and deleted.purge_after.startswith("2026-12-24")
    audit = db._append_access_audit.call_args.kwargs
    assert audit["action"] == "pacts.version.delete" and audit["source"] == "api_key"
    assert audit["target"] == "pacticipant/billing-service/version/1.0.0"
    assert audit["detail"] == {"version_id": VERSION.id, "reason": "bad build", "forced": True}


def test_a_pacticipant_delete_that_lost_a_race_is_not_found() -> None:
    db = _db(_Cursor([None]), queries=[[]])
    assert _code(store.delete_pacticipant, db, TENANT, PACTICIPANT, actor=ACTOR) == CODE_NOT_FOUND
    assert db._append_access_audit.call_count == 0


def test_purge_after_uses_the_grace_period() -> None:
    with patch.object(store.settings, "pact_deletion_grace_days", 7):
        assert store.purge_after("2026-11-24T00:00:00+00:00") == "2026-12-01T00:00:00+00:00"
        assert store.purge_after("2026-11-24T00:00:00").startswith("2026-12-01")
    assert store.purge_after(None) is None and store.purge_after("not a time") is None


# ---------------------------------------------------------------------------------------------
# Restores
# ---------------------------------------------------------------------------------------------


def test_restoring_a_live_pacticipant_is_not_deleted() -> None:
    live = {"id": PACTICIPANT.id, "tenant_id": TENANT, "slug": "billing-service", "name": "B", "deleted_at": None}
    db = _db(_Cursor([]), queries=[[live]])
    assert _code(store.restore_pacticipant, db, TENANT, "billing-service", actor=ACTOR) == CODE_NOT_DELETED


def test_restoring_a_pacticipant_whose_handle_is_taken_is_a_conflict() -> None:
    deleted = {
        "id": PACTICIPANT.id,
        "tenant_id": TENANT,
        "slug": "billing-service",
        "name": "B",
        "deleted_at": "2026-11-20T00:00:00+00:00",
    }
    db = _db(_Cursor([]), queries=[[deleted], [{"?column?": 1}]])
    assert _code(store.restore_pacticipant, db, TENANT, PACTICIPANT.id, actor=ACTOR) == CODE_RESTORE_CONFLICT
    assert db._guarded_tx.call_count == 0


def test_restoring_a_version_whose_number_is_taken_is_a_conflict() -> None:
    rows = [{"id": "new", "deleted_at": None}, {"id": "old", "deleted_at": "2026-11-20T00:00:00+00:00"}]
    db = _db(_Cursor([]), queries=[rows])
    assert _code(store.restore_version, db, TENANT, PACTICIPANT, "1.0.0", actor=ACTOR) == CODE_RESTORE_CONFLICT


def test_an_unknown_pacticipant_cannot_be_restored() -> None:
    db = _db(_Cursor([]), queries=[[]])
    assert _code(store.restore_pacticipant, db, TENANT, "nobody", actor=ACTOR) == CODE_NOT_FOUND
    assert _code(store.restore_pacticipant, MagicMock(), "not-a-uuid", "x", actor=ACTOR) == CODE_NOT_FOUND


# ---------------------------------------------------------------------------------------------
# Heads and purge
# ---------------------------------------------------------------------------------------------


def test_moving_heads_without_versions_is_a_no_op() -> None:
    cursor = _Cursor([])
    assert store.move_heads_tx(cursor, PACTICIPANT.id, []) == 0
    assert cursor.statements == []


def test_the_purge_stops_when_a_batch_is_short_and_audits_per_tenant() -> None:
    claimed = [{"id": "v1", "pacticipant_id": PACTICIPANT.id, "tenant_id": TENANT}]
    # versions: claim, move heads, delete branches, delete versions; then the pacticipant batch.
    cursor = _Cursor([claimed, [], [], [], []])
    db = _db(cursor)
    totals = store.purge_deleted(db, batch=10)
    assert totals == {"versions": 1, "pacticipants": 0}
    assert db._append_access_audit.call_count == 1
    audit = db._append_access_audit.call_args.kwargs
    assert (audit["action"], audit["tenant_id"], audit["actor_label"]) == ("pacts.purge", TENANT, "system")
    assert audit["detail"]["versions"] == 1


def test_a_purged_pacticipant_takes_its_owner_rows_and_unowned_findings_with_it() -> None:
    # PFX-6.4: entity_owners / unowned_findings name the pacticipant by kind and id, with no foreign key.
    purged = [{"id": PACTICIPANT.id, "tenant_id": TENANT, "slug": PACTICIPANT.slug}]
    # versions: an empty claim; then the pacticipant batch and its two owner-row deletes.
    cursor = _Cursor([[], purged, [], []])
    totals = store.purge_deleted(_db(cursor), batch=10)
    assert totals == {"versions": 0, "pacticipants": 1}
    owner_deletes = [sql for sql in cursor.statements if "entity_kind = 'pacticipant'" in sql]
    assert [sql.split()[2] for sql in owner_deletes] == ["apiome.entity_owners", "apiome.unowned_findings"]


def test_a_batch_that_purges_nothing_touches_no_owner_rows() -> None:
    cursor = _Cursor([])
    assert store._purge_pacticipants_tx(cursor, store.datetime.now(store.timezone.utc), 10) == {}
    assert not any("entity_owners" in sql for sql in cursor.statements)
