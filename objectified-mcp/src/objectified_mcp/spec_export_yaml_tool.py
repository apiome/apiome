"""MCP ``spec.export_yaml`` tool: full generated OpenAPI 3.1 as YAML (#3017)."""

from __future__ import annotations

import yaml
from fastmcp.exceptions import ToolError
from psycopg_pool import AsyncConnectionPool

from objectified_mcp.mcp_auth import McpAuthContext
from objectified_mcp.settings import get_settings
from objectified_mcp.spec_get_openapi_tool import build_spec_get_openapi_response


async def build_spec_export_yaml_response(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    auth_ctx: McpAuthContext | None = None,
) -> dict[str, str]:
    """Return ``openapi_yaml`` text for ``spec_id``, or raise ``NotFoundError`` / ``ToolError``."""
    spec = await build_spec_get_openapi_response(
        pool,
        spec_id=spec_id,
        auth_ctx=auth_ctx,
        apply_json_payload_cap=False,
        private_access_audit_tool="spec.export_yaml",
    )
    text = yaml.dump(spec, sort_keys=False, default_flow_style=False)
    settings = get_settings()
    encoded = text.encode("utf-8")
    if len(encoded) > settings.openapi_max_json_bytes:
        raise ToolError(
            f"OpenAPI YAML exceeds server limit ({settings.openapi_max_json_bytes} bytes); "
            "this condition corresponds to HTTP 413 Payload Too Large."
        )
    return {"openapi_yaml": text}
