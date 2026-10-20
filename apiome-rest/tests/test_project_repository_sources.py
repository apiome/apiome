"""Contributing repositories and per-entity provenance — REPO-5.7 (#2792).

``GET /v1/tenants/{tenant_slug}/projects/{project_ref}/repository-sources`` over a scripted
database (:class:`FakeSourcesDb`): the route, the RBAC guard, project / version resolution and the
read's assembly are real. Also pins the V301 migration's shape, since the import (apiome-ui) writes
the rows this read serves.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import comment_store, project_repository_sources, project_repository_sources_routes
from app.auth import validate_authentication
from app.main import app

client = TestClient(app)

TENANT = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0001"
OTHER_TENANT = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f00ff"
PROJECT = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0002"
VERSION_1 = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0010"
VERSION_2 = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0011"
SRC_USERS = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0030"
SRC_BILLING = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0031"
REPO_USERS = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0040"
REPO_BILLING = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0041"
ALICE = "5c1e0a10-2c4d-4e5f-8a9b-0c1d2e3f0101"
URL = "/v1/tenants/acme/projects/shop/repository-sources"
NOW = dt.datetime(2026, 10, 19, 12, 0, tzinfo=dt.timezone.utc)

MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "apiome-db"
    / "scripts"
    / "V301__project_repository_sources_repo_5_7.sql"
)


def _prov(source_id: Optional[str], repo: str, name: str, carried: Optional[str] = None) -> Dict[str, Any]:
    """A provenance column set for one entity row."""
    return {
        "provenance_id": "p",
        "source_id": source_id,
        "repository_id": repo,
        "repository_full_name": name,
        "branch": "main",
        "path": "openapi.yaml",
        "blob_sha": "b1",
        "carried_from_version_id": carried,
    }


class FakeSourcesDb:
    """Scripted answers for the queries the read issues."""

    def __init__(self) -> None:
        self.allowed = True
        self.calls: List[tuple] = []
        self.versions = {
            VERSION_1: {"id": VERSION_1, "project_id": PROJECT, "version_id": "1.0.0"},
            VERSION_2: {"id": VERSION_2, "project_id": PROJECT, "version_id": "1.1.0"},
        }
        self.latest: Optional[str] = VERSION_2
        self.entities: Dict[str, List[Dict[str, Any]]] = {
            VERSION_2: [
                {"kind": "class", "key": "Invoice", **_prov(SRC_BILLING, REPO_BILLING, "acme/billing")},
                {"kind": "class", "key": "Note", "provenance_id": None},
                {"kind": "class", "key": "User", **_prov(SRC_USERS, REPO_USERS, "acme/users", VERSION_1)},
                {"kind": "path", "key": "/invoices", **_prov(SRC_BILLING, REPO_BILLING, "acme/billing")},
                {"kind": "path", "key": "/legacy", **_prov(None, REPO_USERS, "acme/old", VERSION_1)},
            ],
            VERSION_1: [{"kind": "class", "key": "User", **_prov(SRC_USERS, REPO_USERS, "acme/users")}],
        }
        self.sources = [
            {
                "id": SRC_USERS,
                "repository_id": REPO_USERS,
                "repository_full_name": "acme/users",
                "provider": "github",
                "branch": "main",
                "path": "openapi.yaml",
                "precedence": 1,
                "first_version_id": VERSION_1,
                "last_version_id": VERSION_1,
                "last_version_label": "1.0.0",
                "last_blob_sha": "b1",
                "created_at": NOW,
                "updated_at": NOW,
            },
            {
                "id": SRC_BILLING,
                "repository_id": REPO_BILLING,
                "repository_full_name": "acme/billing",
                "provider": "github",
                "branch": "main",
                "path": "spec.yaml",
                "precedence": 2,
                "first_version_id": VERSION_2,
                "last_version_id": VERSION_2,
                "last_version_label": "1.1.0",
                "last_blob_sha": "b2",
                "created_at": NOW,
                "updated_at": NOW,
            },
        ]

    # -- RBAC / resolution ----------------------------------------------------------------------

    def user_has_permission(self, tenant_id, user_id, resource, action) -> bool:
        """Grant or deny every permission."""
        self.calls.append(("perm", resource, action))
        return self.allowed

    def get_project_by_slug(self, slug, tenant_id):
        """The one project, by slug, in the one tenant."""
        return {"id": PROJECT, "slug": "shop"} if slug == "shop" and tenant_id == TENANT else None

    def get_project_by_id(self, project_id, tenant_id):
        """The one project, by id, in the one tenant."""
        return {"id": PROJECT, "slug": "shop"} if project_id == PROJECT and tenant_id == TENANT else None

    def get_version_by_id(self, version_id, tenant_id):
        """A version by revision id."""
        return self.versions.get(version_id)

    def get_version_by_version_id(self, project_id, label, tenant_id):
        """A version by label."""
        return next((v for v in self.versions.values() if v["version_id"] == label), None)

    # -- the read's SQL -------------------------------------------------------------------------

    def execute_query(self, query: str, params: tuple = None):
        """Answer the three statements of the read by shape."""
        self.calls.append(("sql", query, params))
        if "FROM apiome.project_repository_sources prs" in query:
            assert params == (PROJECT, TENANT)
            return list(self.sources)
        if "WITH ents AS" in query:
            return list(self.entities.get(params[0], []))
        if "FROM apiome.versions" in query:
            return [{"id": self.latest}] if self.latest else []
        raise AssertionError(f"unexpected query: {query}")


@pytest.fixture
def fake(monkeypatch) -> FakeSourcesDb:
    """The scripted database beneath the route, the read and the resolvers."""
    store = FakeSourcesDb()
    for module in (comment_store, project_repository_sources, project_repository_sources_routes):
        monkeypatch.setattr(module, "db", store)
    return store


@pytest.fixture(autouse=True)
def act_as():
    """Authenticate as Alice in the tenant."""

    def _set(tenant_id: Optional[str] = TENANT) -> None:
        auth: Dict[str, Any] = {"tenant_id": tenant_id, "auth_method": "jwt", "user_id": ALICE}
        app.dependency_overrides[validate_authentication] = lambda: auth

    _set()
    yield _set
    app.dependency_overrides.pop(validate_authentication, None)


def test_lists_sources_in_precedence_order_with_latest_version_provenance(fake):
    response = client.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_id"] == PROJECT
    assert body["version"] == {"id": VERSION_2, "version_label": "1.1.0"}
    assert [(s["repository_full_name"], s["precedence"]) for s in body["sources"]] == [
        ("acme/users", 1),
        ("acme/billing", 2),
    ]
    users, billing = body["sources"]
    assert (users["class_count"], users["path_count"]) == (1, 0)
    assert (billing["class_count"], billing["path_count"]) == (1, 1)
    assert billing["last_version_label"] == "1.1.0"
    assert body["counts"] == {"classes": 3, "paths": 2, "attributed": 4, "unattributed": 1}


def test_every_class_and_path_carries_its_source(fake):
    entities = {(e["kind"], e["key"]): e["source"] for e in client.get(URL).json()["entities"]}
    assert entities[("class", "Note")] is None
    assert entities[("class", "User")]["repository_full_name"] == "acme/users"
    assert entities[("class", "User")]["carried_from_version_id"] == VERSION_1
    assert entities[("path", "/invoices")]["carried_from_version_id"] is None
    # A removed source keeps its snapshot; it just no longer links to a source row.
    assert entities[("path", "/legacy")]["source_id"] is None
    assert entities[("path", "/legacy")]["repository_full_name"] == "acme/old"


def test_version_query_selects_a_version_by_label_or_id(fake):
    by_label = client.get(URL, params={"version": "1.0.0"}).json()
    assert by_label["version"]["id"] == VERSION_1
    assert [e["key"] for e in by_label["entities"]] == ["User"]
    by_id = client.get(URL, params={"version": VERSION_1}).json()
    assert by_id["version"]["version_label"] == "1.0.0"


def test_project_without_versions_reports_sources_only(fake):
    fake.latest = None
    body = client.get(URL).json()
    assert body["version"] is None
    assert body["entities"] == []
    assert body["counts"] == {"classes": 0, "paths": 0, "attributed": 0, "unattributed": 0}
    assert all(s["class_count"] == 0 for s in body["sources"])


def test_unknown_project_or_version_is_404(fake):
    assert client.get("/v1/tenants/acme/projects/nope/repository-sources").status_code == 404
    assert client.get(URL, params={"version": "9.9.9"}).status_code == 404


def test_another_tenant_cannot_read_the_project(fake, act_as):
    act_as(OTHER_TENANT)
    assert client.get(URL).status_code == 404


def test_requires_projects_view(fake):
    fake.allowed = False
    assert client.get(URL).status_code == 403
    assert ("perm", "projects", "view") in [c[:3] for c in fake.calls if c[0] == "perm"]


def test_openapi_documents_the_route():
    spec = app.openapi()
    operation = spec["paths"]["/v1/tenants/{tenant_slug}/projects/{project_ref}/repository-sources"]["get"]
    assert operation["tags"] == ["project-repository-sources"]
    assert "projects:view" in operation["description"]
    assert {p["name"] for p in operation["parameters"]} >= {"tenant_slug", "project_ref", "version"}


def test_migration_shape():
    sql = MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS apiome.project_repository_sources" in sql
    assert (
        "CONSTRAINT project_repository_sources_lineage_unique "
        "UNIQUE (project_id, repository_id, branch, path)"
    ) in sql
    assert "CREATE TABLE IF NOT EXISTS apiome.version_entity_sources" in sql
    assert "CHECK (entity_kind IN ('class', 'path'))" in sql
    assert "CONSTRAINT version_entity_sources_entity_unique UNIQUE (version_id, entity_kind, entity_key)" in sql
    # Removing a source keeps the provenance snapshot readable.
    assert "source_id UUID REFERENCES apiome.project_repository_sources(id) ON DELETE SET NULL" in sql
    assert "-- Rollback:" in sql
