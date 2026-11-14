"""Tests for the GraphQL mock adapter on the hosted engine (#5729, XPC-1.1)."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from app.canonical_model import ApiParadigm
from app.graphql_normalizer import GraphQlNormalizer
from app.mock_bundle import BundleIdentity, build_bundle
from app.mock_fixture_packs import PACK_FORMAT
from fastapi.responses import Response
from fastapi.testclient import TestClient
from graphql import build_schema, parse

from apiome_mock.canonical_compiler import GraphQlRoute, compile_canonical_spec, compile_graphql_route
from apiome_mock.canonical_loader import LoadedCanonicalSpec
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.chaos import CHAOS_DELAY_HEADER, CHAOS_HEADER
from apiome_mock.graphql_schema import (
    DEFAULT_LIST_LENGTH,
    DEFAULT_MAX_COMPLEXITY,
    DEFAULT_MAX_DEPTH,
    MAX_LIST_LENGTH,
    build_executable_schema,
    measure_operation,
    parse_graphql_settings,
)
from apiome_mock.graphql_transport import (
    CODE_BAD_REQUEST,
    CODE_CHAOS_INJECTED,
    CODE_MAX_COMPLEXITY,
    CODE_MAX_DEPTH,
    CODE_SCENARIO_ERROR,
    CODE_UNKNOWN_SCENARIO,
    CODE_UNSUPPORTED,
    GRAPHQL_OPERATION_SUPPORT,
    GraphQlHttpRequest,
    GraphQlHttpResult,
    graphiql_page,
    is_graphql_source_format,
    serve_graphql,
)
from apiome_mock.sandbox_routes import INTERNAL_TOKEN_HEADER, SANDBOX_PATH
from apiome_mock.scenarios import MOCK_SCENARIO_HEADER, normalize_operation_key

TENANT = "demo"
PROJECT = "people"
VERSION = "1.0.0"
TOKEN = "internal-test-token"

SDL = """
directive @example(value: String) on FIELD_DEFINITION | OBJECT

enum Role { ADMIN USER }

interface Node { id: ID! }

type User implements Node {
  id: ID!
  email: String!
  name: String @example(value: "Ada Lovelace")
  role: Role!
  posts: [Post!]!
}

type Post implements Node {
  id: ID!
  title: String!
  author: User
}

union SearchResult = User | Post

type Query {
  user(id: ID!): User
  users: [User!]!
  search(q: String): [SearchResult!]!
  node(id: ID!): Node
  greeting: String
}

type Mutation {
  createUser(email: String!): User!
}

type Subscription {
  userCreated: User!
}
"""


def _api() -> Any:
    """The canonical model of :data:`SDL`, as the importer stores it."""
    return GraphQlNormalizer().normalize(build_schema(SDL))


def _route(mock_settings: dict[str, Any] | None = None) -> GraphQlRoute:
    """Compile :data:`SDL` with one ``mock_settings`` blob."""
    return compile_graphql_route(_api(), mock_settings or {})


def _post(
    query: str,
    *,
    variables: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    seed: str | None = None,
) -> GraphQlHttpRequest:
    """Describe one POST GraphQL request."""
    body: dict[str, Any] = {"query": query}
    if variables is not None:
        body["variables"] = variables
    return GraphQlHttpRequest(
        method="POST",
        headers={name.lower(): value for name, value in (headers or {}).items()},
        query={"__seed": (seed,)} if seed is not None else {},
        body=body,
        body_present=True,
    )


def _serve(route: GraphQlRoute, request: GraphQlHttpRequest) -> GraphQlHttpResult:
    """Run :func:`serve_graphql` synchronously."""
    return asyncio.run(serve_graphql(route, request, tenant=TENANT))


def _codes(result: GraphQlHttpResult) -> list[str]:
    """The ``extensions.code`` of every error in a result."""
    return [error.get("extensions", {}).get("code") for error in result.body.get("errors", [])]


# ==================================================================================================
# Schema, settings and limits
# ==================================================================================================


def test_compile_canonical_spec_builds_a_graphql_route_for_graph_versions() -> None:
    loaded = LoadedCanonicalSpec(
        revision_id=uuid4(),
        tenant_slug=TENANT,
        project_slug=PROJECT,
        version_label=VERSION,
        updated_at=datetime.now(timezone.utc),
        api=_api(),
        source_format="graphql",
        mock_settings={"graphql": {"listLength": 2}},
    )
    compiled = compile_canonical_spec(loaded)
    assert loaded.paradigm is ApiParadigm.GRAPH
    assert compiled.graphql is not None
    assert compiled.graphql.settings.list_length == 2
    assert compiled.event_channels == ()
    assert compiled.grpc_methods == ()


def test_schema_falls_back_to_the_emitter_when_the_model_has_no_sdl() -> None:
    api = GraphQlNormalizer().normalize(build_schema(SDL), include_raw=False)
    schema = build_executable_schema(api)
    assert schema.query_type is not None
    assert "user" in schema.query_type.fields
    assert schema.get_type("User") is not None


def test_graphql_settings_default_clamp_and_ignore_malformed_values() -> None:
    defaults = parse_graphql_settings(None)
    assert (defaults.max_depth, defaults.max_complexity, defaults.list_length) == (
        DEFAULT_MAX_DEPTH,
        DEFAULT_MAX_COMPLEXITY,
        DEFAULT_LIST_LENGTH,
    )
    clamped = parse_graphql_settings({"graphql": {"maxDepth": 0, "listLength": 10_000, "maxComplexity": "x"}})
    assert clamped.max_depth == 1
    assert clamped.list_length == MAX_LIST_LENGTH
    assert clamped.max_complexity == DEFAULT_MAX_COMPLEXITY
    assert parse_graphql_settings('{"graphql": {"maxDepth": 3}}').max_depth == 3
    assert parse_graphql_settings("not json").max_depth == DEFAULT_MAX_DEPTH
    assert parse_graphql_settings({"graphql": {"maxDepth": True}}).max_depth == DEFAULT_MAX_DEPTH


def test_measure_operation_expands_fragments_and_multiplies_lists() -> None:
    schema = build_schema(SDL)
    document = parse("query { users { ...U } } fragment U on User { id posts { title author { id } } }")
    operation = document.definitions[0]
    fragments = {definition.name.value: definition for definition in document.definitions[1:]}
    measure = measure_operation(schema, operation, fragments, list_length=3)  # type: ignore[arg-type]
    assert measure.depth == 4
    # users(1) + id(3) + posts(3) + title(9) + author(9) + author.id(9)
    assert measure.complexity == 34


def test_measure_operation_ignores_introspection() -> None:
    schema = build_schema(SDL)
    document = parse("{ __schema { types { fields { type { ofType { ofType { name } } } } } } greeting }")
    measure = measure_operation(schema, document.definitions[0], {}, list_length=3)  # type: ignore[arg-type]
    assert measure.depth == 1
    assert measure.complexity == 1


def test_graphql_coordinates_are_operation_keys() -> None:
    assert normalize_operation_key("Query.user") == "Query.user"
    assert normalize_operation_key(" Mutation.createUser ") == "Mutation.createUser"
    assert normalize_operation_key("Query.") is None
    assert normalize_operation_key("Query.user.id") is None
    assert normalize_operation_key("get /pets") == "GET /pets"


def test_source_format_detection_and_capabilities() -> None:
    assert is_graphql_source_format("graphql")
    assert is_graphql_source_format("GraphQL-federation")
    assert not is_graphql_source_format("openapi-3.1")
    assert not is_graphql_source_format(None)
    assert GRAPHQL_OPERATION_SUPPORT["subscription"] == "unsupported"
    assert GRAPHQL_OPERATION_SUPPORT["query"] == "supported"


# ==================================================================================================
# Resolution: examples, seeded synthesis, fixtures
# ==================================================================================================


def test_query_answers_with_examples_where_declared_and_synthetic_data_elsewhere() -> None:
    result = _serve(_route(), _post('{ user(id: "1") { id email name role posts { title } } }'))
    assert result.status == 200
    assert "errors" not in result.body
    user = result.body["data"]["user"]
    assert user["name"] == "Ada Lovelace"
    assert "@" in user["email"]
    assert user["role"] in {"ADMIN", "USER"}
    assert len(user["posts"]) == DEFAULT_LIST_LENGTH
    assert all(isinstance(post["title"], str) and post["title"] for post in user["posts"])


def test_the_same_seed_gives_the_same_response_and_another_seed_differs() -> None:
    route = _route()
    query = '{ user(id: "1") { id email posts { id title } } }'
    first = _serve(route, _post(query, seed="7"))
    again = _serve(route, _post(query, seed="7"))
    other = _serve(route, _post(query, seed="8"))
    assert first.body == again.body
    assert first.body != other.body


def test_a_mutation_returns_the_declared_payload_type() -> None:
    result = _serve(
        _route(),
        _post(
            "mutation Create($email: String!) { createUser(email: $email) { id email } }", variables={"email": "x@y.z"}
        ),
    )
    created = result.body["data"]["createUser"]
    assert set(created) == {"id", "email"}
    assert result.operation == "mutation"


def test_unions_interfaces_aliases_and_directives_resolve() -> None:
    result = _serve(
        _route(),
        _post(
            """
            query($withEmail: Boolean!) {
              search { __typename ... on User { email @include(if: $withEmail) } ... on Post { title } }
              first: node(id: "1") { id __typename }
              hidden: greeting @skip(if: true)
            }
            """,
            variables={"withEmail": True},
        ),
    )
    data = result.body["data"]
    assert {item["__typename"] for item in data["search"]} <= {"User", "Post"}
    for item in data["search"]:
        assert ("email" in item) == (item["__typename"] == "User")
    assert data["first"]["__typename"] in {"User", "Post"}
    assert "hidden" not in data


def test_unknown_fields_produce_standard_graphql_errors() -> None:
    result = _serve(_route(), _post('{ user(id: "1") { nope } }'))
    assert result.status == 200
    assert "data" not in result.body
    assert "Cannot query field 'nope'" in result.body["errors"][0]["message"]


def test_syntax_errors_are_graphql_errors() -> None:
    result = _serve(_route(), _post("{ user("))
    assert result.status == 200
    assert "Syntax Error" in result.body["errors"][0]["message"]


def test_introspection_is_answered() -> None:
    result = _serve(_route(), _post("{ __schema { queryType { name } } }"))
    assert result.body["data"]["__schema"]["queryType"]["name"] == "Query"


def test_fixture_pack_values_keyed_by_coordinate_are_served() -> None:
    settings = {
        "fixturePacks": {
            "people": {
                "packFormat": PACK_FORMAT,
                "packFormatVersion": 1,
                "data": {"Query.greeting": "Hello from a fixture pack", "User.email": "fixture@example.com"},
            }
        }
    }
    result = _serve(_route(settings), _post('{ greeting user(id: "1") { email } }'))
    assert result.body["data"]["greeting"] == "Hello from a fixture pack"
    assert result.body["data"]["user"]["email"] == "fixture@example.com"


def test_list_length_setting_shapes_synthesized_lists() -> None:
    result = _serve(_route({"graphql": {"listLength": 1}}), _post("{ users { id } }"))
    assert len(result.body["data"]["users"]) == 1


# ==================================================================================================
# Limits and unsupported operations
# ==================================================================================================


def test_depth_cap_returns_a_graphql_error_not_a_500() -> None:
    result = _serve(_route({"graphql": {"maxDepth": 2}}), _post('{ user(id: "1") { posts { title } } }'))
    assert result.status == 200
    assert _codes(result) == [CODE_MAX_DEPTH]
    assert "data" not in result.body


def test_complexity_cap_returns_a_graphql_error_not_a_500() -> None:
    result = _serve(_route({"graphql": {"maxComplexity": 5}}), _post("{ users { id email posts { id } } }"))
    assert result.status == 200
    assert _codes(result) == [CODE_MAX_COMPLEXITY]


def test_subscriptions_return_the_unsupported_error() -> None:
    result = _serve(_route(), _post("subscription { userCreated { id } }"))
    assert result.status == 200
    assert _codes(result) == [CODE_UNSUPPORTED]
    assert result.operation == "subscription"


def test_get_runs_queries_and_refuses_mutations() -> None:
    route = _route()
    query = _serve(route, GraphQlHttpRequest(method="GET", query={"query": ("{ greeting }",)}))
    assert query.status == 200
    assert isinstance(query.body["data"]["greeting"], str)
    mutation = _serve(
        route,
        GraphQlHttpRequest(method="GET", query={"query": ('mutation { createUser(email: "a") { id } }',)}),
    )
    assert mutation.status == 405


def test_unreadable_requests_are_400s() -> None:
    route = _route()
    no_query = _serve(route, GraphQlHttpRequest(method="POST", body={}, body_present=True))
    bad_json = _serve(route, GraphQlHttpRequest(method="POST", body_present=True, body_invalid=True))
    bad_vars = _serve(route, GraphQlHttpRequest(method="GET", query={"query": ("{ greeting }",), "variables": ("{",)}))
    for result in (no_query, bad_json, bad_vars):
        assert result.status == 400
        assert _codes(result) == [CODE_BAD_REQUEST]


# ==================================================================================================
# Scenarios and chaos
# ==================================================================================================


def test_a_scenario_overrides_one_root_field_and_leaves_the_others_alone() -> None:
    settings = {
        "scenarios": {
            "vip": {
                "operations": {
                    "Query.user": {"responses": [{"status": 200, "body": {"id": "u-1", "email": "vip@example.com"}}]}
                }
            }
        }
    }
    result = _serve(
        _route(settings),
        _post('{ user(id: "1") { id email name } greeting }', headers={MOCK_SCENARIO_HEADER: "vip"}),
    )
    data = result.body["data"]
    assert data["user"]["id"] == "u-1"
    assert data["user"]["email"] == "vip@example.com"
    # A field the canned body leaves out is still resolved (here from the declared example).
    assert data["user"]["name"] == "Ada Lovelace"
    assert isinstance(data["greeting"], str)
    assert result.headers[MOCK_SCENARIO_HEADER] == "vip"
    assert result.scenario == "vip"


def test_a_scenario_error_status_becomes_a_graphql_error_on_that_field() -> None:
    settings = {
        "scenarios": {
            "missing": {
                "operations": {"Query.user": {"responses": [{"status": 404, "body": {"detail": "No such user."}}]}}
            }
        },
        "activeScenario": "missing",
    }
    result = _serve(_route(settings), _post('{ user(id: "1") { id } greeting }'))
    assert result.body["data"]["user"] is None
    assert isinstance(result.body["data"]["greeting"], str)
    error = result.body["errors"][0]
    assert error["message"] == "No such user."
    assert error["path"] == ["user"]
    assert error["extensions"]["code"] == CODE_SCENARIO_ERROR
    assert error["extensions"]["status"] == 404


def test_the_built_in_server_error_scenario_fails_every_root_field() -> None:
    result = _serve(_route(), _post("{ greeting users { id } }", headers={MOCK_SCENARIO_HEADER: "server-error"}))
    assert set(_codes(result)) == {CODE_SCENARIO_ERROR}
    assert len(result.body["errors"]) == 2


def test_an_unknown_scenario_is_a_graphql_error() -> None:
    result = _serve(_route(), _post("{ greeting }", headers={MOCK_SCENARIO_HEADER: "nope"}))
    assert _codes(result) == [CODE_UNKNOWN_SCENARIO]


def test_chaos_injection_appears_as_a_graphql_error_with_the_chaos_headers() -> None:
    settings = {"chaos": {"operations": {"Query.user": {"errorRate": 100, "delayMs": 5}}}}
    result = _serve(_route(settings), _post('{ user(id: "1") { id } greeting }'))
    assert result.status == 200
    assert result.body["data"]["user"] is None
    assert isinstance(result.body["data"]["greeting"], str)
    assert _codes(result) == [CODE_CHAOS_INJECTED]
    assert result.body["errors"][0]["path"] == ["user"]
    assert result.headers[CHAOS_HEADER] == "error"
    assert result.headers[CHAOS_DELAY_HEADER] == "5"


# ==================================================================================================
# Hosted route and sandbox
# ==================================================================================================


def test_graphiql_page_escapes_its_title_and_targets_the_endpoint() -> None:
    page = graphiql_page("https://mock.example/a/b/1/graphql", title="<a>/b/1")
    assert "&lt;a&gt;/b/1" in page
    assert '"https://mock.example/a/b/1/graphql"' in page
    assert "graphiql.min.js" in page
    hostile = graphiql_page("https://mock.example/x</script><script>alert(1)</script>", title="t")
    assert "</script><script>alert(1)" not in hostile
    assert "\\u003c/script>" in hostile


@pytest.fixture
def hosted(monkeypatch: pytest.MonkeyPatch, mock_pool: MagicMock) -> Iterator[Any]:
    """A hosted-runtime client whose canonical resolution returns :data:`SDL` (or a REST version)."""
    monkeypatch.setenv("APIOME_MOCK_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MOCK_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("APIOME_MOCK_INTERNAL_TOKEN", TOKEN)
    from apiome_mock.settings import get_settings

    get_settings.cache_clear()

    @contextmanager
    def build(source_format: str = "graphql", mock_settings: Any = None) -> Iterator[tuple[TestClient, MagicMock]]:
        from apiome_mock.server import create_app

        loaded = LoadedCanonicalSpec(
            revision_id=uuid4(),
            tenant_slug=TENANT,
            project_slug=PROJECT,
            version_label=VERSION,
            updated_at=datetime.now(timezone.utc),
            api=_api(),
            source_format=source_format,
            mock_settings=mock_settings,
        )
        limits = MagicMock(tenant_id=uuid4())
        record = MagicMock()
        rest = AsyncMock(return_value=Response(status_code=200))
        with (
            patch("apiome_mock.server.create_async_pool", return_value=mock_pool),
            patch("apiome_mock.server.validate_api_key_for_tenant", new=AsyncMock(return_value=None)),
            patch("apiome_mock.server.enforce_mock_limits", new=AsyncMock(return_value=None)),
            patch("apiome_mock.server.resolve_limits_for_tenant", new=AsyncMock(return_value=None)),
            patch("apiome_mock.server.handle_mock_request", new=rest),
            patch(
                "apiome_mock.graphql_transport._fetch_access_row",
                new=AsyncMock(return_value={"source_format": source_format, "mock_enabled": True}),
            ),
            patch("apiome_mock.graphql_transport.load_canonical_spec", new=AsyncMock(return_value=loaded)),
            patch("apiome_mock.graphql_transport.enforce_mock_limits", new=AsyncMock(return_value=None)),
            patch("apiome_mock.graphql_transport.resolve_limits_for_tenant", new=AsyncMock(return_value=limits)),
            patch("apiome_mock.graphql_transport.record_mock_request", new=record),
        ):
            app = create_app()
            with TestClient(app, raise_server_exceptions=False) as client:
                app.state.db_pool = mock_pool
                app.state.canonical_spec_cache = CanonicalSpecCache(max_entries=8, ttl_seconds=300.0)
                client.rest = rest  # type: ignore[attr-defined]
                yield client, record

    yield build
    get_settings.cache_clear()


def test_hosted_route_answers_a_post_and_counts_usage_like_rest(hosted: Any) -> None:
    with hosted() as (client, record):
        response = client.post(f"/{TENANT}/{PROJECT}/{VERSION}/graphql", json={"query": "{ greeting }"})
    assert response.status_code == 200
    assert isinstance(response.json()["data"]["greeting"], str)
    record.assert_called_once()
    assert record.call_args.kwargs["path"] == "graphql"
    assert record.call_args.kwargs["status_code"] == 200


def test_hosted_route_serves_graphiql_on_a_bare_get(hosted: Any) -> None:
    with hosted() as (client, _record):
        response = client.get(f"/{TENANT}/{PROJECT}/{VERSION}/graphql")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "GraphiQL" in response.text


def test_hosted_route_reports_chaos_headers(hosted: Any) -> None:
    settings = {"chaos": {"default": {"errorRate": 100}}}
    with hosted(mock_settings=settings) as (client, _record):
        response = client.post(f"/{TENANT}/{PROJECT}/{VERSION}/graphql", json={"query": "{ greeting }"})
    assert response.headers[CHAOS_HEADER] == "error"
    assert response.json()["errors"][0]["extensions"]["code"] == CODE_CHAOS_INJECTED


def test_a_rest_version_with_a_graphql_path_falls_through_to_the_rest_mock(hosted: Any) -> None:
    with hosted(source_format="openapi-3.1") as (client, record):
        client.post(f"/{TENANT}/{PROJECT}/{VERSION}/graphql", json={"query": "{ greeting }"})
        assert client.rest.await_count == 1  # type: ignore[attr-defined]
        assert client.rest.await_args.kwargs["path"] == "graphql"  # type: ignore[attr-defined]
    record.assert_not_called()


def _bundle(settings: dict[str, Any]) -> dict[str, Any]:
    """A sandbox bundle carrying ``settings`` (its OpenAPI spec is irrelevant to /graphql)."""
    return build_bundle(
        identity=BundleIdentity(
            tenant=TENANT,
            project=PROJECT,
            version=VERSION,
            revision_id=str(uuid4()),
            published=True,
            protocol="graphql",
        ),
        spec={"openapi": "3.1.0", "info": {"title": "x", "version": "1"}, "paths": {}},
        mock_settings=settings,
    )


def test_the_sandbox_serves_the_same_graphql_route(hosted: Any) -> None:
    settings = {"graphql": {"maxDepth": 2}}
    with hosted() as (client, _record):
        served = client.post(
            SANDBOX_PATH,
            json={
                "sandbox": "sandbox-1",
                "bundle": _bundle(settings),
                "graphqlSdl": SDL,
                "request": {"method": "POST", "path": "/graphql", "body": {"query": "{ greeting }"}, "seed": 3},
            },
            headers={INTERNAL_TOKEN_HEADER: TOKEN},
        )
        too_deep = client.post(
            SANDBOX_PATH,
            json={
                "sandbox": "sandbox-1",
                "bundle": _bundle(settings),
                "graphqlSdl": SDL,
                "request": {
                    "method": "POST",
                    "path": "/graphql",
                    "body": {"query": '{ user(id: "1") { posts { id } } }'},
                },
            },
            headers={INTERNAL_TOKEN_HEADER: TOKEN},
        )
    assert served.status_code == 200, served.text
    result = served.json()
    assert result["status"] == 200
    assert result["bodyEncoding"] == "json"
    assert isinstance(result["body"]["data"]["greeting"], str)
    assert result["operation"] == "query"
    assert too_deep.json()["body"]["errors"][0]["extensions"]["code"] == CODE_MAX_DEPTH


def test_the_sandbox_reports_an_sdl_that_does_not_build(hosted: Any) -> None:
    with hosted() as (client, _record):
        served = client.post(
            SANDBOX_PATH,
            json={
                "sandbox": "sandbox-1",
                "bundle": _bundle({}),
                "graphqlSdl": "type Query {",
                "request": {"method": "POST", "path": "/graphql", "body": {"query": "{ a }"}},
            },
            headers={INTERNAL_TOKEN_HEADER: TOKEN},
        )
    assert served.status_code == 200
    assert "could not be built" in served.json()["body"]["errors"][0]["message"]
