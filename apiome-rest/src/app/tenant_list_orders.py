"""Orderings of the tenant-configuration lists that page by cursor (DBP-1.13, #7196).

Each constant spells the ``ORDER BY`` of one ``Database`` accessor, so the accessor (which splices
it into its SQL) and the route (which issues and reads the cursor) share one definition. Kept out
of :mod:`app.database` so a route imports the ordering without reaching into the accessor class.
"""

from __future__ import annotations

from .keyset_lists import ListOrder, SortColumn, newest_first

__all__ = [
    "CHANGE_REPORT_TEMPLATE_VERSIONS_ORDER",
    "MCP_API_KEYS_ORDER",
    "MCP_CATEGORIES_ORDER",
    "MCP_COLLECTIONS_ORDER",
    "MCP_ENDPOINT_MANIFESTS_ORDER",
    "MCP_ENDPOINT_NOTES_ORDER",
    "MCP_SAVED_SEARCHES_ORDER",
    "MEMBERS_ORDER",
    "PUSH_WEBHOOK_DEAD_LETTER_ORDER",
    "PUSH_WEBHOOK_SUBSCRIPTIONS_ORDER",
    "ROLE_BUILTIN_RANK_SQL",
    "ROLES_ORDER",
    "TENANT_REPOSITORIES_ORDER",
]

#: Where a built-in role sits among the built-ins (owner, admin, editor, viewer), then custom roles.
ROLE_BUILTIN_RANK_SQL = (
    "CASE r.slug WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 "
    "WHEN 'editor' THEN 2 WHEN 'viewer' THEN 3 ELSE 4 END"
)

#: ``Database.list_roles`` — built-in first, in their fixed order, then by name.
ROLES_ORDER = ListOrder(
    "roles",
    (
        SortColumn("r.is_builtin", "bool", ("is_builtin",), descending=True),
        SortColumn(ROLE_BUILTIN_RANK_SQL, "int", ("builtin_rank",)),
        SortColumn("r.name", "text", ("name",)),
        SortColumn("r.id", "uuid", ("id",)),
    ),
)

#: ``Database.list_members`` — by display name.
MEMBERS_ORDER = ListOrder(
    "members",
    (
        SortColumn("u.name", "text", ("name",), nullable=True),
        SortColumn("u.id", "uuid", ("user_id",)),
    ),
)

#: ``Database.list_push_webhook_subscriptions`` — newest first.
PUSH_WEBHOOK_SUBSCRIPTIONS_ORDER = newest_first("push-webhook-subscriptions")

#: ``Database.list_push_webhook_dead_letter_events`` — most recently failed first.
PUSH_WEBHOOK_DEAD_LETTER_ORDER = newest_first(
    "push-webhook-dead-letter", "updated_at", "id", timestamp_field="updated_at"
)

#: ``Database.list_change_report_template_version_summaries`` — system templates, then the tenant's.
CHANGE_REPORT_TEMPLATE_VERSIONS_ORDER = ListOrder(
    "change-report-template-versions",
    (
        SortColumn("owner_tenant_id", "uuid", ("owner_tenant_id",), nullable=True, nulls_first=True),
        SortColumn("semver", "text", ("semver",)),
        SortColumn("id", "uuid", ("id",)),
    ),
)

#: ``Database.list_tenant_repositories`` — newest registration first.
TENANT_REPOSITORIES_ORDER = newest_first("tenant-repositories")

#: ``Database.list_mcp_categories`` — by sort order, then label, then slug.
MCP_CATEGORIES_ORDER = ListOrder(
    "mcp-categories",
    (
        SortColumn("c.sort_order", "int", ("sort_order",), nullable=True),
        SortColumn("lower(c.label)", "text", ("label_key",)),
        SortColumn("c.slug", "text", ("slug",)),
        SortColumn("c.id", "uuid", ("id",)),
    ),
)

#: ``Database.list_mcp_saved_searches`` — pinned first, then most recently changed.
MCP_SAVED_SEARCHES_ORDER = ListOrder(
    "mcp-saved-searches",
    (
        SortColumn("is_pinned", "bool", ("is_pinned",), descending=True),
        SortColumn("updated_at", "time", ("updated_at",), descending=True),
        SortColumn("name", "text", ("name",)),
        SortColumn("id", "uuid", ("id",)),
    ),
)

#: ``Database.list_mcp_endpoint_notes`` — newest first.
MCP_ENDPOINT_NOTES_ORDER = newest_first("mcp-endpoint-notes", "n.created_at", "n.id")

#: ``Database.list_mcp_collections`` — most recently changed first.
MCP_COLLECTIONS_ORDER = ListOrder(
    "mcp-collections",
    (
        SortColumn("c.updated_at", "time", ("updated_at",), descending=True),
        SortColumn("c.name", "text", ("name",)),
        SortColumn("c.id", "uuid", ("id",)),
    ),
)

#: ``Database.list_mcp_endpoint_manifests`` — newest first.
MCP_ENDPOINT_MANIFESTS_ORDER = newest_first("mcp-endpoint-manifests")

#: ``Database.list_mcp_api_keys`` — newest first.
MCP_API_KEYS_ORDER = newest_first("mcp-api-keys")
