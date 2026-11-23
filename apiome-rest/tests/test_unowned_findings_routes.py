"""``GET /v1/tenants/{tenant}/unowned-findings`` — CDG-2.3 (#5962).

The Unowned findings report: gated on ``teams:view``, paged, filterable by type, and shaped the way the
CDG-2.5 surface will read it.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import unowned_findings_routes as routes
from app.auth import validate_authentication
from app.main import app

client = TestClient(app)
_TENANT = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def calls(monkeypatch) -> List[Dict[str, Any]]:
    seen: List[Dict[str, Any]] = []

    def _list(
        db, tenant_id, *, finding_type=None, limit=50, offset=0, cursor=None, include_total=False
    ):
        seen.append({"tenant": tenant_id, "type": finding_type, "limit": limit, "offset": offset})
        return {
            "items": [
                {
                    "id": "u-1", "entity_kind": "catalog_item",
                    "entity_id": "22222222-2222-4222-8222-222222222222",
                    "finding_type": "owner_breaking_change",
                    "payload": {"summary": "2 breaking changes", "link": "/ade/dashboard/catalog/x"},
                    "occurrences": 3, "first_seen_at": "2026-10-18T10:00:00+00:00",
                    "last_seen_at": "2026-10-18T11:00:00+00:00",
                }
            ],
            "total": 1 if include_total else None,
            "has_more": False,
            "next_cursor": None,
        }

    monkeypatch.setattr(routes, "list_unowned_findings", _list)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": "u", "auth_method": "jwt",
    }
    yield seen
    app.dependency_overrides.clear()


def test_the_report_lists_entries_with_occurrences(calls) -> None:
    body = client.get(
        "/v1/tenants/acme/unowned-findings?type=owner_breaking_change&limit=10&include_total=true"
    ).json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["occurrences"] == 3 and item["payload"]["summary"] == "2 breaking changes"
    assert calls == [{"tenant": _TENANT, "type": "owner_breaking_change", "limit": 10, "offset": 0}]


def test_the_report_needs_teams_view(calls, monkeypatch) -> None:
    asked: List[str] = []

    def _has(tenant_id, user_id, resource, action):
        asked.append(f"{resource}:{action}")
        return False

    monkeypatch.setattr(routes.db, "user_has_permission", _has)
    monkeypatch.setattr(routes.db, "write_access_audit", lambda **kw: None)
    assert client.get("/v1/tenants/acme/unowned-findings").status_code == 403
    assert asked == ["teams:view"] and calls == []


def test_an_unknown_type_is_rejected(calls) -> None:
    assert client.get("/v1/tenants/acme/unowned-findings?type=mention").status_code == 422


# --- Keyset paging (#7196) ---------------------------------------------------

_URL = "/v1/tenants/acme/unowned-findings"


class _ReportDb:
    """Answers the report's two statements from rows held in memory, like the SQL would."""

    def __init__(self, rows: List[Dict[str, Any]]) -> None:
        self.rows = sorted(rows, key=lambda r: (r["last_seen_at"], r["id"]), reverse=True)
        self.statements: List[Any] = []

    def execute_query(self, sql: str, params: Any = ()) -> List[Dict[str, Any]]:
        self.statements.append((sql, tuple(params)))
        if "capped" in sql:
            return [{"total": len(self.rows)}]
        rows = self.rows
        if "(last_seen_at, id) < (%s, %s::uuid)" in sql:
            stamp, row_id = params[-4], params[-3]
            rows = [r for r in rows if (r["last_seen_at"], r["id"]) < (stamp, row_id)]
        limit, offset = params[-2], params[-1]
        return [dict(r) for r in rows[offset : offset + limit]]


def _findings(count: int) -> List[Dict[str, Any]]:
    from tests.keyset_paging_fakes import stamps

    return [
        {
            "id": f"33333333-3333-4333-8333-{index:012d}",
            "entity_kind": "catalog_item",
            "entity_id": "22222222-2222-4222-8222-222222222222",
            "finding_type": "owner_finding",
            "payload": {},
            "occurrences": 1,
            "first_seen_at": stamp,
            "last_seen_at": stamp,
        }
        for index, stamp in enumerate(stamps(count))
    ]


@pytest.fixture
def report(monkeypatch) -> _ReportDb:
    fake = _ReportDb(_findings(5))
    monkeypatch.setattr(routes, "db", fake)
    monkeypatch.setattr(routes, "enforce_permission", lambda *a, **k: None)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": "u", "auth_method": "jwt",
    }
    yield fake
    app.dependency_overrides.clear()


def test_the_report_pages_by_cursor_to_the_end(report) -> None:
    from tests.keyset_paging_fakes import walk

    seen = walk(lambda params: client.get(_URL, params=params), "items")
    ids = [item["id"] for item in seen]
    assert ids == [row["id"] for row in report.rows]
    assert len(ids) == len(set(ids)) == 5
    # Paging never counted.
    assert not any("capped" in sql for sql, _ in report.statements)


def test_the_report_counts_only_when_asked(report) -> None:
    assert client.get(_URL).json()["total"] is None
    body = client.get(_URL, params={"include_total": "true", "limit": 2}).json()
    assert body["total"] == 5 and body["has_more"] is True and body["next_cursor"]
    count_sql = next(sql for sql, _ in report.statements if "capped" in sql)
    assert "LIMIT 10000" in count_sql


def test_the_report_query_is_a_total_order_and_a_cursor_drops_the_offset(report) -> None:
    from app.keyset_pagination import encode_time_id_cursor

    last = report.rows[1]
    token = encode_time_id_cursor(last["last_seen_at"], last["id"])
    client.get(_URL, params={"cursor": token, "offset": 3, "limit": 2})
    sql, params = report.statements[-1]
    assert "ORDER BY last_seen_at DESC, id DESC" in sql
    assert "count(*) OVER ()" not in sql
    assert params[-2:] == (3, 0)


def test_the_report_refuses_a_malformed_cursor_and_oversized_pages(report) -> None:
    assert client.get(_URL, params={"cursor": "not-a-cursor"}).status_code == 400
    assert client.get(_URL, params={"limit": 201}).status_code == 422
    assert client.get(_URL, params={"offset": 10_001}).status_code == 422
