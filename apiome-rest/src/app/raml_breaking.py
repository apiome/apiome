"""RAML breaking-change classifier — MFI-15.4 (#3802).

RAML has no official compatibility rules, so this is a custom ruleset over the resolved model the
RAML importer builds (AMF-resolved when the server has AMF, MFI-15.1): resources and methods are
operations (``GET /pets``), a method's query / header / URI parameters are its parameters,
responses are messages by status, and RAML types are record or enum types. Resource types and
traits are already applied, so their *effects* (the parameters and responses they add) are graded
where they land.

RAML validates both requests and responses against the declared types, so a change that makes a
value newly required or newly rejected breaks someone. The format-agnostic baseline grades the
parameter list and enum values only as a folded blob (dangerous); this classifier grades what moved:

======================================  ==========  =============================================
Rule                                    Severity    When
======================================  ==========  =============================================
``raml.parameter-added-required``       breaking    a method gains a required parameter
``raml.parameter-added-optional``       safe        a method gains an optional parameter
``raml.parameter-removed``              dangerous   a parameter is gone (callers that still send it
                                                    may be rejected or silently ignored)
``raml.parameter-made-required``        breaking    an optional parameter became required
``raml.parameter-made-optional``        safe        a required parameter became optional
``raml.parameter-type-changed``         breaking    a parameter's type changed
``raml.property-added-required``        breaking    a type gains a required property
``raml.property-added-optional``        safe        a type gains an optional property (``name?``)
``raml.property-type-changed``          breaking    a property's type changed
``raml.property-made-required``         breaking    an optional property became required
``raml.property-made-optional``         dangerous   a required property became optional (readers
                                                    may now get it missing)
``raml.enum-value-removed``             breaking    an enum lost a value
``raml.enum-value-added``               dangerous   an enum gained a value (exhaustive clients)
``raml.enum-reordered``                 safe        only the order of an enum's values moved
``raml.reuse-changed``                  safe        only the applied resource type / traits moved;
                                                    their effects are graded where they land
======================================  ==========  =============================================

Removed resources, methods, responses and types keep the baseline grade (breaking), as do additions
(safe) and every change this classifier does not recognise.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity, _worst
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["RamlBreakingChangeClassifier", "grade_parameters"]

_FORMAT_KEY = "raml"

#: A grade: ``(severity, rule_id, rationale)``.
Grade = Tuple[Severity, str, str]

_REUSE_EXTRAS = frozenset({"raml_traits", "raml_resource_type"})


def _shape(type_ref: Any) -> Any:
    """A type reference without its nullability (what values of it look like)."""
    if not isinstance(type_ref, Mapping):
        return type_ref
    return {key: value for key, value in type_ref.items() if key != "nullable"}


def _by_key(items: Any) -> Dict[str, Mapping[str, Any]]:
    return {str(item.get("key")): item for item in items or [] if isinstance(item, Mapping) and item.get("key")}


def _label(parameter: Mapping[str, Any]) -> str:
    location = parameter.get("location")
    location = getattr(location, "value", location)
    return f"{location} parameter {parameter.get('name')!r}"


def grade_parameters(before: Any, after: Any) -> List[Grade]:
    """Grade every parameter added, removed or changed on one method.

    Args:
        before: The base method's ``parameters`` (self-projection dicts).
        after: The target method's ``parameters``.

    Returns:
        One grade per parameter that moved.
    """
    old, new = _by_key(before), _by_key(after)
    grades: List[Grade] = []
    for key in sorted(new.keys() - old.keys()):
        parameter = new[key]
        if parameter.get("required"):
            grades.append(
                (
                    Severity.BREAKING,
                    "raml.parameter-added-required",
                    f"required {_label(parameter)} was added; existing callers never send it",
                )
            )
        else:
            grades.append((Severity.SAFE, "raml.parameter-added-optional", f"optional {_label(parameter)} was added"))
    for key in sorted(old.keys() - new.keys()):
        grades.append(
            (
                Severity.DANGEROUS,
                "raml.parameter-removed",
                f"{_label(old[key])} was removed; callers that still send it may be rejected or ignored",
            )
        )
    for key in sorted(old.keys() & new.keys()):
        was, now = old[key], new[key]
        if _shape(was.get("type")) != _shape(now.get("type")):
            grades.append(
                (
                    Severity.BREAKING,
                    "raml.parameter-type-changed",
                    f"{_label(now)} changed type ({was.get('extras', {}).get('raml_type')!r} → "
                    f"{now.get('extras', {}).get('raml_type')!r})",
                )
            )
        if now.get("required") and not was.get("required"):
            grades.append(
                (
                    Severity.BREAKING,
                    "raml.parameter-made-required",
                    f"{_label(now)} became required; callers that omit it are rejected",
                )
            )
        elif was.get("required") and not now.get("required"):
            grades.append((Severity.SAFE, "raml.parameter-made-optional", f"{_label(now)} is no longer required"))
    return grades


def _grade_operation(change: EntityChange) -> Optional[Grade]:
    """Grade a method whose parameters and/or applied reuse moved, or ``None`` for the baseline."""
    moved = {f.field for f in change.fields}
    if not moved or not moved <= {"parameters", "extras"}:
        return None
    grades: List[Grade] = []
    if "parameters" in moved:
        field = next(f for f in change.fields if f.field == "parameters")
        grades.extend(grade_parameters(field.before, field.after))
    if "extras" in moved:
        before = dict(change.before.get("extras") or {}) if isinstance(change.before, Mapping) else {}
        after = dict(change.after.get("extras") or {}) if isinstance(change.after, Mapping) else {}
        if {k: v for k, v in before.items() if k not in _REUSE_EXTRAS} != {
            k: v for k, v in after.items() if k not in _REUSE_EXTRAS
        }:
            return None
        grades.append(
            (
                Severity.SAFE,
                "raml.reuse-changed",
                "the applied resource type / traits changed; their effects on parameters and responses are "
                "graded where they land",
            )
        )
    return _combine(grades) if grades else None


def _grade_enum(change: EntityChange) -> Optional[Grade]:
    """Grade an enum whose only move is its values, or ``None`` for the baseline."""
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
                "raml.enum-value-removed",
                f"enum {change.key!r} no longer allows {', '.join(map(repr, removed))}",
            )
        )
    if added:
        grades.append(
            (
                Severity.DANGEROUS,
                "raml.enum-value-added",
                f"enum {change.key!r} now allows {', '.join(map(repr, added))}; clients that handle every value "
                "may not expect it",
            )
        )
    if not grades:  # only the order moved
        grades.append((Severity.SAFE, "raml.enum-reordered", f"enum {change.key!r} reordered its values"))
    return _combine(grades)


def _grade_added_property(change: EntityChange) -> Grade:
    name = change.key.rsplit(".", 1)[-1]
    after = change.after if isinstance(change.after, Mapping) else {}
    nullable = (after.get("type") or {}).get("nullable", True) if isinstance(after.get("type"), Mapping) else True
    if nullable is False:
        return (
            Severity.BREAKING,
            "raml.property-added-required",
            f"required property {name!r} was added; payloads written without it no longer validate",
        )
    return (Severity.SAFE, "raml.property-added-optional", f"optional property {name!r} was added")


def _grade_property(change: EntityChange) -> Optional[Grade]:
    """Grade a property whose type or required-ness moved, or ``None`` for the baseline."""
    moved = {f.field for f in change.fields}
    if "type" not in moved or not moved <= {"type", "extras"}:
        return None
    field = next(f for f in change.fields if f.field == "type")
    before = field.before if isinstance(field.before, Mapping) else {}
    after = field.after if isinstance(field.after, Mapping) else {}
    name = change.key.rsplit(".", 1)[-1]
    grades: List[Grade] = []
    if _shape(before) != _shape(after):
        grades.append((Severity.BREAKING, "raml.property-type-changed", f"property {name!r} changed type"))
    was_optional, is_optional = before.get("nullable", True) is not False, after.get("nullable", True) is not False
    if was_optional and not is_optional:
        grades.append(
            (
                Severity.BREAKING,
                "raml.property-made-required",
                f"property {name!r} became required; payloads that omit it no longer validate",
            )
        )
    elif is_optional and not was_optional:
        grades.append(
            (
                Severity.DANGEROUS,
                "raml.property-made-optional",
                f"property {name!r} became optional; readers may now find it missing",
            )
        )
    return _combine(grades) if grades else None


def _combine(grades: Sequence[Grade]) -> Grade:
    """The worst of several grades, its rule id first and every rationale kept."""
    worst = _worst([severity for severity, _, _ in grades])
    rule_id = next(rule for severity, rule, _ in grades if severity is worst)
    return worst, rule_id, "; ".join(rationale for _, _, rationale in grades)


class RamlBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a RAML diff by resource / method / type changes (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "raml-resources"

    def classify_change(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> ChangeClassification:
        """Grade one change; changes this classifier does not recognise use the baseline."""
        graded: Optional[Grade] = None
        if change.category is EntityCategory.OPERATION and change.kind is ChangeKind.MODIFIED:
            graded = _grade_operation(change)
        elif change.category is EntityCategory.TYPE and change.kind is ChangeKind.MODIFIED:
            graded = _grade_enum(change)
        elif change.category is EntityCategory.FIELD and change.kind is ChangeKind.ADDED:
            graded = _grade_added_property(change)
        elif change.category is EntityCategory.FIELD and change.kind is ChangeKind.MODIFIED:
            graded = _grade_property(change)
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
