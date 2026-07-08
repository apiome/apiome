"""MCP discovery provenance assembly (V2-MCP-34.5 / MCAT-20.5, #4659).

Answers "how does the catalog know this?" for one endpoint: how the endpoint was
added (``mcp_endpoints.added_via``), which discovery run produced each version
snapshot (``mcp_endpoint_versions.discovery_trigger`` / ``discovery_job_id``, V148),
and how often each trigger has run overall (the ``mcp_discovery_jobs`` log). The
result renders as the provenance strip on the identity card and as the
"Provenance" section of the report-card export.

Pure: no DB, no network, no persistence — :func:`build_endpoint_provenance` is a
deterministic function of the rows handed to it, so it is unit-testable with plain
dict fixtures. Honesty rules mirror the lifecycle detector (V2-MCP-34.4): a snapshot
whose producing run is unknown reads as ``unrecorded`` — never silently attributed
to any concrete origin — and the per-version origin list is capped with the overflow
counted, never silently dropped.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Sequence, Tuple

#: The discovery-run origins the job log can record (the V130 ``trigger`` domain).
KNOWN_TRIGGERS: Tuple[str, ...] = ("manual", "sweep", "registry")

#: Origin bucket for a snapshot whose producing run is unknown (a pre-provenance
#: version the V148 backfill could not attribute). Deliberately distinct from every
#: concrete trigger so absence of evidence is never presented as evidence.
TRIGGER_UNRECORDED = "unrecorded"

#: The ways an endpoint can enter the catalog (the V148 ``added_via`` domain).
KNOWN_ADDED_VIA: Tuple[str, ...] = ("manual", "registry", "import")

#: Ceiling on the itemized per-version origin list; older versions beyond it are
#: counted in ``origins_truncated`` rather than silently dropped.
MAX_VERSION_ORIGINS = 20

#: Human labels for each discovery-run origin (UI strip / report rendering).
TRIGGER_LABELS: Dict[str, str] = {
    "manual": "Manual run",
    "sweep": "Scheduled sweep",
    "registry": "Registry refresh",
    TRIGGER_UNRECORDED: "Unrecorded",
}

#: Human labels for each way an endpoint can enter the catalog.
ADDED_VIA_LABELS: Dict[str, str] = {
    "manual": "Registered manually",
    "registry": "Imported from a registry",
    "import": "Bulk import",
}


def provenance_trigger_label(trigger: Optional[str]) -> str:
    """Human label for a discovery-run origin.

    Args:
        trigger: A job ``trigger`` value (``manual`` / ``sweep`` / ``registry``),
            or ``None`` / unknown for an unattributed snapshot.

    Returns:
        The display label; unknown or missing values read as ``"Unrecorded"``.
    """
    if trigger is None:
        return TRIGGER_LABELS[TRIGGER_UNRECORDED]
    return TRIGGER_LABELS.get(str(trigger), TRIGGER_LABELS[TRIGGER_UNRECORDED])


def provenance_added_via_label(added_via: Optional[str]) -> str:
    """Human label for how an endpoint entered the catalog.

    Args:
        added_via: The endpoint's ``added_via`` value.

    Returns:
        The display label; an unknown or missing value falls back to the raw value
        (or ``"Unrecorded"`` when absent) so nothing is ever mislabeled.
    """
    if added_via is None:
        return TRIGGER_LABELS[TRIGGER_UNRECORDED]
    return ADDED_VIA_LABELS.get(str(added_via), str(added_via))


def _ts(value: Any) -> Optional[str]:
    """Normalize a driver timestamp (datetime or string) to an ISO string, or None."""
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _origin_bucket(trigger: Any) -> str:
    """Map a stored ``discovery_trigger`` onto its origin bucket (unknown → unrecorded)."""
    if trigger is None:
        return TRIGGER_UNRECORDED
    value = str(trigger)
    return value if value in KNOWN_TRIGGERS else TRIGGER_UNRECORDED


@dataclass(frozen=True)
class VersionOrigin:
    """How one version snapshot came to be known.

    Attributes:
        version_id: The ``mcp_endpoint_versions`` row id.
        version_seq: The snapshot's per-endpoint sequence number.
        version_tag: The human-readable date/time tag (may be ``None`` on old rows).
        trigger: Origin bucket — a concrete trigger or ``unrecorded``.
        trigger_label: Human label for ``trigger``.
        job_id: The producing ``mcp_discovery_jobs`` id, when recorded.
        discovered_at: When the producing discovery ran (ISO string).
        is_current: Whether this snapshot is the endpoint's current version.
    """

    version_id: str
    version_seq: int
    version_tag: Optional[str]
    trigger: str
    trigger_label: str
    job_id: Optional[str]
    discovered_at: Optional[str]
    is_current: bool = False

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for the wire / report renderers."""
        return {
            "version_id": self.version_id,
            "version_seq": self.version_seq,
            "version_tag": self.version_tag,
            "trigger": self.trigger,
            "trigger_label": self.trigger_label,
            "job_id": self.job_id,
            "discovered_at": self.discovered_at,
            "is_current": self.is_current,
        }


@dataclass(frozen=True)
class EndpointProvenance:
    """The full provenance picture for one catalog endpoint.

    Attributes:
        added_via: How the endpoint entered the catalog (V148 ``added_via``).
        added_via_label: Human label for ``added_via``.
        added_at: When the endpoint was registered (ISO string).
        first_discovered_at: When its earliest snapshot was discovered.
        last_discovered_at: When it was most recently discovered (any outcome).
        version_count: Total snapshots in its history.
        origin_counts: Snapshots per origin bucket (every bucket always present).
        run_counts: Completed discovery runs per trigger from the job log — includes
            unchanged re-runs that produced no snapshot; ``total`` sums them.
        current_origin: Origin of the endpoint's current snapshot, or ``None`` when
            the endpoint has never been discovered.
        origins: Newest-first per-version origins, capped at
            :data:`MAX_VERSION_ORIGINS`.
        origins_truncated: How many older versions the cap excluded.
    """

    added_via: str
    added_via_label: str
    added_at: Optional[str]
    first_discovered_at: Optional[str]
    last_discovered_at: Optional[str]
    version_count: int
    origin_counts: Dict[str, int]
    run_counts: Dict[str, int]
    current_origin: Optional[VersionOrigin]
    origins: Tuple[VersionOrigin, ...] = field(default_factory=tuple)
    origins_truncated: int = 0

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for the wire / report renderers."""
        return {
            "added_via": self.added_via,
            "added_via_label": self.added_via_label,
            "added_at": self.added_at,
            "first_discovered_at": self.first_discovered_at,
            "last_discovered_at": self.last_discovered_at,
            "version_count": self.version_count,
            "origin_counts": dict(self.origin_counts),
            "run_counts": dict(self.run_counts),
            "current_origin": self.current_origin.as_dict()
            if self.current_origin is not None
            else None,
            "origins": [origin.as_dict() for origin in self.origins],
            "origins_truncated": self.origins_truncated,
        }


def _version_origin(
    row: Dict[str, Any], current_version_id: Optional[str]
) -> VersionOrigin:
    """Shape one version-history row into its :class:`VersionOrigin`."""
    trigger = _origin_bucket(row.get("discovery_trigger"))
    version_id = str(row["id"])
    job_id = row.get("discovery_job_id")
    return VersionOrigin(
        version_id=version_id,
        version_seq=int(row["version_seq"]),
        version_tag=str(row["version_tag"]) if row.get("version_tag") is not None else None,
        trigger=trigger,
        trigger_label=provenance_trigger_label(
            trigger if trigger != TRIGGER_UNRECORDED else None
        ),
        job_id=str(job_id) if job_id is not None else None,
        discovered_at=_ts(row.get("discovered_at")),
        is_current=current_version_id is not None
        and str(current_version_id) == version_id,
    )


def build_endpoint_provenance(
    endpoint: Dict[str, Any],
    version_rows: Sequence[Dict[str, Any]],
    job_stat_rows: Sequence[Dict[str, Any]] = (),
) -> EndpointProvenance:
    """Assemble the provenance picture for one endpoint from its stored rows.

    Args:
        endpoint: The ``mcp_endpoints`` row (needs ``added_via``, ``created_at``,
            ``last_discovered_at`` and ``current_version_id``).
        version_rows: The endpoint's version history rows (any order; each needs
            ``id`` / ``version_seq`` / ``version_tag`` / ``discovery_trigger`` /
            ``discovery_job_id`` / ``discovered_at``).
        job_stat_rows: Per-trigger tallies from
            :meth:`Database.list_mcp_discovery_trigger_stats` — dicts with
            ``trigger`` and ``completed`` keys; optional so callers without job
            history still get version-level provenance.

    Returns:
        The deterministic :class:`EndpointProvenance` for the rows given.
    """
    added_via = str(endpoint.get("added_via") or "manual")

    ordered = sorted(
        version_rows, key=lambda row: int(row["version_seq"]), reverse=True
    )
    current_version_id = endpoint.get("current_version_id")
    current_id = str(current_version_id) if current_version_id is not None else None
    origins_all = [_version_origin(row, current_id) for row in ordered]

    origin_counts = {bucket: 0 for bucket in (*KNOWN_TRIGGERS, TRIGGER_UNRECORDED)}
    for origin in origins_all:
        origin_counts[origin.trigger] += 1

    run_counts = {trigger: 0 for trigger in KNOWN_TRIGGERS}
    total_runs = 0
    for row in job_stat_rows:
        completed = int(row.get("completed") or 0)
        trigger = str(row.get("trigger") or "")
        if trigger in run_counts:
            run_counts[trigger] += completed
        total_runs += completed
    run_counts["total"] = total_runs

    discovered = [o.discovered_at for o in origins_all if o.discovered_at is not None]
    current_origin = next((o for o in origins_all if o.is_current), None)

    return EndpointProvenance(
        added_via=added_via,
        added_via_label=provenance_added_via_label(added_via),
        added_at=_ts(endpoint.get("created_at")),
        # Versions are discovered in sequence order, so min/max over the ISO strings
        # of a single endpoint's history is chronological.
        first_discovered_at=min(discovered) if discovered else None,
        last_discovered_at=_ts(endpoint.get("last_discovered_at"))
        or (max(discovered) if discovered else None),
        version_count=len(origins_all),
        origin_counts=origin_counts,
        run_counts=run_counts,
        current_origin=current_origin,
        origins=tuple(origins_all[:MAX_VERSION_ORIGINS]),
        origins_truncated=max(0, len(origins_all) - MAX_VERSION_ORIGINS),
    )
