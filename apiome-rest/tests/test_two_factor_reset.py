"""Admin reset of a user's two-factor (TFA-1.2, #5656).

Three layers, each pinned where it decides something:

* **The transaction** (:meth:`Database.reset_user_two_factor`), driven against the scripted
  connection: what is removed, in what order, and that the audit rows are part of the same commit —
  a failed audit write leaves the factor in place.
* **The super-admin route** — the signed session, the reason, the typed confirmation.
* **The owner route** — owner only, active members only, sole-workspace members only, not
  yourself, not with an API key.
"""

import base64
import hmac
import json
from hashlib import sha256
from unittest.mock import patch

import psycopg2
import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.auth_events import AUTH_EVENT_TYPES, EVENT_TWO_FACTOR_RESET
from app.config import settings
from app.main import app
from app.two_factor_reset_routes import REASON_MAX_LENGTH, REASON_MIN_LENGTH
from tests.scripted_connection import ScriptedConnection, database_with

client = TestClient(app)

USER_ID = "660e8400-e29b-41d4-a716-446655440001"
OWNER_ID = "770e8400-e29b-41d4-a716-446655440002"
TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
EMAIL = "Priya.Raman@Example.com"
REASON = "Lost her phone and her backup codes; identity confirmed on a call."
BODY = {"reason": REASON, "confirm": "priya.raman@example.com"}

USER_ROW = {"id": USER_ID, "email": EMAIL, "name": "Priya Raman", "two_factor_enabled": True}


# --------------------------------------------------------------------------------------------------
# The transaction
# --------------------------------------------------------------------------------------------------
def _script(*, user=USER_ROW, two_factor_rows=1, trusted=2, sessions=3, tenant=False):
    """Scripted answers for one reset, statement by statement."""
    if user is None:
        return [[]]
    answers = [
        [user],  # 1 SELECT … FOR UPDATE
        [{}] * two_factor_rows,  # 2 DELETE two_factor
        [],  # 3 UPDATE users
        [{}] * trusted,  # 4 DELETE trust-device records
        [],  # 5 DELETE in-flight challenges
        [{}] * sessions,  # 6 DELETE sessions
        [{"entry_hash": "prev-auth"}],  # 7 SELECT auth_events chain head
        [],  # 8 INSERT auth_events
    ]
    if tenant:
        answers += [[{"entry_hash": "prev-access"}], []]  # 9, 10 access_audit
    return answers


def _reset(monkeypatch, conn, **overrides):
    """Run the reset as a super-admin (or as given) against a scripted connection."""
    kwargs = {
        "user_id": USER_ID,
        "reason": REASON,
        "actor_kind": "super_admin",
        "actor_label": "super-admin",
    }
    kwargs.update(overrides)
    return database_with(monkeypatch, conn).reset_user_two_factor(**kwargs)


def test_reset_clears_the_factor_devices_and_sessions_in_one_commit(monkeypatch):
    conn = ScriptedConnection(_script())
    result = _reset(monkeypatch, conn)

    sql = [statement for statement, _ in conn.statements]
    assert sql[0].startswith("SELECT id::text AS id, email, name")
    assert sql[0].endswith("FOR UPDATE")
    assert sql[1] == 'DELETE FROM apiome.two_factor WHERE "userId" = %s::uuid'
    assert '"twoFactorEnabled" = false' in sql[2]
    assert "two_factor_reset_at = CURRENT_TIMESTAMP" in sql[2]
    assert "\"identifier\" LIKE 'trust-device-%%'" in sql[3]
    assert "\"identifier\" LIKE '2fa-%%'" in sql[4]
    assert sql[5] == 'DELETE FROM apiome.session WHERE "userId" = %s::uuid'
    assert sql[6].startswith("SELECT entry_hash FROM apiome.auth_events")
    assert sql[7].startswith("INSERT INTO apiome.auth_events")
    assert len(sql) == 8
    assert (conn.commits, conn.rollbacks) == (1, 0)

    assert result == {
        "user_id": USER_ID,
        "email": EMAIL,
        "name": "Priya Raman",
        "had_two_factor": True,
        "sessions_revoked": 3,
        "trusted_devices_revoked": 2,
    }


def test_reset_only_touches_the_target_user(monkeypatch):
    conn = ScriptedConnection(_script())
    _reset(monkeypatch, conn)
    # Every write is parameterised by the target's id and nothing else.
    for statement, params in conn.statements[:6]:
        assert params == (USER_ID,), statement


def test_reset_records_actor_target_and_reason_in_the_auth_ledger(monkeypatch):
    conn = ScriptedConnection(_script())
    _reset(monkeypatch, conn)

    params = conn.statements[7][1]
    event_type, user_id, user_label, _provider, outcome = params[:5]
    assert EVENT_TWO_FACTOR_RESET in AUTH_EVENT_TYPES
    assert (event_type, user_id, outcome) == (EVENT_TWO_FACTOR_RESET, USER_ID, "success")
    assert user_label == "priya.raman@example.com"
    assert json.loads(params[8]) == {
        "actor_kind": "super_admin",
        "actor_id": None,
        "actor_label": "super-admin",
        "tenant_id": None,
        "reason": REASON,
        "had_two_factor": True,
        "sessions_revoked": 3,
        "trusted_devices_revoked": 2,
    }
    # The row extends the chain from the head that was read in this transaction.
    assert params[9] == "prev-auth"
    assert len(params[10]) == 64


def test_owner_reset_is_also_recorded_on_the_workspace_chain(monkeypatch):
    conn = ScriptedConnection(_script(tenant=True))
    _reset(
        monkeypatch,
        conn,
        actor_kind="tenant_owner",
        actor_id=OWNER_ID,
        actor_label="owner@example.com",
        tenant_id=TENANT_ID,
    )

    assert len(conn.statements) == 10
    assert conn.statements[8][0].startswith("SELECT entry_hash FROM apiome.access_audit")
    assert conn.statements[8][1] == (TENANT_ID,)
    insert_sql, params = conn.statements[9]
    assert insert_sql.startswith("INSERT INTO apiome.access_audit")
    tenant_id, actor_id, actor_label, action, target = params[:5]
    assert (tenant_id, actor_id, actor_label) == (TENANT_ID, OWNER_ID, "owner@example.com")
    assert (action, target) == ("member.two_factor_reset", USER_ID)
    assert json.loads(params[6])["reason"] == REASON
    assert (conn.commits, conn.rollbacks) == (1, 0)

    auth_detail = json.loads(conn.statements[7][1][8])
    assert auth_detail["actor_kind"] == "tenant_owner"
    assert auth_detail["actor_id"] == OWNER_ID
    assert auth_detail["tenant_id"] == TENANT_ID


@pytest.mark.parametrize("failing_statement", [2, 3, 6, 7, 8])
def test_nothing_is_kept_when_any_step_fails(monkeypatch, failing_statement):
    """The audit rows are part of the transaction: no audit, no reset."""
    conn = ScriptedConnection(_script(), fail_on=failing_statement)
    with pytest.raises(psycopg2.DatabaseError):
        _reset(monkeypatch, conn)
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_a_failed_workspace_audit_write_rolls_the_reset_back(monkeypatch):
    conn = ScriptedConnection(_script(tenant=True), fail_on=10)
    with pytest.raises(psycopg2.DatabaseError):
        _reset(monkeypatch, conn, actor_kind="tenant_owner", actor_id=OWNER_ID, tenant_id=TENANT_ID)
    assert (conn.commits, conn.rollbacks) == (0, 1)


def test_reset_of_an_unknown_user_writes_nothing(monkeypatch):
    conn = ScriptedConnection(_script(user=None))
    assert _reset(monkeypatch, conn) is None
    assert len(conn.statements) == 1
    assert conn.commits == 0


def test_reset_of_a_malformed_id_never_reaches_the_database(monkeypatch):
    assert database_with(monkeypatch, None).reset_user_two_factor(
        user_id="not-a-uuid", reason=REASON, actor_kind="super_admin"
    ) is None


def test_reset_of_a_user_without_two_factor_still_revokes_and_audits(monkeypatch):
    user = {**USER_ROW, "two_factor_enabled": False}
    conn = ScriptedConnection(_script(user=user, two_factor_rows=0, trusted=0, sessions=1))
    result = _reset(monkeypatch, conn)

    assert result["had_two_factor"] is False
    assert result["sessions_revoked"] == 1
    assert json.loads(conn.statements[7][1][8])["had_two_factor"] is False
    assert conn.commits == 1


def test_an_orphaned_two_factor_row_counts_as_having_had_one(monkeypatch):
    """The flag and the row can disagree; either one means there was something to clear."""
    user = {**USER_ROW, "two_factor_enabled": False}
    conn = ScriptedConnection(_script(user=user, two_factor_rows=1))
    assert _reset(monkeypatch, conn)["had_two_factor"] is True


def test_target_lookup_rejects_a_malformed_id_without_a_query(monkeypatch):
    assert database_with(monkeypatch, None).get_two_factor_reset_target("nope") is None


# --------------------------------------------------------------------------------------------------
# Shared route fixtures
# --------------------------------------------------------------------------------------------------
_ADMIN_SECRET = "test-admin-session-secret"
ADMIN_URL = f"/v1/admin/users/{USER_ID}/two-factor/reset"
MEMBER_URL = f"/v1/access/acme/members/{USER_ID}/two-factor/reset"

TARGET = {
    "id": USER_ID,
    "email": EMAIL,
    "name": "Priya Raman",
    "two_factor_enabled": True,
    "tenant_count": 1,
}
RESULT = {
    "user_id": USER_ID,
    "email": EMAIL,
    "name": "Priya Raman",
    "had_two_factor": True,
    "sessions_revoked": 3,
    "trusted_devices_revoked": 2,
}


def _mint_admin_token(key: str = _ADMIN_SECRET) -> str:
    """Mint a far-future super-admin session token (same recipe as the sign-up policy tests)."""
    payload = {"v": 1, "sub": "admin", "iat": 0, "exp": 9_999_999_999_999}
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    digest = hmac.new(key.encode(), encoded.encode(), sha256).digest()
    return f"{encoded}.{base64.urlsafe_b64encode(digest).rstrip(b'=').decode()}"


@pytest.fixture
def admin_headers(monkeypatch):
    """Configure the admin signing key and return a header carrying a valid session token."""
    monkeypatch.setattr(settings, "admin_session_secret", _ADMIN_SECRET)
    monkeypatch.setattr(settings, "admin_password", None)
    return {"X-Admin-Session": _mint_admin_token()}


@pytest.fixture
def mock_db():
    """The routes' ``db``, answering for a resettable sole-workspace member by default."""
    with patch("app.two_factor_reset_routes.db") as fake:
        fake.get_two_factor_reset_target.return_value = dict(TARGET)
        fake.reset_user_two_factor.return_value = dict(RESULT)
        fake.get_effective_role_slug.return_value = "owner"
        fake.get_member_status.return_value = "active"
        yield fake


@pytest.fixture
def as_owner():
    """Authenticate every request as the workspace's owner, signed in (not an API key)."""
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT_ID,
        "user_id": OWNER_ID,
        "user_email": "owner@example.com",
        "auth_method": "jwt",
    }
    yield
    app.dependency_overrides.pop(validate_authentication, None)


INVALID_BODIES = [
    ("a reason that is too short", {"reason": "x" * (REASON_MIN_LENGTH - 1), "confirm": EMAIL}, "invalid_reason"),
    ("a reason that is only spaces", {"reason": " " * 40, "confirm": EMAIL}, "invalid_reason"),
    ("a reason that is too long", {"reason": "x" * (REASON_MAX_LENGTH + 1), "confirm": EMAIL}, "invalid_reason"),
    ("the wrong email", {"reason": REASON, "confirm": "someone.else@example.com"}, "confirmation_mismatch"),
    ("an empty confirmation", {"reason": REASON, "confirm": "  "}, "confirmation_mismatch"),
    ("the user's name instead of their email", {"reason": REASON, "confirm": "Priya Raman"}, "confirmation_mismatch"),
]


# --------------------------------------------------------------------------------------------------
# Super-admin route
# --------------------------------------------------------------------------------------------------
def test_admin_resets_a_user(admin_headers, mock_db):
    response = client.post(ADMIN_URL, json=BODY, headers=admin_headers)

    assert response.status_code == 200
    assert response.json() == RESULT
    mock_db.reset_user_two_factor.assert_called_once_with(
        user_id=USER_ID, reason=REASON, actor_kind="super_admin", actor_label="super-admin"
    )


def test_admin_reason_is_trimmed_before_it_is_stored(admin_headers, mock_db):
    client.post(ADMIN_URL, json={"reason": f"   {REASON}\n", "confirm": EMAIL}, headers=admin_headers)
    assert mock_db.reset_user_two_factor.call_args.kwargs["reason"] == REASON


def test_admin_confirmation_ignores_case_and_surrounding_space(admin_headers, mock_db):
    body = {"reason": REASON, "confirm": "  PRIYA.RAMAN@example.COM "}
    assert client.post(ADMIN_URL, json=body, headers=admin_headers).status_code == 200


def test_admin_route_needs_a_session(mock_db):
    assert client.post(ADMIN_URL, json=BODY).status_code == 401
    mock_db.reset_user_two_factor.assert_not_called()


def test_admin_route_refuses_a_forged_session(admin_headers, mock_db):
    forged = {"X-Admin-Session": _mint_admin_token("some-other-key")}
    assert client.post(ADMIN_URL, json=BODY, headers=forged).status_code == 403
    mock_db.get_two_factor_reset_target.assert_not_called()
    mock_db.reset_user_two_factor.assert_not_called()


def test_admin_route_does_not_accept_a_tenant_login(as_owner, mock_db):
    """A signed-in workspace owner is not the super-admin."""
    assert client.post(ADMIN_URL, json=BODY).status_code == 401
    mock_db.reset_user_two_factor.assert_not_called()


@pytest.mark.parametrize("_name, body, error", INVALID_BODIES, ids=[case[0] for case in INVALID_BODIES])
def test_admin_route_validates_reason_and_confirmation(admin_headers, mock_db, _name, body, error):
    response = client.post(ADMIN_URL, json=body, headers=admin_headers)
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == error
    mock_db.reset_user_two_factor.assert_not_called()


@pytest.mark.parametrize("body", [{}, {"reason": REASON}, {"confirm": EMAIL}])
def test_admin_route_requires_both_fields(admin_headers, mock_db, body):
    assert client.post(ADMIN_URL, json=body, headers=admin_headers).status_code == 422
    mock_db.reset_user_two_factor.assert_not_called()


def test_admin_route_answers_404_for_an_unknown_user(admin_headers, mock_db):
    mock_db.get_two_factor_reset_target.return_value = None
    response = client.post(ADMIN_URL, json=BODY, headers=admin_headers)
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "user_not_found"


def test_admin_route_answers_404_when_the_user_vanishes_mid_request(admin_headers, mock_db):
    mock_db.reset_user_two_factor.return_value = None
    assert client.post(ADMIN_URL, json=BODY, headers=admin_headers).status_code == 404


def test_admin_may_reset_a_member_of_several_workspaces(admin_headers, mock_db):
    mock_db.get_two_factor_reset_target.return_value = {**TARGET, "tenant_count": 4}
    assert client.post(ADMIN_URL, json=BODY, headers=admin_headers).status_code == 200


# --------------------------------------------------------------------------------------------------
# Owner route
# --------------------------------------------------------------------------------------------------
def test_owner_resets_a_sole_workspace_member(as_owner, mock_db):
    response = client.post(MEMBER_URL, json=BODY)

    assert response.status_code == 200
    assert response.json() == RESULT
    mock_db.get_effective_role_slug.assert_called_once_with(TENANT_ID, OWNER_ID)
    mock_db.get_member_status.assert_called_once_with(TENANT_ID, USER_ID)
    mock_db.reset_user_two_factor.assert_called_once_with(
        user_id=USER_ID,
        reason=REASON,
        actor_kind="tenant_owner",
        actor_id=OWNER_ID,
        actor_label="owner@example.com",
        tenant_id=TENANT_ID,
    )


@pytest.mark.parametrize("role", ["admin", "editor", "viewer", None])
def test_only_an_owner_may_reset(as_owner, mock_db, role):
    mock_db.get_effective_role_slug.return_value = role
    response = client.post(MEMBER_URL, json=BODY)
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "owner_required"
    mock_db.reset_user_two_factor.assert_not_called()


def test_an_api_key_cannot_reset_a_member(mock_db):
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT_ID,
        "user_id": OWNER_ID,
        "auth_method": "api_key",
    }
    try:
        response = client.post(MEMBER_URL, json=BODY)
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "session_required"
    mock_db.get_effective_role_slug.assert_not_called()
    mock_db.reset_user_two_factor.assert_not_called()


def test_owner_route_needs_authentication(mock_db):
    assert client.post(MEMBER_URL, json=BODY).status_code in (401, 403)
    mock_db.reset_user_two_factor.assert_not_called()


def test_an_owner_cannot_reset_themselves_here(as_owner, mock_db):
    response = client.post(f"/v1/access/acme/members/{OWNER_ID}/two-factor/reset", json=BODY)
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "self_reset"
    mock_db.reset_user_two_factor.assert_not_called()


@pytest.mark.parametrize("status", [None, "pending", "suspended"])
def test_the_target_must_be_an_active_member_of_this_workspace(as_owner, mock_db, status):
    mock_db.get_member_status.return_value = status
    response = client.post(MEMBER_URL, json=BODY)
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "member_not_found"
    # A user of another workspace is not even looked up.
    mock_db.get_two_factor_reset_target.assert_not_called()
    mock_db.reset_user_two_factor.assert_not_called()


@pytest.mark.parametrize("tenant_count", [2, 5, 0])
def test_a_member_of_another_workspace_is_left_to_the_super_admin(as_owner, mock_db, tenant_count):
    mock_db.get_two_factor_reset_target.return_value = {**TARGET, "tenant_count": tenant_count}
    response = client.post(MEMBER_URL, json=BODY)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["error"] == "multi_tenant_member"
    assert "administrator of this Apiome installation" in detail["message"]
    mock_db.reset_user_two_factor.assert_not_called()


@pytest.mark.parametrize("_name, body, error", INVALID_BODIES, ids=[case[0] for case in INVALID_BODIES])
def test_owner_route_validates_reason_and_confirmation(as_owner, mock_db, _name, body, error):
    response = client.post(MEMBER_URL, json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == error
    mock_db.reset_user_two_factor.assert_not_called()


def test_owner_scope_comes_from_the_token_not_the_path(as_owner, mock_db):
    """Naming another workspace's slug in the URL does not move the check to that workspace."""
    client.post(f"/v1/access/someone-elses-workspace/members/{USER_ID}/two-factor/reset", json=BODY)
    mock_db.get_effective_role_slug.assert_called_once_with(TENANT_ID, OWNER_ID)
    assert mock_db.reset_user_two_factor.call_args.kwargs["tenant_id"] == TENANT_ID
