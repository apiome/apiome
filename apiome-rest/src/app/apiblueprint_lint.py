"""API Blueprint lint pack — MFI-16.3 (#3806).

Native rules for API Blueprint catalog items, registered under the ``apiblueprint`` format key the
normalizer emits, so they run with the always-on common pack. They report drafter's annotations of
the blueprint (:mod:`app.apiblueprint_drafter`), recorded on the item at import
(``extras["apib_drafter_annotations"]``) — "zero warnings = good":

* **apiblueprint.drafter-warning** (warning) — a drafter warning: a URI-template parameter that is
  not defined, a duplicate resource, an empty body, an action with no response, …
* **apiblueprint.drafter-error** (error) — a drafter error: a base type that is undefined or
  circular, tabs in the source. drafter cannot produce a correct model of such a blueprint; the
  built-in reader imported what it could.

Each finding is at ``apib:<line>:<column>`` (``apib:`` when drafter gave no location), its message
prefixed with drafter's annotation code (``(8)``). Only servers with the bundled drafter report them.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack

__all__ = ["ApiblueprintRulePack"]


def _path(annotation: Mapping[str, Any]) -> str:
    """``apib:<line>:<column>`` for a located annotation, ``apib:`` otherwise."""
    if annotation.get("line") is None:
        return "apib:"
    return f"apib:{annotation.get('line')}:{annotation.get('column')}"


def _check_for(severity: str, *, reports_overflow: bool = False) -> Callable[[CanonicalApi], Iterable[Tuple[str, str]]]:
    """A check that yields the recorded drafter annotations of one severity.

    Args:
        severity: ``warning`` or ``error``.
        reports_overflow: Whether this rule also reports how many annotations the import's cap left
            unlisted (exactly one rule does, since the overflow is not broken down by severity).

    Returns:
        The rule's ``check`` function.
    """

    def check(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
        annotations = api.extras.get("apib_drafter_annotations") or []
        for annotation in annotations:
            if isinstance(annotation, Mapping) and annotation.get("severity") == severity:
                code = annotation.get("code")
                prefix = f"({code}) " if code is not None else ""
                yield _path(annotation), f"{prefix}{annotation.get('message', '')}"
        total = api.extras.get("apib_drafter_annotation_count")
        if reports_overflow and isinstance(total, int) and total > len(annotations):
            yield "apib:", f"{total - len(annotations)} more drafter annotation(s) not listed."

    return check


class ApiblueprintRulePack(RulePack, register=True):
    """Native rules for API Blueprint artifacts (see the module docstring)."""

    format = "apiblueprint"
    pack_id = "apiblueprint"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="apiblueprint.drafter-error",
            category="structure",
            severity="error",
            description="drafter, the reference API Blueprint parser, should report no errors.",
            check=_check_for("error"),
        ),
        LintRule(
            rule_id="apiblueprint.drafter-warning",
            category="structure",
            severity="warning",
            description="drafter, the reference API Blueprint parser, should report no warnings.",
            check=_check_for("warning", reports_overflow=True),
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the API Blueprint native rules in deterministic execution order."""
        return list(self._RULES)
