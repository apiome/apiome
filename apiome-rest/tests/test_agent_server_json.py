"""``server.json`` export for the agent runtime — AAU-5.1 (#5722).

Authentication is overridden and the toolset accessors are the in-memory
:class:`~agent_toolset_fakes.FakeToolsetStore`. These tests pin the acceptance criteria:

* every export validates against the vendored registry ``ServerDetail`` schema;
* importing a toolset export back through the MCP manifest importer yields the same tools and the
  same surface fingerprint as the export's ``digest``;
* the digest changes when curation changes and not otherwise;
* the document is byte-stable;

plus the auth hint, credential-free remotes, and each route's permission and refusals.
"""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List
from unittest.mock import patch

import jsonschema
import pytest
from agent_toolset_fakes import FakeToolsetStore
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.agent_toolset_enrichment as enrichment
import app.agent_toolsets as toolsets
from app import agent_server_json
from app.agent_server_json import (
    AGENT_RUNTIME_META_KEY,
    build_tenant_server_json,
    runtime_server_name,
    toolset_server_name,
)
from app.auth import validate_authentication
from app.database import db
from app.main import app
from app.mcp_manifest_parser import (
    embedded_server_json_manifest,
    is_mcp_manifest,
    manifest_surface,
    parse_mcp_manifest,
)
from app.mcp_registry import definition_schema
from app.openapi_normalizer import OpenApiNormalizer
from app.permissions import Action, Resource

client = TestClient(app)

_TENANT = "11111111-1111-4111-8111-111111111111"
_ACTOR = "33333333-3333-4333-8333-333333333333"
_MOCK_AUTH = {"tenant_id": _TENANT, "user_id": _ACTOR, "auth_method": "jwt", "user_email": "a@x.io"}
_MISSING = "77777777-7777-4777-8777-777777777777"
_BASE = "/v1/tenants/acme/agent-toolsets"
_TENANT_WIDE = "/v1/tenants/acme/agent-access/server.json"
_RUNTIME_URL = "https://agents.example.com/agent/mcp"

#: Reads plus a write op whose body references shared components (the compiler inlines them, so
#: the embedded manifest is self-contained and the round trip needs no ``$ref`` resolution).
SPEC: Dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Pets", "version": "1.0.0"},
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "summary": "List pets",
                "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
                "responses": {"200": {"description": "ok"}},
            },
            "post": {
                "operationId": "createPet",
                "summary": "Create a pet",
                "requestBody": {
                    "required": True,
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}},
                },
                "responses": {"201": {"description": "ok"}},
            },
        },
        "/pets/{id}": {
            "get": {
                "operationId": "getPet",
                "summary": "Get a pet",
                "parameters": [
                    {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
                ],
                "responses": {"200": {"description": "ok"}},
            },
        },
    },
    "components": {
        "schemas": {
            "Pet": {
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}, "tag": {"$ref": "#/components/schemas/Tag"}},
            },
            "Tag": {"type": "string", "enum": ["dog", "cat"]},
        }
    },
}


@pytest.fixture(autouse=True)
def _auth():
    """Authenticate every request as a member of ``_TENANT``."""
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def store(monkeypatch) -> FakeToolsetStore:
    """Toolsets in memory over :data:`SPEC`, the tenant slug ``acme`` and a named project."""
    monkeypatch.setattr(
        toolsets, "_load_version_api", lambda *_args: OpenApiNormalizer().normalize(SPEC)
    )
    monkeypatch.setattr(enrichment.settings, "agent_enrichment_model", None)
    monkeypatch.setattr(agent_server_json.settings, "agent_mcp_public_url", _RUNTIME_URL)
    monkeypatch.setattr(agent_server_json.settings, "agent_mcp_protected_resource_metadata_url", "")
    monkeypatch.setattr(db, "get_tenant_slug_by_id", lambda _tenant_id: "acme")
    monkeypatch.setattr(db, "get_project_by_id", lambda *_args, **_kw: {"name": "Pet Store"})
    monkeypatch.setattr(db, "get_project_core", lambda *_args, **_kw: {"name": "Pet Store"})
    monkeypatch.setattr(db, "write_access_audit", lambda **_fields: None)
    return FakeToolsetStore().install(monkeypatch, db)


def _create(store: FakeToolsetStore, label: str = "1.0.0") -> Dict[str, Any]:
    response = client.post(_BASE, json={"versionId": store.seed_version(_TENANT, label=label)})
    assert response.status_code == 201, response.text
    return response.json()


def _export(toolset_id: str) -> Dict[str, Any]:
    response = client.get(f"{_BASE}/{toolset_id}/server.json")
    assert response.status_code == 200, response.text
    return response.json()


def _tool_id(toolset_id: str, tool_name: str) -> str:
    tools = client.get(f"{_BASE}/{toolset_id}/tools").json()["tools"]
    return next(tool["id"] for tool in tools if tool["toolName"] == tool_name)


def _validate(document: Dict[str, Any], definition: str = "ServerDetail") -> None:
    jsonschema.Draft7Validator(
        definition_schema(definition), format_checker=jsonschema.FormatChecker()
    ).validate(document)


def _runtime(document: Dict[str, Any]) -> Dict[str, Any]:
    return document["_meta"][AGENT_RUNTIME_META_KEY]


# ============================================================================
# Shape and schema
# ============================================================================
def test_toolset_export_validates_and_names_the_runtime(store):
    toolset = _create(store)
    document = _export(toolset["id"])
    _validate(document)
    assert document["name"] == toolset_server_name("acme", toolset["id"])
    assert document["version"] == "1.0.0"
    assert document["title"] == "Pet Store 1.0.0 agent toolset"
    assert document["description"] == "Agent Access to Pet Store 1.0.0: 2 MCP tools."
    [remote] = document["remotes"]
    assert (remote["type"], remote["url"]) == ("streamable-http", _RUNTIME_URL)
    runtime = _runtime(document)
    assert runtime["schemaVersion"] == "aau.server-json.v1"
    assert (runtime["toolsetId"], runtime["versionLabel"], runtime["toolCount"]) == (
        toolset["id"],
        "1.0.0",
        2,
    )
    assert [tool["name"] for tool in runtime["manifest"]["tools"]] == ["listPets", "getPet"]
    assert len(runtime["digest"]) == 64


def test_tools_are_the_compiled_tools(store):
    toolset = _create(store)
    compiled = client.get(f"{_BASE}/{toolset['id']}/compiled").json()
    assert _runtime(_export(toolset["id"]))["manifest"]["tools"] == compiled["tools"]


def test_agent_key_hint_without_oauth(store):
    document = _export(_create(store)["id"])
    assert _runtime(document)["auth"] == {
        "scheme": "agent-key",
        "header": "Authorization",
        "format": "Bearer <agent key>",
    }
    [header] = document["remotes"][0]["headers"]
    assert header["name"] == "Authorization"
    assert header["value"] == "Bearer {agent_key}"
    assert header["isSecret"] is True and header["isRequired"] is True
    assert header["variables"]["agent_key"]["isSecret"] is True


def test_oauth_hint_names_the_protected_resource_metadata(store, monkeypatch):
    prm = "https://agents.example.com/.well-known/oauth-protected-resource/agent/mcp"
    monkeypatch.setattr(agent_server_json.settings, "agent_mcp_protected_resource_metadata_url", prm)
    document = _export(_create(store)["id"])
    _validate(document)
    assert _runtime(document)["auth"] == {"scheme": "oauth", "protectedResourceMetadata": prm}
    assert "headers" not in document["remotes"][0]


def test_runtime_url_never_carries_credentials(store, monkeypatch):
    monkeypatch.setattr(
        agent_server_json.settings,
        "agent_mcp_public_url",
        "https://user:pass@agents.example.com/agent/mcp?token=secret#x",
    )
    raw = client.get(f"{_BASE}/{_create(store)['id']}/server.json").text
    assert "pass" not in raw and "secret" not in raw
    assert json.loads(raw)["remotes"][0]["url"] == _RUNTIME_URL


@pytest.mark.parametrize("url", ["", "ftp://agents.example.com/agent/mcp", "not a url"])
def test_misconfigured_runtime_url_is_503(store, monkeypatch, url):
    toolset = _create(store)
    monkeypatch.setattr(agent_server_json.settings, "agent_mcp_public_url", url)
    for path in (f"{_BASE}/{toolset['id']}/server.json", _TENANT_WIDE):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "agent-runtime-url-invalid"


def test_title_falls_back_without_a_project_name(store, monkeypatch):
    monkeypatch.setattr(db, "get_project_by_id", lambda *_args, **_kw: None)
    monkeypatch.setattr(db, "get_project_core", lambda *_args, **_kw: None)
    document = _export(_create(store)["id"])
    assert document["title"] == "API 1.0.0 agent toolset"
    monkeypatch.setattr(
        db, "get_project_by_id", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    monkeypatch.setattr(
        db, "get_project_core", lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    assert _export(_create(store, label="2.0.0")["id"])["title"] == "API 2.0.0 agent toolset"


# ============================================================================
# Round trip through the MCP manifest importer
# ============================================================================
def test_import_back_yields_the_same_tools_and_fingerprint(store):
    toolset = _create(store)
    client.patch(
        f"{_BASE}/{toolset['id']}/tools/{_tool_id(toolset['id'], 'createPet')}",
        json={"enabled": True, "confirmWriteOp": True},
    )
    document = _export(toolset["id"])
    text = json.dumps(document)
    assert is_mcp_manifest(text)
    imported = parse_mcp_manifest(text, source_label="server.json")
    runtime = _runtime(document)
    assert [dict(tool) for tool in imported.tools] == runtime["manifest"]["tools"]
    assert {tool["name"] for tool in imported.tools} == {"listPets", "getPet", "createPet"}
    assert imported.server_info.name == document["name"]
    assert manifest_surface(imported).fingerprint() == runtime["digest"]


def test_only_agent_runtime_server_json_is_unwrapped():
    third_party = {"$schema": "x", "name": "io.github.x/y", "_meta": {"other/key": {"manifest": {}}}}
    assert embedded_server_json_manifest(third_party) is None
    assert embedded_server_json_manifest([1, 2]) is None
    assert not is_mcp_manifest(json.dumps(third_party))
    tenant_wide = build_tenant_server_json(tenant_slug="acme", toolsets=[], runtime_url=_RUNTIME_URL)
    assert embedded_server_json_manifest(tenant_wide) is None


# ============================================================================
# Digest stability
# ============================================================================
def test_digest_changes_with_curation_and_not_otherwise(store):
    toolset = _create(store)
    before = _runtime(_export(toolset["id"]))["digest"]

    # Not otherwise: a settings change outside curation, and a repeat export.
    client.patch(f"{_BASE}/{toolset['id']}", json={"target": "mock"})
    assert _runtime(_export(toolset["id"]))["digest"] == before

    # Disabling a tool is curation.
    tool_id = _tool_id(toolset["id"], "getPet")
    client.patch(f"{_BASE}/{toolset['id']}/tools/{tool_id}", json={"enabled": False})
    disabled = _runtime(_export(toolset["id"]))["digest"]
    assert disabled != before

    # Restoring the curation restores the digest.
    client.patch(f"{_BASE}/{toolset['id']}/tools/{tool_id}", json={"enabled": True})
    assert _runtime(_export(toolset["id"]))["digest"] == before


def test_digest_changes_when_an_accepted_description_is_served(store):
    toolset = _create(store)
    before = _runtime(_export(toolset["id"]))
    manifest = copy.deepcopy(before["manifest"])
    manifest["tools"][0]["description"] = "Lists the pets in the store."
    assert agent_server_json.manifest_digest(manifest) != before["digest"]
    manifest["tools"][0]["_meta"] = {"volatile": True}
    manifest["tools"][0]["description"] = before["manifest"]["tools"][0]["description"]
    assert agent_server_json.manifest_digest(manifest) == before["digest"]


def test_disabled_toolset_exports_no_tools_with_a_digest(store):
    toolset = _create(store)
    client.patch(f"{_BASE}/{toolset['id']}", json={"enabled": False})
    document = _export(toolset["id"])
    _validate(document)
    runtime = _runtime(document)
    assert (runtime["enabled"], runtime["toolCount"], runtime["manifest"]["tools"]) == (False, 0, [])
    assert len(runtime["digest"]) == 64
    assert document["description"].endswith("0 MCP tools.")


def test_export_is_byte_stable_with_an_etag(store):
    toolset = _create(store)
    first = client.get(f"{_BASE}/{toolset['id']}/server.json")
    second = client.get(f"{_BASE}/{toolset['id']}/server.json")
    assert first.content == second.content
    assert first.headers["etag"] == second.headers["etag"]
    assert first.headers["cache-control"] == "private, no-store"


# ============================================================================
# Tenant-wide export
# ============================================================================
def test_tenant_wide_lists_enabled_toolsets_ordered_by_id(store):
    first = _create(store, label="1.0.0")
    second = _create(store, label="2.0.0")
    off = _create(store, label="3.0.0")
    client.patch(f"{_BASE}/{off['id']}", json={"enabled": False})

    response = client.get(_TENANT_WIDE)
    assert response.status_code == 200
    document = response.json()
    _validate(document)
    assert document["name"] == runtime_server_name("acme") == "apiome.acme/agent-runtime"
    runtime = _runtime(document)
    ids = sorted([first["id"], second["id"]])
    assert [entry["toolsetId"] for entry in runtime["toolsets"]] == ids
    assert runtime["toolsetCount"] == 2 and runtime["unavailable"] == []
    entry = runtime["toolsets"][0]
    assert entry["name"] == toolset_server_name("acme", entry["toolsetId"])
    assert entry["digest"] == _runtime(_export(entry["toolsetId"]))["digest"]
    assert sorted(entry["tools"]) == ["getPet", "listPets"]
    assert document["version"] == f"1.0.0+{runtime['digest'][:12]}"
    assert [r["url"] for r in document["remotes"]] == [_RUNTIME_URL]
    assert client.get(_TENANT_WIDE).content == response.content


def test_tenant_wide_digest_moves_with_any_toolsets_curation(store):
    toolset = _create(store)
    _create(store, label="2.0.0")
    before = _runtime(client.get(_TENANT_WIDE).json())["digest"]
    client.patch(
        f"{_BASE}/{toolset['id']}/tools/{_tool_id(toolset['id'], 'getPet')}", json={"enabled": False}
    )
    assert _runtime(client.get(_TENANT_WIDE).json())["digest"] != before


def test_tenant_wide_lists_an_uncompilable_toolset_as_unavailable(store, monkeypatch):
    good = _create(store)
    bad = _create(store, label="2.0.0")
    real = agent_server_json.compile_agent_toolset

    def _compile(tenant_id: str, toolset_id: str):
        if toolset_id == bad["id"]:
            raise toolsets.AgentToolsetError(toolsets.CODE_TOOLSET_SOURCE_UNAVAILABLE, "gone")
        return real(tenant_id, toolset_id)

    monkeypatch.setattr(agent_server_json, "compile_agent_toolset", _compile)
    runtime = _runtime(client.get(_TENANT_WIDE).json())
    assert [entry["toolsetId"] for entry in runtime["toolsets"]] == [good["id"]]
    assert runtime["unavailable"] == [bad["id"]]


def test_tenant_wide_with_no_toolsets_is_still_valid(store):
    document = client.get(_TENANT_WIDE).json()
    _validate(document)
    assert _runtime(document)["toolsets"] == []
    assert document["description"].startswith("Apiome agent runtime for acme: 0 enabled toolsets")


# ============================================================================
# Routes: permissions and refusals
# ============================================================================
@pytest.mark.parametrize("path", ["/server.json", None])
def test_routes_require_api_keys_view(store, path):
    toolset = _create(store)
    url = f"{_BASE}/{toolset['id']}{path}" if path else _TENANT_WIDE
    with patch(
        "app.agent_toolset_routes.enforce_permission",
        side_effect=HTTPException(status_code=403, detail="forbidden"),
    ) as guard:
        response = client.get(url)
    assert response.status_code == 403
    _db, _auth_data, resource, action = guard.call_args.args
    assert (resource, action) == (Resource.API_KEYS, Action.VIEW)


def test_unknown_or_other_tenants_toolset_is_404(store):
    response = client.get(f"{_BASE}/{_MISSING}/server.json")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "agent-toolset-not-found"
    other = store.seed_version("22222222-2222-4222-8222-222222222222")
    app.dependency_overrides[validate_authentication] = lambda: {
        **_MOCK_AUTH,
        "tenant_id": "22222222-2222-4222-8222-222222222222",
    }
    foreign = client.post(_BASE, json={"versionId": other}).json()
    app.dependency_overrides[validate_authentication] = lambda: _MOCK_AUTH
    assert client.get(f"{_BASE}/{foreign['id']}/server.json").status_code == 404


def test_namespace_is_the_authenticated_tenant_not_the_url(store, monkeypatch):
    toolset = _create(store)
    response = client.get(f"/v1/tenants/somebody-else/agent-toolsets/{toolset['id']}/server.json")
    assert response.json()["name"].startswith("apiome.acme/")
    monkeypatch.setattr(db, "get_tenant_slug_by_id", lambda _tenant_id: None)
    fallback = client.get(f"/v1/tenants/url-slug/agent-toolsets/{toolset['id']}/server.json")
    assert fallback.json()["name"].startswith("apiome.url-slug/")


def test_server_names_match_the_schema_pattern():
    names: List[str] = [
        toolset_server_name("acme corp", _MISSING),
        runtime_server_name("acme_corp!"),
    ]
    name_schema = definition_schema("ServerDetail")["definitions"]["ServerDetail"]["properties"]["name"]
    for name in names:
        jsonschema.validate(name, name_schema)
