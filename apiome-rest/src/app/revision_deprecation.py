"""
Single source of truth for **schema revision** (versions row) deprecation metadata.

Stored in ``apiome.versions.metadata`` as a shallow object. Keys (camelCase in API):

- ``deprecated`` (bool): revision is deprecated for new consumer work.
- ``deprecationMessage`` (str): human-readable explanation / what changed.
- ``successorRevisionId`` (str): optional ``versions.id`` UUID of the replacement revision when migrating
  consumers to another revision; omit for pure end-of-life (sunset with no successor) (#748). **GET**
  ``/v1/versions/{tenant}/{project}/{revisionId}`` supports
  ``successorResolution=none|resolve|redirect`` (#749): follows this pointer (cycle-safe; missing-target and
  protected-ref rules documented on the route).
- ``sunsetAt`` (str): optional instant in **UTC** (ISO 8601, e.g. ``2026-12-01T00:00:00Z`` or calendar day
  ``YYYY-MM-DD`` normalized to UTC midnight). Canonical field for sunset (#748).
- ``sunsetDate`` (str): legacy alias; reads/writes mirror ``sunsetAt`` for #507 / #508 consumers.
- ``deprecatedAt`` (str): optional UTC instant when deprecation was announced; must be **on or before**
  ``sunsetAt`` when both are set (#748).

Display: clients show stored UTC in the user local timezone; API contract is UTC strings.

Migration guide: `#747` (GitHub).
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

MIGRATION_GUIDE_ISSUE_URL = "https://github.com/KenSuenobu/objectified-commercial/issues/747"

_SUNSET_ALIAS_KEYS = ("sunsetAt", "sunsetDate", "sunset_date")
_SUCCESSOR_ALIAS_KEYS = ("successorRevisionId", "successor_revision_id")
_DEPRECATION_MSG_ALIAS_KEYS = ("deprecationMessage", "message")

# Keys where JSON ``null`` or empty string in a patch means "remove from metadata".
_REMOVABLE_DEPRECATION_KEYS = frozenset(
    {
        "sunsetAt",
        "sunsetDate",
        "sunset_date",
        "deprecatedAt",
        "deprecated_at",
        "successorRevisionId",
        "successor_revision_id",
        "deprecationMessage",
        "message",
    }
)


def _patch_clears_key(patch: Dict[str, Any], key: str) -> bool:
    """Return True if *patch* explicitly clears *key* via ``None`` or empty/whitespace string."""
    if key not in patch:
        return False
    v = patch[key]
    return v is None or (isinstance(v, str) and not v.strip())


def _patch_clears_any_in_group(patch: Dict[str, Any], keys: tuple) -> bool:
    return any(_patch_clears_key(patch, k) for k in keys)


def _patch_clears_sunset_aliases(patch: Dict[str, Any]) -> bool:
    return _patch_clears_any_in_group(patch, _SUNSET_ALIAS_KEYS)


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


def successor_revision_id_from_metadata(metadata: Any) -> Optional[str]:
    """Return the successor revision UUID from ``versions.metadata`` (#748, #749)."""
    m = coerce_metadata(metadata)
    for key in _SUCCESSOR_ALIAS_KEYS:
        succ = m.get(key)
        if isinstance(succ, str) and succ.strip():
            return succ.strip()
    return None


def merge_version_metadata(existing: Any, patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Shallow merge for ``versions.metadata`` updates."""
    base = coerce_metadata(existing)
    if not patch:
        return base
    out = dict(base)
    for k, v in patch.items():
        if k in _REMOVABLE_DEPRECATION_KEYS:
            if v is None:
                out.pop(k, None)
                continue
            if isinstance(v, str) and not v.strip():
                out.pop(k, None)
                continue
        out[k] = v
    if _patch_clears_sunset_aliases(patch):
        for sk in _SUNSET_ALIAS_KEYS:
            out.pop(sk, None)
    if _patch_clears_any_in_group(patch, _SUCCESSOR_ALIAS_KEYS):
        for sk in _SUCCESSOR_ALIAS_KEYS:
            out.pop(sk, None)
    if _patch_clears_any_in_group(patch, _DEPRECATION_MSG_ALIAS_KEYS):
        for sk in _DEPRECATION_MSG_ALIAS_KEYS:
            out.pop(sk, None)
    return out


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


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def is_uuid_string(s: str) -> bool:
    return bool(_UUID_RE.match(s.strip()))


def parse_iso_utc_instant(s: Optional[str]) -> Optional[datetime]:
    """Parse a metadata instant to UTC (calendar day ``YYYY-MM-DD`` → UTC midnight)."""
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    if not t:
        return None
    if len(t) == 10 and t[4] == "-" and t[7] == "-":
        try:
            d = date.fromisoformat(t)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            return None
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


def format_utc_z(dt: datetime) -> str:
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"


def normalize_sunset_instant_str(raw: Optional[str]) -> Optional[str]:
    """Normalize user/API input to a single UTC ``Z`` string for storage."""
    if not raw or not isinstance(raw, str):
        return None
    t = raw.strip()
    if not t:
        return None
    parsed = parse_iso_utc_instant(t)
    if parsed is None:
        raise ValueError(
            "Invalid sunsetAt / sunsetDate: expected ISO 8601 date or timestamp (UTC stored; use Z or offset).",
        )
    return format_utc_z(parsed)


def effective_sunset_string(metadata: Any) -> Optional[str]:
    """Canonical sunset for reads: ``sunsetAt`` preferred, then legacy keys."""
    m = coerce_metadata(metadata)
    for key in ("sunsetAt", "sunsetDate", "sunset_date"):
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def effective_deprecated_at_string(metadata: Any) -> Optional[str]:
    m = coerce_metadata(metadata)
    for key in ("deprecatedAt", "deprecated_at"):
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def normalize_deprecation_metadata_for_storage(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """
    After lifecycle / merge: mirror ``sunsetAt`` and ``sunsetDate`` to the same normalized UTC string,
    drop redundant ``sunset_date``, normalize ``deprecatedAt`` form.
    """
    m = dict(metadata)
    raw_sunset: Optional[str] = None
    for key in ("sunsetAt", "sunsetDate", "sunset_date"):
        v = m.get(key)
        if isinstance(v, str) and v.strip():
            raw_sunset = v.strip()
            break
    if raw_sunset is not None:
        norm = normalize_sunset_instant_str(raw_sunset)
        m["sunsetAt"] = norm
        m["sunsetDate"] = norm
        m.pop("sunset_date", None)
    else:
        for k in ("sunsetAt", "sunsetDate", "sunset_date"):
            m.pop(k, None)

    raw_dep_at = effective_deprecated_at_string(m)
    if raw_dep_at is not None:
        norm_d = normalize_sunset_instant_str(raw_dep_at)
        m["deprecatedAt"] = norm_d
        m.pop("deprecated_at", None)
    else:
        m.pop("deprecatedAt", None)
        m.pop("deprecated_at", None)

    succ = m.get("successorRevisionId") or m.get("successor_revision_id")
    if isinstance(succ, str) and succ.strip():
        m["successorRevisionId"] = succ.strip()
        m.pop("successor_revision_id", None)
    else:
        m.pop("successorRevisionId", None)
        m.pop("successor_revision_id", None)

    return m


def validate_deprecation_schedule(metadata: Dict[str, Any]) -> None:
    """
    Rules (#748): if a sunset is set, the revision must be deprecated (or archived for audit).
    ``successorRevisionId`` is optional: omit for end-of-life with no replacement revision.
    If ``deprecatedAt`` and sunset are both set, sunset must be on or after deprecatedAt.
    When a successor is present, it must be a UUID.
    """
    from .revision_lifecycle import (  # local: avoid import cycle with revision_lifecycle
        LIFECYCLE_ARCHIVED,
        LIFECYCLE_DEPRECATED,
        effective_lifecycle,
    )

    m = coerce_metadata(metadata)
    sunset_s = effective_sunset_string(m)
    if not sunset_s:
        return

    elc = effective_lifecycle(metadata)
    if elc not in (LIFECYCLE_DEPRECATED, LIFECYCLE_ARCHIVED) and not is_revision_deprecated(m):
        raise ValueError(
            "sunsetAt requires a deprecated revision (set deprecated: true or lifecycle deprecated/archived)",
        )

    succ = m.get("successorRevisionId") or m.get("successor_revision_id")
    if isinstance(succ, str) and succ.strip():
        succ_id = succ.strip()
        if not is_uuid_string(succ_id):
            raise ValueError("successorRevisionId must be a UUID")

    dep_at_s = effective_deprecated_at_string(m)
    if dep_at_s:
        d_dep = parse_iso_utc_instant(dep_at_s)
        d_sun = parse_iso_utc_instant(sunset_s)
        if d_dep is not None and d_sun is not None and d_sun < d_dep:
            raise ValueError("sunsetAt must be on or after deprecatedAt")


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
    norm_sunset = effective_sunset_string(m)
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
    """Return an object for ``info.x-apiome-revision-deprecation`` or None."""
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
    sunset = effective_sunset_string(m)
    if sunset:
        out["sunsetAt"] = sunset
        out["sunsetDate"] = sunset
    return out


def warnings_for_revision(
    *,
    revision_id: str,
    version_label: str,
    role: str,
    metadata: Any,
) -> "List[RevisionDeprecationWarningOut]":
    """
    Build structured deprecation warnings for API responses (compatibility, etc.).

    role: ``base`` | ``head``
    """
    from .models import RevisionDeprecationWarningOut  # local import to avoid circular dependency

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
    sunset = effective_sunset_string(m)
    if sunset:
        parts.append(f"Sunset: {sunset}.")
    parts.append(f"Migration guide: {MIGRATION_GUIDE_ISSUE_URL}")

    return [
        RevisionDeprecationWarningOut(
            revision_id=revision_id,
            role=role,
            version_id=version_label,
            message=" ".join(parts),
            replacement_revision_id=succ.strip() if isinstance(succ, str) and succ.strip() else None,
            sunset_date=sunset if sunset else None,
            migration_guide_url=MIGRATION_GUIDE_ISSUE_URL,
        )
    ]
