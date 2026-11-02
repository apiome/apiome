"""CORBA / OMG IDL breaking-change classifier — MFI-21.4 (#3994).

A CORBA client invokes an operation by **name** in a GIOP request, and CDR encodes the request's
``in`` / ``inout`` parameters, the reply's return value and ``out`` / ``inout`` parameters, and
every struct and exception **positionally** with no tags or lengths (CORBA 3.4 Part 2 §9.3).
An enum travels as its **ordinal**. So almost every structural change is breaking, and the
format-agnostic baseline (:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) — which
sees a multi-parameter signature only as a folded blob — is sharpened here:

=========================================  ===========  ==========================================
Rule                                       Severity     When
=========================================  ===========  ==========================================
``corbaidl.parameter-added``               breaking     an operation gained a parameter
``corbaidl.parameter-removed``             breaking     an operation lost a parameter
``corbaidl.parameter-type-changed``        breaking     a parameter's type changed (by position)
``corbaidl.parameter-direction-changed``   breaking     a parameter's ``in`` / ``out`` / ``inout``
                                                        changed: it moved between request and reply
``corbaidl.parameter-renamed``             safe         only a parameter's name changed: names are
                                                        not on the wire
``corbaidl.return-type-changed``           breaking     the return type changed
``corbaidl.oneway-changed``                breaking     an operation became, or stopped being,
                                                        ``oneway``: one side waits for a reply the
                                                        other never sends
``corbaidl.raises-added``                  dangerous    an operation may raise a new exception: an
                                                        old client receives it as ``CORBA::UNKNOWN``
``corbaidl.raises-removed``                safe         an operation no longer raises an exception
``corbaidl.member-added``                  breaking     a struct / exception gained a member: old
                                                        readers misread every byte after it
``corbaidl.member-removed``                breaking     a struct / exception lost a member
``corbaidl.member-reordered``              breaking     members changed relative order
``corbaidl.member-shifted``                safe         a member moved only because another was
                                                        added or removed (graded there)
``corbaidl.member-type-changed``           breaking     a member's type changed
``corbaidl.bound-narrowed``                breaking     a ``string<N>`` / ``sequence<T, N>`` bound
                                                        shrank: old senders overflow it
``corbaidl.bound-widened``                 dangerous    a bound grew or was dropped: old receivers
                                                        reject the longer values
``corbaidl.enumerator-removed``            breaking     an enumerator is gone
``corbaidl.enumerator-inserted``           breaking     an enumerator was added before the end:
                                                        every later ordinal shifts
``corbaidl.enumerator-reordered``          breaking     enumerators changed order
``corbaidl.enumerator-appended``           dangerous    an enumerator was added at the end: old
                                                        receivers cannot decode the new ordinal
``corbaidl.kind-changed``                  breaking     a struct became an exception or back
``corbaidl.base-removed``                  breaking     an interface no longer inherits from a base
``corbaidl.base-added``                    safe         an interface gained a base
=========================================  ===========  ==========================================

Added operations, interfaces and types are safe and removed ones breaking, per the baseline.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    Severity,
    _worst,
    relative_field_order_changed,
)
from .canonical_model import CanonicalApi
from .corbaidl_normalizer import member_sources
from .diff import ChangeKind, EntityCategory, EntityChange
from .normalizer import Keys

__all__ = ["CorbaIdlBreakingChangeClassifier", "grade_signature", "operation_signatures"]

_FORMAT_KEY = "corbaidl"
_PREFIX = "corbaidl"

#: A grade: ``(severity, rule_id, rationale)``.
Grade = Tuple[Severity, str, str]


def _combine(grades: Sequence[Grade]) -> Grade:
    """The worst of several grades, its rule id first and every rationale kept."""
    worst = _worst([severity for severity, _, _ in grades])
    rule_id = next(rule for severity, rule, _ in grades if severity is worst)
    return worst, rule_id, "; ".join(rationale for _, _, rationale in grades)


def operation_signatures(api: CanonicalApi) -> Dict[str, Mapping[str, Any]]:
    """Operation key → its declared signature, for every operation of every interface.

    Inherited operations and attribute accessors (``_get_x`` / ``_set_x``) are included, under the
    derived interface's key, exactly as the normalizer flattened them.

    Args:
        api: A normalized CORBA IDL model.

    Returns:
        ``{operation key: {"name", "return_type", "parameters", "raises", "oneway"?}}``.
    """
    listed = api.extras.get("corbaidl_interfaces")
    by_name = {str(e.get("name")): e for e in listed or [] if isinstance(e, Mapping)}
    found: Dict[str, Mapping[str, Any]] = {}
    for service in api.services:
        entry = by_name.get(service.name)
        if entry is None:
            continue
        sources = {str(op["name"]): op for op in member_sources(entry)}
        for member, base in (service.extras.get("corbaidl_inherited") or {}).items():
            for op in member_sources(by_name.get(base) or {}):
                if op["name"] == member:
                    sources.setdefault(member, op)
        for name, op in sources.items():
            found[Keys.operation_rpc(service.key, name)] = op
    return found


def grade_signature(before: Mapping[str, Any], after: Mapping[str, Any]) -> List[Grade]:
    """Grade two signatures of one operation, parameters compared by position.

    Args:
        before: The base signature (an entry of :func:`operation_signatures`).
        after: The target signature.

    Returns:
        One grade per difference (empty when the signatures are wire-identical and equally named).
    """
    name = after.get("name")
    grades: List[Grade] = []
    if bool(before.get("oneway")) != bool(after.get("oneway")):
        now = "oneway" if after.get("oneway") else "two-way"
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.oneway-changed",
                f"{name!r} is now {now}; one side waits for a reply the other never sends",
            )
        )
    if (before.get("return_type") or "void") != (after.get("return_type") or "void"):
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.return-type-changed",
                f"{name!r} returns {after.get('return_type')} instead of {before.get('return_type')}",
            )
        )
    old = list(before.get("parameters") or [])
    new = list(after.get("parameters") or [])
    for index in range(max(len(old), len(new))):
        was = old[index] if index < len(old) else None
        now = new[index] if index < len(new) else None
        if was is None:
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.parameter-added",
                    f"{name!r} gained parameter {now.get('name')!r} at position {index + 1}; CDR is positional",
                )
            )
        elif now is None:
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.parameter-removed",
                    f"{name!r} lost parameter {was.get('name')!r} at position {index + 1}",
                )
            )
        else:
            grades.extend(_grade_parameter(str(name), index, was, now))
    old_raises, new_raises = list(before.get("raises") or []), list(after.get("raises") or [])
    added = [r for r in new_raises if r not in old_raises]
    removed = [r for r in old_raises if r not in new_raises]
    if added:
        grades.append(
            (
                Severity.DANGEROUS,
                f"{_PREFIX}.raises-added",
                f"{name!r} may now raise {', '.join(added)}; an old client receives it as CORBA::UNKNOWN",
            )
        )
    if removed:
        grades.append((Severity.SAFE, f"{_PREFIX}.raises-removed", f"{name!r} no longer raises {', '.join(removed)}"))
    return grades


def _grade_parameter(name: str, index: int, was: Mapping[str, Any], now: Mapping[str, Any]) -> List[Grade]:
    """Grade one parameter position present on both sides."""
    grades: List[Grade] = []
    position = f"parameter {index + 1} ({now.get('name')!r}) of {name!r}"
    if was.get("type") != now.get("type"):
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.parameter-type-changed",
                f"{position} is {now.get('type')} instead of {was.get('type')}",
            )
        )
    if (was.get("direction") or "in") != (now.get("direction") or "in"):
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.parameter-direction-changed",
                f"{position} is {now.get('direction')} instead of {was.get('direction')}; it moved between "
                "request and reply",
            )
        )
    if not grades and was.get("name") != now.get("name"):
        grades.append(
            (
                Severity.SAFE,
                f"{_PREFIX}.parameter-renamed",
                f"parameter {index + 1} of {name!r} was renamed {was.get('name')!r} → {now.get('name')!r}; "
                "names are not on the wire",
            )
        )
    return grades


def _grade_error_message(change: EntityChange) -> Optional[Grade]:
    """A ``raises`` exception added or removed (its error message appeared or went)."""
    exception = change.key.split("#error.", 1)[1]
    operation = change.key.split("#", 1)[0]
    if change.kind is ChangeKind.ADDED:
        return (
            Severity.DANGEROUS,
            f"{_PREFIX}.raises-added",
            f"{operation!r} may now raise {exception}; an old client receives it as CORBA::UNKNOWN",
        )
    if change.kind is ChangeKind.REMOVED:
        return (Severity.SAFE, f"{_PREFIX}.raises-removed", f"{operation!r} no longer raises {exception}")
    return None


def _bounds(projection: Any) -> Tuple[Optional[int], Optional[int]]:
    constraints = projection.get("constraints") if isinstance(projection, Mapping) else None
    constraints = constraints if isinstance(constraints, Mapping) else {}
    return constraints.get("max_length"), constraints.get("max_items")


def _grade_bound(member: str, before: Any, after: Any) -> Optional[Grade]:
    """A ``string<N>`` / ``sequence<T, N>`` bound that moved."""
    for was, now in zip(_bounds(before), _bounds(after)):
        if was == now:
            continue
        if now is not None and (was is None or now < was):
            return (
                Severity.BREAKING,
                f"{_PREFIX}.bound-narrowed",
                f"member {member!r} is bounded to {now} (was {was or 'unbounded'}); old senders overflow it",
            )
        return (
            Severity.DANGEROUS,
            f"{_PREFIX}.bound-widened",
            f"member {member!r} is bounded to {now or 'unbounded'} (was {was}); old receivers reject longer values",
        )
    return None


def _grade_member(change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Grade]:
    """Grade a struct / exception member change, or ``None`` for the baseline."""
    name = change.key.rsplit(".", 1)[-1]
    if change.kind is ChangeKind.ADDED:
        return (
            Severity.BREAKING,
            f"{_PREFIX}.member-added",
            f"member {name!r} was added; CDR carries no tags, so old readers misread everything after it",
        )
    if change.kind is ChangeKind.REMOVED:
        return (Severity.BREAKING, f"{_PREFIX}.member-removed", f"member {name!r} was removed")
    moved = {f.field for f in change.fields}
    if not moved or not moved <= {"type", "field_number", "constraints", "extras"}:
        return None
    grades: List[Grade] = []
    before_type = (change.before or {}).get("type") if isinstance(change.before, Mapping) else None
    after_type = (change.after or {}).get("type") if isinstance(change.after, Mapping) else None
    before_expr = ((change.before or {}).get("extras") or {}).get("corbaidl_type_expr")
    after_expr = ((change.after or {}).get("extras") or {}).get("corbaidl_type_expr")
    bound = _grade_bound(name, change.before, change.after) if "constraints" in moved else None
    if before_type != after_type or (before_expr != after_expr and bound is None):
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.member-type-changed",
                f"member {name!r} is {after_expr or after_type} instead of {before_expr or before_type}",
            )
        )
    if bound is not None:
        grades.append(bound)
    if "field_number" in moved:
        if relative_field_order_changed(base, target, change.key):
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.member-reordered",
                    f"member {name!r} moved relative to the others; CDR reads members in order",
                )
            )
        else:
            grades.append(
                (
                    Severity.SAFE,
                    f"{_PREFIX}.member-shifted",
                    f"member {name!r} shifted because another member was added or removed (graded there)",
                )
            )
    return _combine(grades) if grades else None


def _grade_type(change: EntityChange) -> Optional[Grade]:
    """Grade an enum's enumerators or a struct ↔ exception move, or ``None`` for the baseline."""
    moved = {f.field for f in change.fields}
    if moved == {"extras"}:
        before = ((change.before or {}).get("extras") or {}).get("corbaidl_kind")
        after = ((change.after or {}).get("extras") or {}).get("corbaidl_kind")
        if before != after:
            return (Severity.BREAKING, f"{_PREFIX}.kind-changed", f"{change.key!r} is now a {after} (was a {before})")
        return None
    if "enum_values" not in moved or not moved <= {"enum_values", "extras"}:
        return None
    field = next(f for f in change.fields if f.field == "enum_values")
    old = [str(v.get("name")) for v in field.before or [] if isinstance(v, Mapping)]
    new = [str(v.get("name")) for v in field.after or [] if isinstance(v, Mapping)]
    grades: List[Grade] = []
    removed = [v for v in old if v not in new]
    if removed:
        grades.append(
            (Severity.BREAKING, f"{_PREFIX}.enumerator-removed", f"enum {change.key!r} lost {', '.join(removed)}")
        )
    kept_old = [v for v in old if v in new]
    kept_new = [v for v in new if v in old]
    if kept_old != kept_new:
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.enumerator-reordered",
                f"enum {change.key!r} reordered its enumerators; their ordinals moved",
            )
        )
    added = [v for v in new if v not in old]
    if added:
        tail = new[len(new) - len(added) :] == added and not removed and kept_old == kept_new
        if tail:
            grades.append(
                (
                    Severity.DANGEROUS,
                    f"{_PREFIX}.enumerator-appended",
                    f"enum {change.key!r} gained {', '.join(added)} at the end; old receivers cannot decode it",
                )
            )
        else:
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.enumerator-inserted",
                    f"enum {change.key!r} gained {', '.join(added)} before the end; later ordinals shift",
                )
            )
    return _combine(grades) if grades else None


def _grade_service(change: EntityChange) -> Optional[Grade]:
    """Grade an interface whose only move is its base list (inherited operations grade on their own)."""
    if {f.field for f in change.fields} != {"extras"}:
        return None
    before = (change.before or {}).get("extras") or {}
    after = (change.after or {}).get("extras") or {}
    old, new = list(before.get("corbaidl_bases") or []), list(after.get("corbaidl_bases") or [])
    if old == new:
        return None  # only the inherited map moved; each operation that moved is graded on its own
    removed = [b for b in old if b not in new]
    if removed:
        return (
            Severity.BREAKING,
            f"{_PREFIX}.base-removed",
            f"{change.key!r} no longer inherits from {', '.join(removed)}; it no longer narrows to it",
        )
    added = [b for b in new if b not in old]
    return (
        Severity.SAFE,
        f"{_PREFIX}.base-added",
        f"{change.key!r} now also inherits from {', '.join(added) or 'its bases'}",
    )


class CorbaIdlBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a CORBA IDL diff with GIOP / CDR semantics (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "corbaidl-giop"

    def classify_change(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> ChangeClassification:
        """Grade one change; changes this classifier does not recognise use the baseline.

        Args:
            change: The diff change to grade.
            base: The "from" model.
            target: The "to" model.

        Returns:
            The change's classification.
        """
        graded = self._grade_corba(change, base, target)
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

    def _grade_corba(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Grade]:
        """The CORBA grade of one change, or ``None`` to fall back to the baseline."""
        if change.category is EntityCategory.FIELD:
            return _grade_member(change, base, target)
        if change.category is EntityCategory.TYPE and change.kind is ChangeKind.MODIFIED:
            return _grade_type(change)
        if change.category is EntityCategory.SERVICE and change.kind is ChangeKind.MODIFIED:
            return _grade_service(change)
        if change.category is EntityCategory.MESSAGE and "#error." in change.key:
            return _grade_error_message(change)
        if change.category in (EntityCategory.OPERATION, EntityCategory.MESSAGE):
            operation = change.key.split("#", 1)[0]
            if change.category is EntityCategory.OPERATION and change.kind is not ChangeKind.MODIFIED:
                return None
            before = operation_signatures(base).get(operation)
            after = operation_signatures(target).get(operation)
            if before is None or after is None:
                return None
            grades = [g for g in grade_signature(before, after) if not g[1].startswith(f"{_PREFIX}.raises-")]
            return _combine(grades) if grades else None
        return None


#: The rule ids this classifier can emit (sorted), for tests and docs.
RULE_IDS: Sequence[str] = tuple(
    sorted(
        f"{_PREFIX}.{rule}"
        for rule in (
            "parameter-added",
            "parameter-removed",
            "parameter-type-changed",
            "parameter-direction-changed",
            "parameter-renamed",
            "return-type-changed",
            "oneway-changed",
            "raises-added",
            "raises-removed",
            "member-added",
            "member-removed",
            "member-reordered",
            "member-shifted",
            "member-type-changed",
            "bound-narrowed",
            "bound-widened",
            "enumerator-removed",
            "enumerator-inserted",
            "enumerator-reordered",
            "enumerator-appended",
            "kind-changed",
            "base-removed",
            "base-added",
        )
    )
)
