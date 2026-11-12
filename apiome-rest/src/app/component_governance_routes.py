"""Component governance and lifecycle REST API — DCW-3.4 (private-suite#2364).

Governance on top of the DCW-3.1 component library (:mod:`app.component_library_routes`),
under the same ``/v1/component-library/{tenant_slug}`` prefix:

* ``GET  …/governance/policy`` — the component policy resolved from the governing style guide.
  Administrators edit it with the existing ``PUT /v1/style-guides/{tenant}/{guide}/policy``
  (``componentApprovalStages``, ``componentDeprecationNoticeDays``).
* ``GET/POST …/components/{id}/revisions/{rid}/approval`` — the multi-stage assessment and the
  decision history / record a decision (``approve`` | ``request_changes``) on the current stage.
  Publishing (DCW-3.1 route) answers 409 ``APPROVAL_REQUIRED`` until every stage is satisfied.
* ``POST …/components/{id}/revisions/{rid}/deprecation`` — schedule a deprecation: sunset date
  (no earlier than the policy's notice), optional replacement revision, migration guide. The
  response lists the affected pinned projects and the migration guidance.
* ``DELETE …/components/{id}/deprecations/{did}`` — withdraw a deprecation.
* ``GET  …/deprecations`` — live deprecations with affected projects and guidance.
* ``POST …/components/{id}/upgrades/preview`` — bulk-upgrade plan: every live pin, whether it can
  move to the target (published versions never can), the CTG compatibility classification of
  each affected version's document before and after, and a confirmation token.
* ``POST …/components/{id}/upgrades`` — run the previewed plan; needs ``confirm: true`` and the
  preview's token, and refuses a plan that changed since.
* ``GET  …/audit/export`` — the ledger as JSON or CSV (tenant administrators only).

Scope misses answer 404, never 403, like the DCW-3.1 routes. Every mutation commits with its
audit row in one transaction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field

from .auth import get_authenticated_user_id, validate_authentication
from .change_taxonomy import classify_openapi_changes
from .compatibility_engine import openapi_for_revision
from .component_governance import (
    MAX_MIGRATION_GUIDE_LENGTH,
    MAX_NOTE_LENGTH,
    UPGRADE_ELIGIBLE,
    audit_export_row,
    deprecation_status,
    migration_guidance,
    plan_bulk_upgrade,
    render_audit_csv,
    upgrade_confirmation_token,
    validate_sunset,
)
from .component_governance_service import (
    assess_revision_approval,
    find_revision,
    resolve_component_policy,
)
from .component_library_routes import _CamelModel, _component_or_404, _raise_conflict
from .database import ComponentLibraryConflictError, db
from .permissions import Action, Resource, enforce_permission

router = APIRouter(prefix="/v1/component-library", tags=["component-library"])

#: Versions whose documents the preview classifies. Larger plans still list every pin; the rest
#: report ``compatibility.status = "not-evaluated"`` rather than a guessed verdict.
MAX_CLASSIFIED_VERSIONS = 25
#: Pins one upgrade call may move.
MAX_UPGRADE_PINS = 500
#: Rows one audit export returns; ``truncated`` says when there were more.
MAX_AUDIT_EXPORT_ROWS = 10000
#: Changes listed per classified version (``counts`` always reports the full tally).
MAX_LISTED_CHANGES = 20


# ===========================================================================
# Models
# ===========================================================================


class GovernancePolicyResponse(_CamelModel):
    """The resolved component policy (see ``ComponentGovernancePolicy.as_payload``)."""

    guide_id: Optional[str] = None
    guide_name: Optional[str] = None
    approval_stages: List[Dict[str, Any]] = Field(default_factory=list)
    deprecation_notice_days: int = 0


class ApprovalDecisionBody(_CamelModel):
    """One recorded decision."""

    id: str
    stage_index: int
    stage_name: str
    user_id: Optional[str] = None
    user_email: Optional[str] = None
    decision: str
    note: Optional[str] = None
    payload_digest: str
    stale: bool = Field(description="Given to an earlier payload; no longer counts.")
    created_at: Optional[str] = None


class ApprovalResponse(_CamelModel):
    """A revision's assessment plus its decision history."""

    revision_id: str
    revision: str
    state: str
    assessment: Dict[str, Any]
    decisions: List[ApprovalDecisionBody] = Field(default_factory=list)


class ApprovalDecisionRequest(_CamelModel):
    """Record a decision on the current stage."""

    decision: Literal["approve", "request_changes"]
    note: Optional[str] = Field(default=None, max_length=MAX_NOTE_LENGTH)
    stage: Optional[int] = Field(
        default=None,
        description="The stage the reviewer was shown; refused with 409 STAGE_NOT_CURRENT "
        "when another stage is current.",
    )


class AffectedProjectBody(_CamelModel):
    """A project version that pins the subject revision."""

    project_id: str
    project_name: Optional[str] = None
    version_id: str
    version: Optional[str] = None
    published: bool = False
    revision: Optional[str] = None


class DeprecationRequest(_CamelModel):
    """Schedule the deprecation of a published revision."""

    sunset_at: datetime = Field(description="When new pins to the revision stop (ISO 8601).")
    replacement_revision_id: Optional[str] = Field(
        default=None, description="A published, higher revision of the same component."
    )
    migration_guide: Optional[str] = Field(default=None, max_length=MAX_MIGRATION_GUIDE_LENGTH)


class DeprecationBody(_CamelModel):
    """One live deprecation with its consumers and guidance."""

    id: str
    component_id: str
    component_name: str
    kind: Optional[str] = None
    revision_id: str
    revision: str
    replacement_revision_id: Optional[str] = None
    replacement_revision: Optional[str] = None
    sunset_at: str
    status: str = Field(description="scheduled | sunset")
    migration_guide: Optional[str] = None
    affected_projects: List[AffectedProjectBody] = Field(default_factory=list)
    guidance: Dict[str, Any] = Field(default_factory=dict)


class DeprecationListResponse(_CamelModel):
    deprecations: List[DeprecationBody] = Field(default_factory=list)


class UpgradePreviewRequest(_CamelModel):
    target_revision_id: str


class UpgradeEntryBody(_CamelModel):
    """One pin of the plan."""

    pin_id: str
    project_id: str
    project_name: Optional[str] = None
    version_id: str
    version: Optional[str] = None
    published: bool = False
    from_revision_id: str
    from_revision: str
    local_name: Optional[str] = None
    status: str = Field(
        description="eligible | published-version | already-on-target | target-already-pinned"
    )
    compatibility: Dict[str, Any] = Field(
        default_factory=dict,
        description="status (classified | no-changes | not-evaluated | unavailable | "
        "not-applicable), maxSeverity, counts, changes",
    )


class UpgradePreviewResponse(_CamelModel):
    component_id: str
    target_revision_id: str
    target_revision: str
    entries: List[UpgradeEntryBody] = Field(default_factory=list)
    eligible: int = 0
    skipped: int = 0
    breaking: int = Field(default=0, description="Eligible versions with a breaking change.")
    confirmation_token: str
    policy: Dict[str, Any] = Field(default_factory=dict)


class UpgradeRequest(_CamelModel):
    """Run a previewed plan."""

    target_revision_id: str
    pin_ids: List[str] = Field(min_length=1, max_length=MAX_UPGRADE_PINS)
    confirmation_token: str
    confirm: bool = Field(
        default=False, description="Must be true: the caller confirms the previewed impact."
    )


class UpgradeResponse(_CamelModel):
    target_revision: str
    upgraded: List[Dict[str, Any]] = Field(default_factory=list)
    affected_projects: List[AffectedProjectBody] = Field(default_factory=list)


class AuditExportResponse(_CamelModel):
    rows: List[Dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False


# ===========================================================================
# Helpers
# ===========================================================================


def _now() -> datetime:
    """The current UTC time (patched in tests)."""
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _revision_or_404(tenant_id: str, component_id: str, revision_id: str) -> Dict[str, Any]:
    _component_or_404(tenant_id, component_id)
    revision = find_revision(tenant_id, component_id, revision_id)
    if not revision:
        raise HTTPException(status_code=404, detail="Component revision not found")
    return revision


def _affected(rows: List[Dict[str, Any]]) -> List[AffectedProjectBody]:
    return [
        AffectedProjectBody(
            project_id=str(row["project_id"]),
            project_name=row.get("project_name"),
            version_id=str(row["version_id"]),
            version=row.get("version_label"),
            published=bool(row.get("published")),
            revision=row.get("revision"),
        )
        for row in rows
    ]


def _deprecation_body(row: Dict[str, Any], consumers: List[Dict[str, Any]]) -> DeprecationBody:
    sunset = row["sunset_at"]
    if isinstance(sunset, str):
        sunset = datetime.fromisoformat(sunset)
    return DeprecationBody(
        id=str(row["id"]),
        component_id=str(row["component_id"]),
        component_name=str(row.get("component_name") or ""),
        kind=row.get("kind"),
        revision_id=str(row["revision_id"]),
        revision=str(row.get("revision") or ""),
        replacement_revision_id=(
            str(row["replacement_revision_id"]) if row.get("replacement_revision_id") else None
        ),
        replacement_revision=row.get("replacement_revision"),
        sunset_at=sunset.isoformat(),
        status=deprecation_status(sunset, _now()),
        migration_guide=row.get("migration_guide"),
        affected_projects=_affected(consumers),
        guidance=migration_guidance(
            component_name=str(row.get("component_name") or ""),
            revision=str(row.get("revision") or ""),
            sunset_at=sunset,
            replacement_revision=row.get("replacement_revision"),
            guide=row.get("migration_guide"),
            affected=consumers,
        ),
    )


def _require_tenant_admin(auth_data: Dict[str, Any]) -> str:
    """Audit exports are for tenant administrators (user sessions only), like style guides."""
    tenant_id = str(auth_data.get("tenant_id") or "")
    user_id = get_authenticated_user_id(auth_data)
    if not tenant_id or not user_id or not db.is_user_tenant_admin(tenant_id, user_id):
        raise HTTPException(
            status_code=403, detail="Only tenant administrators can export the audit trail"
        )
    return tenant_id


def _classify_entry(
    tenant_slug: str,
    tenant_id: str,
    entry: Dict[str, Any],
    target: Dict[str, Any],
    digests: Dict[str, str],
) -> Dict[str, Any]:
    """Classify one version's document before and after moving the pin to the target.

    Reuses the CTG classifier (:func:`app.change_taxonomy.classify_openapi_changes`) on the
    version's full materialized document, so the verdict reflects every operation that uses the
    component rather than the component fragment alone.
    """
    if digests.get(str(entry["revision_id"])) == str(target.get("payload_digest") or ""):
        return {"status": "no-changes", "maxSeverity": None, "counts": {}, "changes": []}
    try:
        version = db.get_version_by_id(str(entry["version_id"]), tenant_id)
        if not version:
            return {"status": "unavailable", "detail": "Version not found."}
        base = openapi_for_revision(version, tenant_slug, tenant_id)
        rows = db.get_materializable_pins_for_version(str(entry["version_id"])) or []
        head_rows = [
            (
                {
                    **row,
                    "revision": target.get("revision"),
                    "payload": target.get("canonical_payload"),
                    "revision_id": target.get("id"),
                }
                if str(row.get("revision_id")) == str(entry["revision_id"])
                else row
            )
            for row in rows
        ]
        head = openapi_for_revision(version, tenant_slug, tenant_id, component_pin_rows=head_rows)
        diff = classify_openapi_changes(base, head)
    except HTTPException:
        return {"status": "unavailable", "detail": "The version's document could not be built."}
    except Exception:  # noqa: BLE001 - a preview never fails because one version would not build
        return {"status": "unavailable", "detail": "The version's document could not be built."}
    changes = [change.model_dump(by_alias=True) for change in diff.changes[:MAX_LISTED_CHANGES]]
    return {
        "status": "classified" if diff.changes else "no-changes",
        "maxSeverity": diff.max_severity,
        "counts": dict(diff.counts),
        "changes": changes,
    }


def _target_or_409(tenant_id: str, component_id: str, target_revision_id: str) -> Dict[str, Any]:
    target = _revision_or_404(tenant_id, component_id, target_revision_id)
    if target.get("state") != "published":
        _raise_conflict(
            ComponentLibraryConflictError(
                "revision_not_published", {"revision": target.get("revision")}
            )
        )
    return target


# ===========================================================================
# Policy and approvals
# ===========================================================================


@router.get(
    "/{tenant_slug}/governance/policy",
    response_model=GovernancePolicyResponse,
    response_model_by_alias=True,
)
async def get_governance_policy(
    tenant_slug: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> GovernancePolicyResponse:
    """The component policy of the tenant's governing style guide (any tenant member)."""
    policy = resolve_component_policy(auth_data["tenant_id"]).as_payload()
    return GovernancePolicyResponse(**policy)


def _approval_response(tenant_id: str, revision: Dict[str, Any]) -> ApprovalResponse:
    assessment = assess_revision_approval(tenant_id, revision)
    current = str(revision.get("payload_digest") or "")
    rows = db.list_component_revision_approvals(tenant_id, str(revision["id"])) or []
    return ApprovalResponse(
        revision_id=str(revision["id"]),
        revision=str(revision.get("revision") or ""),
        state=str(revision.get("state") or ""),
        assessment=assessment.as_payload(),
        decisions=[
            ApprovalDecisionBody(
                id=str(row["id"]),
                stage_index=int(row.get("stage_index") or 0),
                stage_name=str(row.get("stage_name") or ""),
                user_id=str(row["user_id"]) if row.get("user_id") else None,
                user_email=row.get("user_email"),
                decision=str(row.get("decision") or ""),
                note=row.get("note"),
                payload_digest=str(row.get("payload_digest") or ""),
                stale=str(row.get("payload_digest") or "") != current,
                created_at=_iso(row.get("created_at")),
            )
            for row in rows
        ],
    )


@router.get(
    "/{tenant_slug}/components/{component_id}/revisions/{revision_id}/approval",
    response_model=ApprovalResponse,
    response_model_by_alias=True,
)
async def get_revision_approval(
    tenant_slug: str,
    component_id: str,
    revision_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApprovalResponse:
    """A revision's multi-stage approval assessment and decision history."""
    tenant_id = auth_data["tenant_id"]
    revision = _revision_or_404(tenant_id, component_id, revision_id)
    return _approval_response(tenant_id, revision)


@router.post(
    "/{tenant_slug}/components/{component_id}/revisions/{revision_id}/approval",
    response_model=ApprovalResponse,
    response_model_by_alias=True,
)
async def record_revision_approval(
    tenant_slug: str,
    component_id: str,
    revision_id: str,
    body: ApprovalDecisionRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> ApprovalResponse:
    """Record a decision on the draft's current approval stage (TYPES/EDIT).

    Decisions are immutable and bound to the payload digest they judged. Only the current stage
    takes decisions: later stages wait until every earlier one is satisfied.
    """
    enforce_permission(db, auth_data, Resource.TYPES, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    revision = _revision_or_404(tenant_id, component_id, revision_id)
    if revision.get("state") == "published":
        _raise_conflict(
            ComponentLibraryConflictError(
                "published_immutable", {"revision": revision.get("revision")}
            )
        )
    policy = resolve_component_policy(tenant_id)
    if not policy.approval_active:
        _raise_conflict(ComponentLibraryConflictError("approval_not_required"))
    assessment = assess_revision_approval(tenant_id, revision, policy)
    current = assessment.current_stage
    if current is None or (body.stage is not None and body.stage != current):
        _raise_conflict(
            ComponentLibraryConflictError("stage_not_current", {"currentStage": current})
        )
    try:
        db.record_component_revision_approval(
            tenant_id,
            component_id,
            revision_id,
            stage_index=current,
            stage_name=policy.stages[current].name,
            decision=body.decision,
            note=(body.note or "").strip() or None,
            expected_digest=str(revision.get("payload_digest") or ""),
            actor_id=get_authenticated_user_id(auth_data),
            policy=policy.as_payload(),
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    refreshed = find_revision(tenant_id, component_id, revision_id) or revision
    return _approval_response(tenant_id, refreshed)


# ===========================================================================
# Deprecation
# ===========================================================================


@router.post(
    "/{tenant_slug}/components/{component_id}/revisions/{revision_id}/deprecation",
    response_model=DeprecationBody,
    response_model_by_alias=True,
    status_code=201,
)
async def schedule_deprecation(
    tenant_slug: str,
    component_id: str,
    revision_id: str,
    body: DeprecationRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeprecationBody:
    """Schedule the deprecation of a published revision (TYPES/PUBLISH).

    The sunset must honour the policy's notice window. The revision itself is never modified;
    after the sunset new pins to it are refused (409 ``REVISION_SUNSET``) and existing pins keep
    working.
    """
    enforce_permission(db, auth_data, Resource.TYPES, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    _component_or_404(tenant_id, component_id)
    policy = resolve_component_policy(tenant_id)
    sunset = body.sunset_at if body.sunset_at.tzinfo else body.sunset_at.replace(tzinfo=timezone.utc)
    problem = validate_sunset(sunset, _now(), policy.deprecation_notice_days)
    if problem:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "SUNSET_INVALID",
                "message": problem,
                "noticeDays": policy.deprecation_notice_days,
            },
        )
    guide = (body.migration_guide or "").strip() or None
    try:
        result = db.schedule_component_deprecation(
            tenant_id,
            component_id,
            revision_id,
            sunset_at=sunset,
            replacement_revision_id=body.replacement_revision_id,
            migration_guide=guide,
            policy={**policy.as_payload(), "noticeDays": policy.deprecation_notice_days},
            actor_id=get_authenticated_user_id(auth_data),
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    component = db.get_operational_component(tenant_id, component_id) or {}
    row = {
        "id": result["deprecationId"],
        "component_id": component_id,
        "component_name": result.get("componentName"),
        "kind": component.get("kind"),
        "revision_id": revision_id,
        "revision": result.get("revision"),
        "replacement_revision_id": body.replacement_revision_id,
        "replacement_revision": result.get("replacementRevision"),
        "sunset_at": sunset,
        "migration_guide": guide,
    }
    return _deprecation_body(row, result.get("affected") or [])


@router.delete(
    "/{tenant_slug}/components/{component_id}/deprecations/{deprecation_id}",
    response_model=Dict[str, bool],
)
async def cancel_deprecation(
    tenant_slug: str,
    component_id: str,
    deprecation_id: str,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Dict[str, bool]:
    """Withdraw a live deprecation (TYPES/PUBLISH)."""
    enforce_permission(db, auth_data, Resource.TYPES, Action.PUBLISH)
    tenant_id = auth_data["tenant_id"]
    _component_or_404(tenant_id, component_id)
    try:
        db.cancel_component_deprecation(
            tenant_id,
            component_id,
            deprecation_id,
            policy=resolve_component_policy(tenant_id).as_payload(),
            actor_id=get_authenticated_user_id(auth_data),
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return {"cancelled": True}


@router.get(
    "/{tenant_slug}/deprecations",
    response_model=DeprecationListResponse,
    response_model_by_alias=True,
)
async def list_deprecations(
    tenant_slug: str,
    component_id: Optional[str] = Query(default=None, alias="componentId"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> DeprecationListResponse:
    """Live deprecations with their affected pinned projects and migration guidance."""
    tenant_id = auth_data["tenant_id"]
    rows = db.list_component_deprecations(tenant_id, component_id) or []
    return DeprecationListResponse(
        deprecations=[
            _deprecation_body(
                row,
                db.get_component_consumers(
                    tenant_id, str(row["component_id"]), [str(row["revision_id"])]
                )
                or [],
            )
            for row in rows
        ]
    )


# ===========================================================================
# Bulk upgrade
# ===========================================================================


@router.post(
    "/{tenant_slug}/components/{component_id}/upgrades/preview",
    response_model=UpgradePreviewResponse,
    response_model_by_alias=True,
)
async def preview_upgrade(
    tenant_slug: str,
    component_id: str,
    body: UpgradePreviewRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UpgradePreviewResponse:
    """Preview moving every consumer of the component to a published target revision.

    Lists every live pin with its status and, for eligible pins, the compatibility impact on
    the version's document. Nothing is written; the returned token is what the upgrade call must
    send back.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    _component_or_404(tenant_id, component_id)
    target = _target_or_409(tenant_id, component_id, body.target_revision_id)
    revisions = db.get_component_revisions(tenant_id, component_id) or []
    digests = {str(row["id"]): str(row.get("payload_digest") or "") for row in revisions}
    plan = plan_bulk_upgrade(
        db.get_component_consumers(tenant_id, component_id) or [], body.target_revision_id
    )
    entries: List[UpgradeEntryBody] = []
    classified = 0
    breaking = 0
    for entry in plan:
        if entry["status"] != UPGRADE_ELIGIBLE:
            compatibility: Dict[str, Any] = {"status": "not-applicable"}
        elif classified >= MAX_CLASSIFIED_VERSIONS:
            compatibility = {
                "status": "not-evaluated",
                "detail": f"Only the first {MAX_CLASSIFIED_VERSIONS} versions are classified.",
            }
        else:
            classified += 1
            compatibility = _classify_entry(tenant_slug, tenant_id, entry, target, digests)
        if compatibility.get("maxSeverity") == "breaking":
            breaking += 1
        entries.append(
            UpgradeEntryBody(
                pin_id=str(entry["pin_id"]),
                project_id=str(entry["project_id"]),
                project_name=entry.get("project_name"),
                version_id=str(entry["version_id"]),
                version=entry.get("version_label"),
                published=bool(entry.get("published")),
                from_revision_id=str(entry["revision_id"]),
                from_revision=str(entry.get("revision") or ""),
                local_name=entry.get("local_name"),
                status=entry["status"],
                compatibility=compatibility,
            )
        )
    eligible = sum(1 for entry in plan if entry["status"] == UPGRADE_ELIGIBLE)
    return UpgradePreviewResponse(
        component_id=component_id,
        target_revision_id=body.target_revision_id,
        target_revision=str(target.get("revision") or ""),
        entries=entries,
        eligible=eligible,
        skipped=len(plan) - eligible,
        breaking=breaking,
        confirmation_token=upgrade_confirmation_token(
            component_id, body.target_revision_id, plan
        ),
        policy=resolve_component_policy(tenant_id).as_payload(),
    )


@router.post(
    "/{tenant_slug}/components/{component_id}/upgrades",
    response_model=UpgradeResponse,
    response_model_by_alias=True,
)
async def execute_upgrade(
    tenant_slug: str,
    component_id: str,
    body: UpgradeRequest,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> UpgradeResponse:
    """Run a previewed bulk upgrade (VERSIONS/EDIT).

    Refused with 422 ``CONFIRMATION_REQUIRED`` unless ``confirm`` is true, and with 409
    ``UPGRADE_PLAN_STALE`` when the plan changed since the preview that issued the token.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.EDIT)
    tenant_id = auth_data["tenant_id"]
    if not body.confirm:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "CONFIRMATION_REQUIRED",
                "message": "Review the preview, then send confirm: true to run the upgrade.",
            },
        )
    _component_or_404(tenant_id, component_id)
    _target_or_409(tenant_id, component_id, body.target_revision_id)
    try:
        result = db.execute_component_bulk_upgrade(
            tenant_id,
            component_id,
            body.target_revision_id,
            list(dict.fromkeys(body.pin_ids)),
            confirmation_token=body.confirmation_token,
            policy=resolve_component_policy(tenant_id).as_payload(),
            actor_id=get_authenticated_user_id(auth_data),
        )
    except ComponentLibraryConflictError as error:
        _raise_conflict(error)
    return UpgradeResponse(
        target_revision=str(result.get("targetRevision") or ""),
        upgraded=result.get("upgraded") or [],
        affected_projects=[
            AffectedProjectBody(
                project_id=item["projectId"],
                project_name=item.get("projectName"),
                version_id=item["versionId"],
                version=item.get("version"),
                published=bool(item.get("published")),
                revision=item.get("revision"),
            )
            for item in result.get("affected") or []
        ],
    )


# ===========================================================================
# Audit export
# ===========================================================================


@router.get(
    "/{tenant_slug}/audit/export",
    response_model=AuditExportResponse,
    response_model_by_alias=True,
    responses={200: {"content": {"text/csv": {}}}},
)
async def export_audit(
    tenant_slug: str,
    format: Literal["json", "csv"] = Query(default="json"),
    since: Optional[datetime] = Query(default=None),
    until: Optional[datetime] = Query(default=None),
    component_id: Optional[str] = Query(default=None, alias="componentId"),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Any:
    """Export the component-library ledger (tenant administrators).

    Each row carries the actor, the policy in force, the old and new revision, the affected
    projects, the decision, and the timestamp. ``format=csv`` returns ``text/csv`` with
    ``policy`` and ``affectedProjects`` as compact JSON cells.
    """
    tenant_id = _require_tenant_admin(auth_data)
    rows = db.list_component_library_audit(
        tenant_id,
        since=since,
        until=until,
        component_id=component_id,
        limit=MAX_AUDIT_EXPORT_ROWS + 1,
    ) or []
    truncated = len(rows) > MAX_AUDIT_EXPORT_ROWS
    exported = [audit_export_row(row) for row in rows[:MAX_AUDIT_EXPORT_ROWS]]
    if format == "csv":
        headers = {"Content-Disposition": 'attachment; filename="component-library-audit.csv"'}
        if truncated:
            headers["X-Apiome-Truncated"] = "true"
        return Response(content=render_audit_csv(exported), media_type="text/csv", headers=headers)
    return AuditExportResponse(rows=exported, truncated=truncated)

