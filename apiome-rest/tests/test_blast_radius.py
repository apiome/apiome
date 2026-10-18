"""The blast-radius query without a database — CDG-3.3 (#5968).

* Pointer helpers: operation keys from ``/paths`` pointers, template shapes, shaped pointers.
* Pointers → operations, including schema pointers reached through ``$ref`` chains, shared path
  parameters, document-wide changes and a missing document.
* Evidence matchers: operation shape matching, fixture-pack path prefixes, scenarios.
* Request validation and the route (permission, bounds, error codes).

The golden fixture, CTG-4.2 parity and the latency budget are in ``test_blast_radius_db.py``.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from app import blast_radius as br
from app import graph_routes as routes
from app.auth import validate_authentication
from app.blast_radius import (
    BlastRadiusRequest,
    affected_operations,
    operation_key_from_pointer,
    shape_pointer,
    template_shape,
)
from app.declared_dependencies import DependencyValidationError
from app.main import app

_TENANT = "11111111-1111-4111-8111-111111111111"
_USER = "33333333-3333-4333-8333-333333333333"


@pytest.mark.parametrize(
    "pointer,key",
    [
        ("/paths/~1pets~1{id}/get", ("GET", "/pets/{id}")),
        ("/paths/~1pets~1{id}/get/responses/200/content", ("GET", "/pets/{id}")),
        ("/paths/~1pets~1{id}", (None, "/pets/{id}")),
        ("/paths/~1pets~1{id}/parameters/0", (None, "/pets/{id}")),
        ("/components/schemas/Pet", None),
        ("/paths", None),
    ],
)
def test_operation_key_from_pointer(pointer, key) -> None:
    assert operation_key_from_pointer(pointer) == key


def test_template_shapes() -> None:
    assert template_shape("/pets/{petId}/toys/{toy_id}") == "/pets/{}/toys/{}"
    assert shape_pointer("/paths/~1pets~1{petId}/get/responses") == "/paths/~1pets~1{}/get/responses"
    assert shape_pointer("/components/schemas/Pet") == "/components/schemas/Pet"


_DOC: Dict[str, Any] = {
    "openapi": "3.1.0",
    "paths": {
        "/pets/{petId}": {
            "parameters": [{"$ref": "#/components/parameters/PetId"}],
            "get": {"responses": {"200": {"content": {"application/json": {
                "schema": {"$ref": "#/components/schemas/Pet"}}}}}},
            "delete": {"responses": {"204": {"description": "gone"}}},
        },
        "/owners": {"get": {"responses": {"200": {"content": {"application/json": {
            "schema": {"type": "array", "items": {"$ref": "#/components/schemas/Owner"}}}}}}}},
        "/toys": {"post": {"requestBody": {"content": {"application/json": {
            "schema": {"$ref": "#/components/schemas/Toy"}}}}}},
    },
    "components": {
        "parameters": {"PetId": {"name": "petId", "in": "path", "schema": {"type": "string"}}},
        "schemas": {
            "Pet": {"properties": {"owner": {"$ref": "#/components/schemas/Owner"}}},
            "Owner": {"properties": {"name": {"type": "string"}}},
            "Toy": {"properties": {"name": {"type": "string"}}},
            "PetFood": {"type": "object"},
        },
    },
}


def test_no_pointers_or_a_document_wide_change_reaches_every_operation() -> None:
    assert affected_operations([], _DOC) == (None, [])
    assert affected_operations(["/security/0"], _DOC) == (None, [])
    assert affected_operations(["/paths/~1pets/get", "/servers"], None) == (None, [])


def test_operation_pointers_need_no_document() -> None:
    ops, warnings = affected_operations(["/paths/~1pets~1{id}/get/responses", "/paths/~1toys"], None)
    assert ops == [("GET", "/pets/{id}"), (None, "/toys")] and warnings == []


def test_a_schema_reaches_operations_through_ref_chains() -> None:
    ops, _ = affected_operations(["/components/schemas/Owner/properties/name"], _DOC)
    assert ops == [("GET", "/owners"), ("GET", "/pets/{petId}")]  # Pet → Owner
    ops, _ = affected_operations(["/components/schemas/Pet"], _DOC)
    assert ops == [("GET", "/pets/{petId}")]
    assert affected_operations(["/components/schemas/PetFood"], _DOC)[0] == []  # not a prefix match


def test_a_shared_path_parameter_reaches_every_method_of_the_path() -> None:
    ops, _ = affected_operations(["/components/parameters/PetId"], _DOC)
    assert ops == [("DELETE", "/pets/{petId}"), ("GET", "/pets/{petId}")]


def test_a_missing_document_is_a_warning_not_a_guess() -> None:
    ops, warnings = affected_operations(["/components/schemas/Pet"], None)
    assert ops == [] and "unavailable" in warnings[0]


def test_operations_match_by_method_and_template_shape() -> None:
    ops = [("GET", "/pets/{id}"), (None, "/toys")]
    assert br._matches(ops, "get", "/pets/{petId}")
    assert not br._matches(ops, "DELETE", "/pets/{petId}")
    assert br._matches(ops, "POST", "/toys") and br._matches(None, "PUT", "/anything")
    assert not br._matches(ops, "GET", "/pets")


def test_fixture_packs_match_by_path_prefix_and_scenarios_by_operation() -> None:
    settings = {
        "fixturePacks": {"pets": {"collections": {"/pets": []}}, "petsitters": {"collections": {"/petsitters": []}},
                         "broken": "not a pack"},
        "scenarios": {"slow": {"operations": {"GET /pets/{petId}": {}}}, "all": {"operations": {"*": {}}},
                      "other": {"operations": {"POST /orders": {}}}},
    }
    found = br._mock_evidence(settings, [("GET", "/pets/{id}")])
    assert [(f["kind"], f["name"]) for f in found] == [("fixture_pack", "pets"), ("scenario", "all"),
                                                      ("scenario", "slow")]
    assert br._mock_evidence(None, None) == []


def test_overlap_is_segment_wise_and_shape_aware() -> None:
    declared = ["/paths/~1pets~1{petId}/get", "/components/schemas/Pet/properties/id"]
    assert br._overlaps_any(declared, ["/paths/~1pets~1{id}/get/responses"]) == ["/paths/~1pets~1{id}/get/responses"]
    assert br._overlaps_any(declared, ["/components/schemas/PetFood"]) == []
    assert br._overlaps_any([], ["/security"]) == ["/security"]


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"depth": 0}, "depth"),
        ({"depth": 6}, "depth"),
        ({"provenances": ("rumoured",)}, "provenance"),
        ({"provenances": ()}, "provenance"),
        ({"pointers": ("paths/x",)}, "start with"),
    ],
)
def test_malformed_requests_are_graph_invalid(kwargs, message) -> None:
    with pytest.raises(DependencyValidationError, match=message) as raised:
        br.blast_radius(None, _TENANT, BlastRadiusRequest(kind="project", entity="petstore", **kwargs))
    assert raised.value.code == "graph-invalid"


# ---------------------------------------------------------------------------------------------
# the route
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch):
    asked: List[str] = []

    def _has(tenant_id, user_id, resource, action):
        asked.append(f"{resource}:{action}")
        return True

    monkeypatch.setattr(routes.db, "user_has_permission", _has)
    app.dependency_overrides[validate_authentication] = lambda: {
        "tenant_id": _TENANT, "user_id": _USER, "auth_method": "jwt",
    }
    yield TestClient(app), asked
    app.dependency_overrides.clear()


_URL = "/v1/graph/acme/blast-radius"


def _answer() -> Dict[str, Any]:
    entity = {"kind": "consumer", "id": "c1", "name": "Web", "slug": "web", "depth": 1, "edge_kind": "consumes",
              "provenance": "derived", "pointers": ["/paths/~1pets/get"], "path": [], "owner": None}
    return {
        "entity": {"kind": "project", "id": "p1", "name": "Petstore", "slug": "petstore", "owner": None},
        "version": {"id": "v1", "label": "1.0.0", "published": True}, "pointers": ["/paths/~1pets/get"],
        "operations": ["GET /pets"], "depth": 3, "provenance": ["declared", "derived", "runtime"],
        "direct": [entity], "transitive": [], "invalidated_evidence": br._empty_evidence(),
        "evidence_checked": True, "truncated": False, "node_count": 1, "warnings": [],
    }


def test_the_route_passes_the_question_through(client, monkeypatch) -> None:
    http, asked = client
    seen: Dict[str, Any] = {}

    def _ask(db, tenant, request):
        seen.update(tenant=tenant, request=request)
        return _answer()

    monkeypatch.setattr(routes, "blast_radius", _ask)
    body = {"entity": {"kind": "project", "id": "petstore"}, "pointers": ["/paths/~1pets/get"], "depth": 2,
            "provenance": ["declared"], "version": "1.0.0"}
    response = http.post(_URL, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["direct"][0]["slug"] == "web"
    assert seen["tenant"] == _TENANT
    assert seen["request"] == BlastRadiusRequest("project", "petstore", ("/paths/~1pets/get",), 2, ("declared",),
                                                 "1.0.0")
    assert asked == ["projects:view"]


def test_the_route_bounds_and_errors(client, monkeypatch) -> None:
    http, _ = client
    assert http.post(_URL, json={"entity": {"kind": "project", "id": "p"}, "depth": 6}).status_code == 422
    assert http.post(_URL, json={"entity": {"kind": "project", "id": "p"},
                                 "pointers": ["/a"] * 201}).status_code == 422

    def _missing(*a, **k):
        raise DependencyValidationError("graph-entity-not-found", "no project 'p' in this tenant")

    monkeypatch.setattr(routes, "blast_radius", _missing)
    response = http.post(_URL, json={"entity": {"kind": "project", "id": "p"}})
    assert response.status_code == 404 and response.json()["detail"]["code"] == "graph-entity-not-found"


def test_the_route_needs_projects_view(client, monkeypatch) -> None:
    http, _ = client
    monkeypatch.setattr(routes.db, "user_has_permission", lambda *a: False)
    assert http.post(_URL, json={"entity": {"kind": "project", "id": "p"}}).status_code == 403
