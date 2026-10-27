"""Avro lint pack — MFI-12.5 (#3786).

Native rules for Avro catalog items (``.avsc`` and IDL), registered under the ``avro`` format key
the Avro normalizer emits, so they run with the always-on common pack. Each rule reports the
hygiene issues :mod:`app.avro_hygiene` recorded on the item at import
(``extras["avro_lint_issues"]``): union order, defaults and aliases are not in the canonical model,
so they are checked on the schema as written. See that module for what each rule checks.

* **avro.invalid-default** (error) — a default that is not a value of its type.
* **avro.invalid-union** (error) — a nested union, or a union that repeats a branch.
* **avro.invalid-alias** (error) — an alias that is not a valid Avro name.
* **avro.alias-conflict** (error) — an alias that collides with another field or named type.
* **avro.optional-union-null-first** (warning) — ``[T, "null"]`` with no default.
* **avro.optional-union-missing-default** (warning) — ``["null", T]`` with no default.
* **avro.doc-ignored** (warning) — a ``doc`` that is not a string, or sits on an anonymous type.
* **avro.redundant-alias** (info) — an alias equal to the element's own name.

Paths are ``avro:/<full type name>/fields/<field>`` (or ``avro:/messages/<message>/request/<param>``
for IDL message parameters).
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Tuple

from .avro_hygiene import (
    RULE_ALIAS_CONFLICT,
    RULE_DOC_IGNORED,
    RULE_INVALID_ALIAS,
    RULE_INVALID_DEFAULT,
    RULE_INVALID_UNION,
    RULE_OPTIONAL_UNION_MISSING_DEFAULT,
    RULE_OPTIONAL_UNION_NULL_FIRST,
    RULE_REDUNDANT_ALIAS,
    issues_by_rule,
)
from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack

__all__ = ["AvroRulePack"]


def _check_for(rule_id: str, *, reports_overflow: bool = False) -> Callable[[CanonicalApi], Iterable[Tuple[str, str]]]:
    """A check that yields the recorded issues of one rule.

    Args:
        rule_id: The rule whose issues to report.
        reports_overflow: Whether this rule also reports how many issues the import's cap left
            unlisted (exactly one rule does, since the overflow is not broken down by rule).

    Returns:
        The rule's ``check`` function.
    """

    def check(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
        issues = api.extras.get("avro_lint_issues") or []
        for path, message in issues_by_rule(issues, rule_id):
            yield f"avro:{path}", message
        total = api.extras.get("avro_lint_issue_count")
        if reports_overflow and isinstance(total, int) and total > len(issues):
            yield "avro:", f"{total - len(issues)} more Avro hygiene issue(s) not listed."

    return check


class AvroRulePack(RulePack, register=True):
    """Native rules for Avro artifacts (see the module docstring)."""

    format = "avro"
    pack_id = "avro"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id=RULE_INVALID_DEFAULT,
            category="structure",
            severity="error",
            description="An Avro default must be a value of its type (a union's, of its first branch).",
            check=_check_for(RULE_INVALID_DEFAULT, reports_overflow=True),
        ),
        LintRule(
            rule_id=RULE_INVALID_UNION,
            category="structure",
            severity="error",
            description="An Avro union must not nest a union or repeat a branch.",
            check=_check_for(RULE_INVALID_UNION),
        ),
        LintRule(
            rule_id=RULE_INVALID_ALIAS,
            category="naming",
            severity="error",
            description="An Avro alias must be a valid Avro name.",
            check=_check_for(RULE_INVALID_ALIAS),
        ),
        LintRule(
            rule_id=RULE_ALIAS_CONFLICT,
            category="naming",
            severity="error",
            description="An Avro alias must not collide with another field's or named type's name or alias.",
            check=_check_for(RULE_ALIAS_CONFLICT),
        ),
        LintRule(
            rule_id=RULE_OPTIONAL_UNION_NULL_FIRST,
            category="structure",
            severity="warning",
            description='An optional Avro field should be ["null", T] so it can default to null.',
            check=_check_for(RULE_OPTIONAL_UNION_NULL_FIRST),
        ),
        LintRule(
            rule_id=RULE_OPTIONAL_UNION_MISSING_DEFAULT,
            category="structure",
            severity="warning",
            description='An optional ["null", T] Avro field should declare "default": null.',
            check=_check_for(RULE_OPTIONAL_UNION_MISSING_DEFAULT),
        ),
        LintRule(
            rule_id=RULE_DOC_IGNORED,
            category="documentation",
            severity="warning",
            description="An Avro doc should be a string on a field or named type, where tools keep it.",
            check=_check_for(RULE_DOC_IGNORED),
        ),
        LintRule(
            rule_id=RULE_REDUNDANT_ALIAS,
            category="naming",
            severity="info",
            description="An Avro alias should differ from the name it aliases.",
            check=_check_for(RULE_REDUNDANT_ALIAS),
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the Avro native rules in deterministic execution order."""
        return list(self._RULES)
