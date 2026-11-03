"""EDI X12 / UN/EDIFACT breaking-change classifiers — MFI-20.5 (#3989).

An EDI item is a transaction set (X12) or message (EDIFACT) inferred from an interchange: a root
record — ``TransactionSet850`` / ``MessageINVOIC`` — holding the elements of the segments that occur
once, plus one list field and record per segment that repeats (``PO1``, ``LIN``). Each element is
named by its **reference designator**, the segment id and the element's position (``BEG03``,
``DTM01-2``), so its place on the wire is in its key. The values are a *sample* of one interchange.

The format-agnostic baseline (:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) reads
that model as a schema and misgrades it four ways: a new sample value is "dangerous", an element
after an inserted one is "breaking" because its ordinal in the flattened record moved, a new segment
is "safe", and a segment that occurs once in the new sample but repeated in the old reads as removed.
These classifiers grade the EDI facts and leave everything else to the baseline.

Rule ids (``<format>`` is ``edix12`` or ``edifact``):

========================================  ===========  ===========================================
Rule                                      Severity     When
========================================  ===========  ===========================================
``edix12.transaction-set-changed``        breaking     the transaction set (``ST01``) — or, for
``edifact.message-type-changed``                       EDIFACT, the message type — changed
``<format>.segment-removed``              breaking     a segment is no longer sent
``<format>.element-removed``              breaking     a segment no longer carries an element
``<format>.segment-added``                dangerous    a segment is now sent: a receiver that
                                                       validates against the old guide rejects it
``<format>.element-added``                dangerous    a segment now carries another element
``<format>.segment-repetition-changed``   dangerous    a segment repeats in one sample and occurs
                                                       once in the other: the guide's maximum use
                                                       decides whether that is allowed
``<format>.ordinal-shifted``              safe         only a field's ordinal in the flattened
                                                       record moved; its reference is unchanged
``<format>.sample-value-changed``         safe         only the sample value changed
========================================  ===========  ===========================================
"""

from __future__ import annotations

import re
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["EdifactBreakingChangeClassifier", "EdiX12BreakingChangeClassifier", "segment_of"]

#: A reference designator: the segment id (two or three characters), the element's two-digit
#: position and, for an EDIFACT composite, ``-`` and the component index (``DTM01-2``).
_REFERENCE = re.compile(r"^([A-Z0-9]{2,3}?)(\d{2})(?:-\d+)?$")

#: The attributes a sample-to-sample diff moves without changing the definition.
_SAMPLE_ATTRIBUTES = frozenset({"default", "field_number"})

Graded = Tuple[Severity, str, str]


def segment_of(reference: str) -> Optional[str]:
    """The segment id of an element reference designator.

    Args:
        reference: ``BEG03``, ``PO101``, ``DTM01-2`` …

    Returns:
        ``BEG``, ``PO1``, ``DTM`` — or ``None`` when *reference* is not a reference designator.
    """
    match = _REFERENCE.match(reference or "")
    return match.group(1) if match else None


def _projection(change: EntityChange) -> Mapping[str, Any]:
    """The side of the change that exists: ``after`` for an addition, else ``before``."""
    projection = change.after if change.kind is ChangeKind.ADDED else change.before
    return projection if isinstance(projection, Mapping) else {}


def _is_segment_reference(projection: Mapping[str, Any]) -> bool:
    """Whether a field projection is a repeating segment (a list of a segment record)."""
    type_ref = projection.get("type")
    return isinstance(type_ref, Mapping) and type_ref.get("item") is not None


class _EdiShape:
    """What one EDI model sends: its segments, and where each element reference sits.

    Attributes:
        repeating: Segments with a record of their own (they repeat in the sample).
        single: Segments whose elements sit on the root record (they occur once).
        elements: Every element reference, wherever it sits.
    """

    def __init__(self, api: CanonicalApi, root_prefix: str) -> None:
        self.repeating: FrozenSet[str] = frozenset(
            type_.name for type_ in api.types if not type_.name.startswith(root_prefix)
        )
        root_names = [
            field.name
            for type_ in api.types
            if type_.name.startswith(root_prefix)
            for field in type_.fields
            if field.type.item is None
        ]
        self.single: FrozenSet[str] = frozenset(
            segment for segment in (segment_of(name) for name in root_names) if segment
        )
        self.elements: FrozenSet[str] = frozenset(root_names) | frozenset(
            field.name
            for type_ in api.types
            if not type_.name.startswith(root_prefix)
            for field in type_.fields
        )

    @property
    def segments(self) -> FrozenSet[str]:
        """Every segment the model sends."""
        return self.repeating | self.single


class _EdiBreakingChangeClassifier(BuiltinBreakingChangeClassifier):
    """Grade an EDI sample-to-sample diff by segment, element reference and repetition.

    Subclasses name the format, the root record's name prefix, the extras key of the transaction
    set / message type, and how to say "transaction set" in a rationale.
    """

    root_prefix: str = ""
    set_extras_key: str = ""
    set_rule: str = ""
    set_noun: str = ""

    def __init__(self) -> None:
        super().__init__()
        self._shapes: Dict[int, _EdiShape] = {}

    def _shape(self, api: CanonicalApi) -> _EdiShape:
        """The shape of *api*, computed once per model this classifier grades."""
        shape = self._shapes.get(id(api))
        if shape is None:
            shape = _EdiShape(api, self.root_prefix)
            self._shapes[id(api)] = shape
        return shape

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; what the EDI rules do not cover uses the baseline.

        Args:
            change: The diff change to grade.
            base: The model the diff starts from.
            target: The model the diff ends at.

        Returns:
            The :class:`ChangeClassification` for ``change``.
        """
        graded = self._grade_edi(change, base, target)
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

    def _rule(self, name: str) -> str:
        return f"{self.format}.{name}"

    def _grade_edi(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> Optional[Graded]:
        """``(severity, rule_id, rationale)`` for an EDI change, else ``None``."""
        before_set, after_set = base.extras.get(self.set_extras_key), target.extras.get(self.set_extras_key)
        if before_set != after_set:
            # The set is every key's namespace, so a changed set diffs as everything removed and
            # added: all of it is the one change.
            return (
                Severity.BREAKING,
                self.set_rule,
                f"the {self.set_noun} changed from {before_set!r} to {after_set!r}; it is another "
                f"{self.set_noun}, with its own definition",
            )
        projection = _projection(change)
        if change.category is EntityCategory.TYPE and change.kind is not ChangeKind.MODIFIED:
            name = str(projection.get("name") or "")
            if name.startswith(self.root_prefix):
                return None
            return self._grade_segment(change.kind, name, base, target)
        if change.category is not EntityCategory.FIELD:
            return None
        if _is_segment_reference(projection):
            name = str(projection.get("name") or "")
            if change.kind is not ChangeKind.MODIFIED:
                return self._grade_segment(change.kind, name, base, target)
            if {field_change.field for field_change in change.fields} == {"field_number"}:
                return self._ordinal_shifted(f"segment {name}")
            return None
        return self._grade_element(change, str(projection.get("name") or ""), base, target)

    def _grade_segment(
        self, kind: ChangeKind, segment: str, base: CanonicalApi, target: CanonicalApi
    ) -> Graded:
        """Grade a repeating segment's record (or list field) appearing or disappearing."""
        old, new = self._shape(base), self._shape(target)
        if kind is ChangeKind.REMOVED and segment in new.segments:
            return self._repetition(segment, "repeated in the old sample and occurs once in the new one")
        if kind is ChangeKind.ADDED and segment in old.segments:
            return self._repetition(segment, "occurred once in the old sample and repeats in the new one")
        if kind is ChangeKind.REMOVED:
            return (
                Severity.BREAKING,
                self._rule("segment-removed"),
                f"segment {segment} is no longer sent; a receiver that requires it rejects the interchange",
            )
        return self._added_segment(segment)

    def _grade_element(
        self, change: EntityChange, reference: str, base: CanonicalApi, target: CanonicalApi
    ) -> Optional[Graded]:
        """Grade an element field: removed, added, moved between records, or a new sample value."""
        segment = segment_of(reference)
        if segment is None:
            return None
        old, new = self._shape(base), self._shape(target)
        if change.kind is ChangeKind.MODIFIED:
            moved = {field_change.field for field_change in change.fields}
            if not moved or not moved <= _SAMPLE_ATTRIBUTES:
                return None
            if "default" in moved:
                return (
                    Severity.SAFE,
                    self._rule("sample-value-changed"),
                    f"element {reference} carries another sample value; the definition is unchanged",
                )
            return self._ordinal_shifted(f"element {reference}")
        if change.kind is ChangeKind.REMOVED:
            if reference in new.elements:
                return self._repetition(segment, "changed how often it occurs between the two samples")
            if segment not in new.segments:
                return (
                    Severity.BREAKING,
                    self._rule("segment-removed"),
                    f"segment {segment} is no longer sent, so neither is its element {reference}; a "
                    "receiver that requires it rejects the interchange",
                )
            return (
                Severity.BREAKING,
                self._rule("element-removed"),
                f"segment {segment} no longer carries element {reference}; a receiver that requires it "
                "rejects the segment",
            )
        if reference in old.elements:
            return self._repetition(segment, "changed how often it occurs between the two samples")
        if segment not in old.segments:
            return self._added_segment(segment)
        return (
            Severity.DANGEROUS,
            self._rule("element-added"),
            f"segment {segment} now carries element {reference}; a receiver that validates against the "
            "old implementation guide rejects the segment",
        )

    def _ordinal_shifted(self, what: str) -> Graded:
        """A field whose only move is its ordinal in the flattened record: the wire is unchanged."""
        return (
            Severity.SAFE,
            self._rule("ordinal-shifted"),
            f"{what} moved only in the flattened record because a segment before it was added or "
            "removed; its reference, and so its place on the wire, is unchanged",
        )

    def _added_segment(self, segment: str) -> Graded:
        return (
            Severity.DANGEROUS,
            self._rule("segment-added"),
            f"segment {segment} is now sent; a receiver that validates against the old implementation "
            "guide rejects the interchange",
        )

    def _repetition(self, segment: str, how: str) -> Graded:
        return (
            Severity.DANGEROUS,
            self._rule("segment-repetition-changed"),
            f"segment {segment} {how}; the implementation guide's maximum use decides whether a "
            "receiver accepts it",
        )


class EdiX12BreakingChangeClassifier(_EdiBreakingChangeClassifier, register=True):
    """Grade an EDI X12 diff by transaction set, segment, element reference and repetition."""

    format = "edix12"
    classifier_id = "edix12-segment"
    root_prefix = "TransactionSet"
    set_extras_key = "x12_set_id"
    set_rule = "edix12.transaction-set-changed"
    set_noun = "transaction set"


class EdifactBreakingChangeClassifier(_EdiBreakingChangeClassifier, register=True):
    """Grade a UN/EDIFACT diff by message type, segment, element reference and repetition."""

    format = "edifact"
    classifier_id = "edifact-segment"
    root_prefix = "Message"
    set_extras_key = "edifact_message_type"
    set_rule = "edifact.message-type-changed"
    set_noun = "message type"
