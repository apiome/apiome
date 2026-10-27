"""Smithy breaking-change classifier — MFI-17.4 (#3811).

Smithy ships its own compatibility checker, ``smithy diff``: a set of diff evaluators
(``AddedRequiredMember``, ``ChangedMemberTarget``, ``RemovedShape``, ``ChangedEnumTrait``, …) that
compare two versions of a model and report each finding at a Smithy severity. This classifier runs
it through the bundled Smithy CLI (:func:`app.smithy_ast.run_smithy_diff`) and maps its severities
onto Apiome's:

==============  ==============  =====================================================
Smithy          Apiome          Meaning (Smithy's own reading)
==============  ==============  =====================================================
``ERROR``       breaking        the change breaks existing clients
``DANGER``      dangerous       the change is likely to break someone (member order)
``WARNING``     dangerous       the change may break someone; review it
``NOTE``        safe            informational: an added shape, an appended enum value
==============  ==============  =====================================================

Each finding names the shape it is about (``example.shelter#Pet$size``), which joins the
canonical change on the same entity: a member to its field (``example.shelter.Pet.size``), else to
the shape that holds it (an enum member to its enum); a shape to the type, service or operation of
that name. Where findings join a change, the worst of them replaces the baseline grade
(``rule_id`` ``smithy-diff.<evaluator id>``, the Smithy messages as rationale). A finding above
``NOTE`` that joins no change — a reordered structure, a removed operation binding on a service
whose own fields did not move — is kept in :attr:`ClassificationResult.unattributed
<app.breaking_change.ClassificationResult.unattributed>` and still counts toward the overall
severity, so a publish gate never misses a Smithy ``ERROR``.

Changes no finding joins keep the format-agnostic baseline grade, and so does the whole diff when
the Smithy CLI is unavailable, either model's text was not retained, or ``smithy diff`` cannot load
a model. The models compared are the ones kept on :attr:`CanonicalApi.raw
<app.canonical_model.CanonicalApi.raw>`: the assembled JSON AST (``smithy_ast``) for a multi-file
set, else the model file (``smithy``).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    ClassificationResult,
    Severity,
    UnattributedFinding,
    _assemble_result,
    _worst,
)
from .canonical_model import CanonicalApi
from .diff import EntityCategory, ModelDiff
from .smithy_ast import run_smithy_diff, smithy_cli_available

__all__ = ["SMITHY_SEVERITIES", "SmithyBreakingChangeClassifier", "model_text", "overlay_events"]

#: Smithy severity → Apiome severity.
SMITHY_SEVERITIES: Dict[str, Severity] = {
    "ERROR": Severity.BREAKING,
    "DANGER": Severity.DANGEROUS,
    "WARNING": Severity.DANGEROUS,
    "NOTE": Severity.SAFE,
}

_RULE_PREFIX = "smithy-diff."


def model_text(model: CanonicalApi) -> Optional[str]:
    """The model text ``smithy diff`` compares: the assembled JSON AST, else the model file.

    Args:
        model: An imported Smithy model.

    Returns:
        The text, or ``None`` when the model was normalized without its raw source.
    """
    raw = model.raw if isinstance(model.raw, Mapping) else {}
    for key in ("smithy_ast", "smithy"):
        text = raw.get(key)
        if isinstance(text, str) and text.strip():
            return text
    return None


def _candidates(shape_id: str) -> List[Tuple[Optional[EntityCategory], str]]:
    """The canonical keys a Smithy shape id may join, most specific first.

    ``ns#Name$member`` → the field ``ns.Name.member``, then the shape ``ns.Name``; ``ns#Name`` →
    the type or service ``ns.Name``, or an operation named ``Name`` (its key is
    ``ns.Service.Name``, marked by a ``None`` category).
    """
    if "#" not in shape_id:
        return []
    namespace, _, name = shape_id.partition("#")
    shape, _, member = name.partition("$")
    candidates: List[Tuple[Optional[EntityCategory], str]] = []
    if member:
        candidates.append((EntityCategory.FIELD, f"{namespace}.{shape}.{member}"))
    candidates += [
        (EntityCategory.TYPE, f"{namespace}.{shape}"),
        (EntityCategory.SERVICE, f"{namespace}.{shape}"),
        (None, f"{namespace}.{shape}"),
    ]
    return candidates


def _join(shape_id: str, changes: Mapping[Tuple[EntityCategory, str], List[int]]) -> List[int]:
    """The positions of the changes a finding on ``shape_id`` joins (empty when none)."""
    for category, key in _candidates(shape_id):
        if category is None:
            namespace, _, name = key.rpartition(".")
            positions = [
                position
                for (change_category, change_key), found in changes.items()
                if change_category is EntityCategory.OPERATION
                and change_key.startswith(f"{namespace}.")
                and change_key.rsplit(".", 1)[-1] == name
                for position in found
            ]
        else:
            positions = list(changes.get((category, key), []))
        if positions:
            return positions
    return []


def _graded(baseline: ChangeClassification, events: List[Mapping[str, Any]]) -> ChangeClassification:
    """``baseline`` regraded by the Smithy findings that join it: the worst wins, every message is kept."""
    severities = [SMITHY_SEVERITIES[event["severity"]] for event in events]
    worst = _worst(severities)
    rule = next(event["id"] for event, severity in zip(events, severities) if severity is worst)
    messages = list(dict.fromkeys(f"{event['id']}: {event['message']}" for event in events))
    return ChangeClassification(
        category=baseline.category,
        kind=baseline.kind,
        key=baseline.key,
        severity=worst,
        rule_id=f"{_RULE_PREFIX}{rule}",
        rationale=f"smithy diff — {'; '.join(messages)}",
    )


def overlay_events(
    classifications: List[ChangeClassification], events: List[Mapping[str, Any]]
) -> Tuple[List[ChangeClassification], List[UnattributedFinding]]:
    """Overlay ``smithy diff`` findings on per-change grades.

    Args:
        classifications: The baseline grades, 1:1 with the diff's changes.
        events: The ``smithy diff`` events (:func:`app.smithy_ast.run_smithy_diff`).

    Returns:
        The grades (the same length and order) with joined findings applied, and the findings
        above ``NOTE`` that join no change.
    """
    index: Dict[Tuple[EntityCategory, str], List[int]] = {}
    for position, classification in enumerate(classifications):
        index.setdefault((classification.category, classification.key), []).append(position)
    joined: Dict[int, List[Mapping[str, Any]]] = {}
    unattributed: List[UnattributedFinding] = []
    for event in events:
        severity = SMITHY_SEVERITIES.get(str(event.get("severity")))
        if severity is None:
            continue
        positions = _join(str(event.get("shape") or ""), index)
        for position in positions:
            joined.setdefault(position, []).append(event)
        if not positions and severity is not Severity.SAFE:
            unattributed.append(
                UnattributedFinding(
                    severity=severity,
                    rule_id=f"{_RULE_PREFIX}{event.get('id')}",
                    rationale=f"smithy diff — {event.get('message')}",
                    shape=event.get("shape"),
                )
            )
    graded = [
        _graded(classification, joined[position]) if position in joined else classification
        for position, classification in enumerate(classifications)
    ]
    return graded, unattributed


class SmithyBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a Smithy diff with ``smithy diff`` over the baseline (see the module docstring)."""

    format = "smithy"
    classifier_id = "smithy-diff"

    def classify(self, model_diff: ModelDiff, base: CanonicalApi, target: CanonicalApi) -> ClassificationResult:
        """Grade every change with the baseline, then overlay the ``smithy diff`` findings.

        Args:
            model_diff: The diff to grade.
            base: The "from" model (its raw text is the old model).
            target: The "to" model (its raw text is the new model).

        Returns:
            The result, 1:1 with ``model_diff.changes``, with unjoined findings in ``unattributed``.
        """
        baseline = [self.classify_change(change, base, target) for change in model_diff.changes]
        old_text, new_text = model_text(base), model_text(target)
        if old_text is None or new_text is None or not smithy_cli_available():
            return _assemble_result(self, target, baseline)
        events = run_smithy_diff(old_text, new_text)
        if events is None:
            return _assemble_result(self, target, baseline)
        graded, unattributed = overlay_events(baseline, events)
        return _assemble_result(self, target, graded, unattributed)
