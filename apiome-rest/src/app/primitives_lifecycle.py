"""
Type deprecation lifecycle — the rules, with no I/O (#3482, 7.5).

A registry type can be *deprecated*: marked as one that should no longer be picked up, with an
optional sunset date, an optional message and an optional replacement type. Deprecation is an
advisory marker — a deprecated type still resolves, validates and can be bound — so the only
rules are about the record itself being coherent. They live here, apart from the routes
(``primitives_lifecycle_routes.py``), so they can be tested without a database.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

#: Longest deprecation message accepted (mirrors ``PrimitiveDeprecateRequest.message``).
MAX_MESSAGE_LENGTH = 500


def today_utc() -> date:
    """Return today's date in UTC — the day a sunset date is compared against."""
    return datetime.now(timezone.utc).date()


def normalize_message(message: Optional[str]) -> Optional[str]:
    """Trim a deprecation message; an empty or whitespace-only one is no message.

    Args:
        message: The message as the caller sent it.

    Returns:
        The trimmed message, or None when there is nothing left.
    """
    trimmed = (message or "").strip()
    return trimmed or None


def sunset_date_error(sunset_date: Optional[date], today: date) -> Optional[str]:
    """Say why a sunset date is not acceptable, if it is not.

    A sunset date announces when a type stops being supported, so one that has already passed
    is a mistake. Today is allowed: "retire this as of now" is a legitimate thing to record.

    Args:
        sunset_date: The requested sunset date, or None when the caller set none.
        today: The current date (UTC).

    Returns:
        A message for the caller, or None when the date is acceptable.
    """
    if sunset_date is not None and sunset_date < today:
        return f"sunset_date {sunset_date.isoformat()} is in the past"
    return None


def replacement_error(
    primitive_id: str,
    replacement_id: Optional[str],
    replacement: Optional[Mapping[str, Any]],
) -> Optional[str]:
    """Say why a replacement type is not acceptable, if it is not.

    The replacement is where readers of a deprecated type are sent, so it must be a type they
    can see, a different type, and one that is not itself on the way out.

    Args:
        primitive_id: The id of the type being deprecated.
        replacement_id: The requested replacement id, or None when the caller named none.
        replacement: The replacement's row as the tenant can see it, or None when no visible
            type has that id.

    Returns:
        A message for the caller, or None when the replacement is acceptable (or absent).
    """
    if replacement_id is None:
        return None
    if str(replacement_id) == str(primitive_id):
        return "A type cannot be its own replacement"
    if replacement is None:
        return f"Replacement type not found: {replacement_id}"
    if replacement.get("deprecated_at") is not None:
        return f"Replacement type '{replacement.get('name')}' is itself deprecated"
    return None


def replacement_summary(replacement: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Reduce a replacement type's row to what a reader needs to follow it.

    Args:
        replacement: The replacement's row, or None.

    Returns:
        ``{id, name, schema_id}``, or None when there is no replacement.
    """
    if replacement is None:
        return None
    return {
        "id": str(replacement["id"]),
        "name": replacement.get("name"),
        "schema_id": replacement.get("schema_id"),
    }


def audit_detail(row: Mapping[str, Any], *, was_deprecated: bool) -> Dict[str, Any]:
    """Build the registry-audit ``detail`` for a deprecation.

    Args:
        row: The primitive row after the write.
        was_deprecated: True when the type was already deprecated (its details were changed).

    Returns:
        A JSON-serializable detail object.
    """
    sunset = row.get("sunset_date")
    replacement_id = row.get("replacement_id")
    return {
        "name": row.get("name"),
        "sunset_date": sunset.isoformat() if isinstance(sunset, date) else sunset,
        "message": row.get("deprecation_message"),
        "replacement_id": str(replacement_id) if replacement_id is not None else None,
        "updated_existing": was_deprecated,
    }


def collect_errors(*errors: Optional[str]) -> List[str]:
    """Drop the absent entries from a list of optional error messages."""
    return [error for error in errors if error]
