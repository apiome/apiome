"""Lay out canonical types as an EDI implementation guide — MFX-24.1 (#4145).

An implementation guide describes one transaction (an X12 transaction set, later a UN/EDIFACT message,
MFX-24.2) as a sequence of **segments** — flat lists of data **elements** — grouped into **loops** that
repeat. This module is the standard-neutral core: it decides the structure and each element's kind, and
the X12 emitter (:mod:`app.x12_guide_emitter`) spells them in X12's terms (``AN``/``ID``/``N``/``R``/
``DT``/``TM``, refs ``BEG01``).

**From types to segments.** Each record no other record contains is a top-level part of the transaction
(:func:`app.cobolcopybook_plan.record_types`). A record is a segment of its scalar fields, in field
order; its record fields follow it — a single record as a child segment used once, a list of records as
a child loop that repeats up to ``maxItems`` (unbounded otherwise) — and a record with children is a loop
headed by its own segment. A list of scalars is a child segment with one element, repeated. A record
that contains itself is cut (recorded); unions and maps are dropped (recorded) — a segment holds flat
values only.

**Elements.** text → ``text`` (``maxLength``, else the default length — recorded), a UUID 36; an enum →
``code`` with its values as the code list, a boolean → ``code`` ``Y``/``N``; integers → ``integer`` sized
by their width; a decimal → ``decimal`` with its scale from ``multipleOf`` (unknown scale: explicit
decimal point); a float → ``decimal`` with no scale; ``date`` → ``date``; ``time`` → ``time``; a
timestamp → two elements, its date and its time. A field the source marks required is mandatory
(``M``), any other optional (``O``).

**An imported X12 transaction** keeps its own segment IDs and element references: a record whose fields
are named like element references (``BEG01``, ``N103``) is split into one segment per prefix, its
segments ordered as the interchange had them (``x12_transactions``), and a reference the sample left
empty is a *not used* (``X``) position.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple, Union

from .canonical_model import CanonicalApi, CanonicalField, Constraints, Type, TypeKind, TypeRef
from .cobolcopybook_plan import record_types
from .emitter import LossKind, LossTracker

__all__ = [
    "ELEMENT_REF_RE",
    "GuideElement",
    "GuideLoop",
    "GuideOptions",
    "GuidePlan",
    "GuideSegment",
    "SegmentUse",
    "plan_guide",
]

#: An element reference: a segment ID (a letter, then 1-2 letters or digits) and a 2-digit position.
ELEMENT_REF_RE = re.compile(r"^([A-Z][A-Z0-9]{1,2})(\d{2})$")

#: Canonical integer scalar names → maximum digits.
_INTEGER_DIGITS: Dict[str, int] = {
    **{n: 3 for n in ("int8", "i8", "sbyte", "uint8", "u8", "byte")},
    **{n: 5 for n in ("int16", "i16", "short", "uint16", "u16")},
    **{n: 10 for n in ("int32", "i32", "int", "sint32", "sfixed32", "uint32", "u32", "fixed32")},
    **{n: 18 for n in ("int64", "i64", "long", "sint64", "sfixed64", "integer", "bigint", "uint64", "u64",
                       "fixed64")},
}
_DECIMALS = frozenset({"decimal", "numeric", "money"})
_FLOATS = frozenset({"float", "double", "f32", "f64", "float32", "float64", "number"})
_BOOLEANS = frozenset({"bool", "boolean"})
_DATES = frozenset({"date"})
_TIMES = frozenset({"time"})
_TIMESTAMPS = frozenset({"datetime", "date-time", "timestamp", "instant"})
_UUIDS = frozenset({"uuid", "guid"})
_TEXT = frozenset({"string", "str", "text", "char", "id", "uri", "url", "email", "hostname", "ipv4", "ipv6",
                   "duration", "bytes", "binary", "blob"})
_NONE = frozenset({"null", "void", "none"})
#: Digits of a decimal (and of a float) element.
_DECIMAL_DIGITS = 15

ElementKind = str  # "text" | "code" | "integer" | "decimal" | "date" | "time"


@dataclass
class GuideElement:
    """One data element of a segment.

    Attributes:
        ref: Its reference (``ORD01``): the segment ID and its 2-digit position.
        name: A readable name (the source field's).
        kind: ``text``, ``code``, ``integer``, ``decimal``, ``date``, ``time``.
        min_length: Minimum characters (digits for numbers).
        max_length: Maximum characters (digits for numbers).
        usage: ``M`` (mandatory), ``O`` (optional) or ``X`` (not used).
        codes: The code list of a ``code`` element.
        scale: Implied decimal places of a ``decimal`` (``None``: an explicit decimal point).
        source: The canonical key it comes from (``""`` for a not-used position).
    """

    ref: str
    name: str
    kind: ElementKind
    min_length: int
    max_length: int
    usage: str
    codes: List[str] = field(default_factory=list)
    scale: Optional[int] = None
    source: str = ""


@dataclass
class GuideSegment:
    """A segment definition (the dictionary entry; the structure places it).

    Attributes:
        id: The segment ID.
        name: A readable name (the source record's, or field's).
        elements: Its elements, refs ``<id>01`` upward with no gap.
        source: The canonical key it comes from.
    """

    id: str
    name: str
    elements: List[GuideElement]
    source: str = ""


@dataclass
class GuideLoop:
    """A loop: a group of segments (and loops) that repeats, headed by its first segment.

    Attributes:
        id: The loop ID — its first segment's ID.
        name: A readable name.
        usage: ``M`` or ``O``.
        max_use: How many times it may repeat (``None``: no limit).
        children: Its segments (as :class:`SegmentUse`) and loops, the heading segment first.
        source: The canonical key it comes from.
    """

    id: str
    name: str
    usage: str
    max_use: Optional[int]
    children: List[Union["SegmentUse", "GuideLoop"]]
    source: str = ""


@dataclass
class SegmentUse:
    """A place in the structure where a segment is used.

    Attributes:
        segment: The segment ID.
        usage: ``M`` or ``O``.
        max_use: How many times it may repeat here (``None``: no limit).
        source: The canonical key of the field that put it here (``""`` for the record's own).
    """

    segment: str
    usage: str
    max_use: Optional[int]
    source: str = ""


@dataclass
class GuidePlan:
    """A whole guide: the segment dictionary and the transaction's structure (without its envelope).

    Attributes:
        segments: Segment ID → definition, in the order first used.
        structure: The top-level segments and loops, in order.
    """

    segments: Dict[str, GuideSegment]
    structure: List[Union[SegmentUse, GuideLoop]]


@dataclass(frozen=True)
class GuideOptions:
    """What the plan synthesizes where the model says nothing.

    Attributes:
        default_length: Maximum length of text with no ``maxLength``.
        reserved_ids: Segment IDs the standard reserves (its envelope: ``ST``, ``SE`` …).
    """

    default_length: int = 80
    reserved_ids: frozenset = frozenset()


class _SegmentIds:
    """Unique, deterministic segment IDs spelled from names (``Order`` → ``ORD``, ``OrderLine`` → ``ORL``)."""

    def __init__(self, reserved: frozenset) -> None:
        self._used: Set[str] = set(reserved)

    def claim(self, segment_id: str) -> bool:
        """Take ``segment_id`` as is (an imported one); ``False`` when it is taken."""
        if segment_id in self._used:
            return False
        self._used.add(segment_id)
        return True

    def allocate(self, name: str) -> str:
        """A new ID for ``name``: its initials and consonants first, then its letters, then a digit."""
        letters = re.sub(r"[^A-Za-z0-9]", "", name).upper() or "SEG"
        if not letters[0].isalpha():
            letters = f"S{letters}"
        words = [w for w in re.split(r"(?<=[a-z0-9])(?=[A-Z])|[^A-Za-z0-9]+", name) if w]
        initials = "".join(w[0] for w in words).upper()
        consonants = letters[0] + re.sub(r"[AEIOU]", "", letters[1:])
        candidates = [letters[:3], (initials + letters[1:])[:3], consonants[:3]]
        candidates += [letters[0] + a + b for a in letters[1:] for b in letters[2:]]
        candidates += [letters[:2] + str(d) for d in range(1, 10)]
        candidates += [letters[0] + str(d) + str(e) for d in range(10) for e in range(10)]
        for candidate in candidates:
            if len(candidate) >= 2 and self.claim(candidate):
                return candidate
        raise ValueError(f"No free segment ID left for {name!r}")


class _Planner:
    """Builds one guide plan (single use)."""

    def __init__(self, api: CanonicalApi, options: GuideOptions, losses: LossTracker) -> None:
        self._api = api
        self._options = options
        self._losses = losses
        self._ids = _SegmentIds(options.reserved_ids)
        self._by_key = {t.key: t for t in api.types if t.key}
        names = [t.name for t in api.types]
        self._by_name = {t.name: t for t in api.types if t.name and names.count(t.name) == 1}
        self.segments: Dict[str, GuideSegment] = {}
        self._segment_of: Dict[str, List[str]] = {}
        self._noted: Set[Tuple[str, str]] = set()
        self._order = self._source_segment_order()

    # --- structure -------------------------------------------------------------

    def plan(self) -> GuidePlan:
        structure: List[Union[SegmentUse, GuideLoop]] = []
        for record in record_types(self._api):
            # The transaction set itself is the container: a top-level record's segments and children sit in it
            # directly, rather than in a loop used once.
            structure += self._record(record, usage="M", max_use=1, source="", path={record.key}, top=True)
        return GuidePlan(segments=self.segments, structure=structure)

    def _record(
        self, record: Type, *, usage: str, max_use: Optional[int], source: str, path: Set[str], top: bool = False
    ) -> List[Union[SegmentUse, GuideLoop]]:
        """A record as its segment(s) and then its record fields; a loop when it has children or repeats.

        A top-level record (``top``) is not wrapped in a loop. An imported X12 transaction's segments and
        loops follow the interchange's order instead of "own segments first".
        """
        own = [SegmentUse(seg_id, "M" if i == 0 else self._segment_usage(seg_id), 1)
               for i, seg_id in enumerate(self._segments_of(record))]
        children: List[Union[SegmentUse, GuideLoop]] = []
        for f in self._ordered_children(record):
            children += self._child(f, path=path)
        members: List[Union[SegmentUse, GuideLoop]] = [*own, *children]
        if self._order:
            rank = {seg: i for i, seg in enumerate(self._order)}
            head, rest = members[0], members[1:]
            rest.sort(key=lambda node: rank.get(node.segment if isinstance(node, SegmentUse) else node.id, len(rank)))
            members = [head, *rest]
        if top:
            return members
        if not children and max_use == 1:
            return [SegmentUse(own[0].segment, usage, 1, source), *own[1:]]
        return [GuideLoop(own[0].segment, record.name or record.key, usage, max_use, members, source or record.key)]

    def _child(self, f: CanonicalField, *, path: Set[str]) -> List[Union[SegmentUse, GuideLoop]]:
        """A record field's place in the structure (scalars are elements of the record's segment)."""
        usage = "M" if f.type.nullable is False else "O"
        ref = f.type
        max_use: Optional[int] = 1
        if ref.is_list():
            max_use = (f.constraints.max_items if f.constraints else None) or None
            ref = ref.item or TypeRef(name="string")
            if ref.is_list():
                self._loss(LossKind.INFERRED, "list-flattened", f.key, f"{f.key!r} is a list of lists; an EDI loop "
                           "cannot nest a list in a list, so its inner lists are written as one list.")
                while ref.is_list():
                    ref = ref.item or TypeRef(name="string")
        target = self._resolve(ref)
        if target is not None and target.kind is TypeKind.ALIAS and target.aliased is not None:
            target = self._resolve(target.aliased) or target
        if target is not None and target.kind is TypeKind.RECORD:
            if target.key in path:
                self._loss(LossKind.NA, "recursion-cut", f.key, f"{f.key!r} refers back to {target.key!r}, which "
                           "contains it; the reference is left out.")
                return []
            return self._record(target, usage=usage, max_use=max_use, source=f.key, path=path | {target.key})
        # A list of scalars: a one-element segment, repeated.
        element = self._element(f, ref, position=1, segment_id="")
        if not element:
            return []
        seg_id = self._new_segment(f.name or f.key, f.key, [f], list_item=ref)
        return [SegmentUse(seg_id, usage, max_use, f.key)]

    def _ordered_children(self, record: Type) -> List[CanonicalField]:
        """The record's fields that are not elements of its own segment(s), in order."""
        children = [f for f in self._fields(record) if self._is_child(f)]
        if self._order:
            # An imported X12 transaction: its repeating segments in interchange order.
            rank = {seg: i for i, seg in enumerate(self._order)}
            children.sort(key=lambda f: rank.get((f.name or ""), len(rank)))
        return children

    # --- segments ----------------------------------------------------------------

    def _segments_of(self, record: Type) -> List[str]:
        """The segment IDs of a record's own scalar fields (several when they are X12 element refs)."""
        if record.key in self._segment_of:
            return self._segment_of[record.key]
        scalars = [f for f in self._fields(record) if not self._is_child(f)]
        groups = self._x12_groups(scalars)
        if groups:
            ids = [self._imported_segment(seg_id, members, record) for seg_id, members in groups]
        else:
            ids = [self._new_segment(record.name or record.key, record.key, scalars)]
        self._segment_of[record.key] = ids
        return ids

    def _x12_groups(self, scalars: List[CanonicalField]) -> List[Tuple[str, List[CanonicalField]]]:
        """Scalar fields named like X12 element refs, grouped by segment ID; ``[]`` when they are not."""
        if not scalars or not all(ELEMENT_REF_RE.match(f.name or "") for f in scalars):
            return []
        groups: Dict[str, List[CanonicalField]] = {}
        for f in scalars:
            groups.setdefault(ELEMENT_REF_RE.match(f.name).group(1), []).append(f)
        order = {seg: i for i, seg in enumerate(self._order)}
        return sorted(groups.items(), key=lambda item: order.get(item[0], len(order)))

    def _imported_segment(self, seg_id: str, members: List[CanonicalField], record: Type) -> str:
        """A segment keeping its imported ID and refs; positions the sample left empty are *not used*."""
        if seg_id in self.segments:
            return seg_id
        if not self._ids.claim(seg_id):
            return self._new_segment(seg_id, record.key, members)
        by_position = {int(ELEMENT_REF_RE.match(f.name).group(2)): f for f in members}
        elements: List[GuideElement] = []
        for position in range(1, max(by_position) + 1):
            f = by_position.get(position)
            if f is None:
                elements.append(GuideElement(f"{seg_id}{position:02d}", "Not used", "text", 1, 1, "X"))
                continue
            built = self._element(f, f.type, position=position, segment_id=seg_id)
            elements += built or [GuideElement(f"{seg_id}{position:02d}", f.name, "text", 1, 1, "X", source=f.key)]
        self.segments[seg_id] = GuideSegment(seg_id, seg_id, elements, record.key)
        return seg_id

    def _new_segment(
        self, name: str, source: str, fields: List[CanonicalField], *, list_item: Optional[TypeRef] = None
    ) -> str:
        """A segment of new elements under a new ID (a record with no scalar gets a synthesized one)."""
        seg_id = self._ids.allocate(name)
        elements: List[GuideElement] = []
        for f in fields:
            ref = list_item if list_item is not None else f.type
            elements += self._element(f, ref, position=len(elements) + 1, segment_id=seg_id)
        if not elements:
            self._loss(LossKind.INFERRED, "element-synthesized", source, f"{source!r} has no value of its own; its "
                       f"segment {seg_id} gets one code element ({seg_id}01 = {seg_id!r}) so it can head its loop.")
            elements = [GuideElement(f"{seg_id}01", "Segment marker", "code", len(seg_id), len(seg_id), "M",
                                     [seg_id], source=source)]
        if len(elements) > 99:
            self._loss(LossKind.NA, "elements-truncated", source, f"{source!r} has {len(elements)} values; a segment "
                       "holds at most 99 elements, so the rest are left out.")
            elements = elements[:99]
        self.segments[seg_id] = GuideSegment(seg_id, name, elements, source)
        self._loss(LossKind.INFERRED, "segment-id-synthesized", source, f"{source!r} is written as segment "
                   f"{seg_id} (an ID made from its name).")
        return seg_id

    def _segment_usage(self, seg_id: str) -> str:
        segment = self.segments[seg_id]
        return "M" if any(e.usage == "M" for e in segment.elements) else "O"

    # --- elements ----------------------------------------------------------------

    def _element(self, f: CanonicalField, ref: TypeRef, *, position: int, segment_id: str) -> List[GuideElement]:
        """The element(s) of one scalar field (a timestamp is two); ``[]`` when it is dropped."""
        usage = "M" if f.type.nullable is False else "O"
        c = f.constraints or Constraints()
        target = self._resolve(ref)
        seen: Set[str] = set()
        # An alias is written as what it stands for (its constraints apply when the field has none).
        while target is not None and target.kind is TypeKind.ALIAS and target.aliased is not None:
            if target.key in seen:
                break
            seen.add(target.key)
            if not f.constraints and target.constraints:
                c = target.constraints
            ref = target.aliased
            target = self._resolve(ref)
        name = f.name or f.key

        def make(kind: str, low: int, high: int, *, codes=None, scale=None, suffix: str = "", at: int = position):
            return GuideElement(f"{segment_id}{at:02d}", name + suffix, kind, low, high, usage, list(codes or []),
                                scale, f.key)

        if target is not None and target.kind is TypeKind.ENUM:
            codes = [str(m.value if m.value is not None else m.name) for m in target.enum_values] or ["X"]
            return [make("code", min(len(code) for code in codes), max(len(code) for code in codes), codes=codes)]
        if target is not None and target.kind in (TypeKind.UNION, TypeKind.MAP):
            what = "union" if target.kind is TypeKind.UNION else "map"
            self._loss(LossKind.NA, f"{what}-dropped", f.key, f"{f.key!r} is a {what}; a segment holds flat values "
                       "only, so it is left out.")
            return []
        scalar = (target.name if target is not None else ref.name) or "string"
        key = scalar.lower()
        fmt = (c.format or "").lower()
        if key in _NONE:
            self._loss(LossKind.NA, "field-dropped", f.key, f"{f.key!r} holds no value; it is left out.")
            return []
        if key in _BOOLEANS:
            return [make("code", 1, 1, codes=["Y", "N"])]
        if key in _INTEGER_DIGITS:
            return [make("integer", 1, _INTEGER_DIGITS[key])]
        if key in _DECIMALS or key in _FLOATS:
            scale = _scale_of(c.multiple_of) if key in _DECIMALS else None
            return [make("decimal", 1, _DECIMAL_DIGITS, scale=scale)]
        if key in _DATES or fmt == "date":
            return [make("date", 8, 8)]
        if key in _TIMES or fmt == "time":
            return [make("time", 4, 8)]
        if key in _TIMESTAMPS or fmt == "date-time":
            self._loss(LossKind.INFERRED, "timestamp-split", f.key, f"{f.key!r} is a timestamp; it is written as "
                       "two elements, its date (CCYYMMDD) and its time (HHMM[SS…]).")
            return [make("date", 8, 8, suffix=" (date)"), make("time", 4, 8, suffix=" (time)", at=position + 1)]
        if key in _UUIDS or fmt == "uuid":
            return [make("text", 36, 36)]
        if key not in _TEXT:
            self._loss(LossKind.INFERRED, "unmapped-scalar", f.key, f"{scalar!r} has no EDI element type; values of "
                       "it are written as text.")
        if c.max_length is None:
            self._loss(LossKind.INFERRED, "length-synthesized", f.key, f"{f.key!r} has no maxLength; its element is "
                       f"written with a maximum of {self._options.default_length} characters (the default).")
        high = c.max_length or self._options.default_length
        low = min(max(c.min_length or 1, 1), high)
        return [make("text", low, max(high, 1))]

    # --- helpers -------------------------------------------------------------------

    def _fields(self, record: Type) -> List[CanonicalField]:
        return sorted(record.fields, key=lambda f: f.field_number or 0)

    def _is_child(self, f: CanonicalField) -> bool:
        """Whether a field is a child of the record (a record or a list) rather than one of its elements."""
        if f.type.is_list():
            return True
        target = self._resolve(f.type.name or "")
        while target is not None and target.kind is TypeKind.ALIAS and target.aliased is not None:
            if target.aliased.is_list():
                return True
            target = self._resolve(target.aliased.name or "")
        return target is not None and target.kind is TypeKind.RECORD

    def _resolve(self, ref: Union[TypeRef, str]) -> Optional[Type]:
        name = ref if isinstance(ref, str) else (ref.name or "")
        return self._by_key.get(name) or self._by_name.get(name)

    def _source_segment_order(self) -> List[str]:
        """An imported X12 transaction's segment IDs in interchange order (``[]`` for any other source)."""
        transactions = self._api.extras.get("x12_transactions")
        if not isinstance(transactions, list) or not transactions or not isinstance(transactions[0], dict):
            return []
        order: List[str] = []
        for segment in transactions[0].get("segments") or []:
            seg_id = segment.get("id") if isinstance(segment, dict) else None
            if isinstance(seg_id, str) and seg_id not in order:
                order.append(seg_id)
        return order

    def _loss(self, kind: LossKind, subject: str, pointer: str, detail: str) -> None:
        if (subject, detail) in self._noted:
            return
        self._noted.add((subject, detail))
        self._losses.record(kind, subject, detail, pointer=pointer or None)


def _scale_of(multiple_of: Optional[float]) -> Optional[int]:
    """The decimal places a ``multipleOf`` of ``10^-k`` implies (``0.01`` → 2), else ``None``."""
    if multiple_of is None or multiple_of <= 0:
        return None
    exponent = Decimal(repr(float(multiple_of))).normalize().as_tuple()
    if exponent.digits == (1,) and isinstance(exponent.exponent, int) and exponent.exponent <= 0:
        return min(-exponent.exponent, 9)
    return None


def plan_guide(api: CanonicalApi, options: GuideOptions, losses: LossTracker) -> GuidePlan:
    """Lay ``api``'s records out as an implementation guide's segments and loops.

    Args:
        api: The canonical model.
        options: The default text length and the IDs the standard reserves.
        losses: Where every synthesized length, ID and dropped value is recorded.

    Returns:
        The :class:`GuidePlan` (empty structure when the model has no record).
    """
    return _Planner(api, options, losses).plan()
