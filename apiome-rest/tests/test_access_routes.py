"""API tests for the Access & IAM routes (#3611): roles, members, audit, platform override."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import validate_authentication, validate_session_credentials
from app.main import app
from app.permissions import Action, Resource

client = TestClient(app)

_AUTH = {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "user_id": "22222222-2222-2222-2222-222222222222",
    "auth_method": "jwt",
    "user_email": "owner@acme.io",
}

_ROLE_EDITOR = {
    "id": "role-editor",
    "slug": "editor",
    "name": "Editor",
    "description": "Edit content",
    "is_builtin": True,
    "member_count": 12,
}
_ROLE_CUSTOM = {
    "id": "role-rm",
    "slug": "release-manager",
    "name": "Release Manager",
    "description": "Publish versions",
    "is_builtin": False,
    "member_count": 2,
}


@pytest.fixture(autouse=True)
def _auth_override():
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    app.dependency_overrides[validate_session_credentials] = lambda: _AUTH
    yield
    app.dependency_overrides.pop(validate_authentication, None)
    app.dependency_overrides.pop(validate_session_credentials, None)


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


def test_list_roles_returns_grids_and_counts():
    with patch("app.access_routes.db") as mdb:
        mdb.list_roles.return_value = [_ROLE_EDITOR, _ROLE_CUSTOM]
        mdb.get_role_permissions.return_value = [
            {"resource": "versions", "action": "view"},
            {"resource": "versions", "action": "publish"},
        ]
        r = client.get("/v1/access/acme/roles")
    assert r.status_code == 200
    body = r.json()
    assert [x["slug"] for x in body] == ["editor", "release-manager"]
    assert body[0]["member_count"] == 12
    assert {"resource": "versions", "action": "publish"} in body[0]["permissions"]
    mdb.ensure_builtin_roles.assert_called_once_with(_AUTH["tenant_id"])


def test_create_role_rejects_invalid_permission():
    with patch("app.access_routes.db") as mdb:
        r = client.post(
            "/v1/access/acme/roles",
            json={"name": "Bad", "permissions": [{"resource": "versions", "action": "frobnicate"}]},
        )
    assert r.status_code == 400
    mdb.create_role.assert_not_called()


def test_create_role_persists_grid_and_audits():
    with patch("app.access_routes.db") as mdb:
        mdb.create_role.return_value = {**_ROLE_CUSTOM}
        mdb.get_role_permissions.return_value = [{"resource": "versions", "action": "publish"}]
        r = client.post(
            "/v1/access/acme/roles",
            json={
                "name": "Release Manager",
                "description": "Publish versions",
                "permissions": [
                    {"resource": "versions", "action": "publish"},
                    {"resource": "versions", "action": "view"},
                ],
            },
        )
    assert r.status_code == 200
    assert r.json()["slug"] == "release-manager"
    # Slug derived from the name.
    args = mdb.create_role.call_args.args
    assert args[1] == "release-manager"
    mdb.set_role_permissions.assert_called_once()
    assert mdb.write_access_audit.call_args.kwargs["action"] == "role.created"


def test_update_builtin_role_keeps_name_and_logs_permission_change():
    with patch("app.access_routes.db") as mdb:
        mdb.get_role.return_value = {**_ROLE_EDITOR}
        # Existing grid has view+create; request drops create, adds delete.
        mdb.get_role_permissions.return_value = [
            {"resource": "classes", "action": "view"},
            {"resource": "classes", "action": "create"},
        ]
        mdb.update_role.return_value = {**_ROLE_EDITOR}
        r = client.put(
            "/v1/access/acme/roles/role-editor",
            json={
                "name": "Renamed (ignored for builtin)",
                "permissions": [
                    {"resource": "classes", "action": "view"},
                    {"resource": "classes", "action": "delete"},
                ],
            },
        )
    assert r.status_code == 200
    # Built-in name is immutable: update_role called with the original name.
    assert mdb.update_role.call_args.args[2] == "Editor"
    audit = mdb.write_access_audit.call_args.kwargs
    assert audit["action"] == "permission.changed"
    assert audit["detail"]["granted"] == ["classes:delete"]
    assert audit["detail"]["revoked"] == ["classes:create"]


def test_delete_builtin_role_forbidden():
    with patch("app.access_routes.db") as mdb:
        mdb.get_role.return_value = {**_ROLE_EDITOR}
        r = client.delete("/v1/access/acme/roles/role-editor")
    assert r.status_code == 400
    mdb.delete_role.assert_not_called()


def test_delete_custom_role_ok():
    with patch("app.access_routes.db") as mdb:
        mdb.get_role.return_value = {**_ROLE_CUSTOM}
        r = client.delete("/v1/access/acme/roles/role-rm")
    assert r.status_code == 204
    mdb.delete_role.assert_called_once()


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def _seat_available(ldb, used=1, limit=5):
    """Configure the license-capacity db mock with `used` of `limit` seats occupied."""
    ldb.get_tenant_license_seats.return_value = {"max_users_per_tenant": limit}
    ldb.count_member_seats_in_use.return_value = used


def test_invite_unknown_account_404():
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb)
        mdb.get_user_by_email.return_value = None
        r = client.post("/v1/access/acme/members", json={"email": "ghost@nowhere.com"})
    assert r.status_code == 404
    mdb.add_member.assert_not_called()


def test_invite_existing_account_assigns_role():
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb)
        mdb.get_user_by_email.return_value = {"id": "u-9", "email": "noah@partner.com"}
        mdb.get_role.return_value = {**_ROLE_CUSTOM}
        r = client.post(
            "/v1/access/acme/members",
            json={"email": "noah@partner.com", "role_id": "role-rm"},
        )
    assert r.status_code == 200
    mdb.add_member.assert_called_once()
    mdb.assign_member_role.assert_called_once()
    assert mdb.write_access_audit.call_args.kwargs["action"] == "member.invited"


def test_invite_blocked_when_seats_exhausted():
    # OLO-5.3 (#4213): the 6th non-suspended member on a 5-seat license is refused
    # with the structured code before any lookup or membership write happens.
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb, used=5, limit=5)
        r = client.post("/v1/access/acme/members", json={"email": "noah@partner.com"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "license-seats-exhausted"
    mdb.get_user_by_email.assert_not_called()
    mdb.add_member.assert_not_called()


def test_suspend_member_audits():
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        mdb.set_member_status.return_value = 1
        r = client.patch("/v1/access/acme/members/u-9", json={"status": "suspended"})
    assert r.status_code == 200
    mdb.set_member_status.assert_called_once_with(_AUTH["tenant_id"], "u-9", "suspended")
    assert mdb.write_access_audit.call_args.kwargs["action"] == "member.suspended"
    # Suspending frees a seat; it must never consult the capacity guard.
    ldb.count_member_seats_in_use.assert_not_called()


def test_reinstate_blocked_when_seats_exhausted():
    # OLO-5.3 (#4213): a suspended member doesn't hold a seat, so reinstating one
    # consumes a seat and is refused at capacity (blocks the suspend → invite →
    # reinstate bypass).
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb, used=5, limit=5)
        mdb.get_member_status.return_value = "suspended"
        r = client.patch("/v1/access/acme/members/u-9", json={"status": "active"})
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "license-seats-exhausted"
    mdb.set_member_status.assert_not_called()


def test_reinstate_allowed_with_free_seat():
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb, used=4, limit=5)
        mdb.get_member_status.return_value = "suspended"
        mdb.set_member_status.return_value = 1
        r = client.patch("/v1/access/acme/members/u-9", json={"status": "active"})
    assert r.status_code == 200
    mdb.set_member_status.assert_called_once_with(_AUTH["tenant_id"], "u-9", "active")
    assert mdb.write_access_audit.call_args.kwargs["action"] == "member.reinstated"


def test_status_change_between_seated_states_skips_capacity_check():
    # active → pending (or re-asserting active) never consumes a new seat, so the
    # guard is not consulted even when the tenant is at capacity.
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb, used=5, limit=5)
        mdb.get_member_status.return_value = "active"
        mdb.set_member_status.return_value = 1
        r = client.patch("/v1/access/acme/members/u-9", json={"status": "pending"})
    assert r.status_code == 200
    ldb.count_member_seats_in_use.assert_not_called()


def test_update_member_rejects_bad_status():
    with patch("app.access_routes.db") as mdb:
        r = client.patch("/v1/access/acme/members/u-9", json={"status": "banished"})
    assert r.status_code == 400
    mdb.set_member_status.assert_not_called()


def test_resend_invite_restamps_pending_membership_and_audits():
    # HIVE-5.2 (#5305): re-issuing renews the pending row and records who renewed it.
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        mdb.touch_pending_membership.return_value = 1
        r = client.post("/v1/access/acme/members/u-9/resend-invite")
    assert r.status_code == 200
    assert r.json() == {"user_id": "u-9", "status": "pending"}
    mdb.touch_pending_membership.assert_called_once_with(_AUTH["tenant_id"], "u-9")
    assert mdb.write_access_audit.call_args.kwargs["action"] == "member.invite_resent"
    # The pending membership already holds its seat, so no capacity check is owed.
    ldb.count_member_seats_in_use.assert_not_called()


def test_resend_invite_404_when_not_a_member():
    with patch("app.access_routes.db") as mdb:
        mdb.touch_pending_membership.return_value = 0
        mdb.get_member_status.return_value = None
        r = client.post("/v1/access/acme/members/u-nope/resend-invite")
    assert r.status_code == 404
    mdb.write_access_audit.assert_not_called()


def test_resend_invite_409_when_membership_is_not_pending():
    # An already-accepted invitation has nothing outstanding to renew, and saying so is
    # a different message from "no such member".
    with patch("app.access_routes.db") as mdb:
        mdb.touch_pending_membership.return_value = 0
        mdb.get_member_status.return_value = "active"
        r = client.post("/v1/access/acme/members/u-9/resend-invite")
    assert r.status_code == 409
    assert "no outstanding invitation" in r.json()["detail"]
    mdb.write_access_audit.assert_not_called()


def test_offboard_member_ok():
    with patch("app.access_routes.db") as mdb:
        mdb.remove_member.return_value = 1
        r = client.delete("/v1/access/acme/members/u-9")
    assert r.status_code == 204
    assert mdb.write_access_audit.call_args.kwargs["action"] == "member.offboarded"


# ---------------------------------------------------------------------------
# Audit + self permissions
# ---------------------------------------------------------------------------


def test_list_audit_filter_maps_to_prefix():
    with patch("app.access_routes.db") as mdb:
        mdb.list_access_audit.return_value = []
        client.get("/v1/access/acme/audit?filter=role")
        assert mdb.list_access_audit.call_args.kwargs["action_prefix"] == "role."


def test_list_audit_style_guide_filter_maps_to_governance_prefix():
    """The sixth category the server has always understood, which the UI exposes in HIVE-5.5."""
    with patch("app.access_routes.db") as mdb:
        mdb.list_access_audit.return_value = []
        client.get("/v1/access/acme/audit?filter=styleGuide")
        assert mdb.list_access_audit.call_args.kwargs["action_prefix"] == "style_guide."


def test_list_audit_since_becomes_an_aware_lower_bound():
    with patch("app.access_routes.db") as mdb:
        mdb.list_access_audit.return_value = []
        r = client.get("/v1/access/acme/audit?since=2026-08-01T00:00:00Z")
    assert r.status_code == 200
    since = mdb.list_access_audit.call_args.kwargs["since"]
    assert since == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_list_audit_naive_since_is_read_as_utc():
    with patch("app.access_routes.db") as mdb:
        mdb.list_access_audit.return_value = []
        client.get("/v1/access/acme/audit?since=2026-08-01T00:00:00")
    assert mdb.list_access_audit.call_args.kwargs["since"].tzinfo == timezone.utc


def test_list_audit_without_since_leaves_the_bound_open():
    with patch("app.access_routes.db") as mdb:
        mdb.list_access_audit.return_value = []
        client.get("/v1/access/acme/audit")
    assert mdb.list_access_audit.call_args.kwargs["since"] is None


def test_list_audit_rejects_an_unparsable_since():
    """Refused rather than dropped: a silently ignored bound exports more than was asked for."""
    with patch("app.access_routes.db") as mdb:
        r = client.get("/v1/access/acme/audit?since=last-tuesday")
    assert r.status_code == 400
    mdb.list_access_audit.assert_not_called()


def test_export_audit_csv():
    with patch("app.access_routes.db") as mdb:
        mdb.list_access_audit.return_value = [
            {
                "created_at": "2026-06-23T10:00:00Z",
                "actor_label": "dana@acme.io",
                "action": "role.assigned",
                "target": "priya@acme.io",
                "source": "web",
            }
        ]
        r = client.get("/v1/access/acme/audit/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "role.assigned" in r.text
    assert "when,actor,event,target,source" in r.text
    # The unnarrowed export is what it always was: the whole ledger, capped at 1000.
    kwargs = mdb.list_access_audit.call_args.kwargs
    assert kwargs["action_prefix"] is None
    assert kwargs["since"] is None
    assert kwargs["limit"] == 1000


def test_export_audit_csv_honours_the_filter_set():
    """The CSV round-trips what the reader was looking at, not a second wider answer."""
    with patch("app.access_routes.db") as mdb:
        mdb.list_access_audit.return_value = []
        r = client.get(
            "/v1/access/acme/audit/export?filter=member&since=2026-08-01T00:00:00Z"
        )
    assert r.status_code == 200
    kwargs = mdb.list_access_audit.call_args.kwargs
    assert kwargs["action_prefix"] == "member."
    assert kwargs["since"] == datetime(2026, 8, 1, tzinfo=timezone.utc)


def test_export_audit_rejects_an_unparsable_since():
    with patch("app.access_routes.db") as mdb:
        r = client.get("/v1/access/acme/audit/export?since=yesterday")
    assert r.status_code == 400
    mdb.list_access_audit.assert_not_called()


def test_permissions_me_admin_sees_everything():
    with patch("app.access_routes.db") as mdb:
        mdb.is_user_tenant_admin.return_value = True
        r = client.get("/v1/access/acme/permissions/me")
    assert r.status_code == 200
    body = r.json()
    assert body["is_admin"] is True
    assert "versions:publish" in body["permissions"]


def test_denied_when_guard_rejects():
    with patch("app.access_routes.db") as mdb:
        mdb.user_has_permission.return_value = False
        mdb.is_user_tenant_admin.return_value = False
        r = client.post("/v1/access/acme/roles", json={"name": "X", "permissions": []})
    assert r.status_code == 403
    mdb.create_role.assert_not_called()


# ---------------------------------------------------------------------------
# Platform-admin plane
# ---------------------------------------------------------------------------


def test_platform_override_requires_platform_admin():
    with patch("app.access_routes.db") as mdb:
        mdb.is_platform_admin.return_value = False
        r = client.post(
            "/v1/platform/access-overrides",
            json={"tenant_id": _AUTH["tenant_id"], "target": "billing@1.0.0"},
        )
    assert r.status_code == 403
    mdb.write_access_audit.assert_not_called()


def test_platform_override_records_admin_override():
    with patch("app.access_routes.db") as mdb:
        mdb.is_platform_admin.return_value = True
        r = client.post(
            "/v1/platform/access-overrides",
            json={"tenant_id": _AUTH["tenant_id"], "target": "billing@1.0.0", "detail": {"why": "support"}},
        )
    assert r.status_code == 201
    kwargs = mdb.write_access_audit.call_args.kwargs
    assert kwargs["action"] == "admin.override"
    assert kwargs["source"] == "admin"


# ---------------------------------------------------------------------------
# Bulk CSV import / export (EID-2.5, #5671)
# ---------------------------------------------------------------------------

# Every write the access routes can make. The dry run must reach none of them.
_MEMBER_WRITES = (
    "add_member",
    "assign_member_role",
    "set_member_status",
    "remove_member",
    "touch_pending_membership",
    "write_access_audit",
)


def _csv_upload(text, name="members.csv"):
    return {"file": (name, text.encode(), "text/csv")}


def _import_db(mdb, *, members=(), accounts=None):
    mdb.list_roles.return_value = [_ROLE_EDITOR, _ROLE_CUSTOM]
    mdb.list_members.return_value = [{"email": e} for e in members]
    mdb.get_users_by_emails.side_effect = lambda emails: (
        accounts if accounts is not None else {e.lower(): {"id": f"u-{e}", "email": e} for e in emails}
    )


def test_import_dry_run_reports_58_invites_and_names_the_two_bad_rows():
    lines = ["email,role,display_name"]
    for i in range(60):
        if i == 3:
            lines.append("not an email,Editor,Bad")
        elif i == 50:
            lines.append("p50@acme.io,Astronaut,Unknown")
        else:
            lines.append(f"p{i}@acme.io,editor,Person {i}")
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb, used=2, limit=100)
        _import_db(mdb)
        r = client.post("/v1/access/acme/members/import?dryRun=true", files=_csv_upload("\n".join(lines)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True
    assert body["total"] == 60
    assert body["seats_free"] == 98
    assert body["counts"]["invite"] == 58
    bad = [(row["line"], row["outcome"]) for row in body["rows"] if row["outcome"] != "invite"]
    assert bad == [(5, "invalid-email"), (52, "unknown-role")]
    invite = body["rows"][0]
    assert invite["role_id"] == "role-editor" and invite["email"] == "p0@acme.io"


def test_import_dry_run_changes_nothing():
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb)
        _import_db(mdb, members=["member@acme.io"])
        r = client.post(
            "/v1/access/acme/members/import",
            files=_csv_upload("email,role\nnew@acme.io,Editor\nmember@acme.io,\n"),
        )
    assert r.status_code == 200
    for write in _MEMBER_WRITES:
        getattr(mdb, write).assert_not_called()
    ldb.add_member.assert_not_called()
    assert [row["outcome"] for row in r.json()["rows"]] == ["invite", "already-member"]


def test_import_reports_seat_cap_past_the_free_seats():
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb, used=4, limit=5)
        _import_db(mdb)
        r = client.post(
            "/v1/access/acme/members/import?dryRun=true",
            files=_csv_upload("email\na@acme.io\nb@acme.io\n"),
        )
    assert [row["outcome"] for row in r.json()["rows"]] == ["invite", "seat-cap"]


def test_import_skips_the_seat_count_when_enforcement_is_off():
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb, patch(
        "app.access_routes.settings"
    ) as msettings:
        msettings.license_enforcement_enabled = False
        _seat_available(ldb, used=5, limit=5)
        _import_db(mdb)
        r = client.post("/v1/access/acme/members/import", files=_csv_upload("email\na@acme.io\n"))
    assert r.json()["seats_free"] is None
    assert r.json()["rows"][0]["outcome"] == "invite"


def test_import_reports_no_account_for_an_unknown_address():
    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb)
        _import_db(mdb, accounts={})
        r = client.post("/v1/access/acme/members/import", files=_csv_upload("email\nghost@acme.io\n"))
    assert r.json()["rows"][0]["outcome"] == "no-account"


def test_import_refuses_to_apply():
    with patch("app.access_routes.db") as mdb:
        r = client.post("/v1/access/acme/members/import?dryRun=false", files=_csv_upload("email\na@acme.io\n"))
    assert r.status_code == 400
    assert "POST /v1/access/acme/members" in r.json()["detail"]
    mdb.add_member.assert_not_called()


def test_import_refuses_an_unreadable_file():
    with patch("app.access_routes.db"):
        r = client.post("/v1/access/acme/members/import", files=_csv_upload("name\nAda\n"))
    assert r.status_code == 400
    assert "email column" in r.json()["detail"]


def test_import_refuses_more_than_1000_rows():
    text = "email\n" + "".join(f"p{i}@acme.io\n" for i in range(1001))
    with patch("app.access_routes.db"):
        r = client.post("/v1/access/acme/members/import", files=_csv_upload(text))
    assert r.status_code == 400
    assert "1000" in r.json()["detail"]


def test_import_refuses_a_file_over_1_mib():
    text = "email\n" + "x" * (1024 * 1024 + 10)
    with patch("app.access_routes.db"):
        r = client.post("/v1/access/acme/members/import", files=_csv_upload(text))
    assert r.status_code == 413


def test_import_needs_members_create():
    with patch("app.access_routes.enforce_permission") as guard, patch("app.access_routes.db"):
        guard.side_effect = HTTPException(status_code=403, detail="Forbidden")
        r = client.post("/v1/access/acme/members/import", files=_csv_upload("email\na@acme.io\n"))
    assert r.status_code == 403
    assert guard.call_args.args[2:] == (Resource.MEMBERS, Action.CREATE)


def test_export_members_csv_and_round_trip_as_already_member():
    roster = [
        {
            "user_id": "u-ada",
            "email": "ada@acme.io",
            "status": "active",
            "role_name": "Editor",
            "two_factor_enabled": True,
            "joined_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "user_id": "u-sam",
            "email": "sam@acme.io",
            "status": "pending",
            "role_name": None,
            "two_factor_enabled": False,
            "joined_at": "2026-02-02T00:00:00+00:00",
        },
    ]
    with patch("app.access_routes.db") as mdb:
        mdb.list_members.return_value = roster
        mdb.list_member_last_sign_ins.return_value = {"u-ada": "2026-06-14T08:00:00+00:00"}
        r = client.get("/v1/access/acme/members/export")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="acme-members.csv"' in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0] == "email,status,role,two_factor,provenance,last_sign_in,created"
    assert lines[1] == "ada@acme.io,active,Editor,enabled,invite,2026-06-14T08:00:00+00:00,2026-01-02T00:00:00+00:00"
    assert lines[2] == "sam@acme.io,pending,,disabled,invite,,2026-02-02T00:00:00+00:00"

    with patch("app.access_routes.db") as mdb, patch("app.license_capacity.db") as ldb:
        _seat_available(ldb)
        _import_db(mdb, members=["ada@acme.io", "sam@acme.io"])
        back = client.post("/v1/access/acme/members/import", files=_csv_upload(r.text))
    assert back.status_code == 200
    assert back.json()["counts"]["already-member"] == 2
    assert back.json()["counts"]["invite"] == 0
