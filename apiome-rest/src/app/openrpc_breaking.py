"""OpenRPC breaking-change classifier — MFI-19.1 (#3979).

A JSON-RPC 2.0 call passes its parameters **by position** (an array) or **by name** (an
object), and an OpenRPC method says which with ``paramStructure`` (``by-position``,
``by-name``, or ``either`` — the default). The normalizer keeps every method's parameters, in
order, on the request message as ``extras["openrpc_params"]``, so the format-agnostic baseline
(:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) sees a parameter change only as
"the request message's extras moved" and grades it *dangerous* whatever it was. This classifier
reads the two parameter lists and grades what actually happened:

======================================  ===========  =========================================
Rule                                    Severity     When
======================================  ===========  =========================================
``openrpc.param-removed``               breaking     a parameter is gone
``openrpc.required-param-added``        breaking     a new required parameter
``openrpc.optional-param-added``        safe         a new optional parameter after the others
``openrpc.param-moved``                 breaking     a parameter changed position (safe when the
                                                     method is ``by-name``)
``openrpc.param-renamed``               breaking     same position and schema, new name (safe
                                                     when the method is ``by-position``)
``openrpc.made-required``               breaking     an optional parameter became required
``openrpc.made-optional``               safe         a required parameter became optional
``openrpc.param-schema-changed``        dangerous    a parameter's schema changed
``openrpc.param-structure-narrowed``    breaking     ``paramStructure`` no longer allows a call
                                                     style it allowed
``openrpc.param-structure-widened``     safe         ``paramStructure`` became ``either``
======================================  ===========  =========================================

A method's result is a response message, so result changes keep the baseline's grading, as do
methods added or removed and every change this classifier does not recognise.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity, _worst
from .canonical_model import CanonicalApi, MessageRole
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["OpenRpcBreakingChangeClassifier"]

_FORMAT_KEY = "openrpc"

#: ``paramStructure`` values and the call styles each allows.
_CALL_STYLES = {
    "by-name": frozenset({"by-name"}),
    "by-position": frozenset({"by-position"}),
    "either": frozenset({"by-name", "by-position"}),
}

#: A grade: ``(severity, rule_id, rationale)``.
Grade = Tuple[Severity, str, str]


def _extras(projection: Any) -> Mapping[str, Any]:
    """The ``extras`` of an entity self-projection dict (``{}`` when absent)."""
    if not isinstance(projection, dict):
        return {}
    extras = projection.get("extras")
    return extras if isinstance(extras, dict) else {}


def _params(projection: Any) -> List[Dict[str, Any]]:
    """The ordered ``openrpc_params`` of a request message's self-projection."""
    return [p for p in _extras(projection).get("openrpc_params") or [] if isinstance(p, dict) and p.get("name")]


def _structure(value: Any) -> str:
    """A ``paramStructure`` value, defaulting to the spec's ``either``."""
    return value if value in _CALL_STYLES else "either"


def _method_structure(api: CanonicalApi, message_key: str) -> str:
    """The ``paramStructure`` of the method that owns ``message_key`` in ``api``."""
    for service in api.services:
        for operation in service.operations:
            if any(message.key == message_key for message in operation.messages):
                return _structure(operation.extras.get("openrpc_param_structure"))
    return "either"


def grade_params(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
    *,
    structure: str,
) -> List[Grade]:
    """Grade every difference between two ordered parameter lists.

    Args:
        before: The method's parameters in the base model (``openrpc_params`` entries).
        after: The method's parameters in the target model.
        structure: The target method's ``paramStructure`` (``by-name`` / ``by-position`` /
            ``either``), which decides whether position and name matter.

    Returns:
        One grade per difference, in parameter order; empty when the lists are equivalent.
    """
    by_name_only = structure == "by-name"
    by_position_only = structure == "by-position"
    old = {p["name"]: (i, p) for i, p in enumerate(before)}
    new = {p["name"]: (i, p) for i, p in enumerate(after)}
    grades: List[Grade] = []
    renamed_old: set = set()
    renamed_new: set = set()

    # A parameter that kept its position and schema under a new name is a rename.
    for name, (index, param) in old.items():
        if name in new or index >= len(after):
            continue
        candidate = after[index]
        if candidate["name"] not in old and candidate.get("schema") == param.get("schema"):
            renamed_old.add(name)
            renamed_new.add(candidate["name"])
            severity = Severity.SAFE if by_position_only else Severity.BREAKING
            grades.append(
                (
                    severity,
                    "openrpc.param-renamed",
                    f"parameter {name!r} was renamed to {candidate['name']!r}; "
                    + (
                        "the method is by-position, so callers are unaffected"
                        if by_position_only
                        else "callers passing parameters by name send the old name"
                    ),
                )
            )

    for name in old:
        if name not in new and name not in renamed_old:
            grades.append(
                (
                    Severity.BREAKING,
                    "openrpc.param-removed",
                    f"parameter {name!r} was removed; callers that send it are rejected or "
                    "shift the positions of the parameters after it",
                )
            )

    for name, (index, param) in new.items():
        if name in old or name in renamed_new:
            continue
        if param.get("required") is True:
            grades.append(
                (
                    Severity.BREAKING,
                    "openrpc.required-param-added",
                    f"required parameter {name!r} was added; existing callers never send it",
                )
            )
        elif index >= len(before):
            grades.append(
                (
                    Severity.SAFE,
                    "openrpc.optional-param-added",
                    f"optional parameter {name!r} was added after the existing parameters; "
                    "existing callers are unaffected",
                )
            )
        # An optional parameter inserted before existing ones is graded by the moves below.

    for name, (old_index, old_param) in old.items():
        if name not in new:
            continue
        new_index, new_param = new[name]
        if old_index != new_index:
            grades.append(
                (
                    Severity.SAFE if by_name_only else Severity.BREAKING,
                    "openrpc.param-moved",
                    f"parameter {name!r} moved from position {old_index} to {new_index}; "
                    + (
                        "the method is by-name, so callers are unaffected"
                        if by_name_only
                        else "callers passing parameters by position send the wrong value"
                    ),
                )
            )
        was_required, is_required = old_param.get("required") is True, new_param.get("required") is True
        if is_required and not was_required:
            grades.append(
                (
                    Severity.BREAKING,
                    "openrpc.made-required",
                    f"parameter {name!r} became required; callers that omit it are rejected",
                )
            )
        elif was_required and not is_required:
            grades.append(
                (
                    Severity.SAFE,
                    "openrpc.made-optional",
                    f"parameter {name!r} is no longer required; existing callers still send it",
                )
            )
        if old_param.get("schema") != new_param.get("schema"):
            grades.append(
                (
                    Severity.DANGEROUS,
                    "openrpc.param-schema-changed",
                    f"parameter {name!r} changed its schema; review whether existing values still validate",
                )
            )
    return grades


def grade_structure(before: Any, after: Any) -> Optional[Grade]:
    """Grade a ``paramStructure`` change, or ``None`` when the allowed call styles are unchanged.

    Args:
        before: The base method's ``paramStructure`` (``None`` = ``either``).
        after: The target method's ``paramStructure``.

    Returns:
        ``param-structure-narrowed`` (breaking) when a call style was dropped,
        ``param-structure-widened`` (safe) when only styles were added, else ``None``.
    """
    old, new = _structure(before), _structure(after)
    dropped = _CALL_STYLES[old] - _CALL_STYLES[new]
    if dropped:
        return (
            Severity.BREAKING,
            "openrpc.param-structure-narrowed",
            f"paramStructure changed from {old!r} to {new!r}; callers passing parameters "
            f"{' / '.join(sorted(dropped))} are rejected",
        )
    if old != new:
        return (
            Severity.SAFE,
            "openrpc.param-structure-widened",
            f"paramStructure changed from {old!r} to {new!r}; every existing call style still works",
        )
    return None


def _combine(grades: Sequence[Grade]) -> Grade:
    """The worst of several grades, its rule id first and every rationale kept."""
    worst = _worst([severity for severity, _, _ in grades])
    rule_id = next(rule for severity, rule, _ in grades if severity is worst)
    return worst, rule_id, "; ".join(rationale for _, _, rationale in grades)


class OpenRpcBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an OpenRPC diff by parameter position, name and requiredness (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "openrpc-params"

    def classify_change(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> ChangeClassification:
        """Grade one change; changes this classifier does not recognise use the baseline."""
        graded: Optional[Grade] = None
        if change.category is EntityCategory.MESSAGE:
            graded = self._grade_request(change, base, target)
        elif change.category is EntityCategory.OPERATION and change.kind is ChangeKind.MODIFIED:
            graded = self._grade_operation(change)
        if graded is None:
            return super().classify_change(change, base, target)
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
    def _grade_request(change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Grade]:
        """Grade a request-message change from its parameter lists, or ``None`` for the baseline."""
        projections = [p for p in (change.before, change.after) if isinstance(p, dict)]
        if not projections or any(p.get("role") != MessageRole.REQUEST.value for p in projections):
            return None
        if change.kind is ChangeKind.MODIFIED and {f.field for f in change.fields} - {"extras", "payload"}:
            # Something besides the parameters moved; the baseline grades the whole message.
            return None
        model = base if change.kind is ChangeKind.REMOVED else target
        grades = grade_params(
            _params(change.before),
            _params(change.after),
            structure=_method_structure(model, change.key),
        )
        return _combine(grades) if grades else None

    @staticmethod
    def _grade_operation(change: EntityChange) -> Optional[Grade]:
        """Grade a method whose only move is its ``paramStructure``, or ``None`` for the baseline."""
        if {f.field for f in change.fields} != {"extras"}:
            return None
        before, after = dict(_extras(change.before)), dict(_extras(change.after))
        old = before.pop("openrpc_param_structure", None)
        new = after.pop("openrpc_param_structure", None)
        if before != after:
            return None
        return grade_structure(old, new)
