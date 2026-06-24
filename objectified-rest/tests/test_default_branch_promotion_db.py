"""GLI-08 / #2727: default-branch promotion sets merge path and workflow_audit."""

from unittest.mock import MagicMock, patch

from app.database import Database

_PID = "00000000-0000-0000-0000-0000000000a1"
_TID = "tenant-1"
_B_NEW = "00000000-0000-0000-0000-0000000000b1"
_B_OLD = "00000000-0000-0000-0000-0000000000c1"


def _out_row(*, rmp: bool) -> dict:
    return {
        "id": _B_NEW,
        "project_id": _PID,
        "name": "feature",
        "tip_version_id": "00000000-0000-0000-0000-0000000000v1",
        "branched_from_revision_id": None,
        "protected": True,
        "is_default": True,
        "require_merge_path": rmp,
        "created_by": "u1",
        "created_at": None,
        "updated_at": None,
    }


def _run_policy(
    *,
    fetch_queue: list,
    is_default: bool = True,
    require_merge_path=None,
    actor_id: str = "u1",
):
    db = Database()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = lambda: fetch_queue.pop(0)
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cursor
    mock_cm.__exit__.return_value = None
    mock_conn.cursor.return_value = mock_cm

    with patch.object(db, "connect", return_value=mock_conn):
        with patch.object(db, "_begin_tx", return_value=False):
            return db.update_version_branch_protection_policy(
                _PID,
                _TID,
                _B_NEW,
                is_default=is_default,
                require_merge_path=require_merge_path,
                actor_id=actor_id,
            ), mock_cursor


def test_promotion_auto_enables_merge_path_and_audits():
    fq = [
        {"id": _B_NEW},
        {"id": _B_OLD},
        _out_row(rmp=True),
    ]
    row, mock_cursor = _run_policy(fetch_queue=fq)
    assert row is not None
    assert row["require_merge_path"] is True
    calls = str(mock_cursor.execute.call_args_list)
    assert "version.default_branch_promoted" in calls
    assert '"mergePathAutoEnabled": true' in calls


def test_promotion_explicit_merge_path_false_audits_without_auto_flag():
    fq = [
        {"id": _B_NEW},
        {"id": _B_OLD},
        _out_row(rmp=False),
    ]
    row, mock_cursor = _run_policy(
        fetch_queue=fq,
        require_merge_path=False,
    )
    assert row["require_merge_path"] is False
    calls = str(mock_cursor.execute.call_args_list)
    assert "version.default_branch_promoted" in calls
    assert '"mergePathAutoEnabled": false' in calls


def test_already_default_no_workflow_audit_on_is_default_only():
    fq = [
        {"id": _B_NEW},
        {"id": _B_NEW},
        _out_row(rmp=False),
    ]
    row, mock_cursor = _run_policy(fetch_queue=fq)
    assert row is not None
    calls = str(mock_cursor.execute.call_args_list)
    assert "version.default_branch_promoted" not in calls


def test_promotion_skips_workflow_audit_without_actor():
    q = [
        {"id": _B_NEW},
        {"id": _B_OLD},
        _out_row(rmp=True),
    ]
    db = Database()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.side_effect = lambda: q.pop(0)
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_cursor
    mock_cm.__exit__.return_value = None
    mock_conn.cursor.return_value = mock_cm

    with patch.object(db, "connect", return_value=mock_conn):
        with patch.object(db, "_begin_tx", return_value=False):
            db.update_version_branch_protection_policy(
                _PID,
                _TID,
                _B_NEW,
                is_default=True,
                actor_id=None,
            )

    assert "version.default_branch_promoted" not in str(mock_cursor.execute.call_args_list)
