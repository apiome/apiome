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

    def _list(db, tenant_id, *, finding_type=None, limit=50, offset=0):
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
            "total": 1,
        }

    monkeypatch.setattr(routes, "list_unowned_findings", _list)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": "u", "auth_method": "jwt",
    }
    yield seen
    app.dependency_overrides.clear()


def test_the_report_lists_entries_with_occurrences(calls) -> None:
    body = client.get("/v1/tenants/acme/unowned-findings?type=owner_breaking_change&limit=10").json()
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
