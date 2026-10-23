"""Natural / ADABAS DDM → canonical model normalizer — FMT-11.4 (#5486).

Maps a parsed :class:`~app.natural_ddm_parser.DdmDocument` onto the **data_schema** paradigm:

.. code-block:: text

    DDM Name ...... CUSTOMER-FILE         → RECORD natural.CUSTOMER-FILE
      1 AA CUSTOMER-NUMBER  A 10  U       →   field CUSTOMER-NUMBER: string ≤ 10, unique descriptor
      1 AE BALANCE          P 11.2        →   field BALANCE: decimal, 13 digits, 7 bytes
    M 1 AH PHONE-NUMBER     A 20          →   field PHONE-NUMBER: list of string ≤ 20
    P 1 AI CONTACT                        →   field CONTACT: list of natural.CUSTOMER-FILE.CONTACT
      2 AJ CONTACT-TYPE     A 2           →     RECORD …CONTACT, field CONTACT-TYPE
    G 1 AK BILLING                        →   field BILLING: natural.CUSTOMER-FILE.BILLING
    R 2 AB PARTY-NAME       A 40          →   field PARTY-NAME, redefining bytes 1–40 of AB
    S 1 S1 SUPER-NAME …     AB(1-40),…    →   extras['natural_ddm']['descriptors'] — a declared key

Formats: ``A`` / ``W`` / ``U`` → ``string``; ``N`` / ``P`` → ``decimal`` with decimal places,
``integer`` without; ``I`` → ``integer``; ``B`` → ``bytes`` of exactly its length; ``F`` / ``G`` →
``float`` (4 bytes) or ``double``; ``L`` → ``boolean``; ``D`` → ``date``; ``T`` → ``datetime``.
Every field carries its short name, level, format, length, digits and **byte length** — computed
under :data:`LENGTH_ASSUMPTIONS`, which the document states — in ``extras['natural_ddm']``. A
multiple-value field and a periodic group are lists whose ``max_items`` is the occurrence bound
when one is stated (a Natural view in the upload, or an "Up to N occurrences" remark). Descriptors,
unique descriptors and derived keys (super-, sub-, hyper-, phonetic and collation descriptors with
their source byte ranges) are declared key metadata on the file's record. Declared limits are in
``extras['natural_ddm']['capability_limits']``.
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
from .natural_ddm_parser import FORMAT_KEY, FORMATS, DdmDescriptor, DdmDocument, DdmField, DdmFile
from .normalizer import Keys, Normalizer, normalize_ordering
from .typescript_types_normalizer import _limits_payload
from .typescript_types_parser import LimitRecorder

__all__ = [
    "LENGTH_ASSUMPTIONS",
    "NATURAL_DDM_EXTRAS_KEY",
    "NATURAL_DDM_LIMIT_DETAILS",
    "NATURAL_DDM_NAMESPACE",
    "NATURAL_DDM_PARTIAL_LIMITS",
    "NaturalDdmNormalizer",
    "byte_length",
]

#: Root extras key of the projection record (also used on types and fields).
NATURAL_DDM_EXTRAS_KEY = "natural_ddm"
#: The namespace record types are keyed under.
NATURAL_DDM_NAMESPACE = "natural"

#: What every byte length of this module assumes. The DDM states none of it.
LENGTH_ASSUMPTIONS: Tuple[str, ...] = (
    "A length is the field's standard length: characters for A, digits before the decimal point for "
    "N and P (the n of n.d; the d digits follow it), and bytes for every other format.",
    "One byte per A character in a single-byte EBCDIC code page; U is UTF-16 (two bytes per "
    "character), so its character limit is half its length.",
    "N is zoned decimal, one byte per digit; P is packed decimal, (digits ÷ 2) + 1 bytes with the "
    "sign in the last nibble.",
    "D is a Natural date and T a Natural time, stored packed (4 and 7 bytes); B, I, F and L take "
    "their stated length in bytes.",
    "A length of 0 is a variable-length (LOB) field with no standard length.",
    "ADABAS stores records compressed, so a field has a standard length but no fixed offset in the "
    "record; no offsets are computed.",
)

#: The declared-limit vocabulary (stable keys → reviewed sentence).
NATURAL_DDM_LIMIT_DETAILS: Dict[str, str] = {
    "ddm.record_offsets": (
        "ADABAS compresses each record, so fields have a standard length but no fixed position; the "
        "record keeps every field's length and no offsets."
    ),
    "ddm.unbounded_occurrences": (
        "A DDM does not state how many occurrences a multiple-value field or periodic group may have. "
        "The list has no max_items unless a Natural view in the upload, or an 'Up to N occurrences' "
        "remark, states a bound; ADABAS's own limit (191, or 65,534 with extended MU/PE limits) applies."
    ),
    "ddm.derived_descriptor": (
        "A super-, sub-, hyper-, phonetic or collation descriptor is a key derived from other fields, "
        "not stored data; it is listed with its source byte ranges in "
        "extras['natural_ddm']['descriptors'] and not modelled as a field."
    ),
    "ddm.redefinition": (
        "A redefinition reads part of a field as a field of its own. The canonical model has no "
        "overlay, so each redefinition is a field that names the field it redefines and its position "
        "within it in extras['natural_ddm']['redefines']."
    ),
    "ddm.lob_field": ("A field of length 0 is a variable-length (LOB) field: it is projected without a length limit."),
    "ddm.unresolved_view": (
        "A Natural view names a DDM that is not in the upload; its occurrence bounds cannot be applied. "
        "It is listed in extras['natural_ddm']['views']."
    ),
}
#: Limits whose construct is still modelled, with only a detail lost.
NATURAL_DDM_PARTIAL_LIMITS = frozenset(
    {"ddm.record_offsets", "ddm.unbounded_occurrences", "ddm.redefinition", "ddm.lob_field"}
)


def byte_length(item: DdmField) -> Optional[int]:
    """The field's standard length in bytes, under :data:`LENGTH_ASSUMPTIONS`.

    Args:
        item: A data field (one with a format).

    Returns:
        The byte length; ``None`` for a group or a variable-length (length 0) field.
    """
    if item.format_code is None or not item.length:
        return None
    if item.format_code in ("N", "P"):
        digits = item.length + (item.decimals or 0)
        return digits if item.format_code == "N" else digits // 2 + 1
    return item.length


def _scalar(item: DdmField) -> Tuple[str, Optional[int], Dict[str, Any]]:
    """The canonical scalar of a data field, its string / bytes length limit, and its storage facts."""
    code = item.format_code or "A"
    facts: Dict[str, Any] = {"format": code, "storage": FORMATS[code], "length": item.length}
    size = byte_length(item)
    if size is not None:
        facts["bytes"] = size
    if code in ("N", "P"):
        facts["decimals"] = item.decimals or 0
        facts["digits"] = (item.length or 0) + (item.decimals or 0)
        return ("decimal" if item.decimals else "integer"), None, facts
    if code in ("A", "W"):
        return "string", item.length or None, facts
    if code == "U":
        return "string", (item.length // 2) if item.length else None, facts
    if code == "B":
        return "bytes", item.length or None, facts
    if code in ("F", "G"):
        return ("float" if item.length == 4 else "double"), None, facts
    if code == "L":
        return "boolean", None, facts
    if code == "D":
        return "date", None, facts
    if code == "T":
        return "datetime", None, facts
    return "integer", None, facts


def _scalar_constraints(scalar: str, limit: Optional[int]) -> Optional[Constraints]:
    if limit is None:
        return None
    if scalar == "bytes":
        return Constraints(min_length=limit, max_length=limit)
    return Constraints(max_length=limit)


def _kind(item: DdmField) -> str:
    if item.periodic:
        return "periodic-group"
    if item.is_group:
        return "group"
    if item.type_code == "R":
        return "redefinition"
    return "multiple-value" if item.multiple_value else "field"


class _Builder:
    """Builds the records of one DDM, recording declared limits as it goes."""

    def __init__(self, ddm: DdmFile, limits: LimitRecorder) -> None:
        self.ddm = ddm
        self.limits = limits
        self.types: List[Type] = []

    def run(self) -> List[Type]:
        """The DDM's record, and one record per group and periodic group."""
        key = Keys.type(self.ddm.name, NATURAL_DDM_NAMESPACE)
        self.limits.record("ddm.record_offsets", location=self.ddm.name)
        for descriptor in self.ddm.descriptors:
            self.limits.record("ddm.derived_descriptor", location=f"{self.ddm.name}.{descriptor.short_name}")
        record = Type(
            key=key,
            name=self.ddm.name,
            kind=TypeKind.RECORD,
            namespace=NATURAL_DDM_NAMESPACE,
            description=self._description(),
            fields=self._fields(key, self.ddm.name, self.ddm.fields),
            extras={NATURAL_DDM_EXTRAS_KEY: self._file_metadata()},
        )
        return [record] + self.types

    def _description(self) -> str:
        descriptors = [f.name for f in self.ddm.walk() if f.descriptor]
        parts = [f"ADABAS file {self.ddm.name}"]
        if self.ddm.database or self.ddm.file_number:
            parts.append(f"(DB {self.ddm.database or '?'}, file {self.ddm.file_number or '?'})")
        text = " ".join(parts) + f": {sum(1 for _ in self.ddm.walk())} fields and groups"
        if descriptors:
            text += f", descriptors {', '.join(descriptors)}"
        return text + ". Lengths are standard lengths; ADABAS records are compressed and have no fixed offsets."

    def _fields(self, type_key: str, path: str, items: List[DdmField]) -> List[CanonicalField]:
        fields: List[CanonicalField] = []
        for item in items:
            if item.type_code == "R":
                continue
            fields.append(self._field(type_key, path, item, len(fields) + 1))
            offset = 0
            for redefinition in (c for c in item.children if c.type_code == "R"):
                fields.append(self._redefinition(type_key, item, redefinition, offset, len(fields) + 1))
                offset += redefinition.length or 0
        return fields

    def _field(self, type_key: str, path: str, item: DdmField, number: int) -> CanonicalField:
        location = f"{self.ddm.name}.{item.name}"
        metadata = self._field_metadata(item)
        if item.is_group:
            group_path = f"{path}.{item.name}"
            group_key = Keys.type(group_path, NATURAL_DDM_NAMESPACE)
            self.types.append(
                Type(
                    key=group_key,
                    name=group_path,
                    kind=TypeKind.RECORD,
                    namespace=NATURAL_DDM_NAMESPACE,
                    description=(
                        f"{'Periodic group' if item.periodic else 'Group'} {item.name} ({item.short_name}) of ADABAS "
                        f"file {self.ddm.name}, level {item.level}."
                    ),
                    fields=self._fields(group_key, group_path, item.children),
                    extras={NATURAL_DDM_EXTRAS_KEY: metadata},
                )
            )
            element = TypeRef(name=group_key, nullable=False)
            if item.periodic:
                ref, constraints = self._occurrences(item, element, None, location)
            else:
                ref, constraints = element, None
            description = f"{'Periodic group' if item.periodic else 'Group'} {item.short_name}."
        else:
            scalar, limit, facts = _scalar(item)
            metadata.update(facts)
            if item.length == 0:
                self.limits.record("ddm.lob_field", location=location)
            element = TypeRef(name=scalar, nullable=False)
            if item.multiple_value:
                ref, constraints = self._occurrences(item, element, limit, location)
            else:
                ref, constraints = element, _scalar_constraints(scalar, limit)
            description = self._field_description(item, facts)
        return CanonicalField(
            key=Keys.field(type_key, item.name),
            name=item.name,
            type=ref,
            field_number=number,
            constraints=constraints,
            description=description,
            extras={NATURAL_DDM_EXTRAS_KEY: metadata},
        )

    def _occurrences(
        self, item: DdmField, element: TypeRef, limit: Optional[int], location: str
    ) -> Tuple[TypeRef, Optional[Constraints]]:
        """A list of ``element``, bounded by the stated occurrence count when there is one."""
        if item.max_occurrences is None:
            self.limits.record("ddm.unbounded_occurrences", location=location)
        extras = {"item_max_length": limit} if limit is not None else {}
        constraints = Constraints(max_items=item.max_occurrences, extras=extras)
        if item.max_occurrences is None and not extras:
            return TypeRef(item=element, nullable=False), None
        return TypeRef(item=element, nullable=False), constraints

    def _redefinition(
        self, type_key: str, parent: DdmField, item: DdmField, offset: int, number: int
    ) -> CanonicalField:
        self.limits.record("ddm.redefinition", location=f"{self.ddm.name}.{item.name}")
        scalar, limit, facts = _scalar(item)
        metadata = self._field_metadata(item)
        metadata.update(facts)
        metadata["redefines"] = {"field": parent.name, "shortName": parent.short_name, "position": offset + 1}
        return CanonicalField(
            key=Keys.field(type_key, item.name),
            name=item.name,
            type=TypeRef(name=scalar, nullable=False),
            field_number=number,
            constraints=_scalar_constraints(scalar, limit),
            description=(
                f"Redefines positions {offset + 1}–{offset + (item.length or 0)} of {parent.name} "
                f"({parent.short_name})."
            ),
            extras={NATURAL_DDM_EXTRAS_KEY: metadata},
        )

    @staticmethod
    def _field_description(item: DdmField, facts: Dict[str, Any]) -> str:
        length = f"{item.length}.{item.decimals}" if item.decimals is not None else f"{item.length}"
        parts = [f"{item.short_name}: format {item.format_code}{length}"]
        if "bytes" in facts:
            parts.append(f"{facts['bytes']} byte{'s' if facts['bytes'] != 1 else ''}")
        else:
            parts.append("variable length")
        if item.descriptor:
            parts.append("unique descriptor" if item.descriptor == "U" else "descriptor")
        if item.multiple_value:
            parts.append("multiple-value")
        return ", ".join(parts) + "."

    @staticmethod
    def _field_metadata(item: DdmField) -> Dict[str, Any]:
        return {
            "shortName": item.short_name,
            "level": item.level,
            "kind": _kind(item),
            **({"descriptor": {"unique": item.descriptor == "U"}} if item.descriptor else {}),
            **({"nullSuppressed": True} if item.null_suppressed else {}),
            **({"fixedStorage": True} if item.fixed_storage else {}),
            **(
                {"occurrences": {"maximum": item.max_occurrences, "source": item.occurrence_source}}
                if item.max_occurrences is not None
                else {}
            ),
            **({"remark": item.remark} if item.remark else {}),
            "line": item.line,
        }

    def _file_metadata(self) -> Dict[str, Any]:
        return {
            "ddm": self.ddm.name,
            **({"database": self.ddm.database} if self.ddm.database else {}),
            **({"fileNumber": self.ddm.file_number} if self.ddm.file_number else {}),
            **(
                {
                    "defaultSequence": {
                        "shortName": self.ddm.default_sequence,
                        "field": self.ddm.by_short_name(self.ddm.default_sequence).name,  # type: ignore[union-attr]
                    }
                }
                if self.ddm.default_sequence
                else {}
            ),
            "descriptors": self.descriptors(),
            **({"file": self.ddm.path} if self.ddm.path else {}),
        }

    def descriptors(self) -> List[Dict[str, Any]]:
        """Every key the DDM declares: field descriptors, then derived descriptors with their sources."""
        keys: List[Dict[str, Any]] = [
            {
                "kind": "unique-descriptor" if item.descriptor == "U" else "descriptor",
                "shortName": item.short_name,
                "field": item.name,
                "unique": item.descriptor == "U",
            }
            for item in self.ddm.walk()
            if item.descriptor
        ]
        keys.extend(self._derived(d) for d in self.ddm.descriptors)
        return keys

    def _derived(self, descriptor: DdmDescriptor) -> Dict[str, Any]:
        sources = []
        for short_name, start, end in descriptor.sources:
            source = self.ddm.by_short_name(short_name)
            sources.append(
                {"shortName": short_name, "field": source.name if source else None, "from": start, "to": end}
            )
        return {
            "kind": descriptor.kind,
            "shortName": descriptor.short_name,
            "name": descriptor.name,
            **({"format": descriptor.format_code} if descriptor.format_code else {}),
            **({"length": descriptor.length} if descriptor.length is not None else {}),
            "unique": descriptor.unique,
            "sources": sources,
            **({"remark": descriptor.remark} if descriptor.remark and not sources else {}),
            "line": descriptor.line,
        }


class NaturalDdmNormalizer(Normalizer, register=True):
    """Normalize a parsed DDM document (:class:`~app.natural_ddm_parser.DdmDocument`)."""

    format = FORMAT_KEY
    paradigm = ApiParadigm.DATA_SCHEMA

    def normalize(self, source: Any, *, include_raw: bool = True) -> CanonicalApi:
        """Map a :class:`~app.natural_ddm_parser.DdmDocument` to the canonical model.

        Args:
            source: The parsed document.
            include_raw: Whether to keep every file's text on ``raw``.

        Returns:
            One ``RECORD`` per DDM and per group or periodic group.

        Raises:
            ValueError: When ``source`` is not a :class:`DdmDocument`.
        """
        if not isinstance(source, DdmDocument):
            raise ValueError("DDM source must be a DdmDocument (see app.natural_ddm_parser)")
        limits = LimitRecorder(details=NATURAL_DDM_LIMIT_DETAILS)
        types: List[Type] = []
        summaries: List[Dict[str, Any]] = []
        for ddm in source.ddms:
            builder = _Builder(ddm, limits)
            types.extend(builder.run())
            summaries.append(
                {
                    "name": ddm.name,
                    "type": Keys.type(ddm.name, NATURAL_DDM_NAMESPACE),
                    **({"database": ddm.database} if ddm.database else {}),
                    **({"fileNumber": ddm.file_number} if ddm.file_number else {}),
                    "fields": sum(1 for _ in ddm.walk()),
                    "descriptors": len(builder.descriptors()),
                    **({"file": ddm.path} if ddm.path else {}),
                }
            )
        for view in source.views:
            if source.ddm(view.ddm) is None:
                limits.record("ddm.unresolved_view", location=f"{view.name} → {view.ddm}")
        primary = source.ddms[0]
        record: Dict[str, Any] = {
            "input": "fileset" if source.is_fileset else "file",
            "files": sorted(source.sources),
            "ddms": summaries,
            "views": [
                {
                    "name": view.name,
                    "ddm": view.ddm,
                    "ddmResolved": source.ddm(view.ddm) is not None,
                    "fields": [
                        {
                            "name": f.name,
                            "level": f.level,
                            **({"occurrences": {"from": f.lower, "to": f.upper}} if f.upper is not None else {}),
                        }
                        for f in view.fields
                    ],
                    **({"file": view.path} if view.path else {}),
                }
                for view in source.views
            ],
            "lengthAssumptions": list(LENGTH_ASSUMPTIONS),
            "capability_limits": _limits_payload(limits.limits()),
        }
        api = CanonicalApi(
            paradigm=self.paradigm,
            format=self.format,
            identity=ApiIdentity(name=primary.name, namespace=NATURAL_DDM_NAMESPACE),
            title=primary.name,
            description=(
                f"Natural / ADABAS data definition modules: {len(source.ddms)} file(s). Byte lengths are "
                "computed under the assumptions in extras['natural_ddm']['lengthAssumptions']; descriptors are "
                "declared key metadata in each file's record."
            ),
            types=types,
            raw={"files": [{"path": p, "text": t} for p, t in sorted(source.sources.items())]} if include_raw else None,
            extras={NATURAL_DDM_EXTRAS_KEY: record},
        )
        return normalize_ordering(api)
