"""Record the original of an import that did not run through the REST import job (COA-5.3, #7079).

The apiome-ui import wizard and its repository file import decompose an OpenAPI, Swagger or
Arazzo document into a revision themselves, so no REST import job sees the file. After such an
import succeeds, the wizard sends the text it read here:

* ``POST /v1/tenants/{tenant}/import-originals`` — keep the document as the revision's original
  (``imports:create``).

The text is scrubbed under the tenant's secret-scrub policy and stored exactly as a REST import
job stores it (:func:`app.spec_import_engine._record_worker_import_snapshot`). Guards:

* only the user who created the revision may record its original;
* a revision keeps the first original it was given; a later call changes nothing;
* the document passes the same size, alias and depth limits as an upload.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from .auth import validate_authentication
from .database import db
from .import_ingestion import IngestionError, parse_document
from .intake_resource_guard import IntakeLimitError, guard_payload_bytes, resolve_guard_profile
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string
from .spec_import_engine import _record_worker_import_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/tenants", tags=["spec-import"])


class ImportOriginalRequest(BaseModel):
    """The document an import that just succeeded was read from."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version_id: str = Field(alias="versionId", description="The revision the import produced (versions.id).")
    content: str = Field(min_length=1, description="The document text, as it was read: JSON or YAML.")
    filename: Optional[str] = Field(
        default=None, description="The file name or URL the document came from.", max_length=4096
    )


class ImportOriginalOut(BaseModel):
    """What was kept for the revision."""

    model_config = ConfigDict(populate_by_name=True)

    stored: bool = Field(
        description="True when this call recorded the original. False when the revision already had one, "
        "or the document is not OpenAPI, Swagger or Arazzo."
    )
    sha256: Optional[str] = Field(default=None, description="SHA-256 of the stored object.")
    content_sha256: Optional[str] = Field(
        default=None,
        alias="contentSha256",
        description="SHA-256 of the stored text (after the secret scrub). "
        "Equals sha256 unless the object is gzip-coded.",
    )
    size_bytes: Optional[int] = Field(
        default=None, alias="sizeBytes", description="Length of the stored text in bytes."
    )
    media_type: Optional[str] = Field(default=None, alias="mediaType", description="Media type of the document.")
    encoding: Optional[str] = Field(default=None, description="Content coding of the stored object: identity or gzip.")


@router.post(
    "/{tenant_slug}/import-originals",
    response_model=ImportOriginalOut,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    summary="Record the original document of an import",
)
async def record_import_original(
    tenant_slug: str,
    body: ImportOriginalRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ImportOriginalOut:
    """Keep the document a finished import was read from as the revision's original.

    For an import that ran outside the REST import job (the apiome-ui import wizard). The text is
    scrubbed under the tenant's secret-scrub policy before it is stored, and for OpenAPI and
    Swagger an import snapshot is recorded with it. A revision keeps its first original: calling
    again answers ``stored: false`` and changes nothing.

    Raises:
        HTTPException: 403 when the caller did not create the revision; 404 when the revision is
            not the tenant's; 413 when the document is over the upload size limit; 422 when it is
            not parseable JSON or YAML or breaches another intake limit.
    """
    tenant_id = auth_data.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="No tenant context for imports.")
    tenant_id = str(tenant_id)
    actor_id = await run_in_threadpool(
        enforce_permission, db, auth_data, Resource.IMPORTS, Action.CREATE, target="import-originals"
    )
    version = None
    if is_uuid_string(body.version_id):
        version = await run_in_threadpool(db.get_version_by_id, body.version_id, tenant_id)
    if not version:
        raise HTTPException(status_code=404, detail=f"Version not found: {body.version_id}")
    if str(version.get("creator_id") or "") != str(actor_id):
        raise HTTPException(status_code=403, detail="Only the user who created the version can record its original.")

    raw = body.content.encode("utf-8")
    try:
        guard_payload_bytes(raw, source_label=body.filename, limits=resolve_guard_profile(tenant_id=tenant_id))
    except IntakeLimitError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    try:
        parse_document(body.content, source_label=body.filename)
    except (IngestionError, IntakeLimitError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload = {
        "tenant_id": tenant_id,
        "user_id": actor_id,
        "filename": body.filename,
        "document_base64": base64.standard_b64encode(raw).decode("ascii"),
    }
    stored = await asyncio.to_thread(
        _record_worker_import_snapshot, tenant_id, tenant_slug, str(version["id"]), payload
    )
    if stored is None:
        return ImportOriginalOut(stored=False)
    return ImportOriginalOut(
        stored=True,
        sha256=stored.sha256,
        content_sha256=stored.content_sha256,
        size_bytes=stored.size_bytes,
        media_type=stored.media_type,
        encoding=stored.encoding,
    )
