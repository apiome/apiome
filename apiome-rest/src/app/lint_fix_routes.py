"""Lint-fix plan and apply routes — GVM-3.2 (#5870).

One contract for inspecting and applying the deterministic fixes of GVM-3.1, shared by the CLI,
the UI, CI and the Studio agent:

* ``GET  /v1/versions/{tenant}/{project}/{version}/lint/fixes`` — the plan over a stored revision's
  OpenAPI document (the same reconstruction its lint report is computed from), under the
  project's style guide. ``format=json|patch|overlay|diff``.
* ``POST /v1/lint/fixes/plan`` — the same plan over a posted document (file mode; stateless,
  nothing is stored), under the tenant's style guide.
* ``POST /v1/versions/{tenant}/{project}/{version}/lint/fixes/apply`` — apply ``fixIds`` or every
  ready fix of ``rules``. Needs ``versions:edit`` and an **unpublished** revision. The revision is
  never changed in place: the fixed document is imported as a **new** revision through the
  import pipeline every document-to-revision change uses (:mod:`app.openapi_version_import`), the
  new revision is re-linted and its report stored with its content fingerprint, and the
  ``source: lint-fix`` provenance plus the ``version.lint_fix_applied`` audit row are written in
  one transaction (:meth:`app.database.Database.record_lint_fix_revision`). If that record cannot
  be written the new revision is withdrawn, so an apply leaves exactly one audited revision or
  none.

Refusals use structured ``{code, message}`` details: ``409 lint-fix-version-published``,
``422 lint-fix-breaking``, ``422 lint-fix-conflict``, ``422 lint-fix-excluded``,
``422 lint-fix-unknown``, ``422 lint-fix-nothing-to-apply``, ``422 lint-fix-invalid-options``,
``422 lint-fix-not-openapi`` and ``500 lint-fix-record-failed``.

The plan itself is computed by :mod:`app.lint_fix_plan`.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import validate_authentication
from .arazzo_fix_rules import is_arazzo_document
from .compatibility_engine import openapi_for_revision
from .database import db
from .lint_fix import DEFAULT_OPERATION_ID_TEMPLATE, FixError
from .lint_fix_plan import (
    FORMAT_DIFF,
    FORMAT_JSON,
    FORMAT_OVERLAY,
    FORMAT_PATCH,
    STATUS_BREAKING,
    STATUS_CONFLICT,
    STATUS_EXCLUDED,
    STATUS_READY,
    FixPlan,
    FixPlanEntry,
    build_fix_plan,
    compose_entries,
    parse_rules_param,
)
from .openapi_version_import import (
    choose_version_label,
    document_bytes,
    enforce_openapi_quality_gate,
    existing_version_labels,
    import_openapi_as_version,
)
from .permissions import Action, Resource, enforce_permission
from .style_guide_engine import guided_lint_openapi_spec, resolve_style_guide
from .style_guide_revisions import pin_guide_revision_id
from .version_quality_capture import (
    persist_version_lint_report,
    stored_report_is_current,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/versions", tags=["lint"])
plan_router = APIRouter(prefix="/v1/lint/fixes", tags=["lint"])

_BASE = "/{tenant_slug}/{project_id}/{version_record_id}/lint/fixes"

#: The audit action an apply writes.
AUDIT_LINT_FIX_APPLIED = "version.lint_fix_applied"
#: ``format_metadata.source`` of a revision an apply created.
SOURCE_LINT_FIX = "lint-fix"

CODE_VERSION_PUBLISHED = "lint-fix-version-published"
CODE_BREAKING = "lint-fix-breaking"
CODE_CONFLICT = "lint-fix-conflict"
CODE_EXCLUDED = "lint-fix-excluded"
CODE_UNKNOWN = "lint-fix-unknown"
CODE_NOTHING = "lint-fix-nothing-to-apply"
CODE_INVALID_OPTIONS = "lint-fix-invalid-options"
CODE_NOT_OPENAPI = "lint-fix-not-openapi"
CODE_IMPORT_FAILED = "lint-fix-import-failed"
CODE_RECORD_FAILED = "lint-fix-record-failed"

#: Ceiling on a posted document, in characters.
MAX_PLAN_DOCUMENT_CHARS = 5_000_000

#: Media type of each non-JSON rendering.
_MEDIA_TYPES = {
    FORMAT_PATCH: "application/json-patch+json",
    FORMAT_OVERLAY: "application/json",
    FORMAT_DIFF: "text/x-diff; charset=utf-8",
}

PlanFormat = Literal["json", "patch", "overlay", "diff"]


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class _CamelModel(BaseModel):
    """Base for the camelCase request and response bodies."""

    model_config = ConfigDict(populate_by_name=True)


class LintFixChangeOut(_CamelModel):
    """One classified change of a fix's own delta."""

    rule_id: str = Field(alias="ruleId")
    severity: str
    pointer: str


class LintFixClassificationOut(_CamelModel):
    """The CTG classification of a fix's own delta."""

    max_severity: Optional[str] = Field(default=None, alias="maxSeverity")
    counts: Dict[str, int] = Field(default_factory=dict)
    changes: List[LintFixChangeOut] = Field(default_factory=list)


class LintFixEntryOut(_CamelModel):
    """One fixable finding of a plan."""

    fix_id: str = Field(alias="fixId")
    rule_id: str = Field(alias="ruleId")
    fix_class: str = Field(alias="fixClass")
    wire_visible: bool = Field(alias="wireVisible")
    path: str
    pointer: str
    finding_id: str = Field(alias="findingId")
    message: str
    ops: List[Dict[str, Any]]
    status: Literal["ready", "conflict", "breaking", "excluded"]
    reason: Optional[str] = None
    conflicts_with: Optional[str] = Field(default=None, alias="conflictsWith")
    classification: Optional[LintFixClassificationOut] = None


class LintFixPlanOut(_CamelModel):
    """A lint-fix plan (``format=json``)."""

    document_fingerprint: str = Field(alias="documentFingerprint")
    fixed_document_fingerprint: str = Field(alias="fixedDocumentFingerprint")
    include_renames: bool = Field(alias="includeRenames")
    rules: Optional[List[str]] = None
    operation_id_template: str = Field(alias="operationIdTemplate")
    counts: Dict[str, int]
    applied_order: List[str] = Field(alias="appliedOrder")
    entries: List[LintFixEntryOut]
    guide_id: Optional[str] = Field(default=None, alias="guideId")
    guide_name: Optional[str] = Field(default=None, alias="guideName")
    project_id: Optional[str] = Field(default=None, alias="projectId")
    version_record_id: Optional[str] = Field(default=None, alias="versionRecordId")
    report_fingerprint: Optional[str] = Field(
        default=None,
        alias="reportFingerprint",
        description="Fingerprint of the revision's stored lint report (revision plans only).",
    )
    report_current: Optional[bool] = Field(
        default=None,
        alias="reportCurrent",
        description="Whether the stored report still matches the planned document (revision plans only).",
    )


class LintFixPlanRequest(_CamelModel):
    """``POST /v1/lint/fixes/plan``: plan the fixes of a posted document."""

    document: str = Field(description="The OpenAPI document, as YAML or JSON text.")
    filename: Optional[str] = Field(default=None, description="The file name, for messages.")
    format: PlanFormat = "json"
    rules: Optional[List[str]] = Field(default=None, description="Plan only these rule ids.")
    include_renames: bool = Field(default=False, alias="includeRenames")
    operation_id_template: str = Field(default=DEFAULT_OPERATION_ID_TEMPLATE, alias="operationIdTemplate")


class LintFixApplyRequest(_CamelModel):
    """``POST …/lint/fixes/apply``: name the fixes (``fixIds``) or rules (``rules``) to apply."""

    fix_ids: Optional[List[str]] = Field(default=None, alias="fixIds")
    rules: Optional[List[str]] = None
    reason: str = Field(min_length=1, max_length=2000, description="Why the fixes are applied (audited).")
    include_renames: bool = Field(default=False, alias="includeRenames")
    operation_id_template: str = Field(default=DEFAULT_OPERATION_ID_TEMPLATE, alias="operationIdTemplate")
    version_label: Optional[str] = Field(default=None, alias="versionLabel", max_length=200)

    @model_validator(mode="after")
    def _one_selection(self) -> "LintFixApplyRequest":
        """Exactly one of ``fixIds`` and ``rules`` must name something."""
        if bool(self.fix_ids) == bool(self.rules):
            raise ValueError("name the fixes to apply in exactly one of fixIds or rules")
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        return self


class LintFixSkippedOut(_CamelModel):
    """A fix of a named rule that was not applied."""

    fix_id: str = Field(alias="fixId")
    rule_id: str = Field(alias="ruleId")
    status: str


class LintFixApplyOut(_CamelModel):
    """The revision an apply created."""

    project_id: str = Field(alias="projectId")
    source_version_record_id: str = Field(alias="sourceVersionRecordId")
    version_record_id: str = Field(alias="versionRecordId")
    version_label: str = Field(alias="versionLabel")
    applied_fix_ids: List[str] = Field(alias="appliedFixIds")
    skipped: List[LintFixSkippedOut] = Field(default_factory=list)
    score: Optional[int] = None
    grade: Optional[str] = None
    report_fingerprint: Optional[str] = Field(default=None, alias="reportFingerprint")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _refuse(status: int, code: str, message: str) -> HTTPException:
    """A structured ``{code, message}`` refusal."""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _version(tenant_id: str, project_id: str, version_record_id: str) -> Dict[str, Any]:
    """Load the revision inside the caller's tenant and project, or raise 404."""
    version = db.get_version_by_id(version_record_id, tenant_id)
    if not version or str(version.get("project_id")) != str(project_id):
        raise HTTPException(status_code=404, detail=f"Revision not found: {version_record_id}")
    return version


def _plan(
    document: Any,
    *,
    rules: Optional[List[str]],
    include_renames: bool,
    operation_id_template: str,
    guide: Any,
) -> FixPlan:
    """Build the plan, turning a bad option or a non-OpenAPI document into a 422."""
    if not isinstance(document, dict) or not (
        str(document.get("openapi") or "").startswith("3.") or is_arazzo_document(document)
    ):
        raise _refuse(
            422, CODE_NOT_OPENAPI, "Lint fixes are planned for OpenAPI 3.x and Arazzo documents only."
        )
    try:
        return build_fix_plan(
            document,
            rules=rules,
            include_renames=include_renames,
            operation_id_template=operation_id_template,
            enabled=guide.is_enabled,
        )
    except FixError as exc:
        raise _refuse(422, CODE_INVALID_OPTIONS, str(exc)) from exc


def fix_plan_links(tenant_slug: str, project_id: str, version_record_id: str) -> Dict[str, str]:
    """API paths of a revision's full lint-fix change, by rendering (GVM-3.4, #5872).

    These are the downloads a CI summary links: ``patch`` returns the same bytes as
    ``apiome lint --fix --dry-run --fix-format patch``.

    Args:
        tenant_slug: The tenant in the URL.
        project_id: The project.
        version_record_id: The revision.

    Returns:
        ``{"patch": …, "overlay": …}``.
    """
    base = f"/v1/versions/{tenant_slug}/{project_id}/{version_record_id}/lint/fixes"
    return {"patch": f"{base}?format={FORMAT_PATCH}", "overlay": f"{base}?format={FORMAT_OVERLAY}"}


def suggest_revision_fixes(
    version: Mapping[str, Any], *, tenant_slug: str, tenant_id: str, project_id: str
) -> Optional[Dict[str, Any]]:
    """The *Suggested fixes* summary of a revision's default plan, for CI summaries (GVM-3.4).

    The plan is the one ``GET …/lint/fixes`` returns without options (every rule the style guide
    turns on, no renames), so the counts match the linked patch. A revision the planner refuses
    (not OpenAPI 3.x) or cannot rebuild has no suggestions — this is context for a summary and
    never a reason to fail one.

    Args:
        version: The revision row.
        tenant_slug: The tenant slug (the document is rebuilt under it).
        tenant_id: The caller's tenant.
        project_id: The owning project (its style guide decides which rules are on).

    Returns:
        :func:`app.lint_fix_suggestions.summarize_fix_plan` output, or ``None``.
    """
    from .lint_fix_suggestions import summarize_fix_plan

    try:
        document = openapi_for_revision(dict(version), tenant_slug, tenant_id)
        guide = resolve_style_guide(tenant_id, project_id)
        plan = _plan(
            document,
            rules=None,
            include_renames=False,
            operation_id_template=DEFAULT_OPERATION_ID_TEMPLATE,
            guide=guide,
        )
        return summarize_fix_plan(plan)
    except HTTPException:
        return None
    except Exception:  # noqa: BLE001 - suggestions are context, never a reason to fail
        logger.warning("Could not plan lint fixes for revision %s", version.get("id"), exc_info=True)
        return None


def _render(plan: FixPlan, fmt: str, extra: Optional[Dict[str, Any]] = None) -> Any:
    """Render ``plan`` in ``fmt``: the JSON model, or a :class:`Response` for the other formats."""
    if fmt == FORMAT_JSON:
        return LintFixPlanOut.model_validate({**plan.as_dict(), **(extra or {})})
    if fmt == FORMAT_PATCH:
        body = json.dumps(plan.patch(), indent=2, ensure_ascii=False) + "\n"
    elif fmt == FORMAT_OVERLAY:
        body = json.dumps(plan.overlay(), indent=2, ensure_ascii=False) + "\n"
    else:
        body = plan.unified_diff()
    return Response(content=body, media_type=_MEDIA_TYPES[fmt])


_RENDERED_RESPONSES: Dict[Any, Dict[str, Any]] = {
    200: {
        "description": "The plan; `format=patch` returns an RFC 6902 document, `format=overlay` an "
        "Overlay 1.0 document and `format=diff` a unified diff.",
        "content": {
            "application/json-patch+json": {"schema": {"type": "array", "items": {"type": "object"}}},
            "text/x-diff": {"schema": {"type": "string"}},
        },
    }
}


def _select(plan: FixPlan, body: LintFixApplyRequest) -> Tuple[List[FixPlanEntry], List[FixPlanEntry]]:
    """The entries an apply request names, and the named-rule entries it skips.

    Raises:
        HTTPException: 422 when a fix id is unknown, breaking, conflicting or excluded, or when
            nothing ready is named.
    """
    if body.fix_ids:
        chosen: List[FixPlanEntry] = []
        for fix_id in dict.fromkeys(body.fix_ids):
            entry = plan.entry(fix_id)
            if entry is None:
                raise _refuse(422, CODE_UNKNOWN, f"Fix {fix_id!r} is not in this revision's plan.")
            if entry.status == STATUS_BREAKING:
                raise _refuse(
                    422,
                    CODE_BREAKING,
                    f"Fix {fix_id!r} ({entry.rule_id}) makes a breaking change, so it is never applied.",
                )
            if entry.status == STATUS_CONFLICT:
                raise _refuse(
                    422,
                    CODE_CONFLICT,
                    f"Fix {fix_id!r} conflicts with {entry.conflicts_with!r}; apply that one first, "
                    "then plan again.",
                )
            if entry.status == STATUS_EXCLUDED:
                raise _refuse(
                    422,
                    CODE_EXCLUDED,
                    f"Fix {fix_id!r} is excluded ({entry.reason}); name its rule in rules or set "
                    "includeRenames to select it.",
                )
            chosen.append(entry)
        return chosen, []
    named = set(body.rules or [])
    of_rules = [entry for entry in plan.entries if entry.rule_id in named]
    chosen = [entry for entry in of_rules if entry.status == STATUS_READY]
    skipped = [entry for entry in of_rules if entry.status != STATUS_READY]
    if not chosen:
        if any(entry.status == STATUS_BREAKING for entry in skipped):
            raise _refuse(
                422,
                CODE_BREAKING,
                "Every fix of the named rules makes a breaking change, so none is applied.",
            )
        raise _refuse(422, CODE_NOTHING, "The named rules have no ready fixes in this revision.")
    return chosen, skipped


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(_BASE, response_model=LintFixPlanOut, response_model_by_alias=True, responses=_RENDERED_RESPONSES)
async def get_lint_fix_plan(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    format: PlanFormat = Query(default="json", description="json | patch | overlay | diff."),
    rules: Optional[str] = Query(default=None, description="Comma-separated rule ids to plan."),
    include_renames: bool = Query(default=False, alias="includeRenames", description="Plan rename fixes."),
    operation_id_template: str = Query(
        default=DEFAULT_OPERATION_ID_TEMPLATE,
        alias="operationIdTemplate",
        description="Template of generated operationIds: {method} {Method} {path} {Path}.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Any:
    """Plan the deterministic lint fixes of a stored revision.

    The plan is computed over the revision's OpenAPI document — the reconstruction its stored
    lint report was computed from — under the project's style guide. The stored report's
    fingerprint is echoed with whether it still matches the document, so a reader can tell the
    plan and the report describe the same content.

    Raises:
        HTTPException: 404 unknown revision; 422 non-OpenAPI revision or invalid options.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = str(auth_data["tenant_id"])
    version = _version(tenant_id, project_id, version_record_id)
    document = await asyncio.to_thread(openapi_for_revision, version, tenant_slug, tenant_id)
    guide = resolve_style_guide(tenant_id, project_id)
    plan = await asyncio.to_thread(
        _plan,
        document,
        rules=list(parse_rules_param(rules) or []) or None,
        include_renames=include_renames,
        operation_id_template=operation_id_template,
        guide=guide,
    )
    extra: Dict[str, Any] = {
        "guideId": guide.guide_id,
        "guideName": guide.name,
        "projectId": project_id,
        "versionRecordId": version_record_id,
    }
    try:
        captured = db.get_version_quality_score(version_record_id, tenant_id) or {}
    except Exception:  # noqa: BLE001 - the stored report is context, never a reason to fail
        captured = {}
    stored = captured.get("quality_report")
    if isinstance(stored, str):
        try:
            stored = json.loads(stored)
        except json.JSONDecodeError:
            stored = None
    if isinstance(stored, dict) and stored.get("report_fingerprint"):
        extra["reportFingerprint"] = str(stored["report_fingerprint"])
        extra["reportCurrent"] = bool(stored_report_is_current(stored, document))
    return _render(plan, format, extra)


@plan_router.post("/plan", response_model=LintFixPlanOut, response_model_by_alias=True, responses=_RENDERED_RESPONSES)
async def plan_lint_fixes_for_document(
    body: LintFixPlanRequest = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Any:
    """Plan the deterministic lint fixes of a posted document (file mode).

    Stateless: nothing is stored. The tenant's style guide decides which rules are on, as it does
    for a stored revision of a project without its own guide.

    Raises:
        HTTPException: 413 over the size limit; 422 not YAML/JSON, not OpenAPI 3.x, or invalid options.
    """
    from .import_ingestion import IngestionError, parse_document

    tenant_id = str(auth_data["tenant_id"])
    if len(body.document) > MAX_PLAN_DOCUMENT_CHARS:
        raise HTTPException(
            status_code=413, detail=f"The document is over the {MAX_PLAN_DOCUMENT_CHARS}-character limit."
        )
    try:
        document = parse_document(body.document, source_label=body.filename or "document")
    except (IngestionError, ValueError) as exc:
        raise _refuse(422, CODE_NOT_OPENAPI, f"The document is not valid YAML or JSON: {exc}") from exc
    guide = resolve_style_guide(tenant_id, None)
    plan = await asyncio.to_thread(
        _plan,
        document,
        rules=body.rules or None,
        include_renames=body.include_renames,
        operation_id_template=body.operation_id_template,
        guide=guide,
    )
    return _render(plan, body.format, {"guideId": guide.guide_id, "guideName": guide.name})


@router.post(f"{_BASE}/apply", response_model=LintFixApplyOut, response_model_by_alias=True, status_code=201)
async def apply_lint_fixes(
    tenant_slug: str,
    project_id: str,
    version_record_id: str,
    body: LintFixApplyRequest = Body(...),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> LintFixApplyOut:
    """Apply lint fixes to an unpublished revision by creating a new ``lint-fix`` revision.

    The revision itself is never changed. The plan is rebuilt with the request's options, the
    named fixes are composed onto the document, and the result is imported as a new revision of
    the same project (through the import quality gate and pipeline). The new revision is
    re-linted and its report stored; its ``source: lint-fix`` provenance and the
    ``version.lint_fix_applied`` audit row are written in one transaction.

    Raises:
        HTTPException: 404 unknown revision; 409 published revision, ``version-exists`` or
            ``QUALITY_POLICY_BLOCKED``; 422 for a breaking, conflicting, excluded or unknown fix,
            nothing to apply, invalid options, or a failed import; 500 when the record cannot be
            written (the new revision is withdrawn).
    """
    actor_id = enforce_permission(
        db, auth_data, Resource.VERSIONS, Action.EDIT, target=f"version:{version_record_id}:lint-fix"
    )
    tenant_id = str(auth_data["tenant_id"])
    version = _version(tenant_id, project_id, version_record_id)
    if version.get("published"):
        raise _refuse(
            409,
            CODE_VERSION_PUBLISHED,
            "This revision is published, so fixes cannot be applied to it. Apply them to a draft revision.",
        )
    document = await asyncio.to_thread(openapi_for_revision, version, tenant_slug, tenant_id)
    guide = resolve_style_guide(tenant_id, project_id)
    plan = await asyncio.to_thread(
        _plan,
        document,
        rules=body.rules or None,
        include_renames=body.include_renames,
        operation_id_template=body.operation_id_template,
        guide=guide,
    )
    chosen, skipped = _select(plan, body)
    fixed, applied, failed = compose_entries(plan.original_document, chosen)
    if failed:
        raise _refuse(
            422,
            CODE_CONFLICT,
            "These fixes no longer apply together: " + ", ".join(e.fix_id for e in failed) + ". Plan again.",
        )
    applied_ids = [entry.fix_id for entry in applied]

    existing = await asyncio.to_thread(existing_version_labels, project_id, tenant_id)
    label = choose_version_label(body.version_label, existing)
    raw = document_bytes(fixed)
    await enforce_openapi_quality_gate(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_id=str(actor_id or ""),
        project_id=project_id,
        label=label,
        raw=raw,
        filename="lint-fixed-openapi.json",
    )
    projection = db.get_version_source_projection(version_record_id, tenant_id) or {}
    rule_ids = sorted({entry.rule_id for entry in applied})
    source_label = version.get("version_id") or version_record_id
    new_id = await asyncio.to_thread(
        import_openapi_as_version,
        tenant_id=tenant_id,
        actor_id=str(actor_id) if actor_id else None,
        project_id=project_id,
        format_metadata=projection.get("format_metadata"),
        fallback_slug=projection.get("project_slug"),
        label=label,
        raw=raw,
        filename_suffix="-lint-fixed.json",
        description=f"Version {source_label} with lint fixes applied ({', '.join(rule_ids)}): {body.reason.strip()}",
        rest_job_id=f"lint-fix-{project_id}",
        failure_code=CODE_IMPORT_FAILED,
        failure_message="The fixed document could not be imported",
    )

    # Re-lint the new revision and store its report with its content fingerprint, so the stored
    # report of the lint-fix revision is current from the start.
    score: Optional[int] = None
    grade: Optional[str] = None
    report_fingerprint: Optional[str] = None
    new_version = db.get_version_by_id(new_id, tenant_id)
    if new_version:
        try:
            spec = await asyncio.to_thread(openapi_for_revision, new_version, tenant_slug, tenant_id)
            result, new_guide = guided_lint_openapi_spec(spec, tenant_id, project_id=project_id)
            persist_version_lint_report(
                new_id,
                tenant_id,
                result,
                spec,
                guide=new_guide,
                guide_revision_id=pin_guide_revision_id(new_guide, tenant_id),
            )
            score, grade, report_fingerprint = result.score, result.grade, result.report_fingerprint
        except Exception:  # noqa: BLE001 - an on-demand lint fills a report that failed here
            logger.exception("lint-fix revision re-lint failed version=%s", new_id)

    provenance = {
        "source": SOURCE_LINT_FIX,
        "lintFix": {
            "sourceVersionRecordId": version_record_id,
            "fixIds": applied_ids,
            "rules": rule_ids,
            "reason": body.reason.strip(),
            "documentFingerprint": plan.document_fingerprint,
        },
    }
    audit_detail = {
        "projectId": project_id,
        "sourceVersionId": version_record_id,
        "versionId": new_id,
        "versionLabel": label,
        "fixIds": applied_ids,
        "rules": rule_ids,
        "reason": body.reason.strip(),
        "documentFingerprint": plan.document_fingerprint,
        "reportFingerprint": report_fingerprint,
    }
    try:
        recorded = db.record_lint_fix_revision(
            tenant_id=tenant_id,
            project_id=project_id,
            version_record_id=new_id,
            actor_id=str(actor_id) if actor_id else None,
            provenance=provenance,
            audit_action=AUDIT_LINT_FIX_APPLIED,
            audit_detail=audit_detail,
        )
    except Exception:  # noqa: BLE001 - handled below by withdrawing the revision
        logger.exception("lint-fix record failed version=%s", new_id)
        recorded = False
    if not recorded:
        try:
            db.delete_version(new_id, tenant_id, str(actor_id) if actor_id else None)
        except Exception:  # noqa: BLE001
            logger.exception("lint-fix revision withdrawal failed version=%s", new_id)
        raise _refuse(
            500,
            CODE_RECORD_FAILED,
            "The fixes were not applied: the new revision's audit record could not be written.",
        )

    return LintFixApplyOut(
        project_id=project_id,
        source_version_record_id=version_record_id,
        version_record_id=new_id,
        version_label=label,
        applied_fix_ids=applied_ids,
        skipped=[
            LintFixSkippedOut(fix_id=e.fix_id, rule_id=e.rule_id, status=e.status) for e in skipped
        ],
        score=score,
        grade=grade,
        report_fingerprint=report_fingerprint,
    )
