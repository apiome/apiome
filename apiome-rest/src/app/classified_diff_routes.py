"""CTG-1.2 classified OpenAPI diff REST endpoint (#4468).

``POST /v1/diff/{tenant_slug}/classified`` compares a stored base revision to either
another stored revision or an uploaded (inline) candidate OpenAPI document, and
returns the CTG-1.1 classified change list with summary counts and max severity.

When ``Accept`` requests ``text/markdown`` (or ``text/md``), the response is the
CTG-1.3 markdown changelog instead of JSON (CTG-2.1 / #4471).

Sending ``consumers: true`` adds the CTG-4.2 per-consumer analysis (#4480): the same changes,
intersected with what each registered consumer of the **base** project declared it uses, plus the
"breaks 2 of 7 consumers" summary. It is opt-in because it needs ``consumer_contracts:view`` and
costs a registry read the default gate does not.

Sending ``blastRadius: true`` adds the CDG-3.6 blast-radius line to every breaking change (#5971):
"affects N consumers across M teams (…); K verification runs invalidated", from the CDG-3.3 blast
radius of the change against the **base** project (:mod:`app.diff_blast_radius`). Opt-in too: it
needs ``projects:view`` and runs one graph traversal per breaking pointer.

Since XPC-4.5 (#5749) the request takes a compatibility ``mode`` (``BACKWARD`` / ``FORWARD`` / ``FULL``
/ ``NONE``), ``transitive`` and a Protobuf ``category``, each defaulting to the base project's
style-guide policy. When the base revision's source format has a mode-aware classifier (Avro, JSON
Schema, AsyncAPI) or a category-aware one (Protobuf), both sides are compared as canonical models and
graded by it — an inline head is read with the same importer as the base. Every other format keeps
the CTG-1.1 OpenAPI taxonomy. The response's ``evaluatedUnder`` says which ran and what it ran under,
and every change carries its ``ruleId``.

Since COA-5.6 (#7082) each stored side of the OpenAPI comparison is the revision's rendered document
from the document store (:func:`app.compatibility_engine.read_revision_openapi`), so a warm diff does
no generation; a baseline whose rendered digest equals the head's is reported unchanged without
classifying. The response's ``X-Apiome-Document-Cache`` header says ``hit`` or ``miss`` per side.
Canonical models come from COA-5.4's per-worker model cache, keyed by source digest.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .auth import validate_authentication
from .change_taxonomy import ClassifiedChange, ClassifiedDiff, classify_openapi_changes, summarize_changes
from .changelog_generator import build_changelog, render_changelog_markdown
from .compatibility_engine import (
    DOCUMENT_CACHE_HEADER,
    DOCUMENT_CACHE_HEADER_DOC,
    RevisionOpenApi,
    document_cache_header,
    read_revision_openapi,
    same_document,
)
from .compatibility_modes import (
    Baseline,
    FormatEvaluation,
    canonical_model_for_revision,
    classify_under,
    ctg_changes,
    evaluated_under,
    evaluated_under_markdown,
    merge_transitive,
    parse_candidate,
    revision_format,
    transitive_baselines,
    CTG_RULESET,
)
from .compatibility_policy import (
    CompatibilityPolicy,
    PolicyValueError,
    effective_policy,
    requested_settings,
    resolve_policy,
)
from .compatibility_report_models import EvaluatedUnderOut
from .consumer_impact import ConsumerImpactReport, render_consumer_impact_markdown
from .consumer_impact_service import consumer_impact_for_diff
from .database import db
from .diff_blast_radius import (
    BlastRadiusAnnotations,
    BlastRadiusDiffMeta,
    BlastRadiusSummary,
    annotate_breaking_changes,
)
from .import_ingestion import IngestionError, parse_document
from .permissions import Action, Resource, enforce_permission
from .revision_deprecation import is_uuid_string
from .version_retention import raise_if_pruned

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
    consumers: bool = Field(
        default=False,
        description=(
            "Include the CTG-4.2 per-consumer analysis for the base project's registered "
            "consumers. Requires ``consumer_contracts:view``."
        ),
    )
    blast_radius: bool = Field(
        default=False,
        alias="blastRadius",
        description=(
            "Annotate each breaking change with its CDG-3.3 blast radius against the base project: "
            "consumers affected, their owner teams and the verification runs invalidated. Requires "
            "``projects:view``."
        ),
    )
    mode: Optional[str] = Field(
        default=None,
        description=(
            "Compatibility mode (XPC-4.5): BACKWARD, FORWARD, FULL or NONE, any case. A "
            "``_TRANSITIVE`` name (``FULL_TRANSITIVE``) also sets ``transitive``. Omit to use the "
            "base project's style-guide policy."
        ),
    )
    transitive: Optional[bool] = Field(
        default=None,
        description=(
            "Also compare the head against every earlier revision of the base, not only the base "
            "(XPC-4.5). Omit to use the base project's policy."
        ),
    )
    category: Optional[str] = Field(
        default=None,
        description=(
            "buf breaking category Protobuf changes are graded at (XPC-4.5): WIRE, WIRE_JSON, "
            "PACKAGE or FILE. Omit to use the base project's policy."
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


class ClassifiedDiffAgainstOut(BaseModel):
    """The stored revision a change was found against (transitive comparisons, XPC-4.5)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    revision_id: str = Field(serialization_alias="revisionId")
    version_label: str = Field(serialization_alias="versionLabel")


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
    consumers: Optional[list[str]] = Field(
        default=None,
        description=(
            "Handles of the registered consumers this change touches. ``null`` when the "
            "consumer analysis was not requested; ``[]`` means no registered consumer is "
            "affected."
        ),
    )
    blast_radius: Optional[BlastRadiusSummary] = Field(
        default=None,
        serialization_alias="blastRadius",
        exclude_if=lambda value: value is None,
        description=(
            "With ``blastRadius: true``, on a breaking change: what it affects. Absent otherwise."
        ),
    )
    grade: Optional[Literal["safe", "dangerous", "breaking"]] = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description=(
            "The three-tier grade when a mode- or category-aware classifier graded the change "
            "(XPC-4.5); ``severity`` then maps dangerous and safe to ``non-breaking``. Absent for "
            "the OpenAPI taxonomy."
        ),
    )
    rationale: Optional[str] = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="Why the classifier graded it so, led by the mode or category. Absent for the OpenAPI taxonomy.",
    )
    against: Optional[ClassifiedDiffAgainstOut] = Field(
        default=None,
        exclude_if=lambda value: value is None,
        description="On a transitive comparison: the stored revision the change was found against.",
    )


class ClassifiedDiffResponse(BaseModel):
    """Classified change list with summary counts, max severity, and resolved sides."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    changes: list[ClassifiedDiffChangeOut] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)
    max_severity: Optional[str] = Field(default=None, serialization_alias="maxSeverity")
    base: ClassifiedDiffResolvedStored
    head: ClassifiedDiffHeadMeta
    consumers: Optional[ConsumerImpactReport] = Field(
        default=None,
        description=(
            "CTG-4.2 per-consumer verdicts, present only when ``consumers: true`` was sent."
        ),
    )
    blast_radius: Optional[BlastRadiusDiffMeta] = Field(
        default=None,
        serialization_alias="blastRadius",
        exclude_if=lambda value: value is None,
        description="With ``blastRadius: true``: how many breaking changes were annotated. Absent otherwise.",
    )
    evaluated_under: EvaluatedUnderOut = Field(
        serialization_alias="evaluatedUnder",
        description=(
            "What the changes were graded under: mode, transitivity, Protobuf category, the formats "
            "compared, whether the mode was applied, the ruleset and the revisions compared (XPC-4.5)."
        ),
    )


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
        HTTPException: 400 for empty ref; 410 ``version-pruned`` when version retention pruned it
            (MFI-31.5); 404 when the revision cannot be found.
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
            if not row:
                raise_if_pruned(db, tenant_id, requested)  # MFI-31.5: 410 version-pruned
            raise HTTPException(
                status_code=404,
                detail=f"Revision not found: {requested}",
            )
        return row

    row = db.get_version_by_version_id(project_id, requested, tenant_id)
    if not row:
        raise_if_pruned(db, tenant_id, requested, project_id)  # MFI-31.5: 410 version-pruned
        raise HTTPException(
            status_code=404,
            detail=f"Version {requested!r} was not found for project {project_id!r}",
        )
    return row


def _resolve_stored_side(
    tenant_id: str, ref: ClassifiedDiffStoredRef
) -> tuple[ClassifiedDiffResolvedStored, Dict[str, Any]]:
    """Resolve a stored ref to response metadata and its version row.

    Returns:
        ``(resolved_meta, version_row)``. The document is built later, once the comparison knows
        whether it reads the OpenAPI document or the canonical model.
    """
    project = _resolve_project(tenant_id, ref.project)
    version = _resolve_version_row(tenant_id, str(project["id"]), ref.version)
    meta = ClassifiedDiffResolvedStored(
        project_id=str(project["id"]),
        project_slug=str(project["slug"]),
        version_record_id=str(version["id"]),
        version_label=str(version["version_id"]),
    )
    return meta, version


def _check_inline_size(inline: Optional[str]) -> None:
    """Reject an empty or over-cap inline document.

    Raises:
        HTTPException: 400 when empty; 413 when over the 10MB cap.
    """
    if inline is None:
        raise HTTPException(status_code=400, detail="inline document is empty")
    size = len(inline.encode("utf-8"))
    if size > INLINE_SPEC_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Inline document exceeds the {INLINE_SPEC_MAX_BYTES}-byte "
                f"limit ({size} bytes)"
            ),
        )


def _parse_inline(inline: str) -> Dict[str, Any]:
    """Validate size and parse an inline OpenAPI document.

    Args:
        inline: Raw YAML or JSON text.

    Returns:
        Parsed OpenAPI document mapping.

    Raises:
        HTTPException: 413 when over the 10MB cap; 400 when empty/unparseable.
    """
    _check_inline_size(inline)
    try:
        return parse_document(inline, source_label="inline")
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=exc.message) from exc


class _GradedRow:
    """One change in a comparison, with what the response adds beyond the CTG model."""

    __slots__ = ("change", "grade")

    def __init__(self, change: ClassifiedChange, grade: Optional[str] = None) -> None:
        self.change = change
        self.grade = grade


def _canonical_rows(base_model: Any, head_model: Any, policy: CompatibilityPolicy) -> Tuple[List[_GradedRow], FormatEvaluation]:
    """Grade one canonical pair under ``policy`` as CTG-shaped rows."""
    result, evaluation = classify_under(base_model, head_model, policy)
    return [_GradedRow(change, grade) for change, grade in ctg_changes(result)], evaluation


def _compare(
    *,
    tenant_id: str,
    tenant_slug: str,
    body: ClassifiedDiffRequest,
    base_version: Dict[str, Any],
    head_version: Optional[Dict[str, Any]],
    baselines: Sequence[Baseline],
    policy: CompatibilityPolicy,
) -> Tuple[List[Tuple[Baseline, List[_GradedRow]]], List[FormatEvaluation], Optional[str]]:
    """Compare the head against each baseline: canonically for mode-graded formats, else as OpenAPI.

    Args:
        tenant_id: Tenant id.
        tenant_slug: Tenant slug (to materialize OpenAPI).
        body: The request (its ``head`` is stored or inline).
        base_version: The base revision row.
        head_version: The stored head revision row, or ``None`` for an inline head.
        baselines: The base, then any earlier revisions a transitive comparison adds.
        policy: The effective mode / category.

    Returns:
        ``(pairs, evaluations, cache_header)``: the rows per baseline, how each pair was graded, and
        the ``X-Apiome-Document-Cache`` value for the stored OpenAPI sides read (``None`` on the
        canonical path).

    Raises:
        HTTPException: 400 when an inline head cannot be read as the base's format.
    """
    base_id = str(base_version["id"])
    base_model = canonical_model_for_revision(db, tenant_id, base_id)
    head_model: Any = None
    if base_model is not None:
        if head_version is None:
            inline = body.head.inline  # type: ignore[union-attr]
            _check_inline_size(inline)
            try:
                head_model = parse_candidate(base_model.format, inline)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        else:
            head_model = canonical_model_for_revision(db, tenant_id, str(head_version["id"]))

    pairs: List[Tuple[Baseline, List[_GradedRow]]] = []
    if base_model is not None and head_model is not None:
        evaluations: List[FormatEvaluation] = []
        for baseline in baselines:
            model = (
                base_model
                if baseline.role == "base"
                else canonical_model_for_revision(db, tenant_id, baseline.revision_id)
            )
            if model is None:
                continue
            rows, evaluation = _canonical_rows(model, head_model, policy)
            evaluations.append(evaluation)
            pairs.append((baseline, rows))
        return pairs, evaluations, None

    # The base document is read before the head's, as it always was.
    base_doc = read_revision_openapi(base_version, tenant_slug, tenant_id)
    sides: List[Tuple[str, RevisionOpenApi]] = [("base", base_doc)]
    head_doc: Optional[RevisionOpenApi] = None
    if head_version is None:
        head_spec = _parse_inline(body.head.inline)  # type: ignore[union-attr]
    else:
        head_doc = read_revision_openapi(head_version, tenant_slug, tenant_id)
        sides.append(("head", head_doc))
        head_spec = head_doc.spec
    for baseline in baselines:
        if baseline.role == "base":
            doc = base_doc
        else:
            row = db.get_version_by_id(baseline.revision_id, tenant_id)
            if not row:
                continue
            doc = read_revision_openapi(row, tenant_slug, tenant_id)
            sides.append(("prior", doc))
        if head_doc is not None and same_document(doc, head_doc):
            # Byte-identical documents: nothing to classify (COA-5.6).
            pairs.append((baseline, []))
            continue
        pairs.append((baseline, [_GradedRow(c) for c in classify_openapi_changes(doc.spec, head_spec).changes]))
    fmt = revision_format(db, tenant_id, base_id)
    return pairs, [FormatEvaluation(format=fmt, ruleset=CTG_RULESET)], document_cache_header(sides)


def _response_from_classified(
    result: ClassifiedDiff,
    *,
    base_meta: ClassifiedDiffResolvedStored,
    head_meta: ClassifiedDiffHeadMeta,
    evaluated: EvaluatedUnderOut,
    extras: Optional[Sequence[Tuple[Optional[str], Optional[ClassifiedDiffAgainstOut]]]] = None,
    impact: Optional[ConsumerImpactReport] = None,
    annotations: Optional[BlastRadiusAnnotations] = None,
) -> ClassifiedDiffResponse:
    """Map a pure ClassifiedDiff onto the REST response model.

    Args:
        result: The CTG-1.1 classification.
        base_meta: Resolved base coordinates.
        head_meta: Resolved head coordinates.
        impact: CTG-4.2 per-consumer analysis, when it was requested. Each change then also
            carries the handles it touches, so a caller never has to re-join the two lists.
        annotations: CDG-3.6 blast-radius summaries, when they were requested; each breaking change
            with a summary carries it as ``blastRadius``.
        evaluated: The ``evaluatedUnder`` block (XPC-4.5).
        extras: Per change, in ``result.changes`` order: its three-tier grade and the revision it
            was found against (each ``None`` when it does not apply).

    Returns:
        The response model.
    """
    slugs_by_change: Dict[tuple[str, str, str], list[str]] = {}
    if impact is not None:
        for entry in impact.attribution:
            slugs_by_change[(entry.pointer, entry.rule_id, entry.change_kind)] = list(
                entry.consumers
            )

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
                consumers=(
                    None
                    if impact is None
                    else slugs_by_change.get((c.pointer, c.rule_id, c.change_kind), [])
                ),
                blast_radius=(
                    annotations.by_pointer.get(c.pointer)
                    if annotations is not None and c.severity == "breaking"
                    else None
                ),
                grade=(extras[i][0] if extras else None),
                rationale=c.rationale,
                against=(extras[i][1] if extras else None),
            )
            for i, c in enumerate(result.changes)
        ],
        counts=dict(result.counts),
        max_severity=result.max_severity,
        base=base_meta,
        head=head_meta,
        consumers=impact,
        blast_radius=None if annotations is None else annotations.meta(),
        evaluated_under=evaluated,
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
            "headers": DOCUMENT_CACHE_HEADER_DOC,
            "content": {
                "text/markdown": {
                    "schema": {"type": "string", "contentMediaType": "text/markdown"}
                },
            },
        }
    },
)
def post_classified_diff(
    tenant_slug: str,
    body: ClassifiedDiffRequest,
    response: Response,
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

    With ``consumers: true`` the response also carries the CTG-4.2 per-consumer analysis —
    ``consumers`` on the body, and the touched handles on each change — and the markdown gains a
    "Consumer impact" section. Consumers are those registered against the **base** project, since
    that is the published contract they declared against; the flag needs
    ``consumer_contracts:view``.

    With ``blastRadius: true`` each breaking change also carries ``blastRadius`` — consumers
    affected, their owner teams and verification runs invalidated, from the CDG-3.3 blast radius of
    the change against the base project and revision — and each breaking row of the markdown gains a
    "Blast radius:" line. The flag needs ``projects:view``.

    Stored OpenAPI sides are read from the rendered document cache (COA-5.6); the
    ``X-Apiome-Document-Cache`` header reports ``hit`` or ``miss`` for ``base``, ``head`` and, on a
    transitive comparison, ``prior``. It is absent when the sides were compared as canonical models.
    """
    enforce_permission(db, auth_data, Resource.VERSIONS, Action.VIEW)
    if body.consumers:
        enforce_permission(db, auth_data, Resource.CONSUMER_CONTRACTS, Action.VIEW)
    if body.blast_radius:
        enforce_permission(db, auth_data, Resource.PROJECTS, Action.VIEW, target="graph")
    tenant_id = str(auth_data["tenant_id"])

    base_meta, base_version = _resolve_stored_side(tenant_id, body.base)

    head_version: Optional[Dict[str, Any]] = None
    if isinstance(body.head, ClassifiedDiffInlineHead):
        head_meta = ClassifiedDiffHeadMeta(source="inline")
    else:
        stored_head, head_version = _resolve_stored_side(tenant_id, body.head)
        head_meta = ClassifiedDiffHeadMeta(
            source="stored",
            project_id=stored_head.project_id,
            project_slug=stored_head.project_slug,
            version_record_id=stored_head.version_record_id,
            version_label=stored_head.version_label,
        )

    try:
        policy = effective_policy(
            resolve_policy(db, tenant_id, base_meta.project_id),
            mode=body.mode,
            transitive=body.transitive,
            category=body.category,
        )
    except PolicyValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    baselines, truncated = transitive_baselines(
        db,
        tenant_id=tenant_id,
        project_id=base_meta.project_id,
        base_revision_id=base_meta.version_record_id,
        base_label=base_meta.version_label,
        transitive=policy.transitive,
    )
    pairs, evaluations, cache_header = _compare(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        body=body,
        base_version=base_version,
        head_version=head_version,
        baselines=baselines,
        policy=policy,
    )
    cache_headers = {DOCUMENT_CACHE_HEADER: cache_header} if cache_header else {}
    response.headers.update(cache_headers)
    merged = merge_transitive(
        pairs,
        key=lambda r: (r.change.rule_id, r.change.pointer, r.change.change_kind),
        is_breaking=lambda r: r.change.severity == "breaking",
    )
    result = summarize_changes([row.change for _, row in merged])
    extras = [
        (
            row.grade,
            ClassifiedDiffAgainstOut(revision_id=b.revision_id, version_label=b.version_label)
            if policy.transitive
            else None,
        )
        for b, row in merged
    ]
    evaluated = evaluated_under(
        policy,
        evaluations,
        requested=requested_settings(mode=body.mode, transitive=body.transitive, category=body.category),
        compared=baselines,
        truncated=truncated,
    )

    impact: Optional[ConsumerImpactReport] = None
    if body.consumers:
        impact = consumer_impact_for_diff(
            tenant_id,
            base_meta.project_id,
            result,
            base_version_id=str(base_version.get("id") or "") or None,
        )

    annotations: Optional[BlastRadiusAnnotations] = None
    if body.blast_radius:
        annotations = annotate_breaking_changes(
            db,
            tenant_id,
            base_meta.project_id,
            base_meta.version_record_id,
            result.changes,
        )

    if _wants_markdown(accept):
        to_version = head_meta.version_label or "inline"
        changelog = build_changelog(
            result,
            from_version=base_meta.version_label,
            to_version=to_version,
        )
        md = render_changelog_markdown(
            changelog, annotations=annotations.lines() if annotations is not None else None
        )
        if annotations is not None and annotations.skipped:
            md = md.rstrip("\n") + (
                f"\n\n_Blast radius shown for the first {annotations.meta().limit} breaking changes; "
                f"{annotations.skipped} more were not checked._\n"
            )
        if impact is not None:
            md = md.rstrip("\n") + "\n\n" + render_consumer_impact_markdown(impact)
        graded_under = evaluated_under_markdown(evaluated)
        if graded_under:
            md = md.rstrip("\n") + "\n\n" + graded_under + "\n"
        return Response(content=md, media_type="text/markdown; charset=utf-8", headers=cache_headers)

    return _response_from_classified(
        result,
        base_meta=base_meta,
        head_meta=head_meta,
        evaluated=evaluated,
        extras=extras,
        impact=impact,
        annotations=annotations,
    )
