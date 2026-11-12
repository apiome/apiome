"""Component usage report — DCW-3.3 (private-suite#2361) for DCW-EPIC-3 (#2349).

The server form of the dependency rule the Designer mirrors (``library-impact.ts``): canonical
reference collection, published-head selection, transitive dependents with shortest depth and
cycle safety, and the ``GET …/components/{id}/usage`` route (tenant scoping, 404 on a scope miss,
pins of the component and its dependents).
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.component_usage import (
    build_dependency_graph,
    collect_component_refs,
    head_payloads,
    transitive_dependents,
)
from app.main import app

client = TestClient(app)

HEADER = {"id": "h", "name": "X-Rate-Limit", "kind": "header"}
RESPONSE = {"id": "r", "name": "TooManyRequests", "kind": "response"}
BUNDLE = {"id": "b", "name": "Errors", "kind": "requestBody"}
LOOP_A = {"id": "a", "name": "LoopA", "kind": "parameter"}
LOOP_B = {"id": "z", "name": "LoopB", "kind": "parameter"}
COMPONENTS = [HEADER, RESPONSE, BUNDLE, LOOP_A, LOOP_B]

PAYLOADS = {
    "h": {"schema": {"type": "integer"}},
    "r": {"description": "Slow down", "headers": {"X-Rate-Limit": {"$ref": "#/components/headers/X-Rate-Limit"}}},
    "b": {"content": {"application/json": {"schema": {"$ref": "#/components/responses/TooManyRequests/content"}}}},
    "a": {"name": "a", "in": "query", "x": {"$ref": "#/components/parameters/LoopB"}},
    "z": {"name": "z", "in": "query", "x": {"$ref": "#/components/parameters/LoopA"}},
}


class TestReferences:
    def test_collects_canonical_refs_and_folds_deeper_pointers(self):
        refs = collect_component_refs(
            {
                "a": {"$ref": "#/components/responses/X/headers/Y"},
                "b": [{"$ref": "#/components/schemas/Pet~1Cat"}, {"$ref": "other.yaml#/x"}],
                "c": {"$ref": "#/components/schemas/Tilde~0"},
            }
        )
        assert refs == {"responses/X", "schemas/Pet/Cat", "schemas/Tilde~"}

    def test_survives_shared_and_scalar_nodes(self):
        shared = {"$ref": "#/components/headers/H"}
        assert collect_component_refs([shared, shared, 3, None, "x"]) == {"headers/H"}

    def test_head_is_the_highest_semver_not_the_last_text(self):
        heads = head_payloads(
            [
                {"component_id": "c", "revision": "1.10.0", "canonical_payload": "ten"},
                {"component_id": "c", "revision": "1.9.0", "canonical_payload": "nine"},
                {"component_id": "c", "revision": "bogus", "canonical_payload": "junk"},
            ]
        )
        assert heads == {"c": "ten"}

    def test_graph_ignores_self_and_unknown_refs(self):
        graph = build_dependency_graph(
            [HEADER, {"id": "s", "name": "Self", "kind": "header"}],
            {"s": {"$ref": "#/components/headers/Self", "x": {"$ref": "#/components/headers/Nope"}}},
        )
        assert graph == {"h": set(), "s": set()}


class TestTransitiveDependents:
    def test_direct_and_transitive_with_depth(self):
        assert transitive_dependents(COMPONENTS, PAYLOADS, "h") == [
            {"componentId": "r", "name": "TooManyRequests", "kind": "response", "depth": 1},
            {"componentId": "b", "name": "Errors", "kind": "requestBody", "depth": 2},
        ]

    def test_cycles_terminate_and_exclude_the_target(self):
        assert transitive_dependents(COMPONENTS, PAYLOADS, "a") == [
            {"componentId": "z", "name": "LoopB", "kind": "parameter", "depth": 1}
        ]

    def test_unpublished_components_reference_nothing(self):
        assert transitive_dependents(COMPONENTS, {"h": PAYLOADS["h"]}, "h") == []


_MOCK_JWT = {"tenant_id": "t1", "user_id": "user-a", "auth_method": "jwt"}


@pytest.fixture(autouse=True)
def _auth():
    app.dependency_overrides[validate_authentication] = lambda: dict(_MOCK_JWT)
    yield
    app.dependency_overrides.pop(validate_authentication, None)


class TestUsageRoute:
    def test_reports_dependents_and_their_pins(self):
        with patch("app.component_library_routes.db") as mdb:
            mdb.get_operational_component.return_value = HEADER
            mdb.get_component_graph_rows.return_value = (
                COMPONENTS,
                [
                    {"component_id": cid, "revision": "1.0.0", "canonical_payload": payload}
                    for cid, payload in PAYLOADS.items()
                ],
            )
            mdb.get_component_usage_pins.return_value = [
                {
                    "id": "pin-1",
                    "local_name": None,
                    "revision_id": "rev-r",
                    "revision": "1.0.0",
                    "payload_digest": "sha256:x",
                    "component_id": "r",
                    "component_name": "TooManyRequests",
                    "kind": "response",
                    "version_id": "v1",
                    "project_id": "p1",
                }
            ]
            r = client.get("/v1/component-library/tn/components/h/usage")
        assert r.status_code == 200
        body = r.json()
        assert body["componentId"] == "h"
        assert [d["componentId"] for d in body["dependents"]] == ["r", "b"]
        assert body["pins"] == [
            {
                "id": "pin-1",
                "componentId": "r",
                "componentName": "TooManyRequests",
                "kind": "response",
                "revisionId": "rev-r",
                "revision": "1.0.0",
                "payloadDigest": "sha256:x",
                "localName": None,
                "projectId": "p1",
                "versionId": "v1",
            }
        ]
        mdb.get_component_graph_rows.assert_called_once_with("t1")
        assert mdb.get_component_usage_pins.call_args.args == ("t1", ["h", "r", "b"])

    def test_other_tenant_component_is_404(self):
        with patch("app.component_library_routes.db") as mdb:
            mdb.get_operational_component.return_value = None
            r = client.get("/v1/component-library/tn/components/h/usage")
        assert r.status_code == 404
        mdb.get_component_graph_rows.assert_not_called()


class TestUsageQueries:
    def test_reads_are_tenant_scoped(self, monkeypatch):
        from app.database import db

        captured = []
        monkeypatch.setattr(
            db, "execute_query", lambda sql, params=None: captured.append((sql, params)) or []
        )
        db.get_component_graph_rows("t1")
        db.get_component_usage_pins("t1", ["h"])
        assert db.get_component_usage_pins("t1", []) == []
        assert len(captured) == 3
        for sql, params in captured:
            assert "tenant_id = %s" in sql
            assert params[0] == "t1"
        assert "r.state = 'published'" in captured[1][0]
