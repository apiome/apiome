"""RAML lint pack — MFI-15.3 (#3801).

Native rules for RAML catalog items, registered under the ``raml`` format key the RAML normalizer
emits, so they run with the always-on common pack. Each rule reports the issues
:func:`app.raml_hygiene.raml_lint_issues` recorded on the item at import
(``extras["raml_lint_issues"]``):

* **raml.shacl-violation** (error) / **raml.shacl-warning** (warning) / **raml.shacl-info** (info)
  — AMF's SHACL validation of the RAML profile, one finding per result, at
  ``raml:<file>:<line>:<column>``. Only on servers with the bundled AMF toolchain.
* **raml.undeclared-security-scheme** (warning) — ``securedBy`` names an undeclared scheme.
* **raml.unused-base-uri-parameter** (warning) — a base URI parameter ``baseUri`` never uses.
* **raml.unused-uri-parameter** (warning) — a URI parameter its resource path never uses.
* **raml.method-without-responses** (warning) — a method that declares no response.
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack
from .raml_hygiene import (
    RULE_METHOD_WITHOUT_RESPONSES,
    RULE_SHACL_BY_SEVERITY,
    RULE_UNDECLARED_SECURITY_SCHEME,
    RULE_UNUSED_BASE_URI_PARAMETER,
    RULE_UNUSED_URI_PARAMETER,
)

__all__ = ["RamlRulePack"]


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
        issues = api.extras.get("raml_lint_issues") or []
        for issue in issues:
            if isinstance(issue, Mapping) and issue.get("rule") == rule_id:
                yield f"raml:{issue.get('path', '')}", str(issue.get("message", ""))
        total = api.extras.get("raml_lint_issue_count")
        if reports_overflow and isinstance(total, int) and total > len(issues):
            yield "raml:", f"{total - len(issues)} more RAML lint issue(s) not listed."

    return check


def _rule(rule_id: str, severity: str, category: str, description: str, *, overflow: bool = False) -> LintRule:
    """One RAML rule bound to its recorded-issue check."""
    return LintRule(
        rule_id=rule_id,
        category=category,
        severity=severity,  # type: ignore[arg-type]
        description=description,
        check=_check_for(rule_id, reports_overflow=overflow),
    )


class RamlRulePack(RulePack, register=True):
    """Native rules for RAML artifacts (see the module docstring)."""

    format = "raml"
    pack_id = "raml"

    _RULES: Tuple[LintRule, ...] = (
        _rule(
            RULE_SHACL_BY_SEVERITY["Violation"],
            "error",
            "structure",
            "A RAML API should conform to AMF's SHACL validation of the RAML profile.",
            overflow=True,
        ),
        _rule(RULE_SHACL_BY_SEVERITY["Warning"], "warning", "structure", "AMF's RAML validation reported a warning."),
        _rule(RULE_SHACL_BY_SEVERITY["Info"], "info", "structure", "AMF's RAML validation reported a note."),
        _rule(
            RULE_UNDECLARED_SECURITY_SCHEME,
            "warning",
            "structure",
            "Every securedBy scheme should be declared in securitySchemes.",
        ),
        _rule(
            RULE_UNUSED_BASE_URI_PARAMETER,
            "warning",
            "structure",
            "Every baseUriParameters entry should appear in baseUri.",
        ),
        _rule(
            RULE_UNUSED_URI_PARAMETER,
            "warning",
            "structure",
            "Every uriParameters entry should appear in its resource path.",
        ),
        _rule(
            RULE_METHOD_WITHOUT_RESPONSES,
            "warning",
            "documentation",
            "Every RAML method should declare at least one response.",
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the RAML native rules in deterministic execution order."""
        return list(self._RULES)
