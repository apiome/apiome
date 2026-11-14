"""GraphQL mock settings and root-field scenario keys on the scenarios route (#5729, XPC-1.1)."""

from __future__ import annotations

from typing import Any, Dict, Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from graphql import build_schema

from app.auth import validate_authentication
from app.graphql_normalizer import GraphQlNormalizer
from app.main import app
from app.mock_bundle import BUNDLED_SETTINGS_KEYS
from app.mock_scenario_settings import (
    graphql_settings_from_storage,
    graphql_settings_to_storage,
    is_graphql_coordinate,
    normalize_operation_key,
    uses_graphql_coordinates,
    validate_mock_chaos,
    validate_mock_scenarios,
)
from app.models import MockChaosSpec, MockGraphQlSettingsSpec, MockScenarioSpec

TENANT = "acme-corp"
PROJECT_ID = "proj-1"
VERSION_ID = "ver-1"
USER_ID = "user-1"
_AUTH = {"tenant_id": "t1", "user_id": USER_ID, "auth_method": "api_key"}
ROUTE = f"/v1/versions/{TENANT}/{PROJECT_ID}/{VERSION_ID}/mock/scenarios"
EMPTY_SPEC: Dict[str, Any] = {"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}}
GRAPHQL_API = GraphQlNormalizer().normalize(
    build_schema("type User { id: ID! } type Query { user(id: ID!): User } type Mutation { touch: Boolean }")
)


@pytest.fixture
def client() -> Iterator[TestClient]:
    app.dependency_overrides[validate_authentication] = lambda: _AUTH
    yield TestClient(app)
    app.dependency_overrides.clear()


def _version_row(mock_settings: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "id": VERSION_ID,
        "project_id": PROJECT_ID,
        "creator_id": USER_ID,
        "version_id": "1.0.0",
        "published": True,
        "mock_enabled": True,
        "mock_settings": mock_settings or {},
        "project_slug": "people",
        "metadata": None,
    }


def _scenario(operations: Dict[str, Any]) -> Dict[str, MockScenarioSpec]:
    return {"vip": MockScenarioSpec.model_validate({"operations": operations})}


# --------------------------------------------------------------------------------------------------
# Key shape and validation
# --------------------------------------------------------------------------------------------------


def test_graphql_coordinates_are_accepted_operation_keys() -> None:
    assert is_graphql_coordinate("Query.user")
    assert not is_graphql_coordinate("GET /pets")
    assert normalize_operation_key(" Query.user ") == "Query.user"
    assert normalize_operation_key("Query.user.id") is None


def test_a_coordinate_naming_a_root_field_validates_without_a_response_schema() -> None:
    scenarios = _scenario({"Query.user": {"responses": [{"status": 200, "body": {"id": "u-1"}}]}})
    assert validate_mock_scenarios(scenarios, EMPTY_SPEC, graphql_operations=frozenset({"Query.user"})) == []


def test_a_coordinate_naming_no_root_field_is_rejected() -> None:
    scenarios = _scenario({"Query.nobody": {"responses": [{"status": 200}]}})
    errors = validate_mock_scenarios(scenarios, EMPTY_SPEC, graphql_operations=frozenset({"Query.user"}))
    assert errors == ["Scenario 'vip', operation 'Query.nobody': no GraphQL root field Query.nobody exists in this version's schema."]


def test_a_coordinate_still_validates_status_and_templates() -> None:
    scenarios = _scenario({"Query.user": {"responses": [{"status": 200, "body": "{{ nope("}]}})
    errors = validate_mock_scenarios(scenarios, EMPTY_SPEC, graphql_operations=frozenset({"Query.user"}))
    assert errors and "body" in errors[0]


def test_chaos_accepts_known_coordinates_and_rejects_unknown_ones() -> None:
    chaos = MockChaosSpec.model_validate({"operations": {"Query.user": {"errorRate": 50}, "Query.x": {"delayMs": 5}}})
    errors = validate_mock_chaos(chaos, EMPTY_SPEC, graphql_operations=frozenset({"Query.user"}))
    assert errors == ["Chaos, operation 'Query.x': no GraphQL root field Query.x exists in this version's schema."]


def test_uses_graphql_coordinates_looks_at_scenarios_and_chaos() -> None:
    assert not uses_graphql_coordinates(_scenario({"GET /pets": {"status": 500}}), None)
    assert uses_graphql_coordinates(_scenario({"Query.user": {"status": 500}}), None)
    chaos = MockChaosSpec.model_validate({"operations": {"Mutation.touch": {"errorRate": 1}}})
    assert uses_graphql_coordinates({}, chaos)


def test_graphql_settings_round_trip_through_storage() -> None:
    spec = MockGraphQlSettingsSpec.model_validate({"maxDepth": 4, "listLength": 2})
    stored = graphql_settings_to_storage(spec)
    assert stored == {"maxDepth": 4, "listLength": 2}
    assert graphql_settings_from_storage({"graphql": stored}) == stored
    assert graphql_settings_from_storage('{"graphql": {"maxDepth": 3}}') == {"maxDepth": 3}
    assert graphql_settings_from_storage({"graphql": [1]}) is None
    assert graphql_settings_from_storage(None) is None


def test_graphql_settings_enforce_their_ranges() -> None:
    with pytest.raises(ValueError):
        MockGraphQlSettingsSpec.model_validate({"maxDepth": 0})
    with pytest.raises(ValueError):
        MockGraphQlSettingsSpec.model_validate({"listLength": 51})
    with pytest.raises(ValueError):
        MockGraphQlSettingsSpec.model_validate({"maxComplexity": 100_001})
    with pytest.raises(ValueError):
        MockGraphQlSettingsSpec.model_validate({"depth": 3})


def test_graphql_settings_travel_in_mock_bundles() -> None:
    assert "graphql" in BUNDLED_SETTINGS_KEYS


# --------------------------------------------------------------------------------------------------
# Route
# --------------------------------------------------------------------------------------------------


def test_get_reports_the_stored_graphql_settings(client: TestClient) -> None:
    with patch(
        "app.versions_routes.db.get_version_by_id",
        return_value=_version_row({"graphql": {"maxDepth": 6}}),
    ), patch("app.versions_routes.enforce_permission"):
        response = client.get(ROUTE)
    assert response.status_code == 200, response.text
    assert response.json()["graphql"] == {"maxDepth": 6, "maxComplexity": None, "listLength": None}


def test_put_stores_graphql_settings_and_root_field_scenarios(client: TestClient) -> None:
    payload = {
        "scenarios": {"vip": {"operations": {"Query.user": {"responses": [{"status": 200, "body": {"id": "u-1"}}]}}}},
        "chaos": {"operations": {"Query.user": {"errorRate": 10}}},
        "graphql": {"maxDepth": 5, "maxComplexity": 200},
    }
    stored = {"graphql": {"maxDepth": 5, "maxComplexity": 200}}
    with patch("app.versions_routes.db.get_version_by_id", return_value=_version_row()), patch(
        "app.versions_routes._generated_spec_for_version", return_value=EMPTY_SPEC
    ), patch("app.versions_routes.db.load_canonical_api", return_value=GRAPHQL_API) as load, patch(
        "app.versions_routes.db.set_version_mock_scenarios", return_value=_version_row(stored)
    ) as write, patch("app.versions_routes.enforce_permission"):
        response = client.put(ROUTE, json=payload)
    assert response.status_code == 200, response.text
    load.assert_called_once()
    kwargs = write.call_args.kwargs
    assert kwargs["graphql"] == {"maxDepth": 5, "maxComplexity": 200}
    assert "Query.user" in kwargs["scenarios"]["vip"]["operations"]
    assert kwargs["chaos"] == {"operations": {"Query.user": {"errorRate": 10.0}}}
    assert response.json()["graphql"]["maxDepth"] == 5


def test_put_rejects_a_root_field_the_schema_does_not_have(client: TestClient) -> None:
    payload = {"scenarios": {"vip": {"operations": {"Query.nobody": {"responses": [{"status": 200}]}}}}}
    with patch("app.versions_routes.db.get_version_by_id", return_value=_version_row()), patch(
        "app.versions_routes._generated_spec_for_version", return_value=EMPTY_SPEC
    ), patch("app.versions_routes.db.load_canonical_api", return_value=GRAPHQL_API), patch(
        "app.versions_routes.enforce_permission"
    ):
        response = client.put(ROUTE, json=payload)
    assert response.status_code == 422
    assert "Query.nobody" in response.json()["detail"]["errors"][0]


def test_put_keeps_stored_graphql_settings_when_the_field_is_omitted(client: TestClient) -> None:
    existing = {"graphql": {"listLength": 2}}
    with patch("app.versions_routes.db.get_version_by_id", return_value=_version_row(existing)), patch(
        "app.versions_routes._generated_spec_for_version", return_value=EMPTY_SPEC
    ), patch("app.versions_routes.db.load_canonical_api") as load, patch(
        "app.versions_routes.db.set_version_mock_scenarios", return_value=_version_row(existing)
    ) as write, patch("app.versions_routes.enforce_permission"):
        response = client.put(ROUTE, json={"scenarios": {}})
    assert response.status_code == 200, response.text
    assert write.call_args.kwargs["graphql"] == {"listLength": 2}
    # No GraphQL keys in the payload, so the canonical model is never loaded.
    load.assert_not_called()


def test_put_clears_graphql_settings_sent_as_null(client: TestClient) -> None:
    existing = {"graphql": {"listLength": 2}}
    with patch("app.versions_routes.db.get_version_by_id", return_value=_version_row(existing)), patch(
        "app.versions_routes._generated_spec_for_version", return_value=EMPTY_SPEC
    ), patch("app.versions_routes.db.set_version_mock_scenarios", return_value=_version_row()) as write, patch(
        "app.versions_routes.enforce_permission"
    ):
        response = client.put(ROUTE, json={"scenarios": {}, "graphql": None})
    assert response.status_code == 200, response.text
    assert write.call_args.kwargs["graphql"] is None


def test_dry_run_reports_the_graphql_settings_it_would_store(client: TestClient) -> None:
    with patch("app.versions_routes.db.get_version_by_id", return_value=_version_row()), patch(
        "app.versions_routes._generated_spec_for_version", return_value=EMPTY_SPEC
    ), patch("app.versions_routes.db.set_version_mock_scenarios") as write, patch(
        "app.versions_routes.enforce_permission"
    ):
        response = client.put(f"{ROUTE}?dryRun=true", json={"scenarios": {}, "graphql": {"listLength": 4}})
    assert response.status_code == 200, response.text
    assert response.json()["graphql"]["listLength"] == 4
    write.assert_not_called()
