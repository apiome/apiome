"""MCP catalog collections validation (V2-MCP-36.4 / MCAT-22.4, #4667).

Named collections group tenant endpoints for navigation and optional public sharing. This module
normalizes collection names, slugs, and member lists before persistence.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List

MAX_COLLECTION_NAME_CHARS = 120
MAX_COLLECTION_DESCRIPTION_CHARS = 2_000
MAX_COLLECTION_MEMBERS = 500

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class CollectionValidationError(ValueError):
    """Raised when a collection field fails validation."""


def slugify_collection_name(name: str) -> str:
    """Derive a URL-safe slug from a collection name."""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return base or "collection"


def normalize_collection_name(raw: str | None) -> str:
    """Strip and validate a collection display name."""
    text = (raw or "").strip()
    if not text:
        raise CollectionValidationError("Collection name is required")
    if len(text) > MAX_COLLECTION_NAME_CHARS:
        raise CollectionValidationError(
            f"Collection name exceeds maximum length ({MAX_COLLECTION_NAME_CHARS} characters)"
        )
    return text


def normalize_collection_slug(raw: str | None, *, fallback_name: str | None = None) -> str:
    """Strip and validate a collection slug (or derive one from ``fallback_name``)."""
    text = (raw or "").strip().lower()
    if not text and fallback_name:
        text = slugify_collection_name(fallback_name)
    if not text:
        raise CollectionValidationError("Collection slug is required")
    if len(text) > 80:
        raise CollectionValidationError("Collection slug exceeds maximum length (80 characters)")
    if not _SLUG_RE.match(text):
        raise CollectionValidationError(
            "Collection slug must contain only lowercase letters, numbers, and hyphens"
        )
    return text


def normalize_collection_description(raw: str | None) -> str | None:
    """Strip and bound an optional collection description."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    if len(text) > MAX_COLLECTION_DESCRIPTION_CHARS:
        raise CollectionValidationError(
            "Collection description exceeds maximum length "
            f"({MAX_COLLECTION_DESCRIPTION_CHARS} characters)"
        )
    return text


def normalize_collection_member_ids(raw: Any) -> List[str]:
    """Validate a list of endpoint ids for collection membership."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CollectionValidationError("endpointIds must be an array")
    out: List[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            raise CollectionValidationError("endpointIds must contain string ids")
        endpoint_id = item.strip()
        if not endpoint_id:
            raise CollectionValidationError("endpointIds must not contain empty values")
        if endpoint_id in seen:
            continue
        seen.add(endpoint_id)
        out.append(endpoint_id)
    if len(out) > MAX_COLLECTION_MEMBERS:
        raise CollectionValidationError(
            f"A collection may contain at most {MAX_COLLECTION_MEMBERS} endpoints"
        )
    return out


def merge_member_ids(existing: Iterable[str], additions: Iterable[str]) -> List[str]:
    """Append unique endpoint ids while preserving order and the member cap."""
    return normalize_collection_member_ids(list(existing) + list(additions))


__all__ = [
    "CollectionValidationError",
    "MAX_COLLECTION_DESCRIPTION_CHARS",
    "MAX_COLLECTION_MEMBERS",
    "MAX_COLLECTION_NAME_CHARS",
    "merge_member_ids",
    "normalize_collection_description",
    "normalize_collection_member_ids",
    "normalize_collection_name",
    "normalize_collection_slug",
    "slugify_collection_name",
]
