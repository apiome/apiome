"""Accepted enrichment as an Overlay — GVM-4.3 (#5878).

* only accepted rows with text become actions, in ``target_key`` order;
* tool rows update the operation, parameter rows update the parameter by ``name`` and ``in``;
* the document applies to the source and its targets survive a quote in a path;
* non-HTTP operations are skipped and listed, never dropped silently;
* ``GET …/enrichment/overlay`` serves the projection with the toolset's coordinates, reads V273
  only (``status="accepted"``) and needs ``api_keys:view``.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.enrichment_overlay import enrichment_overlay_document
from app.export_overlay import ExportOverlay
from app.main import app
from app.openapi_overlay import apply_overlays

TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
TOOLSET = "66666666-6666-6666-6666-666666666666"

_DOC = {
    "openapi": "3.1.0",
    "info": {"title": "Pets", "version": "1"},
    "paths": {
        "/pets/{id}": {
            "get": {
                "responses": {"200": {"description": "OK"}},
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}},
                    {"name": "id", "in": "query", "schema": {"type": "string"}},
                ],
            }
        },
        "/o'clock": {"get": {"responses": {"200": {"description": "OK"}}}},
    },
}


def _row(target_key, *, operation, kind="tool", parameter=None, status="accepted", text="Better."):
    return {
        "operation_key": operation,
        "target_kind": kind,
        "target_key": target_key,
        "parameter_name": parameter,
        "status": status,
        "accepted_description": text if status == "accepted" else None,
    }


_ROWS = [
    _row("GET /pets/{id}", operation="GET /pets/{id}", text="Fetch one pet."),
    _row(
        "GET /pets/{id}#path.id", operation="GET /pets/{id}", kind="parameter", parameter="path.id", text="The pet id."
    ),
    _row("GET /o'clock", operation="GET /o'clock", text="Time."),
    _row(
        "GET /pets/{id}#query.id", operation="GET /pets/{id}", kind="parameter", parameter="query.id", status="proposed"
    ),
    _row("Query.user", operation="Query.user", text="A user."),
]


def test_accepted_rows_project_into_an_applicable_overlay():
    projection = enrichment_overlay_document(_ROWS, title="Accepted agent enrichment (1.0.0)")
    document = projection.document
    assert document["overlay"] == "1.0.0"
    assert document["info"]["title"] == "Accepted agent enrichment (1.0.0)"
    assert projection.action_count == 3
    assert projection.skipped == ["Query.user"]
    ExportOverlay(name="enrichment", document=document)  # a valid stored overlay

    applied = apply_overlays(_DOC, [("enrichment", document)])
    assert applied.findings == []
    get = applied.document["paths"]["/pets/{id}"]["get"]
    assert get["description"] == "Fetch one pet."
    assert get["parameters"][0]["description"] == "The pet id."
    assert "description" not in get["parameters"][1]  # the proposed (unaccepted) row is not served
    assert applied.document["paths"]["/o'clock"]["get"]["description"] == "Time."


def test_the_projection_is_deterministic():
    one = enrichment_overlay_document(_ROWS, title="t").document
    two = enrichment_overlay_document(list(reversed(_ROWS)), title="t").document
    assert one == two


def test_no_accepted_rows_is_an_empty_overlay():
    projection = enrichment_overlay_document([_ROWS[3]], title="t")
    assert projection.action_count == 0
    assert projection.skipped == []


def test_the_route_serves_the_projection(monkeypatch):
    reads = []

    def _list(tenant_id, toolset_id, *, status=None):
        reads.append(status)
        return [r for r in _ROWS if status is None or r["status"] == status]

    monkeypatch.setattr(
        "app.agent_toolset_enrichment.db.get_agent_toolset",
        lambda tenant_id, toolset_id: {
            "id": toolset_id,
            "project_id": "p-1",
            "version_id": "v-1",
            "version_label": "1.0.0",
        },
    )
    monkeypatch.setattr("app.agent_toolset_enrichment.db.list_agent_toolset_enrichments", _list)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT_ID,
        "user_id": "u",
        "auth_method": "jwt",
    }
    try:
        response = TestClient(app).get(f"/v1/tenants/acme/agent-toolsets/{TOOLSET}/enrichment/overlay")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["project_id"] == "p-1"
    assert body["version_label"] == "1.0.0"
    assert body["action_count"] == 3
    assert body["skipped"] == ["Query.user"]
    assert body["document"]["info"]["title"] == "Accepted agent enrichment (1.0.0)"
    assert reads == ["accepted"]


def test_the_route_is_404_for_an_unknown_toolset(monkeypatch):
    monkeypatch.setattr("app.agent_toolset_enrichment.db.get_agent_toolset", lambda *a: None)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": TENANT_ID,
        "user_id": "u",
        "auth_method": "jwt",
    }
    try:
        response = TestClient(app).get(f"/v1/tenants/acme/agent-toolsets/{TOOLSET}/enrichment/overlay")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
