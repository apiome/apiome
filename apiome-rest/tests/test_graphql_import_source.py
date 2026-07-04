"""End-to-end tests for the GraphQL import source (MFI-10.6, #3775).

Exercises the adapter through the full SPI: detect → parse → normalize →
fingerprint/lint, plus the live-introspection discovery seam. Unlike the AsyncAPI
adapter (a Node-backed parser), the GraphQL toolchain (MFI-10.1/10.2/10.4) is pure
Python, so every path runs with no gating — SDL is built with ``graphql-core`` and
the only thing mocked is the introspection endpoint's network (an ``httpx.MockTransport``
fed the *real* introspection response of a built schema, exactly as
``test_graphql_introspection.py`` does).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest
from graphql import GraphQLSchema, build_schema, graphql_sync

from app import ssrf_guard
from app.canonical_model import ApiParadigm, CanonicalApi
from app.graphql_import_source import GraphQlImportSource
from app.graphql_introspection import build_introspection_query
from app.import_source import (
    DetectionInput,
    ImportSourceError,
    InputKind,
    LintReport,
)

# A small, valid SDL schema (a Query root + a couple of object types) — enough to exercise
# every step without being a fixture file.
_SDL = """
\"\"\"The blog API.\"\"\"
type Query {
  post(id: ID!): Post
  posts: [Post!]!
}

type Mutation {
  addPost(title: String!): Post!
}

\"\"\"A blog post.\"\"\"
type Post {
  id: ID!
  title: String!
  author: Author!
}

type Author {
  id: ID!
  name: String!
}
"""

_INVALID_SDL = "type Query { me: UnknownType }"

# A host the SSRF guard will see as a public IP (no real DNS), so the guarded introspection
# client runs without resolving ``api.example.com`` in the test environment.
_PUBLIC_IP = "93.184.216.34"


@contextmanager
def _resolve_public():
    """Make the SSRF guard treat the test endpoint as a public host (mirrors the introspection tests)."""
    with patch.object(ssrf_guard, "_resolve_host_ips", lambda host: [_PUBLIC_IP]):
        yield


@pytest.fixture()
def adapter() -> GraphQlImportSource:
    return GraphQlImportSource()


def _introspection_data(sdl: str) -> Dict[str, Any]:
    """Run the standard introspection query against ``sdl`` to get a real ``data`` payload."""
    schema = build_schema(sdl)
    result = graphql_sync(schema, build_introspection_query())
    assert result.errors is None
    assert result.data is not None
    return result.data


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _schema_responder(sdl: str):
    """A MockTransport handler answering any request with ``sdl``'s introspection result."""
    data = _introspection_data(sdl)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": data})

    return handler


# ===========================================================================
# Descriptor + registry
# ===========================================================================


def test_descriptor_metadata(adapter: GraphQlImportSource) -> None:
    d = adapter.descriptor()
    assert d.key == "graphql"
    assert d.label == "GraphQL"
    assert d.icon == "waypoints"
    assert d.paradigm is ApiParadigm.GRAPH
    assert set(d.input_kinds) == {
        InputKind.FILE,
        InputKind.URL,
        InputKind.PASTE,
        InputKind.DISCOVERY,
        InputKind.FILESET,
    }
    assert d.formats == ["graphql"]
    # GraphQL is the first source advertising live discovery (introspection).
    assert d.supports_live_discovery is True


def test_registered_in_import_source_registry() -> None:
    # Registering the adapter is all the UI source card / CLI dispatch need: it must surface
    # from the public registry enumeration and resolve to this class.
    from app.import_source import available_import_sources, get_import_source

    assert "graphql" in available_import_sources()
    assert isinstance(get_import_source("graphql"), GraphQlImportSource)


# ===========================================================================
# Detection
# ===========================================================================


def test_detect_sdl_text(adapter: GraphQlImportSource) -> None:
    result = adapter.detect(DetectionInput(text=_SDL))
    assert result.format == "graphql"
    assert result.confidence > 0.8


def test_detect_by_filename(adapter: GraphQlImportSource) -> None:
    result = adapter.detect(DetectionInput(text="schema { query: Q }", filename="api.graphql"))
    assert result.matched
    # A `.gql` extension alone (no recognizable text) still matches.
    assert adapter.detect(DetectionInput(text="", filename="api.gql")).matched


def test_detect_introspection_payload(adapter: GraphQlImportSource) -> None:
    data = _introspection_data(_SDL)
    assert adapter.detect(DetectionInput(document={"data": data})).format == "graphql"
    assert adapter.detect(DetectionInput(document=data)).format == "graphql"


def test_detect_non_graphql_is_no_match(adapter: GraphQlImportSource) -> None:
    assert adapter.detect(DetectionInput(document={"openapi": "3.1.0"})).matched is False
    assert adapter.detect(DetectionInput(text="just a sentence with no schema")).matched is False
    # Malformed JSON-looking text must not raise, just fail to match.
    assert adapter.detect(DetectionInput(text="{not valid json [")).matched is False


# ===========================================================================
# Parse (SDL)
# ===========================================================================


def test_parse_sdl_returns_built_schema(adapter: GraphQlImportSource) -> None:
    schema = adapter.parse(_SDL, source_label="blog.graphql")
    assert isinstance(schema, GraphQLSchema)
    assert schema.query_type is not None


def test_parse_invalid_sdl_raises_import_source_error(adapter: GraphQlImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.parse(_INVALID_SDL)


def test_parse_captured_introspection_response(adapter: GraphQlImportSource) -> None:
    # A discovery import whose document is the captured `__schema` answer parses through the
    # same path (full response and bare data object both accepted).
    data = _introspection_data(_SDL)
    schema = adapter.parse(json.dumps({"data": data}))
    assert isinstance(schema, GraphQLSchema)
    assert adapter.normalize(adapter.parse(json.dumps(data))).format == "graphql"


# ===========================================================================
# Normalize (catalogs a version) + lint
# ===========================================================================


def test_normalize_produces_graph_model(adapter: GraphQlImportSource) -> None:
    model = adapter.normalize(adapter.parse(_SDL))
    assert isinstance(model, CanonicalApi)
    assert model.paradigm is ApiParadigm.GRAPH
    assert model.format == "graphql"
    assert model.protocol == "graphql"
    # Query/Mutation roots become services; Post/Author become types.
    assert any(svc.operations for svc in model.services)
    assert any(t.key == "Post" for t in model.types)


def test_normalize_accepts_bare_sdl(adapter: GraphQlImportSource) -> None:
    # normalize() accepts SDL text directly (parses it first) so callers can skip parse().
    model = adapter.normalize(_SDL)
    assert model.format == "graphql"


def test_fingerprint_is_deterministic(adapter: GraphQlImportSource) -> None:
    a = adapter.normalize(adapter.parse(_SDL))
    b = adapter.normalize(adapter.parse(_SDL))
    assert adapter.fingerprint(a) == adapter.fingerprint(b)


def test_normalize_non_schema_raises(adapter: GraphQlImportSource) -> None:
    with pytest.raises(ImportSourceError, match="GraphQLSchema"):
        adapter.normalize(12345)


def test_normalize_without_raw_omits_fidelity_bag(adapter: GraphQlImportSource) -> None:
    model = adapter.normalize(adapter.parse(_SDL), include_raw=False)
    assert model.raw is None


def test_lint_rolls_up_to_score(adapter: GraphQlImportSource) -> None:
    model = adapter.normalize(adapter.parse(_SDL))
    report = adapter.lint(model)
    assert isinstance(report, LintReport)
    assert isinstance(report.score, int)
    assert 0 <= report.score <= 100
    assert report.grade in {"A", "B", "C", "D", "F"}
    assert report.report_fingerprint


# ===========================================================================
# Live introspection (discovery) — catalogs a version from a live endpoint
# ===========================================================================


def test_introspect_live_endpoint_catalogs_a_version(adapter: GraphQlImportSource) -> None:
    client = _mock_client(_schema_responder(_SDL))
    with _resolve_public():
        schema = adapter.introspect("https://api.example.com/graphql", client=client)
    assert isinstance(schema, GraphQLSchema)

    model = adapter.normalize(schema)
    assert model.paradigm is ApiParadigm.GRAPH
    assert model.format == "graphql"
    # The live-introspected model fingerprints identically to the same schema imported from SDL.
    assert adapter.fingerprint(model) == adapter.fingerprint(adapter.normalize(adapter.parse(_SDL)))

    report = adapter.lint(model)
    assert isinstance(report.score, int)


def test_introspect_disabled_falls_back_to_uploaded_sdl(adapter: GraphQlImportSource) -> None:
    def disabled(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"errors": [{"message": "GraphQL introspection is not allowed"}]}
        )

    client = _mock_client(disabled)
    with _resolve_public():
        schema = adapter.introspect(
            "https://api.example.com/graphql", fallback_sdl=_SDL, client=client
        )
    assert adapter.normalize(schema).format == "graphql"


def test_introspect_unavailable_without_fallback_raises(adapter: GraphQlImportSource) -> None:
    def disabled(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"errors": [{"message": "GraphQL introspection is not allowed"}]}
        )

    client = _mock_client(disabled)
    with _resolve_public(), pytest.raises(ImportSourceError):
        adapter.introspect("https://api.example.com/graphql", client=client)


def test_introspect_unsafe_url_raises(adapter: GraphQlImportSource) -> None:
    # An SSRF-rejected endpoint is a config error the caller must fix → ImportSourceError.
    with pytest.raises(ImportSourceError):
        adapter.introspect("http://169.254.169.254/graphql")
