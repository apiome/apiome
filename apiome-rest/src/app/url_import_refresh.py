"""Refresh URL-sourced imports — the rules (RAR-6.1, #3538).

A spec imported into a project from a URL (the import wizard's **URL Import** source) is recorded
as a URL lineage (``apiome.url_import_specs``, :mod:`app.url_import_store`). On its cadence the
sweep (:mod:`app.url_import_refresh_sweep`) re-fetches the URL and decides what to do::

    cadence tick ──► conditional GET (If-None-Match / If-Modified-Since)
       304           → up to date, skip
       200, gated    → up to date, skip   (same content, or a Last-Modified older than the import)
       200, newer    → divergence guard   → edited in Apiome: hold
                                          → else: spec-faithful re-import (RAR-4.1)

This module holds those rules with no database, no network and no clock, so each is unit-testable:

* :func:`normalize_url` — the URL as stored (http/https only, no fragment, no credentials).
* :func:`conditional_headers` — the validators a check sends.
* :func:`decide_check` — the freshness gate: 304 skips; a 200 goes through the RAR-2.2 newer-than
  comparator (:func:`app.repository_refresh_comparator.evaluate_refresh`) on ``Last-Modified`` and
  the document's SHA-256, so the same content (RAR-2.4) or an older ``Last-Modified`` never
  re-imports. A lineage with no anchors yet only records them (``baseline``).
* :func:`divergence_for` — the RAR-4.4 guard on the version the last import produced.
* :func:`version_content_checksum` — that guard's content identity: the SHA-256 of the version's
  rendered OpenAPI document.
* :func:`build_refresh_request` — the spec-import request that replays the stored import spec
  onto the project as a new, date/time-labelled version.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit, urlunsplit

from .repository_divergence_guard import DivergenceDecision, compute_content_checksum, evaluate_divergence
from .repository_refresh_comparator import evaluate_refresh

__all__ = [
    "REASON_BASELINE",
    "REASON_NOT_MODIFIED",
    "STATUS_DIVERGED",
    "STATUS_FAILED",
    "STATUS_REFRESHED",
    "STATUS_REFRESHING",
    "STATUS_UP_TO_DATE",
    "CheckDecision",
    "UrlImportError",
    "build_refresh_request",
    "checksum_bytes",
    "conditional_headers",
    "decide_check",
    "divergence_for",
    "normalize_url",
    "parse_http_date",
    "version_content_checksum",
]

#: ``last_status`` values (``apiome.url_import_specs``).
STATUS_UP_TO_DATE = "up-to-date"
STATUS_REFRESHING = "refreshing"
STATUS_REFRESHED = "refreshed"
STATUS_DIVERGED = "diverged"
STATUS_FAILED = "failed"

#: ``last_reason`` codes this module adds to the RAR-2.2 ``RefreshReason`` vocabulary.
REASON_NOT_MODIFIED = "not-modified"
REASON_BASELINE = "baseline"


class UrlImportError(ValueError):
    """A URL that cannot be recorded or refreshed (not http/https, carries credentials)."""


def normalize_url(url: str) -> str:
    """The URL as a lineage stores it.

    Args:
        url: The URL the person imported from.

    Returns:
        The URL with its scheme and host lower-cased and its fragment dropped.

    Raises:
        UrlImportError: The URL is not http/https, has no host, or carries ``user:password@``
            (credentials are never stored, and such a URL could not refresh without them).
    """
    raw = (url or "").strip()
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise UrlImportError(f"Malformed URL: {raw}") from exc
    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UrlImportError("Only http and https URLs can be refreshed.")
    if not parts.hostname:
        raise UrlImportError("The URL has no host.")
    if parts.username or parts.password:
        raise UrlImportError("The URL carries credentials; they are never stored.")
    netloc = parts.netloc.lower()
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def checksum_bytes(content: bytes) -> str:
    """Lower-case hex SHA-256 of a fetched document."""
    return hashlib.sha256(content).hexdigest()


def parse_http_date(value: Optional[str]) -> Optional[datetime]:
    """An HTTP date (``Last-Modified``) as an aware datetime, or ``None`` when absent or invalid."""
    if not value or not str(value).strip():
        return None
    try:
        parsed = parsedate_to_datetime(str(value).strip())
    except (TypeError, ValueError, IndexError):
        return None
    return parsed


def conditional_headers(etag: Optional[str], last_modified: Optional[str]) -> Dict[str, str]:
    """The validators a check sends: ``If-None-Match`` and ``If-Modified-Since`` when stored."""
    headers: Dict[str, str] = {}
    if etag and etag.strip():
        headers["If-None-Match"] = etag.strip()
    if last_modified and last_modified.strip():
        headers["If-Modified-Since"] = last_modified.strip()
    return headers


@dataclass(frozen=True)
class CheckDecision:
    """What one check decided.

    Attributes:
        refresh: Re-import the fetched document (after the divergence guard).
        record_anchors: Store the fetched validators and checksum without importing
            (``baseline``: the lineage had none).
        reason: A stable code: :data:`REASON_NOT_MODIFIED`, :data:`REASON_BASELINE`, or a
            RAR-2.2 ``RefreshReason`` value (``newer-content``, ``idempotent``, ``stale``…).
        checksum: The fetched document's SHA-256 (``None`` on a 304).
    """

    refresh: bool
    record_anchors: bool
    reason: str
    checksum: Optional[str] = None


def decide_check(
    *,
    status_code: int,
    body: Optional[bytes],
    response_last_modified: Optional[str],
    stored_last_modified: Optional[str],
    stored_checksum: Optional[str],
) -> CheckDecision:
    """Apply the freshness gate to one conditional GET.

    Args:
        status_code: The response status: ``304`` or a ``2xx`` (the caller treats anything else
            as a failure).
        body: The response body on a 2xx.
        response_last_modified: The response's ``Last-Modified`` header.
        stored_last_modified: The ``Last-Modified`` recorded at the last import.
        stored_checksum: The SHA-256 recorded at the last import.

    Returns:
        The :class:`CheckDecision`.
    """
    if status_code == 304:
        return CheckDecision(refresh=False, record_anchors=False, reason=REASON_NOT_MODIFIED)
    checksum = checksum_bytes(body or b"")
    if not stored_checksum and not stored_last_modified:
        # Nothing to compare with (the import-time fetch failed): anchor on what is served now.
        return CheckDecision(refresh=False, record_anchors=True, reason=REASON_BASELINE, checksum=checksum)
    decision = evaluate_refresh(
        remote_committed_at=parse_http_date(response_last_modified),
        last_imported_committed_at=parse_http_date(stored_last_modified),
        remote_checksum=checksum,
        last_imported_checksum=stored_checksum,
    )
    return CheckDecision(
        refresh=decision.should_refresh, record_anchors=False, reason=decision.reason.value, checksum=checksum
    )


def divergence_for(post_import_checksum: Optional[str], current_checksum: Optional[str]) -> DivergenceDecision:
    """The RAR-4.4 guard, hold-not-clobber: a version edited since its import holds the refresh."""
    return evaluate_divergence(post_import_checksum=post_import_checksum, current_checksum=current_checksum)


def version_content_checksum(spec: Mapping[str, Any]) -> Optional[str]:
    """The content identity of a version: SHA-256 of its rendered OpenAPI document.

    Args:
        spec: The document :func:`app.spec_snapshot.build_live_spec` generates.

    Returns:
        The checksum, computed exactly as the divergence guard expects.
    """
    from .spec_snapshot import render_spec_bytes

    return compute_content_checksum(render_spec_bytes(spec).decode("utf-8"))


def build_refresh_request(
    row: Mapping[str, Any],
    *,
    content: bytes,
    version_label: str,
    content_type: Optional[str] = None,
) -> Any:
    """The spec-import request a refresh starts: the stored spec replayed onto the project.

    The request uses the spec-faithful re-import kind (``repository_auto_import``, RAR-4.1): the
    worker routes, parses and applies options from the stored spec, not from defaults. The new
    version is labelled ``version_label`` (a UTC date/time such as ``2026-10-30T14:03Z``) and,
    should that label exist, takes the next free sub-version.

    Args:
        row: The ``url_import_specs`` row.
        content: The fetched document.
        version_label: The new version's label.
        content_type: The response's ``Content-Type``; the stored one wins.

    Returns:
        A :class:`~app.models.SpecImportStartJsonRequest`.
    """
    from .models import (
        REPOSITORY_AUTO_IMPORT_SOURCE_KIND,
        RepositoryRefreshProvenance,
        SpecImportProjectTarget,
        SpecImportStartJsonRequest,
        SpecImportStartMetadata,
        SpecImportStoredSpec,
        SpecImportVersionTarget,
    )

    options = dict(row.get("options_json") or {})
    options.pop("dryRun", None)
    options["onVersionConflict"] = "create-version"
    parent = row.get("last_version_id")
    metadata = SpecImportStartMetadata(
        source_kind=REPOSITORY_AUTO_IMPORT_SOURCE_KIND,
        project=SpecImportProjectTarget(
            project_id=str(row["project_id"]), name=row.get("project_name"), slug=row.get("project_slug")
        ),
        version=SpecImportVersionTarget(version_id=version_label, description=f"Refreshed from {row['url']}"),
        repository_import_spec=SpecImportStoredSpec(
            source_kind=str(row.get("source_kind") or "openapi"),
            format_override=row.get("format_override"),
            content_type=row.get("content_type"),
            options=options,
            spec_schema_version=int(row.get("spec_schema_version") or 1),
        ),
        refresh_provenance=RepositoryRefreshProvenance(parent_version_id=str(parent) if parent else None),
    )
    path = urlsplit(str(row["url"])).path
    filename = path.rsplit("/", 1)[-1] or "spec"
    return SpecImportStartJsonRequest(
        metadata=metadata,
        document_base64=base64.standard_b64encode(content).decode("ascii"),
        filename=filename,
        content_type=row.get("content_type") or content_type,
    )
