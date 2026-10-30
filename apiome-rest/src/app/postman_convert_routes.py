"""Postman Collection → OpenAPI, through the import SPI — REST contract (MFI-32.7, #4409).

``POST /v1/import/{tenant_slug}/postman/openapi`` runs a Postman collection through the registered
:class:`~app.postman_import_source.PostmanImportSource` — parse, then normalize on the shared
inferred-spec engine with secret scrubbing (MFI-32.1 / MFI-32.5) — and emits the canonical model as
an OpenAPI 3.1 document with :class:`~app.openapi_emitter.OpenApiEmitter`.

It is what the web app's **Postman Collection** import card calls: the card used to convert in the
browser (the legacy ``postman-to-openapi`` converter, now behind ``FEATURE_LEGACY_POSTMAN_IMPORT``),
and still hands the OpenAPI it gets back to the Projects import wizard, so the destination is the
same while the content gains inferred schemas, scrubbed values and the adapter's warnings.

The call is stateless: nothing is stored. It needs the ``imports:create`` permission, like starting
an import.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .auth import validate_authentication
from .canonical_model import Server
from .database import db
from .import_source import ImportSourceError, get_import_source, load_builtin_import_sources
from .openapi_emitter import OpenApiEmitter
from .permissions import Action, Resource, enforce_permission
from .postman_normalizer import POSTMAN_EXTRAS_KEY

router = APIRouter(prefix="/v1/import", tags=["import-sources"])

#: The largest collection text accepted (characters). A collection this size is far past any real
#: export; the parser's own intake guards apply below it.
MAX_COLLECTION_CHARS = 10 * 1024 * 1024

#: ``info.version`` when the collection states none — Postman collections carry no API version, and
#: the Projects wizard proposes this value as the new version (the legacy converter's value too).
DEFAULT_VERSION = "1.0.0"

#: The most request names a warning lists before summarizing the rest.
_MAX_LISTED = 5


class PostmanToOpenApiRequest(BaseModel):
    """A Postman collection to convert."""

    document: str = Field(
        ...,
        min_length=1,
        max_length=MAX_COLLECTION_CHARS,
        description="The Postman Collection v2.0 or v2.1 JSON, as text.",
    )
    filename: Optional[str] = Field(default=None, description="The file name, for messages only.")
    base_url: Optional[str] = Field(
        default=None,
        max_length=2048,
        description="When given, the OpenAPI document's only server (replaces the collection's `baseUrl`).",
    )


class PostmanToOpenApiResponse(BaseModel):
    """The OpenAPI document a collection converts to, with what the conversion could not keep."""

    source_kind: str = Field(default="postman", description="The import adapter that read the collection.")
    openapi: Dict[str, Any] = Field(..., description="The OpenAPI 3.1 document.")
    warnings: List[str] = Field(
        default_factory=list,
        description="One sentence per declared limit (scripts, withheld credentials, merged requests …).",
    )


def _warnings(limits: List[Dict[str, Any]]) -> List[str]:
    """Render the adapter's declared limits as user-facing sentences.

    Args:
        limits: ``extras["postman"]["capability_limits"]`` records.

    Returns:
        One sentence per limit: its note, then where it occurs.
    """
    out: List[str] = []
    for limit in limits:
        note = str(limit.get("note") or "").strip()
        locations = [str(name) for name in (limit.get("locations") or [])]
        if not note:
            continue
        if locations:
            listed = ", ".join(locations[:_MAX_LISTED])
            more = len(locations) - _MAX_LISTED
            where = f"{listed} and {more} more" if more > 0 else listed
            note = f"{note} ({where})"
        out.append(note)
    return out


def convert_postman_to_openapi(
    text: str, *, base_url: Optional[str] = None, filename: Optional[str] = None
) -> PostmanToOpenApiResponse:
    """Run a collection through the Postman adapter and emit it as OpenAPI 3.1.

    Args:
        text: The collection JSON.
        base_url: When given, the document's only server.
        filename: Used as the source label in error messages.

    Returns:
        The OpenAPI document and the adapter's warnings.

    Raises:
        ImportSourceError: When the text is not a readable Postman collection (its ``code`` is the
            intake error taxonomy code).
    """
    load_builtin_import_sources()
    adapter = get_import_source("postman")
    api = adapter.normalize(adapter.parse(text, source_label=filename), include_raw=False)
    if base_url and base_url.strip():
        api.servers = [Server(url=base_url.strip())]
    if not api.version:
        api.version = DEFAULT_VERSION
    document = OpenApiEmitter().emit(api).document
    limits = (api.extras.get(POSTMAN_EXTRAS_KEY) or {}).get("capability_limits") or []
    return PostmanToOpenApiResponse(openapi=document, warnings=_warnings(limits))


@router.post(
    "/{tenant_slug}/postman/openapi",
    response_model=PostmanToOpenApiResponse,
    summary="Convert a Postman collection to OpenAPI",
    description=(
        "Read a Postman Collection v2.0 or v2.1 with the Postman import adapter — schemas inferred "
        "from example bodies, credentials scrubbed — and return it as an OpenAPI 3.1 document, with "
        "a warning for each thing the conversion leaves out. Nothing is stored. Requires "
        "``imports:create``."
    ),
)
async def postman_to_openapi(
    tenant_slug: str,
    body: PostmanToOpenApiRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PostmanToOpenApiResponse:
    _ = tenant_slug  # resolved and checked by ``validate_authentication``
    enforce_permission(db, auth_data, Resource.IMPORTS, Action.CREATE)
    try:
        return convert_postman_to_openapi(body.document, base_url=body.base_url, filename=body.filename)
    except ImportSourceError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": getattr(exc, "code", None) or "INPUT_MALFORMED", "message": str(exc)},
        ) from exc
