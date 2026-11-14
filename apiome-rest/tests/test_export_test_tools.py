"""Per-target test-drive tooling registry — MFX-44.1 (#4367).

* tools are declared on the emitter and land, resolved, in its descriptor's ``test_tools``;
* client-side tools are always available; server-side ones (mock, toolchain) report this server's
  availability and the reason when they are not;
* a mock-servable format gains ``mock-server`` without declaring it (once, even if declared);
* ``GET /v1/export/{tenant}/targets`` carries the list, so the UI reads it from the registry alone;
* the built-in declarations: Swagger UI / ReDoc / mock on OpenAPI, GraphiQL on GraphQL, the AsyncAPI viewer,
  and the IDL toolchain checks.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi
from app.config import settings
from app.emitter import EmitResult, Emitter, get_emitter
from app.export_mock import export_mock_availability, mock_engine_unavailable_reason
from app.export_source import ExportSource
from app.export_test_tools import (
    ExportTestToolKind,
    resolve_test_tools,
    test_tool,
    toolchain_check,
)
from app.main import app

client = TestClient(app)

K = ExportTestToolKind


@pytest.fixture
def mock_on(monkeypatch):
    monkeypatch.setattr(settings, "mock_server_enabled", True)
    monkeypatch.setattr(settings, "export_mock_enabled", True)


class _NewEmitter(Emitter):
    """An emitter this suite invents: it declares tools and nothing else knows about it."""

    key = "brand-new"
    format = "brand-new-1"
    label = "Brand new"
    paradigm = ApiParadigm.REST
    test_tools = (test_tool(K.SWAGGER_UI, label="Preview", spec_path="api.json"), toolchain_check("buf", "lint"))

    def emit(self, api, *, opts=None) -> EmitResult:  # pragma: no cover - never emitted
        raise NotImplementedError


def _kinds(tools):
    return [(t.kind.value, t.label) for t in tools]


def test_client_side_tools_are_always_available() -> None:
    tools = resolve_test_tools([test_tool(K.GRAPHIQL), test_tool(K.REDOC, label="Docs")], target_format="graphql")
    assert _kinds(tools) == [("graphiql", "GraphiQL"), ("redoc", "Docs")]
    assert all(t.available and t.unavailable_reason is None and not t.server_side for t in tools)


def test_a_toolchain_check_reports_whether_its_tool_is_installed() -> None:
    spec = toolchain_check("buf", "lint")
    with patch("app.export_test_tools._tool_installed", return_value=True):
        [installed] = resolve_test_tools([spec], target_format="proto3")
    with patch("app.export_test_tools._tool_installed", return_value=False):
        [missing] = resolve_test_tools([spec], target_format="proto3")
    assert installed.server_side and installed.available and installed.params == {"tool": "buf", "check": "lint"}
    assert installed.label == "buf lint"
    assert not missing.available and missing.unavailable_reason == "The buf toolchain is not installed on this server."


def test_a_mock_servable_format_gains_the_mock_once(mock_on) -> None:
    [mock] = resolve_test_tools([], target_format="openapi-3.1")
    assert (mock.kind, mock.label, mock.server_side, mock.available) == (K.MOCK_SERVER, "Mock server", True, True)
    assert resolve_test_tools([], target_format="graphql") == []
    declared = resolve_test_tools([test_tool(K.MOCK_SERVER, label="Live mock")], target_format="openapi-3.1")
    assert _kinds(declared) == [("mock-server", "Live mock")]


@pytest.mark.parametrize("mock_server, export_mock, reason", [
    (False, True, "The Mock Server is not enabled on this server, so an export cannot be mocked."),
    (True, False, "Export test-drive mocks are disabled on this server."),
])
def test_the_mock_is_unavailable_with_the_server_s_reason(monkeypatch, mock_server, export_mock, reason) -> None:
    monkeypatch.setattr(settings, "mock_server_enabled", mock_server)
    monkeypatch.setattr(settings, "export_mock_enabled", export_mock)
    [mock] = resolve_test_tools([], target_format="openapi-3.1")
    assert not mock.available and mock.unavailable_reason == reason
    # The capability endpoint's answer is the same switch.
    assert mock_engine_unavailable_reason() == reason == export_mock_availability().reason


def test_a_new_emitter_s_declared_tools_reach_its_descriptor() -> None:
    with patch("app.export_test_tools._tool_installed", return_value=False):
        tools = _NewEmitter.descriptor().test_tools
    assert _kinds(tools) == [("swagger-ui", "Preview"), ("toolchain", "buf lint")]
    assert tools[0].params == {"spec_path": "api.json"} and tools[0].available
    assert not tools[1].available and "buf" in tools[1].unavailable_reason


def test_an_emitter_without_tools_has_none() -> None:
    assert get_emitter("avro").descriptor().test_tools == []


def test_the_built_in_declarations(mock_on) -> None:
    def kinds(fmt: str):
        return [t.kind.value for t in get_emitter(fmt).descriptor().test_tools]

    assert kinds("openapi-3.1") == ["swagger-ui", "redoc", "toolchain", "mock-server"]
    assert kinds("graphql") == ["graphiql", "toolchain"]
    assert get_emitter("graphql").descriptor().test_tools[1].params == {"tool": "rover", "check": "compose"}
    assert kinds("asyncapi-3") == ["asyncapi-render", "toolchain"]
    proto = get_emitter("proto3").descriptor().test_tools
    assert [t.label for t in proto] == ["buf lint", "buf build"]
    for fmt, tool in [("typespec", "tsp"), ("smithy", "smithy"), ("capnproto", "capnp"), ("thrift", "thrift"),
                      ("apiblueprint", "drafter")]:
        emitter = get_emitter(fmt)
        assert emitter is not None, fmt
        assert [t.params["tool"] for t in emitter.descriptor().test_tools] == [tool]


def test_the_targets_route_carries_the_tools(mock_on) -> None:
    api = CanonicalApi(paradigm=ApiParadigm.REST, format="openapi-3.1", identity=ApiIdentity(name="w"))
    source = ExportSource(api=api, artifact_id="a", version_record_id="r", version_label="1.0.0")
    app.dependency_overrides[validate_authentication] = lambda: {"tenant_id": "t", "user_id": "u", "auth_method": "jwt"}
    try:
        with patch("app.export_routes.load_export_source", return_value=source), \
                patch("app.export_test_tools._tool_installed", return_value=False):
            response = client.get("/v1/export/acme/targets?artifact=a")
    finally:
        app.dependency_overrides.pop(validate_authentication, None)
    assert response.status_code == 200, response.text
    by_key = {t["descriptor"]["key"]: t["descriptor"]["test_tools"] for t in response.json()["targets"]}
    assert [t["kind"] for t in by_key["openapi"]] == ["swagger-ui", "redoc", "toolchain", "mock-server"]
    lint = by_key["openapi"][2]
    assert lint == {"kind": "toolchain", "label": "redocly lint", "params": {"tool": "redocly", "check": "lint"},
                    "server_side": True, "available": False,
                    "unavailable_reason": "The redocly toolchain is not installed on this server."}
    assert by_key["avro"] == []
