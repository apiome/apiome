"""The first fixable Arazzo lint rules — GVM-4.5 (#5880).

Three rules over an Arazzo 1.x document, each carrying a deterministic fix through the
:mod:`app.lint_fix` SPI, exactly as the OpenAPI rules of :mod:`app.openapi_fix_rules` do:

=========================================  ==========  ===========================================
Rule                                       Fix class   What the fix does
=========================================  ==========  ===========================================
``arazzo.step-id-suffix``                  rename      suffixes a repeated ``stepId`` (``-2``, ``-3``)
``arazzo.success-criteria-scaffold``       fill-in     scaffolds ``successCriteria`` from the 2xx code (opt-in)
``arazzo.version-marker-bump``             structural  bumps ``arazzo: 1.0.x`` to ``1.1.0`` for 1.1-only features
=========================================  ==========  ===========================================

**These rules run on demand only**, like the fixable OpenAPI rules: they are catalogued
(``GET /v1/lint/rules``) but never part of :class:`app.arazzo_lint.ArazzoRulePack`, so no stored
lint report, score or fingerprint changes because they exist. They read the *raw* document and
report JSON-Pointer-addressable paths (``workflows.0.steps.1.stepId``), which is what the fix
operations are written against. The detection rules of the default lint
(``arazzo.step-id-duplicate``, ``arazzo.missing-success-criteria``,
``arazzo.async-source-before-1-1``) keep their own canonical-model paths and are unchanged.

Fixes invent nothing: a rename derives the new id from the old, the scaffold is derived from a
2xx response the step's *embedded* source description declares (no embedded document, no
scaffold), and the marker bump names the version that defines the feature already in use.
Checks and fixes are pure and never mutate the document.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional, Set, Tuple

from .arazzo_spec import (
    ARAZZO_VERSION_1_1,
    SOURCE_TYPE_ASYNCAPI,
    ArazzoVersionError,
    is_arazzo_marker,
    parse_arazzo_version,
    resolve_step_target,
    source_description_names,
)
from .canonical_model import CanonicalApi
from .lint_engine import LintRule
from .lint_fix import FixOptions, PatchOp, path_from_pointer, pointer_for_path
from .openapi_document_walk import HTTP_METHODS, join_pointer
from .schema_lint import LintFinding

__all__ = [
    "ARAZZO_FIX_PACK",
    "SCAFFOLD_CONDITION",
    "arazzo_fix_rule",
    "arazzo_fix_rules",
    "is_arazzo_document",
    "lint_arazzo_fixable",
    "plan_arazzo_fix",
    "response_status_codes",
]

#: Pack label the catalogue reports for these rules.
ARAZZO_FIX_PACK = "arazzo"

#: The scaffold condition of the 200 case; another 2xx code renders the same shape.
SCAFFOLD_CONDITION = "$statusCode == {code}"

_SUCCESS_CODE = re.compile(r"^2\d\d$")

DocumentCheck = Callable[[Mapping[str, Any]], Iterable[Tuple[str, str]]]


def is_arazzo_document(document: Any) -> bool:
    """Whether ``document`` is a parsed Arazzo document (a mapping with an ``arazzo`` marker).

    Args:
        document: Any parsed document.

    Returns:
        ``True`` when it carries a non-blank ``arazzo`` string.
    """
    return isinstance(document, Mapping) and is_arazzo_marker(document.get("arazzo"))


# ===========================================================================
# Document traversal
# ===========================================================================


def _steps(document: Mapping[str, Any]) -> Iterator[Tuple[int, int, Dict[str, Any]]]:
    """Yield ``(workflow index, step index, step)`` for every well-formed step."""
    workflows = document.get("workflows")
    if not isinstance(workflows, list):
        return
    for wi, workflow in enumerate(workflows):
        steps = workflow.get("steps") if isinstance(workflow, dict) else None
        if not isinstance(steps, list):
            continue
        for si, step in enumerate(steps):
            if isinstance(step, dict):
                yield wi, si, step


def _step_pointer(wi: int, si: int, *tail: str) -> str:
    """The JSON Pointer of a step (or a key of it)."""
    return join_pointer("", "workflows", str(wi), "steps", str(si), *tail)


# ===========================================================================
# arazzo.step-id-suffix
# ===========================================================================


def _workflow_step_ids(document: Mapping[str, Any], wi: int) -> List[Optional[str]]:
    """The ``stepId`` of each step of workflow ``wi`` (``None`` where absent or not a string)."""
    steps = document["workflows"][wi].get("steps")
    return [
        step.get("stepId") if isinstance(step, dict) and isinstance(step.get("stepId"), str) else None
        for step in steps
    ]


def _check_duplicate_step_id(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """Flag every repeat of a ``stepId`` after its first declaration in the same workflow."""
    seen: Dict[int, Set[str]] = {}
    for wi, si, step in _steps(document):
        step_id = step.get("stepId")
        if not isinstance(step_id, str) or not step_id:
            continue
        if step_id in seen.setdefault(wi, set()):
            yield (
                _step_pointer(wi, si, "stepId"),
                f"stepId {step_id!r} is declared more than once in this workflow.",
            )
        seen[wi].add(step_id)


def _fix_duplicate_step_id(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Replace a repeated ``stepId`` with ``<id>-<n>``, the first ``n >= 2`` no step of the workflow uses.

    Only the repeat is renamed: ``$steps.<id>`` and ``goto`` references already resolve to the
    first declaration, so they keep meaning what they meant. Ids the other findings of the same
    workflow will take are reserved too, so two repeats never collide on one suffix.
    """
    pointer = pointer_for_path(document, finding.path)
    tokens = pointer.split("/")  # "", workflows, wi, steps, si, stepId
    wi, si = int(tokens[2]), int(tokens[4])
    ids = _workflow_step_ids(document, wi)
    original = ids[si]
    if original is None:
        return
    # This is the k-th repeat of the id (the first declaration is kept); it takes the k-th free suffix.
    k = sum(1 for sid in ids[:si] if sid == original) - 1
    taken = {sid for sid in ids if sid is not None}
    n = 2
    free: List[str] = []
    while len(free) <= k:
        if f"{original}-{n}" not in taken:
            free.append(f"{original}-{n}")
        n += 1
    yield PatchOp.replace(pointer, free[k])


# ===========================================================================
# arazzo.success-criteria-scaffold
# ===========================================================================


def response_status_codes(operation: Mapping[str, Any]) -> List[str]:
    """The numeric ``2xx`` status codes an OpenAPI operation declares, sorted.

    Args:
        operation: An OpenAPI operation object.

    Returns:
        ``["200", "201"]``-style codes; a ``2XX`` range or ``default`` is not a code a
        ``$statusCode`` comparison can name, so it is not listed.
    """
    responses = operation.get("responses")
    if not isinstance(responses, Mapping):
        return []
    return sorted(str(code) for code in responses if _SUCCESS_CODE.match(str(code)))


def _embedded_openapi_operations(document: Mapping[str, Any]) -> Dict[str, Dict[str, Dict[str, Any]]]:
    """``{source name: {operationId: operation}}`` of the OpenAPI documents embedded as ``content``."""
    by_source: Dict[str, Dict[str, Dict[str, Any]]] = {}
    sources = document.get("sourceDescriptions")
    for entry in sources if isinstance(sources, list) else []:
        content = entry.get("content") if isinstance(entry, dict) else None
        name = entry.get("name") if isinstance(entry, dict) else None
        if not isinstance(name, str) or not isinstance(content, dict) or not content.get("openapi"):
            continue
        operations: Dict[str, Dict[str, Any]] = by_source.setdefault(name, {})
        for path_item in (content.get("paths") or {}).values():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method in HTTP_METHODS and isinstance(operation, dict):
                    operation_id = operation.get("operationId")
                    if isinstance(operation_id, str) and operation_id.strip():
                        operations.setdefault(operation_id, operation)
    return by_source


def _step_operation(
    document: Mapping[str, Any],
    step: Mapping[str, Any],
    operations: Mapping[str, Mapping[str, Dict[str, Any]]],
) -> Optional[Dict[str, Any]]:
    """The embedded OpenAPI operation a step calls by ``operationId``, when exactly one matches."""
    target = resolve_step_target(step, source_names=source_description_names(document.get("sourceDescriptions")))
    if target is None or target.kind != "operationId" or not target.operation_id:
        return None
    if target.source_name:
        return operations.get(target.source_name, {}).get(target.operation_id)
    matches = [ops[target.operation_id] for ops in operations.values() if target.operation_id in ops]
    return matches[0] if len(matches) == 1 else None


def _scaffold_code(codes: List[str]) -> str:
    """``200`` when declared, otherwise the lowest declared 2xx code."""
    return "200" if "200" in codes else codes[0]


def _check_missing_success_criteria(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """Flag a step with no ``successCriteria`` whose embedded source operation declares a 2xx code."""
    operations = _embedded_openapi_operations(document)
    if not operations:
        return
    for wi, si, step in _steps(document):
        if step.get("successCriteria"):
            continue
        operation = _step_operation(document, step, operations)
        codes = response_status_codes(operation) if operation is not None else []
        if codes:
            yield (
                _step_pointer(wi, si),
                f"Step declares no successCriteria; its operation declares a {_scaffold_code(codes)} response.",
            )


def _fix_missing_success_criteria(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Add ``successCriteria: [{condition: "$statusCode == <2xx>"}]``; nothing when no code is derivable."""
    pointer = pointer_for_path(document, finding.path)
    tokens = pointer.split("/")  # "", workflows, wi, steps, si
    step = document["workflows"][int(tokens[2])]["steps"][int(tokens[4])]
    operation = _step_operation(document, step, _embedded_openapi_operations(document))
    codes = response_status_codes(operation) if operation is not None else []
    if not codes or step.get("successCriteria"):
        return
    value = [{"condition": SCAFFOLD_CONDITION.format(code=_scaffold_code(codes))}]
    key_pointer = join_pointer(pointer, "successCriteria")
    yield PatchOp.replace(key_pointer, value) if "successCriteria" in step else PatchOp.add(key_pointer, value)


# ===========================================================================
# arazzo.version-marker-bump
# ===========================================================================

#: Parameter locations Arazzo 1.1 added (1.0 defines query, header, path, cookie).
_PARAMETER_LOCATIONS_1_1 = ("querystring", "channel")


def _declared_version(document: Mapping[str, Any]) -> Optional[Tuple[int, int]]:
    """The ``(major, minor)`` of the ``arazzo`` marker; ``None`` when unreadable."""
    try:
        return parse_arazzo_version(document.get("arazzo"))
    except ArazzoVersionError:
        return None


def _features_needing_1_1(document: Mapping[str, Any]) -> List[str]:
    """The Arazzo 1.1-only features a document uses, as short labels, in a stable order."""
    features: List[str] = []
    sources = document.get("sourceDescriptions")
    if any(
        isinstance(entry, dict) and entry.get("type") == SOURCE_TYPE_ASYNCAPI
        for entry in (sources if isinstance(sources, list) else [])
    ):
        features.append("an asyncapi source description")
    steps = [step for _wi, _si, step in _steps(document)]
    if any(isinstance(step.get("channelPath"), str) and step["channelPath"].strip() for step in steps):
        features.append("a channelPath step")
    locations = {
        parameter.get("in")
        for step in steps
        for parameter in (step.get("parameters") if isinstance(step.get("parameters"), list) else [])
        if isinstance(parameter, dict)
    }
    for location in _PARAMETER_LOCATIONS_1_1:
        if location in locations:
            features.append(f"a {location} parameter")
    return features


def _check_version_marker(document: Mapping[str, Any]) -> Iterable[Tuple[str, str]]:
    """Flag an ``arazzo: 1.0.x`` document that uses a 1.1-only feature."""
    if _declared_version(document) != (1, 0):
        return
    features = _features_needing_1_1(document)
    if features:
        yield (
            "/arazzo",
            f"The document declares Arazzo {document.get('arazzo')} but uses {', '.join(features)}, "
            f"which need Arazzo {ARAZZO_VERSION_1_1}.",
        )


def _fix_version_marker(
    document: Mapping[str, Any], finding: LintFinding, options: FixOptions
) -> Iterable[PatchOp]:
    """Replace the ``arazzo`` marker with ``1.1.0`` while the document is still declared 1.0."""
    if _declared_version(document) == (1, 0) and _features_needing_1_1(document):
        yield PatchOp.replace("/arazzo", ARAZZO_VERSION_1_1)


# ===========================================================================
# The rules
# ===========================================================================

_DOCUMENT_CHECKS: Dict[str, DocumentCheck] = {}


def _canonical_check(check: DocumentCheck) -> Callable[[CanonicalApi], Iterable[Tuple[str, str]]]:
    """Adapt a document check to the :class:`~app.lint_engine.LintRule` ``check`` signature.

    The check reads the artifact's retained source document and yields nothing without one.
    """

    def run(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
        from .example_conformance_lint import source_document

        document = source_document(api)
        if not is_arazzo_document(document):
            return []
        return [(path_from_pointer(pointer), message) for pointer, message in check(document)]

    return run


def _rule(rule_id: str, category: str, severity: str, description: str, check: DocumentCheck, **fix: Any) -> LintRule:
    """Build one fixable rule and remember its document check."""
    _DOCUMENT_CHECKS[rule_id] = check
    return LintRule(
        rule_id=rule_id,
        category=category,
        severity=severity,
        description=description,
        check=_canonical_check(check),
        **fix,
    )


_RULES: Tuple[LintRule, ...] = (
    _rule(
        "arazzo.step-id-suffix",
        "structure",
        "warning",
        "Step ids must be unique within their workflow; a repeat makes $steps and goto references ambiguous.",
        _check_duplicate_step_id,
        fix=_fix_duplicate_step_id,
        fix_class="rename",
        fix_summary="Suffixes a repeated stepId (-2, -3, …) to the first id the workflow does not use.",
    ),
    _rule(
        "arazzo.success-criteria-scaffold",
        "structure",
        "warning",
        "A step with no successCriteria cannot be verified; its source operation's 2xx response gives a start.",
        _check_missing_success_criteria,
        fix=_fix_missing_success_criteria,
        fix_class="fill-in",
        fix_summary=(
            "Adds successCriteria [{condition: '$statusCode == 200'}] from the 2xx response the "
            "step's embedded source operation declares. Off unless the guide enables it."
        ),
        fix_default=False,
    ),
    _rule(
        "arazzo.version-marker-bump",
        "version",
        "warning",
        "An Arazzo 1.0 document that uses a 1.1-only feature is rejected by a conforming 1.0 runner.",
        _check_version_marker,
        fix=_fix_version_marker,
        fix_class="structural",
        fix_summary="Bumps the arazzo marker to 1.1.0 when a 1.1-only feature is in use.",
    ),
)

_RULES_BY_ID: Dict[str, LintRule] = {rule.rule_id: rule for rule in _RULES}


def arazzo_fix_rules() -> Tuple[LintRule, ...]:
    """Return the fixable Arazzo rules, in the order the module documents them."""
    return _RULES


def arazzo_fix_rule(rule_id: str) -> Optional[LintRule]:
    """Return the fixable Arazzo rule with ``rule_id``, or ``None``."""
    return _RULES_BY_ID.get(rule_id)


def lint_arazzo_fixable(document: Mapping[str, Any]) -> List[LintFinding]:
    """Evaluate the fixable Arazzo rules over a document — on demand, never by default.

    Args:
        document: A parsed Arazzo document. Not mutated.

    Returns:
        The findings sorted by ``(path, rule, id)``; empty for anything that is not Arazzo.
    """
    if not is_arazzo_document(document):
        return []
    findings: List[LintFinding] = []
    for rule in _RULES:
        for pointer, message in _DOCUMENT_CHECKS[rule.rule_id](document):
            findings.append(
                LintFinding(
                    path=path_from_pointer(pointer),
                    category=rule.category,
                    rule=rule.rule_id,
                    severity=rule.severity,
                    message=message,
                )
            )
    return sorted(findings, key=lambda f: (f.path, f.rule, f.id))


def plan_arazzo_fix(
    document: Mapping[str, Any],
    finding: LintFinding,
    options: Optional[FixOptions] = None,
) -> Tuple[PatchOp, ...]:
    """Plan the deterministic fix of one Arazzo finding.

    Args:
        document: The document the finding was reported on. Not mutated.
        finding: A finding of any fixable Arazzo rule.
        options: The caller's fix options; the defaults when omitted.

    Returns:
        The RFC 6902 operations in application order; empty when the rule has no fix, needs an
        opt-in the options do not give, or this finding has no deterministic repair.

    Raises:
        app.lint_fix.FixError: When the finding's path addresses nothing in the document.
        app.lint_fix.FixScopeError: When a fix leaves the scope its rule declared.
    """
    rule = _RULES_BY_ID.get(finding.rule)
    return () if rule is None else rule.plan_fix(document, finding, options)
