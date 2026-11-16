"""Protobuf structural rules graded per ``buf breaking`` category — XPC-4.3 (#5747).

``buf breaking`` sorts its rules into four nested categories (``WIRE`` ⊂ ``WIRE_JSON`` ⊂
``PACKAGE`` ⊂ ``FILE``), so one change can be safe on the wire yet break generated code. The
format-agnostic baseline grades every change once; these rules grade the Protobuf-specific ones
under **each** category, from the canonical model alone (no ``buf`` binary needed), so
:class:`app.proto_breaking.ProtobufBreakingChangeClassifier` can answer at whichever category a
caller asks for.

=============================================  ======  =========  =======  ======
Finding (rule slug)                            WIRE    WIRE_JSON  PACKAGE  FILE
=============================================  ======  =========  =======  ======
``reserved-removed``                           D       D          D        D
``reserved-number-reused`` / ``-name-reused``  B       B          B        B
``field-deleted-unreserved`` (number free)     D       B          B        B
``field-deleted-unreserved`` (name free)       S       B          B        B
``field-deleted`` (number and name reserved)   S       S          B        B
``field-renamed`` (same number)                S       B          B        B
``field-number-reused`` (new type)             B       B          B        B
``json-name-changed``                          S       B          B        B
``type-moved-file``                            S       S          S        B
``package-changed``                            B       B          B        B
``enum-value-number-reused`` (renamed)         S       B          B        B
``enum-value-number-changed``                  B       B          B        B
``oneof-membership-changed``                   B       B          B        B
``cardinality-changed`` (``repeated``)         B       B          B        B
``required-changed``                           B       B          B        B
``presence-changed`` (``optional`` keyword)    S       S          B        B
=============================================  ======  =========  =======  ======

(S = safe, D = dangerous, B = breaking.) The grades follow Buf's rule placement
(https://buf.build/docs/breaking/rules) except where the roadmap decided otherwise: removing a
``reserved`` entry is dangerous rather than breaking, and deleting a field whose number is not
reserved is dangerous rather than breaking under ``WIRE``. Both differences are recorded in the
Buf corpus fixture (``tests/fixtures/proto_breaking_categories``).

Each finding's ``rule_id`` names the narrowest category where it is at its worst —
``protobuf.wire_json.json-name-changed`` — and its rationale lists every category's grade, so a
reader can see that a change is wire-safe but file-breaking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from .breaking_change import Severity, _worst
from .canonical_model import CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from .diff import EntityCategory

__all__ = [
    "CATEGORY_ORDER",
    "COMPATIBLE_RULE_ID",
    "EXPLAINED_FIELD_EXTRAS",
    "EXPLAINED_TYPE_EXTRAS",
    "ProtoFindings",
    "ProtoRuleFinding",
    "category_findings",
    "category_rule_id",
]

#: The four ``buf breaking`` categories, least strict first. Kept as plain strings here so this
#: module does not import :mod:`app.proto_breaking` (which imports it).
CATEGORY_ORDER: Tuple[str, ...] = ("WIRE", "WIRE_JSON", "PACKAGE", "FILE")

#: Rule id of a modified change whose every movement these rules explain without a finding (a
#: reservation added, a oneof declaration list re-read): compatible under every category.
COMPATIBLE_RULE_ID = "protobuf.compatible"

#: Field ``extras`` keys these rules grade; a change confined to them is fully explained.
EXPLAINED_FIELD_EXTRAS = frozenset(
    {"label", "proto3_optional", "field_presence", "oneof", "json_name"}
)

#: Type ``extras`` keys these rules grade (the oneof declaration list is graded per member).
EXPLAINED_TYPE_EXTRAS = frozenset({"reserved_ranges", "reserved_names", "oneofs"})

#: Severities per category, in :data:`CATEGORY_ORDER`.
Grades = Tuple[Severity, Severity, Severity, Severity]

_S, _D, _B = Severity.SAFE, Severity.DANGEROUS, Severity.BREAKING
_ALL_BREAKING: Grades = (_B, _B, _B, _B)
_JSON_BREAKING: Grades = (_S, _B, _B, _B)
_SOURCE_BREAKING: Grades = (_S, _S, _B, _B)
_FILE_BREAKING: Grades = (_S, _S, _S, _B)
_ALL_DANGEROUS: Grades = (_D, _D, _D, _D)

#: Label tokens that make a change a cardinality / requiredness change rather than presence.
_REPEATED, _REQUIRED, _EXPLICIT, _IMPLICIT = "repeated", "required", "explicit", "implicit"


def category_rule_id(slug: str, grades: Grades) -> str:
    """Build a finding's rule id from its slug and the category where it is at its worst.

    Args:
        slug: The rule slug (``json-name-changed``).
        grades: The finding's severity under each category, in :data:`CATEGORY_ORDER`.

    Returns:
        ``protobuf.<category>.<slug>`` with the narrowest category carrying the worst grade,
        lower-cased (``protobuf.wire_json.json-name-changed``).
    """
    worst = _worst(list(grades))
    home = next(cat for cat, grade in zip(CATEGORY_ORDER, grades) if grade is worst)
    return f"protobuf.{home.lower()}.{slug}"


@dataclass(frozen=True)
class ProtoRuleFinding:
    """One Protobuf-specific change, graded under every ``buf breaking`` category.

    Attributes:
        slug: The rule slug (see the module table).
        grades: Its severity under each category, in :data:`CATEGORY_ORDER`.
        subject: The canonical key it concerns (a type or field key).
        message: What changed, in one clause (``json_name changed 'a' → 'alpha'``).
        joins: The canonical diff changes it grades, as ``(category, key)``; a finding that
            joins none of the diff's changes is reported unattributed.
    """

    slug: str
    grades: Grades
    subject: str
    message: str
    joins: Tuple[Tuple[EntityCategory, str], ...]

    @property
    def rule_id(self) -> str:
        """The namespaced rule id, ``protobuf.<home category>.<slug>``."""
        return category_rule_id(self.slug, self.grades)

    def severity(self, category: str) -> Severity:
        """Return the finding's severity under ``category`` (a :data:`CATEGORY_ORDER` name)."""
        return self.grades[CATEGORY_ORDER.index(category)]

    def rationale(self, category: str) -> str:
        """One line naming the category graded at, what changed, and every category's grade.

        Args:
            category: The category the caller grades at.

        Returns:
            ``[WIRE] pkg.M.a: json_name changed … (breaking under WIRE_JSON, PACKAGE, FILE; safe
            under WIRE)``.
        """
        return f"[{category}] {self.subject}: {self.message} ({grades_summary(self.grades)})"


def grades_summary(grades: Grades) -> str:
    """Summarize per-category grades: ``breaking under X, Y; safe under Z`` (worst first).

    Args:
        grades: Severities in :data:`CATEGORY_ORDER`.

    Returns:
        The summary clause.
    """
    parts: List[str] = []
    for severity in (_B, _D, _S):
        cats = [cat for cat, grade in zip(CATEGORY_ORDER, grades) if grade is severity]
        if cats:
            parts.append(f"{severity.value} under {', '.join(cats)}")
    return "; ".join(parts)


@dataclass
class ProtoFindings:
    """Everything :func:`category_findings` found between two versions.

    Attributes:
        findings: The graded findings, in type-key order.
        explained_enum_values: Enum type keys whose ``enum_values`` movement the findings fully
            account for (every removed value renamed onto a number an added value took), so the
            baseline's blanket "enum values moved" grade does not apply on top.
    """

    findings: List[ProtoRuleFinding] = field(default_factory=list)
    explained_enum_values: Set[str] = field(default_factory=set)


# ===========================================================================
# Model reading helpers
# ===========================================================================


def _inclusive_ranges(type_: Type) -> List[Tuple[int, int]]:
    """A type's reserved number ranges as inclusive ``(start, end)`` pairs.

    The normalizer stores a message's ranges half-open ``[start, end)`` (as the descriptor does)
    and an enum's inclusive, both as ``[start, end]``.
    """
    out: List[Tuple[int, int]] = []
    for pair in type_.extras.get("reserved_ranges") or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            start, end = int(pair[0]), int(pair[1])
            out.append((start, end if type_.kind is TypeKind.ENUM else end - 1))
    return out


def _reserved_names(type_: Type) -> Set[str]:
    """A type's reserved names."""
    return {str(name) for name in type_.extras.get("reserved_names") or []}


def _is_reserved(number: Optional[int], ranges: Sequence[Tuple[int, int]]) -> bool:
    """Whether ``number`` falls inside one of the inclusive ``ranges``."""
    return number is not None and any(start <= number <= end for start, end in ranges)


def _uncovered(ranges: Sequence[Tuple[int, int]], cover: Sequence[Tuple[int, int]]) -> List[Tuple[int, int]]:
    """The parts of ``ranges`` that ``cover`` does not reserve (both inclusive).

    Args:
        ranges: The old reservations.
        cover: The new reservations.

    Returns:
        The uncovered sub-ranges, in order.
    """
    out: List[Tuple[int, int]] = []
    merged = sorted(cover)
    for start, end in sorted(ranges):
        cursor = start
        for c_start, c_end in merged:
            if c_end < cursor or c_start > end:
                continue
            if c_start > cursor:
                out.append((cursor, c_start - 1))
            cursor = max(cursor, c_end + 1)
            if cursor > end:
                break
        if cursor <= end:
            out.append((cursor, end))
    return out


def _range_text(ranges: Iterable[Tuple[int, int]]) -> str:
    """``[(5, 5), (9, 11)]`` → ``5, 9 to 11``."""
    return ", ".join(str(s) if s == e else f"{s} to {e}" for s, e in ranges)


def _core(ref: Optional[TypeRef]) -> Optional[str]:
    """A type reference's element name, ignoring nullability and list wrapping."""
    while ref is not None and ref.item is not None:
        ref = ref.item
    return ref.name if ref is not None else None


def _file_index(api: CanonicalApi) -> Dict[str, Dict[str, str]]:
    """Top-level type key → ``{"file", "package", "syntax"}`` from the normalizer's file record."""
    record = api.extras.get("protobuf_files")
    index: Dict[str, Dict[str, str]] = {}
    if not isinstance(record, Mapping):
        return index
    for file_name, entry in record.items():
        if not isinstance(entry, Mapping):
            continue
        for type_key in entry.get("types") or []:
            index[str(type_key)] = {
                "file": str(file_name),
                "package": str(entry.get("package") or ""),
                "syntax": str(entry.get("syntax") or ""),
            }
    return index


def _owner_entry(type_key: str, files: Mapping[str, Mapping[str, str]]) -> Optional[Mapping[str, str]]:
    """The file record of the top-level type that is, or encloses, ``type_key``."""
    owners = [key for key in files if type_key == key or type_key.startswith(key + ".")]
    return files[max(owners, key=len)] if owners else None


def _label(field_: CanonicalField, syntax: str, record_keys: Set[str]) -> Optional[str]:
    """A field's cardinality / presence token: repeated, required, explicit or implicit.

    Args:
        field_: The field.
        syntax: Its file's syntax (``proto2`` / ``proto3`` / ``editions``), or ``""`` unknown.
        record_keys: The message type keys of the model, for "a message field has presence".

    Returns:
        The token, or ``None`` when it cannot be told (a plain singular field of unknown syntax).
    """
    extras = field_.extras
    presence = extras.get("field_presence")
    if extras.get("label") == "repeated":
        return _REPEATED
    if extras.get("label") == "required" or presence == "LEGACY_REQUIRED":
        return _REQUIRED
    if extras.get("proto3_optional") or presence == "EXPLICIT" or extras.get("oneof"):
        return _EXPLICIT
    if presence == "IMPLICIT":
        return _IMPLICIT
    if _core(field_.type) in record_keys:
        return _EXPLICIT  # a message-typed field always tracks presence
    if syntax == "proto2":
        return _EXPLICIT
    if syntax == "proto3":
        return _IMPLICIT
    return None


# ===========================================================================
# The rules
# ===========================================================================


class _Finder:
    """Collect the findings between ``base`` and ``target`` (one instance per comparison)."""

    def __init__(self, base: CanonicalApi, target: CanonicalApi) -> None:
        self.base = base
        self.target = target
        self.old_types = {t.key: t for t in base.types}
        self.new_types = {t.key: t for t in target.types}
        self.old_files = _file_index(base)
        self.new_files = _file_index(target)
        self.record_keys = {
            t.key for t in [*base.types, *target.types] if t.kind is TypeKind.RECORD
        }
        self.out = ProtoFindings()

    def add(self, slug: str, grades: Grades, subject: str, message: str, *joins: Tuple[EntityCategory, str]) -> None:
        """Record one finding."""
        self.out.findings.append(ProtoRuleFinding(slug, grades, subject, message, tuple(joins)))

    def run(self) -> ProtoFindings:
        """Run every rule over every type, in key order."""
        for key in sorted(set(self.old_types) & set(self.new_types)):
            old, new = self.old_types[key], self.new_types[key]
            if old.kind is not new.kind:
                continue  # a kind flip is the baseline's breaking `kind` move
            self._reserved_removed(old, new)
            if new.kind is TypeKind.RECORD:
                self._message_fields(old, new)
            elif new.kind is TypeKind.ENUM:
                self._enum_values(old, new)
        self._moves()
        return self.out

    # --- reservations ----------------------------------------------------

    def _reserved_removed(self, old: Type, new: Type) -> None:
        """A number range or name ``old`` reserved that ``new`` no longer does."""
        numbers = _uncovered(_inclusive_ranges(old), _inclusive_ranges(new))
        names = sorted(_reserved_names(old) - _reserved_names(new))
        if not numbers and not names:
            return
        parts = []
        if numbers:
            parts.append(f"numbers {_range_text(numbers)}")
        if names:
            parts.append("names " + ", ".join(repr(n) for n in names))
        self.add(
            "reserved-removed",
            _ALL_DANGEROUS,
            new.key,
            f"reservation removed ({'; '.join(parts)}), so a later change may reuse them",
            (EntityCategory.TYPE, new.key),
        )

    def _reserved_reuse(
        self, old: Type, name: str, number: Optional[int], key: str, join: Tuple[EntityCategory, str]
    ) -> None:
        """A new field / enum value taking a number or name ``old`` had reserved.

        Args:
            old: The message or enum in the old version (its reservations are checked).
            name: The new field's or value's name.
            number: Its number, or ``None`` when it has none.
            key: The canonical key the finding concerns.
            join: The diff change the finding grades.
        """
        if _is_reserved(number, _inclusive_ranges(old)):
            self.add(
                "reserved-number-reused",
                _ALL_BREAKING,
                key,
                f"number {number} was reserved and is now used by {name!r}",
                join,
            )
        if name in _reserved_names(old):
            self.add(
                "reserved-name-reused",
                _ALL_BREAKING,
                key,
                f"name {name!r} was reserved and is used again",
                join,
            )

    # --- message fields --------------------------------------------------

    def _syntax(self, type_key: str) -> str:
        """The syntax of the file declaring ``type_key`` (new side first), or ``""``."""
        entry = _owner_entry(type_key, self.new_files) or _owner_entry(type_key, self.old_files)
        return entry.get("syntax", "") if entry else ""

    def _message_fields(self, old: Type, new: Type) -> None:
        """Deleted, renamed, re-numbered and re-labelled fields of a message in both versions."""
        old_fields = {f.name: f for f in old.fields}
        new_fields = {f.name: f for f in new.fields}
        removed = [old_fields[n] for n in sorted(set(old_fields) - set(new_fields))]
        added = [new_fields[n] for n in sorted(set(new_fields) - set(old_fields))]
        by_number = {f.field_number: f for f in added if f.field_number is not None}
        new_ranges, new_names = _inclusive_ranges(new), _reserved_names(new)

        for gone in removed:
            taker = by_number.get(gone.field_number)
            joins = [(EntityCategory.FIELD, gone.key)]
            if taker is not None:
                joins.append((EntityCategory.FIELD, taker.key))
                if _core(gone.type) == _core(taker.type):
                    self.add(
                        "field-renamed",
                        _JSON_BREAKING,
                        gone.key,
                        f"field {gone.field_number} renamed {gone.name!r} → {taker.name!r}; "
                        "the binary encoding is unchanged but JSON and generated code key on the name",
                        *joins,
                    )
                else:
                    self.add(
                        "field-number-reused",
                        _ALL_BREAKING,
                        gone.key,
                        f"field number {gone.field_number} now carries {taker.name!r} of type "
                        f"{_core(taker.type)!r} instead of {gone.name!r} of type {_core(gone.type)!r}",
                        *joins,
                    )
                continue
            number_reserved = _is_reserved(gone.field_number, new_ranges)
            name_reserved = gone.name in new_names
            if number_reserved and name_reserved:
                self.add(
                    "field-deleted",
                    _SOURCE_BREAKING,
                    gone.key,
                    f"field {gone.field_number} {gone.name!r} deleted with its number and name reserved",
                    *joins,
                )
                continue
            missing = [w for w, ok in (("number", number_reserved), ("name", name_reserved)) if not ok]
            self.add(
                "field-deleted-unreserved",
                (_S if number_reserved else _D, _B, _B, _B),
                gone.key,
                f"field {gone.field_number} {gone.name!r} deleted without reserving its "
                f"{' and '.join(missing)}",
                *joins,
            )

        for fresh in added:
            self._reserved_reuse(old, fresh.name, fresh.field_number, fresh.key, (EntityCategory.FIELD, fresh.key))

        syntax = self._syntax(new.key)
        for name in sorted(set(old_fields) & set(new_fields)):
            self._field_changes(old_fields[name], new_fields[name], syntax)

    def _field_changes(self, before: CanonicalField, after: CanonicalField, syntax: str) -> None:
        """``json_name``, ``oneof`` and label changes on a field present in both versions."""
        from .proto_normalizer import default_json_name

        join = (EntityCategory.FIELD, after.key)
        old_json = before.extras.get("json_name") or default_json_name(before.name)
        new_json = after.extras.get("json_name") or default_json_name(after.name)
        if old_json != new_json:
            self.add(
                "json-name-changed",
                _JSON_BREAKING,
                after.key,
                f"json_name changed {old_json!r} → {new_json!r}",
                join,
            )
        old_oneof, new_oneof = before.extras.get("oneof"), after.extras.get("oneof")
        if old_oneof != new_oneof:
            self.add(
                "oneof-membership-changed",
                _ALL_BREAKING,
                after.key,
                f"oneof membership changed {_oneof_text(old_oneof)} → {_oneof_text(new_oneof)}",
                join,
            )
        old_label = _label(before, syntax, self.record_keys)
        new_label = _label(after, syntax, self.record_keys)
        if old_label is None or new_label is None or old_label == new_label:
            return
        if _REPEATED in (old_label, new_label):
            slug, grades = "cardinality-changed", _ALL_BREAKING
        elif _REQUIRED in (old_label, new_label):
            slug, grades = "required-changed", _ALL_BREAKING
        else:
            slug, grades = "presence-changed", _SOURCE_BREAKING
        self.add(slug, grades, after.key, f"label changed {old_label} → {new_label}", join)

    # --- enum values -----------------------------------------------------

    def _enum_values(self, old: Type, new: Type) -> None:
        """Re-numbered, renamed and reserved-reusing values of an enum in both versions."""
        old_values = {v.name: v.value for v in old.enum_values}
        new_values = {v.name: v.value for v in new.enum_values}
        join = (EntityCategory.TYPE, new.key)
        for name in sorted(set(old_values) & set(new_values)):
            if old_values[name] != new_values[name]:
                self.add(
                    "enum-value-number-changed",
                    _ALL_BREAKING,
                    new.key,
                    f"value {name!r} moved from number {old_values[name]} to {new_values[name]}",
                    join,
                )
        removed = sorted(set(old_values) - set(new_values))
        added = sorted(set(new_values) - set(old_values))
        added_by_number: Dict[Any, str] = {}
        for name in added:
            added_by_number.setdefault(new_values[name], name)
        paired: Set[str] = set()
        for name in removed:
            taker = added_by_number.get(old_values[name])
            if taker is None or taker in paired:
                continue
            paired.update({name, taker})
            self.add(
                "enum-value-number-reused",
                _JSON_BREAKING,
                new.key,
                f"number {old_values[name]} renamed {name!r} → {taker!r}",
                join,
            )
        for name in added:
            number = new_values[name]
            self._reserved_reuse(old, name, number if isinstance(number, int) else None, new.key, join)
        if set(removed) | set(added) <= paired:
            self.out.explained_enum_values.add(new.key)

    # --- moves -----------------------------------------------------------

    def _moves(self) -> None:
        """Top-level types moved to another file, and types moved to another package."""
        for key in sorted(set(self.old_files) & set(self.new_files)):
            before, after = self.old_files[key]["file"], self.new_files[key]["file"]
            if before != after:
                self.add(
                    "type-moved-file",
                    _FILE_BREAKING,
                    key,
                    f"moved from {before!r} to {after!r} in the same package",
                    (EntityCategory.TYPE, key),
                )
        moved_to: Dict[str, str] = {}
        for key in sorted(set(self.new_files) - set(self.old_files)):
            relative = _relative(key, self.new_files[key]["package"])
            moved_to.setdefault(relative, key)
        for key in sorted(set(self.old_files) - set(self.new_files)):
            package = self.old_files[key]["package"]
            new_key = moved_to.get(_relative(key, package))
            if new_key is None or key in self.new_types:
                continue
            joins = [(EntityCategory.TYPE, key)]
            for type_ in self.base.types:
                if type_.key == key or type_.key.startswith(key + "."):
                    if type_.key != key:
                        joins.append((EntityCategory.TYPE, type_.key))
                    joins.extend((EntityCategory.FIELD, f.key) for f in type_.fields)
            self.add(
                "package-changed",
                _ALL_BREAKING,
                key,
                f"moved from package {package!r} to {self.new_files[new_key]['package']!r} "
                f"as {new_key!r}; its full name, which Any, reflection and RPC paths carry, changed",
                *joins,
            )


def _relative(type_key: str, package: str) -> str:
    """A type key with its package prefix removed."""
    return type_key[len(package) + 1 :] if package and type_key.startswith(package + ".") else type_key


def _oneof_text(name: Any) -> str:
    """``'choice'`` → ``oneof 'choice'``; ``None`` → ``no oneof``."""
    return f"oneof {name!r}" if name else "no oneof"


def category_findings(base: CanonicalApi, target: CanonicalApi) -> ProtoFindings:
    """Compare two Protobuf versions and grade every Protobuf-specific change per category.

    Pure and deterministic: findings come out in type-key order (moves last).

    Args:
        base: The old version (normalized by :class:`app.proto_normalizer.ProtoNormalizer`).
        target: The new version.

    Returns:
        The :class:`ProtoFindings`.
    """
    return _Finder(base, target).run()
