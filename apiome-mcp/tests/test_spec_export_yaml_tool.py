from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
import yaml
from fastmcp.exceptions import NotFoundError, ToolError
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.spec_export_yaml_tool import build_spec_export_yaml_response


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


def _mock_pool_with_row(row: dict[str, object] | None) -> MagicMock:
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
    return pool


def test_build_spec_export_yaml_success_round_trips_json() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    sample_spec = {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
    }

    pool = _mock_pool_with_row(row)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=sample_spec),
        patch("apiome_mcp.spec_export_yaml_tool.get_settings") as gs,
    ):
        gs.return_value.openapi_max_json_bytes = 1_000_000

        async def run() -> dict[str, str]:
            return await build_spec_export_yaml_response(pool, spec_id=str(sid))

        out = asyncio.run(run())

    assert "openapi_yaml" in out
    parsed = yaml.safe_load(out["openapi_yaml"])
    assert parsed == sample_spec
    assert json.loads(json.dumps(parsed)) == sample_spec


def test_build_spec_export_yaml_private_audited() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid, visibility="private")
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000099",
        tenant_id=str(uuid4()),
        label="k",
        scope=Scope(),
    )
    sample_spec = {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
    }

    pool = _mock_pool_with_row(row)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=sample_spec),
        patch("apiome_mcp.spec_export_yaml_tool.get_settings") as gs,
        patch("apiome_mcp.spec_get_openapi_tool.schedule_mcp_private_access_audit") as audit,
    ):
        gs.return_value.openapi_max_json_bytes = 1_000_000

        async def run() -> dict[str, str]:
            return await build_spec_export_yaml_response(pool, spec_id=str(sid), auth_ctx=auth)

        asyncio.run(run())

    audit.assert_called_once()
    assert audit.call_args.kwargs["tool"] == "spec.export_yaml"


def test_build_spec_export_yaml_payload_too_large() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    huge = {"openapi": "3.1.0", "x": "y" * 500_000}

    pool = _mock_pool_with_row(row)

    async def fake_fetch(_conn: object, _revision_id: UUID) -> tuple:
        return ([], {}, [], [], [])

    with (
        patch("apiome_mcp.spec_get_openapi_tool.fetch_openapi_generation_inputs_async", side_effect=fake_fetch),
        patch("apiome_mcp.spec_get_openapi_tool.generate_openapi_spec", return_value=huge),
        patch("apiome_mcp.spec_export_yaml_tool.get_settings") as gs,
    ):
        gs.return_value.openapi_max_json_bytes = 100

        async def run() -> None:
            await build_spec_export_yaml_response(pool, spec_id=str(sid))

        with pytest.raises(ToolError, match="413"):
            asyncio.run(run())


def test_build_spec_export_yaml_not_found() -> None:
    pool = _mock_pool_with_row(None)

    async def run() -> None:
        await build_spec_export_yaml_response(pool, spec_id=str(uuid4()))

    with pytest.raises(NotFoundError, match="Unknown or non-public"):
        asyncio.run(run())


def test_spec_export_yaml_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.export_yaml")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.export_yaml"
