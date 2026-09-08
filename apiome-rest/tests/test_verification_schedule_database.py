"""Guard tests for the scheduled-verification database accessors — CTG-4.4 (#4501).

The suite runs against a live Postgres, so these tests assert only the property that must hold
*before* a statement is sent: a malformed identifier short-circuits and returns the empty value for
its type, rather than reaching the driver and raising. Every sibling accessor in this codebase owes
the same guarantee — it is what keeps a test tenant like ``"t1"`` from producing a 500 instead of a
clean "not found".

The SQL itself is exercised by the migration guardrails and by the store/sweep tests above.
"""

from __future__ import annotations

from app.database import db

_BAD = "not-a-uuid"
_UUID = "11111111-1111-4111-8111-111111111111"


def test_reads_short_circuit_on_a_malformed_id():
    """A bad handle is a clean miss, never a driver error."""
    assert db.get_verification_schedule_by_id(_BAD, _UUID) is None
    assert db.get_verification_schedule_by_id(_UUID, _BAD) is None
    assert db.get_verification_schedule_by_slug(_BAD, "staging") is None
    assert db.get_verification_schedule_by_slug(_UUID, "") is None
    assert db.find_verification_schedule_for_pair(_BAD, "project/p/1", _UUID) is None
    assert db.find_verification_schedule_for_pair(_UUID, "project/p/1", _BAD) is None


def test_lists_short_circuit_on_a_malformed_id():
    """An empty list, so a caller iterates nothing rather than handling an exception."""
    assert db.list_verification_schedules(_BAD) == []
    assert db.list_verification_schedule_runs(_BAD, _UUID) == []
    assert db.list_verification_schedule_runs(_UUID, _BAD) == []


def test_writes_short_circuit_on_a_malformed_id():
    """A write that cannot be addressed is refused before the statement, not after it."""
    assert db.insert_verification_schedule(schedule={"tenant_id": _BAD, "target_id": _UUID}) is None
    assert db.insert_verification_schedule(schedule={"tenant_id": _UUID, "target_id": _BAD}) is None
    assert db.insert_verification_schedule_run(run={"tenant_id": _BAD, "schedule_id": _UUID}) is None
    assert db.insert_verification_schedule_run(run={"tenant_id": _UUID, "schedule_id": _BAD}) is None
    assert db.update_verification_schedule(_BAD, _UUID, fields={"enabled": False}) is None
    assert db.soft_delete_verification_schedule(_BAD, _UUID) is False
    assert (
        db.mark_verification_schedule_ran(_BAD, _UUID, status="passed", succeeded=True) is None
    )


def test_an_update_with_nothing_settable_is_a_no_op():
    """The column whitelist is the guard: a patch naming only unknown keys changes nothing.

    This is what stops a request from ever reaching ``last_success_at`` or ``alert_state`` — the
    sweep's record of what actually happened.
    """
    assert (
        db.update_verification_schedule(
            _UUID, _UUID, fields={"alert_state": "ok", "last_success_at": "now"}
        )
        is None
    )
