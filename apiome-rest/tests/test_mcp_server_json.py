"""``server.json`` normalization and the registry metadata an imported endpoint records —
V2-MCP-26.2 (#3708)."""

from __future__ import annotations

from app.mcp_server_json import (
    camelize_key,
    normalize_server_json,
    registry_metadata,
    remote_headers,
)
from app.models import mcp_endpoint_out_from_row


def test_camelize_key() -> None:
    assert camelize_key("website_url") == "websiteUrl"
    assert camelize_key("is_latest") == "isLatest"
    assert camelize_key("websiteUrl") == "websiteUrl"
    assert camelize_key("io.modelcontextprotocol.registry/official") == "io.modelcontextprotocol.registry/official"
    assert camelize_key("name") == "name"


def test_a_current_draft_document_is_unchanged() -> None:
    doc = {
        "name": "io.github.acme/x",
        "version": "1.0.0",
        "websiteUrl": "https://acme.test",
        "remotes": [{"type": "sse", "url": "https://x.test/sse", "headers": [{"name": "A", "isRequired": True}]}],
        "packages": [{"registryType": "npm", "identifier": "@acme/x"}],
        "_meta": {"io.modelcontextprotocol.registry/publisher-provided": {"some_key": 1}},
    }
    normalized = normalize_server_json(doc)
    assert {k: v for k, v in normalized.items() if k != "_meta"} == {k: v for k, v in doc.items() if k != "_meta"}
    assert "io.modelcontextprotocol.registry/publisher-provided" in normalized["_meta"]


def test_the_snake_case_draft_is_read_as_the_current_one() -> None:
    legacy = {
        "name": "io.github.acme/x",
        "version_detail": {"version": "0.2.0", "release_date": "2025-07-01"},
        "website_url": "https://acme.test",
        "remotes": [
            {
                "transport_type": "streamable-http",
                "url": "https://x.test/mcp",
                "headers": [{"name": "A", "is_secret": True}],
            }
        ],
        "packages": [{"registry_name": "pypi", "name": "acme-x", "version": "0.2.0", "runtime_hint": "uvx"}],
    }
    doc = normalize_server_json(legacy)
    assert doc["version"] == "0.2.0" and "versionDetail" not in doc
    assert doc["websiteUrl"] == "https://acme.test"
    assert doc["remotes"] == [
        {"type": "streamable-http", "url": "https://x.test/mcp", "headers": [{"name": "A", "isSecret": True}]}
    ]
    assert doc["packages"] == [
        {"registryType": "pypi", "identifier": "acme-x", "version": "0.2.0", "runtimeHint": "uvx"}
    ]
    assert legacy["website_url"] == "https://acme.test"  # the input is not modified


def test_a_camel_case_twin_wins_over_its_snake_case_spelling() -> None:
    doc = normalize_server_json({"name": "x", "website_url": "https://old.test", "websiteUrl": "https://new.test"})
    assert doc["websiteUrl"] == "https://new.test" and "website_url" not in doc
    doc = normalize_server_json({"name": "x", "version": "2.0.0", "version_detail": {"version": "1.0.0"}})
    assert doc["version"] == "2.0.0"


def test_remote_headers_never_keep_a_secret_value() -> None:
    headers = remote_headers(
        {
            "headers": [
                {"name": "Authorization", "isSecret": True, "isRequired": True, "value": "Bearer abc", "default": "x"},
                {"name": "X-Tenant", "value": "{tenant_id}", "description": "  your tenant  "},
                {"name": "X-Empty-Secret", "isSecret": True},
                {"description": "nameless"},
            ]
        }
    )
    assert headers == [
        {"name": "Authorization", "isRequired": True, "isSecret": True, "hasValue": True},
        {
            "name": "X-Tenant",
            "isRequired": False,
            "isSecret": False,
            "description": "your tenant",
            "value": "{tenant_id}",
        },
        {"name": "X-Empty-Secret", "isRequired": False, "isSecret": True, "hasValue": False},
    ]


def test_registry_metadata_is_credential_free_and_compact() -> None:
    server = {
        "name": "io.github.acme/x",
        "version": "1.2.0",
        "websiteUrl": "https://user:pw@acme.test/docs?token=t",
        "remotes": [
            {"type": "sse", "url": "https://other.test/sse"},
            {"type": "streamable-http", "url": "https://x.test/mcp", "headers": [{"name": "A"}]},
        ],
    }
    metadata = registry_metadata(
        server,
        {"status": "Deprecated"},
        registry_url="https://registry.test",
        transport="streamable_http",
        url="https://x.test/mcp",
    )
    assert metadata == {
        "registryUrl": "https://registry.test",
        "serverName": "io.github.acme/x",
        "version": "1.2.0",
        "websiteUrl": "https://acme.test/docs",
        "status": "deprecated",
        "remote": {
            "type": "streamable-http",
            "url": "https://x.test/mcp",
            "headers": [{"name": "A", "isRequired": False, "isSecret": False}],
        },
    }


def test_the_endpoint_response_carries_registry_metadata() -> None:
    row = {
        "id": "e1",
        "tenant_id": "t1",
        "name": "X",
        "slug": "x",
        "endpoint_url": "https://x.test/mcp",
        "transport": "streamable_http",
        "visibility": "private",
        "added_via": "registry",
        "registry_metadata": {"serverName": "io.github.acme/x", "version": "1.2.0"},
    }
    out = mcp_endpoint_out_from_row(row)
    assert out.registry_metadata == {"serverName": "io.github.acme/x", "version": "1.2.0"}
    assert mcp_endpoint_out_from_row({**row, "registry_metadata": None}).registry_metadata is None
