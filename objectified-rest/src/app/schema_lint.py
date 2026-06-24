"""
Deterministic quality-scoring / linting engine over a generated OpenAPI document.

The engine walks the reconstructed OpenAPI/JSON-Schema for a project version and emits an
itemized, deterministic set of findings together with a numeric score (0-100) and an A-F
letter grade. It powers the real ``GET .../lint`` service that replaces the old client-side
(localStorage) quality score (#3609).

Design goals:

* **Deterministic** — the same input spec always produces the same findings, score, grade,
  and ``report_fingerprint``. Findings are sorted by ``(path, rule, id)`` and every finding id
  is a stable hash of ``path|rule|message``.
* **Pure** — no database or network access; callers pass a fully reconstructed spec dict.
* **Composable** — breaking-change findings from :mod:`app.compatibility_engine` can be merged
  in via :func:`merge_compatibility_findings` so the lint report can surface API-evolution risk.

Rule groups:

* ``naming``     — component schema names should be PascalCase; property names camelCase/snake_case.
* ``documentation`` — schemas/operations missing descriptions; leaf properties missing examples.
* ``structure``  — arrays without ``maxItems`` (unbounded collections).
* ``compatibility`` — breaking / unknown findings relative to a base revision (when supplied).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

# --- Severity model -------------------------------------------------------------------------

Severity = str  # "error" | "warning" | "info"

#: Score penalty applied per finding of each severity before per-rule capping.
SEVERITY_PENALTY: Mapping[str, float] = {
    "error": 10.0,
    "warning": 4.0,
    "info": 1.0,
}

#: Maximum total penalty a single rule may contribute, so one noisy rule cannot tank the
#: whole score on its own (keeps the grade meaningful for large specs).
PER_RULE_PENALTY_CAP: float = 20.0

#: Letter-grade thresholds, evaluated high-to-low.
GRADE_THRESHOLDS: Tuple[Tuple[int, str], ...] = (
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
    (0, "F"),
)

# --- Naming conventions ---------------------------------------------------------------------

_PASCAL_CASE = re.compile(r"^[A-Z][A-Za-z0-9]*$")
_CAMEL_CASE = re.compile(r"^[a-z][A-Za-z0-9]*$")
_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")

#: Scalar JSON Schema types whose leaf properties are expected to carry an example.
_SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean"})


def _is_pascal_case(name: str) -> bool:
    return bool(_PASCAL_CASE.match(name))


def _is_property_name_ok(name: str) -> bool:
    """Property names are acceptable in either camelCase or snake_case."""
    return bool(_CAMEL_CASE.match(name) or _SNAKE_CASE.match(name))


@dataclass(frozen=True)
class LintFinding:
    """One itemized lint result. ``id`` is a stable hash of ``path|rule|message``."""

    path: str
    category: str
    rule: str
    severity: Severity
    message: str
    id: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not self.id:
            digest = hashlib.sha256(
                f"{self.path}|{self.rule}|{self.message}".encode("utf-8")
            ).hexdigest()[:16]
            object.__setattr__(self, "id", f"lint-{digest}")

    def as_dict(self) -> Dict[str, str]:
        return {
            "id": self.id,
            "path": self.path,
            "category": self.category,
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True)
class LintResult:
    """Engine output suitable for APIs, CLI rendering, and audit payloads."""

    score: int
    grade: str
    findings: Tuple[LintFinding, ...]
    rule_hits: Mapping[str, int]
    severity_counts: Mapping[str, int]
    report_fingerprint: str

    def finding_dicts(self) -> List[Dict[str, str]]:
        return [f.as_dict() for f in self.findings]


# --- Rule catalogue -------------------------------------------------------------------------
# Each rule maps to (category, severity). Centralised so the engine and the API stay in sync.

RULE_CATALOGUE: Mapping[str, Tuple[str, Severity]] = {
    "naming.schema-pascal-case": ("naming", "warning"),
    "naming.property-name": ("naming", "warning"),
    "documentation.schema-missing-description": ("documentation", "warning"),
    "documentation.property-missing-description": ("documentation", "info"),
    "documentation.property-missing-example": ("documentation", "info"),
    "documentation.operation-missing-summary": ("documentation", "warning"),
    "documentation.info-missing-description": ("documentation", "info"),
    "structure.unbounded-array": ("structure", "warning"),
    "compatibility.breaking": ("compatibility", "error"),
    "compatibility.unknown": ("compatibility", "warning"),
}


def _make_finding(path: str, rule: str, message: str) -> LintFinding:
    category, severity = RULE_CATALOGUE[rule]
    return LintFinding(path=path, category=category, rule=rule, severity=severity, message=message)


def _has_example(schema: Mapping[str, Any]) -> bool:
    """True when the schema carries an ``example`` or non-empty ``examples`` (OAS 3.0/3.1)."""
    if "example" in schema:
        return True
    examples = schema.get("examples")
    if isinstance(examples, list):
        return len(examples) > 0
    if isinstance(examples, dict):
        return len(examples) > 0
    return False


def _is_ref_only(schema: Mapping[str, Any]) -> bool:
    """A pure ``$ref`` node carries no place for description/example, so skip those checks."""
    return "$ref" in schema and "type" not in schema and "properties" not in schema


def _walk_property(
    name: str,
    schema: Any,
    path: str,
    findings: List[LintFinding],
) -> None:
    """Recursively lint a single property schema (and its nested object/array members)."""
    if not isinstance(schema, dict):
        return

    # Naming: property keys should be camelCase or snake_case.
    if not _is_property_name_ok(name):
        findings.append(
            _make_finding(
                path,
                "naming.property-name",
                f"Property '{name}' is not camelCase or snake_case.",
            )
        )

    ref_only = _is_ref_only(schema)
    schema_type = schema.get("type")

    if not ref_only:
        # Documentation: every property should describe itself.
        if not _nonempty_str(schema.get("description")):
            findings.append(
                _make_finding(
                    path,
                    "documentation.property-missing-description",
                    f"Property '{name}' is missing a description.",
                )
            )
        # Documentation: leaf scalar properties should carry an example.
        if schema_type in _SCALAR_TYPES and not _has_example(schema):
            findings.append(
                _make_finding(
                    path,
                    "documentation.property-missing-example",
                    f"Property '{name}' ({schema_type}) is missing an example.",
                )
            )

    # Structure: arrays must bound their size.
    if schema_type == "array" and "maxItems" not in schema:
        findings.append(
            _make_finding(
                path,
                "structure.unbounded-array",
                f"Array property '{name}' has no maxItems (unbounded collection).",
            )
        )

    # Recurse into nested object properties.
    nested = schema.get("properties")
    if isinstance(nested, dict):
        for child_name in sorted(nested.keys()):
            _walk_property(
                child_name,
                nested[child_name],
                f"{path}.properties.{child_name}",
                findings,
            )

    # Recurse into array item schemas.
    if schema_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            item_props = items.get("properties")
            if isinstance(item_props, dict):
                for child_name in sorted(item_props.keys()):
                    _walk_property(
                        child_name,
                        item_props[child_name],
                        f"{path}.items.properties.{child_name}",
                        findings,
                    )


def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _lint_schemas(spec: Mapping[str, Any], findings: List[LintFinding]) -> None:
    components = spec.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict):
        return
    for schema_name in sorted(schemas.keys()):
        schema = schemas[schema_name]
        base_path = f"components.schemas.{schema_name}"
        if not _is_pascal_case(schema_name):
            findings.append(
                _make_finding(
                    base_path,
                    "naming.schema-pascal-case",
                    f"Schema '{schema_name}' is not PascalCase.",
                )
            )
        if isinstance(schema, dict):
            if not _nonempty_str(schema.get("description")):
                findings.append(
                    _make_finding(
                        base_path,
                        "documentation.schema-missing-description",
                        f"Schema '{schema_name}' is missing a description.",
                    )
                )
            props = schema.get("properties")
            if isinstance(props, dict):
                for prop_name in sorted(props.keys()):
                    _walk_property(
                        prop_name,
                        props[prop_name],
                        f"{base_path}.properties.{prop_name}",
                        findings,
                    )


def _lint_operations(spec: Mapping[str, Any], findings: List[LintFinding]) -> None:
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return
    http_methods = ("get", "put", "post", "delete", "patch", "options", "head", "trace")
    for path_name in sorted(paths.keys()):
        path_item = paths[path_name]
        if not isinstance(path_item, dict):
            continue
        for method in http_methods:
            operation = path_item.get(method)
            if not isinstance(operation, dict):
                continue
            if not _nonempty_str(operation.get("summary")) and not _nonempty_str(
                operation.get("description")
            ):
                findings.append(
                    _make_finding(
                        f"paths.{path_name}.{method}",
                        "documentation.operation-missing-summary",
                        f"Operation {method.upper()} {path_name} has no summary or description.",
                    )
                )


def _lint_info(spec: Mapping[str, Any], findings: List[LintFinding]) -> None:
    info = spec.get("info")
    description = info.get("description") if isinstance(info, dict) else None
    if not _nonempty_str(description):
        findings.append(
            _make_finding(
                "info",
                "documentation.info-missing-description",
                "API info block is missing a description.",
            )
        )


def _report_fingerprint(score: int, grade: str, finding_dicts: List[Dict[str, str]]) -> str:
    """Stable hash over score, grade, and sorted findings for audit / API identity."""
    payload = {
        "score": score,
        "grade": grade,
        "findings": sorted(
            finding_dicts,
            key=lambda x: (x.get("path", ""), x.get("rule", ""), x.get("id", "")),
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _grade_for_score(score: int) -> str:
    for threshold, grade in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "F"


def _score_from_findings(findings: List[LintFinding]) -> int:
    """Deterministic 0-100 score: 100 minus capped per-rule severity penalties."""
    penalty_by_rule: Dict[str, float] = {}
    for finding in findings:
        weight = SEVERITY_PENALTY.get(finding.severity, 0.0)
        penalty_by_rule[finding.rule] = penalty_by_rule.get(finding.rule, 0.0) + weight
    total_penalty = sum(min(p, PER_RULE_PENALTY_CAP) for p in penalty_by_rule.values())
    return max(0, min(100, round(100.0 - total_penalty)))


def _rule_hits(findings: List[LintFinding]) -> Dict[str, int]:
    hits: Dict[str, int] = {}
    for finding in findings:
        hits[finding.rule] = hits.get(finding.rule, 0) + 1
    return dict(sorted(hits.items()))


def _severity_counts(findings: List[LintFinding]) -> Dict[str, int]:
    counts = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        if finding.severity in counts:
            counts[finding.severity] += 1
    return counts


def lint_openapi_spec(
    spec: Mapping[str, Any],
    extra_findings: Optional[List[LintFinding]] = None,
) -> LintResult:
    """
    Lint a reconstructed OpenAPI document and return a deterministic :class:`LintResult`.

    :param spec: the OpenAPI/JSON-Schema document (as produced by ``generate_openapi_spec``).
    :param extra_findings: optional pre-built findings (e.g. compatibility breaking flags) to
        merge into the report and the score.
    :returns: score, grade, sorted findings, rule hits, severity counts, and a stable fingerprint.
    """
    findings: List[LintFinding] = list(extra_findings or [])
    _lint_info(spec, findings)
    _lint_schemas(spec, findings)
    _lint_operations(spec, findings)

    # Deterministic ordering: by path, then rule, then stable id.
    findings.sort(key=lambda f: (f.path, f.rule, f.id))

    score = _score_from_findings(findings)
    grade = _grade_for_score(score)
    finding_dicts = [f.as_dict() for f in findings]
    fingerprint = _report_fingerprint(score, grade, finding_dicts)

    return LintResult(
        score=score,
        grade=grade,
        findings=tuple(findings),
        rule_hits=_rule_hits(findings),
        severity_counts=_severity_counts(findings),
        report_fingerprint=fingerprint,
    )


def merge_compatibility_findings(compat_findings: Any) -> List[LintFinding]:
    """
    Translate :class:`app.schema_compatibility.CompatibilityFinding` items into lint findings.

    ``breaking`` findings become ``compatibility.breaking`` (error severity); ``unknown``
    findings become ``compatibility.unknown`` (warning). ``safe`` findings are not surfaced as
    lint findings (they are not quality defects).
    """
    out: List[LintFinding] = []
    for f in compat_findings or []:
        category = getattr(f, "category", None)
        path = getattr(f, "path", "") or ""
        message = getattr(f, "message", "") or ""
        if category == "breaking":
            out.append(_make_finding(path, "compatibility.breaking", message))
        elif category == "unknown":
            out.append(_make_finding(path, "compatibility.unknown", message))
    return out
