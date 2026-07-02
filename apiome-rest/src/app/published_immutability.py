"""Published revision immutability (#2586): enterprise default; tenant-admin override with audit."""

from typing import Any, Dict, Optional


def revision_is_published_immutable(row: Optional[Dict[str, Any]]) -> bool:
    """True when the revision is published and marked immutable (writes blocked by default)."""
    if not row:
        return False
    if not bool(row.get("published")):
        return False
    if "published_immutable" in row:
        return bool(row["published_immutable"])
    return True


IMMUTABLE_DETAIL = {
    "code": "PUBLISHED_IMMUTABLE",
    "message": (
        "This revision is published and immutable. "
        "Tenant administrators may retry with overridePublishedImmutability and overrideReason for audit."
    ),
}
