"""Orderings of tenant-scoped lists whose accessor and route live in different modules (#7196).

Each :class:`~app.keyset_lists.ListOrder` spells the ``ORDER BY`` of one accessor; the route
parses and issues cursors with the same object (DBP-1.13).
"""

from __future__ import annotations

from .keyset_lists import ListOrder, SortColumn, newest_first

__all__ = ["AGENT_TOOLSETS_ORDER", "LINT_SAVED_VIEWS_ORDER", "SCHEMA_SUITES_ORDER"]

#: A tenant's schema test suites, newest first (``Database.list_schema_test_suites``).
SCHEMA_SUITES_ORDER = newest_first("schema-suites", "s.created_at", "s.id")

#: One user's saved lint-workspace views: pinned first, then most recently updated
#: (``Database.list_lint_workspace_saved_views``).
LINT_SAVED_VIEWS_ORDER = ListOrder(
    "lint-saved-views",
    (
        SortColumn("is_pinned", "bool", ("is_pinned",), descending=True),
        SortColumn("updated_at", "time", ("updated_at",), descending=True),
        SortColumn("name", "text", ("name",)),
        SortColumn("id", "uuid", ("id",)),
    ),
)

#: A tenant's agent toolsets, newest first, id ascending within one instant
#: (``Database.list_agent_toolsets``).
AGENT_TOOLSETS_ORDER = ListOrder(
    "agent-toolsets",
    (
        SortColumn("ts.created_at", "time", ("created_at",), descending=True),
        SortColumn("ts.id", "uuid", ("id",)),
    ),
)
