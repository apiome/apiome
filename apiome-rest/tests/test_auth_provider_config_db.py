"""Unit tests for the auth_provider_config data layer (OLO-8.4, #4970).

These verify the SQL the :class:`app.database.Database` methods build for the provider-config table
without a live Postgres, by mocking the shared connection and capturing what would be executed:

* the read paths never select the encrypted secret column (only its key id signals presence),
* the partial upsert writes ONLY the supplied columns (so an omitted field is never reset),
* the ``config`` JSONB is adapted via ``Json`` (not sent as a Python-repr string),
* the secret columns are written together (V196 both-or-neither), and the statement upserts on
  ``provider_id``.
"""

from contextlib import contextmanager

import pytest

from app.database import Database


class _FakeCursor:
    """Minimal cursor capturing ``execute`` and returning canned rows."""

    def __init__(self, rows):
        self._rows = rows
        self.executed = []  # list of (sql, params)

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Connection whose ``cursor()`` is a context manager over one ``_FakeCursor``."""

    def __init__(self, rows):
        self.cursor_obj = _FakeCursor(rows)
        self.committed = False
        self.rolled_back = False

    @contextmanager
    def cursor(self):
        yield self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


@pytest.fixture
def db_with_conn(monkeypatch):
    """A Database whose ``connect()`` returns a fake connection; factory sets the canned rows."""
    database = Database()

    def _make(rows):
        conn = _FakeConn(rows)
        monkeypatch.setattr(database, "connect", lambda: conn)
        return conn

    return database, _make


def test_list_selects_no_ciphertext(db_with_conn):
    """The list read path selects the key id but never the encrypted secret column."""
    database, make = db_with_conn
    conn = make([{"provider_id": "github"}])
    database.list_auth_provider_config()
    sql, _ = conn.cursor_obj.executed[0]
    assert "client_secret_encrypted" not in sql
    assert "enc_key_id" in sql
    assert "ORDER BY provider_id" in sql


def test_get_selects_no_ciphertext_and_filters(db_with_conn):
    """The single-row read filters by provider_id and omits the ciphertext."""
    database, make = db_with_conn
    conn = make([{"provider_id": "github"}])
    database.get_auth_provider_config("github")
    sql, params = conn.cursor_obj.executed[0]
    assert "client_secret_encrypted" not in sql
    assert "WHERE provider_id = %s" in sql
    assert params == ("github",)


def test_get_returns_none_when_absent(db_with_conn):
    """A provider with no row yields None."""
    database, make = db_with_conn
    make([])
    assert database.get_auth_provider_config("github") is None


def test_upsert_writes_only_supplied_columns(db_with_conn):
    """Only the supplied columns appear in the INSERT list and the ON CONFLICT SET clause."""
    database, make = db_with_conn
    conn = make([{"provider_id": "github", "enabled": True}])
    database.upsert_auth_provider_config("github", {"enabled": True}, updated_by="admin")
    sql, params = conn.cursor_obj.executed[0]
    assert "INSERT INTO apiome.auth_provider_config" in sql
    assert "ON CONFLICT (provider_id) DO UPDATE SET" in sql
    assert "enabled = EXCLUDED.enabled" in sql
    # Untouched columns are never referenced.
    assert "client_id = EXCLUDED.client_id" not in sql
    assert "client_secret_encrypted" not in sql
    # updated_at is left to the trigger, not written here.
    assert "updated_at = EXCLUDED.updated_at" not in sql
    # provider_id + updated_by + enabled = 3 bound values.
    assert params == ("github", "admin", True)
    assert conn.committed is True


def test_upsert_wraps_config_in_json(db_with_conn):
    """The config dict is adapted (psycopg2 Json), not passed as a raw dict/str."""
    from psycopg2.extras import Json

    database, make = db_with_conn
    conn = make([{"provider_id": "azure"}])
    database.upsert_auth_provider_config(
        "azure", {"config": {"authority": "https://login"}}, updated_by="admin"
    )
    _, params = conn.cursor_obj.executed[0]
    # params = (provider_id, updated_by, config)
    assert isinstance(params[2], Json)


def test_upsert_writes_secret_pair_together(db_with_conn):
    """Storing a secret writes both the ciphertext and its key id (both-or-neither)."""
    database, make = db_with_conn
    conn = make([{"provider_id": "github"}])
    database.upsert_auth_provider_config(
        "github",
        {"client_secret_encrypted": b"\x00blob", "enc_key_id": "default"},
        updated_by="admin",
    )
    sql, params = conn.cursor_obj.executed[0]
    assert "client_secret_encrypted = EXCLUDED.client_secret_encrypted" in sql
    assert "enc_key_id = EXCLUDED.enc_key_id" in sql
    assert params == ("github", "admin", b"\x00blob", "default")


def test_upsert_clear_secret_pair(db_with_conn):
    """Clearing a secret writes both columns as NULL together."""
    database, make = db_with_conn
    conn = make([{"provider_id": "github"}])
    database.upsert_auth_provider_config(
        "github",
        {"client_secret_encrypted": None, "enc_key_id": None},
        updated_by="admin",
    )
    _, params = conn.cursor_obj.executed[0]
    assert params == ("github", "admin", None, None)


def test_upsert_rolls_back_on_error(monkeypatch):
    """A DB error rolls back and re-raises (no partial commit)."""
    database = Database()
    conn = _FakeConn([{"provider_id": "github"}])

    def _boom(sql, params=None):
        raise RuntimeError("db exploded")

    conn.cursor_obj.execute = _boom
    monkeypatch.setattr(database, "connect", lambda: conn)
    with pytest.raises(RuntimeError, match="db exploded"):
        database.upsert_auth_provider_config("github", {"enabled": True}, updated_by="admin")
    assert conn.rolled_back is True
    assert conn.committed is False
