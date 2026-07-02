from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastmcp.exceptions import NotFoundError
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.spec_describe_component_tool import (
    build_spec_describe_component_response,
    extract_resolved_component,
)


def test_extract_resolved_component_plain_schema() -> None:
    spec: dict[str, object] = {
        "openapi": "3.1.0",
        "components": {"schemas": {"Pet": {"type": "object", "properties": {"id": {"type": "string"}}}}},
    }
    out = extract_resolved_component(spec, "schemas", "Pet")
    assert out == {"type": "object", "properties": {"id": {"type": "string"}}}


def test_extract_resolved_component_expands_internal_ref() -> None:
    spec: dict[str, object] = {
        "openapi": "3.1.0",
        "components": {
            "schemas": {
                "Base": {"type": "object", "properties": {"id": {"type": "string"}}},
                "Pet": {"$ref": "#/components/schemas/Base", "description": "pet"},
            }
        },
    }
    out = extract_resolved_component(spec, "schemas", "Pet")
    assert isinstance(out, dict)
    assert out["type"] == "object"
    assert out["description"] == "pet"
    assert out["properties"]["id"]["type"] == "string"


def test_extract_resolved_component_unknown_kind() -> None:
    spec: dict[str, object] = {
        "openapi": "3.1.0",
        "components": {"headers": {"X": {"schema": {"type": "string"}}}},
    }
    assert extract_resolved_component(spec, "headers", "X") is None


def test_extract_resolved_component_unknown_name_or_empty() -> None:
    spec: dict[str, object] = {
        "openapi": "3.1.0",
        "components": {"schemas": {"A": {"type": "string"}}},
    }
    assert extract_resolved_component(spec, "schemas", "Missing") is None
    assert extract_resolved_component(spec, "schemas", "  ") is None


def test_extract_resolved_component_missing_components() -> None:
    assert extract_resolved_component({"openapi": "3.1.0"}, "schemas", "X") is None


def _openapi_row(*, spec_id: UUID | None = None, visibility: str = "public") -> dict[str, object]:
    sid = spec_id or uuid4()
    return {
        "id": sid,
        "tenant_slug": "acme",
        "project_slug": "payments",
        "version_label": "2.1.0",
        "project_description": "Payments service",
        "metadata": None,
        "spec_visibility": visibility,
    }


def test_build_spec_describe_component_success() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    sample_spec: dict[str, object] = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "responses": {"Ok": {"description": "fine"}},
            "schemas": {"User": {"$ref": "#/components/schemas/Base", "nullable": True}, "Base": {"type": "object"}},
        },
    }

    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=row)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=sample_spec),
    ):

        async def run() -> object:
            return await build_spec_describe_component_response(pool, spec_id=str(sid), kind="schemas", name="User")

        out = asyncio.run(run())

    assert isinstance(out, dict)
    assert out["type"] == "object"
    assert out["nullable"] is True


def test_build_spec_describe_component_not_found_revision() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=None)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def run() -> None:
        await build_spec_describe_component_response(pool, spec_id=str(uuid4()), kind="schemas", name="X")

    with pytest.raises(NotFoundError, match="Unknown or non-public"):
        asyncio.run(run())


def test_build_spec_describe_component_unknown_component() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    sample_spec: dict[str, object] = {
        "openapi": "3.1.0",
        "components": {"schemas": {"Only": {"type": "string"}}},
    }

    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=row)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=sample_spec),
    ):

        async def run() -> None:
            await build_spec_describe_component_response(pool, spec_id=str(sid), kind="schemas", name="Nope")

        with pytest.raises(NotFoundError, match="Unknown component kind or name"):
            asyncio.run(run())


def test_build_spec_describe_component_private_audited() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid, visibility="private")
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000099",
        tenant_id=str(uuid4()),
        label="k",
        scope=Scope(),
    )
    sample_spec: dict[str, object] = {
        "openapi": "3.1.0",
        "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
    }

    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=row)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=sample_spec),
        patch("apiome_mcp.spec_get_openapi_tool.schedule_mcp_private_access_audit") as audit,
    ):

        async def run() -> None:
            await build_spec_describe_component_response(
                pool, spec_id=str(sid), kind="securitySchemes", name="bearer", auth_ctx=auth
            )

        asyncio.run(run())

    audit.assert_called_once()
    assert audit.call_args.kwargs["tool"] == "spec.describe_component"


def test_build_spec_describe_component_allows_oversize_openapi_payload() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    huge = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {"parameters": {"p": {"name": "q", "in": "query"}}},
        "x-padding": "z" * 500_000,
    }

    pool = MagicMock(spec=AsyncConnectionPool)
    describe_cur = MagicMock()
    describe_cur.execute = AsyncMock()
    describe_cur.fetchone = AsyncMock(return_value=row)
    describe_cm = AsyncMock()
    describe_cm.__aenter__.return_value = describe_cur
    describe_cm.__aexit__.return_value = None
    conn = MagicMock()
    conn.cursor = MagicMock(return_value=describe_cm)
    conn_cm = AsyncMock()
    conn_cm.__aenter__.return_value = conn
    conn_cm.__aexit__.return_value = None
    pool.connection = MagicMock(return_value=conn_cm)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=huge),
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
    ):
        gs.return_value.openapi_max_json_bytes = 100

        async def run() -> object:
            return await build_spec_describe_component_response(pool, spec_id=str(sid), kind="parameters", name="p")

        out = asyncio.run(run())

    assert out == {"name": "q", "in": "query"}


def test_spec_describe_component_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.describe_component")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.describe_component"
