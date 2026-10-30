"""Lay out canonical types as COBOL copybook records — MFX-23.1 (#4139).

The COBOL copybook emitter writes record layouts; this module decides them. It turns a
:class:`~app.canonical_model.CanonicalApi` into the same tree a copybook import produces
(:func:`app.cobolcopybook_parser.field_template`: ``level``, ``name``, ``picture``, ``usage``,
``occurs_min`` / ``occurs_max`` / ``depending_on``, ``redefines``, ``conditions``, ``children``), so
the emitter renders a converted model and a re-exported copybook the same way — and the PL/I output
mode (MFX-23.3) can reuse the plan.

**Records.** COBOL has no type references: a record's nested objects are written inline as group
items. Each record no other record contains becomes its own ``01`` level; levels below it step by 5
(``05``, ``10`` …), or by less when a record nests too deep for that to stay within 49. A record that
contains itself is cut at the second visit (recorded).

**Items.**

* text → ``PIC X(n)``: ``maxLength``, else a date / time layout (``date`` ``X(10)``, ``time``
  ``X(15)``, a timestamp ``X(32)``, a UUID ``X(36)``), else the default length (recorded);
* integers → ``PIC S9(4)`` / ``S9(9)`` / ``S9(18)`` (``9(n)`` when unsigned) with ``COMP``, or plain
  zoned decimal with ``numeric_usage="display"``; a decimal → ``S9(p)V9(s)`` packed (``COMP-3``), its
  scale from ``multipleOf`` (``0.01`` → 2) else the default scale; a float → ``COMP-1`` / ``COMP-2``;
* a boolean → ``PIC X`` with ``88`` levels ``<NAME>-TRUE VALUE 'Y'`` and ``<NAME>-FALSE VALUE 'N'``;
  an enum → ``PIC X(n)`` (or numeric) with an ``88`` level per value;
* a list → ``OCCURS n TIMES`` when its size is fixed, else ``OCCURS min TO max TIMES DEPENDING ON``
  a synthesized ``<NAME>-COUNT`` item written just before it (max: ``maxItems`` else the default
  occurrences); inside another table, where ``DEPENDING ON`` is not allowed, a list is a fixed table
  of its maximum;
* a union → one item per member, each after the first ``REDEFINES`` the first, largest first;
* a map, or a type with no value, is dropped (recorded).

**Names** are COBOL data names: upper case, letters, digits and single hyphens, at most 30
characters, not a reserved word, and unique across the whole copybook (``-2``, ``-3`` … within the
30), so no reference ever needs ``OF`` qualification and the same model always gets the same names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from .canonical_model import CanonicalApi, CanonicalField, Constraints, Type, TypeKind, TypeRef
from .cobolcopybook_layout import picture_size
from .emitter import LossKind, LossTracker

__all__ = ["COBOL_RESERVED_WORDS", "CopybookPlanOptions", "CobolNamer", "plan_copybook", "record_types"]

#: COBOL data names are at most 30 characters.
MAX_NAME_LENGTH = 30
#: The highest level number a data item may have below 01.
_MAX_LEVEL = 49

#: Reserved words a data name may not be (the common subset across IBM Enterprise COBOL and COBOL 2014).
COBOL_RESERVED_WORDS = frozenset("""
ACCEPT ACCESS ADD ADDRESS ADVANCING AFTER ALL ALPHABET ALPHABETIC ALPHANUMERIC ALSO ALTER ALTERNATE AND
ANY ARE AREA AREAS ASCENDING ASSIGN AT AUTHOR BEFORE BINARY BLANK BLOCK BOTTOM BY CALL CANCEL CHARACTER
CHARACTERS CLASS CLOSE CODE COLLATING COLUMN COMMA COMMON COMP COMP-1 COMP-2 COMP-3 COMP-4 COMP-5
COMPUTATIONAL COMPUTE CONFIGURATION CONTAINS CONTENT CONTINUE CONTROL CONVERTING COPY CORR CORRESPONDING
COUNT CURRENCY DATA DATE DATE-COMPILED DATE-WRITTEN DAY DAY-OF-WEEK DE DEBUGGING DECIMAL-POINT DECLARATIVES
DELETE DELIMITED DELIMITER DEPENDING DESCENDING DESTINATION DETAIL DISPLAY DIVIDE DIVISION DOWN DUPLICATES
DYNAMIC ELSE END END-IF END-PERFORM ENTRY ENVIRONMENT EQUAL ERROR EVALUATE EXCEPTION EXIT EXTEND EXTERNAL
FALSE FD FILE FILE-CONTROL FILLER FIRST FOOTING FOR FROM FUNCTION GENERATE GIVING GLOBAL GO GOBACK GREATER
GROUP HEADING HIGH-VALUE HIGH-VALUES I-O IDENTIFICATION IF IN INDEX INDEXED INITIAL INITIALIZE INPUT
INSPECT INTO INVALID IS JUST JUSTIFIED KEY LABEL LAST LEADING LEFT LENGTH LESS LIMIT LIMITS LINE LINES
LINKAGE LOCK LOW-VALUE LOW-VALUES MERGE MESSAGE MODE MOVE MULTIPLY NATIVE NEGATIVE NEXT NO NOT NULL NULLS
NUMBER NUMERIC OBJECT OCCURS OF OFF OMITTED ON OPEN OPTIONAL OR ORDER ORGANIZATION OTHER OUTPUT OVERFLOW
PACKED-DECIMAL PADDING PAGE PERFORM PIC PICTURE POINTER POSITION POSITIVE PROCEDURE PROCEED PROGRAM
PROGRAM-ID QUOTE QUOTES RANDOM READ RECORD RECORDS REDEFINES REFERENCE RELATIVE RELEASE REMAINDER REMOVE
RENAMES REPLACE REPLACING REPORT RESERVE RETURN REWRITE RIGHT ROUNDED RUN SAME SEARCH SECTION SECURITY
SELECT SENTENCE SEPARATE SEQUENCE SEQUENTIAL SET SIGN SIZE SORT SOURCE SPACE SPACES STANDARD START STATUS
STOP STRING SUBTRACT SUM SUPPRESS SYNC SYNCHRONIZED TABLE TALLYING TEST THAN THEN THROUGH THRU TIME TIMES
TO TOP TRAILING TRUE TYPE UNIT UNSTRING UNTIL UP UPON USAGE USE USING VALUE VALUES VARYING WHEN WITH WORDS
WORKING-STORAGE WRITE ZERO ZEROES ZEROS
""".split())

#: Canonical integer scalar names → (digits, signed).
_INTEGERS: Dict[str, Tuple[int, bool]] = {
    **{n: (4, True) for n in ("int8", "i8", "sbyte", "int16", "i16", "short")},
    **{n: (4, False) for n in ("uint8", "u8", "byte", "uint16", "u16")},
    **{n: (9, True) for n in ("int32", "i32", "int", "sint32", "sfixed32")},
    **{n: (9, False) for n in ("uint32", "u32", "fixed32")},
    **{n: (18, True) for n in ("int64", "i64", "long", "sint64", "sfixed64", "integer", "bigint")},
    **{n: (18, False) for n in ("uint64", "u64", "fixed64")},
}
#: Canonical text scalar names (and string formats) with a fixed ISO layout → length.
_FIXED_TEXT: Dict[str, int] = {
    "date": 10, "time": 15, "datetime": 32, "date-time": 32, "timestamp": 32, "instant": 32,
    "uuid": 36, "guid": 36,
}
_TEXT = frozenset({"string", "str", "text", "char", "id", "uri", "url", "email", "hostname", "ipv4", "ipv6",
                   "duration", "bytes", "binary", "blob"})
_FLOATS = {"float": "COMP-1", "f32": "COMP-1", "float32": "COMP-1",
           "double": "COMP-2", "f64": "COMP-2", "float64": "COMP-2", "number": "COMP-2"}
_DECIMALS = frozenset({"decimal", "numeric", "money"})
_BOOLEANS = frozenset({"bool", "boolean"})
_NONE = frozenset({"null", "void", "none"})
#: Total digits of a synthesized decimal (IBM packed decimal allows up to 31).
_DECIMAL_DIGITS = 18


@dataclass(frozen=True)
class CopybookPlanOptions:
    """What the plan synthesizes where the model says nothing (the emitter's options).

    Attributes:
        numeric_usage: ``"comp"`` (binary integers, packed decimals, floats) or ``"display"`` (zoned).
        default_string_length: Length of text with no ``maxLength`` and no fixed layout.
        default_occurs: Maximum occurrences of a list with no ``maxItems``.
        decimal_scale: Digits after the point of a decimal with no ``multipleOf``.
    """

    numeric_usage: str = "comp"
    default_string_length: int = 255
    default_occurs: int = 10
    decimal_scale: int = 2


class CobolNamer:
    """Copybook-wide unique COBOL data names (deterministic for the same sequence of requests)."""

    def __init__(self) -> None:
        self._used: Set[str] = set()

    def name(self, *parts: str) -> str:
        """The unique data name spelled from ``parts`` (joined by hyphens), within 30 characters."""
        base = cobol_name("-".join(p for p in parts if p))
        candidate, suffix = base, 2
        while candidate in self._used:
            tail = f"-{suffix}"
            candidate = base[: MAX_NAME_LENGTH - len(tail)].rstrip("-") + tail
            suffix += 1
        self._used.add(candidate)
        return candidate


def cobol_name(source: str) -> str:
    """``source`` as a COBOL data name (not checked for uniqueness).

    ``orderLineItems`` → ``ORDER-LINE-ITEMS``, ``order_id`` → ``ORDER-ID``, ``2fa`` → ``2FA`` (a name may
    start with a digit when it holds a letter), ``2024`` → ``X-2024``, ``status`` → ``STATUS-X`` (a reserved
    word); cut to 30 characters, never ending in a hyphen.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", source or "")
    word = re.sub(r"[^A-Za-z0-9]+", "-", spaced).strip("-").upper() or "ITEM"
    if not any(ch.isalpha() for ch in word):
        word = f"X-{word}"
    if word in COBOL_RESERVED_WORDS:
        word = f"{word}-X"
    return word[:MAX_NAME_LENGTH].rstrip("-")


def record_types(api: CanonicalApi) -> List[Type]:
    """The records written as ``01`` levels: those no other record or union contains.

    A model whose records all contain one another (a cycle) writes its first record.
    """
    records = [t for t in api.types if t.kind is TypeKind.RECORD]
    by_key = {t.key: t for t in api.types}
    by_name = {t.name: t for t in api.types if t.name and [x.name for x in api.types].count(t.name) == 1}
    contained: Set[str] = set()

    def note(ref: Optional[TypeRef], seen: Set[str]) -> None:
        while ref is not None and ref.is_list():
            ref = ref.item
        if ref is None:
            return
        target = by_key.get(ref.name or "") or by_name.get(ref.name or "")
        if target is None or target.key in seen:
            return
        if target.kind is TypeKind.ALIAS:
            note(target.aliased, seen | {target.key})
        elif target.kind is TypeKind.UNION:
            for member in target.union_members:
                note(TypeRef(name=member), seen | {target.key})
        else:
            contained.add(target.key)

    for type_ in api.types:
        for f in type_.fields:
            note(f.type, {type_.key})
    roots = [t for t in records if t.key not in contained]
    return roots or records[:1]


class _Planner:
    """Builds the copybook trees of one model (single use)."""

    def __init__(self, api: CanonicalApi, options: CopybookPlanOptions, losses: LossTracker) -> None:
        self._api = api
        self._options = options
        self._losses = losses
        self._names = CobolNamer()
        self._by_key = {t.key: t for t in api.types if t.key}
        names = [t.name for t in api.types]
        self._by_name = {t.name: t for t in api.types if t.name and names.count(t.name) == 1}
        self._noted: Set[Tuple[str, str]] = set()

    # --- records -------------------------------------------------------------

    def records(self) -> List[Dict[str, Any]]:
        """One ``01`` tree per record type the model writes."""
        trees = []
        for record in record_types(self._api):
            name = self._name(record.name or record.key, record.key, "record")
            tree = _node(name)
            tree["children"] = self._children(record, path={record.key}, in_table=False)
            if not tree["children"]:
                tree["children"] = [self._filler()]
            _assign_levels(tree)
            trees.append(tree)
        return trees

    def _children(self, record: Type, *, path: Set[str], in_table: bool) -> List[Dict[str, Any]]:
        """The items of a record's fields, in field order."""
        items: List[Dict[str, Any]] = []
        for f in sorted(record.fields, key=lambda x: x.field_number or 0):
            items += self._field(f, path=path, in_table=in_table)
        return items

    def _filler(self) -> Dict[str, Any]:
        """A one-byte placeholder for a group that would otherwise be empty (COBOL forbids that)."""
        return _node("FILLER", picture="X(1)")

    # --- fields --------------------------------------------------------------

    def _field(self, f: CanonicalField, *, path: Set[str], in_table: bool) -> List[Dict[str, Any]]:
        """The item(s) for one field: the item, preceded by its counter when it is a variable table."""
        name = self._name(f.name or f.key, f.key, "field")
        return self._item(name, f.type, f.constraints, f.key, path=path, in_table=in_table)

    def _item(
        self, name: str, ref: TypeRef, constraints: Optional[Constraints], owner: str, *, path: Set[str],
        in_table: bool,
    ) -> List[Dict[str, Any]]:
        """``ref`` laid out under the data name ``name`` (an empty list when it is dropped)."""
        if ref.is_list():
            return self._table(name, ref, constraints, owner, path=path, in_table=in_table)
        target = self._by_key.get(ref.name or "") or self._by_name.get(ref.name or "")
        if target is None:
            return self._scalar(name, ref.name or "string", constraints, owner)
        if target.key in path:
            self._loss(LossKind.NA, "recursion-cut", owner, f"{owner!r} refers back to {target.key!r}, which "
                       "contains it; a copybook writes nested records inline, so the reference is left out.")
            return []
        if target.kind is TypeKind.RECORD:
            node = _node(name)
            node["children"] = self._children(target, path=path | {target.key}, in_table=in_table) or [
                self._filler()]
            return [node]
        if target.kind is TypeKind.UNION:
            return [self._union(name, target, owner, path=path, in_table=in_table)]
        if target.kind is TypeKind.ENUM:
            return [self._enum(name, target)]
        if target.kind is TypeKind.MAP:
            self._loss(LossKind.NA, "map-dropped", owner, f"A copybook has no map; {owner!r} (a map) is left out.")
            return []
        if target.kind is TypeKind.ALIAS and target.aliased is not None:
            return self._item(name, target.aliased, constraints or target.constraints, owner,
                              path=path | {target.key}, in_table=in_table)
        return self._scalar(name, target.name or target.key, constraints or target.constraints, owner)

    def _table(
        self, name: str, ref: TypeRef, constraints: Optional[Constraints], owner: str, *, path: Set[str],
        in_table: bool,
    ) -> List[Dict[str, Any]]:
        """A list as ``OCCURS``: fixed when its size is, else ``DEPENDING ON`` a synthesized counter."""
        c = constraints or Constraints()
        low = c.min_items or 0
        high = c.max_items
        if high is None:
            high = max(self._options.default_occurs, low or 1)
            self._loss(LossKind.INFERRED, "occurs-synthesized", owner, f"{owner!r} has no maxItems; it is "
                       f"written to hold at most {high} occurrences (the default).")
        high = max(high, 1)
        inner_constraints = c.model_copy(update={"min_items": None, "max_items": None, "unique_items": None})
        item = ref.item or TypeRef(name="string")
        if item.is_list():
            # A list of lists: each occurrence is a group holding the inner table.
            node = _node(name)
            node["children"] = self._table(self._names.name(name, "ITEM"), item, inner_constraints, owner,
                                           path=path, in_table=True)
        else:
            laid = self._item(name, item, inner_constraints, owner, path=path, in_table=True)
            if not laid:
                return []
            node = laid[0]
            if len(laid) > 1 or node.get("occurs_max") is not None:
                node = _node(name)
                node["children"] = laid
        fixed = low == high or in_table
        if fixed:
            if in_table and low != high:
                self._loss(LossKind.INFERRED, "occurs-fixed", owner, f"{owner!r} is inside another table, where "
                           f"DEPENDING ON is not allowed; it is a fixed table of {high}.")
            node["occurs_min"], node["occurs_max"] = high, high
            return [node]
        counter = self._names.name(name, "COUNT")
        self._loss(LossKind.INFERRED, "counter-synthesized", owner, f"{owner!r} varies in size; it is written "
                   f"OCCURS {max(low, 0)} TO {high} DEPENDING ON {counter}, a counter written just before it.")
        node["occurs_min"], node["occurs_max"], node["depending_on"] = max(low, 0), high, counter
        return [_node(counter, picture=self._integer_picture(4, signed=True), usage=self._binary()), node]

    def _union(self, name: str, union: Type, owner: str, *, path: Set[str], in_table: bool) -> Dict[str, Any]:
        """A union as a group of members that share storage: each after the first ``REDEFINES`` it."""
        group = _node(name)
        members: List[Dict[str, Any]] = []
        for member in union.union_members:
            target = self._by_key.get(member) or self._by_name.get(member)
            label = target.name if target is not None else member.split(".")[-1]
            laid = self._item(self._names.name(name, cobol_name(label)), TypeRef(name=member), None, owner,
                              path=path | {union.key}, in_table=in_table)
            if laid:
                members.append(laid[0] if len(laid) == 1 else {**_node(self._names.name(name, "ALT")),
                                                               "children": laid})
        if not members:
            group["children"] = [self._filler()]
            return group
        members.sort(key=lambda m: -(_size(m) or 0))
        for member in members[1:]:
            member["redefines"] = members[0]["name"]
        if len(members) > 1:
            self._loss(LossKind.INFERRED, "union-as-redefines", owner, f"The union {union.key!r} is written as "
                       f"items that share storage (REDEFINES {members[0]['name']}); a reader needs another field to "
                       "know which one holds data.")
        group["children"] = members
        return group

    def _enum(self, name: str, enum: Type) -> Dict[str, Any]:
        """An enum as one item with an ``88`` condition per value."""
        values = [m.value if m.value is not None else m.name for m in enum.enum_values]
        numeric = bool(values) and all(isinstance(v, int) and not isinstance(v, bool) for v in values)
        if numeric:
            digits = max(len(str(abs(v))) for v in values)
            node = _node(name, picture=self._integer_picture(digits, signed=min(values) < 0))
        else:
            values = [str(v) for v in values]
            node = _node(name, picture=f"X({max([len(v) for v in values] or [1]) or 1})")
        node["conditions"] = [
            {"name": self._names.name(name, cobol_name(str(m.name or v))), "value": str(v), "numeric": numeric}
            for m, v in zip(enum.enum_values, values)
        ]
        return node

    # --- scalars -------------------------------------------------------------

    def _scalar(self, name: str, scalar: str, constraints: Optional[Constraints], owner: str) -> List[Dict[str, Any]]:
        """An elementary item for a canonical scalar."""
        c = constraints or Constraints()
        key = scalar.lower()
        fmt = (c.format or "").lower()
        if key in _NONE:
            self._loss(LossKind.NA, "field-dropped", owner, f"{owner!r} has the type {scalar!r}, which holds no "
                       "value; it is left out.")
            return []
        if key in _BOOLEANS:
            node = _node(name, picture="X(1)")
            node["conditions"] = [
                {"name": self._names.name(name, "TRUE"), "value": "Y", "numeric": False},
                {"name": self._names.name(name, "FALSE"), "value": "N", "numeric": False},
            ]
            return [node]
        if key in _INTEGERS:
            digits, signed = _INTEGERS[key]
            if c.minimum is not None and c.minimum >= 0:
                signed = False
            return [_node(name, picture=self._integer_picture(digits, signed=signed), usage=self._binary())]
        if key in _DECIMALS:
            return [self._decimal(name, c)]
        if key in _FLOATS:
            if self._options.numeric_usage == "display":
                self._loss(LossKind.INFERRED, "float-as-decimal", owner, f"{owner!r} is a floating-point number; "
                           "with DISPLAY usage it is written as a zoned decimal, which has a fixed scale.")
                return [self._decimal(name, c)]
            return [_node(name, usage=_FLOATS[key])]
        length = c.max_length or _FIXED_TEXT.get(fmt) or _FIXED_TEXT.get(key)
        if length is None:
            if key not in _TEXT:
                self._loss(LossKind.INFERRED, "unmapped-scalar", owner, f"{scalar!r} has no COBOL type; values of it "
                           "are written as text.")
            length = self._options.default_string_length
            self._loss(LossKind.INFERRED, "length-synthesized", owner, f"{owner!r} has no maxLength; it is written "
                       f"PIC X({length}) (the default length).")
        return [_node(name, picture=f"X({max(int(length), 1)})")]

    def _decimal(self, name: str, c: Constraints) -> Dict[str, Any]:
        """``S9(p)V9(s)``, packed (``COMP-3``) unless numeric usage is DISPLAY."""
        scale = _scale_of(c.multiple_of)
        scale = self._options.decimal_scale if scale is None else scale
        scale = min(max(scale, 0), _DECIMAL_DIGITS - 1)
        whole = _DECIMAL_DIGITS - scale
        sign = "S" if c.minimum is None or c.minimum < 0 else ""
        picture = f"{sign}9({whole})" + (f"V9({scale})" if scale else "")
        return _node(name, picture=picture, usage="COMP-3" if self._options.numeric_usage == "comp" else None)

    def _integer_picture(self, digits: int, *, signed: bool) -> str:
        return f"{'S' if signed else ''}9({digits})"

    def _binary(self) -> Optional[str]:
        return "COMP" if self._options.numeric_usage == "comp" else None

    # --- bookkeeping ---------------------------------------------------------

    def _name(self, source: str, key: str, what: str) -> str:
        """A unique data name for a type or field, recording a respelling."""
        name = self._names.name(source)
        # Upper-casing alone is how every COBOL name reads, not a rename worth reporting.
        if name != source.upper():
            self._loss(LossKind.INFERRED, "name-mangled", key, f"The {what} {source!r} is written as {name!r} to "
                       "follow the COBOL naming rules.")
        return name

    def _loss(self, kind: LossKind, subject: str, pointer: str, detail: str) -> None:
        if (subject, detail) in self._noted:
            return
        self._noted.add((subject, detail))
        self._losses.record(kind, subject, detail, pointer=pointer or None)


def _node(name: str, *, picture: Optional[str] = None, usage: Optional[str] = None) -> Dict[str, Any]:
    """A copybook tree node, in the shape of :func:`app.cobolcopybook_parser.field_template`."""
    return {"level": 0, "name": name, "picture": picture, "usage": usage, "occurs_min": None, "occurs_max": None,
            "depending_on": None, "redefines": None, "conditions": [], "children": []}


def _depth(node: Dict[str, Any]) -> int:
    return 1 + max([_depth(child) for child in node["children"]], default=0)


def _assign_levels(root: Dict[str, Any]) -> None:
    """``01`` for the record; below it ``05``, ``10`` … or a smaller step when the record nests deep."""
    depth = _depth(root) - 1
    step = 5 if depth * 5 <= _MAX_LEVEL else max(1, (_MAX_LEVEL - 1) // max(depth, 1))

    def walk(node: Dict[str, Any], d: int) -> None:
        node["level"] = 1 if d == 0 else (step * d if step > 1 else d + 1)
        for child in node["children"]:
            walk(child, d + 1)

    walk(root, 0)


def _size(node: Dict[str, Any]) -> Optional[int]:
    """The bytes an item takes (a table counted at its maximum), ``None`` when unknown."""
    if node["children"]:
        sizes = [_size(c) for c in node["children"] if not c.get("redefines")]
        total = None if any(s is None for s in sizes) else sum(sizes)
    else:
        total = picture_size(node.get("picture"), node.get("usage")).length
    if total is not None and node.get("occurs_max"):
        total *= int(node["occurs_max"])
    return total


def _scale_of(multiple_of: Optional[float]) -> Optional[int]:
    """The decimal places a ``multipleOf`` of ``10^-k`` implies (``0.01`` → 2), else ``None``."""
    if multiple_of is None or multiple_of <= 0:
        return None
    exponent = Decimal(repr(float(multiple_of))).normalize().as_tuple()
    digits, exp = exponent.digits, exponent.exponent
    if digits == (1,) and isinstance(exp, int):
        return max(-exp, 0)
    return None


def plan_copybook(api: CanonicalApi, options: CopybookPlanOptions, losses: LossTracker) -> List[Dict[str, Any]]:
    """Lay out ``api``'s records as copybook trees.

    Args:
        api: The canonical model.
        options: What to synthesize where the model says nothing.
        losses: Where every synthesized length, counter, rename and dropped item is recorded.

    Returns:
        One tree per ``01`` record, in the shape of :func:`app.cobolcopybook_parser.field_template`
        (plus a ``numeric`` flag on each ``88`` condition). Empty when the model has no record.
    """
    return _Planner(api, options, losses).records()
