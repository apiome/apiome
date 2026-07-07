"""Scheduled catalog digest — pure compilation of a per-tenant catalog report (V2-MCP-33.5 / MCAT-19.5, #4654).

Operators want a recurring "here's your catalog this week" without opening the app. The scheduled
sweep (:mod:`app.mcp_catalog_digest_sweep`) reads the raw catalog activity over a time window and
this module folds it into a normalized :class:`CatalogDigest` and the JSON payload delivered over the
tenant's notification channel. It is the **pure** counterpart to that sweep, mirroring how
:mod:`app.mcp_change_feed` is the pure renderer behind the change-feed routes.

The digest covers the four kinds of activity the ticket calls out, each derived from real catalog
data over the window ``(window_start, window_end]``:

* **New endpoints** — endpoints registered during the window.
* **Grade movements** — endpoints whose quality grade (:mod:`app.mcp_score`, A–F) changed between two
  consecutive discovery snapshots inside the window.
* **Breaking changes** — capability changes classified ``breaking`` by the *same*
  :func:`app.mcp_change_severity.classify_change` the rest of the product uses, so the digest agrees
  with the change feed / churn timeline on what "breaking" means.
* **Discovery-health problems** — endpoints that became quarantined or are failing discovery during
  the window (the MCAT-5.3 backoff/quarantine signals).

Design rules (mirroring the feed / badge / inventory siblings):

* **Pure and deterministic.** Nothing here touches the database, the request, or the clock — the
  window bounds are supplied by the caller — so the same rows always produce byte-identical output.
  That makes the digest trivially testable without a database.
* **Tenant-scoped, but not public-gated.** Unlike the public change feed, the digest is a private
  operator report over the *whole* catalog the tenant owns (private endpoints included). The caller
  (the sweep + its DB reads) is responsible for scoping every read to one ``tenant_id``; this layer
  only folds the rows it is handed. No raw ``endpoint_url`` (which may embed a credential) is ever
  read or emitted — only endpoint identity (name / slug).

The public surface is :class:`CatalogDigest` (+ its section dataclasses), :func:`compile_digest`
(raw rows → digest), :func:`digest_is_empty`, :func:`render_digest_summary` (digest → one-line
headline) and :func:`build_digest_payload` (digest → JSON webhook payload).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, List, Mapping, Optional, Sequence

from .mcp_change_severity import SEVERITY_BREAKING, classify_change

#: Push-webhook event type stamped on every digest delivery. Namespaced under ``mcp.catalog.*`` so a
#: subscriber can route/filter digests distinctly from the repository-refresh events (RAR-5.4).
EVENT_TYPE_DIGEST = "mcp.catalog.digest"

#: Letter grades best → worst; the index is the rank used to decide a movement's direction.
_GRADE_ORDER = ("A", "B", "C", "D", "F")

#: Cap on how many breaking-change entries the digest lists, so one very churny window cannot balloon
#: the payload. The full breaking count is still reported in the summary/totals.
_MAX_BREAKING_ENTRIES = 50


# --- Normalized section model ----------------------------------------------------------------------


@dataclass(frozen=True)
class DigestNewEndpoint:
    """One endpoint registered during the window.

    Attributes:
        endpoint_id: The endpoint's id.
        name: The endpoint's display name.
        slug: The endpoint's tenant-unique catalog slug.
        visibility: ``private`` / ``public``.
        created_at: When the endpoint was registered (tz-aware), or ``None`` if unrecorded.
    """

    endpoint_id: str
    name: str
    slug: str
    visibility: str
    created_at: Optional[datetime]


@dataclass(frozen=True)
class DigestGradeMovement:
    """One endpoint whose quality grade changed within the window.

    Attributes:
        endpoint_id: The endpoint's id.
        name: The endpoint's display name.
        slug: The endpoint's slug.
        previous_grade: The grade of the prior scored snapshot (A–F).
        new_grade: The grade of the in-window snapshot (A–F).
        direction: ``improved`` / ``declined`` / ``changed`` (when either grade is unrecognized).
        version_seq: The in-window snapshot's monotonic sequence number, when known.
        version_tag: The in-window snapshot's date/time tag, when known.
        moved_at: When the movement was observed (the snapshot's discovery time), or ``None``.
    """

    endpoint_id: str
    name: str
    slug: str
    previous_grade: str
    new_grade: str
    direction: str
    version_seq: Optional[int]
    version_tag: Optional[str]
    moved_at: Optional[datetime]


@dataclass(frozen=True)
class DigestBreakingChange:
    """One breaking capability change within the window.

    Attributes:
        endpoint_id: The owning endpoint's id.
        endpoint_name: The owning endpoint's display name.
        endpoint_slug: The owning endpoint's slug.
        change_type: ``added`` / ``removed`` / ``modified`` (breaking is usually ``removed``/``modified``).
        item_type: ``tool`` / ``resource`` / ``resource_template`` / ``prompt`` / ``server``.
        item_name: The changed item's name.
        version_seq: The introducing snapshot's sequence number, when known.
        version_tag: The introducing snapshot's date/time tag, when known.
        changed_at: When the change was observed, or ``None``.
    """

    endpoint_id: str
    endpoint_name: str
    endpoint_slug: str
    change_type: str
    item_type: str
    item_name: str
    version_seq: Optional[int]
    version_tag: Optional[str]
    changed_at: Optional[datetime]


@dataclass(frozen=True)
class DigestHealthProblem:
    """One endpoint with a discovery-health problem observed in the window.

    Attributes:
        endpoint_id: The endpoint's id.
        name: The endpoint's display name.
        slug: The endpoint's slug.
        quarantined: Whether the endpoint is quarantined (tripped the failure threshold).
        quarantine_reason: The error code/summary that tripped quarantine, when any.
        consecutive_failures: Back-to-back discovery failures (≥ 1 for a failing endpoint).
        last_status: The most recent discovery status (e.g. ``failed`` / ``unreachable``).
        observed_at: When the problem was observed (quarantine time, else last attempt), or ``None``.
    """

    endpoint_id: str
    name: str
    slug: str
    quarantined: bool
    quarantine_reason: Optional[str]
    consecutive_failures: int
    last_status: Optional[str]
    observed_at: Optional[datetime]


@dataclass(frozen=True)
class CatalogDigest:
    """A compiled per-tenant catalog digest over one window.

    Attributes:
        tenant_slug: The catalog's tenant slug.
        window_start: Start of the digest window (exclusive), tz-aware.
        window_end: End of the digest window (inclusive), tz-aware.
        new_endpoints: Endpoints registered during the window.
        grade_movements: Grade changes observed during the window.
        breaking_changes: Breaking capability changes during the window (capped for size).
        breaking_change_total: The true count of breaking changes, even when the list was capped.
        health_problems: Discovery-health problems observed during the window.
    """

    tenant_slug: str
    window_start: datetime
    window_end: datetime
    new_endpoints: List[DigestNewEndpoint] = field(default_factory=list)
    grade_movements: List[DigestGradeMovement] = field(default_factory=list)
    breaking_changes: List[DigestBreakingChange] = field(default_factory=list)
    breaking_change_total: int = 0
    health_problems: List[DigestHealthProblem] = field(default_factory=list)


# --- Coercion helpers ------------------------------------------------------------------------------


def _as_datetime(value: Any) -> Optional[datetime]:
    """Coerce a timestamp column (a ``datetime`` or ISO-8601 string) to a ``datetime``, else ``None``.

    An unparseable value yields ``None`` rather than raising, so one malformed row can never break the
    digest. Timezone normalization is intentionally left to the caller/serializer (the digest's own
    window bounds are already tz-aware).
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _as_int(value: Any) -> Optional[int]:
    """Coerce a value to ``int``, or ``None`` when missing/unparseable."""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _clean_str(value: Any) -> Optional[str]:
    """Return a stripped non-empty string, or ``None`` for blank/missing values."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _grade_direction(previous: str, current: str) -> str:
    """Classify a grade transition as ``improved`` / ``declined`` / ``changed``.

    A lower :data:`_GRADE_ORDER` index is a better grade, so a move to a lower index is an
    improvement. An unrecognized grade on either side (e.g. a custom or future grade) degrades to the
    neutral ``changed`` rather than guessing a direction.
    """
    try:
        prev_rank = _GRADE_ORDER.index(previous)
        cur_rank = _GRADE_ORDER.index(current)
    except ValueError:
        return "changed"
    if cur_rank < prev_rank:
        return "improved"
    if cur_rank > prev_rank:
        return "declined"
    return "changed"


# --- Compilation -----------------------------------------------------------------------------------


def compile_digest(
    *,
    tenant_slug: str,
    window_start: datetime,
    window_end: datetime,
    new_endpoint_rows: Sequence[Mapping[str, Any]],
    change_rows: Sequence[Mapping[str, Any]],
    grade_movement_rows: Sequence[Mapping[str, Any]],
    health_rows: Sequence[Mapping[str, Any]],
) -> CatalogDigest:
    """Fold the window's raw catalog rows into a normalized :class:`CatalogDigest` (MCAT-19.5).

    Pure and deterministic: the digest depends only on the supplied rows and window bounds. The
    breaking-change section is derived by running the shared
    :func:`app.mcp_change_severity.classify_change` over ``change_rows`` and keeping only the
    ``breaking`` verdicts (capped at :data:`_MAX_BREAKING_ENTRIES`, with the true total retained), so
    the digest never disagrees with the change feed on severity. All other sections are a direct
    projection of their pre-scoped rows.

    Args:
        tenant_slug: The catalog's tenant slug (stamped on the digest for the payload).
        window_start: Start of the window (exclusive), tz-aware.
        window_end: End of the window (inclusive), tz-aware.
        new_endpoint_rows: Endpoint rows registered in the window (``id`` / ``name`` / ``slug`` /
            ``visibility`` / ``created_at``).
        change_rows: All capability-change rows in the window, each carrying the fields
            :func:`classify_change` reads plus the owning endpoint's identity and snapshot context.
        grade_movement_rows: Pre-computed grade transitions (``prev_grade`` / ``new_grade`` + endpoint
            identity + snapshot context) whose in-window snapshot changed grade.
        health_rows: Endpoint rows with a discovery-health problem observed in the window.

    Returns:
        The compiled :class:`CatalogDigest`.
    """
    new_endpoints = [
        DigestNewEndpoint(
            endpoint_id=str(row.get("id") or ""),
            name=_clean_str(row.get("name")) or str(row.get("slug") or "unnamed"),
            slug=str(row.get("slug") or ""),
            visibility=str(row.get("visibility") or "private"),
            created_at=_as_datetime(row.get("created_at")),
        )
        for row in new_endpoint_rows
    ]

    grade_movements = [
        DigestGradeMovement(
            endpoint_id=str(row.get("endpoint_id") or ""),
            name=_clean_str(row.get("endpoint_name")) or str(row.get("endpoint_slug") or "unnamed"),
            slug=str(row.get("endpoint_slug") or ""),
            previous_grade=str(row.get("prev_grade") or ""),
            new_grade=str(row.get("new_grade") or ""),
            direction=_grade_direction(
                str(row.get("prev_grade") or ""), str(row.get("new_grade") or "")
            ),
            version_seq=_as_int(row.get("version_seq")),
            version_tag=_clean_str(row.get("version_tag")),
            moved_at=_as_datetime(row.get("moved_at")) or _as_datetime(row.get("discovered_at")),
        )
        for row in grade_movement_rows
    ]

    breaking_changes: List[DigestBreakingChange] = []
    breaking_total = 0
    for row in change_rows:
        if classify_change(row) != SEVERITY_BREAKING:
            continue
        breaking_total += 1
        if len(breaking_changes) >= _MAX_BREAKING_ENTRIES:
            continue
        breaking_changes.append(
            DigestBreakingChange(
                endpoint_id=str(row.get("endpoint_id") or ""),
                endpoint_name=_clean_str(row.get("endpoint_name"))
                or str(row.get("endpoint_slug") or "unnamed"),
                endpoint_slug=str(row.get("endpoint_slug") or ""),
                change_type=str(row.get("change_type") or ""),
                item_type=str(row.get("item_type") or ""),
                item_name=str(row.get("item_name") or ""),
                version_seq=_as_int(row.get("version_seq")),
                version_tag=_clean_str(row.get("version_tag")),
                changed_at=_as_datetime(row.get("discovered_at"))
                or _as_datetime(row.get("version_created_at"))
                or _as_datetime(row.get("created_at")),
            )
        )

    health_problems = [
        DigestHealthProblem(
            endpoint_id=str(row.get("id") or ""),
            name=_clean_str(row.get("name")) or str(row.get("slug") or "unnamed"),
            slug=str(row.get("slug") or ""),
            quarantined=row.get("quarantined_at") is not None,
            quarantine_reason=_clean_str(row.get("quarantine_reason")),
            consecutive_failures=_as_int(row.get("consecutive_failures")) or 0,
            last_status=_clean_str(row.get("last_discovery_status")),
            observed_at=_as_datetime(row.get("quarantined_at"))
            or _as_datetime(row.get("last_discovered_at")),
        )
        for row in health_rows
    ]

    return CatalogDigest(
        tenant_slug=tenant_slug,
        window_start=window_start,
        window_end=window_end,
        new_endpoints=new_endpoints,
        grade_movements=grade_movements,
        breaking_changes=breaking_changes,
        breaking_change_total=breaking_total,
        health_problems=health_problems,
    )


def digest_is_empty(digest: CatalogDigest) -> bool:
    """Return whether a digest has nothing to report across all four sections.

    Used by the sweep to honour the empty-window policy: a tenant with ``send_empty = False`` skips
    delivery entirely when this is ``True`` (an acceptance criterion), while ``send_empty = True``
    sends an explicit "no changes" digest regardless.

    Args:
        digest: The compiled digest.

    Returns:
        ``True`` when every section is empty.
    """
    return not (
        digest.new_endpoints
        or digest.grade_movements
        or digest.breaking_change_total
        or digest.health_problems
    )


def render_digest_summary(digest: CatalogDigest) -> str:
    """Render a one-line human headline for a digest (the payload's ``summary``).

    Reports the count in each non-empty section, or an explicit "no changes" line for an empty
    window, so a recipient sees the gist without expanding the structured sections.

    Args:
        digest: The compiled digest.

    Returns:
        A single-line summary string.
    """
    if digest_is_empty(digest):
        return f"No catalog changes for {digest.tenant_slug} in this window."

    parts: List[str] = []
    if digest.new_endpoints:
        n = len(digest.new_endpoints)
        parts.append(f"{n} new endpoint{'s' if n != 1 else ''}")
    if digest.grade_movements:
        n = len(digest.grade_movements)
        parts.append(f"{n} grade movement{'s' if n != 1 else ''}")
    if digest.breaking_change_total:
        n = digest.breaking_change_total
        parts.append(f"{n} breaking change{'s' if n != 1 else ''}")
    if digest.health_problems:
        n = len(digest.health_problems)
        parts.append(f"{n} discovery-health problem{'s' if n != 1 else ''}")

    return f"Catalog digest for {digest.tenant_slug}: " + ", ".join(parts) + "."


def _iso(value: Optional[datetime]) -> Optional[str]:
    """ISO-8601 string for a datetime, or ``None``."""
    return value.isoformat() if value is not None else None


def build_digest_payload(digest: CatalogDigest) -> dict:
    """Assemble the JSON-serializable webhook payload for a digest (MCAT-19.5).

    The payload carries the ``event`` type (:data:`EVENT_TYPE_DIGEST`), the tenant slug, the window
    bounds, a human ``summary``, per-section ``totals``, and the structured section lists (camelCase
    keys, matching the repository-refresh notification style). It contains only catalog identity and
    activity — never a raw endpoint URL or any credential.

    Args:
        digest: The compiled digest.

    Returns:
        A JSON-serializable dict ready to hand to ``enqueue_push_webhook_delivery``.
    """
    return {
        "event": EVENT_TYPE_DIGEST,
        "tenantSlug": digest.tenant_slug,
        "windowStart": _iso(digest.window_start),
        "windowEnd": _iso(digest.window_end),
        "summary": render_digest_summary(digest),
        "empty": digest_is_empty(digest),
        "totals": {
            "newEndpoints": len(digest.new_endpoints),
            "gradeMovements": len(digest.grade_movements),
            "breakingChanges": digest.breaking_change_total,
            "healthProblems": len(digest.health_problems),
        },
        "newEndpoints": [
            {
                "endpointId": e.endpoint_id,
                "name": e.name,
                "slug": e.slug,
                "visibility": e.visibility,
                "createdAt": _iso(e.created_at),
            }
            for e in digest.new_endpoints
        ],
        "gradeMovements": [
            {
                "endpointId": m.endpoint_id,
                "name": m.name,
                "slug": m.slug,
                "previousGrade": m.previous_grade,
                "newGrade": m.new_grade,
                "direction": m.direction,
                "versionSeq": m.version_seq,
                "versionTag": m.version_tag,
                "movedAt": _iso(m.moved_at),
            }
            for m in digest.grade_movements
        ],
        "breakingChanges": [
            {
                "endpointId": c.endpoint_id,
                "endpointName": c.endpoint_name,
                "endpointSlug": c.endpoint_slug,
                "changeType": c.change_type,
                "itemType": c.item_type,
                "itemName": c.item_name,
                "versionSeq": c.version_seq,
                "versionTag": c.version_tag,
                "changedAt": _iso(c.changed_at),
            }
            for c in digest.breaking_changes
        ],
        "breakingChangesTruncated": digest.breaking_change_total > len(digest.breaking_changes),
        "healthProblems": [
            {
                "endpointId": h.endpoint_id,
                "name": h.name,
                "slug": h.slug,
                "quarantined": h.quarantined,
                "quarantineReason": h.quarantine_reason,
                "consecutiveFailures": h.consecutive_failures,
                "lastStatus": h.last_status,
                "observedAt": _iso(h.observed_at),
            }
            for h in digest.health_problems
        ],
    }


__all__ = [
    "EVENT_TYPE_DIGEST",
    "DigestNewEndpoint",
    "DigestGradeMovement",
    "DigestBreakingChange",
    "DigestHealthProblem",
    "CatalogDigest",
    "compile_digest",
    "digest_is_empty",
    "render_digest_summary",
    "build_digest_payload",
]
