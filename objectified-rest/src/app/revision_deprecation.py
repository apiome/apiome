"""
Single source of truth for **schema revision** (versions row) deprecation metadata.

Stored in ``odb.versions.metadata`` as a shallow object. Keys (camelCase in API):

- ``deprecated`` (bool): revision is deprecated for new consumer work.
- ``deprecationMessage`` (str): human-readable explanation / what changed.
- ``successorRevisionId`` (str): optional ``versions.id`` UUID of the replacement revision (#749).
- ``sunsetDate`` (str): optional ISO 8601 date (calendar day or full timestamp) (#748).

Migration guide: `#747` (GitHub).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

MIGRATION_GUIDE_ISSUE_URL = "https://github.com/KenSuenobu/objectified/issues/747"


def coerce_metadata(raw: Any) -> Dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return dict(parsed) if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def merge_version_metadata(existing: Any, patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Shallow merge for ``versions.metadata`` updates."""
    base = coerce_metadata(existing)
    if not patch:
        return base
    return {**base, **patch}


def parse_calendar_date(s: Optional[str]) -> Optional[date]:
    """Parse YYYY-MM-DD from an ISO 8601 date or timestamp string."""
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if len(t) < 10:
        return None
    try:
        return date.fromisoformat(t[:10])
    except ValueError:
        return None


def sunset_timeline_fields(
    metadata: Any,
    *,
    today: Optional[date] = None,
) -> Tuple[str, str, Optional[str]]:
    """
    Timeline UX and lifecycle for deprecation / sunset (#508).

    Returns (timeline_status, lifecycle_phase, normalized_sunset_str).
    timeline_status: announced | imminent | past
    lifecycle_phase: deprecated | sunset_reached
    """
    today = today or date.today()
    m = coerce_metadata(metadata)
    sunset_raw = m.get("sunsetDate") or m.get("sunset_date")
    norm_sunset: Optional[str] = None
    if isinstance(sunset_raw, str) and sunset_raw.strip():
        norm_sunset = sunset_raw.strip()
    sunset_d = parse_calendar_date(norm_sunset) if norm_sunset else None
    dep = is_revision_deprecated(metadata)

    if sunset_d is not None:
        if sunset_d < today:
            return ("past", "sunset_reached", norm_sunset)
        if (sunset_d - today).days <= 30:
            return ("imminent", "deprecated", norm_sunset)
        return ("announced", "deprecated", norm_sunset)

    if dep:
        return ("announced", "deprecated", None)
    return ("announced", "deprecated", norm_sunset)


def is_revision_deprecated(metadata: Any) -> bool:
    m = coerce_metadata(metadata)
    v = m.get("deprecated")
    if v is True:
        return True
    if isinstance(v, str) and v.lower() in ("true", "1", "yes"):
        return True
    return False


def deprecation_payload_for_openapi(metadata: Any) -> Optional[Dict[str, Any]]:
    """Return an object for ``info.x-objectified-revision-deprecation`` or None."""
    if not is_revision_deprecated(metadata):
        return None
    m = coerce_metadata(metadata)
    out: Dict[str, Any] = {
        "deprecated": True,
        "migrationGuideUrl": MIGRATION_GUIDE_ISSUE_URL,
    }
    msg = m.get("deprecationMessage") or m.get("message")
    if isinstance(msg, str) and msg.strip():
        out["message"] = msg.strip()
    succ = m.get("successorRevisionId") or m.get("successor_revision_id")
    if isinstance(succ, str) and succ.strip():
        out["successorRevisionId"] = succ.strip()
    sunset = m.get("sunsetDate") or m.get("sunset_date")
    if isinstance(sunset, str) and sunset.strip():
        out["sunsetDate"] = sunset.strip()
    return out


def warnings_for_revision(
    *,
    revision_id: str,
    version_label: str,
    role: str,
    metadata: Any,
) -> List[Dict[str, Any]]:
    """
    Build structured warning dicts for API responses (compatibility, etc.).

    role: ``base`` | ``head``
    """
    if not is_revision_deprecated(metadata):
        return []
    m = coerce_metadata(metadata)
    parts: List[str] = [
        f"Revision {version_label} ({revision_id[:8]}…) is deprecated.",
    ]
    msg = m.get("deprecationMessage") or m.get("message")
    if isinstance(msg, str) and msg.strip():
        parts.append(msg.strip())
    succ = m.get("successorRevisionId") or m.get("successor_revision_id")
    if isinstance(succ, str) and succ.strip():
        parts.append(f"Prefer successor revision {succ.strip()}.")
    sunset = m.get("sunsetDate") or m.get("sunset_date")
    if isinstance(sunset, str) and sunset.strip():
        parts.append(f"Sunset: {sunset.strip()}.")
    parts.append(f"Migration guide: {MIGRATION_GUIDE_ISSUE_URL}")

    return [
        {
            "revisionId": revision_id,
            "role": role,
            "versionId": version_label,
            "message": " ".join(parts),
            "replacementRevisionId": succ.strip() if isinstance(succ, str) and succ.strip() else None,
            "sunsetDate": sunset.strip() if isinstance(sunset, str) and sunset.strip() else None,
            "migrationGuideUrl": MIGRATION_GUIDE_ISSUE_URL,
        }
    ]
