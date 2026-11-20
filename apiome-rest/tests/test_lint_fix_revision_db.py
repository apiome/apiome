"""GVM-3.2 (#5870): ``record_lint_fix_revision`` stamps provenance and audits in one transaction."""

from __future__ import annotations

import json
from typing import Any, List, Optional
from unittest.mock import MagicMock, patch

from app.database import Database

_TID = "tenant-1"
_PID = "00000000-0000-0000-0000-0000000000a1"
_VID = "00000000-0000-0000-0000-0000000000b2"


def _run(fetch: List[Optional[dict]], *, execute_error: Optional[Exception] = None):
    """Call the method against a mocked connection; return (result or exception, conn, cursor)."""
    db = Database()
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.side_effect = lambda: fetch.pop(0)
    if execute_error is not None:
        calls = {"n": 0}

        def _execute(*_args: Any, **_kwargs: Any) -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise execute_error

        cursor.execute.side_effect = _execute
    manager = MagicMock()
    manager.__enter__.return_value = cursor
    manager.__exit__.return_value = None
    conn.cursor.return_value = manager
    with patch.object(db, "connect", return_value=conn), patch.object(db, "_begin_tx", return_value=False):
        try:
            outcome: Any = db.record_lint_fix_revision(
                tenant_id=_TID,
                project_id=_PID,
                version_record_id=_VID,
                actor_id="u1",
                provenance={"source": "lint-fix", "lintFix": {"fixIds": ["fix-1"]}},
                audit_action="version.lint_fix_applied",
                audit_detail={"fixIds": ["fix-1"], "reason": "r"},
            )
        except Exception as exc:  # noqa: BLE001 - returned for the assertions
            outcome = exc
    return outcome, conn, cursor


def test_stamps_and_audits_then_commits_once() -> None:
    outcome, conn, cursor = _run([{"id": _VID}])
    assert outcome is True
    assert cursor.execute.call_count == 2
    update_sql, update_args = cursor.execute.call_args_list[0].args
    assert "format_metadata = COALESCE(v.format_metadata, '{}'::jsonb) || %s::jsonb" in update_sql
    assert update_args[1:] == (_VID, _TID)
    insert_sql, insert_args = cursor.execute.call_args_list[1].args
    assert "INSERT INTO apiome.workflow_audit" in insert_sql
    assert insert_args[:5] == (_TID, _PID, _VID, "version.lint_fix_applied", "u1")
    assert json.loads(insert_args[5]) == {"fixIds": ["fix-1"], "reason": "r"}
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    assert conn.autocommit is False


def test_unknown_revision_writes_nothing() -> None:
    outcome, conn, cursor = _run([None])
    assert outcome is False
    assert cursor.execute.call_count == 1
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()


def test_audit_failure_rolls_back_the_stamp_and_raises() -> None:
    outcome, conn, _cursor = _run([{"id": _VID}], execute_error=RuntimeError("audit insert failed"))
    assert isinstance(outcome, RuntimeError)
    conn.commit.assert_not_called()
    conn.rollback.assert_called_once()
