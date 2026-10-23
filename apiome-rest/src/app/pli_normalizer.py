"""PL/I structures → canonical model normalizer — FMT-11.1 (#5480).

Maps a parsed :class:`~app.pli_parser.PliDocument` onto the **data_schema** paradigm:

.. code-block:: text

    DCL 1 ORDER_REC,                 → RECORD  pli.ORDER_REC
          2 SHIP_TO LIKE ADDR_BLK,   → field   SHIP_TO: ADDR_BLK          (the cloned block's record)
          2 LINES(20),               → field   LINES: list of 20 ORDER_REC.LINES
            3 SKU  CHAR(18),         →   RECORD pli.ORDER_REC.LINES, field SKU: string ≤ 18
            3 QTY  FIXED DEC(9,3),   →   field QTY: decimal
          2 BODY UNION,              → RECORD  pli.ORDER_REC.BODY whose fields all start at one
                                       offset — each later member records the first in
                                       ``redefines``, the copybook REDEFINES presentation

Scalars: ``CHAR`` / ``GRAPHIC`` / ``WIDECHAR`` and character pictures are ``string`` with
``max_length``; ``FIXED`` with a scale is ``decimal``, without one ``integer``; ``FLOAT`` is ``float``
(4 bytes) or ``double``; ``BIT(1)`` is ``boolean`` and a longer bit string ``bytes``; numeric pictures
are ``integer`` / ``decimal`` and edited ones ``string``; locators and areas are ``bytes``; program
control items (``ENTRY``, ``FILE`` …) are ``any``. Dimensions nest lists, one per dimension, with
exactly the declared count.

Every field and record carries its storage — offset (1-based, relative to the record it is a field
of), length, total length, alignment, padding, bit offset — in ``extras['pli']``; each major
structure additionally carries the absolute **storage map** of every item, LIKE copies included, and
the document carries :data:`~app.pli_layout.LAYOUT_ASSUMPTIONS`, the statement of what those byte
counts assume. A structure an unresolved ``%INCLUDE`` leaves incomplete is marked ``partial`` with
the member named. Declared limits are counted in ``extras['pli']['capability_limits']``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

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
from .normalizer import Keys, Normalizer, normalize_ordering
from .pli_layout import LAYOUT_ASSUMPTIONS, ItemLayout, compute_layout, picture_info
from .pli_parser import FORMAT_KEY, PliData, PliDocument, PliItem
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "PLI_EXTRAS_KEY",
    "PLI_LIMIT_DETAILS",
    "PLI_NAMESPACE",
    "PLI_PARTIAL_LIMITS",
    "PliNormalizer",
    "declared_attributes",
]

#: Root extras key of the projection record (also used on types and fields).
PLI_EXTRAS_KEY = "pli"
#: The namespace record types are keyed under.
PLI_NAMESPACE = "pli"

#: The declared-limit vocabulary (stable keys → reviewed sentence).
PLI_LIMIT_DETAILS: Dict[str, str] = {
    "pli.unresolved_include": (
        "An %INCLUDE member was not in the upload. A structure the directive sits inside is marked "
        "partial with the member named and has no length from that point on; a directive between "
        "declarations that nothing references leaves the records whole. Upload the members "
        "together as a fileset to resolve it."
    ),
    "pli.union_storage": (
        "UNION members share one storage area. The canonical model has no overlay record, so the "
        "members are fields that all start at the union's offset; each later member names the first "
        "in extras['pli']['redefines'], as a COBOL REDEFINES does."
    ),
    "pli.refer_extent": (
        "A REFER or * extent is a runtime value: the item has no fixed length, lists carry no item "
        "count, and nothing after it has a single offset."
    ),
    "pli.default_attributes": (
        "An element declared without (some of) its data attributes takes PL/I's language defaults "
        "(RULES(IBM)); which ones were assumed is in extras['pli']['defaulted']."
    ),
    "pli.edited_picture": (
        "An edited numeric picture (Z, *, $, comma, point, slash, B, sign or CR / DB insertion) "
        "formats a number for display; the field is a string and the picture is kept in "
        "extras['pli']['picture']."
    ),
    "pli.locator_item": (
        "A POINTER, OFFSET, HANDLE or AREA holds an address or a storage pool, which has no meaning "
        "outside the running program; it is projected to bytes of its size."
    ),
    "pli.program_control_item": (
        "An ENTRY, FILE, LABEL, FORMAT, EVENT, TASK, ORDINAL or TYPE item describes program control "
        "rather than data; it is projected to `any` and has no storage length."
    ),
    "pli.unread_attribute": (
        "An attribute this reader does not know is kept in extras['pli']['unread'] and not "
        "interpreted; the item is sized from the attributes it does know."
    ),
    "pli.scalar_declaration": (
        "A declaration without a level number (a pointer, a counter, a standalone string) is not a "
        "record; it is listed in extras['pli']['scalars'] and not modelled."
    ),
    "pli.non_declare_statement": (
        "A statement that is not a declaration (a PROCEDURE, an assignment, a preprocessor statement "
        "other than %INCLUDE) is not read; it is listed in extras['pli']['statements']."
    ),
    "pli.unreferenced_member": (
        "A fileset member no %INCLUDE reached is not read; import it as its own root if it declares records of its own."
    ),
}
#: Limits whose construct is still modelled, with only a detail lost.
PLI_PARTIAL_LIMITS = frozenset(
    {
        "pli.unresolved_include",
        "pli.union_storage",
        "pli.refer_extent",
        "pli.default_attributes",
        "pli.edited_picture",
        "pli.locator_item",
        "pli.program_control_item",
        "pli.unread_attribute",
    }
)

_LOCATOR_KINDS = frozenset({"pointer", "offset", "handle", "area"})
_PROGRAM_CONTROL_KINDS = frozenset({"entry", "file", "label", "format", "event", "task", "ordinal", "type"})


def declared_attributes(data: PliData) -> str:
    """Render an element's data attributes the way a declaration writes them.

    Args:
        data: The (defaults-completed) data description.

    Returns:
        ``CHAR(50) VARYING``, ``FIXED DEC(13,2)``, ``FIXED BIN(31) UNSIGNED``, ``PIC'S9(7)V99'`` ….
    """
    kind = data.kind
    if kind in {"character", "bit", "graphic", "widechar"}:
        word = {"character": "CHAR", "bit": "BIT", "graphic": "GRAPHIC", "widechar": "WIDECHAR"}[kind]
        length = data.length if data.length is not None else data.length_text
        return f"{word}({length})" + (f" {data.varying}" if data.varying else "")
    if kind == "picture":
        return f"PIC'{data.picture}'"
    if kind.startswith(("fixed-", "float-")):
        scale, base = kind.split("-")
        precision = f"{data.precision}" + (f",{data.scale}" if data.scale is not None else "")
        text = f"{scale.upper()} {'DEC' if base == 'decimal' else 'BIN'}({precision})"
        return text + (" UNSIGNED" if data.unsigned else "") + (" COMPLEX" if data.complex else "")
    word = kind.upper()
    if kind == "area":
        return f"AREA({data.length if data.length is not None else data.length_text or 1000})"
    return f"{word}({data.target})" if data.target else word


def _scalar(data: PliData, limits: LimitRecorder, location: str) -> Tuple[str, Optional[Constraints]]:
    """The canonical scalar and constraints of an element, recording any limit it meets."""
    kind = data.kind
    if kind in {"character", "graphic", "widechar"}:
        return "string", Constraints(max_length=data.length) if data.length is not None else None
    if kind == "bit":
        return ("boolean", None) if data.length == 1 and not data.varying else ("bytes", None)
    if kind == "fixed-decimal" or kind == "fixed-binary":
        return ("decimal" if data.scale else "integer"), None
    if kind in {"float-decimal", "float-binary"}:
        short = (data.precision or 0) <= (21 if kind == "float-binary" else 6)
        return ("float" if short else "double"), None
    if kind == "picture":
        info = picture_info(data.picture)
        if info.character:
            return "string", Constraints(max_length=info.positions) if info.positions is not None else None
        if info.edited:
            limits.record("pli.edited_picture", location=location)
            return "string", Constraints(max_length=info.positions) if info.positions is not None else None
        return ("decimal" if info.decimals else "integer"), None
    if kind in _LOCATOR_KINDS:
        limits.record("pli.locator_item", location=location)
        return "bytes", None
    limits.record("pli.program_control_item", location=location)
    return "any", None


def _wrap_dimensions(element: TypeRef, item: PliItem) -> Tuple[TypeRef, Optional[Constraints]]:
    """Nest ``element`` in one list per dimension, innermost last; return the ref and its constraints."""
    if not item.dimensions:
        return element, None
    ref = element
    for _ in item.dimensions:
        ref = TypeRef(item=ref, nullable=False)
    outer = item.dimensions[0].count
    constraints = Constraints(min_items=outer, max_items=outer) if outer is not None else None
    return ref, constraints


def _storage_payload(layout: ItemLayout, base: int) -> Dict[str, Any]:
    """An item's storage facts, omitting unknowns; ``offset`` is relative to ``base`` (1-based)."""
    payload: Dict[str, Any] = {}
    if layout.offset is not None:
        payload["offset"] = layout.offset - base + 1
    if layout.offset_variable:
        payload["offsetVariable"] = True
    if layout.bit_offset:
        payload["bitOffset"] = layout.bit_offset
    if layout.length is not None:
        payload["length"] = layout.length
    if layout.bits is not None:
        payload["bits"] = layout.bits
    if layout.total_length is not None and layout.total_length != layout.length:
        payload["totalLength"] = layout.total_length
    if layout.occurrences not in (None, 1):
        payload["occurrences"] = layout.occurrences
    payload["aligned"] = layout.aligned
    if layout.padding_bits:
        payload["paddingBits"] = layout.padding_bits
    if layout.variable:
        payload["variableLength"] = True
    if layout.basis:
        payload["storageBasis"] = layout.basis
    if layout.union:
        payload["union"] = layout.union
    if layout.redefines:
        payload["redefines"] = layout.redefines
    if layout.reason:
        payload["lengthUnknownReason"] = layout.reason
    return payload


def _dimension_payload(item: PliItem) -> List[Dict[str, Any]]:
    return [
        {
            "bounds": dimension.text,
            **({"lower": dimension.lower} if dimension.lower is not None else {}),
            **({"upper": dimension.upper} if dimension.upper is not None else {}),
            **({"refer": dimension.refer} if dimension.refer else {}),
        }
        for dimension in item.dimensions
    ]


def _item_payload(item: PliItem) -> Dict[str, Any]:
    """Declared facts of one item (level, attributes, storage class …), omitting what it lacks."""
    payload: Dict[str, Any] = {"level": item.level}
    if item.data is not None:
        payload["attributes"] = declared_attributes(item.data)
        payload["dataKind"] = item.data.kind
        if item.data.precision is not None:
            payload["precision"] = item.data.precision
        if item.data.scale is not None:
            payload["scale"] = item.data.scale
        if item.data.picture is not None:
            payload["picture"] = item.data.picture
        if item.data.varying:
            payload["varying"] = item.data.varying
        if item.data.refer:
            payload["lengthRefer"] = item.data.refer
        if item.data.defaulted:
            payload["defaulted"] = list(item.data.defaulted)
    if item.dimensions:
        payload["dimensions"] = _dimension_payload(item)
    for key, value in (
        ("like", item.like),
        ("alignment", item.alignment),
        ("storageClass", item.storage_class),
        ("based", item.locator),
        ("defined", item.defined),
        ("position", item.position),
        ("scope", item.scope),
        ("clonedFrom", item.cloned_from),
    ):
        if value is not None:
            payload[key] = value
    if item.union:
        payload["union"] = True
    if item.unread:
        payload["unread"] = list(item.unread)
    return payload


class _Builder:
    """Builds the record types of one document."""

    def __init__(self, document: PliDocument, limits: LimitRecorder) -> None:
        self.document = document
        self.limits = limits
        self.types: Dict[str, Type] = {}
        #: ``id(structure item) → type key`` for every structure that owns a record type.
        self.keys: Dict[int, str] = {}
        self.layouts: Dict[int, ItemLayout] = {}
        #: ``name → type key`` of LIKE targets, majors before minors (the reader's lookup order).
        self.like_keys: Dict[str, str] = {}

    def run(self) -> List[Type]:
        for structure in self.document.structures:
            self.layouts.update(compute_layout(structure))
            self._assign_keys(structure, structure.name)
        for structure in self.document.structures:
            for item in structure.walk():
                if item.is_structure and item.like is None and item.cloned_from is None:
                    self.like_keys.setdefault(item.name, self.keys[id(item)])
        for structure in self.document.structures:
            self._record(structure, structure)
        return list(self.types.values())

    def _assign_keys(self, item: PliItem, path: str) -> None:
        """Key every structure declared in place (LIKE copies reuse their target's record)."""
        if item.like is not None or not item.children:
            return
        self.keys[id(item)] = Keys.type(path, PLI_NAMESPACE)
        for child in item.children:
            if child.children and child.like is None:
                self._assign_keys(child, f"{path}.{child.name}")

    def _like_key(self, item: PliItem) -> Optional[str]:
        """The record a LIKE item references: its target's own record type."""
        assert item.like is not None
        return self.like_keys.get(item.like.split(".")[-1])

    def _record(self, item: PliItem, major: PliItem) -> None:
        key = self.keys[id(item)]
        layout = self.layouts[id(item)]
        base = layout.offset or 1
        fields: List[CanonicalField] = []
        number = 0
        filler = 0
        gaps: List[str] = []
        for child in item.children:
            if child.include is not None:
                gaps.append(child.include)
                self.limits.record("pli.unresolved_include", location=f"{major.name}: {child.include}")
                continue
            number += 1
            name = child.name
            if name == "*":
                filler += 1
                name = f"FILLER_{filler}"
            location = f"{_type_name(key)}.{name}"
            child_layout = self.layouts[id(child)]
            constraints: Optional[Constraints] = None
            if child.like is not None:
                target = self._like_key(child)
                element = TypeRef(name=target or "any", nullable=False)
            elif child.children:
                self._record(child, major)
                element = TypeRef(name=self.keys[id(child)], nullable=False)
            else:
                assert child.data is not None
                scalar, constraints = _scalar(child.data, self.limits, location)
                element = TypeRef(name=scalar, nullable=False)
                if child.data.defaulted:
                    self.limits.record("pli.default_attributes", location=location)
                if child.data.refer or (child.data.length is None and child.data.length_text):
                    self.limits.record("pli.refer_extent", location=location)
            if child.unread:
                self.limits.record("pli.unread_attribute", location=location)
            if any(dimension.count is None for dimension in child.dimensions):
                self.limits.record("pli.refer_extent", location=location)
            ref, list_constraints = _wrap_dimensions(element, child)
            if list_constraints is not None:
                if constraints is not None and constraints.max_length is not None:
                    list_constraints = list_constraints.model_copy(
                        update={"extras": {"item_max_length": constraints.max_length}}
                    )
                constraints = list_constraints
            elif child.dimensions:
                constraints = None
            payload = {**_item_payload(child), **_storage_payload(child_layout, base)}
            if child.name == "*":
                payload["filler"] = True
            fields.append(
                CanonicalField(
                    key=Keys.field(key, name),
                    name=name,
                    type=ref,
                    field_number=number,
                    constraints=constraints,
                    description=_field_description(child, child_layout, base),
                    extras={PLI_EXTRAS_KEY: payload},
                )
            )
        if item.union:
            self.limits.record("pli.union_storage", location=_type_name(key))
        metadata: Dict[str, Any] = {**_item_payload(item), **_storage_payload(layout, layout.offset or 1)}
        metadata["file"] = item.file
        metadata["line"] = item.line
        if gaps:
            metadata["partial"] = {
                "reason": (
                    f"%INCLUDE {', '.join(gaps)} sits inside this structure and was not supplied; the members "
                    "it declares are missing and the structure has no length from that point on."
                ),
                "missingIncludes": gaps,
            }
        if item is major:
            metadata["storageMap"] = _storage_map(major, self.layouts)
        self.types[key] = Type(
            key=key,
            name=_type_name(key),
            kind=TypeKind.RECORD,
            namespace=PLI_NAMESPACE,
            description=_record_description(item, layout, bool(gaps)),
            fields=fields,
            extras={PLI_EXTRAS_KEY: metadata},
        )


def _type_name(key: str) -> str:
    """The record's name from its key (``…pli.ORDER_REC.LINES`` → ``ORDER_REC.LINES``)."""
    prefix = f"{PLI_NAMESPACE}."
    tail = key.split(":")[-1]
    return tail[len(prefix) :] if tail.startswith(prefix) else tail


def _field_description(item: PliItem, layout: ItemLayout, base: int) -> str:
    """``CHAR(10) at offset 1, 10 bytes`` — the declaration and where it sits."""
    if item.like is not None:
        what = f"LIKE {item.like}"
    elif item.children:
        what = "UNION" if item.union else "structure"
    else:
        assert item.data is not None
        what = declared_attributes(item.data)
    if item.dimensions:
        what += f", dimension ({', '.join(d.text for d in item.dimensions)})"
    if layout.offset is not None:
        where = f" at offset {layout.offset - base + 1}" + (f" bit {layout.bit_offset}" if layout.bit_offset else "")
    else:
        where = " at a runtime offset" if layout.offset_variable else " at an unknown offset"
    if layout.total_length is not None:
        size = f", {layout.total_length} byte{'s' if layout.total_length != 1 else ''}"
    else:
        size = ", length not fixed"
    shared = f"; shares storage with {layout.redefines}" if layout.redefines else ""
    return f"{what}{where}{size}{shared}."


def _record_description(item: PliItem, layout: ItemLayout, partial: bool) -> str:
    kind = "UNION" if item.union else ("structure" if item.level == 1 else "minor structure")
    if partial:
        size = "partial — an %INCLUDE inside it was not supplied"
    elif layout.total_length is not None:
        size = f"{layout.total_length} bytes"
    else:
        size = "length not fixed"
    return f"PL/I {kind} {item.name} (level {item.level}), {size}."


def _storage_map(major: PliItem, layouts: Dict[int, ItemLayout]) -> List[Dict[str, Any]]:
    """Every item of a major structure with its absolute storage, LIKE copies expanded."""
    rows: List[Dict[str, Any]] = []

    def visit(item: PliItem, path: str) -> None:
        layout = layouts[id(item)]
        row: Dict[str, Any] = {"path": path, "level": item.level}
        if item.include is not None:
            row["include"] = item.include
        elif item.data is not None:
            row["attributes"] = declared_attributes(item.data)
        elif item.union:
            row["attributes"] = "UNION"
        row.update(_storage_payload(layout, 1))
        rows.append(row)
        for child in item.children:
            label = child.name if child.include is None else f"%INCLUDE {child.include}"
            visit(child, f"{path}.{label}")

    visit(major, major.name)
    return rows


class PliNormalizer(Normalizer, register=True):
    """Normalize a parsed PL/I document (:class:`~app.pli_parser.PliDocument`)."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.pli_parser.PliDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            One ``RECORD`` per structure (major and minor; LIKE copies reference their target's).

        Raises:
            ValueError: When ``source`` is not a :class:`PliDocument`.
        """
        if not isinstance(source, PliDocument):
            raise ValueError("PL/I source must be a PliDocument (see app.pli_parser)")
        limits = LimitRecorder(details=PLI_LIMIT_DETAILS)
        builder = _Builder(source, limits)
        types = builder.run()
        for include in source.unresolved_includes:
            if include.inside is None:
                limits.record("pli.unresolved_include", location=include.member)
        for scalar in source.scalars:
            limits.record("pli.scalar_declaration", location=scalar.name)
        for statement in source.statements:
            limits.record(
                "pli.non_declare_statement", location=f"{statement.keyword} ({statement.file}:{statement.line})"
            )
        for member in source.unreferenced:
            limits.record("pli.unreferenced_member", location=member)
        primary = source.structures[0]
        record: Dict[str, Any] = {
            "input": "fileset" if source.is_fileset else "file",
            "files": sorted(source.sources),
            "structures": [_structure_summary(s, builder) for s in source.structures],
            "scalars": [
                {"name": s.name, **({"attributes": declared_attributes(s.data)} if s.data is not None else {})}
                for s in source.scalars
            ],
            "includes": [
                {
                    "member": i.member,
                    "file": i.file,
                    "line": i.line,
                    "resolved": i.resolved,
                    **({"inside": i.inside} if i.inside else {}),
                }
                for i in source.includes
            ],
            "statements": [{"keyword": s.keyword, "file": s.file, "line": s.line} for s in source.statements],
            "unreferenced": list(source.unreferenced),
            "layoutAssumptions": list(LAYOUT_ASSUMPTIONS),
            "capability_limits": _limits_payload(limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=primary.name, namespace=PLI_NAMESPACE),
            title=primary.name,
            description=(
                f"PL/I declarations: {len(source.structures)} structure(s). Byte offsets and lengths are "
                "computed under the assumptions in extras['pli']['layoutAssumptions']."
            ),
            types=types,
            raw={"files": [{"path": p, "text": t} for p, t in sorted(source.sources.items())]} if include_raw else None,
            extras={PLI_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)


def _structure_summary(structure: PliItem, builder: _Builder) -> Dict[str, Any]:
    layout = builder.layouts[id(structure)]
    gaps = [item.include for item in structure.walk() if item.include is not None]
    return {
        "name": structure.name,
        "type": builder.keys[id(structure)],
        **({"length": layout.total_length} if layout.total_length is not None else {}),
        **({"variableLength": True} if layout.variable else {}),
        **({"partial": True, "missingIncludes": gaps} if gaps else {}),
    }
