"""Source-to-model change review REST API — DCW-2.3 (private-suite#2360).

The transactional review/apply surface for the Designer's editable source
workspace (DCW-2.2):

* ``POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/source-review``
  — parse a candidate source text and classify it against the revision's
  current merged document (server-generated canonical + live preservation
  envelope) into additions / updates / deletions / unsupported-preserved
  changes grouped by document, path, operation, component, and schema, with
  structural **blockers** (referenced-component deletions with every
  referencing pointer, model-owned values, unrepresentable shared shapes).
  Never mutates anything. The response carries the **base digest** and the
  **change-set digest** the apply must present.

* ``POST /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/source-apply``
  — apply the reviewed candidate once, in a single database transaction
  (``Database.apply_source_change_set``): tenant scope, published-
  immutability, draft-lock ownership, and the VERSIONS/EDIT permission are
  rechecked **inside** the transaction after a FOR UPDATE row lock; a stale
  base digest answers 409 with the current digest and resolution choices
  (rebase/reparse — never last-write-wins); replaying an applied change set
  is idempotent; canonical rows, preservation payload, and the audit entry
  commit or roll back together, so a failed apply leaves the revision
  unchanged.

Both endpoints run the same dialect (meta-schema) validation and local
``$ref`` integrity checks as the export surface, so review, apply, and
export can never disagree about validity.

Authorization: both endpoints require the VERSIONS/EDIT permission. Scope
misses answer 404 (not 403) so cross-tenant probes cannot confirm a revision
exists.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import get_authenticated_user_id, validate_authentication
from .database import SourceApplyConflictError, db
from .openapi_generator import generate_openapi_spec
from .openapi_validator import validate_openapi_document
from .permissions import Action, Resource, enforce_permission
from .preservation_envelope import (
    PreservationClaim,
    PreservationEnvelope,
    apply_envelope,
)
from .safe_oas_parse import safe_oas_parse
from .source_change_review import (
    RefIntegrityError,
    SourceChange,
    SourceChangeBlocker,
    SourceChangeCounts,
    build_source_change_set,
    ref_integrity_errors,
)

router = APIRouter(prefix="/v1/versions", tags=["versions"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SourceReviewRequest(_CamelModel):
    """A candidate source text to classify against the revision."""

    source_text: str = Field(description="The full candidate source text.")
    source_format: Literal["yaml", "json"] = Field(
        default="yaml", description="Serialization of source_text."
    )


class SourceApplyRequest(SourceReviewRequest):
    """Apply a reviewed candidate under optimistic concurrency."""

    base_digest: str = Field(
        description="The baseDigest the review endpoint returned; the apply "
        "is rejected as stale when the revision no longer fingerprints to it."
    )
    change_set_digest: str = Field(
        description="The changeSetDigest the review endpoint returned for "
        "this candidate against that base."
    )


class SourceChangeSetBody(_CamelModel):
    """The classified diff in the review response."""

    base_digest: str
    candidate_digest: str
    change_set_digest: str
    changes: List[SourceChange]
    counts: SourceChangeCounts
    blockers: List[SourceChangeBlocker]


class SourceReviewResponse(_CamelModel):
    """Review outcome: the classified change set, nothing mutated."""

    dialect: str
    change_set: SourceChangeSetBody


class SourceApplyResponse(_CamelModel):
    """Apply outcome: exactly one revision mutation, or an idempotent no-op."""

    applied: bool
    already_applied: bool = False
    no_changes: bool = False
    result_digest: str
    audit_id: Optional[str] = None
    counts: Optional[SourceChangeCounts] = None
    enrichments: List[str] = Field(
        default_factory=list,
        description="Pointers the generator deterministically added during "
        "the apply (reported, never silent).",
    )
    claim_count: int = Field(
        default=0, description="Preservation claims live after the apply."
    )


class SourceInvalidBody(_CamelModel):
    """422 body: the candidate is not applyable source, nothing mutated."""

    code: str = Field(default="SOURCE_INVALID")
    diagnostics: List[Dict[str, Any]] = Field(default_factory=list)
    openapi_issues: List[Dict[str, Any]] = Field(default_factory=list)
    ref_integrity: List[RefIntegrityError] = Field(default_factory=list)


def _version_or_404(tenant_id: str, project_id: str, version_record_id: str) -> Dict[str, Any]:
    """Tenant-scoped version row, or 404 (never 403 — do not leak existence)."""
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _stored_dialect(version: Dict[str, Any]) -> str:
    """The dialect recorded on the revision metadata, defaulting to 3.1.0."""
    metadata = version.get("metadata")
    if isinstance(metadata, dict):
        dialect = metadata.get("oasDialect")
        if isinstance(dialect, str) and dialect:
            return dialect
    return "3.1.0"


def _parse_candidate(source_text: str, source_format: str) -> Dict[str, Any]:
    """Parse and validate a candidate exactly like the export surface would.

    All-or-nothing: resource-limit and syntax diagnostics (DCW-0.2 safe
    parser), then the dialect meta-schema, then local ``$ref`` integrity.
    Any failure answers 422 with the structured findings and no mutation.
    """
    parse_result = safe_oas_parse(source_text, source_format)
    if not parse_result.ok:
        raise HTTPException(
            status_code=422,
            detail=SourceInvalidBody(
                diagnostics=[
                    d.model_dump(by_alias=True) for d in parse_result.diagnostics
                ]
            ).model_dump(by_alias=True),
        )
    document = parse_result.document
    if not isinstance(document, dict):
        raise HTTPException(
            status_code=422,
            detail=SourceInvalidBody(
                diagnostics=[
                    {
                        "code": "OAS_NOT_AN_OBJECT",
                        "message": "The candidate must be a single OpenAPI document object.",
                        "severity": "error",
                    }
                ]
            ).model_dump(by_alias=True),
        )
    openapi_issues = validate_openapi_document(document)
    if openapi_issues:
        raise HTTPException(
            status_code=422,
            detail=SourceInvalidBody(openapi_issues=openapi_issues).model_dump(
                by_alias=True
            ),
        )
    ref_errors = ref_integrity_errors(document)
    if ref_errors:
        raise HTTPException(
            status_code=422,
            detail=SourceInvalidBody(ref_integrity=ref_errors).model_dump(by_alias=True),
        )
    return document


def _generated_canonical_document(version: Dict[str, Any], tenant_slug: str) -> Dict[str, Any]:
    """The revision's canonical OpenAPI document, generated server-side.

    Same generation path as export and the preservation envelope, so the
    review always classifies against what the server would actually emit —
    never against a client-supplied document.
    """
    classes = db.get_classes_for_version(version["id"])
    all_properties: Dict[str, List[Dict[str, Any]]] = {}
    for class_data in classes:
        all_properties[class_data["id"]] = db.get_properties_for_class(class_data["id"])
    return generate_openapi_spec(
        tenant_slug,
        str(version.get("project_slug") or version["project_id"]),
        str(version["version_id"]),
        classes,
        all_properties,
        version.get("project_description"),
        version_db_id=version["id"],
        revision_metadata=version.get("metadata"),
        project_metadata=version.get("project_metadata"),
    )


def _current_merged_document(
    version: Dict[str, Any], tenant_id: str, tenant_slug: str, project_id: str, dialect: str
) -> Dict[str, Any]:
    """Canonical + live preservation envelope: what the source editor edits."""
    canonical = _generated_canonical_document(version, tenant_slug)
    claim_rows = db.get_preservation_claims(tenant_id, project_id, str(version["id"]))
    envelope = PreservationEnvelope(
        dialect=dialect,
        claims=[
            PreservationClaim(
                pointer=row["pointer"],
                value=row["payload"],
                source_file=row.get("source_file"),
                source_digest=row.get("source_digest"),
            )
            for row in claim_rows
        ],
    )
    merged, _errors = apply_envelope(canonical, envelope)
    return merged


_APPLY_CONFLICT_STATUS = {
    "version_not_found": 404,
    "published_version": 409,
    "draft_lock_conflict": 409,
    "permission_denied": 403,
    "stale_base": 409,
    "change_set_mismatch": 409,
    "blocked": 409,
    "apply_fidelity": 422,
    "apply_lossy": 422,
}

_APPLY_CONFLICT_CODE = {
    "published_version": "PUBLISHED_IMMUTABLE",
    "draft_lock_conflict": "DRAFT_LOCK_CONFLICT",
    "permission_denied": "PERMISSION_DENIED",
    "stale_base": "STALE_BASE",
    "change_set_mismatch": "CHANGE_SET_MISMATCH",
    "blocked": "SOURCE_APPLY_BLOCKED",
    "apply_fidelity": "SOURCE_APPLY_FIDELITY",
    "apply_lossy": "SOURCE_APPLY_LOSSY",
}


def _raise_apply_conflict(error: SourceApplyConflictError) -> None:
    status = _APPLY_CONFLICT_STATUS.get(error.code, 409)
    if error.code == "version_not_found":
        raise HTTPException(status_code=404, detail="Version not found")
    detail: Dict[str, Any] = {"code": _APPLY_CONFLICT_CODE.get(error.code, error.code)}
    detail.update(error.payload)
    if error.code == "stale_base":
        # Conflict resolution is a choice, never last-write-wins: the client
        # must rebase onto the current revision and re-review, or discard.
        detail["choices"] = ["rebase-reparse", "discard"]
    raise HTTPException(status_code=status, detail=detail)


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/source-review",
    response_model=SourceReviewResponse,
    response_model_by_alias=True,
)
async def review_source_changes(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: SourceReviewRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SourceReviewResponse:
    """Classify a candidate source text against the revision. Never mutates."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    version = _version_or_404(tenant_id, project_id, version_record_id)
    candidate = _parse_candidate(body.source_text, body.source_format)
    dialect = _stored_dialect(version)
    merged = _current_merged_document(version, tenant_id, tenant_slug, project_id, dialect)
    change_set = build_source_change_set(merged, candidate, dialect)
    return SourceReviewResponse(
        dialect=dialect,
        change_set=SourceChangeSetBody(
            base_digest=change_set.base_digest,
            candidate_digest=change_set.candidate_digest,
            change_set_digest=change_set.change_set_digest,
            changes=change_set.changes,
            counts=change_set.counts,
            blockers=change_set.blockers,
        ),
    )


@router.post(
    "/{tenant_slug}/{project_id}/{version_record_id}/source-apply",
    response_model=SourceApplyResponse,
    response_model_by_alias=True,
)
async def apply_source_changes(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: SourceApplyRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> SourceApplyResponse:
    """Apply a reviewed candidate once, in a single transaction."""
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    version = _version_or_404(tenant_id, project_id, version_record_id)
    candidate = _parse_candidate(body.source_text, body.source_format)
    dialect = _stored_dialect(version)
    actor_id = get_authenticated_user_id(auth_data)
    source_digest = "sha256:" + hashlib.sha256(body.source_text.encode("utf-8")).hexdigest()
    try:
        result = db.apply_source_change_set(
            tenant_id,
            tenant_slug,
            project_id,
            str(version["id"]),
            actor_id=actor_id,
            candidate_document=candidate,
            source_format=body.source_format,
            source_digest=source_digest,
            base_digest=body.base_digest,
            change_set_digest_value=body.change_set_digest,
            dialect=dialect,
        )
    except SourceApplyConflictError as error:
        _raise_apply_conflict(error)
    counts = result.get("counts")
    return SourceApplyResponse(
        applied=bool(result.get("applied")),
        already_applied=bool(result.get("alreadyApplied")),
        no_changes=bool(result.get("noChanges")),
        result_digest=result["resultDigest"],
        audit_id=result.get("auditId"),
        counts=SourceChangeCounts.model_validate(counts) if counts else None,
        enrichments=list(result.get("enrichments") or []),
        claim_count=int(result.get("claimCount") or 0),
    )
