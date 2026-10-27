"""WSDL / XSD breaking-change classifier — MFI-13.5 (#3792).

SOAP has no official compatibility contract, and XSD has no standard diff, so this classifier
is a ruleset in the spirit of membrane's soa-model: it grades what the WSDL importer now records
(MFI-13.5) — each operation's message exchange pattern, its SOAP binding's ``soapAction`` and
style, and each element particle's ``minOccurs`` / ``maxOccurs`` / ``nillable`` / ``default`` and
simple-type restriction facets.

**"Additive = safe" does not hold for XSD.** SOAP stacks validate strictly: a receiver that does
not know an element rejects the message, and the same complex type is often both sent and
received. So an *added optional element* is graded **dangerous**, not safe, and a widened value
space (a longer ``maxLength``, a new ``enumeration`` value) is dangerous too. Direction (request vs
response) is not known per type, so a narrowing is breaking.

=====================================  ==========  ============================================
Rule                                   Severity    When
=====================================  ==========  ============================================
``wsdl.mep-changed``                   breaking    an operation's message exchange pattern changed
``wsdl.soap-action-changed``           breaking    an operation's ``soapAction`` changed
``wsdl.soap-style-changed``            breaking    an operation moved between rpc and document style
``wsdl.element-added-required``        breaking    a new element with ``minOccurs`` ≥ 1
``wsdl.element-added-optional``        dangerous   a new element with ``minOccurs="0"`` (strict receivers)
``wsdl.element-type-changed``          breaking    an element's type changed
``wsdl.min-occurs-raised``             breaking    ``minOccurs`` increased
``wsdl.min-occurs-lowered``            dangerous   ``minOccurs`` decreased
``wsdl.max-occurs-lowered``            breaking    ``maxOccurs`` decreased
``wsdl.max-occurs-raised``             dangerous   ``maxOccurs`` increased
``wsdl.made-non-nillable``             breaking    ``nillable`` true → false
``wsdl.made-nillable``                 dangerous   ``nillable`` false → true
``wsdl.default-changed``               dangerous   an element's ``default`` changed
``wsdl.facet-narrowed``                breaking    a restriction got tighter: an enumeration value
                                                   removed, a facet added, a bound tightened, a
                                                   ``pattern`` changed, the base type changed
``wsdl.facet-widened``                 dangerous   a restriction got looser: an enumeration value
                                                   added, a facet removed, a bound loosened
``wsdl.element-unchanged-on-the-wire``  safe        only the spelling moved (``maxOccurs="1"`` made
                                                   explicit): the element accepts the same values
=====================================  ==========  ============================================

Operations, types and elements added or removed outright keep the baseline grading (removed:
breaking; a new operation or type: safe — existing messages are unaffected). Standalone ``.xsd``
catalog items (the ``xsd`` format) are not graded here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity, _worst
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["WsdlBreakingChangeClassifier", "grade_facets", "grade_occurs"]

_FORMAT_KEY = "wsdl"

#: A grade: ``(severity, rule_id, rationale)``.
Grade = Tuple[Severity, str, str]

#: Facets whose larger value is *looser* (a longer string / higher bound / more digits allowed).
_UPPER_BOUNDS = frozenset({"maxLength", "maxInclusive", "maxExclusive", "totalDigits", "fractionDigits"})
#: Facets whose larger value is *tighter*.
_LOWER_BOUNDS = frozenset({"minLength", "minInclusive", "minExclusive"})

_XSD_DETAILS = (
    "xsd_min_occurs",
    "xsd_max_occurs",
    "xsd_nillable",
    "xsd_default",
    "xsd_simple_type",
    "xsd_base",
    "xsd_facets",
)


def _extras(projection: Any) -> Dict[str, Any]:
    if isinstance(projection, Mapping) and isinstance(projection.get("extras"), Mapping):
        return dict(projection["extras"])
    return {}


def _number(value: Any) -> Optional[Decimal]:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _occurs(value: Any, default: int = 1) -> Optional[Decimal]:
    """A ``minOccurs`` / ``maxOccurs`` value (``unbounded`` → infinity; unstated → XSD's default ``1``)."""
    if value is None:
        return Decimal(default)
    if str(value).strip() == "unbounded":
        return Decimal("Infinity")
    return _number(value)


def _show(value: Decimal) -> str:
    """An occurrence bound as XSD writes it (``unbounded`` for infinity)."""
    return "unbounded" if value.is_infinite() else str(value)


def _is_true(value: Any) -> bool:
    return str(value).strip().lower() in ("true", "1")


# ---------------------------------------------------------------------------
# Element particles
# ---------------------------------------------------------------------------


def grade_occurs(name: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> List[Grade]:
    """Grade ``minOccurs`` / ``maxOccurs`` moves of one element."""
    grades: List[Grade] = []
    old_min, new_min = _occurs(before.get("xsd_min_occurs")), _occurs(after.get("xsd_min_occurs"))
    if old_min is not None and new_min is not None and old_min != new_min:
        if new_min > old_min:
            grades.append(
                (
                    Severity.BREAKING,
                    "wsdl.min-occurs-raised",
                    f"element {name!r} now needs at least {_show(new_min)} occurrence(s) "
                    f"(was {_show(old_min)}); messages "
                    "that omit it are rejected",
                )
            )
        else:
            grades.append(
                (
                    Severity.DANGEROUS,
                    "wsdl.min-occurs-lowered",
                    f"element {name!r} may now be omitted (minOccurs {_show(old_min)} → {_show(new_min)}); "
                    "receivers that "
                    "expect it may fail",
                )
            )
    old_max, new_max = _occurs(before.get("xsd_max_occurs")), _occurs(after.get("xsd_max_occurs"))
    if old_max is not None and new_max is not None and old_max != new_max:
        if new_max < old_max:
            grades.append(
                (
                    Severity.BREAKING,
                    "wsdl.max-occurs-lowered",
                    f"element {name!r} now allows at most {_show(new_max)} occurrence(s) "
                    f"(was {_show(old_max)}); messages "
                    "with more are rejected",
                )
            )
        else:
            grades.append(
                (
                    Severity.DANGEROUS,
                    "wsdl.max-occurs-raised",
                    f"element {name!r} now allows more occurrences (maxOccurs {_show(old_max)} → {_show(new_max)}); "
                    "receivers that expect one value may fail",
                )
            )
    return grades


def grade_facets(name: str, before: Mapping[str, Any], after: Mapping[str, Any]) -> List[Grade]:
    """Grade a simple-type restriction's moves: tighter is breaking, looser dangerous.

    Args:
        name: The element, for messages.
        before: The base field's extras (``xsd_base`` / ``xsd_facets``).
        after: The target field's extras.

    Returns:
        One grade per facet that moved.
    """
    grades: List[Grade] = []
    if before.get("xsd_base") != after.get("xsd_base") and before.get("xsd_base") and after.get("xsd_base"):
        grades.append(
            (
                Severity.BREAKING,
                "wsdl.facet-narrowed",
                f"element {name!r} now restricts {after.get('xsd_base')!r} instead of {before.get('xsd_base')!r}",
            )
        )
    old = before.get("xsd_facets") if isinstance(before.get("xsd_facets"), Mapping) else {}
    new = after.get("xsd_facets") if isinstance(after.get("xsd_facets"), Mapping) else {}
    for facet in sorted(set(old) | set(new)):
        was, now = old.get(facet), new.get(facet)
        if was == now:
            continue
        if facet == "enumeration":
            removed = [v for v in was or [] if v not in (now or [])]
            added = [v for v in now or [] if v not in (was or [])]
            if was is None:
                grades.append(_narrowed(name, f"an enumeration ({', '.join(map(repr, added))}) was added"))
                continue
            if now is None:
                grades.append(_widened(name, "its enumeration was removed"))
                continue
            if removed:
                grades.append(_narrowed(name, f"enumeration value(s) {', '.join(map(repr, removed))} were removed"))
            if added:
                grades.append(_widened(name, f"enumeration value(s) {', '.join(map(repr, added))} were added"))
            continue
        if was is None:
            grades.append(_narrowed(name, f"facet {facet}={now!r} was added"))
        elif now is None:
            grades.append(_widened(name, f"facet {facet}={was!r} was removed"))
        elif facet == "pattern" or facet == "length":
            grades.append(_narrowed(name, f"facet {facet} changed from {was!r} to {now!r}"))
        else:
            old_value, new_value = _number(was), _number(now)
            if old_value is None or new_value is None:
                grades.append(_narrowed(name, f"facet {facet} changed from {was!r} to {now!r}"))
            elif (facet in _UPPER_BOUNDS) == (new_value < old_value):
                grades.append(_narrowed(name, f"facet {facet} tightened from {was} to {now}"))
            else:
                grades.append(_widened(name, f"facet {facet} loosened from {was} to {now}"))
    return grades


def _narrowed(name: str, what: str) -> Grade:
    return (
        Severity.BREAKING,
        "wsdl.facet-narrowed",
        f"element {name!r}: {what}; values the old schema accepted may now be rejected",
    )


def _widened(name: str, what: str) -> Grade:
    return (
        Severity.DANGEROUS,
        "wsdl.facet-widened",
        f"element {name!r}: {what}; strict receivers still validating against the old schema reject the new values",
    )


def grade_element(change: EntityChange) -> Optional[Grade]:
    """Grade a modified element particle, or ``None`` when nothing this classifier knows moved."""
    moved = {f.field for f in change.fields}
    if not moved <= {"type", "extras"}:
        return None
    name = change.key.rsplit(".", 1)[-1]
    before, after = _extras(change.before), _extras(change.after)
    grades: List[Grade] = []
    if "type" in moved or before.get("xsd_type") != after.get("xsd_type"):
        if not (before.get("xsd_simple_type") and before.get("xsd_simple_type") == after.get("xsd_simple_type")):
            grades.append(
                (
                    Severity.BREAKING,
                    "wsdl.element-type-changed",
                    f"element {name!r} changed type from {before.get('xsd_type')!r} to {after.get('xsd_type')!r}",
                )
            )
    grades.extend(grade_occurs(name, before, after))
    old_nil, new_nil = _is_true(before.get("xsd_nillable")), _is_true(after.get("xsd_nillable"))
    if old_nil and not new_nil:
        grades.append(
            (
                Severity.BREAKING,
                "wsdl.made-non-nillable",
                f"element {name!r} is no longer nillable; xsi:nil values are rejected",
            )
        )
    elif new_nil and not old_nil:
        grades.append(
            (
                Severity.DANGEROUS,
                "wsdl.made-nillable",
                f"element {name!r} became nillable; receivers may now get xsi:nil",
            )
        )
    if before.get("xsd_default") != after.get("xsd_default"):
        grades.append(
            (
                Severity.DANGEROUS,
                "wsdl.default-changed",
                f"element {name!r} default changed from {before.get('xsd_default')!r} to {after.get('xsd_default')!r}",
            )
        )
    grades.extend(grade_facets(name, before, after))
    rest_before = {k: v for k, v in before.items() if k not in _XSD_DETAILS and k != "xsd_type"}
    rest_after = {k: v for k, v in after.items() if k not in _XSD_DETAILS and k != "xsd_type"}
    if rest_before != rest_after:
        return None
    if not grades:
        # Only the spelling moved (`maxOccurs="1"` now written out, a facet re-ordered): same schema.
        return (
            Severity.SAFE,
            "wsdl.element-unchanged-on-the-wire",
            f"element {name!r} is declared differently but accepts the same values",
        )
    return _combine(grades)


def grade_added_element(change: EntityChange) -> Grade:
    """Grade a new element particle: required is breaking, optional dangerous (strict receivers)."""
    name = change.key.rsplit(".", 1)[-1]
    min_occurs = _occurs(_extras(change.after).get("xsd_min_occurs"))
    if min_occurs is not None and min_occurs == 0:
        return (
            Severity.DANGEROUS,
            "wsdl.element-added-optional",
            f"optional element {name!r} was added; XSD is not additive-safe — receivers validating against the old "
            "schema reject messages that carry it",
        )
    return (
        Severity.BREAKING,
        "wsdl.element-added-required",
        f"required element {name!r} was added (minOccurs ≥ 1); senders built on the old schema omit it and are "
        "rejected",
    )


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def grade_operation(change: EntityChange) -> Optional[Grade]:
    """Grade a modified operation's MEP and SOAP binding moves, or ``None`` for the baseline."""
    moved = {f.field for f in change.fields}
    if not moved <= {"kind", "extras"}:
        return None
    before, after = _extras(change.before), _extras(change.after)
    name = change.key.rsplit(".", 1)[-1].split("#")[-1]
    grades: List[Grade] = []
    if "kind" in moved:
        old_kind = change.before.get("kind") if isinstance(change.before, Mapping) else None
        new_kind = change.after.get("kind") if isinstance(change.after, Mapping) else None
        grades.append(
            (
                Severity.BREAKING,
                "wsdl.mep-changed",
                f"operation {name!r} changed its message exchange pattern ({old_kind} → {new_kind}); callers expect "
                "the old message flow",
            )
        )
    if before.pop("wsdl_soap_action", None) != (action := after.pop("wsdl_soap_action", None)):
        grades.append(
            (
                Severity.BREAKING,
                "wsdl.soap-action-changed",
                f"operation {name!r} now has soapAction {action!r}; services that dispatch on SOAPAction no longer "
                "route old requests to it",
            )
        )
    if before.pop("wsdl_soap_style", "document") != (style := after.pop("wsdl_soap_style", "document")):
        grades.append(
            (
                Severity.BREAKING,
                "wsdl.soap-style-changed",
                f"operation {name!r} moved to {style} style; the SOAP body is shaped differently on the wire",
            )
        )
    if before != after:
        return None
    return _combine(grades) if grades else None


def _combine(grades: Sequence[Grade]) -> Grade:
    """The worst of several grades, its rule id first and every rationale kept."""
    worst = _worst([severity for severity, _, _ in grades])
    rule_id = next(rule for severity, rule, _ in grades if severity is worst)
    return worst, rule_id, "; ".join(rationale for _, _, rationale in grades)


class WsdlBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a WSDL diff by SOAP / XSD compatibility (see the module docstring)."""

    format = _FORMAT_KEY
    classifier_id = "wsdl-xsd"

    def classify_change(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> ChangeClassification:
        """Grade one change; changes this classifier does not recognise use the baseline."""
        graded: Optional[Grade] = None
        if change.category is EntityCategory.FIELD and change.kind is ChangeKind.ADDED:
            graded = grade_added_element(change)
        elif change.category is EntityCategory.FIELD and change.kind is ChangeKind.MODIFIED:
            graded = grade_element(change)
        elif change.category is EntityCategory.OPERATION and change.kind is ChangeKind.MODIFIED:
            graded = grade_operation(change)
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
