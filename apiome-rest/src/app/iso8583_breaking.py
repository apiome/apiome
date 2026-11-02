"""ISO 8583 breaking-change classifier — MFI-20.6 (#3990).

An ISO 8583 message definition is a Message Type Indicator plus the data elements a bitmap flags,
each cut from the wire by its **number**, **type** and **length**. The format-agnostic baseline
(:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) grades a changed length or type as
"some attribute moved" and a changed sample value as dangerous; this classifier grades the wire
facts and leaves everything else to the baseline.

Rule ids (all ``iso8583.*``):

=================================  ===========  ==================================================
Rule                               Severity     When
=================================  ===========  ==================================================
``iso8583.mti-changed``            breaking     the message's MTI changed: it is another message
``iso8583.de-removed``             breaking     a data element the bitmap flagged is gone
``iso8583.de-added``               dangerous    a data element now flagged: counterparties on the
                                                old definition never send it
``iso8583.de-length-changed``      breaking     a data element's length changed: the wire no
                                                longer cuts where it did
``iso8583.de-type-changed``        breaking     a data element's type changed (``n`` → ``ans``)
``iso8583.de-renamed``             safe         only the data element's descriptive name changed
``iso8583.sample-value-changed``   safe         only the sample value changed: not the contract
=================================  ===========  ==================================================
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["Iso8583BreakingChangeClassifier"]

_FORMAT_KEY = "iso8583"


def _extras(projection: Any) -> Mapping[str, Any]:
    """The ``extras`` of a field / type self-projection dict."""
    extras = projection.get("extras") if isinstance(projection, Mapping) else None
    return extras if isinstance(extras, Mapping) else {}


def _is_data_element(projection: Any) -> bool:
    return "iso8583_de_number" in _extras(projection)


class Iso8583BreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade an ISO 8583 diff by MTI, data element number, type and length."""

    format = _FORMAT_KEY
    classifier_id = "iso8583-data-element"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; what the ISO 8583 rules do not cover uses the baseline.

        Args:
            change: The diff change to grade.
            base: The definition the diff starts from.
            target: The definition the diff ends at.

        Returns:
            The :class:`ChangeClassification` for ``change``.
        """
        graded: Optional[Tuple[Severity, str, str]] = None
        if change.category is EntityCategory.FIELD:
            graded = self._grade_field(change)
        elif change.category is EntityCategory.TYPE:
            graded = self._grade_type(change, base, target)
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
    def _grade_field(change: EntityChange) -> Optional[Tuple[Severity, str, str]]:
        """``(severity, rule_id, rationale)`` for a data-element field change, else ``None``."""
        projection = change.after if change.kind is ChangeKind.ADDED else change.before
        if not _is_data_element(projection):
            return None
        number = _extras(projection).get("iso8583_de_number")
        if change.kind is ChangeKind.REMOVED:
            return (
                Severity.BREAKING,
                "iso8583.de-removed",
                f"data element {number} ({change.key!r}) was removed; counterparties on the old "
                "definition still set its bit and send it",
            )
        if change.kind is ChangeKind.ADDED:
            return (
                Severity.DANGEROUS,
                "iso8583.de-added",
                f"data element {number} ({change.key!r}) was added; counterparties on the old "
                "definition never set its bit, so a receiver that expects it rejects their messages",
            )
        before, after = _extras(change.before), _extras(change.after)
        if before.get("iso8583_de_length") != after.get("iso8583_de_length"):
            return (
                Severity.BREAKING,
                "iso8583.de-length-changed",
                f"data element {number} changed its length from {before.get('iso8583_de_length')!r} "
                f"to {after.get('iso8583_de_length')!r}; the wire no longer cuts where it did",
            )
        if before.get("iso8583_de_type") != after.get("iso8583_de_type"):
            return (
                Severity.BREAKING,
                "iso8583.de-type-changed",
                f"data element {number} changed its type from {before.get('iso8583_de_type')!r} to "
                f"{after.get('iso8583_de_type')!r}; counterparties on the old definition encode it wrongly",
            )
        moved = {field_change.field for field_change in change.fields}
        if moved <= {"extras", "description"} and before.get("iso8583_de_name") != after.get("iso8583_de_name"):
            return (
                Severity.SAFE,
                "iso8583.de-renamed",
                f"data element {number} is now described as {after.get('iso8583_de_name')!r}; "
                "the wire is unchanged",
            )
        if moved <= {"default"}:
            return (
                Severity.SAFE,
                "iso8583.sample-value-changed",
                f"data element {number} carries another sample value; the definition is unchanged",
            )
        return None

    @staticmethod
    def _grade_type(
        change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> Optional[Tuple[Severity, str, str]]:
        """Grade the message record when the MTI changed; ``None`` for everything else.

        The MTI is the namespace of every key, so a definition whose MTI changed diffs as its
        message record removed and another added: both are graded as the one MTI change.
        """
        projection = change.after if change.kind is ChangeKind.ADDED else change.before
        if _extras(projection).get("iso8583_kind") != "message":
            return None
        before_mti, after_mti = base.extras.get("iso8583_mti"), target.extras.get("iso8583_mti")
        if before_mti != after_mti:
            return (
                Severity.BREAKING,
                "iso8583.mti-changed",
                f"the message type indicator changed from {before_mti!r} to {after_mti!r}; "
                "it is another message",
            )
        return None
