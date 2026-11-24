"""MCP ``spec.list_components`` tool: component names grouped by OpenAPI kind (#3020)."""

from __future__ import annotations

from typing import Any

from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.spec_get_openapi_tool import build_spec_part_response

# OpenAPI ``components`` kinds exposed by MCP list/describe tools (subset of the spec).
MCP_COMPONENT_KINDS: tuple[str, ...] = ("schemas", "parameters", "responses", "securitySchemes")


def grouped_components_from_openapi(spec: dict[str, Any]) -> dict[str, list[str]]:
    """Return ``{kind: [name, …], …}`` with stable kind order and sorted names; omit empty kinds."""
    components_raw = spec.get("components")
    if not isinstance(components_raw, dict):
        return {}

    out: dict[str, list[str]] = {}
    for kind in MCP_COMPONENT_KINDS:
        section = components_raw.get(kind)
        if not isinstance(section, dict) or not section:
            continue
        names = sorted(str(k) for k in section.keys())
        if names:
            out[kind] = names
    return out


async def build_spec_list_components_response(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    auth_ctx: McpAuthContext | None = None,
) -> dict[str, list[str]]:
    """Return grouped component names for ``spec_id``, or raise like ``spec.get_openapi``.

    Reads the classes, properties, security schemes and component pins only (four statements; none
    when the names or the full document of the unchanged revision are cached) — DBP-1.22.
    """
    names: dict[str, list[str]] = await build_spec_part_response(
        pool,
        spec_id=spec_id,
        part="components",
        derive=grouped_components_from_openapi,
        auth_ctx=auth_ctx,
        private_access_audit_tool="spec.list_components",
    )
    return names
