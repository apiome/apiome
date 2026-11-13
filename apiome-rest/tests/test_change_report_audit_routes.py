"""API tests for the change-report audit list (#2705, CR-V2-01).

``GET /v1/tenants/{tenant_slug}/change-report-audit``: tenant-admin only, filters passed to
the database layer, validation of bad filters, and keyset pagination.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

_ADMIN = {"tenant_id": "t1", "user_id": "admin-b", "auth_method": "jwt"}
_MEMBER = {"tenant_id": "t1", "user_id": "member-c", "auth_method": "jwt"}
_API_KEY = {"tenant_id": "t1", "tenant_slug": "tn", "auth_method": "api_key"}
_URL = "/v1/tenants/tn/change-report-audit"
_T0 = datetime(2026, 11, 13, 12, 0, 0, tzinfo=timezone.utc)
_UUID_A = "11111111-1111-4111-8111-111111111111"
_UUID_B = "22222222-2222-4222-8222-222222222222"


def _row(n, **overrides):
    """Audit row ``n`` — newer rows have a smaller ``n``."""
    row = {
        "id": f"00000000-0000-4000-8000-{n:012d}",
        "tenant_id": "t1",
        "project_id": _UUID_A,
        "change_report_id": _UUID_B,
        "published_revision_id": _UUID_B,
        "template_version_id": None,
        "action": "report.approve",
        "actor_id": "admin-b",
        "detail": {"from": "pending_review", "to": "approved", "note": None},
        "created_at": _T0 - timedelta(minutes=n),
    }
    row.update(overrides)
    return row


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: _ADMIN
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def mdb():
    with patch("app.change_report_enterprise_routes.db") as mock_db:
        mock_db.is_user_tenant_admin.side_effect = lambda tenant_id, user_id: user_id == "admin-b"
        mock_db.list_change_report_audit.return_value = []
        yield mock_db


def test_an_admin_reads_the_trail_newest_first(mdb):
    mdb.list_change_report_audit.return_value = [_row(1), _row(2, action="report.submit")]

    r = client.get(_URL)

    assert r.status_code == 200
    body = r.json()
    assert [i["action"] for i in body["items"]] == ["report.approve", "report.submit"]
    first = body["items"][0]
    assert first["actorId"] == "admin-b"
    assert first["publishedRevisionId"] == _UUID_B
    assert first["detail"]["to"] == "approved"
    assert first["createdAt"].startswith("2026-11-13T11:59:00")
    assert body["limit"] == 50
    assert body["nextCursor"] is None


def test_the_trail_is_scoped_to_the_callers_tenant(mdb):
    client.get("/v1/tenants/some-other-slug/change-report-audit")

    assert mdb.list_change_report_audit.call_args.args == ("t1",)


@pytest.mark.parametrize("auth", [_MEMBER, _API_KEY])
def test_only_a_tenant_admin_may_read_it(mdb, auth):
    app.dependency_overrides[validate_authentication] = lambda: auth

    r = client.get(_URL)

    assert r.status_code == 403
    mdb.list_change_report_audit.assert_not_called()


def test_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)

    assert client.get(_URL).status_code == 401


def test_filters_reach_the_database_layer(mdb):
    r = client.get(
        _URL,
        params={
            "action": ["report.approve", "report.export_pdf"],
            "actorId": _UUID_A,
            "projectId": _UUID_A,
            "versionId": _UUID_B,
            "since": "2026-11-01T00:00:00Z",
            "until": "2026-11-30T23:59:59Z",
            "limit": 10,
        },
    )

    assert r.status_code == 200
    kwargs = mdb.list_change_report_audit.call_args.kwargs
    assert kwargs["actions"] == ["report.approve", "report.export_pdf"]
    assert kwargs["actor_id"] == _UUID_A
    assert kwargs["project_id"] == _UUID_A
    assert kwargs["published_revision_id"] == _UUID_B
    assert kwargs["since"] == datetime(2026, 11, 1, tzinfo=timezone.utc)
    assert kwargs["until"] == datetime(2026, 11, 30, 23, 59, 59, tzinfo=timezone.utc)
    # One row beyond the page, to learn whether an older page exists.
    assert kwargs["limit"] == 11
    assert kwargs["before"] is None


def test_no_filters_means_no_narrowing(mdb):
    client.get(_URL)

    kwargs = mdb.list_change_report_audit.call_args.kwargs
    assert kwargs["actions"] is None
    assert kwargs["actor_id"] is None and kwargs["project_id"] is None
    assert kwargs["since"] is None and kwargs["until"] is None


@pytest.mark.parametrize(
    "params, fragment",
    [
        ({"action": "report.publish"}, "Unknown action"),
        ({"actorId": "not-a-uuid"}, "Invalid actorId"),
        ({"projectId": "nope"}, "Invalid projectId"),
        ({"versionId": "nope"}, "Invalid versionId"),
        ({"since": "last tuesday"}, "Invalid since"),
        ({"cursor": "!!!"}, "Invalid cursor"),
    ],
)
def test_bad_filters_are_400(mdb, params, fragment):
    r = client.get(_URL, params=params)

    assert r.status_code == 400
    assert fragment in r.json()["detail"]
    mdb.list_change_report_audit.assert_not_called()


@pytest.mark.parametrize("limit", [0, 201])
def test_limit_is_bounded(mdb, limit):
    assert client.get(_URL, params={"limit": limit}).status_code == 422


def test_a_full_page_hands_back_a_cursor_that_fetches_the_next_one(mdb):
    mdb.list_change_report_audit.return_value = [_row(1), _row(2), _row(3)]

    first = client.get(_URL, params={"limit": 2})

    body = first.json()
    assert len(body["items"]) == 2
    cursor = body["nextCursor"]
    assert cursor

    mdb.list_change_report_audit.return_value = [_row(3)]
    second = client.get(_URL, params={"limit": 2, "cursor": cursor})

    assert second.status_code == 200
    assert second.json()["nextCursor"] is None
    before = mdb.list_change_report_audit.call_args.kwargs["before"]
    # The cursor points at the last row of the first page: strictly older rows follow.
    assert before == (_row(2)["created_at"], _row(2)["id"])


def test_template_events_have_no_report_ids(mdb):
    mdb.list_change_report_audit.return_value = [
        _row(1, action="template.create", change_report_id=None, published_revision_id=None,
             project_id=None, template_version_id=_UUID_A, detail={"semver": "1.2.0"})
    ]

    item = client.get(_URL).json()["items"][0]

    assert item["changeReportId"] is None
    assert item["templateVersionId"] == _UUID_A
    assert item["detail"] == {"semver": "1.2.0"}


def test_gating_on_refuses_a_tenant_without_the_entitlement():
    with patch("app.feature_gating.settings") as settings, patch("app.feature_gating.db") as gdb:
        settings.change_report_enterprise_gating_enabled = True
        gdb.tenant_has_feature_flag.return_value = False

        assert client.get(_URL).status_code == 403
