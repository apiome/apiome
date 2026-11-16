"""Grade a revision pair under a compatibility policy (XPC-4.5, #5749).

XPC-4.1–4.4 taught four classifiers to grade by **mode** (Avro, JSON Schema, AsyncAPI) or by
**buf breaking category** (Protobuf). This module is what the classified diff, the compatibility
check and the publish guardrail call to use them:

* :func:`classify_under` builds the right classifier for the target's format, configured with the
  policy's mode or category, and says whether that setting was **applied**. A format with no
  mode-aware classifier (RAML, API Blueprint, WSDL, OpenAPI today) is graded by its own ruleset —
  or the format-agnostic ``builtin`` one — and reported ``modeApplied: false``, so no response
  implies mode semantics it did not evaluate.
* ``NONE`` is Confluent's "no compatibility checking". Where the mode is applied, changes are still
  listed with their rule ids and graded as ``BACKWARD`` would, but nothing is breaking: a break is
  reported dangerous, its rationale led by ``[NONE]``.
* :func:`graded_changes` flattens a result — per-change grades and unattributed tool findings — into
  one list with JSON-Pointer-like locations, the shape both endpoints render.
* :func:`canonical_model_for_revision` and :func:`parse_candidate` rebuild a stored revision's, or an
  uploaded candidate's, canonical model from source.
* :func:`transitive_baselines` lists the earlier revisions a transitive check compares against.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Hashable, List, Optional, Sequence, Tuple, TypeVar

from .breaking_change import (
    BreakingChangeClassifier,
    ClassificationResult,
    Severity,
    _assemble_result,
    classify,
    get_breaking_change_classifier,
)
from .canonical_model import CanonicalApi
from .compatibility_policy import MODE_BACKWARD, MODE_NONE, CompatibilityPolicy
from .compatibility_report_models import ComparedRevisionOut, EvaluatedUnderOut
from .diff import diff

logger = logging.getLogger(__name__)

__all__ = [
    "Baseline",
    "CTG_RULESET",
    "NATIVE_COMPAT_RULESET",
    "MAX_TRANSITIVE_REVISIONS",
    "OPENAPI_FORMAT",
    "FormatEvaluation",
    "GradedChange",
    "canonical_model_for_revision",
    "classify_under",
    "ctg_changes",
    "evaluated_under",
    "evaluated_under_markdown",
    "graded_changes",
    "is_mode_graded_format",
    "parse_candidate",
    "revision_format",
    "merge_transitive",
    "transitive_baselines",
]

#: Ruleset id reported for the OpenAPI change taxonomy (CTG-1.1), which has no mode semantics.
CTG_RULESET = "ctg"

#: Ruleset id reported for the native OpenAPI compatibility engine behind ``…/compatibility``.
NATIVE_COMPAT_RULESET = "openapi-compatibility"

#: The format key OpenAPI revisions report (design projects record no ``source_format``).
OPENAPI_FORMAT = "openapi"

#: Cap on the earlier revisions one transitive check compares against.
MAX_TRANSITIVE_REVISIONS = 50

#: Prefix a ``NONE`` grade's rationale carries.
_NONE_LEAD = "[NONE] compatibility checking is off; graded as BACKWARD would:"


@dataclass(frozen=True)
class FormatEvaluation:
    """How one comparison was graded.

    Attributes:
        format: The target's format key.
        ruleset: The classifier id that graded it (``avro-compatibility``, ``builtin``, …).
        mode_applied: Whether a mode-aware classifier graded by the policy's mode.
        category_applied: Whether the Protobuf classifier graded at the policy's category.
    """

    format: str
    ruleset: str
    mode_applied: bool = False
    category_applied: bool = False


@dataclass(frozen=True)
class GradedChange:
    """One graded change, flattened for a response.

    Attributes:
        rule_id: The rule that produced the grade.
        severity: ``safe`` / ``dangerous`` / ``breaking``.
        pointer: Where it is: ``/<category>/<key>`` for a canonical change, ``/unattributed/<shape>``
            for a tool finding no change carries.
        change_kind: ``added`` / ``removed`` / ``modified`` (``unattributed`` for a tool finding).
        rationale: The one-line explanation.
    """

    rule_id: str
    severity: str
    pointer: str
    change_kind: str
    rationale: str


def is_mode_graded_format(format_key: Optional[str]) -> bool:
    """Whether ``format_key`` has a classifier that grades by mode or by Protobuf category.

    Args:
        format_key: A canonical format key (``avro``, ``protobuf``, ``asyncapi-3``, …) or ``None``.

    Returns:
        ``True`` for the XPC-4.1–4.4 formats; ``False`` for everything else, including OpenAPI.
    """
    cls = get_breaking_change_classifier(str(format_key or ""))
    return cls is not None and (_is_mode_aware(cls) or _is_category_aware(cls))


def _is_mode_aware(cls: type[BreakingChangeClassifier]) -> bool:
    """A mode-aware classifier declares ``default_mode`` and takes ``mode`` (XPC-4.1/4.2/4.4)."""
    return isinstance(getattr(cls, "default_mode", None), str)


def _is_category_aware(cls: type[BreakingChangeClassifier]) -> bool:
    """The Protobuf classifier takes a buf breaking ``category`` (XPC-4.3)."""
    from .proto_breaking import ProtobufBreakingChangeClassifier

    return issubclass(cls, ProtobufBreakingChangeClassifier)


def _without_breaks(result: ClassificationResult, classifier: BreakingChangeClassifier, target: CanonicalApi) -> ClassificationResult:
    """Re-grade a ``BACKWARD`` result for ``NONE``: every break becomes dangerous, led by ``[NONE]``."""

    def soften(item: Any) -> Any:
        if item.severity is not Severity.BREAKING:
            return item
        return item.model_copy(
            update={"severity": Severity.DANGEROUS, "rationale": f"{_NONE_LEAD} breaking — {item.rationale}"}
        )

    return _assemble_result(
        classifier,
        target,
        [soften(c) for c in result.classifications],
        [soften(f) for f in result.unattributed],
    )


def classify_under(
    base: CanonicalApi, target: CanonicalApi, policy: CompatibilityPolicy
) -> Tuple[ClassificationResult, FormatEvaluation]:
    """Diff two canonical models and grade the diff under ``policy``.

    Args:
        base: The earlier ("from") model.
        target: The later ("to") model; its format picks the classifier.
        policy: The mode and Protobuf category to grade under (``transitive`` is the caller's
            concern: this grades one pair).

    Returns:
        ``(result, evaluation)``: the classification and how it was graded.
    """
    model_diff = diff(base, target)
    cls = get_breaking_change_classifier(target.format)
    if cls is None:
        result = classify(model_diff, base, target)
        return result, FormatEvaluation(format=target.format, ruleset=result.classifier)
    if _is_mode_aware(cls):
        grading_mode = MODE_BACKWARD if policy.mode == MODE_NONE else policy.mode
        classifier = cls(mode=grading_mode)  # type: ignore[call-arg]
        result = classifier.classify(model_diff, base, target)
        if policy.mode == MODE_NONE:
            result = _without_breaks(result, classifier, target)
        return result, FormatEvaluation(format=target.format, ruleset=result.classifier, mode_applied=True)
    if _is_category_aware(cls):
        classifier = cls(category=policy.category)  # type: ignore[call-arg]
        result = classifier.classify(model_diff, base, target)
        return result, FormatEvaluation(format=target.format, ruleset=result.classifier, category_applied=True)
    result = cls().classify(model_diff, base, target)
    return result, FormatEvaluation(format=target.format, ruleset=result.classifier)


def _escape_pointer(token: str) -> str:
    """Escape one JSON Pointer reference token (RFC 6901)."""
    return token.replace("~", "~0").replace("/", "~1")


def graded_changes(result: ClassificationResult) -> List[GradedChange]:
    """Flatten a classification into one list: per-change grades, then unattributed findings.

    Args:
        result: A :class:`ClassificationResult`.

    Returns:
        The graded changes in the diff's stable order, unattributed tool findings last.
    """
    changes = [
        GradedChange(
            rule_id=c.rule_id,
            severity=c.severity.value,
            pointer=f"/{c.category.value}/{_escape_pointer(c.key)}",
            change_kind=c.kind.value,
            rationale=c.rationale,
        )
        for c in result.classifications
    ]
    changes += [
        GradedChange(
            rule_id=f.rule_id,
            severity=f.severity.value,
            pointer=f"/unattributed/{_escape_pointer(f.shape or f.rule_id)}",
            change_kind="unattributed",
            rationale=f.rationale,
        )
        for f in result.unattributed
    ]
    return changes


#: Canonical three-tier grade → the CTG severity the classified diff, the changelog and CI gates read.
CTG_SEVERITY_OF_GRADE = {"breaking": "breaking", "dangerous": "non-breaking", "safe": "non-breaking"}


def ctg_changes(result: ClassificationResult) -> List[Tuple[Any, str]]:
    """Map a canonical classification onto CTG changes, keeping each one's three-tier grade.

    A breaking grade stays ``breaking``; dangerous and safe become ``non-breaking`` (the CI gate's
    ``warn`` level), and the rationale travels on the change so the changelog can explain it.

    Args:
        result: A :class:`ClassificationResult`.

    Returns:
        ``(ClassifiedChange, grade)`` per graded change, in :func:`graded_changes` order.
    """
    from .change_taxonomy import ClassifiedChange

    return [
        (
            ClassifiedChange(
                rule_id=c.rule_id,
                severity=CTG_SEVERITY_OF_GRADE.get(c.severity, "breaking"),  # type: ignore[arg-type]
                pointer=c.pointer,
                change_kind=c.change_kind,
                rationale=c.rationale,
            ),
            c.severity,
        )
        for c in graded_changes(result)
    ]


def _conversion_item(row: Dict[str, Any]) -> Dict[str, Any]:
    """The catalog-item shape :func:`app.catalog_conversion.build_conversion_source` reads."""
    return {
        "id": row.get("project_id"),
        "source_format": row.get("source_format"),
        "protocol": row.get("protocol"),
        "format_metadata": row.get("format_metadata"),
        "metadata": row.get("metadata"),
    }


def canonical_model_for_revision(db: Any, tenant_id: str, revision_id: str) -> Optional[CanonicalApi]:
    """Rebuild a revision's canonical model from its captured source, when it is mode-graded.

    Args:
        db: Database handle exposing ``get_revision_source_row``.
        tenant_id: The owning tenant.
        revision_id: The revision (``versions.id``).

    Returns:
        The canonical model when the revision's ``source_format`` has a mode- or category-aware
        classifier and its source can be rebuilt; ``None`` otherwise (the caller keeps the OpenAPI
        path).
    """
    row = db.get_revision_source_row(str(revision_id), tenant_id)
    if not row or not is_mode_graded_format(row.get("source_format")):
        return None
    from .catalog_conversion import build_conversion_source

    try:
        return build_conversion_source(_conversion_item(row)).api
    except Exception:  # noqa: BLE001 - an unrebuildable source falls back to the OpenAPI path
        logger.info("compatibility: revision %s has no rebuildable source", revision_id, exc_info=True)
        return None


def revision_format(db: Any, tenant_id: str, revision_id: str) -> str:
    """Return a revision's recorded source format, or :data:`OPENAPI_FORMAT` when it has none.

    Args:
        db: Database handle exposing ``get_revision_source_row``.
        tenant_id: The owning tenant.
        revision_id: The revision (``versions.id``).

    Returns:
        The ``source_format`` (``avro``, ``raml``, …), or ``openapi`` for a design project.
    """
    row = db.get_revision_source_row(str(revision_id), tenant_id) or {}
    return str(row.get("source_format") or "").strip() or OPENAPI_FORMAT


def parse_candidate(source_format: str, text: str, *, source_label: str = "inline") -> CanonicalApi:
    """Parse an uploaded candidate document with the importer for ``source_format``.

    Args:
        source_format: The base revision's format; the candidate is read as the same format.
        text: The candidate's raw text.
        source_label: The file name the importer sees (some importers read its extension).

    Returns:
        The candidate's canonical model.

    Raises:
        ValueError: When no importer reads the format or the text does not parse.
    """
    from .catalog_conversion import resolve_conversion_adapter
    from .import_source import ImportSourceError

    try:
        adapter = resolve_conversion_adapter(source_format, text)
        return adapter.normalize(adapter.parse(text, source_label=source_label))
    except ImportSourceError as exc:
        raise ValueError(f"The candidate {source_format} document could not be read: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - ConversionError and friends become a 400
        raise ValueError(str(exc)) from exc


@dataclass(frozen=True)
class Baseline:
    """One stored revision the head is compared against.

    Attributes:
        revision_id: The revision (``versions.id``).
        version_label: Its version label.
        role: ``base`` for the requested base, ``prior`` for an earlier one a transitive check adds.
    """

    revision_id: str
    version_label: str
    role: str = "base"


def transitive_baselines(
    db: Any,
    *,
    tenant_id: str,
    project_id: str,
    base_revision_id: str,
    base_label: str,
    transitive: bool,
) -> Tuple[List[Baseline], bool]:
    """List the revisions a check compares the head against: the base, then — when transitive —
    every earlier revision in its lineage.

    Args:
        db: Database handle exposing ``list_prior_revisions_for_transitive_check``.
        tenant_id: The owning tenant.
        project_id: The base revision's project.
        base_revision_id: The base revision.
        base_label: The base revision's version label.
        transitive: Whether to add the earlier revisions.

    Returns:
        ``(baselines, truncated)``: the base first, then earlier revisions newest first (at most
        :data:`MAX_TRANSITIVE_REVISIONS`), and whether more earlier revisions exist than were listed.
    """
    baselines = [Baseline(str(base_revision_id), str(base_label), "base")]
    if not transitive:
        return baselines, False
    rows = db.list_prior_revisions_for_transitive_check(
        project_id, tenant_id, base_revision_id, limit=MAX_TRANSITIVE_REVISIONS + 1
    )
    rows = [r for r in rows or [] if str(r.get("id")) != str(base_revision_id)]
    baselines += [
        Baseline(str(r["id"]), str(r.get("version_id") or ""), "prior")
        for r in rows[:MAX_TRANSITIVE_REVISIONS]
    ]
    return baselines, len(rows) > MAX_TRANSITIVE_REVISIONS


T = TypeVar("T")


def merge_transitive(
    pairs: Sequence[Tuple[Baseline, Sequence[T]]],
    *,
    key: Callable[[T], Hashable],
    is_breaking: Callable[[T], bool],
) -> List[Tuple[Baseline, T]]:
    """Merge each baseline's findings into one list, the way a ``*_TRANSITIVE`` mode reads them.

    Every finding against the base is kept. From an earlier revision only **breaking** findings are
    added — the transitive check exists to catch a change compatible with the base but not with an
    older revision — and only when the base (or a newer earlier revision) did not already report the
    same finding, so one break is reported once, against the newest revision it breaks.

    Args:
        pairs: ``(baseline, findings)`` per baseline, base first.
        key: The identity of a finding (rule id and location).
        is_breaking: Whether a finding is breaking.

    Returns:
        ``(baseline, finding)`` pairs in baseline order.
    """
    seen: set = set()
    out: List[Tuple[Baseline, T]] = []
    for baseline, findings in pairs:
        for finding in findings:
            identity = key(finding)
            if baseline.role != "base" and (identity in seen or not is_breaking(finding)):
                continue
            seen.add(identity)
            out.append((baseline, finding))
    return out


def evaluated_under(
    policy: CompatibilityPolicy,
    evaluations: Sequence[FormatEvaluation],
    *,
    requested: Dict[str, bool],
    compared: Sequence[Baseline] = (),
    truncated: bool = False,
    default_ruleset: str = CTG_RULESET,
) -> EvaluatedUnderOut:
    """Build the ``evaluatedUnder`` block for a response.

    Args:
        policy: The effective policy the comparison ran under.
        evaluations: How each compared pair was graded (one per pair; duplicates collapse).
        requested: ``{"mode": bool, "transitive": bool, "category": bool}`` — whether the request
            named each setting (``False`` means it came from the project's policy).
        compared: The stored revisions compared, base first.
        truncated: Whether a transitive check stopped at its cap.
        default_ruleset: The ruleset named when no pair was graded by a canonical classifier.

    Returns:
        The :class:`EvaluatedUnderOut`.
    """
    formats = list(dict.fromkeys(e.format for e in evaluations))
    rulesets = list(dict.fromkeys(e.ruleset for e in evaluations))
    category_applied = any(e.category_applied for e in evaluations)
    return EvaluatedUnderOut(
        mode=policy.mode,
        transitive=policy.transitive,
        category=policy.category if category_applied else None,
        formats=formats,
        mode_applied=any(e.mode_applied for e in evaluations),
        category_applied=category_applied,
        ruleset=", ".join(rulesets) if rulesets else default_ruleset,
        source={
            key: ("request" if requested.get(key) else "policy")
            for key in ("mode", "transitive", "category")
        },
        compared_revisions=[
            ComparedRevisionOut(
                revision_id=b.revision_id, version_label=b.version_label, role=b.role  # type: ignore[arg-type]
            )
            for b in compared
        ],
        compared_revisions_truncated=truncated,
    )


def evaluated_under_markdown(evaluated: EvaluatedUnderOut) -> Optional[str]:
    """One Markdown line for a changelog saying what it was graded under, when that is not plain.

    Returns ``None`` for an untouched OpenAPI comparison (no mode, no category, not transitive), so
    the changelog a CI gate posts stays exactly what it was before XPC-4.5.

    Args:
        evaluated: The ``evaluatedUnder`` block.

    Returns:
        For example ``_Graded under `FULL_TRANSITIVE` by avro-compatibility, against 2.0.0, 1.0.0._``.
    """
    if not (evaluated.mode_applied or evaluated.category_applied or evaluated.transitive):
        return None
    parts: List[str] = []
    if evaluated.mode_applied:
        mode = CompatibilityPolicy(mode=evaluated.mode, transitive=evaluated.transitive).mode_name
        parts.append(f"`{mode}`")
    if evaluated.category_applied and evaluated.category:
        parts.append(f"Protobuf category `{evaluated.category}`")
    if not parts:
        parts.append("every earlier version")
    line = f"_Graded under {' and '.join(parts)} by {evaluated.ruleset}"
    labels = [r.version_label for r in evaluated.compared_revisions]
    if len(labels) > 1:
        line += f", against {', '.join(labels)}"
    return line + "._"
