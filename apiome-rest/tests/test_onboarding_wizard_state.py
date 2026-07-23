"""Tests for the onboarding-wizard resume-state + funnel routes (OLO-4.5, #4209).

``GET/PUT/DELETE /v1/onboarding/wizard-state`` persist the first-tenant wizard's
resume position and record step-reached/completed funnel telemetry. Route-level
tests mock auth (dependency override) and the ``db`` singleton, so no live
database is touched. The ``Database`` helpers are exercised separately with a
mocked connection to prove the SQL contract (upsert-on-conflict, expiry-filtered
read, best-effort telemetry that never raises, and the abandon-prune sweep).
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import psycopg2

from fastapi.testclient import TestClient

from app.auth import validate_session_credentials
from app.database import Database
from app.main import app

client = TestClient(app)

_USER_ID = "660e8400-e29b-41d4-a716-446655440001"
_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"

_JWT_SESSION = {
    "auth_method": "jwt",
    "user_id": _USER_ID,
    "user_email": "ada@example.com",
    "user_name": "Ada",
}

_API_KEY_SESSION = {
    "auth_method": "api_key",
    "user_id": _USER_ID,
    "tenant_id": _TENANT_ID,
}


def _use_jwt():
    app.dependency_overrides[validate_session_credentials] = lambda: dict(_JWT_SESSION)


def _use_api_key():
    app.dependency_overrides[validate_session_credentials] = lambda: dict(_API_KEY_SESSION)


def _clear_override():
    app.dependency_overrides.pop(validate_session_credentials, None)


def teardown_function():
    _clear_override()


# ---- GET /wizard-state ---------------------------------------------------


def test_get_requires_credentials():
    _clear_override()
    r = client.get("/v1/onboarding/wizard-state")
    assert r.status_code == 401


def test_get_rejects_api_key_sessions():
    _use_api_key()
    r = client.get("/v1/onboarding/wizard-state")
    assert r.status_code == 403


def test_get_returns_204_when_no_state():
    _use_jwt()
    with patch("app.onboarding_routes.db") as mdb:
        mdb.get_onboarding_wizard_state.return_value = None
        r = client.get("/v1/onboarding/wizard-state")
    assert r.status_code == 204
    mdb.get_onboarding_wizard_state.assert_called_once_with(_USER_ID)


def test_get_returns_204_when_step_unknown():
    _use_jwt()
    with patch("app.onboarding_routes.db") as mdb:
        mdb.get_onboarding_wizard_state.return_value = {
            "step": "legacy-step",
            "org_name": None,
            "slug": None,
            "updated_at": None,
        }
        r = client.get("/v1/onboarding/wizard-state")
    assert r.status_code == 204


def test_get_returns_saved_state():
    _use_jwt()
    with patch("app.onboarding_routes.db") as mdb:
        mdb.get_onboarding_wizard_state.return_value = {
            "step": "summary",
            "org_name": "Acme Corp",
            "slug": "acme-corp",
            "updated_at": "2026-07-22T12:00:00+00:00",
        }
        r = client.get("/v1/onboarding/wizard-state")
    assert r.status_code == 200
    assert r.json() == {
        "step": "summary",
        "org_name": "Acme Corp",
        "slug": "acme-corp",
        "updated_at": "2026-07-22T12:00:00+00:00",
    }


# ---- PUT /wizard-state ---------------------------------------------------


def test_put_rejects_api_key_sessions():
    _use_api_key()
    r = client.put("/v1/onboarding/wizard-state", json={"step": "welcome"})
    assert r.status_code == 403


def test_put_rejects_unknown_step():
    _use_jwt()
    with patch("app.onboarding_routes.db") as mdb:
        r = client.put("/v1/onboarding/wizard-state", json={"step": "nope"})
    assert r.status_code == 400
    mdb.upsert_onboarding_wizard_state.assert_not_called()


def test_put_upserts_and_records_funnel_event():
    _use_jwt()
    with patch("app.onboarding_routes.db") as mdb:
        r = client.put(
            "/v1/onboarding/wizard-state",
            json={
                "step": "summary",
                "org_name": "Acme Corp",
                "slug": "acme-corp",
                "event": "reached",
            },
        )
    assert r.status_code == 204
    mdb.upsert_onboarding_wizard_state.assert_called_once_with(
        _USER_ID, "summary", "Acme Corp", "acme-corp"
    )
    mdb.record_onboarding_funnel_event.assert_called_once_with(
        _USER_ID, "summary", "reached"
    )


def test_put_without_event_persists_but_records_no_funnel_event():
    _use_jwt()
    with patch("app.onboarding_routes.db") as mdb:
        r = client.put(
            "/v1/onboarding/wizard-state",
            json={"step": "organization", "org_name": "Acme", "slug": "acme"},
        )
    assert r.status_code == 204
    mdb.upsert_onboarding_wizard_state.assert_called_once_with(
        _USER_ID, "organization", "Acme", "acme"
    )
    mdb.record_onboarding_funnel_event.assert_not_called()


def test_put_trims_blank_values_to_null():
    _use_jwt()
    with patch("app.onboarding_routes.db") as mdb:
        r = client.put(
            "/v1/onboarding/wizard-state",
            json={"step": "welcome", "org_name": "   ", "slug": ""},
        )
    assert r.status_code == 204
    mdb.upsert_onboarding_wizard_state.assert_called_once_with(
        _USER_ID, "welcome", None, None
    )


def test_put_caps_oversized_text_to_column_width():
    _use_jwt()
    long_name = "x" * 500
    with patch("app.onboarding_routes.db") as mdb:
        r = client.put(
            "/v1/onboarding/wizard-state",
            json={"step": "organization", "org_name": long_name},
        )
    assert r.status_code == 204
    _, _, org_name, _ = mdb.upsert_onboarding_wizard_state.call_args.args
    assert len(org_name) == 255


def test_put_rejects_invalid_event_value():
    _use_jwt()
    r = client.put(
        "/v1/onboarding/wizard-state",
        json={"step": "welcome", "event": "bogus"},
    )
    assert r.status_code == 422


# ---- DELETE /wizard-state ------------------------------------------------


def test_delete_rejects_api_key_sessions():
    _use_api_key()
    r = client.delete("/v1/onboarding/wizard-state")
    assert r.status_code == 403


def test_delete_clears_state():
    _use_jwt()
    with patch("app.onboarding_routes.db") as mdb:
        mdb.delete_onboarding_wizard_state.return_value = 1
        r = client.delete("/v1/onboarding/wizard-state")
    assert r.status_code == 204
    mdb.delete_onboarding_wizard_state.assert_called_once_with(_USER_ID)


# ---- Database helpers ----------------------------------------------------


def _mock_connection():
    """A psycopg2-shaped connection mock whose cursor is scriptable."""
    conn = MagicMock()
    conn.info.transaction_status = psycopg2.extensions.TRANSACTION_STATUS_IDLE
    conn.autocommit = True
    cursor = conn.cursor.return_value.__enter__.return_value
    return conn, cursor


def _database_with(conn) -> Database:
    dbi = Database()
    dbi.connect = lambda: conn  # type: ignore[method-assign]
    return dbi


def test_db_upsert_commits_on_conflict_insert():
    conn, cursor = _mock_connection()
    _database_with(conn).upsert_onboarding_wizard_state(
        _USER_ID, "summary", "Acme Corp", "acme-corp"
    )
    conn.commit.assert_called_once()
    sql = cursor.execute.call_args.args[0]
    assert "ON CONFLICT (user_id) DO UPDATE" in sql


def test_db_upsert_rolls_back_on_error():
    conn, cursor = _mock_connection()
    cursor.execute.side_effect = RuntimeError("boom")
    try:
        _database_with(conn).upsert_onboarding_wizard_state(_USER_ID, "welcome", None, None)
        raise AssertionError("expected the error to propagate")
    except RuntimeError:
        pass
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_db_get_filters_expired_and_serializes_updated_at():
    dbi = Database()
    updated = datetime(2026, 7, 22, 12, 0, 0)
    with patch.object(
        dbi,
        "execute_query",
        return_value=[
            {"step": "summary", "org_name": "Acme", "slug": "acme", "updated_at": updated}
        ],
    ) as mq:
        state = dbi.get_onboarding_wizard_state(_USER_ID)
    assert state == {
        "step": "summary",
        "org_name": "Acme",
        "slug": "acme",
        "updated_at": updated.isoformat(),
    }
    assert "expires_at > CURRENT_TIMESTAMP" in mq.call_args.args[0]


def test_db_get_returns_none_when_absent():
    dbi = Database()
    with patch.object(dbi, "execute_query", return_value=[]):
        assert dbi.get_onboarding_wizard_state(_USER_ID) is None


def test_db_record_funnel_event_is_best_effort():
    conn, cursor = _mock_connection()
    cursor.execute.side_effect = RuntimeError("telemetry table gone")
    # Must not raise: telemetry can never fail the wizard step it records.
    _database_with(conn).record_onboarding_funnel_event(_USER_ID, "welcome", "reached")
    conn.rollback.assert_called_once()


def test_db_record_funnel_event_commits_on_success():
    conn, cursor = _mock_connection()
    _database_with(conn).record_onboarding_funnel_event(
        _USER_ID, "summary", "completed", {"resumed": True}
    )
    conn.commit.assert_called_once()


def test_db_prune_returns_deleted_count():
    conn, cursor = _mock_connection()
    cursor.rowcount = 4
    deleted = _database_with(conn).prune_onboarding_wizard_state()
    assert deleted == 4
    conn.commit.assert_called_once()
    assert "expires_at <= CURRENT_TIMESTAMP" in cursor.execute.call_args.args[0]


def test_db_prune_swallows_errors():
    conn, cursor = _mock_connection()
    cursor.execute.side_effect = RuntimeError("boom")
    assert _database_with(conn).prune_onboarding_wizard_state() == 0
    conn.rollback.assert_called_once()


def test_db_delete_returns_rowcount():
    conn, cursor = _mock_connection()
    cursor.rowcount = 1
    assert _database_with(conn).delete_onboarding_wizard_state(_USER_ID) == 1
    conn.commit.assert_called_once()
