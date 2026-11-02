"""FIX Orchestra breaking-change classifier — MFI-20.4 (#3988).

A FIX Orchestra repository is a venue's or a firm's **dialect** of FIX: which messages it
accepts, which fields each carries, and with what ``presence``. Two repositories — one venue
against another, or one release of a venue's rules of engagement against the next — differ in
ways the format-agnostic baseline (:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`)
cannot grade: a FIX field is identified on the wire by its **tag**, not its name; ``presence``
decides whether a counterparty's existing messages are still accepted; a **code set** is the list
of values a field may carry; and a message is routed by its ``msgType``. This classifier grades
those with FIX semantics and leaves everything else to the baseline.

Rule ids (all ``fix-orchestra.*``):

==========================================  ===========  ======================================
Rule                                        Severity     When
==========================================  ===========  ======================================
``fix-orchestra.field-renamed``             dangerous    same tag and type, a new field name
``fix-orchestra.tag-reused``                breaking     same tag, a different type
``fix-orchestra.tag-changed``               breaking     same field name, a different tag
``fix-orchestra.required-field-added``      breaking     a new ``required`` / ``constant`` field:
                                                         senders on the old dialect omit it
``fix-orchestra.optional-field-added``      safe         a new optional / conditional / ignored
                                                         / forbidden field
``fix-orchestra.required-field-removed``    breaking     a ``required`` / ``constant`` field
                                                         removed
``fix-orchestra.optional-field-removed``    dangerous    any other field removed: a strict
                                                         receiver rejects what senders still send
``fix-orchestra.made-required``             breaking     presence tightened to ``required`` /
                                                         ``constant``
``fix-orchestra.made-forbidden``            breaking     presence tightened to ``forbidden``:
                                                         senders that send it are rejected
``fix-orchestra.made-optional``             dangerous    ``required`` / ``constant`` relaxed
``fix-orchestra.made-ignored``              dangerous    the field is now accepted but ignored
``fix-orchestra.presence-relaxed``          safe         ``forbidden`` → optional / conditional
``fix-orchestra.constant-changed``          breaking     a ``constant`` field's value changed
``fix-orchestra.rules-changed``             dangerous    a conditional field's ``when`` /
                                                         ``assign`` rules changed
``fix-orchestra.code-removed``              breaking     a code set lost a code
``fix-orchestra.code-value-changed``        breaking     a code's wire value changed
``fix-orchestra.code-added``                safe         a code set gained a code
``fix-orchestra.msgtype-changed``           breaking     a message's ``msgType`` changed
==========================================  ===========  ======================================
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi, CanonicalField
from .diff import ChangeKind, EntityCategory, EntityChange
from .numbered_field_breaking import enum_value_changes, is_enum

__all__ = ["FixOrchestraBreakingChangeClassifier"]

_FORMAT_KEY = "fix-orchestra"

#: Presence values under which a counterparty must send the field.
_MANDATORY = frozenset({"required", "constant"})


def _extras(projection: Any) -> Mapping[str, Any]:
    """The ``extras`` of a field / type, from a model or its self-projection dict."""
    if isinstance(projection, CanonicalField):
        return projection.extras
    if isinstance(projection, Mapping):
        extras = projection.get("extras")
        return extras if isinstance(extras, Mapping) else {}
    return {}


def _presence(projection: Any) -> str:
    """The ref's ``presence`` (``optional`` when the field records none)."""
    value = _extras(projection).get("fix_presence")
    return value if isinstance(value, str) else "optional"


def _field_index(api: CanonicalApi) -> Dict[str, Tuple[str, CanonicalField]]:
    """Field key → ``(owning type key, field)`` for every field of ``api``."""
    return {field.key: (api_type.key, field) for api_type in api.types for field in api_type.fields}


def _type_shape(field: CanonicalField) -> Any:
    """A field's type with nullability (presence) left out, for comparing two fields."""
    return field.type.model_dump(exclude={"nullable"})


def _counterpart(
    field_key: str,
    *,
    own: Mapping[str, Tuple[str, CanonicalField]],
    other: Mapping[str, Tuple[str, CanonicalField]],
) -> Tuple[Optional[CanonicalField], Optional[CanonicalField]]:
    """The field and, on the other side of the diff, a *different* field of its type with its tag."""
    entry = own.get(field_key)
    if entry is None:
        return None, None
    type_key, field = entry
    if field.field_number is None:
        return field, None
    for other_key, (other_type, candidate) in other.items():
        if (
            other_type == type_key
            and candidate.field_number == field.field_number
            and other_key != field_key
            and other_key not in own
        ):
            return field, candidate
    return field, None


def _rules(projection: Any) -> Any:
    """The ``fix_rules`` a conditional field records on its constraints, or ``None``."""
    if isinstance(projection, CanonicalField):
        return projection.constraints.extras.get("fix_rules") if projection.constraints else None
    constraints = projection.get("constraints") if isinstance(projection, Mapping) else None
    extras = constraints.get("extras") if isinstance(constraints, Mapping) else None
    return extras.get("fix_rules") if isinstance(extras, Mapping) else None


def _constant_value(projection: Any) -> Any:
    """The value a ``constant`` field is pinned to (its default), or ``None``."""
    if isinstance(projection, CanonicalField):
        return projection.default
    return projection.get("default") if isinstance(projection, Mapping) else None


class FixOrchestraBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a FIX Orchestra diff with tag, presence, code-set and msgType rules."""

    format = _FORMAT_KEY
    classifier_id = "fix-orchestra-dialect"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; what the FIX rules do not cover uses the baseline.

        Args:
            change: The diff change to grade.
            base: The repository the diff starts from.
            target: The repository the diff ends at.

        Returns:
            The :class:`ChangeClassification` for ``change``.
        """
        graded: Optional[Tuple[Severity, str, str]] = None
        if change.category is EntityCategory.FIELD:
            graded = self._grade_field(change, base, target)
        elif change.category is EntityCategory.TYPE and change.kind is ChangeKind.MODIFIED:
            graded = self._grade_type(change)
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

    # --- fields --------------------------------------------------------------------------

    def _grade_field(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> Optional[Tuple[Severity, str, str]]:
        """``(severity, rule_id, rationale)`` for a field change, or ``None`` for the baseline."""
        base_fields, target_fields = _field_index(base), _field_index(target)
        if change.kind is ChangeKind.REMOVED:
            field, counterpart = _counterpart(change.key, own=base_fields, other=target_fields)
            return self._grade_pair(change.key, field, counterpart, removed=True)
        if change.kind is ChangeKind.ADDED:
            field, counterpart = _counterpart(change.key, own=target_fields, other=base_fields)
            return self._grade_pair(change.key, field, counterpart, removed=False)
        return self._grade_modified_field(change)

    @staticmethod
    def _grade_pair(
        key: str,
        field: Optional[CanonicalField],
        counterpart: Optional[CanonicalField],
        *,
        removed: bool,
    ) -> Optional[Tuple[Severity, str, str]]:
        """Grade a removed / added field, paired by tag with its counterpart when it has one."""
        if field is None:
            return None
        tag = field.field_number
        if counterpart is not None:
            old, new = (field, counterpart) if removed else (counterpart, field)
            if _type_shape(old) == _type_shape(new):
                return (
                    Severity.DANGEROUS,
                    "fix-orchestra.field-renamed",
                    f"tag {tag} was renamed from {old.name!r} to {new.name!r}; the wire is "
                    "unchanged, but generated code and documentation see the new name",
                )
            return (
                Severity.BREAKING,
                "fix-orchestra.tag-reused",
                f"tag {tag} now carries {new.name!r} of another type than {old.name!r}; "
                "counterparties on the old dialect read it wrongly",
            )
        presence = _presence(field)
        if removed:
            if presence in _MANDATORY:
                return (
                    Severity.BREAKING,
                    "fix-orchestra.required-field-removed",
                    f"{presence} field {key!r} (tag {tag}) was removed; messages built on the "
                    "old dialect still carry it",
                )
            return (
                Severity.DANGEROUS,
                "fix-orchestra.optional-field-removed",
                f"{presence} field {key!r} (tag {tag}) was removed; a strict receiver rejects "
                "the messages that still send it",
            )
        if presence in _MANDATORY:
            return (
                Severity.BREAKING,
                "fix-orchestra.required-field-added",
                f"{presence} field {key!r} (tag {tag}) was added; senders on the old dialect "
                "omit it and are rejected",
            )
        return (
            Severity.SAFE,
            "fix-orchestra.optional-field-added",
            f"{presence} field {key!r} (tag {tag}) was added; senders on the old dialect "
            "need not send it",
        )

    @staticmethod
    def _grade_modified_field(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """Grade a tag move, a presence transition, a constant or a rule change on a kept field."""
        moved = {field_change.field: field_change for field_change in change.fields}
        if "field_number" in moved:
            number = moved["field_number"]
            return (
                Severity.BREAKING,
                "fix-orchestra.tag-changed",
                f"field {change.key!r} moved from tag {number.before} to tag {number.after}; "
                "counterparties on the old dialect no longer find it",
            )
        before, after = _presence(change.before), _presence(change.after)
        if before != after:
            return FixOrchestraBreakingChangeClassifier._grade_presence(change.key, before, after)
        if after == "constant" and _constant_value(change.before) != _constant_value(change.after):
            return (
                Severity.BREAKING,
                "fix-orchestra.constant-changed",
                f"constant field {change.key!r} changed from {_constant_value(change.before)!r} "
                f"to {_constant_value(change.after)!r}; messages carrying the old value are rejected",
            )
        if _rules(change.before) != _rules(change.after):
            return (
                Severity.DANGEROUS,
                "fix-orchestra.rules-changed",
                f"the presence rules of field {change.key!r} changed; messages that satisfied "
                "the old rules may not satisfy the new ones",
            )
        return None

    @staticmethod
    def _grade_presence(key: str, before: str, after: str) -> Tuple[Severity, str, str]:
        """Grade a presence transition ``before`` → ``after`` on a kept field."""
        if after in _MANDATORY and before not in _MANDATORY:
            return (
                Severity.BREAKING,
                "fix-orchestra.made-required",
                f"field {key!r} went from {before} to {after}; senders that omit it are rejected",
            )
        if after == "forbidden":
            return (
                Severity.BREAKING,
                "fix-orchestra.made-forbidden",
                f"field {key!r} went from {before} to forbidden; senders that send it are rejected",
            )
        if after == "ignored":
            return (
                Severity.DANGEROUS,
                "fix-orchestra.made-ignored",
                f"field {key!r} went from {before} to ignored; what senders put in it no longer "
                "has effect",
            )
        if before in _MANDATORY:
            return (
                Severity.DANGEROUS,
                "fix-orchestra.made-optional",
                f"field {key!r} went from {before} to {after}; receivers on the old dialect "
                "still expect it",
            )
        return (
            Severity.SAFE,
            "fix-orchestra.presence-relaxed",
            f"field {key!r} went from {before} to {after}; every message valid before is "
            "still valid",
        )

    # --- types: code sets and messages ---------------------------------------------------

    @staticmethod
    def _grade_type(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """Grade a code set's values or a message's ``msgType``; ``None`` for the baseline."""
        before_msg = _extras(change.before).get("fix_msg_type")
        after_msg = _extras(change.after).get("fix_msg_type")
        if before_msg is not None and after_msg is not None and before_msg != after_msg:
            return (
                Severity.BREAKING,
                "fix-orchestra.msgtype-changed",
                f"message {change.key!r} changed its msgType from {before_msg!r} to "
                f"{after_msg!r}; counterparties route it as another message",
            )
        if not (is_enum(change.before) and is_enum(change.after)):
            return None
        moved = {field_change.field for field_change in change.fields}
        if moved - {"enum_values"}:
            return None  # something beyond the codes moved: let the baseline grade it
        changed, removed = enum_value_changes(change.before, change.after)
        added = FixOrchestraBreakingChangeClassifier._added_codes(change.before, change.after)
        if removed:
            return (
                Severity.BREAKING,
                "fix-orchestra.code-removed",
                f"code set {change.key!r} lost the code(s) {', '.join(removed)}; messages "
                "carrying them are rejected",
            )
        if changed:
            return (
                Severity.BREAKING,
                "fix-orchestra.code-value-changed",
                f"code set {change.key!r} changed the wire value of {', '.join(changed)}; "
                "counterparties on the old dialect send the old value",
            )
        if added:
            return (
                Severity.SAFE,
                "fix-orchestra.code-added",
                f"code set {change.key!r} gained the code(s) {', '.join(added)}; every value "
                "valid before is still valid",
            )
        return None

    @staticmethod
    def _added_codes(before: Any, after: Any) -> List[str]:
        """The code names present after but not before, sorted."""

        def names(projection: Any) -> set:
            values = projection.get("enum_values") if isinstance(projection, Mapping) else None
            return {str(v["name"]) for v in values or [] if isinstance(v, Mapping) and v.get("name") is not None}

        return sorted(names(after) - names(before))
