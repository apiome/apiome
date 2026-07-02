"""
Import-source enumeration & format detection — REST contract (MFI-1.3 / MFI-1.5).

Exposes the import-source registry (MFI-1.1) as a read-only list so the UI's
``ImportDialog`` can render its source cards from data instead of hard-coded JSX,
and the CLI (MFI-1.4) can list available formats. Each entry is the registry's
public :class:`~app.import_source.ImportSourceDescriptor` — key, label,
description, Lucide ``icon`` name, paradigm, accepted ``input_kinds``
(file/url/paste/discovery), live-discovery capability, and emitted ``formats``.

Adding an adapter server-side (a new ``ImportSource`` subclass with
``register=True``) makes it appear here automatically, so a new source card shows
up in the UI with no UI code change.

``POST /v1/import/detect`` (MFI-1.5) sniffs a document's format so the importer —
UI or CLI — can pre-select the right source and, when the input is ambiguous,
prompt the user instead of guessing.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from .auth import validate_session_credentials
from .format_detection import FormatCandidate, FormatDetection, detect_format
from .import_source import (
    DetectionInput,
    ImportSourceDescriptor,
    describe_import_sources,
)

router = APIRouter(prefix="/v1/import", tags=["import-sources"])


class ImportSourceListResponse(BaseModel):
    """The list of registered import sources, for source-card / CLI enumeration."""

    sources: List[ImportSourceDescriptor] = Field(
        default_factory=list,
        description="Every registered adapter's descriptor, sorted by key.",
    )


@router.get(
    "/sources",
    response_model=ImportSourceListResponse,
    summary="List import sources",
    description=(
        "Enumerate every registered import-source adapter (MFI-1.1 registry). "
        "Drives the ImportDialog source cards (MFI-1.3) and the CLI format list "
        "(MFI-1.4): each descriptor carries the Lucide icon, label, description, "
        "and the input kinds (file/url/paste/discovery) its card/verb should use."
    ),
)
async def list_import_sources(
    auth_data: Dict[str, Any] = Depends(validate_session_credentials),
) -> ImportSourceListResponse:
    # The source list is non-tenant registry metadata: authentication is required
    # (consistent with the rest of the API) but no per-tenant scoping applies. This
    # uses the session-credentials dependency rather than validate_authentication
    # precisely because there is no ``{tenant_slug}`` path segment here — the
    # tenant-scoped dependency would otherwise make ``tenant_slug`` a *required query
    # parameter* the caller never sends, rejecting every real call with 422.
    _ = auth_data
    return ImportSourceListResponse(sources=describe_import_sources())


class DetectFormatRequest(BaseModel):
    """A document (plus optional hints) to auto-detect the format of."""

    text: Optional[str] = Field(
        default=None,
        description="Raw document text to sniff (the primary signal).",
    )
    filename: Optional[str] = Field(
        default=None, description="Optional filename hint (extension-based signals)."
    )
    content_type: Optional[str] = Field(
        default=None, description="Optional MIME type hint."
    )
    url: Optional[str] = Field(default=None, description="Optional source URL hint.")


class FormatCandidateModel(BaseModel):
    """One ranked format guess (mirrors :class:`app.format_detection.FormatCandidate`)."""

    format: str = Field(description="Detected format key (e.g. asyncapi-2, graphql).")
    confidence: float = Field(description="0.0–1.0 certainty from the matching detector.")
    reason: Optional[str] = Field(default=None, description="Short marker justification.")
    source_key: Optional[str] = Field(
        default=None, description="Registry key of the importable adapter, or null for sniffer-only."
    )
    importable: bool = Field(
        description="Whether a registered adapter can import this format today."
    )

    @classmethod
    def from_candidate(cls, candidate: FormatCandidate) -> "FormatCandidateModel":
        """Adapt a detection candidate into its serializable response shape."""
        return cls(
            format=candidate.format,
            confidence=candidate.confidence,
            reason=candidate.reason,
            source_key=candidate.source_key,
            importable=candidate.importable,
        )


class DetectFormatResponse(BaseModel):
    """The auto-detection verdict for a document."""

    matched: bool = Field(description="Whether any detector recognized the document.")
    detected: Optional[FormatCandidateModel] = Field(
        default=None, description="The best candidate, or null when nothing matched."
    )
    ambiguous: bool = Field(
        description="True when leading formats tie within the ambiguity margin (prompt the user)."
    )
    candidates: List[FormatCandidateModel] = Field(
        default_factory=list, description="All distinct-format candidates, ranked."
    )
    ambiguous_candidates: List[FormatCandidateModel] = Field(
        default_factory=list,
        description="The close cluster to choose between when ambiguous; empty otherwise.",
    )

    @classmethod
    def from_detection(cls, detection: FormatDetection) -> "DetectFormatResponse":
        """Adapt a :class:`FormatDetection` into the REST response shape."""
        return cls(
            matched=detection.matched,
            detected=(
                FormatCandidateModel.from_candidate(detection.detected)
                if detection.detected is not None
                else None
            ),
            ambiguous=detection.ambiguous,
            candidates=[FormatCandidateModel.from_candidate(c) for c in detection.candidates],
            ambiguous_candidates=[
                FormatCandidateModel.from_candidate(c) for c in detection.ambiguous_candidates
            ],
        )


@router.post(
    "/detect",
    response_model=DetectFormatResponse,
    summary="Auto-detect a document's import format",
    description=(
        "Sniff a document's format (MFI-1.5) by polling every registered adapter "
        "and the built-in format sniffers; the highest-confidence match wins. "
        "Recognized-but-not-yet-importable formats (RAML, AsyncAPI, GraphQL, …) "
        "are reported with ``importable: false`` so the importer can name the "
        "format. When two formats tie within the ambiguity margin, ``ambiguous`` "
        "is true and ``ambiguous_candidates`` lists the choices to prompt for."
    ),
)
async def detect_import_format(
    body: DetectFormatRequest,
    auth_data: Dict[str, Any] = Depends(validate_session_credentials),
) -> DetectFormatResponse:
    # Detection is pure registry/sniffer metadata over the supplied document; auth is
    # required (consistent with the API) but no per-tenant scoping applies. Uses the
    # session-credentials dependency for the same reason as ``/sources`` above: with no
    # ``{tenant_slug}`` path segment, the tenant-scoped dependency would make
    # ``tenant_slug`` a required query parameter and 422 every real call.
    _ = auth_data
    detection = detect_format(
        DetectionInput(
            text=body.text,
            filename=body.filename,
            content_type=body.content_type,
            url=body.url,
        )
    )
    return DetectFormatResponse.from_detection(detection)
