"""Arazzo change rules: what moved in a workflow, and how much it matters — COA-1.6 (#7042).

The canonical diff (:mod:`app.diff`) reports an Arazzo workflow as a *service* and each step as an
*operation*; almost everything a workflow says — its inputs schema, outputs, parameters, success
criteria, ``onSuccess`` / ``onFailure`` actions — lives in the entity's ``extras`` bag, so the diff
sees one opaque ``extras`` move. This module opens that bag. It is the Arazzo half of the CTG
classifier registry (:mod:`app.change_taxonomy_rules`):

* :data:`ARAZZO_RULES` is the rule table. Each :class:`ArazzoRule` has a stable ``rule_id``, the raw
  ``change_kind`` it matches, its grade on the canonical three-tier scale
  (:class:`~app.breaking_change.Severity`) and a one-line summary. Every rule is also registered in
  the CTG registry (with its CTG severity), so the taxonomy lists it and a lookup that misses it
  takes the registry's fail-safe.
* The enumerators — :func:`workflow_changes`, :func:`step_changes`, :func:`root_changes` — compare
  the ``before`` / ``after`` extras and return one :class:`ArazzoChange` per thing that moved.
  A key the enumerators do not know becomes a ``<key>_changed`` kind no rule claims.
* :func:`grade` looks a change's kind up in the CTG registry. A kind no rule claims is graded
  **breaking** under ``ctg.unclassified`` (fail-safe), exactly like an unknown OpenAPI change.

The module is pure: no DB, no network.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .breaking_change import Severity
from .change_taxonomy_rules import (
    UNCLASSIFIED_RULE_ID,
    TaxonomyRule,
    register_rules,
    rule_for_kind,
)

__all__ = [
    "ArazzoRule",
    "ArazzoChange",
    "ARAZZO_RULES",
    "ARAZZO_RULES_BY_KIND",
    "grade",
    "workflow_changes",
    "step_changes",
    "root_changes",
    "resolve_inputs",
    "steps_reordered",
    "worst_of",
]

_S, _D, _B = Severity.SAFE, Severity.DANGEROUS, Severity.BREAKING


@dataclass(frozen=True)
class ArazzoRule:
    """One Arazzo change rule.

    Attributes:
        rule_id: Stable identifier (``arazzo.<name>``).
        change_kind: The raw change kind the enumerators emit for it (``arazzo_<name>``).
        severity: The canonical grade (safe / dangerous / breaking).
        summary: One-line description of the change the rule reports.
        docs_only: Whether the change only touches documentation (``docs-only`` in the CTG scale).
    """

    rule_id: str
    change_kind: str
    severity: Severity
    summary: str
    docs_only: bool = False

    @property
    def ctg_severity(self) -> str:
        """The CTG severity: breaking stays breaking, docs are docs-only, the rest non-breaking."""
        if self.docs_only:
            return "docs-only"
        return "breaking" if self.severity is _B else "non-breaking"


def _rule(name: str, severity: Severity, summary: str, *, docs_only: bool = False) -> ArazzoRule:
    """Build a rule whose id is ``arazzo.<name>`` and whose kind is ``arazzo_<name>`` (dashes → ``_``)."""
    return ArazzoRule(
        rule_id=f"arazzo.{name}",
        change_kind=f"arazzo_{name.replace('-', '_')}",
        severity=severity,
        summary=summary,
        docs_only=docs_only,
    )


#: Every Arazzo change rule, in the order the docs list them.
ARAZZO_RULES: Tuple[ArazzoRule, ...] = (
    # Steps and their order.
    _rule("step-reorder", _D, "Steps both versions share run in a different order."),
    _rule("step-order-shifted", _S, "A step was added or removed; the other steps keep their order."),
    _rule("step-target-changed", _B, "A step calls a different operation, channel or workflow."),
    _rule("depends-on-changed", _D, "The workflows or steps a workflow or step depends on changed."),
    _rule("request-body-changed", _D, "The request body or request a step sends changed."),
    _rule("position-changed", _S, "Only a workflow's or step's declaration position moved."),
    # Workflow inputs (a JSON Schema, after resolving `$ref` to `components.inputs`).
    _rule("input-required-added", _B, "A workflow input became required, or a required input was added."),
    _rule("input-type-changed", _B, "A workflow input's type changed."),
    _rule("input-removed", _D, "A workflow input was removed; callers that still send it may be rejected."),
    _rule("inputs-changed", _D, "A workflow input's schema changed (format, enum, constraints, …)."),
    _rule("input-added", _S, "An optional workflow input was added."),
    _rule("input-required-removed", _S, "A workflow input is no longer required."),
    # Outputs (workflow and step).
    _rule("output-removed", _B, "A workflow or step output was removed; whatever reads it breaks."),
    _rule("output-changed", _D, "A workflow or step output's expression changed."),
    _rule("output-added", _S, "A workflow or step output was added."),
    # Parameters (workflow, step and `components.parameters`).
    _rule("parameter-added", _D, "A parameter the workflow sends was added."),
    _rule("parameter-removed", _D, "A parameter the workflow sent was removed."),
    _rule("parameter-changed", _D, "A parameter's location or value changed."),
    # Success / failure criteria and actions.
    _rule("success-criteria-added", _D, "A step success criterion was added; runs that passed may now fail."),
    _rule("success-criteria-removed", _D, "A step success criterion was removed; failures may now pass."),
    _rule("success-actions-changed", _D, "An onSuccess / successActions action was added, removed or changed."),
    _rule("failure-actions-changed", _D, "An onFailure / failureActions action was added, removed or changed."),
    # Source descriptions.
    _rule("source-removed", _B, "A source description was removed; steps that call it cannot run."),
    _rule("source-changed", _D, "A source description's URL or type changed."),
    _rule("source-added", _S, "A source description was added."),
    # Documentation.
    _rule("docs-changed", _S, "Only a summary, description, title or example changed.", docs_only=True),
)

#: change_kind -> rule, for the canonical grade of a CTG registry hit.
ARAZZO_RULES_BY_KIND: Dict[str, ArazzoRule] = {rule.change_kind: rule for rule in ARAZZO_RULES}

register_rules(
    TaxonomyRule(
        rule_id=rule.rule_id,
        change_kind=rule.change_kind,
        severity=rule.ctg_severity,  # type: ignore[arg-type]
        summary=rule.summary,
    )
    for rule in ARAZZO_RULES
)


@dataclass(frozen=True)
class ArazzoChange:
    """One thing that moved in an Arazzo document.

    Attributes:
        kind: The raw change kind (``arazzo_<name>``, or ``<key>_changed`` for a key no rule knows).
        pointer: Where it moved, as a JSON Pointer into the Arazzo document
            (``/workflows/<id>/steps/<id>/outputs/<name>``, ``/sourceDescriptions/<name>``, …).
        detail: The human-readable "what", used in the rationale.
        before: The value in the base version (``None`` when added).
        after: The value in the target version (``None`` when removed).
    """

    kind: str
    pointer: str
    detail: str
    before: Any = None
    after: Any = None


def grade(change: ArazzoChange) -> Tuple[Severity, str, str]:
    """Grade one change through the CTG registry.

    Args:
        change: The change to grade.

    Returns:
        ``(severity, rule_id, rationale)``. A kind the registry has no Arazzo rule for is graded
        :attr:`Severity.BREAKING` under ``ctg.unclassified`` (fail-safe).
    """
    registered = rule_for_kind(change.kind)
    rule = ARAZZO_RULES_BY_KIND.get(change.kind) if registered is not None else None
    if rule is None:
        return (
            _B,
            UNCLASSIFIED_RULE_ID,
            f"{change.detail}: no Arazzo rule classifies this change, so it is graded breaking (fail-safe)",
        )
    return rule.severity, rule.rule_id, change.detail


# ===========================================================================
# Helpers
# ===========================================================================

#: Schema keywords that only document an input; a move of these alone is docs-only.
_DOC_KEYS = frozenset({"description", "title", "summary", "example", "examples", "$comment"})


def _canonical(value: Any) -> str:
    """A key-order-independent JSON string of ``value`` for equality tests."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _without_docs(value: Any) -> Any:
    """``value`` with every documentation keyword removed, recursively."""
    if isinstance(value, dict):
        return {k: _without_docs(v) for k, v in value.items() if k not in _DOC_KEYS}
    if isinstance(value, list):
        return [_without_docs(v) for v in value]
    return value


def _token(text: Any) -> str:
    """Escape one JSON Pointer reference token (RFC 6901)."""
    return str(text).replace("~", "~0").replace("/", "~1")


def _resolve_ref(value: Any, components: Mapping[str, Any]) -> Any:
    """Follow a ``{"$ref": "#/components/<section>/<name>"}`` into ``components`` (one hop).

    Args:
        value: A value that may be a local ``$ref``.
        components: The document's ``components`` bag (root ``extras.components``).

    Returns:
        The referenced component, or ``value`` unchanged when it is not a resolvable local ref.
    """
    if not isinstance(value, dict) or not isinstance(value.get("$ref"), str):
        return value
    parts = value["$ref"].split("/")
    if len(parts) != 4 or parts[:2] != ["#", "components"]:
        return value
    section = components.get(parts[2]) if isinstance(components, Mapping) else None
    target = section.get(parts[3]) if isinstance(section, dict) else None
    return target if target is not None else value


def resolve_inputs(inputs: Any, components: Mapping[str, Any]) -> Any:
    """A workflow's ``inputs`` schema with a ``$ref`` to ``components.inputs`` followed."""
    return _resolve_ref(inputs, components)


def _keyed(items: Any, identity) -> Dict[str, Any]:
    """Index a list of mappings by ``identity(item)``, skipping non-mappings."""
    out: Dict[str, Any] = {}
    if not isinstance(items, list):
        return out
    for index, item in enumerate(items):
        if isinstance(item, dict):
            out[identity(item, index)] = item
    return out


def _parameter_identity(param: Dict[str, Any], index: int) -> str:
    """A parameter is the component it references, or its location and name."""
    if isinstance(param.get("reference"), str):
        return param["reference"]
    if param.get("name") is not None:
        location = param.get("in")
        return f"{location}:{param['name']}" if location else str(param["name"])
    return f"#{index}"


def _action_identity(action: Dict[str, Any], index: int) -> str:
    """An action is the component it references, or its name."""
    if isinstance(action.get("reference"), str):
        return action["reference"]
    if action.get("name") is not None:
        return str(action["name"])
    return f"#{index}"


def steps_reordered(before: Any, after: Any) -> bool:
    """Whether the steps both orders share appear in a different relative order.

    Args:
        before: The base ``stepOrder`` list.
        after: The target ``stepOrder`` list.

    Returns:
        ``True`` for a reorder; ``False`` when an added or removed step only shifted the others.
    """
    before_list = before if isinstance(before, list) else []
    after_list = after if isinstance(after, list) else []
    shared = set(before_list) & set(after_list)
    return [s for s in before_list if s in shared] != [s for s in after_list if s in shared]


# ===========================================================================
# Per-concern comparators
# ===========================================================================


def _inputs_changes(pointer: str, before: Any, after: Any) -> List[ArazzoChange]:
    """Compare two (resolved) workflow ``inputs`` JSON Schemas property by property.

    Args:
        pointer: The ``inputs`` pointer (``/workflows/<id>/inputs``).
        before: The base inputs schema, or ``None``.
        after: The target inputs schema, or ``None``.

    Returns:
        One change per input that was added, removed, made required / optional, retyped or
        otherwise changed; a docs-only change when only documentation keywords moved.
    """
    if _canonical(before) == _canonical(after):
        return []
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    b_props = b.get("properties") if isinstance(b.get("properties"), dict) else {}
    a_props = a.get("properties") if isinstance(a.get("properties"), dict) else {}
    b_req = set(b.get("required") or []) if isinstance(b.get("required"), list) else set()
    a_req = set(a.get("required") or []) if isinstance(a.get("required"), list) else set()
    changes: List[ArazzoChange] = []

    def at(name: str) -> str:
        return f"{pointer}/properties/{_token(name)}"

    for name in sorted(set(a_props) - set(b_props)):
        if name in a_req:
            changes.append(
                ArazzoChange(
                    "arazzo_input_required_added",
                    at(name),
                    f"input {name!r} was added as required",
                    None,
                    a_props[name],
                )
            )
        else:
            changes.append(
                ArazzoChange("arazzo_input_added", at(name), f"optional input {name!r} was added", None, a_props[name])
            )
    for name in sorted(set(b_props) - set(a_props)):
        changes.append(
            ArazzoChange("arazzo_input_removed", at(name), f"input {name!r} was removed", b_props[name], None)
        )
    for name in sorted(set(a_props) & set(b_props)):
        b_prop, a_prop = b_props[name], a_props[name]
        if name in a_req and name not in b_req:
            changes.append(
                ArazzoChange("arazzo_input_required_added", at(name), f"input {name!r} is now required", False, True)
            )
        elif name in b_req and name not in a_req:
            changes.append(
                ArazzoChange(
                    "arazzo_input_required_removed", at(name), f"input {name!r} is no longer required", True, False
                )
            )
        b_type = b_prop.get("type") if isinstance(b_prop, dict) else None
        a_type = a_prop.get("type") if isinstance(a_prop, dict) else None
        if _canonical(b_type) != _canonical(a_type):
            changes.append(
                ArazzoChange(
                    "arazzo_input_type_changed",
                    at(name),
                    f"input {name!r} changed type from {b_type!r} to {a_type!r}",
                    b_type,
                    a_type,
                )
            )
            continue
        if _canonical(_without_docs(b_prop)) != _canonical(_without_docs(a_prop)):
            changes.append(
                ArazzoChange("arazzo_inputs_changed", at(name), f"input {name!r} changed its schema", b_prop, a_prop)
            )
        elif _canonical(b_prop) != _canonical(a_prop):
            changes.append(
                ArazzoChange(
                    "arazzo_docs_changed", at(name), f"input {name!r} changed its documentation", b_prop, a_prop
                )
            )
    # Required names with no property of their own (allowed by JSON Schema).
    for name in sorted((a_req - b_req) - set(a_props)):
        changes.append(
            ArazzoChange("arazzo_input_required_added", at(name), f"input {name!r} is now required", False, True)
        )
    for name in sorted((b_req - a_req) - set(b_props)):
        changes.append(
            ArazzoChange(
                "arazzo_input_required_removed", at(name), f"input {name!r} is no longer required", True, False
            )
        )
    # Everything else in the schema (additionalProperties, type, …).
    rest_b = {k: v for k, v in b.items() if k not in ("properties", "required")}
    rest_a = {k: v for k, v in a.items() if k not in ("properties", "required")}
    if _canonical(_without_docs(rest_b)) != _canonical(_without_docs(rest_a)):
        changes.append(ArazzoChange("arazzo_inputs_changed", pointer, "the inputs schema changed", rest_b, rest_a))
    elif _canonical(rest_b) != _canonical(rest_a):
        changes.append(
            ArazzoChange("arazzo_docs_changed", pointer, "the inputs schema changed its documentation", rest_b, rest_a)
        )
    return changes


def _outputs_changes(pointer: str, before: Any, after: Any) -> List[ArazzoChange]:
    """Compare two ``outputs`` maps (output name → runtime expression)."""
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    changes: List[ArazzoChange] = []
    for name in sorted(set(b) | set(a)):
        at = f"{pointer}/{_token(name)}"
        if name not in b:
            changes.append(ArazzoChange("arazzo_output_added", at, f"output {name!r} was added", None, a[name]))
        elif name not in a:
            changes.append(ArazzoChange("arazzo_output_removed", at, f"output {name!r} was removed", b[name], None))
        elif _canonical(b[name]) != _canonical(a[name]):
            changes.append(
                ArazzoChange(
                    "arazzo_output_changed",
                    at,
                    f"output {name!r} changed from {b[name]!r} to {a[name]!r}",
                    b[name],
                    a[name],
                )
            )
    return changes


def _parameters_changes(pointer: str, before: Any, after: Any) -> List[ArazzoChange]:
    """Compare two ``parameters`` lists, pairing parameters by reference or location + name."""
    b = _keyed(before, _parameter_identity)
    a = _keyed(after, _parameter_identity)
    changes: List[ArazzoChange] = []
    for ident in sorted(set(b) | set(a)):
        at = f"{pointer}/{_token(ident)}"
        if ident not in b:
            changes.append(ArazzoChange("arazzo_parameter_added", at, f"parameter {ident!r} was added", None, a[ident]))
        elif ident not in a:
            changes.append(
                ArazzoChange("arazzo_parameter_removed", at, f"parameter {ident!r} was removed", b[ident], None)
            )
        elif _canonical(b[ident]) != _canonical(a[ident]):
            changes.append(
                ArazzoChange("arazzo_parameter_changed", at, f"parameter {ident!r} changed", b[ident], a[ident])
            )
    return changes


def _component_parameters_changes(pointer: str, before: Any, after: Any) -> List[ArazzoChange]:
    """Compare two ``components.parameters`` maps (component name → parameter)."""
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    changes: List[ArazzoChange] = []
    for name in sorted(set(b) | set(a)):
        at = f"{pointer}/{_token(name)}"
        if name not in b:
            changes.append(
                ArazzoChange("arazzo_parameter_added", at, f"parameter component {name!r} was added", None, a[name])
            )
        elif name not in a:
            changes.append(
                ArazzoChange("arazzo_parameter_removed", at, f"parameter component {name!r} was removed", b[name], None)
            )
        elif _canonical(b[name]) != _canonical(a[name]):
            changes.append(
                ArazzoChange("arazzo_parameter_changed", at, f"parameter component {name!r} changed", b[name], a[name])
            )
    return changes


def _criteria_changes(pointer: str, before: Any, after: Any) -> List[ArazzoChange]:
    """Compare two ``successCriteria`` lists as multisets of criteria."""
    b = list(before) if isinstance(before, list) else []
    a = list(after) if isinstance(after, list) else []
    # Pair equal criteria one-for-one; what is left on either side was removed or added.
    removed: List[Any] = list(b)
    added: List[Any] = []
    for criterion in a:
        text = _canonical(criterion)
        match = next((i for i, c in enumerate(removed) if _canonical(c) == text), None)
        if match is None:
            added.append(criterion)
        else:
            removed.pop(match)
    changes: List[ArazzoChange] = []
    for criterion in added:
        changes.append(
            ArazzoChange(
                "arazzo_success_criteria_added",
                pointer,
                f"success criterion {_describe_criterion(criterion)} was added",
                None,
                criterion,
            )
        )
    for criterion in removed:
        changes.append(
            ArazzoChange(
                "arazzo_success_criteria_removed",
                pointer,
                f"success criterion {_describe_criterion(criterion)} was removed",
                criterion,
                None,
            )
        )
    return changes


def _describe_criterion(criterion: Any) -> str:
    """A criterion's condition, quoted, for a rationale."""
    if isinstance(criterion, dict) and criterion.get("condition") is not None:
        return repr(criterion["condition"])
    return repr(criterion)


def _actions_changes(kind: str, label: str, pointer: str, before: Any, after: Any) -> List[ArazzoChange]:
    """Compare two action lists (``onSuccess`` / ``onFailure`` / ``successActions`` / ``failureActions``).

    Args:
        kind: The change kind every action move gets (success or failure actions).
        label: The list's name for the rationale.
        pointer: The list's pointer.
        before: The base list.
        after: The target list.

    Returns:
        One change per action added, removed or changed (paired by reference or name).
    """
    b = _keyed(before, _action_identity)
    a = _keyed(after, _action_identity)
    changes: List[ArazzoChange] = []
    for ident in sorted(set(b) | set(a)):
        at = f"{pointer}/{_token(ident)}"
        if ident not in b:
            changes.append(ArazzoChange(kind, at, f"{label} action {ident!r} was added", None, a[ident]))
        elif ident not in a:
            changes.append(ArazzoChange(kind, at, f"{label} action {ident!r} was removed", b[ident], None))
        elif _canonical(b[ident]) != _canonical(a[ident]):
            changes.append(ArazzoChange(kind, at, f"{label} action {ident!r} changed", b[ident], a[ident]))
    return changes


def _component_actions_changes(kind: str, label: str, pointer: str, before: Any, after: Any) -> List[ArazzoChange]:
    """Compare two ``components.successActions`` / ``failureActions`` maps (name → action)."""
    b = before if isinstance(before, dict) else {}
    a = after if isinstance(after, dict) else {}
    changes: List[ArazzoChange] = []
    for name in sorted(set(b) | set(a)):
        if _canonical(b.get(name)) != _canonical(a.get(name)):
            verb = "added" if name not in b else "removed" if name not in a else "changed"
            changes.append(
                ArazzoChange(
                    kind,
                    f"{pointer}/{_token(name)}",
                    f"{label} component {name!r} was {verb}",
                    b.get(name),
                    a.get(name),
                )
            )
    return changes


def _plain_change(kind: str, pointer: str, label: str, before: Any, after: Any) -> List[ArazzoChange]:
    """One change of ``kind`` when ``before`` and ``after`` differ."""
    if _canonical(before) == _canonical(after):
        return []
    return [ArazzoChange(kind, pointer, f"{label} changed", before, after)]


def _unknown(pointer: str, owner: str, key: str, before: Any, after: Any) -> List[ArazzoChange]:
    """A change to a key no rule knows: kind ``<key>_changed``, which the registry fails safe on."""
    if _canonical(before) == _canonical(after):
        return []
    return [ArazzoChange(f"{key}_changed", f"{pointer}/{_token(key)}", f"{owner} changed {key!r}", before, after)]


def _moved_keys(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[str]:
    """The keys whose values differ between two mappings, sorted."""
    return sorted(k for k in set(before) | set(after) if _canonical(before.get(k)) != _canonical(after.get(k)))


# ===========================================================================
# Enumerators
# ===========================================================================

#: Workflow extras that never grade on their own: identity, and declaration position.
_WORKFLOW_IGNORED = frozenset({"workflowId", "workflowIndex"})
#: Step extras that never grade on their own: identity, position (graded by `stepOrder`), and the
#: source link / async marker derived from the step's target.
_STEP_IGNORED = frozenset({"stepId", "stepIndex", "sourceDescription", "sourceType", "asyncStep"})
#: The step fields that name what the step calls.
_STEP_TARGETS = ("operationId", "operationRef", "operationPath", "workflowId", "channelPath")


def workflow_changes(
    workflow_id: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    base_components: Mapping[str, Any],
    target_components: Mapping[str, Any],
) -> List[ArazzoChange]:
    """Enumerate what moved in one workflow's ``extras``.

    Args:
        workflow_id: The workflow's id (for pointers and rationales).
        before: The workflow's base ``extras``.
        after: The workflow's target ``extras``.
        base_components: The base document's ``components`` (to resolve an inputs ``$ref``).
        target_components: The target document's ``components``.

    Returns:
        The changes, in key order; a key no rule knows yields a fail-safe ``<key>_changed`` change.
    """
    pointer = f"/workflows/{_token(workflow_id)}"
    owner = f"workflow {workflow_id!r}"
    keys = set(before) | set(after)
    changes: List[ArazzoChange] = []
    # Inputs are compared resolved, so they are checked even when the `$ref` itself did not move.
    changes += _inputs_changes(
        f"{pointer}/inputs",
        resolve_inputs(before.get("inputs"), base_components),
        resolve_inputs(after.get("inputs"), target_components),
    )
    for key in sorted(keys - _WORKFLOW_IGNORED - {"inputs"}):
        b, a = before.get(key), after.get(key)
        if _canonical(b) == _canonical(a):
            continue
        if key == "stepOrder":
            if steps_reordered(b, a):
                changes.append(
                    ArazzoChange(
                        "arazzo_step_reorder",
                        f"{pointer}/steps",
                        f"{owner} step order changed; execution sequence may differ",
                        b,
                        a,
                    )
                )
            else:
                changes.append(
                    ArazzoChange(
                        "arazzo_step_order_shifted",
                        f"{pointer}/steps",
                        f"{owner} added or removed a step; the other steps keep their order",
                        b,
                        a,
                    )
                )
        elif key == "outputs":
            changes += _outputs_changes(f"{pointer}/outputs", b, a)
        elif key == "parameters":
            changes += _parameters_changes(f"{pointer}/parameters", b, a)
        elif key == "successActions":
            changes += _actions_changes(
                "arazzo_success_actions_changed", "successActions", f"{pointer}/successActions", b, a
            )
        elif key == "failureActions":
            changes += _actions_changes(
                "arazzo_failure_actions_changed", "failureActions", f"{pointer}/failureActions", b, a
            )
        elif key == "dependsOn":
            changes += _plain_change("arazzo_depends_on_changed", f"{pointer}/dependsOn", f"{owner} dependsOn", b, a)
        elif key == "summary":
            changes += _plain_change("arazzo_docs_changed", f"{pointer}/summary", f"{owner} summary", b, a)
        else:
            changes += _unknown(pointer, owner, key, b, a)
    return changes


def step_changes(step_key: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> List[ArazzoChange]:
    """Enumerate what moved in one step's ``extras``.

    Args:
        step_key: The step's canonical key (``<workflowId>#<stepId>``).
        before: The step's base ``extras``.
        after: The step's target ``extras``.

    Returns:
        The changes; a key no rule knows yields a fail-safe ``<key>_changed`` change.
    """
    workflow_id, _, step_id = step_key.partition("#")
    pointer = f"/workflows/{_token(workflow_id)}/steps/{_token(step_id or step_key)}"
    owner = f"step {step_key!r}"
    changes: List[ArazzoChange] = []
    target_moved = any(_canonical(before.get(k)) != _canonical(after.get(k)) for k in _STEP_TARGETS)
    if target_moved:
        b_target = {k: before[k] for k in _STEP_TARGETS if k in before}
        a_target = {k: after[k] for k in _STEP_TARGETS if k in after}
        changes.append(
            ArazzoChange(
                "arazzo_step_target_changed",
                pointer,
                f"{owner} now calls {a_target or 'nothing'} instead of {b_target or 'nothing'}",
                b_target,
                a_target,
            )
        )
    for key in _moved_keys(before, after):
        if key in _STEP_IGNORED or key in _STEP_TARGETS:
            continue
        b, a = before.get(key), after.get(key)
        if key == "outputs":
            changes += _outputs_changes(f"{pointer}/outputs", b, a)
        elif key == "parameters":
            changes += _parameters_changes(f"{pointer}/parameters", b, a)
        elif key == "successCriteria":
            changes += _criteria_changes(f"{pointer}/successCriteria", b, a)
        elif key == "onSuccess":
            changes += _actions_changes("arazzo_success_actions_changed", "onSuccess", f"{pointer}/onSuccess", b, a)
        elif key == "onFailure":
            changes += _actions_changes("arazzo_failure_actions_changed", "onFailure", f"{pointer}/onFailure", b, a)
        elif key in ("requestBody", "request"):
            changes += _plain_change("arazzo_request_body_changed", f"{pointer}/{key}", f"{owner} {key}", b, a)
        elif key == "dependsOn":
            changes += _plain_change("arazzo_depends_on_changed", f"{pointer}/dependsOn", f"{owner} dependsOn", b, a)
        else:
            changes += _unknown(pointer, owner, key, b, a)
    return changes


#: Root extras that never grade: the version marker, values derived from `sourceDescriptions`, and
#: documentation. `components.inputs` is graded through the workflows that reference it.
_ROOT_IGNORED = frozenset({"arazzo", "sourceTypes", "asyncSources"})
_ROOT_DOCS = frozenset({"infoSummary", "self"})


def _source_changes(before: Any, after: Any) -> List[ArazzoChange]:
    """Compare two ``sourceDescriptions`` lists, pairing sources by name."""
    b = _keyed(before, lambda item, index: str(item.get("name") or f"#{index}"))
    a = _keyed(after, lambda item, index: str(item.get("name") or f"#{index}"))
    changes: List[ArazzoChange] = []
    for name in sorted(set(b) | set(a)):
        at = f"/sourceDescriptions/{_token(name)}"
        if name not in b:
            changes.append(
                ArazzoChange("arazzo_source_added", at, f"source description {name!r} was added", None, a[name])
            )
        elif name not in a:
            changes.append(
                ArazzoChange("arazzo_source_removed", at, f"source description {name!r} was removed", b[name], None)
            )
        elif _canonical(b[name]) != _canonical(a[name]):
            moved = _moved_keys(b[name], a[name])
            changes.append(
                ArazzoChange(
                    "arazzo_source_changed",
                    at,
                    f"source description {name!r} changed {', '.join(moved)}",
                    b[name],
                    a[name],
                )
            )
    return changes


def root_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[ArazzoChange]:
    """Enumerate what moved in the document root's ``extras``: source descriptions and components.

    Args:
        before: The base model's root ``extras``.
        after: The target model's root ``extras``.

    Returns:
        The changes; a root key or components section no rule knows yields a fail-safe change.
    """
    changes: List[ArazzoChange] = []
    for key in _moved_keys(before, after):
        if key in _ROOT_IGNORED:
            continue
        b, a = before.get(key), after.get(key)
        if key == "sourceDescriptions":
            changes += _source_changes(b, a)
        elif key == "components":
            changes += _components_changes(b if isinstance(b, dict) else {}, a if isinstance(a, dict) else {})
        elif key in _ROOT_DOCS:
            changes += _plain_change("arazzo_docs_changed", f"/{key}", f"document {key}", b, a)
        else:
            changes += _unknown("", "the document", key, b, a)
    return changes


def _components_changes(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[ArazzoChange]:
    """Compare two ``components`` bags section by section (``inputs`` is graded per workflow)."""
    changes: List[ArazzoChange] = []
    for section in _moved_keys(before, after):
        b, a = before.get(section), after.get(section)
        pointer = f"/components/{_token(section)}"
        if section == "inputs":
            continue
        if section == "parameters":
            changes += _component_parameters_changes(pointer, b, a)
        elif section == "successActions":
            changes += _component_actions_changes("arazzo_success_actions_changed", "successActions", pointer, b, a)
        elif section == "failureActions":
            changes += _component_actions_changes("arazzo_failure_actions_changed", "failureActions", pointer, b, a)
        else:
            changes += _unknown("/components", "components", section, b, a)
    return changes


def worst_of(changes: Iterable[ArazzoChange]) -> Optional[Tuple[Severity, str, str]]:
    """Grade ``changes`` and return the worst grade, with every rationale joined.

    Args:
        changes: The changes to grade.

    Returns:
        ``(severity, rule_id, rationale)`` where the rule is the first worst-graded change's and
        the rationale lists every change with its rule id; ``None`` when ``changes`` is empty.
    """
    graded = [grade(change) for change in changes]
    if not graded:
        return None
    rank = {_S: 0, _D: 1, _B: 2}
    worst = max(graded, key=lambda g: rank[g[0]])
    if len(graded) == 1:
        return worst
    rationale = "; ".join(f"{text} [{rule_id}]" for _, rule_id, text in graded)
    return worst[0], worst[1], rationale
