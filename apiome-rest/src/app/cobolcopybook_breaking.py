"""COBOL copybook breaking-change classifier — the layout diff of MFI-21.1 (#3991).

A copybook describes a record **by position**: a program reads ``CUST-BALANCE`` as "the six bytes
at offset 42, packed". Whether a new version of the copybook breaks its readers therefore turns on
offsets, lengths and storage, not on names alone. The format-agnostic baseline
(:class:`~app.breaking_change.BuiltinBreakingChangeClassifier`) cannot see that — it grades a new
field as an optional or mandatory addition — so this classifier reads each field's
``cobol_offset`` / ``cobol_total_length`` / clauses (recorded by
:mod:`app.cobolcopybook_normalizer`) and the record's length, and leaves everything else to the
baseline.

Rule ids (all ``cobolcopybook.*``):

=======================================  ===========  ===========================================
Rule                                     Severity     When
=======================================  ===========  ===========================================
``cobolcopybook.offset-moved``           breaking     an item starts at another offset: readers
                                                      cut it, and everything after it, wrongly
``cobolcopybook.occurs-changed``         breaking     a table's OCCURS bounds or DEPENDING ON
                                                      changed
``cobolcopybook.length-changed``         breaking     an item occupies another number of bytes
``cobolcopybook.picture-changed``        breaking     the PICTURE or USAGE changed at the same
                                                      length: the bytes decode differently
``cobolcopybook.field-removed``          breaking     an item is gone
``cobolcopybook.field-inserted``         breaking     an item was added and moved others
``cobolcopybook.field-appended``         dangerous    an item was added after the last byte:
                                                      offsets hold, the record grows (LRECL)
``cobolcopybook.field-added-in-place``   safe         an item was added in spare storage: the
                                                      record length and every offset hold
``cobolcopybook.filler-reclaimed``       safe         a FILLER shrank or went to make room, and
                                                      no named item moved
``cobolcopybook.overlay-added``          dangerous    a REDEFINES layout was added: writers of
                                                      it put bytes old readers misread
``cobolcopybook.overlay-removed``        breaking     a REDEFINES layout is gone
``cobolcopybook.record-length-changed``  breaking     a record or group changed length (grew
                                                      with every offset held: dangerous)
``cobolcopybook.condition-removed``      dangerous    an 88-level condition was removed or its
                                                      value changed: programs testing it break
``cobolcopybook.condition-added``        safe         only 88-level conditions were added
``cobolcopybook.level-renumbered``       safe         only level numbers or field order numbers
                                                      changed; the bytes are the same
=======================================  ===========  ===========================================
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from .breaking_change import BuiltinBreakingChangeClassifier, ChangeClassification, Severity
from .canonical_model import CanonicalApi
from .cobolcopybook_lint import FILLER
from .diff import ChangeKind, EntityCategory, EntityChange

__all__ = ["CobolCopybookBreakingChangeClassifier"]

_FORMAT_KEY = "cobolcopybook"

#: Field extras that are bookkeeping, not layout: a change confined to them reads the same bytes.
_RENUMBER_ONLY = frozenset({"cobol_level"})

_Graded = Optional[Tuple[Severity, str, str]]


def _extras(projection: Any) -> Mapping[str, Any]:
    """The ``extras`` of a self-projection dict."""
    extras = projection.get("extras") if isinstance(projection, Mapping) else None
    return extras if isinstance(extras, Mapping) else {}


def _is_filler(projection: Any) -> bool:
    """True for a FILLER item."""
    return isinstance(projection, Mapping) and str(projection.get("name", "")).upper() == FILLER


def _record_length(api: CanonicalApi) -> Optional[int]:
    """The record's maximum length in bytes, or ``None`` when it is not computed."""
    length = api.extras.get("cobolcopybook_record_length")
    return length.get("max") if isinstance(length, Mapping) else None


def _named_offsets(api: CanonicalApi) -> Dict[str, Any]:
    """``field key → offset`` of every named (non-FILLER) item."""
    return {
        field.key: field.extras.get("cobol_offset")
        for type_ in api.types
        for field in type_.fields
        if field.name.upper() != FILLER
    }


def _layout_held(base: CanonicalApi, target: CanonicalApi) -> bool:
    """True when every named item present in both versions starts at the same, known offset."""
    before, after = _named_offsets(base), _named_offsets(target)
    common = set(before) & set(after)
    return all(before[key] is not None and before[key] == after[key] for key in common)


def _conditions(projection: Any) -> Dict[str, Any]:
    """``condition name → value`` of an item's 88-levels."""
    listed = _extras(projection).get("cobol_conditions")
    if not isinstance(listed, list):
        return {}
    return {c.get("name"): c.get("value") for c in listed if isinstance(c, Mapping)}


class CobolCopybookBreakingChangeClassifier(BuiltinBreakingChangeClassifier, register=True):
    """Grade a copybook diff by record layout: offsets, lengths, storage and overlays."""

    format = _FORMAT_KEY
    classifier_id = "cobolcopybook-layout"

    def classify_change(
        self, change: EntityChange, base: CanonicalApi, target: CanonicalApi
    ) -> ChangeClassification:
        """Grade one change; what the layout rules do not cover uses the baseline.

        Args:
            change: The diff change to grade.
            base: The copybook version the diff starts from.
            target: The copybook version the diff ends at.

        Returns:
            The :class:`ChangeClassification` for ``change``.
        """
        graded: _Graded = None
        if change.category is EntityCategory.FIELD:
            graded = self._grade_field(change, base, target)
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

    # --- fields -------------------------------------------------------------------------------

    def _grade_field(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> _Graded:
        """An item added, removed or changed."""
        projection = change.after if change.kind is ChangeKind.ADDED else change.before
        if "cobol_picture" not in _extras(projection):
            return None
        if change.kind is ChangeKind.ADDED:
            return self._layout_added(change, base, target)
        if change.kind is ChangeKind.REMOVED:
            if _is_filler(change.before) and self._reclaimed(base, target):
                return self._filler_reclaimed(change)
            return (
                Severity.BREAKING,
                "cobolcopybook.field-removed",
                f"item {change.key!r} was removed; readers of it find nothing, and the items after it "
                "move up",
            )
        return self._layout_modified(change, base, target)

    @staticmethod
    def _reclaimed(base: CanonicalApi, target: CanonicalApi) -> bool:
        """True when the record kept its length and no named item moved."""
        length = _record_length(base)
        return length is not None and length == _record_length(target) and _layout_held(base, target)

    @staticmethod
    def _filler_reclaimed(change: EntityChange) -> Tuple[Severity, str, str]:
        return (
            Severity.SAFE,
            "cobolcopybook.filler-reclaimed",
            f"{change.key!r} gave up spare storage; the record length and every named item's offset "
            "are unchanged",
        )

    def _layout_added(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> _Graded:
        """A new item: in spare room, after the last byte, or in the middle."""
        offset = _extras(change.after).get("cobol_offset")
        if self._reclaimed(base, target):
            return (
                Severity.SAFE,
                "cobolcopybook.field-added-in-place",
                f"item {change.key!r} was added in storage that was spare; the record length and every "
                "other item's offset are unchanged",
            )
        base_length = _record_length(base)
        if (
            offset is not None
            and base_length is not None
            and offset > base_length
            and _layout_held(base, target)
        ):
            return (
                Severity.DANGEROUS,
                "cobolcopybook.field-appended",
                f"item {change.key!r} was added after byte {base_length}; every offset holds, but the "
                "record grows, so a fixed-length file (LRECL) or a buffer sized to the old record "
                "truncates it",
            )
        return (
            Severity.BREAKING,
            "cobolcopybook.field-inserted",
            f"item {change.key!r} was added and moved the items after it; readers on the old layout "
            "cut them at the wrong offsets",
        )

    def _layout_modified(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> _Graded:
        """A changed item, graded by the first layout fact that moved."""
        before, after = _extras(change.before), _extras(change.after)
        moved_extras = {key for key in set(before) | set(after) if before.get(key) != after.get(key)}
        moved = {field_change.field for field_change in change.fields}
        if moved <= {"extras", "field_number"} and moved_extras <= _RENUMBER_ONLY:
            return (
                Severity.SAFE,
                "cobolcopybook.level-renumbered",
                f"only the level or order number of {change.key!r} changed; it occupies the same bytes",
            )
        if _is_filler(change.before) and self._reclaimed(base, target):
            return self._filler_reclaimed(change)
        if before.get("cobol_offset") != after.get("cobol_offset"):
            return (
                Severity.BREAKING,
                "cobolcopybook.offset-moved",
                f"item {change.key!r} moved from offset {before.get('cobol_offset')!r} to "
                f"{after.get('cobol_offset')!r}; readers on the old layout cut it, and everything "
                "after it, wrongly",
            )
        bounds = ("cobol_occurs_min", "cobol_occurs_max", "cobol_depending_on")
        if any(before.get(key) != after.get(key) for key in bounds):
            return (
                Severity.BREAKING,
                "cobolcopybook.occurs-changed",
                f"the table {change.key!r} changed from OCCURS {before.get('cobol_occurs_min')!r}–"
                f"{before.get('cobol_occurs_max')!r} to {after.get('cobol_occurs_min')!r}–"
                f"{after.get('cobol_occurs_max')!r}; its size, and the offsets after it, differ",
            )
        if before.get("cobol_total_length") != after.get("cobol_total_length"):
            return (
                Severity.BREAKING,
                "cobolcopybook.length-changed",
                f"item {change.key!r} changed from {before.get('cobol_total_length')!r} to "
                f"{after.get('cobol_total_length')!r} bytes; readers on the old layout read the wrong "
                "bytes",
            )
        if (before.get("cobol_picture"), before.get("cobol_usage")) != (
            after.get("cobol_picture"),
            after.get("cobol_usage"),
        ):
            return (
                Severity.BREAKING,
                "cobolcopybook.picture-changed",
                f"item {change.key!r} changed from PIC {before.get('cobol_picture')!r} "
                f"{before.get('cobol_usage') or 'DISPLAY'} to PIC {after.get('cobol_picture')!r} "
                f"{after.get('cobol_usage') or 'DISPLAY'}; the same bytes now decode differently",
            )
        overlay = self._grade_overlay_field(change, before, after)
        if overlay is not None:
            return overlay
        old_conditions, new_conditions = _conditions(change.before), _conditions(change.after)
        if old_conditions != new_conditions:
            lost = {name for name, value in old_conditions.items() if new_conditions.get(name, object()) != value}
            if lost:
                return (
                    Severity.DANGEROUS,
                    "cobolcopybook.condition-removed",
                    f"88-level condition(s) {', '.join(sorted(map(str, lost)))} of {change.key!r} were "
                    "removed or changed value; programs that test them stop compiling or test something "
                    "else",
                )
            return (
                Severity.SAFE,
                "cobolcopybook.condition-added",
                f"88-level conditions were added to {change.key!r}; the item's bytes are unchanged",
            )
        return None

    @staticmethod
    def _grade_overlay_field(
        change: EntityChange, before: Mapping[str, Any], after: Mapping[str, Any]
    ) -> _Graded:
        """The item gained or lost REDEFINES layouts (its type became, or stopped being, an overlay)."""
        old = set(before.get("cobol_redefined_by") or ())
        new = set(after.get("cobol_redefined_by") or ())
        if old - new:
            return (
                Severity.BREAKING,
                "cobolcopybook.overlay-removed",
                f"the REDEFINES layout(s) {', '.join(sorted(old - new))} of {change.key!r} are gone; "
                "programs reading the storage that way find nothing",
            )
        if new - old:
            return (
                Severity.DANGEROUS,
                "cobolcopybook.overlay-added",
                f"{change.key!r} is now also laid out as {', '.join(sorted(new - old))} (REDEFINES); "
                "records written that way are misread by programs that know only the old layouts",
            )
        return None

    # --- types --------------------------------------------------------------------------------

    def _grade_type(self, change: EntityChange, base: CanonicalApi, target: CanonicalApi) -> _Graded:
        """A REDEFINES overlay added, removed or changed; a record or group that changed length."""
        projection = change.after if change.kind is ChangeKind.ADDED else change.before
        extras = _extras(projection)
        kind = extras.get("cobol_kind")
        if kind == "redefines":
            return self._grade_overlay_type(change)
        if kind != "group" or change.kind is not ChangeKind.MODIFIED:
            return None
        old_length = _extras(change.before).get("cobol_length") or {}
        new_length = _extras(change.after).get("cobol_length") or {}
        if old_length == new_length:
            return None
        old_max, new_max = old_length.get("max"), new_length.get("max")
        if old_max is not None and new_max is not None and new_max > old_max and _layout_held(base, target):
            return (
                Severity.DANGEROUS,
                "cobolcopybook.record-length-changed",
                f"{change.key!r} grew from {old_max} to {new_max} bytes with every offset held; a "
                "fixed-length file or buffer sized to the old length truncates it",
            )
        return (
            Severity.BREAKING,
            "cobolcopybook.record-length-changed",
            f"{change.key!r} changed from {old_max!r} to {new_max!r} bytes; readers on the old layout "
            "read the wrong bytes",
        )

    @staticmethod
    def _grade_overlay_type(change: EntityChange) -> _Graded:
        """The union of a REDEFINES overlay."""
        if change.kind is ChangeKind.ADDED:
            return (
                Severity.DANGEROUS,
                "cobolcopybook.overlay-added",
                f"the storage overlay {change.key!r} was added (REDEFINES); records written in a new "
                "layout are misread by programs that know only the old one",
            )
        if change.kind is ChangeKind.REMOVED:
            return (
                Severity.BREAKING,
                "cobolcopybook.overlay-removed",
                f"the storage overlay {change.key!r} is gone; programs reading the storage in its "
                "other layouts find nothing",
            )
        old = list((change.before or {}).get("union_members") or [])
        new = list((change.after or {}).get("union_members") or [])
        if set(old) - set(new):
            return (
                Severity.BREAKING,
                "cobolcopybook.overlay-removed",
                f"layout(s) {', '.join(sorted(set(old) - set(new)))} of {change.key!r} are gone",
            )
        if set(new) - set(old):
            return (
                Severity.DANGEROUS,
                "cobolcopybook.overlay-added",
                f"layout(s) {', '.join(sorted(set(new) - set(old)))} were added to {change.key!r}; "
                "records written that way are misread by programs that know only the old layouts",
            )
        return None
