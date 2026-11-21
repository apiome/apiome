"""
Backward compatibility API: compare two schema revisions (versions.id) using generated OpenAPI.

Since XPC-4.5 (#5749) the check takes a compatibility ``mode``, ``transitive`` and a Protobuf
``category``, each defaulting to the project's style-guide policy. Revisions whose source format has
a mode-aware classifier (Avro, JSON Schema, AsyncAPI) or a category-aware one (Protobuf) are graded
by it from their canonical models; every other revision keeps the OpenAPI engine, and the response's
``evaluatedUnder.modeApplied`` says which happened.

Also exposes independent oasdiff compatibility evidence (CLX-2.3 / #4853) with
normalized JSON / SARIF / JUnit gate outputs.

Since COA-5.6 (#7082) both routes read each revision's rendered OpenAPI document from the document
store (:func:`app.compatibility_engine.read_revision_openapi`) instead of generating it, a baseline
byte-identical to the head yields no findings without running the engine, and the check's response
carries ``X-Apiome-Document-Cache`` (``hit`` / ``miss`` per side).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from .auth import validate_authentication
from .compatibility_engine import (
    DOCUMENT_CACHE_HEADER,
    DOCUMENT_CACHE_HEADER_DOC,
    CompatibilityCheckEngine,
    RevisionOpenApi,
    compat_report_fingerprint,
    document_cache_header,
    read_revision_openapi,
    same_document,
)
from .compatibility_modes import (
    NATIVE_COMPAT_RULESET,
    Baseline,
    FormatEvaluation,
    GradedChange,
    canonical_model_for_revision,
    classify_under,
    evaluated_under,
    graded_changes,
    merge_transitive,
    revision_format,
    transitive_baselines,
)
from .compatibility_policy import (
    CompatibilityPolicy,
    PolicyValueError,
    effective_policy,
    requested_settings,
    resolve_policy,
)
from .database import db
from .gate_report_emit import (
    GATE_FORMAT_JSON,
    normalize_gate_format,
    serialize_gate,
    to_normalized_json,
)
from .openapi_compatibility_adapters import OASDIFF_ADAPTER_ID, OASDIFF_ADAPTER_VERSION
from .openapi_compatibility_evidence import (
    capture_oasdiff_compatibility_evidence,
    run_oasdiff_compatibility,
)
from .permissions import enforce_permission, Resource, Action
from .models import (
    CompatibilityAgainstOut,
    CompatibilityCheckRequest,
    CompatibilityCheckResponse,
    CompatibilityEvidenceFindingOut,
    CompatibilityEvidenceRequest,
    CompatibilityEvidenceResponse,
    CompatibilityFindingOut,
    LintEvidenceResponse,
    RevisionDeprecationWarningOut,
    lint_evidence_response_from_rows,
)
from .revision_deprecation import warnings_for_revision
from .schema_compatibility import BREAKING_DOC_ISSUE_URL, CompatibilityRules


router = APIRouter(prefix="/v1/versions", tags=["compatibility"])


def _parse_project_metadata(metadata: Any) -> Dict[str, Any]:
    if metadata is None:
        return {}
    if isinstance(metadata, dict):
        return metadata
    if isinstance(metadata, str):
        try:
            parsed = json.loads(metadata)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _tenant_compat_gate(project: Dict[str, Any]) -> bool:
    return bool(_parse_project_metadata(project.get("metadata")).get("compatGateOnMerge"))


def _tenant_fail_ci_on_deprecated(project: Dict[str, Any]) -> bool:
    """When true, consumers should treat deprecated revisions as merge/CI blockers (see ``deprecatedRevisionBlocked``)."""
    return bool(_parse_project_metadata(project.get("metadata")).get("failCiOnDeprecatedRevision"))


def _rules_from_payload(req: CompatibilityCheckRequest) -> CompatibilityRules:
    p = req.rules
    if not p:
        return CompatibilityRules()
    return CompatibilityRules(
        check_paths=p.check_paths,
        check_schemas=p.check_schemas,
        treat_removed_schema_as_breaking=p.treat_removed_schema_as_breaking,
        treat_removed_property_as_breaking=p.treat_removed_property_as_breaking,
        treat_removed_path_as_breaking=p.treat_removed_path_as_breaking,
        treat_removed_operation_as_breaking=p.treat_removed_operation_as_breaking,
        detect_possible_renames=p.detect_possible_renames,
    )


#: Canonical severity → the compatibility response's finding category.
_CATEGORY_OF_SEVERITY = {"breaking": "breaking", "dangerous": "unknown", "safe": "safe"}

#: The finding keys the report fingerprint has always covered; ``against`` joins them on a
#: transitive check. ``ruleId`` and ``severity`` restate ``rule`` / ``category`` and stay out, so
#: an OpenAPI report's fingerprint is what it was before XPC-4.5.
_FINGERPRINT_KEYS = ("id", "path", "category", "rule", "message")


def _canonical_finding(change: GradedChange) -> CompatibilityFindingOut:
    """Map one canonical grade onto a compatibility finding."""
    category = _CATEGORY_OF_SEVERITY.get(change.severity, "unknown")
    digest = hashlib.sha256(
        f"{change.pointer}|{change.rule_id}|{change.rationale}".encode("utf-8")
    ).hexdigest()[:16]
    return CompatibilityFindingOut(
        id=f"cmp-{digest}",
        path=change.pointer,
        category=category,
        rule=change.rule_id,
        message=change.rationale,
        rule_id=change.rule_id,
        severity=change.severity,
    )


def _overall_of(findings: Sequence[CompatibilityFindingOut]) -> str:
    """Worst finding category: ``breaking`` over ``unknown`` over ``safe``."""
    categories = {f.category for f in findings}
    if "breaking" in categories:
        return "breaking"
    if "unknown" in categories:
        return "unknown"
    return "safe"


def _fingerprint_dict(finding: CompatibilityFindingOut) -> Dict[str, Any]:
    """The part of a finding the report fingerprint covers."""
    out: Dict[str, Any] = {key: getattr(finding, key) for key in _FINGERPRINT_KEYS}
    if finding.against is not None:
        out["against"] = finding.against.model_dump(by_alias=True)
    return out


def _compare_baselines(
    *,
    tenant_slug: str,
    tenant_id: str,
    base_ver: Dict[str, Any],
    head_ver: Dict[str, Any],
    baselines: Sequence[Baseline],
    compat_policy: CompatibilityPolicy,
    rules: CompatibilityRules,
) -> Tuple[
    List[Tuple[Baseline, List[CompatibilityFindingOut]]],
    List[FormatEvaluation],
    Optional[Tuple[Dict[str, Any], Dict[str, Any]]],
    Optional[str],
]:
    """Compare the head against each baseline, with the mode-aware classifier when there is one.

    Args:
        tenant_slug: Tenant slug (to materialize OpenAPI).
        tenant_id: Tenant id.
        base_ver: The base revision row.
        head_ver: The head revision row.
        baselines: The base, then any earlier revisions a transitive check adds.
        compat_policy: The effective mode / category.
        rules: The OpenAPI engine's toggles (unused on the canonical path).

    Returns:
        ``(pairs, evaluations, specs, cache_header)``: findings per baseline; how each canonical
        pair was graded (empty on the OpenAPI path); the base and head OpenAPI documents on the
        OpenAPI path (``None`` on the canonical one); and the ``X-Apiome-Document-Cache`` value for
        the OpenAPI sides read (``None`` on the canonical path). An earlier revision whose source
        cannot be rebuilt is skipped. A baseline whose rendered document is byte-identical to the
        head's has no findings and is not run through the engine (COA-5.6).
    """
    head_id, base_id = str(head_ver["id"]), str(base_ver["id"])
    head_model = canonical_model_for_revision(db, tenant_id, head_id)
    base_model = canonical_model_for_revision(db, tenant_id, base_id) if head_model is not None else None
    pairs: List[Tuple[Baseline, List[CompatibilityFindingOut]]] = []

    if head_model is not None and base_model is not None:
        evaluations: List[FormatEvaluation] = []
        for baseline in baselines:
            model = (
                base_model
                if baseline.role == "base"
                else canonical_model_for_revision(db, tenant_id, baseline.revision_id)
            )
            if model is None:
                continue
            result, evaluation = classify_under(model, head_model, compat_policy)
            evaluations.append(evaluation)
            pairs.append((baseline, [_canonical_finding(c) for c in graded_changes(result)]))
        return pairs, evaluations, None, None

    base_doc = read_revision_openapi(base_ver, tenant_slug, tenant_id)
    head_doc = read_revision_openapi(head_ver, tenant_slug, tenant_id)
    sides: List[Tuple[str, RevisionOpenApi]] = [("base", base_doc), ("head", head_doc)]
    for baseline in baselines:
        if baseline.role == "base":
            doc = base_doc
        else:
            row = db.get_version_by_id(baseline.revision_id, tenant_id)
            if not row:
                continue
            doc = read_revision_openapi(row, tenant_slug, tenant_id)
            sides.append(("prior", doc))
        if same_document(doc, head_doc):
            pairs.append((baseline, []))
            continue
        result = CompatibilityCheckEngine.run(doc.spec, head_doc.spec, rules)
        pairs.append(
            (
                baseline,
                [
                    CompatibilityFindingOut(
                        id=f.id,
                        path=f.path,
                        category=f.category,
                        rule=f.rule,
                        message=f.message,
                        rule_id=f.rule,
                    )
                    for f in result.findings
                ],
            )
        )
    head_format = revision_format(db, tenant_id, head_id)
    return (
        pairs,
        [FormatEvaluation(format=head_format, ruleset=NATIVE_COMPAT_RULESET)],
        (base_doc.spec, head_doc.spec),
        document_cache_header(sides),
    )


@router.post(
    "/{tenant_slug}/{project_id}/compatibility",
    response_model=CompatibilityCheckResponse,
    responses={200: {"headers": DOCUMENT_CACHE_HEADER_DOC}},
)
async def check_revision_compatibility(
    tenant_slug: str,
    project_id: str,
    body: CompatibilityCheckRequest,
    http_response: Response,
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> CompatibilityCheckResponse:
    """
    Compare **baseRevisionId** (older / consumer expectation) to **headRevisionId** (newer).
    Returns structured safe / breaking / unknown findings for CI-style merge gates.

    ``mode`` (BACKWARD / FORWARD / FULL / NONE), ``transitive`` and ``category`` (Protobuf) default
    to the project's style-guide policy. Avro, JSON Schema and AsyncAPI revisions are graded by
    mode, Protobuf revisions at the category; other formats keep the OpenAPI engine and report
    ``evaluatedUnder.modeApplied: false``. With ``transitive`` the head is also compared against
    every earlier revision of the base, and each finding names the revision it was found against.

    Each side is the revision's rendered OpenAPI document from the document store (COA-5.6);
    ``X-Apiome-Document-Cache`` reports ``hit`` or ``miss`` per side, on the 409 replies too.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    base_id = (body.base_revision_id or "").strip()
    head_id = (body.head_revision_id or "").strip()
    if not base_id or not head_id:
        raise HTTPException(
            status_code=400,
            detail="baseRevisionId and headRevisionId are required",
        )
    if base_id == head_id:
        raise HTTPException(
            status_code=400,
            detail="baseRevisionId and headRevisionId must differ",
        )

    base_ver = db.get_version_by_id(base_id, tenant_id)
    head_ver = db.get_version_by_id(head_id, tenant_id)
    if not base_ver:
        raise HTTPException(status_code=404, detail=f"Revision not found: {base_id}")
    if not head_ver:
        raise HTTPException(status_code=404, detail=f"Revision not found: {head_id}")

    if base_ver["project_id"] != project_id or head_ver["project_id"] != project_id:
        raise HTTPException(
            status_code=400,
            detail="Both revisions must belong to the specified project",
        )

    try:
        compat_policy = effective_policy(
            resolve_policy(db, tenant_id, project_id),
            mode=body.mode,
            transitive=body.transitive,
            category=body.category,
        )
    except PolicyValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    baselines, truncated = transitive_baselines(
        db,
        tenant_id=tenant_id,
        project_id=project_id,
        base_revision_id=base_id,
        base_label=str(base_ver["version_id"]),
        transitive=compat_policy.transitive,
    )
    pairs, evaluations, specs, cache_header = _compare_baselines(
        tenant_slug=tenant_slug,
        tenant_id=tenant_id,
        base_ver=base_ver,
        head_ver=head_ver,
        baselines=baselines,
        compat_policy=compat_policy,
        rules=_rules_from_payload(body),
    )
    cache_headers = {DOCUMENT_CACHE_HEADER: cache_header} if cache_header else {}
    http_response.headers.update(cache_headers)
    merged = merge_transitive(
        pairs,
        key=lambda f: (f.rule, f.path),
        is_breaking=lambda f: f.category == "breaking",
    )
    finding_out = [
        (
            f.model_copy(
                update={
                    "against": CompatibilityAgainstOut(
                        revision_id=b.revision_id, version_label=b.version_label
                    )
                }
            )
            if compat_policy.transitive
            else f
        )
        for b, f in merged
    ]
    overall = _overall_of(finding_out)
    finding_dicts = [_fingerprint_dict(f) for f in finding_out]
    rule_hits: Dict[str, int] = {}
    for f in finding_out:
        rule_hits[f.rule] = rule_hits.get(f.rule, 0) + 1
    rule_hits_sorted = dict(sorted(rule_hits.items()))
    under = evaluated_under(
        compat_policy,
        evaluations,
        requested=requested_settings(
            mode=body.mode, transitive=body.transitive, category=body.category
        ),
        compared=baselines,
        truncated=truncated,
        default_ruleset=NATIVE_COMPAT_RULESET,
    )

    dep_out: List[RevisionDeprecationWarningOut] = []
    dep_out.extend(
        warnings_for_revision(
            revision_id=base_ver["id"],
            version_label=base_ver["version_id"],
            role="base",
            metadata=base_ver.get("metadata"),
        )
    )
    dep_out.extend(
        warnings_for_revision(
            revision_id=head_ver["id"],
            version_label=head_ver["version_id"],
            role="head",
            metadata=head_ver.get("metadata"),
        )
    )

    dep_dicts = [w.model_dump(by_alias=True) for w in dep_out]
    fp = compat_report_fingerprint(overall, finding_dicts, dep_dicts or None)

    tenant_gate = _tenant_compat_gate(project)
    merge_blocked = bool(tenant_gate and overall != "safe")
    fail_dep = _tenant_fail_ci_on_deprecated(project)
    deprecated_revision_blocked = bool(fail_dep and dep_out)

    doc_url = BREAKING_DOC_ISSUE_URL if overall == "breaking" else None

    response = CompatibilityCheckResponse(
        overall=overall,
        base_revision_id=base_id,
        head_revision_id=head_id,
        findings=finding_out,
        rule_hits=rule_hits_sorted,
        breaking_change_documentation_issue_url=doc_url,
        report_fingerprint=fp,
        tenant_compat_gate_active=tenant_gate,
        merge_blocked_by_compat_gate=merge_blocked,
        deprecation_warnings=dep_out,
        deprecated_revision_blocked=deprecated_revision_blocked,
        evaluated_under=under,
    )

    policy = body.policy
    if policy and policy.http409_when_breaking and overall == "breaking":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "COMPATIBILITY_BREAKING",
                "message": "Head revision introduces breaking changes relative to base",
                "report": response.model_dump(by_alias=True),
            },
            headers=cache_headers or None,
        )

    if policy and policy.http409_when_deprecated_revision and dep_out:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "DEPRECATED_REVISION",
                "message": "One or both revisions in this compatibility check are deprecated",
                "report": response.model_dump(by_alias=True),
            },
            headers=cache_headers or None,
        )

    # CLX-2.3: best-effort independent oasdiff evidence (does not affect native gate). Only the
    # OpenAPI path has documents to give it.
    try:
        if specs is None:
            return response
        base_spec, head_spec = specs
        await capture_oasdiff_compatibility_evidence(
            base_document=base_spec,
            head_document=head_spec,
            version_record_id=str(head_id),
            base_revision_id=base_id,
            head_revision_id=head_id,
        )
    except Exception:  # noqa: BLE001
        pass

    return response


def _resolve_revision_pair(
    *,
    tenant_id: str,
    project_id: str,
    base_id: str,
    head_id: str,
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    if not base_id or not head_id:
        raise HTTPException(
            status_code=400,
            detail="baseRevisionId and headRevisionId are required",
        )
    if base_id == head_id:
        raise HTTPException(
            status_code=400,
            detail="baseRevisionId and headRevisionId must differ",
        )
    base_ver = db.get_version_by_id(base_id, tenant_id)
    head_ver = db.get_version_by_id(head_id, tenant_id)
    if not base_ver:
        raise HTTPException(status_code=404, detail=f"Revision not found: {base_id}")
    if not head_ver:
        raise HTTPException(status_code=404, detail=f"Revision not found: {head_id}")
    if base_ver["project_id"] != project_id or head_ver["project_id"] != project_id:
        raise HTTPException(
            status_code=400,
            detail="Both revisions must belong to the specified project",
        )
    return base_ver, head_ver


def _evidence_response_from_run(
    *,
    result: Any,
    changelog_md: Optional[str],
    base_id: str,
    head_id: str,
    evidence_run_id: Optional[str],
) -> CompatibilityEvidenceResponse:
    from .external_linter_evidence import outcome_for_adapter_result

    findings = [
        CompatibilityEvidenceFindingOut(
            rule_id=f.get("rule_id"),
            message=f.get("message"),
            severity=f.get("severity"),
            change_class=f.get("change_class"),
            category=f.get("category"),
            location=f.get("location") if isinstance(f.get("location"), dict) else {},
            source_fingerprint=f.get("source_fingerprint"),
            remediation=f.get("remediation"),
        )
        for f in (result.envelope_findings or [])
    ]
    outcome = outcome_for_adapter_result(
        failure_kind=result.failure_kind,
        findings=result.envelope_findings or [],
    )
    payload = to_normalized_json(
        findings=result.envelope_findings or [],
        scanner_id=OASDIFF_ADAPTER_ID,
        base_revision_id=base_id,
        head_revision_id=head_id,
        outcome=outcome,
        changelog_markdown=changelog_md,
        coverage=(
            {
                "state": "none" if result.failure_kind else "full",
                "failureKind": result.failure_kind,
                "diagnostics": result.diagnostics,
            }
            if result.failure_kind
            else {"state": "full"}
        ),
        evidence_run_id=evidence_run_id,
    )
    return CompatibilityEvidenceResponse(
        schema_version=1,
        scanner_id=OASDIFF_ADAPTER_ID,
        base_revision_id=base_id,
        head_revision_id=head_id,
        outcome=payload.get("outcome"),
        overall=str(payload.get("overall") or "safe"),
        counts=payload.get("counts") or {},
        findings=findings,
        coverage=payload.get("coverage") or {},
        changelog_markdown=changelog_md,
        evidence_run_id=evidence_run_id,
    )


@router.post(
    "/{tenant_slug}/{project_id}/compatibility/evidence",
    response_model=None,
)
async def create_compatibility_evidence(
    tenant_slug: str,
    project_id: str,
    body: CompatibilityEvidenceRequest,
    request: Request,
    format: Optional[str] = Query(
        default=None,
        description="Gate output format: json (default), sarif, or junit.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Any:
    """Run oasdiff, persist evidence on the head revision, return gate output.

    Emits normalized JSON by default. Pass ``?format=sarif`` or ``?format=junit``
    (or matching ``Accept``) for CI-compatible artifacts.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")

    base_id = (body.base_revision_id or "").strip()
    head_id = (body.head_revision_id or "").strip()
    base_ver, head_ver = _resolve_revision_pair(
        tenant_id=tenant_id,
        project_id=project_id,
        base_id=base_id,
        head_id=head_id,
    )
    # Both sides from the rendered document cache (COA-5.6, #7082).
    base_spec = read_revision_openapi(base_ver, tenant_slug, tenant_id).spec
    head_spec = read_revision_openapi(head_ver, tenant_slug, tenant_id).spec

    result, changelog_md, changelog_html = await run_oasdiff_compatibility(
        base_document=base_spec,
        head_document=head_spec,
    )
    evidence_run_id = await capture_oasdiff_compatibility_evidence(
        base_document=base_spec,
        head_document=head_spec,
        version_record_id=str(head_id),
        base_revision_id=base_id,
        head_revision_id=head_id,
        result=result,
        changelog_md=changelog_md,
        changelog_html=changelog_html,
    )

    accept = request.headers.get("accept")
    fmt = normalize_gate_format(format or accept)
    if fmt != GATE_FORMAT_JSON:
        body_text, media = serialize_gate(
            fmt,
            findings=result.envelope_findings or [],
            scanner_id=OASDIFF_ADAPTER_ID,
            base_revision_id=base_id,
            head_revision_id=head_id,
            outcome=_evidence_response_from_run(
                result=result,
                changelog_md=changelog_md,
                base_id=base_id,
                head_id=head_id,
                evidence_run_id=evidence_run_id,
            ).outcome,
            changelog_markdown=changelog_md,
            evidence_run_id=evidence_run_id,
            tool_version=OASDIFF_ADAPTER_VERSION,
        )
        return Response(content=body_text, media_type=media)

    return _evidence_response_from_run(
        result=result,
        changelog_md=changelog_md,
        base_id=base_id,
        head_id=head_id,
        evidence_run_id=evidence_run_id,
    )


@router.get(
    "/{tenant_slug}/{project_id}/{version_id}/compatibility/evidence",
    response_model=None,
)
async def list_compatibility_evidence(
    tenant_slug: str,
    project_id: str,
    version_id: str,
    request: Request,
    format: Optional[str] = Query(
        default=None,
        description="When set to sarif/junit, emit gate output for the latest oasdiff run.",
    ),
    auth_data: Dict[str, Any] = Depends(validate_authentication),
) -> Any:
    """List persisted oasdiff compatibility evidence runs for a revision."""
    _ = tenant_slug
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    tenant_id = auth_data["tenant_id"]
    project = db.get_project_by_id(project_id, tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_id}")
    version = db.get_version_by_id(version_id, tenant_id)
    if not version or version["project_id"] != project_id:
        raise HTTPException(status_code=404, detail=f"Revision not found: {version_id}")

    rows = db.list_lint_evidence_runs_for_version(version_id, tenant_id)
    oasdiff_rows = [
        row for row in rows if str(row.get("scanner_id") or "") == OASDIFF_ADAPTER_ID
    ]
    fmt = normalize_gate_format(format or request.headers.get("accept"))
    if fmt != GATE_FORMAT_JSON and oasdiff_rows:
        latest = oasdiff_rows[0]
        findings = latest.get("findings") or []
        coverage = latest.get("coverage") if isinstance(latest.get("coverage"), dict) else {}
        body_text, media = serialize_gate(
            fmt,
            findings=findings,
            scanner_id=OASDIFF_ADAPTER_ID,
            base_revision_id=coverage.get("baseRevisionId"),
            head_revision_id=coverage.get("headRevisionId") or version_id,
            outcome=str(latest.get("outcome") or ""),
            changelog_markdown=coverage.get("changelogMarkdown"),
            coverage=coverage,
            evidence_run_id=str(latest.get("id")) if latest.get("id") else None,
            tool_version=str(latest.get("adapter_version") or OASDIFF_ADAPTER_VERSION),
        )
        return Response(content=body_text, media_type=media)

    return lint_evidence_response_from_rows(
        "catalog_revision",
        version_id,
        oasdiff_rows,
    )
