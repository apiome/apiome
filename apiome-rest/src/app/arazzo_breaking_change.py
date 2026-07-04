"""Arazzo breaking-change classifier — MFI-30.2 (#4395).

The Arazzo provider on the MFI-3.3 breaking-change classifier SPI. Subclasses the
format-agnostic :class:`~app.breaking_change.BuiltinBreakingChangeClassifier` and
sharpens workflow semantics:

* a removed workflow step (operation) is **breaking** (inherited baseline);
* an added step is **safe** (inherited baseline);
* a workflow whose only change is ``extras.stepOrder`` is **dangerous** (step reorder
  changes execution order).
"""

from __future__ import annotations

from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    Severity,
)
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["ArazzoBreakingChangeClassifier"]


class ArazzoBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an Arazzo workflow diff with workflow-aware rules."""

    format = "arazzo"
    classifier_id = "arazzo-workflow"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        if (
            change.kind is ChangeKind.MODIFIED
            and change.category is EntityCategory.SERVICE
            and self._is_step_reorder_only(change)
        ):
            return ChangeClassification(
                category=change.category,
                kind=change.kind,
                key=change.key,
                severity=Severity.DANGEROUS,
                rule_id="arazzo.step-reorder",
                rationale=(
                    f"workflow {change.key!r} step order changed; execution sequence may differ"
                ),
            )
        return super().classify_change(change, base, target)

    @staticmethod
    def _is_step_reorder_only(change: EntityChange) -> bool:
        moved = {field.field for field in change.fields}
        return moved <= {"extras"} and any(
            field.field == "extras"
            and isinstance(field.before, dict)
            and isinstance(field.after, dict)
            and field.before.get("stepOrder") != field.after.get("stepOrder")
            for field in change.fields
        )
