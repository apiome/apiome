"""ASN.1 breaking-change classifier — MFI-21.5 (#3995).

An ASN.1 module is a contract between encoders and decoders (BER / DER / CER, PER, XER, OER…):
a decoder finds each component by its **tag** (BER family) or its **position and constraints**
(PER), and it can only skip what an **extension marker** (``...``) told it to expect. So this
classifier grades a change by how an old peer reads a new value:

=============================================  ===========  ======================================
Rule                                           Severity     When
=============================================  ===========  ======================================
``asn1.component-added-as-extension``          safe         a component was added after ``...``:
                                                            old decoders skip it
``asn1.component-added-optional``              dangerous    an OPTIONAL / DEFAULT component was
                                                            added to the extension root: strict
                                                            and PER decoders reject it
``asn1.component-added-required``              breaking     a mandatory component was added
``asn1.component-removed``                     breaking     a component is gone
``asn1.component-type-changed``                breaking     a component's type (or declared
                                                            built-in) changed: so did its tag /
                                                            encoding
``asn1.component-made-required``               breaking     an OPTIONAL component became mandatory
``asn1.component-made-optional``               dangerous    a mandatory component became OPTIONAL:
                                                            readers may now find it missing
``asn1.default-changed``                       breaking     a DEFAULT changed: DER omits a
                                                            component equal to its default, so an
                                                            omitted value now means another value
``asn1.tag-changed``                           breaking     a tag (class, number or kind) changed
``asn1.extension-moved``                       breaking     a component moved into or out of the
                                                            extension additions
``asn1.component-reordered``                   breaking     SEQUENCE components changed relative
                                                            order (decoded in order)
``asn1.component-shifted``                     safe         a component moved only because another
                                                            was added or removed (graded there)
``asn1.set-component-moved``                   safe         a SET component moved: SETs are
                                                            decoded by tag, not position
``asn1.constraint-narrowed``                   breaking     a value range or SIZE shrank
``asn1.constraint-widened``                    dangerous    a value range or SIZE grew or was
                                                            dropped: PER encodes constrained
                                                            values against the bounds
``asn1.enum-item-removed``                     breaking     an ENUMERATED item is gone
``asn1.enum-item-renumbered``                  breaking     an item's number changed
``asn1.enum-item-added-as-extension``          safe         an item was added after ``...``
``asn1.enum-item-added``                       dangerous    an item was added to the root
``asn1.alternative-removed``                   breaking     a CHOICE alternative is gone
``asn1.alternative-added-as-extension``        safe         an alternative was added after ``...``
``asn1.alternative-added``                     dangerous    an alternative was added to the root
``asn1.alternative-type-changed``              breaking     an alternative's type changed
``asn1.extension-marker-removed``              breaking     a type lost its ``...``: extension
                                                            additions from new peers are rejected
``asn1.extension-marker-added``                dangerous    a type gained ``...``: its PER encoding
                                                            gains an extension bit
``asn1.kind-changed``                          breaking     a SEQUENCE became a SET or back
                                                            (UNIVERSAL 16 ↔ 17)
``asn1.alias-target-changed``                  breaking     a type assignment refers to another
                                                            type
=============================================  ===========  ======================================

Removed and added types keep the baseline grade, as does every change not listed.
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
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["Asn1BreakingChangeClassifier", "RULE_IDS", "grade_bounds"]

_FORMAT_KEY = "asn1"
_PREFIX = "asn1"

#: A grade: ``(severity, rule_id, rationale)``.
Grade = Tuple[Severity, str, str]

#: The constraint pairs graded as ranges: ``(lower key, upper key)``.
_RANGES = (("minimum", "maximum"), ("min_length", "max_length"), ("min_items", "max_items"))


def _combine(grades: Sequence[Grade]) -> Grade:
    """The worst of several grades, its rule id first and every rationale kept."""
    worst = _worst([severity for severity, _, _ in grades])
    rule_id = next(rule for severity, rule, _ in grades if severity is worst)
    return worst, rule_id, "; ".join(rationale for _, _, rationale in grades)


def _get(projection: Any, key: str) -> Any:
    return projection.get(key) if isinstance(projection, Mapping) else None


def _extras(projection: Any) -> Mapping[str, Any]:
    extras = _get(projection, "extras")
    return extras if isinstance(extras, Mapping) else {}


def _shape(ref: Any) -> Any:
    """A type reference without nullability at any level."""
    if not isinstance(ref, Mapping):
        return ref
    return {k: _shape(v) for k, v in ref.items() if k != "nullable"}


def _optional(projection: Any) -> bool:
    ref = _get(projection, "type")
    nullable = not isinstance(ref, Mapping) or ref.get("nullable", True) is not False
    return nullable or _get(projection, "default") is not None


def grade_bounds(owner: str, before: Any, after: Any) -> Optional[Grade]:
    """Grade the value-range / SIZE bounds of two constraint projections.

    Args:
        owner: What the constraints belong to, for the rationale.
        before: The base ``constraints`` dict (or ``None``).
        after: The target ``constraints`` dict (or ``None``).

    Returns:
        ``constraint-narrowed`` (breaking) when any bound tightened, else ``constraint-widened``
        (dangerous) when any moved, else ``None``.
    """
    before = before if isinstance(before, Mapping) else {}
    after = after if isinstance(after, Mapping) else {}
    narrowed: List[str] = []
    widened: List[str] = []
    for low_key, high_key in _RANGES:
        old_low, new_low = before.get(low_key), after.get(low_key)
        old_high, new_high = before.get(high_key), after.get(high_key)
        if old_low != new_low:
            (narrowed if new_low is not None and (old_low is None or new_low > old_low) else widened).append(low_key)
        if old_high != new_high:
            (narrowed if new_high is not None and (old_high is None or new_high < old_high) else widened).append(
                high_key
            )
    if narrowed:
        return (
            Severity.BREAKING,
            f"{_PREFIX}.constraint-narrowed",
            f"{owner} accepts fewer values ({', '.join(narrowed)} tightened); old encoders produce rejected values",
        )
    if widened:
        return (
            Severity.DANGEROUS,
            f"{_PREFIX}.constraint-widened",
            f"{owner} accepts more values ({', '.join(widened)} loosened); PER encodes constrained values against "
            "the bounds and old decoders reject the new ones",
        )
    return None


def _grade_added_component(change: EntityChange) -> Grade:
    name = change.key.rsplit(".", 1)[-1]
    if _extras(change.after).get("asn1_extension"):
        return (
            Severity.SAFE,
            f"{_PREFIX}.component-added-as-extension",
            f"component {name!r} was added after the extension marker; old decoders skip it",
        )
    if _optional(change.after):
        return (
            Severity.DANGEROUS,
            f"{_PREFIX}.component-added-optional",
            f"optional component {name!r} was added to the extension root; strict and PER decoders reject it",
        )
    return (
        Severity.BREAKING,
        f"{_PREFIX}.component-added-required",
        f"mandatory component {name!r} was added; old encoders never send it",
    )


def _grade_component(change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Grade]:
    """Grade a modified SEQUENCE / SET component, or ``None`` for the baseline."""
    moved = {f.field for f in change.fields}
    if not moved or not moved <= {"type", "field_number", "constraints", "extras", "default"}:
        return None
    name = change.key.rsplit(".", 1)[-1]
    before, after = change.before, change.after
    old_extras, new_extras = _extras(before), _extras(after)
    grades: List[Grade] = []
    if _shape(_get(before, "type")) != _shape(_get(after, "type")) or old_extras.get("asn1_type") != new_extras.get(
        "asn1_type"
    ):
        grades.append((Severity.BREAKING, f"{_PREFIX}.component-type-changed", f"component {name!r} changed type"))
    was_optional, is_optional = _optional(before), _optional(after)
    if was_optional and not is_optional:
        grades.append(
            (Severity.BREAKING, f"{_PREFIX}.component-made-required", f"component {name!r} is no longer OPTIONAL")
        )
    elif is_optional and not was_optional:
        grades.append(
            (
                Severity.DANGEROUS,
                f"{_PREFIX}.component-made-optional",
                f"component {name!r} became OPTIONAL; readers may now find it missing",
            )
        )
    if "default" in moved and _get(before, "default") is not None and _get(after, "default") is not None:
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.default-changed",
                f"the DEFAULT of {name!r} changed ({_get(before, 'default')!r} → {_get(after, 'default')!r}); DER "
                "omits a value equal to its default, so an omitted value now means another one",
            )
        )
    if old_extras.get("asn1_tag") != new_extras.get("asn1_tag"):
        grades.append((Severity.BREAKING, f"{_PREFIX}.tag-changed", f"the tag of {name!r} changed"))
    if bool(old_extras.get("asn1_extension")) != bool(new_extras.get("asn1_extension")):
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.extension-moved",
                f"component {name!r} moved {'into' if new_extras.get('asn1_extension') else 'out of'} the extension "
                "additions",
            )
        )
    if "constraints" in moved:
        bound = grade_bounds(f"component {name!r}", _get(before, "constraints"), _get(after, "constraints"))
        if bound is not None:
            grades.append(bound)
    if "field_number" in moved:
        grades.append(_grade_position(change, name, base, target))
    return _combine(grades) if grades else None


def _owner_is_set(api: CanonicalApi, field_key: str) -> bool:
    for type_ in api.types:
        if any(field.key == field_key for field in type_.fields):
            return type_.extras.get("asn1_kind") == "SET"
    return False


def _grade_position(change: EntityChange, name: str, base: CanonicalApi, target: CanonicalApi) -> Grade:
    if _owner_is_set(target, change.key):
        return (
            Severity.SAFE,
            f"{_PREFIX}.set-component-moved",
            f"SET component {name!r} moved; a SET is decoded by tag, not position",
        )
    if relative_field_order_changed(base, target, change.key):
        return (
            Severity.BREAKING,
            f"{_PREFIX}.component-reordered",
            f"component {name!r} moved relative to the others; a SEQUENCE is decoded in order",
        )
    return (
        Severity.SAFE,
        f"{_PREFIX}.component-shifted",
        f"component {name!r} shifted because another component was added or removed (graded there)",
    )


def _grade_enum(change: EntityChange) -> List[Grade]:
    field = next((f for f in change.fields if f.field == "enum_values"), None)
    if field is None:
        return []
    old = {str(v.get("name")): v for v in field.before or [] if isinstance(v, Mapping)}
    new = {str(v.get("name")): v for v in field.after or [] if isinstance(v, Mapping)}
    grades: List[Grade] = []
    removed = [n for n in old if n not in new]
    if removed:
        grades.append((Severity.BREAKING, f"{_PREFIX}.enum-item-removed", f"{change.key!r} lost {', '.join(removed)}"))
    renumbered = [n for n in old if n in new and old[n].get("value") != new[n].get("value")]
    if renumbered:
        grades.append(
            (Severity.BREAKING, f"{_PREFIX}.enum-item-renumbered", f"{change.key!r} renumbered {', '.join(renumbered)}")
        )
    for name in (n for n in new if n not in old):
        if _extras(new[name]).get("asn1_extension"):
            grades.append(
                (
                    Severity.SAFE,
                    f"{_PREFIX}.enum-item-added-as-extension",
                    f"{change.key!r} gained {name} after the extension marker",
                )
            )
        else:
            grades.append(
                (
                    Severity.DANGEROUS,
                    f"{_PREFIX}.enum-item-added",
                    f"{change.key!r} gained {name} in its root; old decoders cannot decode it",
                )
            )
    return grades


def _alternatives(projection: Any) -> Dict[str, Mapping[str, Any]]:
    listed = _extras(projection).get("asn1_choice_members")
    return {str(a.get("name")): a for a in listed or [] if isinstance(a, Mapping)}


def _grade_choice(change: EntityChange) -> List[Grade]:
    old, new = _alternatives(change.before), _alternatives(change.after)
    grades: List[Grade] = []
    for name in (n for n in old if n not in new):
        grades.append((Severity.BREAKING, f"{_PREFIX}.alternative-removed", f"alternative {name!r} is gone"))
    for name in (n for n in new if n not in old):
        if new[name].get("asn1_extension"):
            grades.append(
                (
                    Severity.SAFE,
                    f"{_PREFIX}.alternative-added-as-extension",
                    f"alternative {name!r} was added after the extension marker",
                )
            )
        else:
            grades.append(
                (
                    Severity.DANGEROUS,
                    f"{_PREFIX}.alternative-added",
                    f"alternative {name!r} was added to the root; old decoders cannot decode it",
                )
            )
    for name in (n for n in old if n in new):
        was, now = old[name], new[name]
        if (was.get("type"), was.get("asn1_type")) != (now.get("type"), now.get("asn1_type")):
            grades.append(
                (Severity.BREAKING, f"{_PREFIX}.alternative-type-changed", f"alternative {name!r} changed type")
            )
        if was.get("asn1_tag") != now.get("asn1_tag"):
            grades.append((Severity.BREAKING, f"{_PREFIX}.tag-changed", f"the tag of alternative {name!r} changed"))
        bound = grade_bounds(f"alternative {name!r}", was.get("constraints"), now.get("constraints"))
        if bound is not None:
            grades.append(bound)
        if bool(was.get("asn1_extension")) != bool(now.get("asn1_extension")):
            grades.append(
                (
                    Severity.BREAKING,
                    f"{_PREFIX}.extension-moved",
                    f"alternative {name!r} moved into or out of the extension additions",
                )
            )
    return grades


def _grade_type(change: EntityChange) -> Optional[Grade]:
    """Grade a modified type assignment, or ``None`` for the baseline."""
    moved = {f.field for f in change.fields}
    if not moved or not moved <= {"enum_values", "union_members", "extras", "aliased", "constraints"}:
        return None
    before, after = change.before, change.after
    old_extras, new_extras = _extras(before), _extras(after)
    grades: List[Grade] = _grade_enum(change) + _grade_choice(change)
    if bool(old_extras.get("asn1_extensible")) and not new_extras.get("asn1_extensible"):
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.extension-marker-removed",
                f"{change.key!r} lost its extension marker; extension additions from new peers are rejected",
            )
        )
    elif new_extras.get("asn1_extensible") and not old_extras.get("asn1_extensible"):
        grades.append(
            (
                Severity.DANGEROUS,
                f"{_PREFIX}.extension-marker-added",
                f"{change.key!r} gained an extension marker; its PER encoding gains an extension bit",
            )
        )
    if (old_extras.get("asn1_kind") or "SEQUENCE") != (new_extras.get("asn1_kind") or "SEQUENCE"):
        grades.append(
            (
                Severity.BREAKING,
                f"{_PREFIX}.kind-changed",
                f"{change.key!r} is now a {new_extras.get('asn1_kind') or 'SEQUENCE'} (UNIVERSAL 16 ↔ 17)",
            )
        )
    if old_extras.get("asn1_tag") != new_extras.get("asn1_tag"):
        grades.append((Severity.BREAKING, f"{_PREFIX}.tag-changed", f"the tag of {change.key!r} changed"))
    if "aliased" in moved or old_extras.get("asn1_type") != new_extras.get("asn1_type"):
        grades.append(
            (Severity.BREAKING, f"{_PREFIX}.alias-target-changed", f"{change.key!r} now refers to another type")
        )
    if "constraints" in moved:
        bound = grade_bounds(repr(change.key), _get(before, "constraints"), _get(after, "constraints"))
        if bound is not None:
            grades.append(bound)
    return _combine(grades) if grades else None


class Asn1BreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an ASN.1 diff by how an old peer decodes a new value (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "asn1-encoding"

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
        if change.category is EntityCategory.FIELD:
            if change.kind is ChangeKind.ADDED:
                graded = _grade_added_component(change)
            elif change.kind is ChangeKind.REMOVED:
                graded = (
                    Severity.BREAKING,
                    f"{_PREFIX}.component-removed",
                    f"component {change.key.rsplit('.', 1)[-1]!r} was removed",
                )
            else:
                graded = _grade_component(change, base, target)
        elif change.category is EntityCategory.TYPE and change.kind is ChangeKind.MODIFIED:
            graded = _grade_type(change)
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


#: The rule ids this classifier can emit (sorted), for tests and docs.
RULE_IDS: Sequence[str] = tuple(
    sorted(
        f"{_PREFIX}.{rule}"
        for rule in (
            "component-added-as-extension",
            "component-added-optional",
            "component-added-required",
            "component-removed",
            "component-type-changed",
            "component-made-required",
            "component-made-optional",
            "default-changed",
            "tag-changed",
            "extension-moved",
            "component-reordered",
            "component-shifted",
            "set-component-moved",
            "constraint-narrowed",
            "constraint-widened",
            "enum-item-removed",
            "enum-item-renumbered",
            "enum-item-added-as-extension",
            "enum-item-added",
            "alternative-removed",
            "alternative-added-as-extension",
            "alternative-added",
            "alternative-type-changed",
            "extension-marker-removed",
            "extension-marker-added",
            "kind-changed",
            "alias-target-changed",
        )
    )
)
