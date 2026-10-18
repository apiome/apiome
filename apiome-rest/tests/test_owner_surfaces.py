"""Ownership surfaces, server half — CDG-2.4 (#5963).

* ``?team=`` filters every owner-aware list **in SQL**, on the owner the list shows (confirmed, else
  suggested): catalog, projects, MCP browse and consumers. The reads stay one statement.
* ``GET /v1/tenants/{t}/teams/{slug}/activity`` returns what the team owns, how many entities
  suggest it, the caller's unread owner-finding rows for it (the bell's own count) and the last 30
  days of routed events, one per event.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import team_routes, team_store
from app.auth import validate_authentication
from app.database import Database
from app.entity_owners import owner_team_filter
from app.main import app
from app.teams import CODE_NOT_FOUND, TeamRecord, TeamValidationError

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_USER = "33333333-3333-4333-8333-333333333333"
_TEAM_ID = "44444444-4444-4444-8444-444444444444"


# ---------------------------------------------------------------------------------------------
# ?team= in SQL
# ---------------------------------------------------------------------------------------------


def test_the_team_filter_clause() -> None:
    assert owner_team_filter(" Payments ") == ("AND own.entity_owner->'team'->>'slug' = %s", ["payments"])
    assert owner_team_filter(None) == ("", [])
    assert owner_team_filter("  ") == ("", [])


class _Cursor:
    def __init__(self, conn: "_Connection") -> None:
        self.conn = conn

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, query: str, params: Any = None) -> None:
        self.conn.statements.append((" ".join(query.split()), tuple(params or ())))

    def fetchall(self) -> List[Dict[str, Any]]:
        return []


class _Connection:
    closed = False

    def __init__(self) -> None:
        self.statements: List[Any] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


@pytest.mark.parametrize(
    "read",
    [
        lambda d: d.get_projects_for_tenant(_TENANT, team="payments"),
        lambda d: d.get_catalog_items_for_tenant(_TENANT, team="payments"),
        lambda d: d.browse_mcp_endpoints(_TENANT, team="payments"),
        lambda d: d.list_consumers(_PROJECT, _TENANT, team="payments"),
    ],
    ids=["projects", "catalog", "mcp-browse", "consumers"],
)
def test_each_list_filters_by_team_in_its_one_statement(read) -> None:
    database = Database()
    conn = _Connection()
    with patch.object(database, "connect", return_value=conn):
        read(database)
    assert len(conn.statements) == 1
    sql, params = conn.statements[0]
    assert "own.entity_owner->'team'->>'slug' = %s" in sql
    assert params[-1] == "payments"


def test_an_unfiltered_read_has_no_team_clause() -> None:
    database = Database()
    conn = _Connection()
    with patch.object(database, "connect", return_value=conn):
        database.browse_mcp_endpoints(_TENANT)
    sql, params = conn.statements[0]
    assert "->>'slug' = %s" not in sql and params == (_TENANT,)
    assert "own.entity_owner" in sql


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_routes_pass_team_through(authed) -> None:
    with patch("app.projects_routes.db.get_projects_for_tenant", return_value=[]) as projects, patch(
        "app.catalog_routes.db.get_catalog_items_for_tenant", return_value=[]
    ) as catalog, patch("app.catalog_routes.db.get_artifact_tags_for_projects", return_value={}), patch(
        "app.mcp_catalog_routes.db.browse_mcp_endpoints", return_value=[]
    ) as browse:
        assert authed.get("/v1/projects/acme", params={"team": "payments"}).status_code == 200
        assert authed.get("/v1/catalog/acme", params={"team": "payments"}).status_code == 200
        assert authed.get("/v1/mcp/acme/browse", params={"team": "payments"}).status_code == 200
    assert projects.call_args.kwargs["team"] == "payments"
    assert catalog.call_args.kwargs["team"] == "payments"
    assert browse.call_args.kwargs["team"] == "payments"


def test_a_browse_endpoint_carries_its_owner() -> None:
    from app.models import mcp_browse_endpoint_out_from_row

    owner = {"team": {"id": _TEAM_ID, "slug": "payments", "name": "Payments"}, "status": "suggested", "source": "hub"}
    row = {
        "id": _PROJECT, "tenant_id": _TENANT, "name": "Tools", "slug": "tools",
        "endpoint_url": "https://mcp.example.com", "transport": "http", "visibility": "private",
        "published": False, "enabled": True, "entity_owner": owner,
    }
    out = mcp_browse_endpoint_out_from_row(row)
    assert out.owner is not None and out.owner.team.slug == "payments" and out.owner.status == "suggested"


# ---------------------------------------------------------------------------------------------
# team activity
# ---------------------------------------------------------------------------------------------


def _team() -> TeamRecord:
    return TeamRecord(id=_TEAM_ID, slug="payments", name="Payments", member_count=2)


def test_activity_counts_the_callers_unread_owner_rows_and_groups_events(monkeypatch) -> None:
    queries: List[Any] = []

    def _query(sql: str, params: Any = None) -> List[Dict[str, Any]]:
        flat = " ".join(sql.split())
        queries.append((flat, params))
        if "FROM apiome.entity_owners eo" in flat:
            return [
                {"entity_kind": "project", "entity_id": _PROJECT, "source": "manual", "name": "Payments API"},
                {"entity_kind": "connector", "entity_id": _USER, "source": "manual", "name": "Prod Kong"},
            ]
        if "status = 'suggested'" in flat:
            return [{"n": 4}]
        if "read_at IS NULL" in flat:
            return [{"n": 3}]
        if "GROUP BY type" in flat:
            return [{"type": "owner_finding", "entity_kind": "project", "entity_id": _PROJECT,
                     "entity_name": "Payments API", "summary": "2 new error-level lint findings",
                     "link": "/ade/x", "created_at": None, "recipients": 2}]
        raise AssertionError(flat)

    monkeypatch.setattr(team_store, "get_team", lambda tenant, slug: _team())
    monkeypatch.setattr(team_store.db, "execute_query", _query)
    activity = team_store.team_activity(_TENANT, "payments", _USER)

    assert activity["owned_counts"] == {"project": 1, "connector": 1}
    assert activity["suggested_count"] == 4 and activity["open_findings"] == 3
    assert activity["events"][0]["recipients"] == 2
    unread_sql, unread_params = next(q for q in queries if "read_at IS NULL" in q[0])
    assert "user_id = %s::uuid" in unread_sql and unread_params[1] == _USER
    assert "payload->'team'->>'id' = %s" in unread_sql and unread_params[3] == _TEAM_ID
    events_sql, events_params = next(q for q in queries if "GROUP BY type" in q[0])
    assert "date_trunc('minute', created_at)" in events_sql and events_params[3] == team_store.ACTIVITY_DAYS
    # Only confirmed ownership counts as owned.
    assert "eo.status = 'confirmed'" in next(q for q in queries if "FROM apiome.entity_owners eo" in q[0])[0]


def test_an_unattributable_caller_has_no_open_findings(monkeypatch) -> None:
    monkeypatch.setattr(team_store, "get_team", lambda tenant, slug: _team())
    monkeypatch.setattr(
        team_store.db, "execute_query",
        lambda sql, params=None: [] if "GROUP BY" in sql or "eo.entity_kind" in sql else [{"n": 0}],
    )
    assert team_store.team_activity(_TENANT, "payments", None)["open_findings"] == 0


def test_the_activity_route_needs_teams_view_and_maps_an_unknown_team(authed, monkeypatch) -> None:
    asked: List[str] = []

    def _has(tenant_id, user_id, resource, action):
        asked.append(f"{resource}:{action}")
        return True

    monkeypatch.setattr(team_routes.db, "user_has_permission", _has)
    monkeypatch.setattr(
        team_routes, "team_activity",
        lambda tenant, slug, viewer: {"team_id": _TEAM_ID, "owned": [], "owned_counts": {},
                                      "suggested_count": 0, "open_findings": 1, "events": []},
    )
    body = authed.get("/v1/tenants/acme/teams/payments/activity").json()
    assert body["open_findings"] == 1 and asked == ["teams:view"]

    def _missing(tenant, slug, viewer):
        raise TeamValidationError(CODE_NOT_FOUND, "no team")

    monkeypatch.setattr(team_routes, "team_activity", _missing)
    response = authed.get("/v1/tenants/acme/teams/ghost/activity")
    assert response.status_code == 404 and response.json()["detail"]["code"] == CODE_NOT_FOUND
