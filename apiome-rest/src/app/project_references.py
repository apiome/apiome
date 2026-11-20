"""The References tab's logic — COA-2.8 (#7051).

Pure decisions behind ``/v1/projects/{tenant}/{project}/references``; the routes
(:mod:`app.project_references_routes`) load the document and the stored rows, and write what these
functions decide.

* :func:`classify_fetch` turns one refresh's fetch into a stored outcome. A fetch that worked is
  compared with the **pin** when the reference is pinned, else with the previous snapshot: the
  same digest is ``ok``, a different one is ``changed`` with a JSON Pointer diff
  (:func:`app.openapi_ref_hygiene.json_value_diff`). The first fetch of a reference has nothing
  to compare with, so it is ``ok``. A fetch the tenant policy, the deployment kill switch or the
  SSRF guard refused is ``blocked``; any other failure is ``unreachable``. A failed fetch keeps
  the previous snapshot.
* :func:`reference_view` merges a reference found in the document with its stored row into what
  the panel shows (``not-fetched`` when it was never refreshed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import urlsplit

from .openapi_ref_hygiene import json_value_diff
from .remote_ref_resolver import REASON_BLOCKED, FetchedDocument
from .repository_external_ref_policy import (
    REASON_ALLOWLIST_EMPTY,
    REASON_HOST_NOT_ALLOWLISTED,
    REASON_INVALID_URL,
    REASON_POLICY_BLOCKED,
    REASON_RESOLUTION_DISABLED,
    REASON_UNSUPPORTED_SCHEME,
)

__all__ = [
    "BLOCKED_REASONS",
    "STATUS_NOT_FETCHED",
    "FetchOutcome",
    "classify_fetch",
    "reference_view",
    "summarize",
]

#: A fetch refused on purpose — by the tenant policy, the kill switch or the SSRF guard.
BLOCKED_REASONS = frozenset(
    {
        REASON_POLICY_BLOCKED,
        REASON_HOST_NOT_ALLOWLISTED,
        REASON_ALLOWLIST_EMPTY,
        REASON_RESOLUTION_DISABLED,
        REASON_UNSUPPORTED_SCHEME,
        REASON_INVALID_URL,
        REASON_BLOCKED,
    }
)

#: The status shown for a reference no refresh has checked yet (never stored).
STATUS_NOT_FETCHED = "not-fetched"


@dataclass(frozen=True)
class FetchOutcome:
    """What one refresh of one reference decided, ready for :func:`app.project_external_ref_store.record_check`.

    Attributes:
        status: ``ok``, ``changed``, ``unreachable`` or ``blocked``.
        reason: Machine reason for a refusal or failure.
        detail: Human explanation for a refusal or failure.
        digest: The fetched document's digest, when the fetch worked.
        document: The fetched document, when the fetch worked.
        diff: The change found (``{changes, total, truncated, against}``), or ``None``.
    """

    status: str
    reason: Optional[str] = None
    detail: Optional[str] = None
    digest: Optional[str] = None
    document: Any = None
    diff: Optional[Dict[str, Any]] = None


def classify_fetch(fetched: FetchedDocument, previous: Optional[Mapping[str, Any]]) -> FetchOutcome:
    """Decide the outcome of one refresh.

    Args:
        fetched: What :func:`app.remote_ref_resolver.fetch_remote_documents` returned for the URL.
        previous: The reference's stored row (``content_digest``, ``document``, ``pinned_digest``,
            ``pinned_document``), or ``None`` for a first refresh.

    Returns:
        The :class:`FetchOutcome`.
    """
    if fetched.document is None or not fetched.digest:
        reason = fetched.reason or "fetch-failed"
        status = "blocked" if reason in BLOCKED_REASONS else "unreachable"
        return FetchOutcome(status=status, reason=reason, detail=fetched.detail or None)

    row = previous or {}
    if row.get("pinned_digest"):
        against, baseline_digest, baseline = "pin", row.get("pinned_digest"), row.get("pinned_document")
    else:
        against, baseline_digest, baseline = "previous", row.get("content_digest"), row.get("document")

    if not baseline_digest or baseline_digest == fetched.digest:
        return FetchOutcome(status="ok", digest=fetched.digest, document=fetched.document)
    diff = json_value_diff(baseline, fetched.document)
    diff["against"] = against
    diff["from_digest"] = baseline_digest
    diff["to_digest"] = fetched.digest
    return FetchOutcome(status="changed", digest=fetched.digest, document=fetched.document, diff=diff)


def reference_view(group: Mapping[str, Any], row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """What the panel shows for one external reference.

    Args:
        group: ``{url, locations}`` from :func:`app.openapi_ref_hygiene.external_ref_groups`.
        row: The reference's stored row, or ``None`` when it was never refreshed.

    Returns:
        ``{url, host, locations, status, reason, detail, digest, fetched_at, checked_at, pinned,
        diff}`` — ``pinned`` is ``{digest, at}`` or ``None``; the documents themselves are not
        included.
    """
    url = str(group["url"])
    stored = row or {}
    pinned_digest = stored.get("pinned_digest")
    return {
        "url": url,
        "host": (urlsplit(url).hostname or "").lower(),
        "locations": list(group.get("locations") or []),
        "status": stored.get("status") or STATUS_NOT_FETCHED,
        "reason": stored.get("reason"),
        "detail": stored.get("detail"),
        "digest": stored.get("content_digest"),
        "fetched_at": stored.get("fetched_at"),
        "checked_at": stored.get("checked_at"),
        "pinned": {"digest": pinned_digest, "at": stored.get("pinned_at")} if pinned_digest else None,
        "diff": stored.get("diff"),
    }


def summarize(references: List[Mapping[str, Any]]) -> Dict[str, int]:
    """Count references per status, for the panel's summary line.

    Args:
        references: :func:`reference_view` rows.

    Returns:
        ``status → count`` (only statuses that occur).
    """
    counts: Dict[str, int] = {}
    for reference in references:
        counts[str(reference["status"])] = counts.get(str(reference["status"]), 0) + 1
    return counts
