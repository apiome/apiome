"""``owner`` in list envelopes, with one SQL join — CDG-2.2 (#5961).

Catalog items, projects, MCP endpoints and consumers each carry ``owner: {team, status, source}``.
The acceptance criterion is that no list read grows a round trip, so — as
``test_scoped_catalog_store`` does — a recording connection counts the statements each read issues:
exactly one, and that one joins ``apiome.entity_owners``. The routes then serialize the column the
join adds as ``owner``.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.database import Database
from app.main import app

_TENANT = "11111111-1111-4111-8111-111111111111"
_PROJECT = "22222222-2222-4222-8222-222222222222"
_OWNER = {
    "team": {"id": "33333333-3333-4333-8333-333333333333", "slug": "payments", "name": "Payments"},
    "status": "confirmed",
    "source": "gateway_tag",
}


class _Cursor:
    def __init__(self, conn: "_Connection") -> None:
        self.conn = conn

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, query: str, params: Any = None) -> None:
        self.conn.statements.append(" ".join(query.split()))

    def fetchall(self) -> List[Dict[str, Any]]:
        return []


class _Connection:
    closed = False

    def __init__(self) -> None:
        self.statements: List[str] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


@pytest.fixture
def counted():
    database = Database()
    conn = _Connection()
    with patch.object(database, "connect", return_value=conn):
        yield database, conn


@pytest.mark.parametrize(
    "read,kinds",
    [
        (lambda d: d.get_projects_for_tenant(_TENANT), "('project', 'catalog_item')"),
        (lambda d: d.get_catalog_items_for_tenant(_TENANT), "('project', 'catalog_item')"),
        (lambda d: d.list_mcp_endpoints(_TENANT), "('mcp_endpoint')"),
        (lambda d: d.list_consumers(_PROJECT, _TENANT), "('consumer')"),
    ],
    ids=["projects", "catalog", "mcp-endpoints", "consumers"],
)
def test_each_list_read_embeds_the_owner_in_one_statement(counted, read, kinds) -> None:
    database, conn = counted
    read(database)
    assert len(conn.statements) == 1
    statement = conn.statements[0]
    assert "FROM apiome.entity_owners eo" in statement
    assert f"eo.entity_kind IN {kinds}" in statement
    assert "own.entity_owner" in statement


# ---------------------------------------------------------------------------------------------
# Route envelopes
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def authed():
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": "u-1", "auth_method": "jwt",
    }
    yield TestClient(app)
    app.dependency_overrides.clear()


def _project_row(**extra: Any) -> Dict[str, Any]:
    row = {
        "id": _PROJECT, "tenant_id": _TENANT, "name": "Pets", "slug": "pets",
        "publishable": True, "versions_count": 0, "entity_owner": _OWNER,
    }
    row.update(extra)
    return row


def test_the_projects_list_carries_owner(authed) -> None:
    with patch("app.projects_routes.db.get_projects_for_tenant", return_value=[_project_row()]):
        body = authed.get("/v1/projects/acme").json()
    assert body[0]["owner"] == _OWNER


def test_a_project_without_an_owner_says_null(authed) -> None:
    with patch(
        "app.projects_routes.db.get_projects_for_tenant",
        return_value=[_project_row(entity_owner=None)],
    ):
        body = authed.get("/v1/projects/acme").json()
    assert body[0]["owner"] is None


def test_the_catalog_list_carries_a_suggested_owner(authed) -> None:
    suggested = {**_OWNER, "status": "suggested"}
    with patch(
        "app.catalog_routes.db.get_catalog_items_for_tenant",
        return_value=[_project_row(publishable=False, entity_owner=suggested)],
    ), patch("app.catalog_routes.db.get_artifact_tags_for_projects", return_value={}):
        body = authed.get("/v1/catalog/acme").json()
    assert body[0]["owner"]["status"] == "suggested"
    assert body[0]["owner"]["team"]["slug"] == "payments"


def test_the_mcp_endpoint_list_carries_owner(authed) -> None:
    row = {
        "id": _PROJECT, "tenant_id": _TENANT, "name": "Tools", "slug": "tools",
        "endpoint_url": "https://mcp.example.com", "transport": "http", "visibility": "private",
        "published": False, "enabled": True, "entity_owner": _OWNER,
    }
    with patch("app.mcp_catalog_routes.db.list_mcp_endpoints", return_value=[row]):
        body = authed.get("/v1/mcp/acme/endpoints").json()
    assert body["endpoints"][0]["owner"] == _OWNER


def test_the_consumer_summary_carries_owner_beside_the_free_text_owner() -> None:
    from app.consumer_contract_store import list_consumer_summaries

    row = {
        "id": "44444444-4444-4444-8444-444444444444", "tenant_id": _TENANT,
        "project_id": _PROJECT, "slug": "billing", "name": "Billing", "owner": "Squad B",
        "metadata": {}, "entity_owner": _OWNER,
    }
    with patch("app.consumer_contract_store.db.list_consumers", return_value=[row]), patch(
        "app.consumer_contract_store.db.list_current_consumer_contracts", return_value=[]
    ):
        summaries = list_consumer_summaries(_TENANT, _PROJECT)
    assert summaries[0].consumer.owner == "Squad B"
    assert summaries[0].owner is not None and summaries[0].owner.team.slug == "payments"
