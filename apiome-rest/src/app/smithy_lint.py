"""Smithy lint pack — MFI-17.3 (#3810).

Native rules for Smithy catalog items, registered under the ``smithy`` format key the Smithy
normalizer emits, so they run with the always-on common pack. They report the ``smithy validate``
events recorded on the item at import (``extras["smithy_validation_events"]``,
:func:`app.smithy_ast.validate_smithy_members`), which include the ``smithy-linters`` validators
Apiome switches on (:data:`app.smithy_ast.SMITHY_LINTERS`):

* **smithy.linter** (warning) — a ``smithy-linters`` finding: ``CamelCase``,
  ``MissingPaginatedTrait``, ``AbbreviationName``, ``StutteredShapeName``, ….
* **smithy.validation-error** (error) — an ``ERROR`` event: the model is invalid Smithy (seen for a
  single ``.smithy`` file the built-in reader accepted; a multi-file set with errors is refused).
* **smithy.validation-warning** (warning) — a ``DANGER`` / ``WARNING`` event from Smithy's built-in
  validators (or the model's own ``metadata validators``).
* **smithy.validation-note** (info) — a ``NOTE`` event.

Each finding is at ``smithy:<file>:<line>:<column>`` (``smithy:<shape id>`` when the event has no
file), its message prefixed with the event id. Only servers with the bundled Smithy CLI report them.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, List, Mapping, Tuple

from .canonical_model import CanonicalApi
from .lint_engine import LintRule, RulePack
from .smithy_ast import SMITHY_LINTERS

__all__ = ["SmithyRulePack", "rule_for_event"]

_LINTER_IDS = frozenset(SMITHY_LINTERS)


def rule_for_event(event: Mapping[str, Any]) -> str:
    """The ``smithy.*`` rule an event is reported under.

    A linter's event id is its name, optionally followed by a ``.``-separated detail
    (``CamelCase.MemberName``), so the part before the first ``.`` is matched.
    """
    if str(event.get("id") or "").split(".", 1)[0] in _LINTER_IDS:
        return "smithy.linter"
    severity = str(event.get("severity") or "").upper()
    if severity == "ERROR":
        return "smithy.validation-error"
    if severity == "NOTE":
        return "smithy.validation-note"
    return "smithy.validation-warning"


def _path(event: Mapping[str, Any]) -> str:
    """``smithy:<file>:<line>:<column>``, or ``smithy:<shape>`` for an event with no file."""
    if event.get("file"):
        return f"smithy:{event.get('file')}:{event.get('line')}:{event.get('column')}"
    return f"smithy:{event.get('shape') or ''}"


def _check_for(rule_id: str, *, reports_overflow: bool = False) -> Callable[[CanonicalApi], Iterable[Tuple[str, str]]]:
    """A check that yields the recorded events of one rule.

    Args:
        rule_id: The rule whose events to report.
        reports_overflow: Whether this rule also reports how many events the import's cap left
            unlisted (exactly one rule does, since the overflow is not broken down by rule).

    Returns:
        The rule's ``check`` function.
    """

    def check(api: CanonicalApi) -> Iterable[Tuple[str, str]]:
        events = api.extras.get("smithy_validation_events") or []
        for event in events:
            if isinstance(event, Mapping) and rule_for_event(event) == rule_id:
                yield _path(event), f"{event.get('id', '')}: {event.get('message', '')}"
        total = api.extras.get("smithy_validation_event_count")
        if reports_overflow and isinstance(total, int) and total > len(events):
            yield "smithy:", f"{total - len(events)} more Smithy validation event(s) not listed."

    return check


class SmithyRulePack(RulePack, register=True):
    """Native rules for Smithy artifacts (see the module docstring)."""

    format = "smithy"
    pack_id = "smithy"

    _RULES: Tuple[LintRule, ...] = (
        LintRule(
            rule_id="smithy.validation-error",
            category="structure",
            severity="error",
            description="A Smithy model must validate: the Smithy CLI reports no ERROR events.",
            check=_check_for("smithy.validation-error"),
        ),
        LintRule(
            rule_id="smithy.linter",
            category="naming",
            severity="warning",
            description=(
                "A Smithy model should pass the smithy-linters validators (CamelCase, MissingPaginatedTrait, …)."
            ),
            check=_check_for("smithy.linter", reports_overflow=True),
        ),
        LintRule(
            rule_id="smithy.validation-warning",
            category="structure",
            severity="warning",
            description="A Smithy model should have no DANGER or WARNING validation events.",
            check=_check_for("smithy.validation-warning"),
        ),
        LintRule(
            rule_id="smithy.validation-note",
            category="structure",
            severity="info",
            description="A NOTE event from Smithy's validators.",
            check=_check_for("smithy.validation-note"),
        ),
    )

    def rules(self) -> List[LintRule]:
        """Return the Smithy native rules in deterministic execution order."""
        return list(self._RULES)
