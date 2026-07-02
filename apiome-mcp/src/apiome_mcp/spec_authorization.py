"""Combine MCP API key scope with version visibility for spec reads (#3010).

Public revisions are readable when the key's :class:`~apiome_mcp.scope.Scope`
allows the resource tenant/project. Private revisions additionally require the
spec's tenant to match the authenticated key's ``tenant_id`` (no cross-tenant
private reads, even if scope lists foreign projects).

SQL helpers emit a parameterized predicate suitable for ``WHERE`` clauses; keep
them aligned with :func:`authorize_spec`.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope

_SQL_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*$")


def _validate_qualified_identifier(name: str, *, role: str) -> str:
    if not _SQL_IDENT_RE.fullmatch(name):
        raise ValueError(f"Invalid SQL identifier for {role}: {name!r}")
    return name


def _normalize_visibility(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    if s in ("public", "private"):
        return s
    return None


def _as_scope_key(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw)


def authorize_spec(auth_ctx: McpAuthContext, spec_row: Mapping[str, Any]) -> bool:
    """Return True if *auth_ctx* may read the spec described by *spec_row*.

    *spec_row* must expose ``tenant_id``, ``project_id``, and ``visibility``
    (as returned from Postgres / MCP views). Unknown visibility values are
    denied.
    """
    visibility = _normalize_visibility(spec_row.get("visibility"))
    if visibility is None:
        return False

    tenant_id = _as_scope_key(spec_row.get("tenant_id"))
    project_id = _as_scope_key(spec_row.get("project_id"))

    if not auth_ctx.scope.allows(tenant_id, project_id):
        return False

    if visibility == "public":
        return True

    return tenant_id == str(auth_ctx.tenant_id)


def _scope_predicate_sql(scope: Scope, tenant_column: str, project_column: str) -> tuple[str, list[Any]]:
    parts: list[str] = []
    params: list[Any] = []

    if scope.tenants:
        parts.append(f"{tenant_column}::text = ANY(%s)")
        params.append(list(scope.tenants))

    if scope.projects:
        parts.append(f"{project_column}::text = ANY(%s)")
        params.append(list(scope.projects))

    if not parts:
        return "TRUE", []

    return "(" + " AND ".join(parts) + ")", params


def build_authorized_spec_sql_predicate(
    auth_ctx: McpAuthContext,
    *,
    tenant_column: str,
    project_column: str,
    visibility_column: str,
) -> tuple[str, list[Any]]:
    """Build a parameterized SQL boolean expression for scope ∩ visibility.

    The fragment assumes ``tenant_column`` / ``project_column`` /
    ``visibility_column`` are trusted qualified identifiers (e.g. ``v.tenant_id``).

    Returns ``FALSE`` with an empty param list when ``auth_ctx.scope`` is deny-all. Otherwise
    params are ordered: tenant allow-list (if any), project allow-list (if any),
    then the key's ``tenant_id`` text for the private-spec guard.
    """
    tenant_column = _validate_qualified_identifier(tenant_column, role="tenant_column")
    project_column = _validate_qualified_identifier(project_column, role="project_column")
    visibility_column = _validate_qualified_identifier(visibility_column, role="visibility_column")

    if auth_ctx.scope.deny_all:
        return "FALSE", []

    scope_sql, scope_params = _scope_predicate_sql(auth_ctx.scope, tenant_column, project_column)

    visibility_sql = (
        f"({visibility_column}::text = 'public' OR "
        f"({visibility_column}::text = 'private' AND {tenant_column}::text = %s))"
    )
    params = [*scope_params, str(auth_ctx.tenant_id)]

    combined = f"({scope_sql}) AND {visibility_sql}"
    return combined, params


def build_mcp_scope_sql_predicate(
    auth_ctx: McpAuthContext,
    *,
    tenant_column: str,
    project_column: str,
) -> tuple[str, list[Any]]:
    """Parameterized SQL for scope-only checks on rows that are already public-visible.

    Use on ``apiome.mcp_v_public_specs`` (no ``visibility`` column): callers already
    exclude private revisions. Mirrors the scope half of :func:`authorize_spec`
    for public visibility (``visibility == "public"``).
    """

    tenant_column = _validate_qualified_identifier(tenant_column, role="tenant_column")
    project_column = _validate_qualified_identifier(project_column, role="project_column")

    if auth_ctx.scope.deny_all:
        return "FALSE", []

    return _scope_predicate_sql(auth_ctx.scope, tenant_column, project_column)
