"""``GET /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/provenance`` — DCW-2.4.

private-suite#2365. For every path, operation and component of a revision: whether it is as
imported, edited in Apiome, or edited through the source workspace; the stable ids it is known by
(its JSON Pointer, and the class or path id where one exists); and the original file, pointer and
digest behind it. ``?pointer=`` narrows the answer to the element that owns that pointer and adds a
bounded excerpt of the original import text.

Status is derived (:mod:`app.source_provenance`) from two recorded facts: the revision's import
snapshot (V362, written when the import committed; a draft uses its nearest ancestor's) and the
pointers DCW-2.3 source applies changed since. DCW-2.1 preserved fields come back with the file and
digest their claims recorded.

**Authorization:** ``projects:view`` — the same as reading the revision's lint report. The quoted
source is the scrubbed text the import kept, never anything a reader could not export.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import validate_authentication
from .compatibility_engine import openapi_for_revision
from .database import db
from .permissions import Action, Resource, enforce_permission
from .source_provenance import EXCERPT_MAX_LINES, classify_elements, escape_token, excerpt

__all__ = ["router"]

router = APIRouter(prefix="/v1/versions", tags=["source-provenance"])


class _Out(BaseModel):
    """camelCase on the wire; populated by field name."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SourceExcerpt(_Out):
    """Lines of the original import text behind an element."""

    start_line: int = Field(description="First quoted line (1-based).")
    end_line: int = Field(description="Last quoted line (1-based).")
    text: str = Field(description="The quoted lines, as the import stored them (secret-scrubbed).")
    truncated: bool = Field(description=f"True when the value runs past the {EXCERPT_MAX_LINES}-line limit.")


class ElementProvenanceOut(_Out):
    """One element's provenance."""

    pointer: str = Field(description="The element's JSON Pointer in the generated document — its stable id.")
    kind: Literal["path", "operation", "component"] = Field(description="What the element is.")
    entity_id: Optional[str] = Field(default=None, description="The class or path id, where the element has one.")
    status: Literal["imported", "local", "source-edited"] = Field(
        description="As imported; edited in Apiome; or edited through the source workspace."
    )
    source_file: Optional[str] = Field(
        default=None, description="The file the import came from, for an imported element."
    )
    source_pointer: Optional[str] = Field(
        default=None, description="Where the element sat in that file, when it was there."
    )
    source_digest: Optional[str] = Field(default=None, description="sha256 digest of the imported file.")
    last_source_edit_at: Optional[str] = Field(default=None, description="When a source apply last changed it.")
    excerpt: Optional[SourceExcerpt] = Field(default=None, description="The original text — only with `?pointer=`.")


class PreservedProvenanceOut(_Out):
    """A DCW-2.1 preserved field and the source it was claimed from."""

    pointer: str
    source_file: Optional[str] = None
    source_digest: Optional[str] = None


class ImportSnapshotOut(_Out):
    """The import the statuses are measured against."""

    version_record_id: str = Field(description="The revision that was imported (this one or an ancestor).")
    source_file: Optional[str] = None
    source_format: str
    source_digest: str
    imported_at: Optional[str] = None
    text_available: bool = Field(description="False when the import's text was withheld, so no excerpt exists.")


class SourceProvenanceResponse(_Out):
    """A revision's source provenance."""

    version_record_id: str
    snapshot: Optional[ImportSnapshotOut] = Field(
        default=None,
        description=(
            "Null when no import in the revision's lineage was recorded: every element then reads "
            "`local`, except those a source apply changed."
        ),
    )
    elements: List[ElementProvenanceOut]
    preserved: List[PreservedProvenanceOut]
    counts: Dict[str, int] = Field(description="Elements per status.")


def _iso(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _owning_element(pointer: str, elements: List[ElementProvenanceOut]) -> Optional[ElementProvenanceOut]:
    """The deepest element whose pointer is ``pointer`` or contains it."""
    owners = [e for e in elements if pointer == e.pointer or pointer.startswith(e.pointer + "/")]
    return max(owners, key=lambda e: len(e.pointer)) if owners else None


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/provenance",
    response_model=SourceProvenanceResponse,
    response_model_by_alias=True,
    summary="Get the source provenance of a revision's paths, operations and components",
    description=(
        "For every path, operation and component: `imported` (unchanged since the import), "
        "`source-edited` (changed through a source apply since) or `local` (changed or created in "
        "Apiome), keyed by JSON Pointer with the class or path id where one exists, plus the "
        "imported file and its digest. A draft is measured against its nearest ancestor's import.\n\n"
        "`?pointer=` returns only the element that owns that pointer, with an excerpt of the "
        f"original import text (at most {EXCERPT_MAX_LINES} lines).\n\nRequires `projects:view`."
    ),
)
async def get_source_provenance(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    pointer: Optional[str] = Query(default=None, description="Narrow to the element owning this JSON Pointer."),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SourceProvenanceResponse:
    """Project the revision's source provenance.

    Args:
        tenant_slug: The tenant in the URL (shapes document generation).
        project_id: The owning project.
        version_record_id: The revision.
        pointer: Optional pointer to narrow to, adding an excerpt.
        auth_data: The authenticated principal.

    Returns:
        The provenance.

    Raises:
        HTTPException: 404 for an unknown revision (never 403, so existence does not leak), 422 for
            a pointer that is not an RFC 6901 pointer, 403 without ``projects:view``.
    """
    enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW)
    tenant_id = str(auth_data.get("tenant_id") or "")
    version = db.get_version_by_id(version_record_id, tenant_id) if tenant_id else None
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail="Version not found")
    if pointer is not None and pointer != "" and not pointer.startswith("/"):
        raise HTTPException(status_code=422, detail="pointer must be an RFC 6901 JSON Pointer")

    current = openapi_for_revision(version, tenant_slug, tenant_id)
    snapshot, chain = db.get_import_snapshot_lineage(version_record_id, tenant_id)
    edits = db.list_source_edits(chain, tenant_id)
    imported_doc = snapshot.get("canonical_document") if snapshot else None
    classified = classify_elements(current, imported_doc, [row["pointer"] for row in edits])

    class_ids = {row["name"]: str(row["id"]) for row in db.get_classes_for_version(version_record_id)}
    path_ids = {row["pathname"]: str(row["id"]) for row in db.get_paths_for_version(version_record_id)}
    entity_ids: Dict[str, str] = {f"/components/schemas/{escape_token(n)}": i for n, i in class_ids.items()}
    entity_ids.update({f"/paths/{escape_token(p)}": i for p, i in path_ids.items()})

    def last_edit(element_pointer: str) -> Optional[str]:
        for row in edits:  # newest first
            p = row["pointer"]
            if p == element_pointer or p.startswith(element_pointer + "/") or element_pointer.startswith(p + "/"):
                return _iso(row.get("created_at"))
        return None

    elements = [
        ElementProvenanceOut(
            pointer=e.pointer,
            kind=e.kind,
            entity_id=entity_ids.get(e.pointer),
            status=e.status,
            source_file=snapshot.get("source_file") if snapshot and e.in_import else None,
            source_pointer=e.pointer if e.in_import else None,
            source_digest=snapshot.get("source_digest") if snapshot and e.in_import else None,
            last_source_edit_at=last_edit(e.pointer) if e.status == "source-edited" else None,
        )
        for e in classified
    ]

    if pointer is not None:
        owner = _owning_element(pointer, elements)
        elements = [owner] if owner else []
        text = snapshot.get("source_text") if snapshot else None
        if owner and owner.source_pointer and text:
            quoted = excerpt(text, owner.source_pointer)
            owner.excerpt = (
                SourceExcerpt(
                    **{
                        "start_line": quoted["startLine"],
                        "end_line": quoted["endLine"],
                        "text": quoted["text"],
                        "truncated": quoted["truncated"],
                    }
                )
                if quoted
                else None
            )

    preserved = [
        PreservedProvenanceOut(
            pointer=row["pointer"], source_file=row.get("source_file"), source_digest=row.get("source_digest")
        )
        for row in db.get_preservation_claims(tenant_id, project_id, version_record_id)
        if row.get("source_file") or row.get("source_digest")
    ]
    counts = {
        status: sum(1 for e in classified if e.status == status) for status in ("imported", "local", "source-edited")
    }
    return SourceProvenanceResponse(
        version_record_id=version_record_id,
        snapshot=ImportSnapshotOut(
            version_record_id=str(snapshot["version_id"]),
            source_file=snapshot.get("source_file"),
            source_format=snapshot["source_format"],
            source_digest=snapshot["source_digest"],
            imported_at=_iso(snapshot.get("created_at")),
            text_available=bool(snapshot.get("source_text")),
        )
        if snapshot
        else None,
        elements=elements,
        preserved=preserved,
        counts=counts,
    )
