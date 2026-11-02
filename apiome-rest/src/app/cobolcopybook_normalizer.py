"""COBOL copybook → canonical model normalizer — MFI-22.7, MFI-21.1 (#3991).

Maps a parsed :class:`~app.cobolcopybook_parser.CobolCopybookDocument` into a
:class:`~app.canonical_model.CanonicalApi` of paradigm
:attr:`~app.canonical_model.ApiParadigm.DATA_SCHEMA`:

* every **group** item (the ``01`` record and each subordinate group) → a ``RECORD`` type, one
  field per subordinate item, in source order;
* every **elementary** item → a field typed by its ``PICTURE`` and ``USAGE``
  (:func:`picture_type_ref`): alphanumeric and numeric-edited → ``string`` with its width as
  ``max_length``; an integer → ``i32`` (up to 9 digits) or ``i64`` (up to 18); a picture with an
  implied decimal point (``V``), or more than 18 digits → ``decimal``; ``COMP-1`` / ``COMP-2`` →
  ``float`` / ``double``. A numeric item carries the bounds its digits allow (``0`` minimum when
  unsigned);
* an **OCCURS** table → a list of the item's type, its bounds as ``min_items`` / ``max_items``;
* a **REDEFINES** overlay → a ``UNION`` type named ``<base>-OVERLAY`` whose members are each
  layout of the shared storage — a group's record type, or an ``ALIAS`` named after an
  elementary item. The redefined (base) item's field is typed by the union, and the items that
  redefine it are not separate fields: they are the same bytes, read another way. A ``REDEFINES``
  naming no earlier sibling stays an ordinary field (the ``cobolcopybook`` lint pack flags it).

Every field also records where it sits in the record and how its bytes are encoded
(:data:`STORAGE_NOTES`): its 1-based ``cobol_offset``, ``cobol_length`` /
``cobol_total_length`` and ``cobol_storage`` — character data in the host's EBCDIC code page,
zoned decimal, packed decimal, binary or hexadecimal floating point. The lengths come from
:func:`~app.cobolcopybook_layout.compute_layout`, under the assumptions it publishes
(:data:`~app.cobolcopybook_layout.LAYOUT_ASSUMPTIONS`), which the model carries as
``extras["cobolcopybook_encoding"]``.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from . import cobolcopybook_fingerprint  # noqa: F401 — registers the record-layout hasher
from .canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from .cobolcopybook_layout import (
    BASIS_BINARY,
    BASIS_DISPLAY,
    BASIS_FLOAT,
    BASIS_PACKED,
    LAYOUT_ASSUMPTIONS,
    FieldLayout,
    compute_layout,
    record_length_range,
)
from .cobolcopybook_parser import CobolCopybookDocument, CobolField, field_template
from .normalizer import Keys, Normalizer, normalize_ordering

__all__ = [
    "ENCODING_ASSUMED",
    "OVERLAY_SUFFIX",
    "STORAGE_NOTES",
    "CobolCopybookNormalizer",
    "picture_class",
    "picture_type_ref",
    "storage_kind",
]

_FORMAT_KEY = "cobolcopybook"

#: Suffix of the union type a REDEFINES overlay normalizes to (``PAYMENT-DETAIL-OVERLAY``).
OVERLAY_SUFFIX = "-OVERLAY"

#: The code page a copybook's character data is assumed to be in. The copybook never says, so
#: it is recorded as an assumption rather than a fact.
ENCODING_ASSUMED = "EBCDIC"

#: What each storage kind means for someone moving the bytes off the mainframe — the
#: "EBCDIC notes" a field carries in ``extras["cobol_storage"]["note"]``.
STORAGE_NOTES: Dict[str, str] = {
    "ebcdic-text": (
        "Character data in the host code page (EBCDIC; the copybook does not say which code page). "
        "Transcode it as text, one character per byte."
    ),
    "ebcdic-edited": (
        "Numeric-edited display text in the host code page (EBCDIC). Transcode it as text; it is "
        "formatted for printing, not for arithmetic."
    ),
    "zoned-decimal": (
        "Zoned decimal: one EBCDIC digit (X'F0'–X'F9') per byte, the sign overpunched in the zone "
        "nibble of the last byte (X'C' positive, X'D' negative). Convert it as a number; transcoding "
        "it as text corrupts a signed value."
    ),
    "packed-decimal": (
        "Packed decimal (COMP-3): two digits per byte and a trailing sign nibble. Binary data — never "
        "transcode it."
    ),
    "binary": "Big-endian two's-complement binary (COMP / BINARY). Never transcode it.",
    "hex-float": (
        "IBM hexadecimal floating point (COMP-1 / COMP-2) unless the program is compiled for IEEE "
        "floating point. Never transcode it."
    ),
    "unsized": "The storage of this item is not computed, so how its bytes are encoded is not stated.",
}

#: PICTURE symbols of a numeric (non-edited) item: digits, sign, implied point and scaling.
_NUMERIC_SYMBOLS = frozenset("9SVP")
#: PICTURE symbols of an alphanumeric or alphabetic item.
_TEXT_SYMBOLS = frozenset("XA")
#: The most digits a numeric bound can carry exactly as a double-precision constraint.
_EXACT_DIGITS = 15
#: A repetition count inside a PICTURE, e.g. the ``(10)`` of ``X(10)``.
_REPEAT = re.compile(r"\(\d+\)")


def _type_key(name: str, namespace: Optional[str]) -> str:
    return Keys.type(name, namespace)


def picture_class(picture: Optional[str]) -> Optional[str]:
    """Classify a PICTURE character-string.

    Args:
        picture: The picture, without the ``PIC`` keyword, or ``None``.

    Returns:
        ``"text"`` for an alphanumeric / alphabetic picture (any ``X`` or ``A``), ``"numeric"`` for
        one made only of ``9``, ``S``, ``V`` and ``P``, ``"edited"`` for any other (numeric-edited:
        ``Z``, ``*``, ``$``, ``,`` …), or ``None`` when there is no picture.
    """
    if not picture or not picture.strip():
        return None
    symbols = set(_REPEAT.sub("", picture.strip().upper().rstrip(".")))
    if symbols & _TEXT_SYMBOLS:
        return "text"
    if symbols <= _NUMERIC_SYMBOLS:
        return "numeric"
    return "edited"


def storage_kind(field: CobolField, layout: Optional[FieldLayout]) -> str:
    """Name how one elementary item's bytes are encoded — a key of :data:`STORAGE_NOTES`.

    Args:
        field: The elementary item.
        layout: Its computed layout, or ``None``.

    Returns:
        The storage kind: ``ebcdic-text``, ``ebcdic-edited``, ``zoned-decimal``,
        ``packed-decimal``, ``binary``, ``hex-float`` or ``unsized``.
    """
    basis = layout.picture.basis if layout is not None and layout.picture is not None else None
    if basis == BASIS_PACKED:
        return "packed-decimal"
    if basis == BASIS_BINARY:
        return "binary"
    if basis == BASIS_FLOAT:
        return "hex-float"
    if basis == BASIS_DISPLAY:
        kind = picture_class(field.picture)
        if kind == "numeric":
            return "zoned-decimal"
        if kind == "edited":
            return "ebcdic-edited"
        return "ebcdic-text"
    return "unsized"


def _numeric_bounds(digits: int, decimals: int, signed: bool) -> Tuple[float, float]:
    """The ``(minimum, maximum)`` a numeric picture of ``digits`` / ``decimals`` can hold."""
    integer_digits = max(digits - decimals, 0)
    maximum = round(10**integer_digits - 10 ** (-decimals), decimals) if decimals else float(10**digits - 1)
    return (-maximum if signed else 0.0), maximum


def picture_type_ref(
    field: CobolField, layout: Optional[FieldLayout]
) -> Tuple[TypeRef, Optional[Constraints]]:
    """The canonical scalar of one elementary item (see the module docstring for the mapping).

    Args:
        field: The elementary item.
        layout: Its computed layout (gives the width and digit counts), or ``None``.

    Returns:
        ``(type_ref, constraints)``: a non-nullable scalar :class:`TypeRef`, and the
        :class:`Constraints` its picture implies — ``max_length`` for text, the numeric bounds for a
        number — or ``None`` when it implies none that are known.
    """
    if not field.picture and field.usage in ("COMP-1", "COMP-2"):
        # A floating-point item has a USAGE and no PICTURE (MFX-23.1).
        return TypeRef(name="float" if field.usage == "COMP-1" else "double", nullable=False), None
    size = layout.picture if layout is not None else None
    kind = picture_class(field.picture)
    if kind is None:
        return TypeRef(name="string", nullable=False), None
    if kind in ("text", "edited"):
        width = size.length if size is not None and size.basis == BASIS_DISPLAY else None
        return TypeRef(name="string", nullable=False), (Constraints(max_length=width) if width else None)
    digits = size.digits if size is not None else None
    decimals = (size.decimals or 0) if size is not None else 0
    if not digits:
        return TypeRef(name="i64", nullable=False), None
    if decimals or digits > 18:
        name = "decimal"
    elif digits <= 9:
        name = "i32"
    else:
        name = "i64"
    if "P" in (field.picture or "").upper() or digits > _EXACT_DIGITS:
        # A ``P`` scales the value by a power of ten the digit count does not show, and a bound of
        # more than 15 digits is not exact in a (floating-point) constraint: no bound, not a wrong one.
        return TypeRef(name=name, nullable=False), None
    minimum, maximum = _numeric_bounds(digits, decimals, bool(size and size.signed))
    return TypeRef(name=name, nullable=False), Constraints(minimum=minimum, maximum=maximum)


def _occurs_ref(
    field: CobolField, inner: TypeRef, constraints: Optional[Constraints]
) -> Tuple[TypeRef, Optional[Constraints]]:
    """Wrap ``inner`` in a list when ``field`` is an OCCURS table, its bounds as item counts.

    Args:
        field: The item.
        inner: The type of one occurrence.
        constraints: The constraints of one occurrence (a picture's width or bounds).

    Returns:
        ``(type_ref, constraints)`` for the field: ``inner`` and ``constraints`` unchanged when the
        item is not a table; otherwise a list of ``inner`` with ``min_items`` / ``max_items`` added.
    """
    if field.occurs_max is None:
        return inner, constraints
    items = {
        "min_items": field.occurs_min if field.occurs_min is not None else field.occurs_max,
        "max_items": field.occurs_max,
    }
    merged = constraints.model_copy(update=items) if constraints is not None else Constraints(**items)
    return TypeRef(item=inner, nullable=False), merged


def _storage_extras(field: CobolField, layout: Optional[FieldLayout]) -> Dict[str, Any]:
    """Where one item sits in the record and how its bytes are encoded."""
    extras: Dict[str, Any] = {
        "cobol_offset": layout.offset if layout is not None else None,
        "cobol_offset_variable": bool(layout and layout.offset_variable),
        "cobol_length": layout.length if layout is not None else None,
        "cobol_total_length": layout.total_length if layout is not None else None,
    }
    if not field.children:
        kind = storage_kind(field, layout)
        extras["cobol_storage"] = {"kind": kind, "note": STORAGE_NOTES[kind]}
    return extras


def _clause_extras(field: CobolField) -> Dict[str, Any]:
    """The copybook clauses of one item, as declared."""
    return {
        "cobol_level": field.level,
        "cobol_picture": field.picture,
        "cobol_usage": field.usage,
        "cobol_occurs_min": field.occurs_min,
        "cobol_occurs_max": field.occurs_max,
        "cobol_depending_on": field.depending_on,
        "cobol_redefines": field.redefines,
        "cobol_conditions": [
            {"name": condition.name, "value": condition.value} for condition in field.conditions
        ],
    }


def _overlays(children: List[CobolField]) -> Dict[str, List[CobolField]]:
    """Group a group's children into REDEFINES overlays.

    Args:
        children: One group's subordinate items, in source order.

    Returns:
        ``base name → [base, redefining item, …]`` for every base some later sibling redefines.
        A redefining item that names another redefining item belongs to that item's base (the
        storage is still the base's); one naming no earlier sibling belongs to no overlay.
    """
    base_of: Dict[str, str] = {}
    overlays: Dict[str, List[CobolField]] = {}
    for child in children:
        if child.redefines and child.redefines in base_of:
            base = base_of[child.redefines]
            overlays.setdefault(base, []).append(child)
            base_of[child.name] = base
        elif not child.redefines:
            base_of[child.name] = child.name
            overlays.setdefault(child.name, [child])
    return {base: members for base, members in overlays.items() if len(members) > 1}


class _Builder:
    """Builds the types of one copybook record (single use)."""

    def __init__(self, namespace: str, layouts: Dict[int, FieldLayout]) -> None:
        self._namespace = namespace
        self._layouts = layouts
        self.types: Dict[str, Type] = {}

    def record(self, group: CobolField) -> str:
        """Build the RECORD type of one group (and every type under it); return its key."""
        type_key = _type_key(group.name, self._namespace)
        if type_key in self.types:
            return type_key
        # Reserve the key first, so a repeated group name resolves to the first one declared.
        self.types[type_key] = Type(key=type_key, name=group.name, kind=TypeKind.RECORD)
        overlays = _overlays(group.children)
        redefiners = {id(m) for members in overlays.values() for m in members[1:]}
        fields: List[CanonicalField] = []
        seen: Dict[str, int] = {}
        for child in group.children:
            if id(child) in redefiners:
                continue
            seen[child.name] = seen.get(child.name, 0) + 1
            # A repeated name (FILLER most of all) needs its own key, or diff pairs the wrong items.
            key_name = child.name if seen[child.name] == 1 else f"{child.name}#{seen[child.name]}"
            members = overlays.get(child.name) if seen[child.name] == 1 else None
            extras = {**_clause_extras(child), **_storage_extras(child, self._layouts.get(id(child)))}
            if members:
                inner, constraints = TypeRef(name=self.overlay(members), nullable=False), None
                extras["cobol_redefined_by"] = [m.name for m in members[1:]]
            else:
                inner, constraints = self._item_ref(child)
            type_ref, constraints = _occurs_ref(child, inner, constraints)
            fields.append(
                CanonicalField(
                    key=Keys.field(type_key, key_name),
                    name=child.name,
                    type=type_ref,
                    constraints=constraints,
                    field_number=len(fields) + 1,
                    description=child.picture,
                    extras=extras,
                )
            )
        layout = self._layouts.get(id(group))
        minimum, maximum = record_length_range(layout) if layout is not None else (None, None)
        self.types[type_key] = Type(
            key=type_key,
            name=group.name,
            kind=TypeKind.RECORD,
            fields=fields,
            extras={
                "cobol_level": group.level,
                "cobol_kind": "group",
                "cobol_length": {"min": minimum, "max": maximum},
            },
        )
        return type_key

    def _item_ref(self, item: CobolField) -> Tuple[TypeRef, Optional[Constraints]]:
        """The type of one occurrence of an item: its group's record, or its PICTURE's scalar.

        Returns:
            ``(type_ref, constraints)``; a group's constraints are always ``None``.
        """
        if item.children:
            return TypeRef(name=self.record(item), nullable=False), None
        return picture_type_ref(item, self._layouts.get(id(item)))

    def overlay(self, members: List[CobolField]) -> str:
        """Build the UNION type of one REDEFINES overlay; return its key.

        Args:
            members: The base item first, then each item that redefines it.

        Returns:
            The union type's key. Each member is a type: a group's record, or an ``ALIAS`` named
            after an elementary item, aliasing its scalar (a list when it is a table).
        """
        base = members[0]
        name = f"{base.name}{OVERLAY_SUFFIX}"
        type_key = _type_key(name, self._namespace)
        member_keys: List[str] = []
        layouts: List[Dict[str, Any]] = []
        for member in members:
            if member.children:
                member_key = self.record(member)
            else:
                member_key = _type_key(member.name, self._namespace)
                aliased, constraints = _occurs_ref(member, *self._item_ref(member))
                self.types.setdefault(
                    member_key,
                    Type(
                        key=member_key,
                        name=member.name,
                        kind=TypeKind.ALIAS,
                        aliased=aliased,
                        constraints=constraints,
                        description=member.picture,
                        extras={
                            **_clause_extras(member),
                            **_storage_extras(member, self._layouts.get(id(member))),
                            "cobol_kind": "elementary",
                        },
                    ),
                )
            member_keys.append(member_key)
            layout = self._layouts.get(id(member))
            layouts.append(
                {
                    "name": member.name,
                    "redefines": member.redefines,
                    "kind": "group" if member.children else "elementary",
                    "occurs_max": member.occurs_max,
                    "total_length": layout.total_length if layout is not None else None,
                }
            )
        base_layout = self._layouts.get(id(base))
        self.types[type_key] = Type(
            key=type_key,
            name=name,
            kind=TypeKind.UNION,
            union_members=member_keys,
            description=f"Storage of {base.name}, laid out {len(members)} ways (REDEFINES).",
            extras={
                "cobol_kind": "redefines",
                "cobol_base": base.name,
                "cobol_layouts": layouts,
                "cobol_offset": base_layout.offset if base_layout is not None else None,
                "cobol_storage_length": base_layout.total_length if base_layout is not None else None,
            },
        )
        return type_key


class CobolCopybookNormalizer(Normalizer, register=True):
    """Normalize a parsed COBOL copybook into a :class:`CanonicalApi`."""

    format = _FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Normalize ``source`` (see the module docstring).

        Args:
            source: The parsed :class:`~app.cobolcopybook_parser.CobolCopybookDocument`.
            include_raw: Keep the copybook text on the model (``raw["cobolcopybook"]``).

        Returns:
            The canonical model, ordered canonically.

        Raises:
            ValueError: If ``source`` is not a copybook document.
        """
        if not isinstance(source, CobolCopybookDocument):
            raise ValueError(
                "COBOL copybook source must be a CobolCopybookDocument "
                "(see app.cobolcopybook_parser.parse_cobolcopybook)"
            )

        root = source.root
        namespace = re.sub(r"[^A-Za-z0-9_-]+", "-", root.name).strip("-") or "copybook"
        layouts = compute_layout(root)
        builder = _Builder(namespace, layouts)
        if root.children:
            builder.record(root)
        minimum, maximum = record_length_range(layouts[id(root)])
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=root.name, namespace=namespace),
            title=root.name,
            types=list(builder.types.values()),
            raw={"cobolcopybook": source.raw} if include_raw else None,
            extras={
                "cobolcopybook_root": root.name,
                "cobolcopybook_tree": field_template(root),
                "cobolcopybook_record_length": {"min": minimum, "max": maximum},
                "cobolcopybook_encoding": {
                    "assumed": ENCODING_ASSUMED,
                    "notes": list(LAYOUT_ASSUMPTIONS),
                },
            },
        )
        return normalize_ordering(api)
