"""API products and plans on the sunset timeline — APX-1.4 (#6101).

The sunset timeline (``GET /v1/versions/{tenant}/sunset-timeline``, #508) is the tenant's end-of-life
schedule. Besides deprecated *versions* it lists every deprecated or retired **API product** and
**plan**, so an owner sees in one place that the Standard tier retires on 31 March next to the
version sunsets it relates to. :func:`timeline_entries` reads them; the rules for where an entry sits
(``past``, ``imminent``, ``announced``) are :func:`app.api_lifecycle.timeline_status`.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from .api_lifecycle import timeline_status
from .api_product_store import _iso, _rows
from .database import db
from .models import SunsetTimelineProductEntryOut
from .revision_deprecation import is_uuid_string

__all__ = ["timeline_entries"]

#: Only products that include ``project_id`` (when one is given): a non-MCP member naming it.
_PROJECT_FILTER = """
    AND (%s::text IS NULL OR EXISTS (
        SELECT 1 FROM apiome.api_product_members m
        WHERE m.product_id = ap.id AND m.member_kind <> 'mcp_server' AND m.member_ref::text = %s::text))
"""


def _entry(row: Dict[str, Any], kind: str, today: date) -> SunsetTimelineProductEntryOut:
    """Build one timeline entry from a product or plan row.

    Args:
        row: A row of :func:`timeline_entries`' statements.
        kind: ``product`` or ``plan``.
        today: The current UTC day.

    Returns:
        The entry.
    """
    status, phase = timeline_status(row["state"], row.get("retire_at"), today)
    return SunsetTimelineProductEntryOut(
        kind=kind,
        product_slug=row["product_slug"],
        product_name=row["product_name"],
        plan_slug=row.get("plan_slug"),
        plan_name=row.get("plan_name"),
        state=row["state"],
        deprecated_at=_iso(row.get("deprecated_at")),
        retire_at=_iso(row.get("retire_at")),
        retired_at=_iso(row.get("retired_at")),
        timeline_status=status,
        lifecycle_phase=phase,
        deprecation_message=row.get("deprecation_message"),
        successor_plan_slug=row.get("successor_slug"),
        successor_plan_name=row.get("successor_name"),
    )


def _sort_key(entry: SunsetTimelineProductEntryOut) -> tuple:
    """Soonest retirement first, undated last; then product, then the product before its plans."""
    return (
        entry.retire_at is None,
        entry.retire_at or "",
        entry.product_name.lower(),
        entry.kind != "product",
        (entry.plan_name or "").lower(),
    )


def timeline_entries(
    tenant_id: str, project_id: Optional[str] = None, *, today: Optional[date] = None
) -> List[SunsetTimelineProductEntryOut]:
    """Every deprecated or retired live product and plan of a tenant, soonest retirement first.

    Args:
        tenant_id: The tenant.
        project_id: Only products that include this project (a Project or catalog-item member).
        today: The current UTC day; defaults to now.

    Returns:
        The entries; empty for a tenant id that is not a UUID.
    """
    if not is_uuid_string(tenant_id):
        return []
    today = today or datetime.now(timezone.utc).date()
    project = project_id if project_id and is_uuid_string(project_id) else None
    if project_id and project is None:
        return []

    def work(cursor: Any) -> List[SunsetTimelineProductEntryOut]:
        products = _rows(
            cursor,
            f"""
            SELECT ap.slug AS product_slug, ap.name AS product_name, ap.state, ap.deprecated_at,
                   ap.retire_at, ap.retired_at, ap.deprecation_message
            FROM apiome.api_products ap
            WHERE ap.tenant_id = %s::uuid AND ap.deleted_at IS NULL AND ap.state IN ('deprecated', 'retired')
            {_PROJECT_FILTER}
            """,
            (tenant_id, project, project),
        )
        plans = _rows(
            cursor,
            f"""
            SELECT ap.slug AS product_slug, ap.name AS product_name, pl.slug AS plan_slug,
                   pl.name AS plan_name, pl.state, pl.deprecated_at, pl.retire_at, pl.retired_at,
                   pl.deprecation_message, s.slug AS successor_slug, s.name AS successor_name
            FROM apiome.api_plans pl
            JOIN apiome.api_products ap ON ap.id = pl.product_id AND ap.tenant_id = pl.tenant_id
            LEFT JOIN apiome.api_plans s ON s.id = pl.successor_plan_id AND s.deleted_at IS NULL
            WHERE pl.tenant_id = %s::uuid AND pl.deleted_at IS NULL AND ap.deleted_at IS NULL
              AND pl.state IN ('deprecated', 'retired')
            {_PROJECT_FILTER}
            """,
            (tenant_id, project, project),
        )
        entries = [_entry(row, "product", today) for row in products]
        entries.extend(_entry(row, "plan", today) for row in plans)
        return sorted(entries, key=_sort_key)

    return db._guarded_tx(work)
