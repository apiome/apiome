"""The cursor and page-size plumbing every paginated MCP tool shares (apiome #7196).

``project.list``, ``spec.list``, ``spec.search`` and ``spec.list_tags`` page the same way as the
REST API: an opaque keyset cursor, a ``limit`` with a hard maximum, and ``has_more`` /
``next_cursor`` in the result. Each tool's cursor carries its own sort key, but the envelope is
one format — a versioned JSON object, base64url without ``=`` padding — and lives here once.
"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "clamp_page_limit",
    "cursor_timestamp",
    "decode_cursor_payload",
    "encode_cursor_payload",
    "utc",
]


def utc(value: datetime) -> datetime:
    """Return ``value`` in UTC; a naive datetime is taken to be UTC already.

    Args:
        value: Any datetime.

    Returns:
        The same instant, timezone-aware, in UTC.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def encode_cursor_payload(payload: dict[str, Any]) -> str:
    """Serialise a cursor payload.

    Args:
        payload: The tool's sort-key fields plus its ``v`` version.

    Returns:
        A stable URL-safe cursor: compact JSON with sorted keys, base64url without ``=`` padding.
    """
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor_payload(
    raw: str | None, *, tool: str, version: int, error: type[ValueError]
) -> dict[str, Any] | None:
    """Read a cursor's payload back and check its envelope.

    Args:
        raw: The ``cursor`` argument; ``None`` means the first page.
        tool: The tool's name for error messages (``spec.list``).
        version: The cursor version the tool issues.
        error: The tool's invalid-cursor exception class.

    Returns:
        The payload object, or ``None`` when no cursor was given.

    Raises:
        ValueError: An instance of ``error`` when the cursor is empty, is not base64url JSON, is
            not an object, or carries another version.
    """
    if raw is None:
        return None
    if not raw.strip():
        raise error(f"Invalid {tool} cursor (empty value).")
    text = raw.strip()
    try:
        blob = base64.urlsafe_b64decode(text + "=" * ((4 - len(text) % 4) % 4))
        payload = json.loads(blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError, binascii.Error) as exc:
        raise error(f"Invalid {tool} cursor (malformed encoding).") from exc
    if not isinstance(payload, dict):
        raise error(f"Invalid {tool} cursor (expected JSON object).")
    found = payload.get("v")
    if found != version:
        raise error(f"Unsupported {tool} cursor version: {found!r}.")
    return payload


def cursor_timestamp(value: str, *, tool: str, error: type[ValueError]) -> datetime:
    """Parse a cursor's ISO-8601 timestamp field.

    Args:
        value: The field as stored in the cursor (``Z`` or an explicit offset).
        tool: The tool's name for error messages.
        error: The tool's invalid-cursor exception class.

    Returns:
        The instant, in UTC.

    Raises:
        ValueError: An instance of ``error`` when the text is not a timestamp or has no offset.
    """
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise error(f"Invalid {tool} cursor (bad timestamp).") from exc
    if parsed.tzinfo is None:
        raise error(f"Invalid {tool} cursor (timestamp must include timezone offset).")
    return utc(parsed)


def clamp_page_limit(limit: int | None, *, default: int, maximum: int) -> int:
    """Resolve a requested page size against a tool's bounds.

    Args:
        limit: The requested size; ``None`` for the default.
        default: The size used when none is requested.
        maximum: The tool's hard maximum.

    Returns:
        A size in ``[1, maximum]``.

    Raises:
        ValueError: When ``limit`` is below 1.
    """
    if limit is None:
        return default
    if limit < 1:
        raise ValueError(f"limit must be at least 1, got {limit}.")
    return min(limit, maximum)
