from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastmcp.exceptions import NotFoundError
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.spec_list_components_tool import (
    build_spec_list_components_response,
    grouped_components_from_openapi,
)


def _spec_with_components() -> dict[str, object]:
    return {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {"Pet": {"type": "object"}, "User": {"type": "object"}},
            "parameters": {"limitParam": {"name": "limit", "in": "query"}},
            "responses": {"NotFound": {"description": "missing"}},
            "securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}},
            "headers": {"X-Trace": {"schema": {"type": "string"}}},
        },
    }


def _spec_partial_components() -> dict[str, object]:
    """Only schemas; headers present but not in MCP grouping."""
    return {
        "openapi": "3.1.0",
        "paths": {},
        "components": {
            "schemas": {"Z": {}, "A": {}},
            "headers": {"H": {}},
        },
    }


def test_grouped_components_full_spec_order_and_sort() -> None:
    out = grouped_components_from_openapi(_spec_with_components())
    assert list(out.keys()) == ["schemas", "parameters", "responses", "securitySchemes"]
    assert out["schemas"] == ["Pet", "User"]
    assert out["parameters"] == ["limitParam"]
    assert out["responses"] == ["NotFound"]
    assert out["securitySchemes"] == ["bearer"]
    assert "headers" not in out


def test_grouped_components_omits_empty_kinds() -> None:
    out = grouped_components_from_openapi(_spec_partial_components())
    assert out == {"schemas": ["A", "Z"]}


def test_grouped_components_missing_or_malformed() -> None:
    assert grouped_components_from_openapi({}) == {}
    assert grouped_components_from_openapi({"components": None}) == {}
    assert grouped_components_from_openapi({"components": "bad"}) == {}
    assert grouped_components_from_openapi({"components": {"schemas": None}}) == {}
    assert grouped_components_from_openapi({"components": {"schemas": {}}}) == {}


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


def test_build_spec_list_components_success() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    sample_spec = _spec_with_components()

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

        async def run() -> dict[str, list[str]]:
            return await build_spec_list_components_response(pool, spec_id=str(sid))

        out = asyncio.run(run())

    assert out["schemas"] == ["Pet", "User"]
    assert out["securitySchemes"] == ["bearer"]


def test_build_spec_list_components_not_found() -> None:
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
        await build_spec_list_components_response(pool, spec_id=str(uuid4()))

    with pytest.raises(NotFoundError, match="Unknown or non-public"):
        asyncio.run(run())


def test_build_spec_list_components_private_audited() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid, visibility="private")
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000099",
        tenant_id=str(uuid4()),
        label="k",
        scope=Scope(),
    )

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
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=_spec_partial_components()),
        patch("apiome_mcp.spec_get_openapi_tool.schedule_mcp_private_access_audit") as audit,
    ):

        async def run() -> None:
            await build_spec_list_components_response(pool, spec_id=str(sid), auth_ctx=auth)

        asyncio.run(run())

    audit.assert_called_once()
    assert audit.call_args.kwargs["tool"] == "spec.list_components"


def test_build_spec_list_components_allows_oversize_openapi_payload() -> None:
    """Component index skips JSON byte cap that would block spec.get_openapi."""
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    huge = {
        "openapi": "3.1.0",
        "paths": {},
        "components": {"schemas": {"S": {"type": "string"}}},
        "x": "y" * 500_000,
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

        async def run() -> dict[str, list[str]]:
            return await build_spec_list_components_response(pool, spec_id=str(sid))

        out = asyncio.run(run())

    assert out == {"schemas": ["S"]}


def test_spec_list_components_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.list_components")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.list_components"
