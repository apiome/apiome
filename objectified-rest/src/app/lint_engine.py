"""
Schema lint engine — rule registry, dispatcher, runner skeleton.

Rules live in `lint_rules/` (added in Phase 2C) and self-register against the
module-level `registry` singleton on import. Each rule declares the kind of
target it cares about (class, property, or whole-schema); the runner walks the
version's classes/properties exactly once and dispatches each rule against the
appropriate iterable.

The runner is intentionally synchronous for v1. A "Run lint" request blocks
until completion. If perf becomes an issue on large schemas (>1k classes), v2
adds a worker queue and a `:status` endpoint — the persistence schema and rule
contract are stable across that change.

This module deliberately ships with **no rules registered**. Importing it must
not pull in any rule modules; rule packages do `from .. import lint_engine` and
register themselves. That gives us a clear boundary between the engine and the
rule set so the rule set can be extended without touching the engine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple


Severity = Literal["error", "warning", "info"]
TargetKind = Literal["class", "property", "schema"]


@dataclass
class LintFinding:
    """One finding emitted by a rule. Mirrors the `version_lint_findings` row
    shape (sans persistence-only columns like `id`/`result_id`/`created_at`).
    """

    rule_id: str
    severity: Severity
    target_kind: TargetKind
    target_path: str
    message: str
    target_id: Optional[str] = None
    suggestion: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None


# A "context" type each rule receives. Kept loose (Dict) so we can extend it
# without touching every rule signature. Required keys per target_kind:
#   class    : {"class": <class row dict>}
#   property : {"property": <class_property row dict>, "class": <class row dict>}
#   schema   : {"classes": [...], "properties": [...]}
LintContext = Dict[str, Any]


@dataclass
class LintRule:
    """Static rule definition. The `check` callable receives a `LintContext`
    appropriate for `target_kind` and returns a (possibly empty) list of
    findings. Rules MUST be pure given their inputs — no DB access, no I/O —
    so the runner can parallelize them later without coordination."""

    id: str
    severity: Severity
    title: str
    description: str
    target_kind: TargetKind
    check: Callable[[LintContext], List[LintFinding]]
    enabled: bool = True


@dataclass
class LintReport:
    """In-memory summary returned by `run_lint`. The route handler is what
    persists it (one transaction: parent row + all findings)."""

    findings: List[LintFinding] = field(default_factory=list)
    rules_applied: int = 0
    duration_ms: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "info")


class LintRuleRegistry:
    """Insertion-order rule registry. Singletons elsewhere in the codebase are
    instantiated as module-level objects — we follow that convention so a fresh
    `from .lint_engine import registry` always sees the same rule set."""

    def __init__(self) -> None:
        self._rules: Dict[str, LintRule] = {}

    def register(self, rule: LintRule) -> None:
        """Add a rule. Re-registering the same id is a programmer error and
        raises rather than silently overwriting; tests that need to override a
        rule should reach for `replace` instead."""
        if rule.id in self._rules:
            raise ValueError(f"Lint rule already registered: {rule.id}")
        self._rules[rule.id] = rule

    def replace(self, rule: LintRule) -> None:
        """Test-only override. Production code should never call this."""
        self._rules[rule.id] = rule

    def unregister(self, rule_id: str) -> None:
        self._rules.pop(rule_id, None)

    def get(self, rule_id: str) -> Optional[LintRule]:
        return self._rules.get(rule_id)

    def all(self) -> List[LintRule]:
        return list(self._rules.values())

    def by_target(self, target_kind: TargetKind) -> List[LintRule]:
        return [r for r in self._rules.values() if r.target_kind == target_kind and r.enabled]

    def __len__(self) -> int:
        return len(self._rules)


registry = LintRuleRegistry()


# ---------- Grade derivation ----------


def derive_grade(error_count: int, warning_count: int) -> Literal["A", "B", "C", "D", "F"]:
    """Letter grade from error/warning counts. Matches the contract advertised
    to the user when we picked the lint engine defaults:

      A — 0 errors, ≤2 warnings
      B — 0 errors, ≤5 warnings
      C — 0 errors, more warnings
      D — any error
      F — ≥5 errors

    Info-level findings never affect the grade."""
    if error_count >= 5:
        return "F"
    if error_count >= 1:
        return "D"
    if warning_count <= 2:
        return "A"
    if warning_count <= 5:
        return "B"
    return "C"


# ---------- Runner ----------


def _safe_run(rule: LintRule, ctx: LintContext) -> List[LintFinding]:
    """Execute one rule, swallowing exceptions into an `info` finding so a
    buggy rule never breaks the whole lint run. The buggy rule's id makes it
    into the finding so authors can spot what failed."""
    try:
        out = rule.check(ctx) or []
    except Exception as exc:  # noqa: BLE001 — defensive boundary for third-party rules
        return [
            LintFinding(
                rule_id=rule.id,
                severity="info",
                target_kind=rule.target_kind,
                target_path="<rule-error>",
                message=f"Rule {rule.id} crashed: {exc.__class__.__name__}: {exc}",
            )
        ]
    return list(out)


def run_lint(
    classes: List[Dict[str, Any]],
    properties: List[Dict[str, Any]],
) -> LintReport:
    """Apply every enabled rule to a version's class/property bundle.

    The route handler is responsible for loading classes/properties (it already
    holds an open DB connection) and persisting the resulting `LintReport`.
    Keeping the engine pure makes it cheap to unit-test against fixture data
    without spinning up Postgres."""
    start = time.perf_counter()
    findings: List[LintFinding] = []

    schema_ctx: LintContext = {"classes": classes, "properties": properties}
    for rule in registry.by_target("schema"):
        findings.extend(_safe_run(rule, schema_ctx))

    properties_by_class: Dict[str, List[Dict[str, Any]]] = {}
    for prop in properties:
        cid = str(prop.get("class_id"))
        properties_by_class.setdefault(cid, []).append(prop)

    class_rules = registry.by_target("class")
    property_rules = registry.by_target("property")

    for cls in classes:
        cls_ctx: LintContext = {"class": cls}
        for rule in class_rules:
            findings.extend(_safe_run(rule, cls_ctx))
        cls_id = str(cls.get("id"))
        for prop in properties_by_class.get(cls_id, []):
            prop_ctx: LintContext = {"class": cls, "property": prop}
            for rule in property_rules:
                findings.extend(_safe_run(rule, prop_ctx))

    duration_ms = int((time.perf_counter() - start) * 1000)
    return LintReport(
        findings=findings,
        rules_applied=len(registry),
        duration_ms=duration_ms,
    )


# ---------- Path helpers (used by rules in Phase 2C) ----------


def _non_blank(value: Any) -> Optional[str]:
    """Return the stripped string if it's a non-empty string, else None.
    Used by the path helpers so blank-but-truthy values like `"   "` fall
    through to the id fallback instead of rendering as an empty cell in the
    UI."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def class_path(cls: Dict[str, Any]) -> str:
    """Display path for a class-level finding (e.g. `User`). Falls back to the
    class id when the name is missing or blank, and to a literal placeholder
    when both are absent."""
    return _non_blank(cls.get("name")) or str(cls.get("id") or "<unnamed-class>")


def property_path(cls: Dict[str, Any], prop: Dict[str, Any]) -> str:
    """Display path for a property-level finding (e.g. `User.email`). Same
    blank/missing fallback behaviour as `class_path`."""
    name = _non_blank(prop.get("name")) or str(prop.get("id") or "<unnamed-property>")
    return f"{class_path(cls)}.{name}"


__all__ = [
    "LintContext",
    "LintFinding",
    "LintReport",
    "LintRule",
    "LintRuleRegistry",
    "Severity",
    "TargetKind",
    "class_path",
    "derive_grade",
    "property_path",
    "registry",
    "run_lint",
]
