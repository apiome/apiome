"""SQL the MCP listing tools share: page first, on stored sort keys — DBP-1.22 (#7205).

``spec.list``, ``spec.list_my_specs``, ``project.list``, ``spec.search`` and
``spec.search_semantic`` used to read ``apiome.mcp_v_public_specs``, whose ``updated_at`` is
computed from three tables for every row, so each page read and sorted the whole public catalog
and aggregated every revision's tags. They now:

1. pick the page's revisions from ``apiome.versions`` on ``mcp_listed_at`` — the view's
   ``updated_at``, stored by migration V428 and NOT NULL exactly for listable revisions — with the
   cursor and ``LIMIT`` applied in that step, so the partial indexes
   ``idx_versions_mcp_public_listed`` / ``idx_versions_mcp_project_listed`` return one page;
2. aggregate tags (:func:`page_with_tags`) for the rows of that page only.

Every predicate that decides what a caller may see (published, enabled, not deleted, visibility,
the project's state) is still stated in the statement: the stored column orders the rows, it is
not what makes one visible.

Optional filters are appended only when set (:class:`Where`), instead of
``(%s IS NULL OR column = %s)``, which hides the column from the planner once a statement is
planned generically.
"""

from __future__ import annotations

from typing import Any, Literal

__all__ = ["LISTED_PROJECT", "PAGE_COLUMNS", "Where", "listed_version", "page_with_tags"]

#: The project half of the listable predicate (alias ``p``).
LISTED_PROJECT = "p.deleted_at IS NULL AND p.enabled IS TRUE"

#: What a spec row is made of, from ``apiome.versions v`` joined to ``apiome.projects p``.
PAGE_COLUMNS = (
    "v.id, p.tenant_id, v.project_id, p.name AS title, v.version_id AS version, "
    "v.description, v.mcp_listed_at AS updated_at"
)


def listed_version(visibility: Literal["public", "private"]) -> str:
    """The revision half of the listable predicate (alias ``v``) for one visibility.

    ``mcp_listed_at IS NOT NULL AND visibility = 'public'`` is the predicate of
    ``idx_versions_mcp_public_listed``; the remaining terms restate what the column encodes.

    Args:
        visibility: Which revisions to list.

    Returns:
        A SQL boolean expression.
    """
    return (
        f"v.mcp_listed_at IS NOT NULL AND v.visibility = '{visibility}'::apiome.visibility_type "
        "AND v.deleted_at IS NULL AND v.enabled IS TRUE AND v.published IS TRUE"
    )


class Where:
    """An ``AND`` list of predicates with their positional parameters, in order."""

    def __init__(self, *predicates: str) -> None:
        """Start with ``predicates`` (parameterless SQL boolean expressions)."""
        self._parts: list[str] = list(predicates)
        self.params: list[Any] = []

    def add(self, predicate: str, *params: Any) -> Where:
        """Append ``predicate`` (with ``%s`` placeholders) and its parameters; returns ``self``."""
        self._parts.append(predicate)
        self.params.extend(params)
        return self

    def add_if(self, value: Any, predicate: str) -> Where:
        """Append ``predicate`` with ``value`` as its one parameter, unless ``value`` is ``None``."""
        if value is not None:
            self.add(predicate, value)
        return self

    @property
    def sql(self) -> str:
        """The predicates joined with ``AND`` (``TRUE`` when there are none)."""
        return " AND ".join(f"({p})" for p in self._parts) if self._parts else "TRUE"


def page_with_tags(page_sql: str, *, columns: str, order_by: str) -> str:
    """Wrap a page query so that tags are aggregated for its rows only.

    Args:
        page_sql: A query returning at least ``id`` and ``project_id``, already limited to a page.
        columns: The output columns to take from the page (``page.`` qualified or bare).
        order_by: The page's order, restated for the outer query.

    Returns:
        A statement returning ``columns`` plus ``tags`` (sorted tag names, empty when none).
    """
    return f"""
WITH page AS (
{page_sql}
)
SELECT {columns}, COALESCE(tg.tags, ARRAY[]::TEXT[]) AS tags
FROM page
LEFT JOIN LATERAL (
  SELECT array_agg(vt.name ORDER BY vt.name) AS tags
  FROM apiome.version_tags vt
  WHERE vt.version_id = page.id AND vt.project_id = page.project_id
) tg ON TRUE
ORDER BY {order_by}
"""
