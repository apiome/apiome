"""Backup status surfacing for the ops dashboard (RC1-3.2 over RC1-1.3, #3617/#3613).

The apiome-db backup tooling writes, for every backup artifact, a plaintext ``*.manifest.json``
sidecar (see ``apiome-db/src/backup/manifest.ts``). The manifest is *always* unencrypted and
contains only metadata — scope, creation time, size, checksum — so an operator (or this service) can
report backup health without holding the encryption key.

This module scans the configured backup directory for those manifests and summarizes them into the
shape the ops dashboard needs: the latest backup overall and per scope, its age, and whether it is
stale relative to the configured RPO guard. It is deliberately read-only and tolerant: a missing or
unreadable directory yields a clear "unconfigured"/"unavailable" status rather than an exception, so
surfacing backup health can never take the API down.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Manifests are written with this suffix by the backup engine.
_MANIFEST_SUFFIX = ".manifest.json"


@dataclass
class BackupManifestSummary:
    """The fields of a backup manifest the ops dashboard cares about."""

    id: str
    kind: str  # "full" | "tenant" | "project"
    tenant: Optional[str]
    project: Optional[str]
    created_at: str
    size_bytes: int
    encrypted: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "tenant": self.tenant,
            "project": self.project,
            "created_at": self.created_at,
            "size_bytes": self.size_bytes,
            "encrypted": self.encrypted,
        }


def _parse_created_at(value: str) -> Optional[datetime]:
    """Parse a manifest ``createdAt`` ISO-8601 timestamp into an aware UTC datetime, or None."""
    if not value:
        return None
    try:
        # Manifests use ISO-8601 UTC; accept a trailing "Z" which fromisoformat rejects pre-3.11.
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load_manifest(path: Path) -> Optional[BackupManifestSummary]:
    """Load and minimally validate one manifest file; return None if it is unusable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    created_at = raw.get("createdAt")
    backup_id = raw.get("id")
    kind = raw.get("kind")
    if not isinstance(backup_id, str) or not isinstance(created_at, str) or kind not in (
        "full",
        "tenant",
        "project",
    ):
        return None
    size = raw.get("sizeBytes")
    return BackupManifestSummary(
        id=backup_id,
        kind=kind,
        tenant=raw.get("tenant") if isinstance(raw.get("tenant"), str) else None,
        project=raw.get("project") if isinstance(raw.get("project"), str) else None,
        created_at=created_at,
        size_bytes=size if isinstance(size, int) else 0,
        encrypted=bool(raw.get("encrypted")),
    )


def collect_backup_status(
    backup_dir: Optional[str],
    *,
    stale_after_hours: int,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Summarize backup health from manifests under ``backup_dir``.

    Args:
        backup_dir: Directory the backup tooling writes manifests to. ``None`` when unset.
        stale_after_hours: Age threshold above which the latest backup is flagged ``stale``.
        now: Reference "current" time (injectable for tests); defaults to ``datetime.now(UTC)``.

    Returns:
        A JSON-serializable dict with a top-level ``status`` of:
          * ``"unconfigured"`` — no backup directory configured;
          * ``"unavailable"`` — directory configured but missing/unreadable;
          * ``"empty"`` — directory present but no valid manifests found;
          * ``"ok"`` / ``"stale"`` — at least one backup, fresh or older than the RPO guard.
        Plus ``backup_count``, ``latest`` (newest manifest), ``latest_by_kind``, and
        ``latest_age_seconds``.
    """
    reference = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if not backup_dir:
        return {
            "status": "unconfigured",
            "message": "No backup directory configured (set APIOME_BACKUP_DIR).",
            "backup_count": 0,
            "latest": None,
            "latest_by_kind": {},
            "latest_age_seconds": None,
            "stale_after_hours": stale_after_hours,
        }

    directory = Path(backup_dir)
    if not directory.is_dir():
        return {
            "status": "unavailable",
            "message": f"Backup directory does not exist or is not readable: {backup_dir}",
            "backup_count": 0,
            "latest": None,
            "latest_by_kind": {},
            "latest_age_seconds": None,
            "stale_after_hours": stale_after_hours,
        }

    summaries: List[BackupManifestSummary] = []
    try:
        manifest_paths = sorted(directory.glob(f"*{_MANIFEST_SUFFIX}"))
    except OSError:
        manifest_paths = []
    for path in manifest_paths:
        summary = _load_manifest(path)
        if summary is not None:
            summaries.append(summary)

    if not summaries:
        return {
            "status": "empty",
            "message": "Backup directory contains no readable manifests.",
            "backup_count": 0,
            "latest": None,
            "latest_by_kind": {},
            "latest_age_seconds": None,
            "stale_after_hours": stale_after_hours,
        }

    # Sort by parsed creation time (newest first); manifests with unparseable timestamps sort last.
    def _sort_key(s: BackupManifestSummary) -> datetime:
        parsed = _parse_created_at(s.created_at)
        return parsed or datetime.min.replace(tzinfo=timezone.utc)

    summaries.sort(key=_sort_key, reverse=True)
    latest = summaries[0]

    latest_by_kind: Dict[str, Dict[str, Any]] = {}
    for summary in summaries:
        if summary.kind not in latest_by_kind:
            latest_by_kind[summary.kind] = summary.to_dict()

    latest_dt = _parse_created_at(latest.created_at)
    if latest_dt is None:
        age_seconds: Optional[float] = None
        status = "ok"
    else:
        age_seconds = max(0.0, (reference - latest_dt).total_seconds())
        status = "stale" if age_seconds > stale_after_hours * 3600 else "ok"

    return {
        "status": status,
        "message": "Latest backup is within the freshness window."
        if status == "ok"
        else f"Latest backup is older than the {stale_after_hours}h freshness window.",
        "backup_count": len(summaries),
        "latest": latest.to_dict(),
        "latest_by_kind": latest_by_kind,
        "latest_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "stale_after_hours": stale_after_hours,
    }
