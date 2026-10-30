"""Import a new version: compare the incoming spec with the project's latest version — IXH-3.7 (#6321).

Pins:

* the pure builder — counts, ranking (breaking first), per-change grading from the compatibility
  findings, scalar/container previews, labels, the surface filter, truncation, no-change state;
* classification parity with Versions → Compare (``CompatibilityCheckEngine`` on the same pair);
* target resolution — slug normalization, explicit id wins, catalog items / unknown slugs /
  empty projects are not a new version;
* the route — 200 with both documents, 204 when skipped, 500 (retryable) on a rebuild failure,
  and that nothing is written.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

import pytest
from fastapi.testclient import TestClient

from app import import_project_delta as delta_module
from app.auth import validate_authentication
from app.compatibility_engine import CompatibilityCheckEngine
from app.import_project_delta import (
    MAX_DELTA_CHANGES,
    ProjectDeltaRequest,
    build_project_delta,
    change_label,
    resolve_project_delta_target,
    run_project_delta,
)
from app.main import app

client = TestClient(app)

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TENANT_SLUG = "acme"
USER_ID = "660e8400-e29b-41d4-a716-446655440001"
PROJECT_ID = "770e8400-e29b-41d4-a716-446655440002"
REVISION_ID = "880e8400-e29b-41d4-a716-446655440003"

ROUTE = f"/v1/tenants/{TENANT_SLUG}/import/project-delta"

_MOCK_AUTH = {
    "tenant_id": TENANT_ID,
    "tenant_slug": TENANT_SLUG,
    "user_id": USER_ID,
    "auth_method": "jwt",
}


def _ok(description: str = "ok") -> Dict[str, Any]:
    return {"responses": {"200": {"description": description}}}


#: The latest version: GET + DELETE /refunds/{id}, Refund.amount minimum 0.
BASE: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Payments API", "version": "2.4.0", "description": "No description provided"},
    "paths": {"/refunds/{id}": {"get": _ok(), "delete": _ok()}},
    "components": {
        "schemas": {
            "Refund": {
                "type": "object",
                "properties": {"amount": {"type": "number", "minimum": 0}},
                "required": ["amount"],
            }
        }
    },
}

#: The incoming spec: DELETE removed (breaking), POST /payouts added (safe), minimum raised
#: (breaking), optional Refund.note added (safe), and an info change (outside the surface).
INCOMING: Dict[str, Any] = {
    "openapi": "3.1.0",
    "info": {"title": "Payments API", "version": "2.5.0", "description": "Hand-written"},
    "paths": {"/refunds/{id}": {"get": _ok()}, "/payouts": {"post": _ok()}},
    "components": {
        "schemas": {
            "Refund": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "minimum": 0.01},
                    "note": {"type": "string"},
                },
                "required": ["amount"],
            }
        }
    },
}


# ---------------------------------------------------------------------------
# Pure builder
# ---------------------------------------------------------------------------


def test_counts_and_overall_match_the_compatibility_engine():
    delta = build_project_delta(BASE, INCOMING)
    engine = CompatibilityCheckEngine.run(BASE, INCOMING)

    assert delta["overall"] == engine.overall == "breaking"
    assert [f.model_dump() for f in delta["findings"]] == engine.finding_dicts
    counts = delta["counts"]
    assert counts.breaking == sum(1 for f in engine.findings if f.category == "breaking") == 2
    assert (counts.added, counts.changed, counts.removed) == (2, 1, 1)
    assert counts.total == 4
    assert delta["truncated"] is False


def test_changes_are_ranked_breaking_first_and_graded_by_covering_findings():
    rows = build_project_delta(BASE, INCOMING)["changes"]
    by_pointer = {r.pointer: r for r in rows}

    removed = by_pointer["/paths/~1refunds~1{id}/delete"]
    assert (removed.kind, removed.severity, removed.label) == ("removed", "breaking", "DELETE /refunds/{id}")
    assert removed.rules == ["operation_removed"]

    minimum = by_pointer["/components/schemas/Refund/properties/amount/minimum"]
    assert (minimum.kind, minimum.severity) == ("changed", "breaking")
    assert minimum.label == "schema Refund.amount minimum"
    assert (minimum.before, minimum.after) == (0, 0.01)

    payouts = by_pointer["/paths/~1payouts"]
    assert (payouts.kind, payouts.severity, payouts.scope) == ("added", "safe", "path")
    # A whole added subtree is previewed, never inlined into the row.
    assert payouts.after == "{1 key}"
    assert payouts.before is None

    # Breaking rows first; within breaking, removals before changes.
    assert [r.severity for r in rows[:2]] == ["breaking", "breaking"]
    assert rows[0].kind == "removed"
    assert all(r.severity in ("safe", None) for r in rows[2:])


def test_changes_outside_the_api_surface_are_not_listed():
    rows = build_project_delta(BASE, INCOMING)["changes"]
    assert not any(r.pointer.startswith("/info") for r in rows)


def test_identical_documents_have_no_changes():
    delta = build_project_delta(BASE, copy.deepcopy(BASE))
    assert delta["changes"] == []
    assert delta["counts"].total == 0
    assert delta["overall"] == "safe"


def test_an_ungraded_change_is_not_called_safe():
    incoming = copy.deepcopy(BASE)
    incoming["paths"]["/refunds/{id}"]["get"]["summary"] = "Fetch a refund"
    rows = build_project_delta(BASE, incoming)["changes"]
    assert len(rows) == 1
    assert rows[0].severity is None
    assert rows[0].rules == []


def test_inputs_are_never_mutated():
    base, incoming = copy.deepcopy(BASE), copy.deepcopy(INCOMING)
    build_project_delta(base, incoming)
    assert base == BASE and incoming == INCOMING


def test_truncation_is_stated_and_counts_cover_every_change():
    incoming = copy.deepcopy(BASE)
    incoming["paths"].update({f"/p{i}": {"get": _ok()} for i in range(12)})
    delta = build_project_delta(BASE, incoming, max_changes=5)
    assert len(delta["changes"]) == 5
    assert delta["truncated"] is True
    assert delta["counts"].total == delta["counts"].added == 12


@pytest.mark.parametrize(
    "pointer, label",
    [
        ("/paths/~1refunds~1{id}/delete", "DELETE /refunds/{id}"),
        ("/paths/~1a/get/responses/200/description", "GET /a responses 200 description"),
        ("/paths/~1a/parameters", "path /a parameters"),
        ("/components/schemas/Refund", "schema Refund"),
        ("/components/schemas/A/properties/b/properties/c/type", "schema A.b.c type"),
        ("/components/securitySchemes/key/in", "component securitySchemes/key in"),
        ("/components", "components"),
    ],
)
def test_change_labels(pointer: str, label: str):
    assert change_label(pointer) == label


def test_the_list_is_capped_by_default():
    assert MAX_DELTA_CHANGES == 5000


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


class _FakeDb:
    """Just the reads the delta makes; any write would be an AttributeError."""

    def __init__(
        self,
        *,
        project: Optional[Dict[str, Any]] = None,
        latest: Optional[str] = REVISION_ID,
    ) -> None:
        self.project = project
        self.latest = latest
        self.slug_lookups: List[str] = []
        self.id_lookups: List[str] = []

    def get_project_by_slug(self, slug: str, tenant_id: str):
        assert tenant_id == TENANT_ID
        self.slug_lookups.append(slug)
        return self.project if self.project and self.project["slug"] == slug else None

    def get_project_by_id(self, project_id: str, tenant_id: str):
        assert tenant_id == TENANT_ID
        self.id_lookups.append(project_id)
        return self.project if self.project and self.project["id"] == project_id else None

    def get_latest_revision_id_for_project(self, project_id: str, tenant_id: str):
        return self.latest

    def list_version_labels_for_project(self, project_id: str, tenant_id: str):
        assert tenant_id == TENANT_ID
        return ["2.3.0", "2.4.0"] if project_id == PROJECT_ID else []

    def get_version_by_id(self, version_id: str, tenant_id: str):
        if version_id != REVISION_ID:
            return None
        return {"id": REVISION_ID, "project_id": PROJECT_ID, "version_id": "2.4.0"}


def _project(**overrides: Any) -> Dict[str, Any]:
    row = {"id": PROJECT_ID, "slug": "payments-api", "name": "Payments API", "publishable": True}
    row.update(overrides)
    return row


def test_slug_is_trimmed_and_lower_cased_like_the_commit():
    db = _FakeDb(project=_project())
    target = resolve_project_delta_target(db, TENANT_ID, project_slug="  Payments-API ", project_id=None)
    assert target is not None
    assert db.slug_lookups == ["payments-api"]
    assert target["version"]["id"] == REVISION_ID


def test_explicit_project_id_wins_over_the_slug():
    db = _FakeDb(project=_project())
    target = resolve_project_delta_target(db, TENANT_ID, project_slug="other", project_id=PROJECT_ID)
    assert target is not None
    assert db.id_lookups == [PROJECT_ID] and db.slug_lookups == []


@pytest.mark.parametrize(
    "db, slug",
    [
        (_FakeDb(project=None), "payments-api"),  # first-time import
        (_FakeDb(project=_project(publishable=False)), "payments-api"),  # catalog item
        (_FakeDb(project=_project(), latest=None), "payments-api"),  # no revision yet
        (_FakeDb(project=_project()), "   "),  # nothing to match
    ],
)
def test_not_a_new_version_resolves_to_none(db: _FakeDb, slug: str):
    assert resolve_project_delta_target(db, TENANT_ID, project_slug=slug, project_id=None) is None


def test_run_rebuilds_the_latest_revision_and_omits_documents_on_request(monkeypatch):
    calls: List[Dict[str, Any]] = []

    def _rebuild(version: Dict[str, Any], tenant_slug: str, tenant_id: str):
        calls.append(version)
        return copy.deepcopy(BASE)

    monkeypatch.setattr(delta_module, "openapi_for_revision", _rebuild)
    db = _FakeDb(project=_project())
    response = run_project_delta(
        db,
        ProjectDeltaRequest(document=INCOMING, project_slug="payments-api", include_documents=False),
        tenant_id=TENANT_ID,
        tenant_slug=TENANT_SLUG,
    )
    assert response is not None
    assert calls[0]["id"] == REVISION_ID
    assert response.base_version_label == "2.4.0"
    assert response.project_name == "Payments API"
    # #590: the wizard checks the import's version against every live label of the project.
    assert response.existing_version_labels == ["2.3.0", "2.4.0"]
    assert response.base_document is None and response.incoming_document is None


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _auth_override():
    def _fake_auth(tenant_slug: str):
        return {**_MOCK_AUTH, "tenant_slug": tenant_slug}

    app.dependency_overrides[validate_authentication] = _fake_auth
    yield
    app.dependency_overrides.pop(validate_authentication, None)


@pytest.fixture
def fake_db(monkeypatch):
    """Point the route's database at a fake and its rebuild at ``BASE``."""
    from app import spec_import_routes

    db = _FakeDb(project=_project())
    monkeypatch.setattr(spec_import_routes, "db", db)
    monkeypatch.setattr(spec_import_routes, "enforce_permission", lambda *a, **k: None)
    monkeypatch.setattr(delta_module, "openapi_for_revision", lambda *a, **k: copy.deepcopy(BASE))
    return db


def test_route_returns_the_delta_with_both_documents(fake_db):
    res = client.post(ROUTE, json={"document": INCOMING, "project_slug": "payments-api"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["project_id"] == PROJECT_ID
    assert body["base_revision_id"] == REVISION_ID
    assert body["base_version_label"] == "2.4.0"
    assert body["existing_version_labels"] == ["2.3.0", "2.4.0"]
    assert body["overall"] == "breaking"
    assert body["counts"] == {"added": 2, "changed": 1, "removed": 1, "breaking": 2, "total": 4}
    assert body["changes"][0]["severity"] == "breaking"
    assert body["base_document"] == BASE
    assert body["incoming_document"] == INCOMING


def test_route_answers_204_for_a_first_time_import(fake_db):
    res = client.post(ROUTE, json={"document": INCOMING, "project_slug": "brand-new"})
    assert res.status_code == 204
    assert res.content == b""


def test_route_answers_204_for_a_catalog_item(fake_db):
    fake_db.project = _project(publishable=False)
    res = client.post(ROUTE, json={"document": INCOMING, "project_slug": "payments-api"})
    assert res.status_code == 204


def test_route_reports_a_rebuild_failure_as_a_retryable_500(fake_db, monkeypatch):
    def _boom(*args: Any, **kwargs: Any):
        raise RuntimeError("generator exploded")

    monkeypatch.setattr(delta_module, "openapi_for_revision", _boom)
    res = client.post(ROUTE, json={"document": INCOMING, "project_slug": "payments-api"})
    assert res.status_code == 500
    assert "could not be compared" in res.json()["detail"]


def test_route_rejects_a_request_without_a_document(fake_db):
    res = client.post(ROUTE, json={"project_slug": "payments-api"})
    assert res.status_code == 422
