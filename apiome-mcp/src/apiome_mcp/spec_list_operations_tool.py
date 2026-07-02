"""MCP ``spec.list_operations`` tool: operation index without full OpenAPI doc (#3018)."""

from __future__ import annotations

from typing import Any

from psycopg_pool import AsyncConnectionPool

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.spec_get_openapi_tool import build_spec_get_openapi_response

# OpenAPI 3.x path item operation keys (exclude summary/description/parameters/servers/$ref).
_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def sorted_operations_from_openapi(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Build ``[{path, method, operation_id, summary, tags}, …]`` sorted by path then method."""
    paths_raw = spec.get("paths")
    paths: dict[str, Any] = paths_raw if isinstance(paths_raw, dict) else {}
    rows: list[dict[str, Any]] = []

    for path_str in sorted(paths.keys()):
        item = paths[path_str]
        if not isinstance(item, dict):
            continue
        for method in sorted(k for k in item if k in _HTTP_METHODS):
            op = item[method]
            if not isinstance(op, dict):
                continue
            oid = op.get("operationId")
            summary = op.get("summary")
            tags_raw = op.get("tags")
            if tags_raw is None:
                tags: list[str] = []
            elif isinstance(tags_raw, list):
                tags = [str(t) for t in tags_raw]
            else:
                tags = []

            rows.append(
                {
                    "path": path_str,
                    "method": method,
                    "operation_id": str(oid) if oid is not None else None,
                    "summary": str(summary) if summary is not None else None,
                    "tags": tags,
                }
            )

    return rows


async def build_spec_list_operations_response(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    auth_ctx: McpAuthContext | None = None,
) -> list[dict[str, Any]]:
    """Return sorted operation rows for ``spec_id``, or raise like ``spec.get_openapi``."""
    spec = await build_spec_get_openapi_response(
        pool,
        spec_id=spec_id,
        auth_ctx=auth_ctx,
        apply_json_payload_cap=False,
        private_access_audit_tool="spec.list_operations",
    )
    return sorted_operations_from_openapi(spec)
