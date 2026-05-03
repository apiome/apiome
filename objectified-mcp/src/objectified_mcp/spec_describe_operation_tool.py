"""MCP ``spec.describe_operation`` tool: operation fragments with resolved refs (#3019)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from fastmcp.exceptions import NotFoundError
from psycopg_pool import AsyncConnectionPool

from objectified_mcp.mcp_auth import McpAuthContext
from objectified_mcp.spec_get_openapi_tool import build_spec_get_openapi_response

_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


def _json_pointer_follow(root: dict[str, Any], pointer: str) -> Any | None:
    """Resolve an OpenAPI internal fragment pointer ``#/a/b`` against ``root``."""
    if not pointer.startswith("#/"):
        return None
    node: Any = root
    for raw in pointer[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = node.get(key)
        elif isinstance(node, list):
            try:
                idx = int(key)
            except ValueError:
                return None
            if idx < 0 or idx >= len(node):
                return None
            node = node[idx]
        else:
            return None
    return node


def resolve_openapi_refs(root: dict[str, Any], node: Any, stack: frozenset[str]) -> Any:
    """Recursively resolve document-internal ``#/…`` ``$ref`` values; leave external refs unchanged.

    Sibling fields alongside a ``$ref`` (valid in OAS 3.1 / JSON Schema) are merged into the resolved
    target, with the sibling values taking precedence over same-named target fields.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            if ref in stack:
                return {"$ref": ref}
            target = _json_pointer_follow(root, ref)
            if target is None:
                return deepcopy(node)
            new_stack = frozenset({*stack, ref})
            resolved = resolve_openapi_refs(root, deepcopy(target), new_stack)
            siblings = {
                k: resolve_openapi_refs(root, deepcopy(v), new_stack)
                for k, v in node.items()
                if k != "$ref"
            }
            if siblings and isinstance(resolved, dict):
                return {**resolved, **siblings}
            return resolved
        return {k: resolve_openapi_refs(root, v, stack) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_openapi_refs(root, item, stack) for item in node]
    return node


def _follow_path_item_ref(spec: dict[str, Any], raw: Any, stack: frozenset[str]) -> dict[str, Any] | None:
    """Expand path-item reference chain (``$ref`` only); return a path-item dict or None."""
    cur: Any = raw
    while isinstance(cur, dict) and "$ref" in cur:
        ref = cur.get("$ref")
        if not isinstance(ref, str) or not ref.startswith("#/"):
            return None
        if ref in stack:
            return None
        nxt = _json_pointer_follow(spec, ref)
        if not isinstance(nxt, dict):
            return None
        cur = nxt
        stack = frozenset({*stack, ref})
    return cur if isinstance(cur, dict) else None


def merge_path_and_operation_parameters(path_item: dict[str, Any], operation: dict[str, Any]) -> list[Any]:
    """Merge OpenAPI path-item and operation ``parameters`` (operation wins same ``name`` + ``in``)."""
    pp = path_item.get("parameters")
    op = operation.get("parameters")
    path_list = pp if isinstance(pp, list) else []
    op_list = op if isinstance(op, list) else []
    combined: list[Any] = [*path_list, *op_list]

    seen: dict[tuple[str, str], int] = {}
    out: list[Any] = []
    for p in combined:
        if not isinstance(p, dict):
            out.append(p)
            continue
        name, inn = p.get("name"), p.get("in")
        if isinstance(name, str) and isinstance(inn, str):
            key = (name, inn)
            if key in seen:
                out[seen[key]] = p
            else:
                seen[key] = len(out)
                out.append(p)
        else:
            out.append(p)
    return out


def extract_operation_detail(spec: dict[str, Any], path: str, method: str) -> dict[str, Any] | None:
    """Return merged parameters, requestBody, responses, and security for ``path`` / ``method``, or None."""
    m = method.strip().lower()
    if m not in _HTTP_METHODS:
        return None

    paths_raw = spec.get("paths")
    if not isinstance(paths_raw, dict):
        return None

    path_item = _follow_path_item_ref(spec, paths_raw.get(path), frozenset())
    if path_item is None:
        return None

    op_raw = path_item.get(m)
    operation = resolve_openapi_refs(spec, op_raw, frozenset())
    if not isinstance(operation, dict):
        return None

    # Expand $ref values in path-item parameters before the (name, in) dedup merge so that
    # operation-level parameters correctly override path-level $ref parameters.
    path_item_params_raw = path_item.get("parameters")
    path_item_params_expanded = resolve_openapi_refs(
        spec,
        path_item_params_raw if isinstance(path_item_params_raw, list) else [],
        frozenset(),
    )
    path_item_for_merge = {**path_item, "parameters": path_item_params_expanded}
    parameters = merge_path_and_operation_parameters(path_item_for_merge, operation)
    # operation params inside `operation` are already resolved; re-running is a harmless no-op.
    parameters_resolved = resolve_openapi_refs(spec, parameters, frozenset())

    request_body = operation.get("requestBody")
    responses = operation.get("responses")
    if "security" in operation:
        sec_raw = operation.get("security")
    else:
        sec_raw = spec.get("security")

    return {
        "parameters": parameters_resolved,
        "requestBody": resolve_openapi_refs(spec, request_body, frozenset()) if request_body is not None else None,
        "responses": resolve_openapi_refs(spec, responses, frozenset()) if responses is not None else None,
        "security": resolve_openapi_refs(spec, sec_raw, frozenset()) if sec_raw is not None else None,
    }


async def build_spec_describe_operation_response(
    pool: AsyncConnectionPool,
    *,
    spec_id: str,
    path: str,
    method: str,
    auth_ctx: McpAuthContext | None = None,
) -> dict[str, Any]:
    """Return operation fragments for ``spec_id`` / ``path`` / ``method``, or raise ``NotFoundError``."""
    spec = await build_spec_get_openapi_response(
        pool,
        spec_id=spec_id,
        auth_ctx=auth_ctx,
        apply_json_payload_cap=False,
        private_access_audit_tool="spec.describe_operation",
    )
    detail = extract_operation_detail(spec, path=str(path), method=str(method))
    if detail is None:
        raise NotFoundError("Unknown path or method for this spec.")
    return detail
