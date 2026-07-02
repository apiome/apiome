"""MCP ``spec.describe_component`` tool: one components.* entry with resolved refs (#3021)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastmcp.exceptions import NotFoundError
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.spec_describe_operation_tool import resolve_openapi_refs
from apiome_mcp.spec_get_openapi_tool import build_spec_get_openapi_response
from apiome_mcp.spec_list_components_tool import MCP_COMPONENT_KINDS


def extract_resolved_component(spec: dict[str, Any], kind: str, name: str) -> Any | None:
    """Return the component object for ``kind`` / ``name`` with internal ``#/…`` refs expanded, or None."""
    k = str(kind).strip()
    n = str(name).strip()
    if not n or k not in MCP_COMPONENT_KINDS:
        return None

    components_raw = spec.get("components")
    if not isinstance(components_raw, dict):
        return None

    section = components_raw.get(k)
    if not isinstance(section, dict):
        return None

    raw = section.get(n)
    if raw is None:
        return None

    return resolve_openapi_refs(spec, deepcopy(raw), frozenset())


async def build_spec_describe_component_response(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    kind: str,
    name: str,
    auth_ctx: McpAuthContext | None = None,
) -> Any:
    """Return resolved component definition for ``spec_id`` / ``kind`` / ``name``, or raise ``NotFoundError``."""
    spec = await build_spec_get_openapi_response(
        pool,
        spec_id=spec_id,
        auth_ctx=auth_ctx,
        apply_json_payload_cap=False,
        private_access_audit_tool="spec.describe_component",
    )
    resolved = extract_resolved_component(spec, kind=str(kind), name=str(name))
    if resolved is None:
        raise NotFoundError("Unknown component kind or name for this spec.")
    return resolved
