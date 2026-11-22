"""Download a revision's original file (COA-5.7, #7083).

* ``GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/original`` — the document the
  import read (after the tenant's secret scrub), under its original file name. For a set of files
  (an archive, a multi-file import) this is the set's JSON manifest, which lists every file.
* ``GET …/original/{part_path}`` — one file of a set, by its path inside the set.

Both answer with ``ETag: "<sha256 of the content>"``, ``Accept-Ranges: bytes`` and an
``X-Apiome-Content-Sha256`` header; ``If-None-Match`` gives ``304`` and a single ``Range``
``206`` (``416`` past the end). With ``?redirect=presigned`` and a store that can sign links
(``s3``), a content stored as it is answers ``302`` to a short-lived presigned URL instead; every
other case streams, so the parameter is always safe to send.

Errors carry ``detail.code``: ``404 original-not-stored`` when nothing was stored (or no file at
``part_path``), ``410 original-withheld`` when the import withheld the source under the tenant's
intake policy, ``404`` for an unknown revision, ``502 original-unreadable`` when the store no
longer returns the bytes.

Permission: ``versions:view``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import RedirectResponse, Response, StreamingResponse

from .auth import validate_authentication
from .database import db
from .document_store import DocumentStoreError, get_document_store
from .tenant_document_store import TenantDocumentStoreUnavailable
from .download_headers import attachment_headers
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string
from .version_original import (
    OriginalNotStoredError,
    OriginalWithheldError,
    RangeNotSatisfiableError,
    ResolvedOriginal,
    describe,
    etag_matches,
    iter_stream,
    materialize,
    parse_range,
    resolve_original,
)

logger = logging.getLogger(__name__)

# Registered before ``versions_router`` in main.py, like the other literal-suffix version routes.
router = APIRouter(prefix="/v1/versions", tags=["versions"])

#: Lifetime of the presigned link ``?redirect=presigned`` answers with, in seconds.
PRESIGNED_TTL_SECONDS = 300

_ERRORS: Dict[int, Dict[str, Any]] = {
    206: {"description": "The requested byte range (`Content-Range` names it)."},
    302: {"description": "`?redirect=presigned`: a short-lived presigned URL in `Location`."},
    304: {"description": "`If-None-Match` names the current ETag."},
    404: {"description": "Unknown revision, or `original-not-stored`: nothing stored (or no file at the path)."},
    410: {"description": "`original-withheld`: the import withheld the source under the intake policy."},
    416: {"description": "The `Range` starts past the end; `Content-Range: bytes */<size>`."},
    502: {"description": "`original-unreadable`: the document store did not return the bytes."},
}
_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    200: {
        "description": "The original file, streamed, with `ETag`, `Accept-Ranges` and `Content-Disposition`.",
        "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
        "headers": {
            "ETag": {"description": "`\"<sha256>\"` of the content.", "schema": {"type": "string"}},
            "X-Apiome-Content-Sha256": {
                "description": "SHA-256 of the bytes served (the whole file).",
                "schema": {"type": "string"},
            },
        },
    },
    **_ERRORS,
}


def _require_revision(tenant_id: str, project_id: str, version_record_id: str) -> Dict[str, Any]:
    """Resolve the revision inside the tenant and project, or raise ``404``."""
    if not is_uuid_string((version_record_id or "").strip()) or not is_uuid_string((project_id or "").strip()):
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")
    return version


def _resolve(tenant_id: str, version_record_id: str, part_path: Optional[str]) -> ResolvedOriginal:
    """Find the object to serve, mapping a missing or withheld source onto its error."""
    try:
        return resolve_original(db, tenant_id, version_record_id, part_path)
    except OriginalWithheldError as exc:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "original-withheld",
                "reason": exc.reason,
                "message": "The import withheld this source under the tenant's intake policy.",
            },
        ) from None
    except OriginalNotStoredError as exc:
        raise HTTPException(status_code=404, detail={"code": "original-not-stored", "message": str(exc)}) from None


def _presigned(resolved: ResolvedOriginal, headers: Dict[str, str]) -> Optional[str]:
    """A presigned link for content stored as it is, or ``None`` when the store cannot sign one."""
    if not resolved.served_as_stored or resolved.sha256 is None:
        return None
    try:
        return get_document_store().presign_get(
            resolved.tenant_id,
            resolved.sha256,
            PRESIGNED_TTL_SECONDS,
            content_disposition=headers["Content-Disposition"],
            content_type=resolved.media_type,
        )
    except DocumentStoreError as exc:
        logger.warning("original presign failed: %s", type(exc).__name__)
        return None


def _serve(
    tenant_id: str,
    version_record_id: str,
    part_path: Optional[str],
    *,
    redirect: Optional[str],
    range_header: Optional[str],
    if_none_match: Optional[str],
    if_range: Optional[str],
) -> Response:
    """Answer one download of an original (the whole file, a range, a 304, or a redirect)."""
    resolved = _resolve(tenant_id, version_record_id, part_path)
    disposition = attachment_headers(resolved.filename, fallback="original")
    if redirect == "presigned":
        url = _presigned(resolved, disposition)
        if url is not None:
            return RedirectResponse(url=url, status_code=302, headers={"Cache-Control": "private, no-store"})
    # An object stored as it is has the content's digest already: a revalidation reads nothing.
    if resolved.served_as_stored and resolved.sha256 and etag_matches(if_none_match, resolved.sha256):
        return Response(
            status_code=304, headers={"ETag": f'"{resolved.sha256}"', "Cache-Control": "private, no-cache"}
        )
    try:
        content = materialize(get_document_store(), resolved)
    except TenantDocumentStoreUnavailable:
        # The workspace's own bucket is down (COA-5.15): the original is unavailable, and the
        # app-level handler answers 503 tenant-document-store-unavailable with the reason.
        raise
    except (DocumentStoreError, ValueError) as exc:
        logger.warning(
            "original unreadable version_id=%s %s: %s", version_record_id, describe(resolved), type(exc).__name__
        )
        raise HTTPException(
            status_code=502,
            detail={"code": "original-unreadable", "message": "The document store did not return the original."},
        ) from None
    etag = f'"{content.sha256}"'
    headers = {
        **disposition,
        "ETag": etag,
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, no-cache",
        "X-Apiome-Content-Sha256": content.sha256,
    }
    if etag_matches(if_none_match, content.sha256):
        content.close()
        return Response(status_code=304, headers={key: headers[key] for key in ("ETag", "Cache-Control")})
    # ``If-Range`` with another validator means "the file changed": send all of it.
    use_range = range_header if (not if_range or etag_matches(if_range, content.sha256)) else None
    try:
        span = parse_range(use_range, content.size)
    except RangeNotSatisfiableError:
        content.close()
        return Response(status_code=416, headers={"Content-Range": f"bytes */{content.size}", "ETag": etag})
    if span is None:
        headers["Content-Length"] = str(content.size)
        return StreamingResponse(iter_stream(content), media_type=resolved.media_type, headers=headers)
    start, end = span
    headers["Content-Range"] = f"bytes {start}-{end}/{content.size}"
    headers["Content-Length"] = str(end - start + 1)
    return StreamingResponse(
        iter_stream(content, start, end), status_code=206, media_type=resolved.media_type, headers=headers
    )


_REDIRECT = Query(
    None,
    description=(
        "`presigned`: answer `302` to a short-lived presigned URL when the store can sign one "
        "(`s3`) and the content is stored as it is; otherwise the file is streamed."
    ),
)


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/original",
    response_class=StreamingResponse,
    responses=_RESPONSES,
)
def get_version_original(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    redirect: Optional[Literal["presigned"]] = _REDIRECT,
    range_header: Optional[str] = Header(None, alias="Range"),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
    if_range: Optional[str] = Header(None, alias="If-Range"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Download the file the import stored for a revision (COA-5.7).

    For a single document this is the document; for a set of files it is the set's manifest
    (``application/vnd.apiome.fileset-manifest+json``), whose ``members`` name each file to
    fetch from ``…/original/{part_path}``.
    """
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    _require_revision(tenant_id, project_id, version_record_id)
    return _serve(
        tenant_id,
        version_record_id,
        None,
        redirect=redirect,
        range_header=range_header,
        if_none_match=if_none_match,
        if_range=if_range,
    )


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/original/{part_path:path}",
    response_class=StreamingResponse,
    responses=_RESPONSES,
)
def get_version_original_part(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    part_path: str,
    redirect: Optional[Literal["presigned"]] = _REDIRECT,
    range_header: Optional[str] = Header(None, alias="Range"),
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
    if_range: Optional[str] = Header(None, alias="If-Range"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Download one file of a revision's stored set of files, by its path inside the set (COA-5.7)."""
    _ = tenant_slug
    tenant_id = auth_data["tenant_id"]
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    _require_revision(tenant_id, project_id, version_record_id)
    return _serve(
        tenant_id,
        version_record_id,
        part_path,
        redirect=redirect,
        range_header=range_header,
        if_none_match=if_none_match,
        if_range=if_range,
    )
