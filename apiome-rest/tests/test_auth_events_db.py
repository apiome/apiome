"""Database tests for the auth-events ledger (OLO-1.6, #4191).

Exercise the ``Database`` write/read/prune methods with the connection or ``execute_query`` mocked:
best-effort swallowing on the append path, the hash-chain wiring, the per-user read SQL, and the
tail-retention delete. No live database is touched.
"""

from unittest.mock import MagicMock

from app import auth_events as ae
from app.database import Database

_USER = "660e8400-e29b-41d4-a716-446655440001"


def _mock_conn(prev_entry_hash=None):
    """A MagicMock connection whose cursor returns ``prev_entry_hash`` for the chain lookup."""
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (
        {"entry_hash": prev_entry_hash} if prev_entry_hash is not None else None
    )
    return conn, cursor


# --- write_auth_event --------------------------------------------------------------------------


def test_write_auth_event_inserts_hash_chained_row():
    db = Database()
    conn, cursor = _mock_conn(prev_entry_hash=None)
    db.connect = MagicMock(return_value=conn)

    db.write_auth_event(
        event_type=ae.EVENT_SIGN_IN,
        outcome=ae.OUTCOME_SUCCESS,
        provider="github",
        user_id=_USER,
        user_label="ada@example.com",
        ip_hash="deadbeef",
    )

    # Two statements: the chain lookup then the insert.
    insert_sql, params = cursor.execute.call_args_list[-1][0]
    assert "INSERT INTO apiome.auth_events" in insert_sql
    assert params[0] == ae.EVENT_SIGN_IN
    assert params[1] == _USER
    assert params[4] == ae.OUTCOME_SUCCESS
    # prev_hash is None (empty chain); entry_hash is a 64-char sha256 digest.
    prev_hash, entry_hash = params[-2], params[-1]
    assert prev_hash is None
    assert isinstance(entry_hash, str) and len(entry_hash) == 64
    conn.commit.assert_called_once()


def test_write_auth_event_links_to_previous_entry_hash():
    db = Database()
    conn, cursor = _mock_conn(prev_entry_hash="a" * 64)
    db.connect = MagicMock(return_value=conn)

    db.write_auth_event(event_type=ae.EVENT_LINK, outcome=ae.OUTCOME_SUCCESS)

    _, params = cursor.execute.call_args_list[-1][0]
    assert params[-2] == "a" * 64  # prev_hash chains to the newest row


def test_write_auth_event_is_best_effort():
    db = Database()
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("db down")
    db.connect = MagicMock(return_value=conn)
    # Must not raise even though the connection blows up mid-write.
    db.write_auth_event(event_type=ae.EVENT_SIGN_IN, outcome=ae.OUTCOME_FAILURE)
    conn.rollback.assert_called_once()


def test_log_auth_event_forwards_event_and_hashes():
    db = Database()
    db.write_auth_event = MagicMock()
    event = ae.AuthEvent(
        event_type=ae.EVENT_LINK,
        outcome=ae.OUTCOME_SUCCESS,
        provider="gitlab",
        user_id=_USER,
        detail={"auto_linked": True},
    )
    db.log_auth_event(event, ip_hash="ip", user_agent_hash="ua")
    kwargs = db.write_auth_event.call_args.kwargs
    assert kwargs["event_type"] == ae.EVENT_LINK
    assert kwargs["provider"] == "gitlab"
    assert kwargs["user_id"] == _USER
    assert kwargs["ip_hash"] == "ip" and kwargs["user_agent_hash"] == "ua"
    assert kwargs["detail"] == {"auto_linked": True}


# --- list_auth_events_for_user -----------------------------------------------------------------


def test_list_auth_events_for_user_scopes_and_orders():
    db = Database()
    db.execute_query = MagicMock(return_value=[])
    db.list_auth_events_for_user(_USER, limit=25)
    sql, params = db.execute_query.call_args[0]
    assert "FROM apiome.auth_events" in sql
    assert "WHERE user_id = %s::uuid" in sql
    assert "ORDER BY created_at DESC, id DESC" in sql
    assert params == (_USER, 25)


def test_list_auth_events_for_user_clamps_limit():
    db = Database()
    db.execute_query = MagicMock(return_value=[])
    db.list_auth_events_for_user(_USER, limit=10_000)
    _, params = db.execute_query.call_args[0]
    assert params[1] == 1000  # clamped to the ceiling
    db.list_auth_events_for_user(_USER, limit=0)
    _, params = db.execute_query.call_args[0]
    assert params[1] == 1  # clamped to the floor


# --- prune_auth_events -------------------------------------------------------------------------


def test_prune_auth_events_deletes_by_age_and_returns_count():
    db = Database()
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.rowcount = 4
    db.connect = MagicMock(return_value=conn)

    deleted = db.prune_auth_events(retention_days=ae.DEFAULT_AUTH_EVENT_RETENTION_DAYS)

    assert deleted == 4
    sql, params = cursor.execute.call_args[0]
    assert "DELETE FROM apiome.auth_events" in sql
    assert "make_interval(days => %s)" in sql
    assert params == (365,)
    conn.commit.assert_called_once()


def test_prune_auth_events_floors_retention_and_is_best_effort():
    db = Database()
    conn = MagicMock()
    conn.cursor.side_effect = RuntimeError("db down")
    db.connect = MagicMock(return_value=conn)
    # Swallows failures (returns 0) rather than raising.
    assert db.prune_auth_events(retention_days=0) == 0
    conn.rollback.assert_called_once()
