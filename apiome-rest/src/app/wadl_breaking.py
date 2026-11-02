"""WADL breaking-change classifier — MFI-21.3 (#3993).

WADL has no compatibility rules of its own, so this is a custom ruleset over the model
:class:`~app.wadl_normalizer.WadlNormalizer` builds: each resource method is an operation
(``GET /books/{bookId}``), its params are parameters, its request and each response status are
messages (with their representations' media types), and the grammars' complex types are records
whose fields are the ``xsd:sequence`` elements (``minOccurs="0"`` / ``nillable`` → optional,
``maxOccurs`` → a bounded list). Named enumerated simple types are enums.

A WADL service validates XML against its grammars, so the rules follow XML Schema: a sequence is
**ordered**, a missing required element fails validation, and an occurrence bound is enforced.
The format-agnostic baseline grades a parameter set, a media-type list and a field-number move
only as a folded blob; this classifier grades what moved:

========================================  ==========  =============================================
Rule                                      Severity    When
========================================  ==========  =============================================
``wadl.parameter-added-required``         breaking    a method gains a required param
``wadl.parameter-added-optional``         safe        a method gains an optional param
``wadl.parameter-removed``                dangerous   a param is gone (callers that still send it
                                                      may be rejected or silently ignored)
``wadl.parameter-made-required``          breaking    an optional param became required
``wadl.parameter-made-optional``          safe        a required param became optional
``wadl.parameter-type-changed``           breaking    a param's XSD type changed
``wadl.parameter-option-removed``         breaking    a param no longer allows an ``option`` value
``wadl.parameter-option-added``           safe        a param allows a new ``option`` value
``wadl.media-type-removed``               breaking    a request / response representation's
                                                      ``mediaType`` is gone
``wadl.media-type-added``                 safe        a representation gained a ``mediaType``
``wadl.representation-type-changed``      breaking    a representation names a different element
``wadl.element-added-required``           breaking    a sequence gains a required element
                                                      (documents without it no longer validate)
``wadl.element-added-optional``           safe        a sequence gains an optional element
``wadl.element-type-changed``             breaking    an element's XSD type (or repetition) changed
``wadl.element-made-required``            breaking    an optional element became required
``wadl.element-made-optional``            dangerous   a required element became optional (readers
                                                      may now find it missing)
``wadl.element-reordered``                breaking    the relative order of a sequence's elements
                                                      changed (a sequence is validated in order)
``wadl.element-shifted``                  safe        an element's position moved only because
                                                      another was added or removed (graded there)
``wadl.occurs-narrowed``                  breaking    ``minOccurs`` rose or ``maxOccurs`` fell
``wadl.occurs-widened``                   dangerous   ``minOccurs`` fell or ``maxOccurs`` rose
                                                      (readers may get more or fewer items)
``wadl.enum-value-removed``               breaking    an enumerated simple type lost a value
``wadl.enum-value-added``                 dangerous   an enumerated simple type gained a value
``wadl.enum-reordered``                   safe        only the order of the values moved
========================================  ==========  =============================================

Removed methods, responses, types and elements keep the baseline grade (breaking), as do every
other addition (safe) and every change this classifier does not recognise.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional, Sequence

from .breaking_change import (
    BuiltinBreakingChangeClassifier,
    ChangeClassification,
    Severity,
    _worst,
    relative_field_order_changed,
)
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange, FieldChange
from .raml_breaking import Grade, grade_parameters

__all__ = ["RULE_IDS", "WadlBreakingChangeClassifier", "grade_options", "relative_order_changed"]

#: Kept under its original name; the helper moved to :mod:`app.breaking_change` (MFI-21.4).
relative_order_changed = relative_field_order_changed

_FORMAT_KEY = "wadl"
_PREFIX = "wadl"


def _shape(type_ref: Any) -> Any:
    """A type reference with nullability removed at every level (what values of it look like)."""
    if not isinstance(type_ref, Mapping):
        return type_ref
    return {key: _shape(value) for key, value in type_ref.items() if key != "nullable"}


def _optional(type_ref: Any) -> bool:
    """Whether a field's (outermost) type may be absent."""
    return not isinstance(type_ref, Mapping) or type_ref.get("nullable", True) is not False


def _combine(grades: Sequence[Grade]) -> Grade:
    """The worst of several grades, its rule id first and every rationale kept."""
    worst = _worst([severity for severity, _, _ in grades])
    rule_id = next(rule for severity, rule, _ in grades if severity is worst)
    return worst, rule_id, "; ".join(rationale for _, _, rationale in grades)


def _moved(change: EntityChange, name: str) -> Optional[FieldChange]:
    return next((f for f in change.fields if f.field == name), None)


def _options(parameter: Mapping[str, Any]) -> List[str]:
    constraints = parameter.get("constraints") or {}
    values = constraints.get("enum") if isinstance(constraints, Mapping) else None
    return [str(value) for value in values or []]


def grade_options(before: Any, after: Any) -> List[Grade]:
    """Grade the ``option`` values of every param present on both sides.

    Args:
        before: The base method's ``parameters`` (self-projection dicts).
        after: The target method's ``parameters``.

    Returns:
        One grade per param whose allowed values were removed or added.
    """
    old = {str(p.get("key")): p for p in before or [] if isinstance(p, Mapping)}
    new = {str(p.get("key")): p for p in after or [] if isinstance(p, Mapping)}
    grades: List[Grade] = []
    for key in sorted(old.keys() & new.keys()):
        was, now = _options(old[key]), _options(new[key])
        name = new[key].get("name")
        if was == now:
            continue
        if not now:
            grades.append((Severity.SAFE, f"{_PREFIX}.parameter-option-added", f"param {name!r} now allows any value"))
            continue
        # An empty list allowed any value, so restricting it removes every value but the options.
        removed = [value for value in was if value not in now] if was else ["any value but the listed options"]
        added = [value for value in now if value not in was] if was else []
        if removed:
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.parameter-option-removed",
                    f"param {name!r} no longer allows {', '.join(map(repr, removed))}; callers sending it are rejected",
                )
            )
        if added:
            grades.append(
                (
                    Severity.SAFE,
                    f"{_PREFIX}.parameter-option-added",
                    f"param {name!r} now also allows {', '.join(map(repr, added))}",
                )
            )
    return grades


def _without_options(parameters: Any) -> List[Any]:
    """The parameters with their option lists removed (graded separately)."""
    out: List[Any] = []
    for parameter in parameters or []:
        if isinstance(parameter, Mapping):
            parameter = {k: v for k, v in parameter.items() if k != "constraints"}
        out.append(parameter)
    return out


def _grade_operation(change: EntityChange) -> Optional[Grade]:
    """Grade a method whose only move is its params, or ``None`` for the baseline."""
    if {f.field for f in change.fields} != {"parameters"}:
        return None
    field = change.fields[0]
    grades = grade_parameters(
        _without_options(field.before), _without_options(field.after), prefix=_PREFIX, type_extra="wadl_type"
    )
    grades.extend(grade_options(field.before, field.after))
    return _combine(grades) if grades else None


def _grade_message(change: EntityChange) -> Optional[Grade]:
    """Grade a representation whose media types and/or element moved, or ``None``."""
    moved = {f.field for f in change.fields}
    if not moved or not moved <= {"content_types", "payload"}:
        return None
    grades: List[Grade] = []
    media = _moved(change, "content_types")
    if media is not None:
        was, now = list(media.before or []), list(media.after or [])
        removed = [m for m in was if m not in now]
        added = [m for m in now if m not in was]
        if removed:
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.media-type-removed",
                    f"{change.key!r} no longer has a {', '.join(removed)} representation; callers that send "
                    "or accept it break",
                )
            )
        if added:
            grades.append(
                (
                    Severity.SAFE,
                    f"{_PREFIX}.media-type-added",
                    f"{change.key!r} gained a {', '.join(added)} representation",
                )
            )
    payload = _moved(change, "payload")
    if payload is not None:
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.representation-type-changed",
                f"{change.key!r} now names a different grammar element; documents of the old one no longer validate",
            )
        )
    return _combine(grades) if grades else None


def _grade_enum(change: EntityChange) -> Optional[Grade]:
    """Grade an enumerated simple type whose only move is its values, or ``None``."""
    if {f.field for f in change.fields} != {"enum_values"}:
        return None
    field = change.fields[0]
    old = [str(v.get("name")) for v in field.before or [] if isinstance(v, Mapping)]
    new = [str(v.get("name")) for v in field.after or [] if isinstance(v, Mapping)]
    grades: List[Grade] = []
    removed = [v for v in old if v not in new]
    added = [v for v in new if v not in old]
    if removed:
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.enum-value-removed",
                f"simple type {change.key!r} no longer allows {', '.join(map(repr, removed))}",
            )
        )
    if added:
        grades.append(
            (
                Severity.DANGEROUS,
                f"{_PREFIX}.enum-value-added",
                f"simple type {change.key!r} now allows {', '.join(map(repr, added))}; readers that handle every "
                "value may not expect it",
            )
        )
    if not grades:
        grades.append((Severity.SAFE, f"{_PREFIX}.enum-reordered", f"simple type {change.key!r} reordered its values"))
    return _combine(grades)


def _grade_added_element(change: EntityChange) -> Grade:
    name = change.key.rsplit(".", 1)[-1]
    after = change.after if isinstance(change.after, Mapping) else {}
    if not _optional(after.get("type")):
        return (
            Severity.BREAKING,
            f"{_PREFIX}.element-added-required",
            f"required element {name!r} was added to the sequence; documents written without it no longer validate",
        )
    return (Severity.SAFE, f"{_PREFIX}.element-added-optional", f"optional element {name!r} was added")


def _bounds(field: Mapping[str, Any]) -> tuple:
    constraints = field.get("constraints") if isinstance(field, Mapping) else None
    constraints = constraints if isinstance(constraints, Mapping) else {}
    return constraints.get("min_items") or 0, constraints.get("max_items")


def _grade_element(change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Grade]:
    """Grade a sequence element whose type, position or occurrence moved, or ``None``."""
    moved = {f.field for f in change.fields}
    if not moved or not moved <= {"type", "field_number", "constraints", "extras"}:
        return None
    name = change.key.rsplit(".", 1)[-1]
    before = change.before if isinstance(change.before, Mapping) else {}
    after = change.after if isinstance(change.after, Mapping) else {}
    grades: List[Grade] = []
    if "type" in moved:
        was, now = before.get("type"), after.get("type")
        if _shape(was) != _shape(now):
            grades.append((Severity.BREAKING, f"{_PREFIX}.element-type-changed", f"element {name!r} changed type"))
        if _optional(was) and not _optional(now):
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.element-made-required",
                    f"element {name!r} became required; documents that omit it no longer validate",
                )
            )
        elif _optional(now) and not _optional(was):
            grades.append(
                (
                    Severity.DANGEROUS,
                    f"{_PREFIX}.element-made-optional",
                    f"element {name!r} became optional; readers may now find it missing",
                )
            )
    if "field_number" in moved:
        if relative_field_order_changed(base, target, change.key):
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.element-reordered",
                    f"element {name!r} moved relative to its siblings; an xsd:sequence is validated in order",
                )
            )
        else:
            grades.append(
                (
                    Severity.SAFE,
                    f"{_PREFIX}.element-shifted",
                    f"element {name!r} shifted because a sibling was added or removed (graded there)",
                )
            )
    if "constraints" in moved:
        (old_min, old_max), (new_min, new_max) = _bounds(before), _bounds(after)
        narrowed = new_min > old_min or (new_max is not None and (old_max is None or new_max < old_max))
        if narrowed:
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.occurs-narrowed",
                    f"element {name!r} allows fewer occurrences ({old_min}..{old_max or 'unbounded'} → "
                    f"{new_min}..{new_max or 'unbounded'})",
                )
            )
        elif (old_min, old_max) != (new_min, new_max):
            grades.append(
                (
                    Severity.DANGEROUS,
                    f"{_PREFIX}.occurs-widened",
                    f"element {name!r} allows more occurrences ({old_min}..{old_max or 'unbounded'} → "
                    f"{new_min}..{new_max or 'unbounded'}); readers may get more or fewer items",
                )
            )
    return _combine(grades) if grades else None


class WadlBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a WADL diff by method, representation and grammar changes (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "wadl-resources"

    def classify_change(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> ChangeClassification:
        """Grade one change; changes this classifier does not recognise use the baseline.

        Args:
            change: The diff change to grade.
            base: The "from" model.
            target: The "to" model.

        Returns:
            The change's classification.
        """
        graded: Optional[Grade] = None
        modified = change.kind is ChangeKind.MODIFIED
        if change.category is EntityCategory.OPERATION and modified:
            graded = _grade_operation(change)
        elif change.category is EntityCategory.MESSAGE and modified:
            graded = _grade_message(change)
        elif change.category is EntityCategory.TYPE and modified:
            graded = _grade_enum(change)
        elif change.category is EntityCategory.FIELD and change.kind is ChangeKind.ADDED:
            graded = _grade_added_element(change)
        elif change.category is EntityCategory.FIELD and modified:
            graded = _grade_element(change, base, target)
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


#: Exposed for tests: the rule ids this classifier can emit (sorted).
RULE_IDS: Sequence[str] = tuple(
    sorted(
        f"{_PREFIX}.{rule}"
        for rule in (
            "parameter-added-required",
            "parameter-added-optional",
            "parameter-removed",
            "parameter-made-required",
            "parameter-made-optional",
            "parameter-type-changed",
            "parameter-option-removed",
            "parameter-option-added",
            "media-type-removed",
            "media-type-added",
            "representation-type-changed",
            "element-added-required",
            "element-added-optional",
            "element-type-changed",
            "element-made-required",
            "element-made-optional",
            "element-reordered",
            "element-shifted",
            "occurs-narrowed",
            "occurs-widened",
            "enum-value-removed",
            "enum-value-added",
            "enum-reordered",
        )
    )
)
