"""Fidelity / completeness gap analyzer — MFI-22.3 (#4004).

The emitter (:mod:`app.openapi_emitter`, MFI-22.1) turns a
:class:`~app.canonical_model.CanonicalApi` into an OpenAPI 3.1 document, and the
paradigm projections (:mod:`app.projection`, MFI-22.2) declare — as
:class:`~app.emitter.Loss` records — what each non-REST source could *not* carry
faithfully onto OpenAPI's path/verb/response vocabulary. Both leave a trail: the
emitter tags **every emitted value** with a :class:`~app.emitter.Provenance`
(``source`` / ``inferred`` / ``default``) and the projection records its
``inferred`` / ``n/a`` losses. *This* module reads that trail — the
:class:`~app.emitter.EmitResult` plus the source model — and answers the question a
user must see *before* committing a conversion: **what will the converted spec
contain, what did the conversion have to invent, and what did it lose?**

It produces a structured :class:`FidelityReport`:

* a **completeness checklist** (:class:`ChecklistItem`) — one row per load-bearing
  OpenAPI construct (``info`` fields, ``servers``, ``paths``, ``operationId``,
  parameters, ``requestBody``, ``responses``, ``components.schemas``, security,
  ``tags``, ``examples``, ``externalDocs``, ``deprecated``). Each row carries a
  :class:`Coverage` tag (``present`` / ``inferred`` / ``partial`` / ``missing`` /
  ``n/a``), a count, up to a few example coordinates, and a human-readable reason
  ("source declares no servers", "gRPC method has no media types");

* the **enumerated projection losses** carried straight through from the
  :class:`~app.emitter.EmitResult`, so a pub/sub action or a GraphQL subscription is
  shown, not silently dropped;

* a rolled-up **fidelity score** (0-100) and **A-F grade** — reusing the house
  grade bands (:data:`app.schema_lint.GRADE_THRESHOLDS`, the MFI-4.2 banding) so a
  fidelity grade reads like a lint grade — weighted by how *load-bearing* each
  inferred/partial/missing construct is, plus a per-loss penalty; and

* a coarse **fidelity tier** (``high`` / ``medium`` / ``low``) derived from the
  score, which the conversion preview (MFI-22.4) uses to scale how strong its
  warning is.

The analyzer is **pure and deterministic**: no DB or network, checklist rows in a
fixed order, examples sorted and capped, so the same ``(api, result)`` always yields
an equal report.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .emitter import EmitResult, Loss, LossKind, Provenance, ProvenanceTracker
from .schema_lint import GRADE_THRESHOLDS

__all__ = [
    "Coverage",
    "FidelityTier",
    "ChecklistItem",
    "FidelityReport",
    "FidelityAnalyzer",
    "analyze_fidelity",
]

#: Most example coordinates any one checklist row carries (kept small + sorted so
#: the report is compact and deterministic).
MAX_EXAMPLES = 3

#: Penalty weight charged per projection loss, by kind. An ``n/a`` loss (a source
#: capability with *no* OpenAPI representation — a pub/sub action, a subscription,
#: streaming) is a real fidelity gap and is charged; an ``inferred`` loss (a
#: synthesized binding) is already reflected in the ``paths`` checklist row's
#: ``inferred`` coverage, so it is not double-charged here.
LOSS_PENALTY: Dict[LossKind, float] = {
    LossKind.NA: 5.0,
    LossKind.INFERRED: 0.0,
}

#: Score at or above which the conversion is ``high`` fidelity; below
#: :data:`TIER_MEDIUM_MIN` it is ``low``. These coarse tiers drive how strong the
#: MFI-22.4 preview warning is.
TIER_HIGH_MIN = 85
TIER_MEDIUM_MIN = 60


class Coverage(str, Enum):
    """How completely one OpenAPI construct survived the conversion.

    * :attr:`PRESENT` — carried faithfully from the source (every instance
      :attr:`~app.emitter.Provenance.SOURCE`).
    * :attr:`INFERRED` — emitted, but *derived* by the conversion rather than stated
      by the source (a synthesized HTTP binding, a defaulted status code / media
      type, a synthesized ``operationId``).
    * :attr:`PARTIAL` — some instances faithful, others inferred/absent.
    * :attr:`MISSING` — an OpenAPI construct the source *could* have carried but this
      conversion has none of (no servers, no response status codes).
    * :attr:`NA` — the construct has no counterpart for this source: either the
      canonical model does not retain it (contact, license, examples) or the source
      paradigm simply has none of it (a schema-only source has no operations).
    """

    PRESENT = "present"
    INFERRED = "inferred"
    PARTIAL = "partial"
    MISSING = "missing"
    NA = "n/a"


class FidelityTier(str, Enum):
    """Coarse three-band fidelity signal derived from the score.

    Drives how strong the conversion-preview (MFI-22.4) warning is: a ``low`` tier
    warrants an explicit, dismiss-to-proceed acknowledgement, a ``high`` tier a
    reassuring note.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ChecklistItem(BaseModel):
    """One completeness-checklist row: how one OpenAPI construct fared.

    ``count`` is how many instances of the construct were considered (paths,
    parameters, response objects…); ``examples`` are up to :data:`MAX_EXAMPLES`
    coordinates (JSON Pointers into the emitted document, or source keys) that
    illustrate the row, sorted for determinism.
    """

    model_config = ConfigDict(extra="forbid")

    key: str = Field(description="Stable slug for the construct, e.g. ``responses``.")
    title: str = Field(description="Human-readable construct name.")
    coverage: Coverage
    weight: int = Field(
        description="How load-bearing the construct is; scales the score penalty a "
        "non-``present`` coverage incurs.",
    )
    count: int = Field(description="How many instances of the construct were considered.")
    examples: List[str] = Field(
        default_factory=list,
        description="Up to a few illustrative coordinates (pointers/keys), sorted.",
    )
    reason: str = Field(description="Human-readable explanation of the coverage tag.")


class FidelityReport(BaseModel):
    """The full fidelity preview for one canonical-model → OpenAPI conversion.

    Deterministic for a given ``(api, EmitResult)``: the checklist is in a fixed
    order, losses come pre-sorted from the :class:`~app.emitter.EmitResult`, and the
    score/grade/tier are pure functions of the two.
    """

    model_config = ConfigDict(extra="forbid")

    score: int = Field(description="Weighted 0-100 fidelity score (100 = lossless).")
    grade: str = Field(description="A-F letter grade from the house bands (MFI-4.2).")
    tier: FidelityTier = Field(description="Coarse high/medium/low fidelity signal.")
    items: List[ChecklistItem] = Field(
        description="The completeness checklist, one row per construct, fixed order.",
    )
    losses: List[Loss] = Field(
        default_factory=list,
        description="Projection losses carried through from the EmitResult, sorted.",
    )
    coverage_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of checklist rows per :class:`Coverage` tag.",
    )
    penalty: int = Field(
        description="Total penalty subtracted from 100 to reach ``score`` (transparency).",
    )


# Fraction of a checklist row's ``weight`` charged as a penalty, per coverage tag. A
# ``present`` or ``n/a`` row costs nothing (faithful, or nothing was representable to
# lose); an ``inferred``/``partial`` row costs half (emitted but not faithful); a
# ``missing`` row costs its full weight.
_COVERAGE_PENALTY_FACTOR: Dict[Coverage, float] = {
    Coverage.PRESENT: 0.0,
    Coverage.INFERRED: 0.5,
    Coverage.PARTIAL: 0.5,
    Coverage.MISSING: 1.0,
    Coverage.NA: 0.0,
}


class FidelityAnalyzer:
    """Read an emitter's :class:`~app.emitter.EmitResult` into a :class:`FidelityReport`.

    Stateless; a single shared instance can be reused. All the analysis lives in
    :meth:`analyze`, which builds a provenance index over the emitted document and
    walks a fixed checklist of OpenAPI constructs, classifying each from the emitted
    document plus its provenance and the projection's losses.
    """

    def analyze(self, api: CanonicalApi, result: EmitResult) -> FidelityReport:
        """Produce the fidelity report for ``api`` emitted as ``result``.

        Args:
            api: The source canonical model that was converted.
            result: The emitter's output for ``api`` (document + provenance + losses).

        Returns:
            A deterministic :class:`FidelityReport`.
        """
        ctx = _Context(api, result)
        items = [build(ctx) for build in _CHECKLIST]

        penalty = self._penalty(items, result.losses)
        score = max(0, min(100, round(100.0 - penalty)))
        grade = _grade_for_score(score)
        tier = _tier_for_score(score)

        coverage_counts: Dict[str, int] = {c.value: 0 for c in Coverage}
        for item in items:
            coverage_counts[item.coverage.value] += 1

        return FidelityReport(
            score=score,
            grade=grade,
            tier=tier,
            items=items,
            losses=result.losses,
            coverage_counts=coverage_counts,
            penalty=round(penalty),
        )

    @staticmethod
    def _penalty(items: List[ChecklistItem], losses: List[Loss]) -> float:
        """Sum the weighted checklist penalties and the per-loss penalties."""
        total = 0.0
        for item in items:
            total += item.weight * _COVERAGE_PENALTY_FACTOR[item.coverage]
        for loss in losses:
            total += LOSS_PENALTY.get(loss.kind, 0.0)
        return total


def analyze_fidelity(api: CanonicalApi, result: EmitResult) -> FidelityReport:
    """Convenience wrapper: analyze ``api``/``result`` with a fresh analyzer."""
    return FidelityAnalyzer().analyze(api, result)


# ===========================================================================
# Analysis context + provenance index
# ===========================================================================


class _Context:
    """Working state shared by the checklist classifiers for one analysis.

    Indexes the emitter's provenance records by JSON Pointer (exact and by prefix)
    so a classifier can ask "where did the value at this pointer come from?" or
    "what provenance do the values under this subtree carry?" cheaply, and exposes
    the emitted document + source model the classifiers read.
    """

    def __init__(self, api: CanonicalApi, result: EmitResult) -> None:
        self.api = api
        self.document = result.document
        self.paths: Dict[str, Dict] = result.document.get("paths", {}) or {}
        self._by_pointer: Dict[str, Provenance] = {
            record.pointer: record.provenance for record in result.provenance
        }

    def provenance_at(self, pointer: str) -> Optional[Provenance]:
        """Return the provenance recorded exactly at ``pointer``, or ``None``."""
        return self._by_pointer.get(pointer)

    def operation_pointers(self) -> List[Tuple[str, str, str, Dict]]:
        """Return every emitted operation as ``(path, method, op_pointer, op_obj)``.

        Sorted by ``(path, method)`` so any aggregation over operations is
        deterministic regardless of the emitted dict's insertion order.
        """
        result: List[Tuple[str, str, str, Dict]] = []
        for path, item in self.paths.items():
            if not isinstance(item, dict):
                continue
            for method, op_obj in item.items():
                if method.startswith("x-") or not isinstance(op_obj, dict):
                    continue
                op_ptr = ProvenanceTracker.child("/paths", path, method)
                result.append((path, method, op_ptr, op_obj))
        result.sort(key=lambda row: (row[0], row[1]))
        return result

    def operation_count(self) -> int:
        """Return the number of operations across all services in the source model."""
        return sum(len(service.operations) for service in self.api.services)


def _examples(values: List[str]) -> List[str]:
    """Return up to :data:`MAX_EXAMPLES` unique ``values``, sorted (deterministic)."""
    return sorted(set(values))[:MAX_EXAMPLES]


def _aggregate(verdicts: List[Coverage]) -> Coverage:
    """Fold per-instance coverage verdicts into one row-level coverage.

    ``present`` iff every instance is present; ``missing`` iff every instance is
    missing; otherwise ``partial`` when faithful and unfaithful instances are mixed,
    else ``inferred`` (all instances inferred, or a mix of inferred and missing).
    Callers guarantee ``verdicts`` is non-empty.
    """
    unique = set(verdicts)
    if unique == {Coverage.PRESENT}:
        return Coverage.PRESENT
    if unique == {Coverage.MISSING}:
        return Coverage.MISSING
    if Coverage.PRESENT in unique:
        return Coverage.PARTIAL
    return Coverage.INFERRED


# ===========================================================================
# Checklist classifiers
# ===========================================================================
#
# Each classifier takes the :class:`_Context` and returns a fully-formed
# :class:`ChecklistItem`. They are collected into ``_CHECKLIST`` in the fixed order
# the report renders them. Weights encode how load-bearing each construct is: the
# core request/response surface (paths, responses, components) is heaviest; document
# metadata is light; constructs the canonical model cannot carry at all are ``n/a``
# and never penalize.


def _info_title(ctx: _Context) -> ChecklistItem:
    prov = ctx.provenance_at("/info/title")
    if prov is Provenance.SOURCE:
        coverage, reason = Coverage.PRESENT, "title carried from the source"
    else:
        coverage, reason = (
            Coverage.INFERRED,
            "source declares no title; derived from the artifact identity name",
        )
    return ChecklistItem(
        key="info.title",
        title="API title",
        coverage=coverage,
        weight=3,
        count=1,
        examples=["/info/title"],
        reason=reason,
    )


def _info_version(ctx: _Context) -> ChecklistItem:
    prov = ctx.provenance_at("/info/version")
    if prov is Provenance.SOURCE:
        coverage, reason = Coverage.PRESENT, "version carried from the source"
    else:
        coverage, reason = (
            Coverage.MISSING,
            "source declares no API version; a placeholder was emitted",
        )
    return ChecklistItem(
        key="info.version",
        title="API version",
        coverage=coverage,
        weight=3,
        count=1,
        examples=["/info/version"],
        reason=reason,
    )


def _info_description(ctx: _Context) -> ChecklistItem:
    present = ctx.provenance_at("/info/description") is Provenance.SOURCE
    return ChecklistItem(
        key="info.description",
        title="API description",
        coverage=Coverage.PRESENT if present else Coverage.MISSING,
        weight=2,
        count=1 if present else 0,
        examples=["/info/description"] if present else [],
        reason=(
            "description carried from the source"
            if present
            else "source carries no top-level API description"
        ),
    )


def _info_contact(ctx: _Context) -> ChecklistItem:
    return ChecklistItem(
        key="info.contact",
        title="Contact info",
        coverage=Coverage.NA,
        weight=1,
        count=0,
        examples=[],
        reason="the canonical model does not retain contact information",
    )


def _info_license(ctx: _Context) -> ChecklistItem:
    return ChecklistItem(
        key="info.license",
        title="License",
        coverage=Coverage.NA,
        weight=1,
        count=0,
        examples=[],
        reason="the canonical model does not retain license information",
    )


def _servers(ctx: _Context) -> ChecklistItem:
    servers = ctx.document.get("servers", []) or []
    present = len(servers) > 0
    return ChecklistItem(
        key="servers",
        title="Servers",
        coverage=Coverage.PRESENT if present else Coverage.MISSING,
        weight=4,
        count=len(servers),
        examples=_examples([s.get("url", "") for s in servers if isinstance(s, dict)]),
        reason=(
            "server URL(s) carried from the source"
            if present
            else "source declares no servers; the base URL is unknown"
        ),
    )


def _paths(ctx: _Context) -> ChecklistItem:
    operations = ctx.operation_pointers()
    if not operations:
        # Nothing reached the paths object. Distinguish a schema-only source (never
        # had operations) from one whose operations were all dropped by projection.
        if ctx.operation_count() == 0:
            reason = "source defines types only; there are no operations to route"
        else:
            reason = "no source operation could be projected onto an HTTP path"
        return ChecklistItem(
            key="paths",
            title="Paths & methods",
            coverage=Coverage.NA,
            weight=15,
            count=0,
            examples=[],
            reason=reason,
        )

    verdicts: List[Coverage] = []
    inferred_paths: List[str] = []
    source_paths: List[str] = []
    for path, method, op_ptr, _ in operations:
        # The emitter records an INFERRED note at the operation pointer itself only
        # when it had to synthesize the (method, path) binding.
        if ctx.provenance_at(op_ptr) is Provenance.INFERRED:
            verdicts.append(Coverage.INFERRED)
            inferred_paths.append(f"{method.upper()} {path}")
        else:
            verdicts.append(Coverage.PRESENT)
            source_paths.append(f"{method.upper()} {path}")
    coverage = _aggregate(verdicts)
    if coverage is Coverage.PRESENT:
        reason = "every operation kept its source HTTP method and path"
    elif coverage is Coverage.INFERRED:
        reason = "no operation carried an HTTP binding; every route was synthesized"
    else:
        reason = "some routes came from the source, others were synthesized"
    return ChecklistItem(
        key="paths",
        title="Paths & methods",
        coverage=coverage,
        weight=15,
        count=len(operations),
        examples=_examples(inferred_paths or source_paths),
        reason=reason,
    )


def _operation_metadata(ctx: _Context) -> ChecklistItem:
    operations = ctx.operation_pointers()
    if not operations:
        return _na_operation_item(
            "operation.metadata", "Operation id / summary", weight=3
        )
    verdicts: List[Coverage] = []
    examples: List[str] = []
    for path, method, op_ptr, _ in operations:
        prov = ctx.provenance_at(f"{op_ptr}/operationId")
        if prov is Provenance.SOURCE:
            verdicts.append(Coverage.PRESENT)
        else:
            verdicts.append(Coverage.INFERRED)
            examples.append(f"{method.upper()} {path}")
    coverage = _aggregate(verdicts)
    if coverage is Coverage.PRESENT:
        reason = "operationId carried from the source for every operation"
    elif coverage is Coverage.INFERRED:
        reason = "no operationId in the source; each was synthesized from method+path"
    else:
        reason = "some operationIds came from the source, others were synthesized"
    return ChecklistItem(
        key="operation.metadata",
        title="Operation id / summary",
        coverage=coverage,
        weight=3,
        count=len(operations),
        examples=_examples(examples),
        reason=reason,
    )


def _parameters(ctx: _Context) -> ChecklistItem:
    count = 0
    examples: List[str] = []
    for path, method, _, op_obj in ctx.operation_pointers():
        params = op_obj.get("parameters", []) or []
        count += len(params)
        for param in params:
            if isinstance(param, dict):
                examples.append(f"{method.upper()} {path} · {param.get('name', '?')}")
    if count == 0:
        return ChecklistItem(
            key="parameters",
            title="Parameters",
            coverage=Coverage.NA,
            weight=6,
            count=0,
            examples=[],
            reason="no operation declares parameters",
        )
    # Emitted parameters always carry their source ``in``/``required``/``schema``.
    return ChecklistItem(
        key="parameters",
        title="Parameters",
        coverage=Coverage.PRESENT,
        weight=6,
        count=count,
        examples=_examples(examples),
        reason="parameters carried from the source with location, requiredness and schema",
    )


def _request_body(ctx: _Context) -> ChecklistItem:
    verdicts: List[Coverage] = []
    examples: List[str] = []
    for path, method, op_ptr, op_obj in ctx.operation_pointers():
        if "requestBody" not in op_obj:
            continue
        examples.append(f"{method.upper()} {path}")
        # requestBody.content media type is SOURCE when the message declared content
        # types, INFERRED when the default media type had to be assumed.
        if ctx.provenance_at(f"{op_ptr}/requestBody/content") is Provenance.SOURCE:
            verdicts.append(Coverage.PRESENT)
        else:
            verdicts.append(Coverage.INFERRED)
    if not verdicts:
        return ChecklistItem(
            key="requestBody",
            title="Request body",
            coverage=Coverage.NA,
            weight=8,
            count=0,
            examples=[],
            reason="no operation carries a request body",
        )
    coverage = _aggregate(verdicts)
    if coverage is Coverage.PRESENT:
        reason = "request bodies carried with their source media type and schema"
    elif coverage is Coverage.INFERRED:
        reason = "request payloads kept, but no media type was declared (defaulted)"
    else:
        reason = "some request bodies kept their media type, others were defaulted"
    return ChecklistItem(
        key="requestBody",
        title="Request body",
        coverage=coverage,
        weight=8,
        count=len(verdicts),
        examples=_examples(examples),
        reason=reason,
    )


def _responses(ctx: _Context) -> ChecklistItem:
    operations = ctx.operation_pointers()
    if not operations:
        return _na_operation_item("responses", "Responses", weight=12)
    verdicts: List[Coverage] = []
    examples: List[str] = []
    for path, method, op_ptr, op_obj in operations:
        verdict = _response_verdict(ctx, op_ptr, op_obj)
        verdicts.append(verdict)
        if verdict is not Coverage.PRESENT:
            examples.append(f"{method.upper()} {path}")
    coverage = _aggregate(verdicts)
    if coverage is Coverage.PRESENT:
        reason = "responses carried with their source status codes, media types and schema"
    elif coverage is Coverage.MISSING:
        reason = "no operation declares responses; a placeholder response was emitted"
    elif coverage is Coverage.INFERRED:
        reason = "status codes and/or media types were inferred, not declared by the source"
    else:
        reason = "some responses were faithful; others had status/media inferred or missing"
    return ChecklistItem(
        key="responses",
        title="Responses",
        coverage=coverage,
        weight=12,
        count=len(operations),
        examples=_examples(examples),
        reason=reason,
    )


def _response_verdict(ctx: _Context, op_ptr: str, op_obj: Dict) -> Coverage:
    """Classify one operation's responses from their status/content provenance.

    ``missing`` when the only response is the emitter's placeholder ``default`` (the
    operation declared none); ``inferred`` when a status code or a media type had to
    be inferred; ``present`` when every status and media type came from the source.
    """
    responses = op_obj.get("responses", {}) or {}
    inferred = False
    for status in responses:
        status_ptr = ProvenanceTracker.child(op_ptr, "responses", status)
        status_prov = ctx.provenance_at(status_ptr)
        if status_prov is Provenance.DEFAULT:
            # The whole responses object is the "no response messages" placeholder.
            return Coverage.MISSING
        if status_prov is Provenance.INFERRED:
            inferred = True
        if ctx.provenance_at(f"{status_ptr}/content") is Provenance.INFERRED:
            inferred = True
    # Defensive: an empty responses object should not occur, but treat it as missing.
    if not responses:
        return Coverage.MISSING
    return Coverage.INFERRED if inferred else Coverage.PRESENT


def _components(ctx: _Context) -> ChecklistItem:
    schemas = (ctx.document.get("components", {}) or {}).get("schemas", {}) or {}
    present = len(schemas) > 0
    return ChecklistItem(
        key="components.schemas",
        title="Component schemas",
        coverage=Coverage.PRESENT if present else Coverage.NA,
        weight=10,
        count=len(schemas),
        examples=_examples(list(schemas.keys())),
        reason=(
            "named types carried from the source into components.schemas"
            if present
            else "source defines no named component schemas"
        ),
    )


def _security(ctx: _Context) -> ChecklistItem:
    return ChecklistItem(
        key="security",
        title="Security schemes",
        coverage=Coverage.NA,
        weight=4,
        count=0,
        examples=[],
        reason="the canonical model does not retain security schemes or requirements",
    )


def _tags(ctx: _Context) -> ChecklistItem:
    count = 0
    examples: List[str] = []
    for path, method, _, op_obj in ctx.operation_pointers():
        if op_obj.get("tags"):
            count += 1
            examples.append(f"{method.upper()} {path}")
    return ChecklistItem(
        key="tags",
        title="Tags",
        coverage=Coverage.PRESENT if count else Coverage.NA,
        weight=2,
        count=count,
        examples=_examples(examples),
        reason=(
            "operation tags carried from the source"
            if count
            else "no operation declares tags"
        ),
    )


def _examples_item(ctx: _Context) -> ChecklistItem:
    return ChecklistItem(
        key="examples",
        title="Examples",
        coverage=Coverage.NA,
        weight=2,
        count=0,
        examples=[],
        reason="the canonical model does not retain request/response examples",
    )


def _external_docs(ctx: _Context) -> ChecklistItem:
    return ChecklistItem(
        key="externalDocs",
        title="External docs",
        coverage=Coverage.NA,
        weight=1,
        count=0,
        examples=[],
        reason="the canonical model does not retain external-documentation links",
    )


def _deprecated(ctx: _Context) -> ChecklistItem:
    count = 0
    examples: List[str] = []
    for path, method, _, op_obj in ctx.operation_pointers():
        if op_obj.get("deprecated"):
            count += 1
            examples.append(f"{method.upper()} {path}")
    schemas = (ctx.document.get("components", {}) or {}).get("schemas", {}) or {}
    for name, schema in schemas.items():
        if isinstance(schema, dict) and schema.get("deprecated"):
            count += 1
            examples.append(name)
    return ChecklistItem(
        key="deprecated",
        title="Deprecation flags",
        coverage=Coverage.PRESENT if count else Coverage.NA,
        weight=1,
        count=count,
        examples=_examples(examples),
        reason=(
            "deprecation flags carried from the source"
            if count
            else "no construct is marked deprecated"
        ),
    )


def _na_operation_item(key: str, title: str, weight: int) -> ChecklistItem:
    """Build the ``n/a`` row for an operation-scoped construct when there are no ops."""
    return ChecklistItem(
        key=key,
        title=title,
        coverage=Coverage.NA,
        weight=weight,
        count=0,
        examples=[],
        reason="source defines no operations",
    )


def _source_openapi_version(ctx: _Context) -> ChecklistItem:
    """Note when a 3.2 source is emitted as the 3.1 target format."""
    if ctx.api.format != "openapi-3.2":
        return ChecklistItem(
            key="source.openapi-version",
            title="Source OpenAPI version",
            coverage=Coverage.NA,
            weight=0,
            count=0,
            examples=[],
            reason="source is not OpenAPI 3.2",
        )
    return ChecklistItem(
        key="source.openapi-version",
        title="Source OpenAPI version",
        coverage=Coverage.PARTIAL,
        weight=5,
        count=1,
        examples=["openapi-3.2"],
        reason=(
            "OpenAPI 3.2 source converted to OpenAPI 3.1 target; QUERY and "
            "additionalOperations methods are stashed on x-apiome-* extensions "
            "rather than native 3.1 path-item methods"
        ),
    )


#: The completeness checklist, in the fixed order the report renders it. Mirrors the
#: MFI-22.3 checklist: info (title/version/description/contact/license), servers,
#: paths+methods, operation metadata, parameters, requestBody, responses,
#: components.schemas, security, tags, examples, externalDocs, deprecated.
_CHECKLIST: Tuple[Callable[["_Context"], ChecklistItem], ...] = (
    _info_title,
    _info_version,
    _info_description,
    _info_contact,
    _info_license,
    _source_openapi_version,
    _servers,
    _paths,
    _operation_metadata,
    _parameters,
    _request_body,
    _responses,
    _components,
    _security,
    _tags,
    _examples_item,
    _external_docs,
    _deprecated,
)


# ===========================================================================
# Score → grade / tier
# ===========================================================================


def _grade_for_score(score: int) -> str:
    """Map a 0-100 ``score`` to its A-F grade via the house bands (MFI-4.2)."""
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _tier_for_score(score: int) -> FidelityTier:
    """Map a 0-100 ``score`` to a coarse high/medium/low fidelity tier."""
    if score >= TIER_HIGH_MIN:
        return FidelityTier.HIGH
    if score >= TIER_MEDIUM_MIN:
        return FidelityTier.MEDIUM
    return FidelityTier.LOW
