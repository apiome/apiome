"""Arazzo breaking-change classifier — MFI-30.2 (#4395), COA-1.6 (#7042).

The Arazzo provider on the MFI-3.3 breaking-change classifier SPI. Subclasses the
format-agnostic :class:`~app.breaking_change.BuiltinBreakingChangeClassifier` and
sharpens workflow semantics with the Arazzo rules in :mod:`app.arazzo_change_rules`:

* a removed workflow or step is **breaking**, an added one **safe** (inherited baseline);
* a modified workflow or step is graded by what moved inside its ``extras``: inputs schema,
  outputs, parameters, success criteria, ``onSuccess`` / ``onFailure`` actions, the step's
  target, the step order (a reorder of shared steps is **dangerous**; a shift caused by an added
  or removed step is **safe**). The worst rule wins and the rationale lists every rule that fired;
* changes the diff does not itemize — ``sourceDescriptions``, ``components`` and a workflow input
  that moved only inside a referenced ``components.inputs`` entry — are reported as
  :class:`~app.breaking_change.UnattributedFinding` s, one per change, so they still count toward
  the overall severity;
* a change no rule knows is **breaking** under ``ctg.unclassified`` (fail-safe).

:attr:`ArazzoBreakingChangeClassifier.grades_classified_diff` puts Arazzo revisions on the
canonical path of the classified diff and catalog change reports, so these rules are what
``apiome diff``, the diff Action and the change report show.
"""

from __future__ import annotations

from typing import Any, ClassVar, List, Mapping

from .arazzo_change_rules import (
    ArazzoChange,
    grade,
    resolve_inputs,
    root_changes,
    step_changes,
    workflow_changes,
    worst_of,
)
from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    ClassificationResult,
    UnattributedFinding,
    _assemble_result,
    _worst,
)
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange, FieldChange, ModelDiff

__all__ = ["ArazzoBreakingChangeClassifier"]


def _components(api: CanonicalApi) -> Mapping[str, Any]:
    """The document's ``components`` bag (root ``extras.components``), or ``{}``."""
    components = (api.extras or {}).get("components")
    return components if isinstance(components, dict) else {}


def _extras_field(change: EntityChange) -> FieldChange | None:
    """The ``extras`` attribute move of a modified entity, when there is one."""
    return next((field for field in change.fields if field.field == "extras"), None)


def _as_dict(value: Any) -> Mapping[str, Any]:
    """``value`` when it is a mapping, else ``{}`` (extras may be missing on either side)."""
    return value if isinstance(value, dict) else {}


class ArazzoBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an Arazzo workflow diff with workflow-aware rules."""

    format = "arazzo"
    classifier_id = "arazzo-workflow"

    #: Grade Arazzo revisions canonically in the classified diff and change reports (COA-1.6).
    grades_classified_diff: ClassVar[bool] = True

    def classify(self, model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi) -> ClassificationResult:
        """Grade each change, then add the document-level changes the diff does not itemize.

        Args:
            model_diff: The diff to grade.
            base: The "from" model.
            target: The "to" model.

        Returns:
            The result: one grade per change, plus an unattributed finding per source description,
            component or referenced-input change.
        """
        classifications = [self.classify_change(change, base, target) for change in model_diff.changes]
        modified_workflows = {
            change.key
            for change in model_diff.changes
            if change.category is EntityCategory.SERVICE and change.kind is ChangeKind.MODIFIED
        }
        found: List[ArazzoChange] = root_changes(_as_dict(base.extras), _as_dict(target.extras))
        found += self._referenced_input_changes(base, target, skip=modified_workflows)
        return _assemble_result(self, target, classifications, [self._finding(change) for change in found])

    def classify_change(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> ChangeClassification:
        """Grade one change: a modified workflow or step by the Arazzo rules, all else by the baseline.

        Args:
            change: The diff change to grade.
            base: The "from" model (its ``components`` resolve a base inputs ``$ref``).
            target: The "to" model.

        Returns:
            The grade. For a modified workflow or step, the worst of the Arazzo rules that fired on
            its ``extras`` and the baseline's grade of any other attribute that moved.
        """
        if change.kind is not ChangeKind.MODIFIED or change.category not in (
            EntityCategory.SERVICE,
            EntityCategory.OPERATION,
        ):
            return super().classify_change(change, base, target)
        extras = _extras_field(change)
        before, after = _as_dict(extras.before if extras else None), _as_dict(extras.after if extras else None)
        if change.category is EntityCategory.SERVICE:
            found = workflow_changes(
                change.key,
                before,
                after,
                base_components=_components(base),
                target_components=_components(target),
            )
        else:
            found = step_changes(change.key, before, after)
        graded = worst_of(found)
        rest = [field for field in change.fields if field.field != "extras"]
        if rest:
            baseline = super().classify_change(change.model_copy(update={"fields": rest}), base, target)
            if graded is None or _worst([graded[0], baseline.severity]) is not graded[0]:
                return baseline
        if graded is None:
            # Only keys the rules ignore moved (a workflow's declaration position, a step's index).
            noun = "workflow" if change.category is EntityCategory.SERVICE else "step"
            graded = grade(ArazzoChange("arazzo_position_changed", "", f"{noun} {change.key!r} only moved position"))
        severity, rule_id, rationale = graded
        return ChangeClassification(
            category=change.category,
            kind=change.kind,
            key=change.key,
            severity=severity,
            rule_id=rule_id,
            rationale=rationale,
        )

    @staticmethod
    def _referenced_input_changes(base: CanonicalApi, target: CanonicalApi, *, skip: set) -> List[ArazzoChange]:
        """Input changes of workflows whose ``inputs`` ``$ref`` held while its component moved.

        Args:
            base: The "from" model.
            target: The "to" model.
            skip: Workflows the diff already reports as modified (graded by :meth:`classify_change`).

        Returns:
            The input changes of every other workflow present in both versions.
        """
        targets = {service.key: service for service in target.services}
        found: List[ArazzoChange] = []
        for service in base.services:
            other = targets.get(service.key)
            if other is None or service.key in skip:
                continue
            before = _as_dict(service.extras)
            after = _as_dict(other.extras)
            if resolve_inputs(before.get("inputs"), _components(base)) == resolve_inputs(
                after.get("inputs"), _components(target)
            ):
                continue
            found += [
                change
                for change in workflow_changes(
                    service.key,
                    {"inputs": before.get("inputs")},
                    {"inputs": after.get("inputs")},
                    base_components=_components(base),
                    target_components=_components(target),
                )
            ]
        return found

    @staticmethod
    def _finding(change: ArazzoChange) -> UnattributedFinding:
        """An unattributed finding for a document-level change, keyed by its pointer."""
        severity, rule_id, rationale = grade(change)
        return UnattributedFinding(severity=severity, rule_id=rule_id, rationale=rationale, shape=change.pointer)
