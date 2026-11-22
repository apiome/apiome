"""Read a revision's OpenAPI document as a workspace member (COA-5.13, #7089).

* ``GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/document`` — the revision's
  OpenAPI document, rendered from its classes, properties, paths, servers and security schemes.

This is the document the UI shows: the version view, the compare view, the catalog's version
diff and the spec of a merge request or review. It differs from the public
``GET /v1/schema/{tenant}/{project}/{version}`` in three ways:

* it is addressed by record id and needs ``versions:view``, so a draft can be read;
* it declares OpenAPI 3.2 and writes the 3.2 constructs natively;
* it keeps the operations marked ``x-private``, each carrying ``x-private: true``.

The document is rendered once per change of the revision and kept in the document store
(:data:`app.rendered_documents.KIND_OPENAPI_MEMBERS`); later requests stream the stored bytes.
The answer carries ``ETag: "<sha256>"`` and ``X-Apiome-Content-Sha256``. Send the ETag back as
``If-None-Match`` to get ``304`` with no body while the document is unchanged; two revisions with
the same digest have the same document. ``X-Apiome-Document-Cache`` says ``hit`` when the bytes
came from the store and ``miss`` when this request rendered them.

Errors: ``404`` for an unknown revision (or one of another tenant or project), ``502``
``document-unreadable`` when the store no longer returns the stored bytes.

Permission: ``versions:view``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response, StreamingResponse

from .auth import validate_authentication
from .database import db
from .document_store import DocumentStoreError
from .permissions import Action, Resource, enforce_permission
from .rendered_documents import KIND_OPENAPI_MEMBERS, etag_matches, iter_stream, rendered_document
from .revision_deprecation import is_uuid_string

logger = logging.getLogger(__name__)

# Registered before ``versions_router`` in main.py, like the other literal-suffix version routes.
router = APIRouter(prefix="/v1/versions", tags=["versions"])

#: Says whether the bytes came from the document store (``hit``) or were rendered (``miss``).
DOCUMENT_CACHE_HEADER = "X-Apiome-Document-Cache"

_HEADERS: Dict[str, Dict[str, Any]] = {
    "ETag": {"description": "`\"<sha256>\"` of the document.", "schema": {"type": "string"}},
    "X-Apiome-Content-Sha256": {
        "description": "SHA-256 of the document; equal for two revisions with the same document.",
        "schema": {"type": "string"},
    },
    DOCUMENT_CACHE_HEADER: {
        "description": "`hit` when the stored document was served, `miss` when it was rendered now.",
        "schema": {"type": "string", "enum": ["hit", "miss"]},
    },
}
_RESPONSES: Dict[int | str, Dict[str, Any]] = {
    200: {
        "description": "The revision's OpenAPI 3.2 document, as compact JSON.",
        "content": {"application/json": {"schema": {"type": "object", "additionalProperties": True}}},
        "headers": _HEADERS,
    },
    304: {"description": "`If-None-Match` names the current ETag; no body."},
    404: {"description": "Unknown revision, or one of another workspace or project."},
    502: {"description": "`document-unreadable`: the document store did not return the stored bytes."},
}


def _not_found(version_record_id: str) -> HTTPException:
    """The ``404`` of a revision the caller cannot address."""
    return HTTPException(status_code=404, detail=f"Version not found: {version_record_id}")


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/document",
    response_class=StreamingResponse,
    responses=_RESPONSES,
)
async def get_version_document(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    if_none_match: Optional[str] = Header(
        None,
        alias="If-None-Match",
        description="An ETag from an earlier response; the answer is 304 while the document is unchanged.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Response:
    """Read a revision's OpenAPI document, draft or published (COA-5.13).

    The document a workspace member sees in the UI: OpenAPI 3.2, private operations kept. It is
    served from the document store once rendered; ``If-None-Match`` answers ``304``.

    Args:
        tenant_slug: The workspace slug (the workspace is taken from the credentials).
        project_id: The project (or catalog item) UUID the revision belongs to.
        version_record_id: The revision UUID (``versions.id``).
        if_none_match: ETag(s) the caller already holds.
        auth_data: The authenticated caller.

    Returns:
        The document streamed as JSON, or ``304`` with no body.

    Raises:
        HTTPException: ``404`` for an unknown revision, ``502`` when the stored bytes are gone.
    """
    _ = tenant_slug
    tenant_id = str(auth_data["tenant_id"])
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    if not is_uuid_string((version_record_id or "").strip()) or not is_uuid_string((project_id or "").strip()):
        raise _not_found(version_record_id)
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise _not_found(version_record_id)

    document = rendered_document(version_record_id, KIND_OPENAPI_MEMBERS, tenant_id=tenant_id, database=db)
    if document is None:
        raise _not_found(version_record_id)
    headers = {
        "ETag": document.etag,
        "Cache-Control": "private, no-cache",
        "X-Apiome-Content-Sha256": document.sha256,
        DOCUMENT_CACHE_HEADER: "hit" if document.cached else "miss",
    }
    if etag_matches(if_none_match, document.sha256):
        return Response(status_code=304, headers=headers)
    try:
        stream = document.open_stream()
    except DocumentStoreError as exc:
        logger.warning("members document unreadable version_id=%s: %s", version_record_id, type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail={"code": "document-unreadable", "message": "The document store did not return the document."},
        ) from None
    headers["Content-Length"] = str(document.size_bytes)
    return StreamingResponse(iter_stream(stream), media_type=document.media_type, headers=headers)
