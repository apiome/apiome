"""Who has moved — the **Switch over** step's "Last published to" list, PFX-8.17 (#7314).

Pipelines move to Apiome one at a time, so after a copy the wizard lists, for each pacticipant,
where it last published: **Apiome** or **the old broker**.

What counts as publishing is what a pipeline does: a consumer publishes pacts, a provider publishes
verification results. The source's newest of each comes from what the run read
(:func:`source_latest`); Apiome's from its own tables (:func:`apiome_latest`).

A copied record keeps the source's timestamp, so a pacticipant whose newest publication in Apiome is
no newer than its newest at the source has not moved — its newest pact in Apiome *is* the copied one.
One that published to Apiome after its last publication at the source has (:func:`moved_report`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .pact_migration import parse_timestamp
from .pact_migration_plan import Plan
from .pact_migration_run_store import as_utc
from .pacticipant import PacticipantValidationError, slugify_pacticipant_name

__all__ = ["MAX_LISTED", "apiome_latest", "moved_report", "source_latest"]

#: Pacticipants listed on the run; more are counted.
MAX_LISTED = 500


def _when(value: Any) -> Optional[datetime]:
    """A source timestamp, or ``None`` when it has none or it cannot be read."""
    try:
        return parse_timestamp(value)
    except Exception:  # noqa: BLE001 — an unreadable time says nothing about who moved
        return None


def _later(current: Optional[datetime], candidate: Optional[datetime]) -> Optional[datetime]:
    """The later of two optional moments."""
    if candidate is None:
        return current
    return candidate if current is None or candidate > current else current


def source_latest(plan: Plan) -> Dict[str, Optional[datetime]]:
    """When each pacticipant last published at the source.

    Args:
        plan: The records read from the source (pacticipants, pacts, verification results).

    Returns:
        ``{name: newest pact (as consumer) or result (as provider)}`` — ``None`` for a pacticipant
        the source lists that never published either.
    """
    latest: Dict[str, Optional[datetime]] = {record["name"]: None for _key, record in plan.records["pacticipant"]}
    for _key, record in plan.records["pact"]:
        latest[record["consumer"]] = _later(latest.get(record["consumer"]), _when(record.get("created_at")))
        latest.setdefault(record["provider"], None)
    for _key, record in plan.records["verification"]:
        latest[record["provider"]] = _later(latest.get(record["provider"]), _when(record.get("created_at")))
        latest.setdefault(record["consumer"], None)
    return latest


def _handle(name: str) -> Optional[str]:
    """A pacticipant name's handle, or ``None`` when it has none."""
    try:
        return slugify_pacticipant_name(name)
    except PacticipantValidationError:
        return None


def apiome_latest(db: Any, tenant_id: str, names: Sequence[str]) -> Dict[str, Optional[datetime]]:
    """When each named pacticipant last published in Apiome.

    Args:
        db: The database.
        tenant_id: The workspace.
        names: The source's pacticipant names.

    Returns:
        ``{name: newest pact or result}`` for each name Apiome has a live pacticipant for (``None``
        when it published nothing); a name Apiome does not have is left out.
    """
    by_handle = {handle: name for name in names if (handle := _handle(name))}
    if not by_handle:
        return {}
    rows = db.execute_query(
        """
        SELECT p.slug,
               GREATEST(
                   (SELECT max(pub.created_at) FROM apiome.pact_publication pub WHERE pub.consumer_id = p.id),
                   (SELECT max(r.created_at)
                    FROM apiome.verification_result r
                    WHERE r.provider_id = p.id AND r.tenant_id = p.tenant_id)
               ) AS latest
        FROM apiome.pacticipant p
        WHERE p.tenant_id = %s::uuid AND p.slug = ANY(%s::text[]) AND p.deleted_at IS NULL
        """,
        (tenant_id, sorted(by_handle)),
    )
    found: Dict[str, Optional[datetime]] = {}
    for row in rows or []:
        data = dict(row)
        name = by_handle.get(str(data["slug"]))
        if name is not None:
            found[name] = as_utc(data.get("latest"))
    return found


def _iso(moment: Optional[datetime]) -> Optional[str]:
    """ISO 8601 UTC text."""
    return moment.isoformat().replace("+00:00", "Z") if moment else None


def moved_report(
    source: Mapping[str, Optional[datetime]],
    apiome: Mapping[str, Optional[datetime]],
    *,
    checked_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Where each pacticipant last published.

    Args:
        source: :func:`source_latest`.
        apiome: :func:`apiome_latest`.
        checked_at: When (ISO 8601).

    Returns:
        ``{total, moved, pacticipants: [{name, last, apiome_at, source_at}], dropped, checked_at}``
        — ``last`` is ``apiome`` (published to Apiome after its last publication at the source),
        ``source`` (last published to the old broker) or ``none`` (published to neither). Stragglers
        first, then by name. Stored on the run as ``facts.moved``.
    """
    entries: List[Dict[str, Any]] = []
    for name in sorted(source, key=str.lower):
        at_source = source.get(name)
        here = apiome.get(name)
        if here is not None and (at_source is None or here > at_source):
            last = "apiome"
        elif at_source is not None:
            last = "source"
        else:
            last = "none"
        entries.append({"name": name, "last": last, "apiome_at": _iso(here), "source_at": _iso(at_source)})
    order = {"source": 0, "apiome": 1, "none": 2}
    entries.sort(key=lambda entry: order[entry["last"]])
    return {
        "total": len(entries),
        "moved": sum(1 for entry in entries if entry["last"] == "apiome"),
        "pacticipants": entries[:MAX_LISTED],
        "dropped": max(0, len(entries) - MAX_LISTED),
        "checked_at": checked_at,
    }
