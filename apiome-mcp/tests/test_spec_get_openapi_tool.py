from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastmcp.exceptions import NotFoundError, ToolError
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.spec_get_openapi_tool import build_spec_get_openapi_response


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


def test_build_spec_get_openapi_success() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    sample_spec = {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
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
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
    ):
        gs.return_value.openapi_max_json_bytes = 1_000_000

        async def run() -> dict[str, object]:
            return await build_spec_get_openapi_response(pool, spec_id=str(sid))

        out = asyncio.run(run())

    assert out == sample_spec


def test_build_spec_get_openapi_not_found() -> None:
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
        await build_spec_get_openapi_response(pool, spec_id=str(uuid4()))

    with pytest.raises(NotFoundError, match="Unknown or non-public"):
        asyncio.run(run())


def test_build_spec_get_openapi_payload_too_large() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    huge = {"openapi": "3.1.0", "x": "y" * 500_000}

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

        async def run() -> None:
            await build_spec_get_openapi_response(pool, spec_id=str(sid))

        with pytest.raises(ToolError, match="413"):
            asyncio.run(run())


def test_build_spec_get_openapi_private_audited() -> None:
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
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
        patch("apiome_mcp.spec_get_openapi_tool.schedule_mcp_private_access_audit") as audit,
    ):
        gs.return_value.openapi_max_json_bytes = 1_000_000

        async def run() -> None:
            await build_spec_get_openapi_response(pool, spec_id=str(sid), auth_ctx=auth)

        asyncio.run(run())

    audit.assert_called_once()
    assert audit.call_args.kwargs["tool"] == "spec.get_openapi"


def test_build_spec_get_openapi_private_audited_custom_tool_name() -> None:
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
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
        patch("apiome_mcp.spec_get_openapi_tool.schedule_mcp_private_access_audit") as audit,
    ):
        gs.return_value.openapi_max_json_bytes = 1_000_000

        async def run() -> None:
            await build_spec_get_openapi_response(
                pool,
                spec_id=str(sid),
                auth_ctx=auth,
                private_access_audit_tool="spec.export_yaml",
            )

        asyncio.run(run())

    audit.assert_called_once()
    assert audit.call_args.kwargs["tool"] == "spec.export_yaml"


def test_build_spec_get_openapi_returns_valid_json_shape() -> None:
    sid = uuid4()
    row = _openapi_row(spec_id=sid)
    sample_spec = {
        "openapi": "3.1.0",
        "info": {"title": "payments API", "version": "2.1.0", "description": "d"},
        "paths": {"/items": {"get": {"responses": {"200": {"description": "ok"}}}}},
        "components": {"schemas": {"Widget": {"type": "object"}}},
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
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
    ):
        gs.return_value.openapi_max_json_bytes = 1_000_000

        async def run() -> dict[str, object]:
            return await build_spec_get_openapi_response(pool, spec_id=str(sid))

        out = asyncio.run(run())

    raw = json.dumps(out)
    parsed = json.loads(raw)
    assert parsed["openapi"] == "3.1.0"
    assert "components" in parsed


def test_build_spec_get_openapi_deny_all_raises_without_query() -> None:
    pool = MagicMock(spec=AsyncConnectionPool)
    pool.connection = MagicMock()

    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000001",
        tenant_id=str(uuid4()),
        label="x",
        scope=Scope(deny_all=True),
    )

    async def run() -> None:
        await build_spec_get_openapi_response(pool, spec_id=str(uuid4()), auth_ctx=auth)

    with pytest.raises(NotFoundError, match="Unknown or non-public"):
        asyncio.run(run())
    pool.connection.assert_not_called()


def test_build_spec_get_openapi_authenticated_merged_sql() -> None:
    sid = uuid4()
    tid = uuid4()
    auth = McpAuthContext(
        key_id="00000000-0000-4000-8000-000000000002",
        tenant_id=str(tid),
        label="k",
        scope=Scope(),
    )
    row = _openapi_row(spec_id=sid)
    sample_spec = {
        "openapi": "3.1.0",
        "info": {"title": "x", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
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
        patch("apiome_mcp.spec_get_openapi_tool.get_settings") as gs,
    ):
        gs.return_value.openapi_max_json_bytes = 1_000_000

        async def run() -> dict[str, object]:
            return await build_spec_get_openapi_response(pool, spec_id=str(sid), auth_ctx=auth)

        out = asyncio.run(run())

    assert out == sample_spec

    sql, params = describe_cur.execute.await_args.args
    assert "UNION ALL" in sql
    assert "mcp_v_public_specs" in sql
    assert "visibility = 'private'" in sql
    assert "spec_visibility" in sql
    assert isinstance(params, tuple)
    assert params[0] == sid
    assert params[1] == sid
    assert params[2] == str(auth.tenant_id)


def test_spec_get_openapi_tool_registered_on_mcp() -> None:
    from apiome_mcp.server import mcp

    async def load() -> object:
        return await mcp.get_tool("spec.get_openapi")

    tool = asyncio.run(load())
    assert tool is not None
    assert tool.name == "spec.get_openapi"
