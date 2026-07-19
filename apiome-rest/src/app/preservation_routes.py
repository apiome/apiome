"""Preservation-envelope REST API — DCW-2.1 (private-suite#2352).

Tenant/version-scoped storage for the round-trip preservation envelope:

* ``GET  /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/preservation``
  — the revision's live envelope plus the semantic fingerprint of the merged
  (canonical + preserved) document and the DCW-0.1 lexical exclusions.
* ``PUT  /v1/versions/{tenant_slug}/{project_id}/{version_record_id}/preservation``
  — validate and replace the envelope. Validation runs against the revision's
  **server-generated** canonical document (never client-supplied truth):
  malformed/duplicate/nested pointers, canonical-vs-preserved collisions for
  the same pointer, unsupported dialects, and oversized envelopes are rejected
  with the structured ``EnvelopeError`` list and **no mutation**. Published
  revisions are immutable. The replace and its audit row commit in one
  transaction (DCW-0.2 ``failure-injection-no-partial-mutation``).

Authorization: reads require any authenticated tenant member; writes require
the VERSIONS/EDIT permission. Scope misses answer 404 (not 403) so
cross-tenant probes cannot confirm a revision exists.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .auth import get_authenticated_user_id, validate_authentication
from .database import db
from .openapi_generator import generate_openapi_spec
from .permissions import Action, Resource, enforce_permission
from .preservation_envelope import (
    ENVELOPE_VERSION,
    EnvelopeError,
    PreservationClaim,
    PreservationEnvelope,
    SemanticFingerprint,
    apply_envelope,
    semantic_fingerprint,
    validate_envelope,
)

router = APIRouter(prefix="/v1/versions", tags=["versions"])


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PreservationClaimBody(_CamelModel):
    """One claim in the request/response payload."""

    pointer: str = Field(description="RFC 6901 JSON Pointer of the preserved value.")
    value: Any = Field(default=None, description="The preserved subtree verbatim.")
    source_file: Optional[str] = Field(default=None, description="Provenance file path.")
    source_digest: Optional[str] = Field(
        default=None, description="Algorithm-prefixed provenance digest (sha256:<hex>)."
    )


class PreservationEnvelopeResponse(_CamelModel):
    """A revision's live preservation envelope plus its semantic fingerprint."""

    envelope_version: str = Field(description="Envelope payload contract version.")
    dialect: str = Field(description="OAS dialect the claims were validated under.")
    claims: List[PreservationClaimBody]
    fingerprint: SemanticFingerprint = Field(
        description="Semantic fingerprint of the merged (canonical + preserved) "
        "document, reporting the intentionally excluded lexical differences."
    )


class PreservationEnvelopePutRequest(_CamelModel):
    """Replace a draft revision's preservation envelope."""

    dialect: str = Field(description="OAS dialect the claims target (e.g. 3.1.0).")
    claims: List[PreservationClaimBody] = Field(
        default_factory=list, description="The full new set of claims (empty clears)."
    )


class PreservationValidationErrorBody(_CamelModel):
    """422 body: the deterministic structured error list, nothing mutated."""

    code: str = Field(default="PRESERVATION_ENVELOPE_INVALID")
    errors: List[EnvelopeError]


def _generated_canonical_document(version: Dict[str, Any], tenant_slug: str) -> Dict[str, Any]:
    """The revision's canonical OpenAPI document, generated server-side.

    Same generation path as ``/v1/schema`` (classes + properties + paths rows),
    so collision checks always run against what export would actually emit —
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


def _version_or_404(tenant_id: str, project_id: str, version_record_id: str) -> Dict[str, Any]:
    """Tenant-scoped version row, or 404 (never 403 — do not leak existence)."""
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail="Version not found")
    return version


def _envelope_from_rows(dialect: str, rows: List[Dict[str, Any]]) -> PreservationEnvelope:
    """Build the pure-logic envelope model from live claim rows."""
    return PreservationEnvelope(
        dialect=dialect,
        claims=[
            PreservationClaim(
                pointer=row["pointer"],
                value=row["payload"],
                source_file=row.get("source_file"),
                source_digest=row.get("source_digest"),
            )
            for row in rows
        ],
    )


def _claim_bodies(rows: List[Dict[str, Any]]) -> List[PreservationClaimBody]:
    return [
        PreservationClaimBody(
            pointer=row["pointer"],
            value=row["payload"],
            source_file=row.get("source_file"),
            source_digest=row.get("source_digest"),
        )
        for row in rows
    ]


def _stored_dialect(version: Dict[str, Any]) -> str:
    """The dialect recorded on the revision metadata, defaulting to 3.1.0."""
    metadata = version.get("metadata")
    if isinstance(metadata, dict):
        dialect = metadata.get("oasDialect")
        if isinstance(dialect, str) and dialect:
            return dialect
    return "3.1.0"


@router.get(
    "/{tenant_slug}/{project_id}/{version_record_id}/preservation",
    response_model=PreservationEnvelopeResponse,
    response_model_by_alias=True,
)
async def get_preservation_envelope(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PreservationEnvelopeResponse:
    """Return the revision's live preservation envelope and semantic fingerprint."""
    tenant_id = auth_data["tenant_id"]
    version = _version_or_404(tenant_id, project_id, version_record_id)
    try:
        rows = db.get_preservation_claims(tenant_id, project_id, version_record_id)
    except ValueError as ve:
        if str(ve) == "version_not_found":
            raise HTTPException(status_code=404, detail="Version not found") from ve
        raise HTTPException(status_code=500, detail=str(ve)) from ve

    dialect = _stored_dialect(version)
    canonical = _generated_canonical_document(version, tenant_slug)
    merged, merge_errors = apply_envelope(canonical, _envelope_from_rows(dialect, rows))
    # A stored envelope that no longer merges cleanly (canonical drift) still
    # reads back; the fingerprint then covers the canonical document alone.
    fingerprint = semantic_fingerprint(merged if not merge_errors else canonical)
    return PreservationEnvelopeResponse(
        envelope_version=ENVELOPE_VERSION,
        dialect=dialect,
        claims=_claim_bodies(rows),
        fingerprint=fingerprint,
    )


@router.put(
    "/{tenant_slug}/{project_id}/{version_record_id}/preservation",
    response_model=PreservationEnvelopeResponse,
    response_model_by_alias=True,
)
async def put_preservation_envelope(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: PreservationEnvelopePutRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> PreservationEnvelopeResponse:
    """Validate and replace a draft revision's preservation envelope.

    Responses:
        * **200** — envelope stored; body echoes the live envelope + fingerprint.
        * **404** — revision not in the caller's tenant/project scope.
        * **409** — revision is published (immutable); nothing mutated.
        * **422** — structured validation errors; nothing mutated.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    version = _version_or_404(tenant_id, project_id, version_record_id)

    if version.get("published"):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PUBLISHED_IMMUTABLE",
                "message": "Published revisions are immutable; preservation writes "
                "target an authorized draft.",
            },
        )

    envelope = PreservationEnvelope(
        dialect=body.dialect,
        claims=[
            PreservationClaim(
                pointer=claim.pointer,
                value=claim.value,
                source_file=claim.source_file,
                source_digest=claim.source_digest,
            )
            for claim in body.claims
        ],
    )
    canonical = _generated_canonical_document(version, tenant_slug)
    report = validate_envelope(envelope, canonical)
    if not report.ok:
        raise HTTPException(
            status_code=422,
            detail=PreservationValidationErrorBody(errors=report.errors).model_dump(
                by_alias=True
            ),
        )

    merged, merge_errors = apply_envelope(canonical, envelope)
    if merge_errors:
        raise HTTPException(
            status_code=422,
            detail=PreservationValidationErrorBody(errors=merge_errors).model_dump(
                by_alias=True
            ),
        )

    actor_id = get_authenticated_user_id(auth_data)
    try:
        db.replace_preservation_claims(
            tenant_id,
            project_id,
            version_record_id,
            [
                {
                    "pointer": claim.pointer,
                    "value": claim.value,
                    "source_file": claim.source_file,
                    "source_digest": claim.source_digest,
                }
                for claim in envelope.claims
            ],
            actor_id,
            detail={"envelopeVersion": ENVELOPE_VERSION, "dialect": envelope.dialect},
        )
    except ValueError as ve:
        code = str(ve)
        if code == "version_not_found":
            raise HTTPException(status_code=404, detail="Version not found") from ve
        if code == "published_version":
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "PUBLISHED_IMMUTABLE",
                    "message": "Published revisions are immutable; preservation writes "
                    "target an authorized draft.",
                },
            ) from ve
        raise HTTPException(status_code=500, detail=code) from ve

    return PreservationEnvelopeResponse(
        envelope_version=ENVELOPE_VERSION,
        dialect=envelope.dialect,
        claims=[
            PreservationClaimBody(
                pointer=claim.pointer,
                value=claim.value,
                source_file=claim.source_file,
                source_digest=claim.source_digest,
            )
            for claim in envelope.claims
        ],
        fingerprint=semantic_fingerprint(merged),
    )
