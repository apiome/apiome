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
from uuid import UUID

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


def _uuid_list(values: tuple[str, ...]) -> list[UUID]:
    """The entries of a scope list that are UUIDs, as UUIDs.

    Tenant and project ids are UUIDs, so an entry that is not one can never match a row; it is
    dropped here instead of being compared as text on every row.
    """
    out: list[UUID] = []
    for value in values:
        try:
            out.append(UUID(str(value).strip()))
        except ValueError:
            continue
    return out


def _uuid_or_none(value: Any) -> UUID | None:
    """``value`` as a UUID, or ``None`` when it is not one."""
    try:
        return UUID(str(value).strip())
    except ValueError:
        return None


def _scope_predicate_sql(scope: Scope, tenant_column: str, project_column: str) -> tuple[str, list[Any]]:
    """Scope allow-lists as ``column = ANY(uuid[])`` predicates (DBP-1.22).

    The columns are compared as uuid, with the allow-list sent as a uuid array, so an index on the
    column can serve the predicate (a ``column::text`` cast could not). A non-empty allow-list
    with no valid id matches nothing.
    """
    parts: list[str] = []
    params: list[Any] = []

    for column, allowed in ((tenant_column, scope.tenants), (project_column, scope.projects)):
        if not allowed:
            continue
        ids = _uuid_list(allowed)
        if not ids:
            return "FALSE", []
        parts.append(f"{column} = ANY(%s::uuid[])")
        params.append(ids)

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
    then the key's ``tenant_id`` (a uuid) for the private-spec guard. A key whose tenant id is
    not a UUID can read no private spec.
    """
    tenant_column = _validate_qualified_identifier(tenant_column, role="tenant_column")
    project_column = _validate_qualified_identifier(project_column, role="project_column")
    visibility_column = _validate_qualified_identifier(visibility_column, role="visibility_column")

    if auth_ctx.scope.deny_all:
        return "FALSE", []

    scope_sql, scope_params = _scope_predicate_sql(auth_ctx.scope, tenant_column, project_column)

    public_sql = f"{visibility_column} = 'public'::apiome.visibility_type"
    key_tenant = _uuid_or_none(auth_ctx.tenant_id)
    if key_tenant is None:
        return f"({scope_sql}) AND {public_sql}", scope_params

    visibility_sql = (
        f"({public_sql} OR ({visibility_column} = 'private'::apiome.visibility_type AND {tenant_column} = %s::uuid))"
    )
    params = [*scope_params, key_tenant]

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
