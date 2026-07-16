"""CTG-1.2 classified OpenAPI diff REST endpoint (#4468).

``POST /v1/diff/{tenant_slug}/classified`` compares a stored base revision to either
another stored revision or an uploaded (inline) candidate OpenAPI document, and
returns the CTG-1.1 classified change list with summary counts and max severity.

When ``Accept`` requests ``text/markdown`` (or ``text/md``), the response is the
CTG-1.3 markdown changelog instead of JSON (CTG-2.1 / #4471).
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import validate_authentication
from .change_taxonomy import ClassifiedDiff, classify_openapi_changes
from .changelog_generator import build_changelog, render_changelog_markdown
from .compatibility_engine import openapi_for_revision
from .database import db
from .import_ingestion import IngestionError, parse_document
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string

router = APIRouter(prefix="/v1/diff", tags=["classified-diff"])

#: Hard cap on UTF-8 size of an inline OpenAPI document (acceptance: 10MB).
INLINE_SPEC_MAX_BYTES = 10 * 1024 * 1024

_MARKDOWN_ACCEPT_TOKENS = ("text/markdown", "text/md")


def _wants_markdown(accept: Optional[str]) -> bool:
    """Return True when the client prefers CTG-1.3 markdown over JSON."""
    if not accept:
        return False
    lowered = accept.lower()
    return any(token in lowered for token in _MARKDOWN_ACCEPT_TOKENS)


class ClassifiedDiffStoredRef(BaseModel):
    """Reference to a stored project revision (slug/UUID + version label/UUID/latest)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project: str = Field(
        description="Project slug or project UUID within the authenticated tenant.",
    )
    version: str = Field(
        description=(
            "Version label (e.g. ``1.0.0``), revision UUID, or the literal ``latest``."
        ),
    )


class ClassifiedDiffInlineHead(BaseModel):
    """Uploaded candidate OpenAPI document as raw YAML or JSON text."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    inline: str = Field(
        description="Raw OpenAPI 3.x document as YAML or JSON text (max 10MB UTF-8).",
    )


class ClassifiedDiffRequest(BaseModel):
    """Request body for classified diff: stored base vs stored or inline head."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    base: ClassifiedDiffStoredRef = Field(
        description="Stored baseline revision (published contract / older side).",
    )
    head: Union[ClassifiedDiffStoredRef, ClassifiedDiffInlineHead] = Field(
        description=(
            "Head side: either another stored ``{project, version}`` or "
            "``{inline}`` candidate document text."
        ),
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_head(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        head = data.get("head")
        if not isinstance(head, dict):
            return data
        has_inline = "inline" in head
        has_project = "project" in head
        has_version = "version" in head
        if has_inline and (has_project or has_version):
            raise ValueError(
                "head must be either a stored ref {project, version} or {inline}, not both"
            )
        if has_inline:
            data = {**data, "head": ClassifiedDiffInlineHead.model_validate(head)}
        elif has_project or has_version:
            data = {**data, "head": ClassifiedDiffStoredRef.model_validate(head)}
        else:
            raise ValueError(
                "head must be either a stored ref {project, version} or {inline}"
            )
        return data


class ClassifiedDiffResolvedStored(BaseModel):
    """Resolved coordinates for a stored side of the comparison."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    project_id: str = Field(serialization_alias="projectId")
    project_slug: str = Field(serialization_alias="projectSlug")
    version_record_id: str = Field(serialization_alias="versionRecordId")
    version_label: str = Field(serialization_alias="versionLabel")


class ClassifiedDiffHeadMeta(BaseModel):
    """Resolved head metadata (stored coords when source is stored)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source: Literal["stored", "inline"]
    project_id: Optional[str] = Field(default=None, serialization_alias="projectId")
    project_slug: Optional[str] = Field(default=None, serialization_alias="projectSlug")
    version_record_id: Optional[str] = Field(
        default=None, serialization_alias="versionRecordId"
    )
    version_label: Optional[str] = Field(default=None, serialization_alias="versionLabel")


class ClassifiedDiffChangeOut(BaseModel):
    """One classified change in the API response."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    rule_id: str = Field(serialization_alias="ruleId")
    severity: str
    pointer: str
    before: Any = None
    after: Any = None
    unclassified: bool = False
    change_kind: str = Field(default="", serialization_alias="changeKind")


class ClassifiedDiffResponse(BaseModel):
    """Classified change list with summary counts, max severity, and resolved sides."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    changes: list[ClassifiedDiffChangeOut] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)
    max_severity: Optional[str] = Field(default=None, serialization_alias="maxSeverity")
    base: ClassifiedDiffResolvedStored
    head: ClassifiedDiffHeadMeta


def _resolve_project(tenant_id: str, project_ref: str) -> Dict[str, Any]:
    """Resolve project slug or UUID to a project row for the tenant.

    Args:
        tenant_id: Authenticated tenant id.
        project_ref: Project slug or UUID.

    Returns:
        Project row with at least ``id`` and ``slug``.

    Raises:
        HTTPException: 404 when the project is not found in the tenant.
    """
    ref = (project_ref or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="project is required")
    if is_uuid_string(ref):
        row = db.get_project_by_id(ref, tenant_id)
    else:
        row = db.get_project_by_slug(ref, tenant_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"Project not found: {ref}")
    return row


def _resolve_version_row(
    tenant_id: str, project_id: str, version_ref: str
) -> Dict[str, Any]:
    """Resolve version label, revision UUID, or ``latest`` to a versions row.

    Args:
        tenant_id: Authenticated tenant id.
        project_id: Owning project UUID.
        version_ref: Version label, revision UUID, or ``latest``.

    Returns:
        Version row including ``id``, ``version_id``, ``project_id``.

    Raises:
        HTTPException: 400 for empty ref; 404 when the revision cannot be found.
    """
    requested = (version_ref or "").strip()
    if not requested:
        raise HTTPException(status_code=400, detail="version is required")

    if requested.lower() == "latest":
        latest_id = db.get_latest_revision_id_for_project(project_id, tenant_id)
        if not latest_id:
            raise HTTPException(
                status_code=404,
                detail=f"Project {project_id!r} has no versions",
            )
        row = db.get_version_by_id(str(latest_id), tenant_id)
        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"Revision not found: {latest_id}",
            )
        return row

    if is_uuid_string(requested):
        row = db.get_version_by_id(requested, tenant_id)
        if not row or str(row.get("project_id")) != str(project_id):
            raise HTTPException(
                status_code=404,
                detail=f"Revision not found: {requested}",
            )
        return row

    row = db.get_version_by_version_id(project_id, requested, tenant_id)
    if not row:
        raise HTTPException(
            status_code=404,
            detail=f"Version {requested!r} was not found for project {project_id!r}",
        )
    return row


def _resolve_stored_side(
    tenant_id: str, tenant_slug: str, ref: ClassifiedDiffStoredRef
) -> tuple[Dict[str, Any], ClassifiedDiffResolvedStored, Dict[str, Any]]:
    """Resolve a stored ref to OpenAPI document + response metadata.

    Returns:
        ``(openapi_doc, resolved_meta, version_row)``.
    """
    project = _resolve_project(tenant_id, ref.project)
    version = _resolve_version_row(tenant_id, str(project["id"]), ref.version)
    doc = openapi_for_revision(version, tenant_slug, tenant_id)
    meta = ClassifiedDiffResolvedStored(
        project_id=str(project["id"]),
        project_slug=str(project["slug"]),
        version_record_id=str(version["id"]),
        version_label=str(version["version_id"]),
    )
    return doc, meta, version


def _parse_inline(inline: str) -> Dict[str, Any]:
    """Validate size and parse an inline OpenAPI document.

    Args:
        inline: Raw YAML or JSON text.

    Returns:
        Parsed OpenAPI document mapping.

    Raises:
        HTTPException: 413 when over the 10MB cap; 400 when empty/unparseable.
    """
    if inline is None:
        raise HTTPException(status_code=400, detail="inline document is empty")
    size = len(inline.encode("utf-8"))
    if size > INLINE_SPEC_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Inline OpenAPI document exceeds the {INLINE_SPEC_MAX_BYTES}-byte "
                f"limit ({size} bytes)"
            ),
        )
    try:
        return parse_document(inline, source_label="inline")
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


def _response_from_classified(
    result: ClassifiedDiff,
    *,
    base_meta: ClassifiedDiffResolvedStored,
    head_meta: ClassifiedDiffHeadMeta,
) -> ClassifiedDiffResponse:
    """Map a pure ClassifiedDiff onto the REST response model."""
    return ClassifiedDiffResponse(
        changes=[
            ClassifiedDiffChangeOut(
                rule_id=c.rule_id,
                severity=c.severity,
                pointer=c.pointer,
                before=c.before,
                after=c.after,
                unclassified=c.unclassified,
                change_kind=c.change_kind,
            )
            for c in result.changes
        ],
        counts=dict(result.counts),
        max_severity=result.max_severity,
        base=base_meta,
        head=head_meta,
    )


@router.post(
    "/{tenant_slug}/classified",
    response_model=ClassifiedDiffResponse,
    responses={
        200: {
            "description": (
                "Classified JSON by default, or CTG-1.3 markdown when "
                "``Accept: text/markdown`` (or ``text/md``) is sent."
            ),
            "content": {
                "text/markdown": {
                    "schema": {"type": "string", "contentMediaType": "text/markdown"}
                },
            },
        }
    },
)
async def post_classified_diff(
    tenant_slug: str,
    body: ClassifiedDiffRequest,
    accept: Optional[str] = Header(None),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Union[ClassifiedDiffResponse, Response]:
    """Classify changes between a stored base revision and a stored or inline head.

    Supports **stored-vs-stored** (``head: {project, version}``) and
    **inline-vs-stored** (``head: {inline}``) for the CI PR use case. Inline
    documents larger than 10MB UTF-8 are rejected with ``413``.

    Default response is JSON (:class:`ClassifiedDiffResponse`). When ``Accept``
    includes ``text/markdown`` or ``text/md``, returns the CTG-1.3 markdown
    changelog for the same classification (used by ``apiome diff --format md``).
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = str(auth_data["tenant_id"])

    base_doc, base_meta, _ = _resolve_stored_side(tenant_id, tenant_slug, body.base)

    if isinstance(body.head, ClassifiedDiffInlineHead):
        head_doc = _parse_inline(body.head.inline)
        head_meta = ClassifiedDiffHeadMeta(source="inline")
    else:
        head_doc, stored_head, _ = _resolve_stored_side(
            tenant_id, tenant_slug, body.head
        )
        head_meta = ClassifiedDiffHeadMeta(
            source="stored",
            project_id=stored_head.project_id,
            project_slug=stored_head.project_slug,
            version_record_id=stored_head.version_record_id,
            version_label=stored_head.version_label,
        )

    result = classify_openapi_changes(base_doc, head_doc)

    if _wants_markdown(accept):
        to_version = head_meta.version_label or "inline"
        changelog = build_changelog(
            result,
            from_version=base_meta.version_label,
            to_version=to_version,
        )
        md = render_changelog_markdown(changelog)
        return Response(content=md, media_type="text/markdown; charset=utf-8")

    return _response_from_classified(result, base_meta=base_meta, head_meta=head_meta)
