"""UBL and Peppol BIS profiles for the XSD export — MFX-24.6 (#4346).

MFI-20.5 imports UBL / Peppol document schemas (:mod:`app.ubl_schema`); this is the export half of the mirror.
With ``profile="ubl"`` the XSD emitter (:mod:`app.xsd_emitter`) writes the item's types as a **UBL 2.1 document
schema**, on the shared XSD mapping (:mod:`app.xsd_schema`, MFX-22.1), and with ``profile="peppol"`` the same
document with the **Peppol BIS Billing 3.0** conventions applied:

* **UBL data types.** Every value is typed by one of UBL's unqualified data types (``udt:TextType``,
  ``udt:CodeType``, ``udt:IdentifierType``, ``udt:AmountType``, ``udt:DateType`` …, :func:`ubl_data_type`). A
  value whose name and data type match a UBL basic component is a reference to it (``cbc:IssueDate``,
  ``cbc:Note``), so the schema reuses the UBL library rather than redefining it.
* **UBL names.** Names are UpperCamelCase and an element ends with its representation term (``Code``,
  ``Indicator``, ``Date``, ``Amount``, ``ID`` …): ``status`` (an enum) is ``StatusCode``. A record is an aggregate,
  ``<Name>Type``, and a field holding one is an element of that type.
* **The document.** One global element, the document (``ubl_document``: ``Invoice``, ``Order`` …), whose type is the
  document record (``document_record``, else the one record no other record uses) headed by ``cbc:UBLVersionID``,
  ``cbc:CustomizationID`` and ``cbc:ProfileID``. The schema is in the document's own customization namespace
  (``ubl_namespace``, else ``urn:apiome:names:specification:ubl:schema:xsd:<Document>-2``) — the OASIS namespaces
  belong to the OASIS documents — and imports the UBL component schemas.
* **The UBL schemas ship with it.** The export holds ``<Document>.xsd``, the OASIS UBL 2.1 component schemas it
  imports (``common/…``, unmodified, from :data:`BUNDLE_DIR`), their ``NOTICE.md`` and a Markdown guide
  (``<Document>.ubl-guide.md``), so it builds and validates with no other file. The export gate builds it with an
  XML Schema processor against those schemas and checks they are the OASIS files, byte for byte.

**Peppol BIS Billing 3.0** (``profile="peppol"``): the document is an ``Invoice`` or a ``CreditNote``; its
``cbc:CustomizationID`` and ``cbc:ProfileID`` are mandatory, documented with the BIS values
(:data:`PEPPOL_CUSTOMIZATION_ID`, :data:`PEPPOL_PROFILE_ID`); ``cbc:ID``, ``cbc:IssueDate``, the type code
(``cbc:InvoiceTypeCode`` / ``cbc:CreditNoteTypeCode``) and ``cbc:DocumentCurrencyCode`` are mandatory — the item's
own when it has them, else added and reported ``SYNTH``. :func:`peppol_problems` checks those conventions. Peppol's
Schematron business rules are **not** run (no XSLT 2.0 processor is bundled); the guide says so.

Every convention the item cannot meet is recorded on the writer's :class:`~app.emitter.LossTracker` and graded by
the XSD fidelity pack (:data:`SYNTHESIZED_SUBJECTS` → ``SYNTH``, the rest ``APPROX``).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Set, Tuple

from .canonical_model import CanonicalApi, CanonicalField, Constraints, Type, TypeKind, TypeRef
from .emitter import LossKind, LossTracker, Provenance
from .iso20022_xsd_profile import iso20022_name, unused_records
from .xsd_schema import XSD_NS, NameScope, XsdSchemaWriter, annotate

__all__ = [
    "BUNDLE_DIR",
    "PEPPOL_CUSTOMIZATION_ID",
    "PEPPOL_DOCUMENTS",
    "PEPPOL_PROFILE_ID",
    "PROFILE_APPINFO_SOURCE",
    "SYNTHESIZED_SUBJECTS",
    "UBL_NOTICE_PATH",
    "UblDocument",
    "UblSchemaWriter",
    "bundled_files",
    "cbc_components",
    "peppol_problems",
    "resolve_document",
    "ubl_data_type",
    "ubl_guide",
]

#: The OASIS UBL 2.1 schemas, vendored unmodified (see ``NOTICE.md`` there).
BUNDLE_DIR = Path(__file__).resolve().parent / "data" / "ubl_2_1_xsd"
#: Where the export puts the OASIS notice the bundled schemas must travel with.
UBL_NOTICE_PATH = "NOTICE.md"
_CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
_UDT_NS = "urn:oasis:names:specification:ubl:schema:xsd:UnqualifiedDataTypes-2"
_CBC_FILE = "UBL-CommonBasicComponents-2.1.xsd"
_UDT_FILE = "UBL-UnqualifiedDataTypes-2.1.xsd"
#: The ``xsd:appinfo`` source that names the profile a schema was written with (the gate reads it).
PROFILE_APPINFO_SOURCE = "urn:apiome:xsd-profile"

#: Peppol BIS Billing 3.0 — the documents it defines, and its customization and profile identifiers.
PEPPOL_DOCUMENTS = frozenset({"Invoice", "CreditNote"})
PEPPOL_CUSTOMIZATION_ID = "urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0"
PEPPOL_PROFILE_ID = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"

#: Loss subjects the fidelity pack reports as ``SYNTH``.
SYNTHESIZED_SUBJECTS: FrozenSet[str] = frozenset({"ubl-document-root", "peppol-element-synthesized",
                                                 "iso20022-name-synthesized"})

#: Representation terms an element name ends with, by UBL data type (``TextType`` has none).
_TERMS = {"CodeType": "Code", "IndicatorType": "Indicator", "DateType": "Date", "TimeType": "Time",
          "DateTimeType": "DateTime", "AmountType": "Amount", "NumericType": "Numeric", "QuantityType": "Quantity",
          "IdentifierType": "ID", "NameType": "Name", "BinaryObjectType": "BinaryObject"}
_INTEGERS = frozenset({"int8", "i8", "sbyte", "uint8", "u8", "byte", "int16", "i16", "short", "uint16", "u16",
                       "int32", "i32", "int", "sint32", "sfixed32", "uint32", "u32", "fixed32", "int64", "i64",
                       "long", "sint64", "sfixed64", "integer", "bigint", "uint64", "u64", "fixed64"})
_DECIMALS = frozenset({"decimal", "numeric", "money", "float", "double", "f32", "f64", "float32", "float64",
                       "number"})
_MONEY_WORDS = re.compile(r"(amount|price|total|cost|tax|fee|charge|subtotal|balance)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# The bundled UBL schemas
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def cbc_components() -> Dict[str, str]:
    """Every UBL 2.1 basic component: element name → the unqualified data type it is (``IssueDate`` → ``DateType``).

    Read from the bundled ``UBL-CommonBasicComponents-2.1.xsd``: each ``<Name>`` element is of ``<Name>Type``, a
    simple-content extension of one ``udt:`` type.
    """
    text = (BUNDLE_DIR / "common" / _CBC_FILE).read_text(encoding="utf-8")
    bases = dict(re.findall(r'<xsd:complexType name="([A-Za-z0-9]+)">\s*<xsd:simpleContent>\s*'
                            r'<xsd:extension base="udt:([A-Za-z]+)"', text))
    elements = re.findall(r'<xsd:element name="([A-Za-z0-9]+)"\s+type="([A-Za-z0-9]+)"', text)
    return {name: bases[type_] for name, type_ in elements if type_ in bases}


@lru_cache(maxsize=1)
def bundled_files() -> Dict[str, str]:
    """The component schemas an export ships: published path (``common/<file>``) → text, the import closure of the
    basic components and the unqualified data types."""
    common = BUNDLE_DIR / "common"
    wanted, seen = [_CBC_FILE, _UDT_FILE], set()
    while wanted:
        name = wanted.pop()
        if name in seen:
            continue
        seen.add(name)
        text = (common / name).read_text(encoding="utf-8")
        wanted += [loc for loc in re.findall(r'schemaLocation="([^"]+)"', text) if "/" not in loc]
    return {f"common/{name}": (common / name).read_text(encoding="utf-8") for name in sorted(seen)}


def notice_text() -> str:
    """The OASIS notice the bundled schemas must be distributed with."""
    return (BUNDLE_DIR / "NOTICE.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


@dataclass
class UblDocument:
    """The UBL document an export describes.

    Attributes:
        name: The document element (``Invoice``).
        namespace: The schema's target namespace.
        record: The key of the record the document is made from, or ``None`` when the model has no record.
        peppol: Whether the Peppol BIS Billing 3.0 conventions apply.
        candidates: The records that could be the document (none uses another), when there are several.
    """

    name: str
    namespace: str
    record: Optional[str]
    peppol: bool
    candidates: List[str]

    @property
    def schema_path(self) -> str:
        return f"{self.name}.xsd"

    @property
    def guide_path(self) -> str:
        return f"{self.name}.ubl-guide.md"


def resolve_document(api: CanonicalApi, *, peppol: bool, document: Optional[str], namespace: Optional[str],
                     record: Optional[str]) -> UblDocument:
    """Decide the document: its element, namespace and the record it is made from.

    Args:
        api: The model being exported.
        peppol: Whether the Peppol profile is selected.
        document: The ``ubl_document`` option (validated), or ``None``.
        namespace: The ``ubl_namespace`` option, or ``None``.
        record: The ``document_record`` option (a record name or key), or ``None``.

    Returns:
        The document. Without ``ubl_document``: an imported UBL item's own type, else ``Invoice`` for Peppol, else the
        item's name in UpperCamelCase.

    Raises:
        ValueError: When ``document_record`` names no record of the model.
    """
    recorded = api.extras.get("ubl_document")
    # An imported UBL document schema (MFI-20.5, app.ubl_schema) records its document type.
    imported = (recorded.get("document_type") if isinstance(recorded, dict) and recorded.get("kind") == "document"
                else None)
    if document is None:
        if isinstance(imported, str) and imported and (not peppol or imported in PEPPOL_DOCUMENTS):
            document = imported
        elif peppol:
            document = "Invoice"
        else:
            document = iso20022_name(api.identity.name or api.title or "Document", "Document")[0]
    records = [t for t in api.types if t.kind is TypeKind.RECORD]
    if record:
        chosen = next((t for t in records if record in (t.key, t.name)), None)
        if chosen is None:
            raise ValueError(f"document_record {record!r} names no record type of this item")
        candidates: List[Type] = []
    else:
        candidates = unused_records(api, records)
        chosen = (candidates or records or [None])[0]
    return UblDocument(
        name=document,
        namespace=namespace or f"urn:apiome:names:specification:ubl:schema:xsd:{document}-2",
        record=chosen.key if chosen is not None else None,
        peppol=peppol,
        candidates=[t.key for t in candidates] if len(candidates) > 1 else [],
    )


def ubl_data_type(ref_name: str, name: str, constraints: Optional[Constraints], *, enum: bool) -> str:
    """The UBL unqualified data type of a value.

    Args:
        ref_name: The canonical scalar (``string``, ``int32``, ``decimal`` …).
        name: The field's name (a decimal named like money is an amount; text named ``…id`` an identifier).
        constraints: Its constraints (its ``format``).
        enum: Whether the value is an enumeration (a code).

    Returns:
        ``TextType``, ``CodeType``, ``IdentifierType``, ``NameType``, ``AmountType``, ``NumericType``,
        ``IndicatorType``, ``DateType``, ``TimeType``, ``DateTimeType`` or ``BinaryObjectType``.
    """
    if enum:
        return "CodeType"
    key = (ref_name or "string").lower()
    fmt = ((constraints.format if constraints else None) or "").lower()
    lowered = (name or "").lower()
    if key in ("bool", "boolean"):
        return "IndicatorType"
    if key in _INTEGERS:
        return "NumericType"
    if key in _DECIMALS:
        return "AmountType" if _MONEY_WORDS.search(name or "") else "NumericType"
    if key == "date" or fmt == "date":
        return "DateType"
    if key == "time" or fmt == "time":
        return "TimeType"
    if key in ("datetime", "date-time", "timestamp", "instant") or fmt == "date-time":
        return "DateTimeType"
    if key in ("bytes", "binary", "blob") or fmt in ("byte", "binary"):
        return "BinaryObjectType"
    if key in ("uuid", "guid") or fmt == "uuid" or lowered == "id" or lowered.endswith(("id", "_id", "number")):
        return "IdentifierType"
    if lowered.endswith("name"):
        return "NameType"
    return "TextType"


def ubl_element_name(raw: str, data_type: Optional[str]) -> Tuple[str, str]:
    """A UBL element name: UpperCamelCase, ending with the representation term of its data type.

    Returns:
        ``(name, how)`` — ``how`` as :func:`app.iso20022_xsd_profile.iso20022_name` reports it, ``"recased"`` when only
        the term was added.
    """
    name, how = iso20022_name(raw, "Value")
    term = _TERMS.get(data_type or "")
    if term and not name.endswith(term):
        name = name[: -len("Id")] + "ID" if term == "ID" and name.endswith("Id") else name + term
        how = "recased" if how == "kept" else how
    return name, how


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------


class UblSchemaWriter(XsdSchemaWriter):
    """The shared XSD writer with UBL's conventions: ``udt:`` values, ``cbc:`` references, UBL names.

    Only records and unions are written as named types (``<Name>Type``); enums, scalars and aliases of scalars are
    values, typed by UBL data types where they are used.
    """

    def __init__(self, api: CanonicalApi, **kwargs: Any) -> None:
        #: Whether the model came from UBL, whose element names are kept.
        self._how: Dict[str, str] = {}
        #: The ``cbc:`` components the schema references (for the guide).
        self.cbc_used: Set[str] = set()
        #: Element path → (UBL data type or ``cbc:<Name>``, cardinality, source key), for the guide.
        self.values: List[Tuple[str, str, str, str]] = []
        super().__init__(api, **kwargs)
        # An aggregate is named <Name>Type (UBL's naming rule for ABIEs).
        for key, name in list(self.type_names.items()):
            if not name.endswith("Type"):
                self.type_names[key] = f"{name}Type"

    def append_value(self, parent: ET.Element, name: str, ref: TypeRef, **kwargs: Any) -> ET.Element:
        """The shared writer's element, without ``nillable``: UBL has no ``xsi:nil``, an absent value is left out."""
        element = super().append_value(parent, name, ref, **kwargs)
        element.attrib.pop("nillable", None)
        return element

    def _record_json_mapping_notes(self, field: CanonicalField, *, optional: bool, examples: List[Any]) -> None:
        """Examples are kept as documentation (as in any XSD export); null needs no note — it is an absent element."""
        super()._record_json_mapping_notes(field, optional=False, examples=examples)

    # --- names ------------------------------------------------------------------

    def legal_name(self, raw: str, *, pascal: bool = False, fallback: str = "item") -> str:
        name, how = iso20022_name(raw, fallback[:1].upper() + fallback[1:])
        self._how[raw] = how
        return name

    def structural_name(self, name: str) -> str:
        return name[:1].upper() + name[1:]

    def rename(self, source: Optional[str], emitted: str, pointer: str, noun: str) -> str:
        if source == emitted:
            return emitted
        how = self._how.get(source or "", "recased")
        subject = {"lossy": "iso20022-name-unmappable", "synthesized": "iso20022-name-synthesized"}.get(
            how, "renamed-identifier")
        self.losses.record(
            LossKind.INFERRED, subject,
            f"UBL {noun} names are UpperCamelCase and end with their representation term; {source!r} is written as "
            f"{emitted!r}.",
            pointer=pointer,
        )
        return emitted

    # --- types ------------------------------------------------------------------

    def is_value_type(self, type_: Type) -> bool:
        """Whether a named type is written as a UBL value rather than an aggregate (enums, scalars, aliases)."""
        if type_.kind in (TypeKind.ENUM, TypeKind.SCALAR):
            return True
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None and type_.aliased.item is None:
            target = self.types_by_key.get(type_.aliased.name or "")
            return target is None or self.is_value_type(target)
        return False

    def append_type(self, schema_el: ET.Element, type_: Type) -> bool:
        """Records, unions and maps as aggregates; values are not written as types of their own."""
        if self.is_value_type(type_):
            self.tracker.record(type_.key, Provenance.SOURCE)
            return False
        return super().append_type(schema_el, type_)

    def _value_of(self, ref: TypeRef, constraints: Optional[Constraints]) -> Tuple[Optional[str], Optional[Type],
                                                                                   Optional[Constraints]]:
        """The scalar a value reference ends at (following aliases), its enum type, and its constraints."""
        target = self.types_by_key.get(ref.name or "")
        seen: Set[str] = set()
        while target is not None and target.kind is TypeKind.ALIAS and target.aliased is not None:
            if target.key in seen or target.aliased.item is not None:
                break
            seen.add(target.key)
            constraints = constraints or target.constraints
            ref = target.aliased
            target = self.types_by_key.get(ref.name or "")
        if target is not None and target.kind is TypeKind.ENUM:
            return None, target, constraints
        if target is not None and target.kind is TypeKind.SCALAR:
            return target.name, None, constraints or target.constraints
        if target is None:
            return ref.name or "string", None, constraints
        return None, None, constraints

    def append_field(self, parent: ET.Element, field: CanonicalField, scope: NameScope, *,
                     in_choice: bool = False) -> None:
        """A field: an aggregate element, or a UBL value (``udt:`` typed, or a ``cbc:`` reference)."""
        item = field.type.item if field.type.is_list() else None
        ref = item or field.type
        scalar, enum, constraints = self._value_of(ref, field.constraints)
        if scalar is None and enum is None:
            super().append_field(parent, field, scope, in_choice=in_choice)
            return
        data_type = ubl_data_type(scalar or "", field.name or "", constraints, enum=enum is not None)
        base, how = ubl_element_name(field.name or field.key, data_type)
        self._how[field.name or ""] = how
        name = scope.claim(base)
        self.rename(field.name, name, field.key, "element")
        self.tracker.record(field.key, Provenance.SOURCE)
        attributes: Dict[str, str] = {}
        if field.type.is_list():
            attributes.update(minOccurs="0", maxOccurs="unbounded")
        elif field.type.nullable and not in_choice:
            attributes["minOccurs"] = "0"
        if cbc_components().get(name) == data_type:
            self.cbc_used.add(name)
            element = ET.SubElement(parent, ET.QName(XSD_NS, "element"), {"ref": f"cbc:{name}", **attributes})
            written = f"cbc:{name}"
        else:
            element = ET.SubElement(parent, ET.QName(XSD_NS, "element"),
                                    {"name": name, "type": f"udt:{data_type}", **attributes})
            written = f"udt:{data_type}"
        notes = _value_notes(constraints, enum)
        if field.description or notes:
            annotate(element, "\n".join([field.description or "", *notes]).strip())
        if notes:
            subject = "codes-as-documentation" if enum is not None else "facets-as-documentation"
            self.losses.record(
                LossKind.INFERRED, subject,
                f"UBL data types carry no facets or code lists; the rules of {field.key!r} are written as "
                f"documentation: {'; '.join(notes)}.",
                pointer=field.key,
            )
        self.node_keys[id(element)] = field.key
        self.values.append((name, written, _cardinality(attributes), field.key))


def _cardinality(attributes: Mapping[str, str]) -> str:
    low = attributes.get("minOccurs", "1")
    high = attributes.get("maxOccurs", "1")
    return f"{low}..{'n' if high == 'unbounded' else high}"


def _value_notes(constraints: Optional[Constraints], enum: Optional[Type]) -> List[str]:
    """The rules a UBL data type cannot carry, as documentation lines."""
    notes: List[str] = []
    if enum is not None:
        notes.append("codes: " + ", ".join(str(v.value if v.value is not None else v.name) for v in enum.enum_values))
    c = constraints
    if c is not None:
        for label, value in (("minimum length", c.min_length), ("maximum length", c.max_length),
                             ("pattern", c.pattern), ("minimum", c.minimum), ("maximum", c.maximum)):
            if value is not None:
                notes.append(f"{label}: {value}")
    return notes


# ---------------------------------------------------------------------------
# The document element and the Peppol conventions
# ---------------------------------------------------------------------------

#: The UBL header every document starts with: (cbc component, Peppol cardinality, BIS value or ``None``).
_HEADER = (("UBLVersionID", "0", None), ("CustomizationID", "1", PEPPOL_CUSTOMIZATION_ID),
           ("ProfileID", "1", PEPPOL_PROFILE_ID))


def _peppol_mandatory(document: str) -> Tuple[str, ...]:
    """The basic components a Peppol BIS Billing 3.0 document must carry after its header."""
    return ("ID", "IssueDate", f"{document}TypeCode", "DocumentCurrencyCode")


def append_document(schema_el: ET.Element, writer: UblSchemaWriter, document: UblDocument,
                    losses: LossTracker) -> None:
    """Write the document element and its type: the UBL header, (for Peppol) its mandatory components, the record.

    The document record's own aggregate is renamed ``<Document>Type`` and becomes the document's type; another
    record's aggregate is left as it is.
    """
    record_type_name = writer.type_names.get(document.record) if document.record else None
    complex_el = next((el for el in schema_el.findall(f"{{{XSD_NS}}}complexType")
                       if el.get("name") == record_type_name), None) if record_type_name else None
    doc_type = f"{document.name}Type"
    if complex_el is None:
        complex_el = ET.Element(ET.QName(XSD_NS, "complexType"), {"name": doc_type})
        ET.SubElement(complex_el, ET.QName(XSD_NS, "sequence"))
        schema_el.append(complex_el)
    elif record_type_name != doc_type:
        referenced = any(el.get("type") == writer.qualified(record_type_name, document.namespace)
                         for el in schema_el.iter(f"{{{XSD_NS}}}element"))
        if referenced:
            copy = ET.fromstring(ET.tostring(complex_el))
            copy.set("name", doc_type)
            schema_el.append(copy)
            complex_el = copy
        else:
            complex_el.set("name", doc_type)
    sequence = complex_el.find(f"{{{XSD_NS}}}sequence")
    if sequence is None:
        sequence = ET.SubElement(complex_el, ET.QName(XSD_NS, "sequence"))
    header: List[ET.Element] = []
    for name, peppol_min, value in _HEADER:
        element = ET.Element(ET.QName(XSD_NS, "element"),
                             {"ref": f"cbc:{name}", "minOccurs": peppol_min if document.peppol else "0"})
        if document.peppol and value:
            annotate(element, f"Peppol BIS Billing 3.0: {value}")
        header.append(element)
        writer.cbc_used.add(name)
    if document.peppol:
        present = {el.get("ref") for el in sequence.findall(f"{{{XSD_NS}}}element")}
        for name in _peppol_mandatory(document.name):
            ref = f"cbc:{name}"
            existing = next((el for el in sequence.findall(f"{{{XSD_NS}}}element") if el.get("ref") == ref), None)
            if existing is not None:
                # The item's own value, made mandatory and moved into the header (the guide says so too).
                sequence.remove(existing)
                existing.attrib.pop("minOccurs", None)
                header.append(existing)
                writer.values = [(n, w, "1..1" if w == ref else c, src) for n, w, c, src in writer.values]
                continue
            if ref not in present:
                header.append(ET.Element(ET.QName(XSD_NS, "element"), {"ref": ref}))
                writer.cbc_used.add(name)
                losses.record(
                    LossKind.INFERRED, "peppol-element-synthesized",
                    f"Peppol BIS Billing 3.0 requires {ref} in every {document.name}; the item has no value for it, "
                    "so the export adds it.",
                    pointer="",
                )
    for index, element in enumerate(header):
        sequence.insert(index, element)
    root = ET.Element(ET.QName(XSD_NS, "element"), {"name": document.name,
                                                    "type": writer.qualified(doc_type, document.namespace)})
    annotate(root, f"UBL 2.1 {document.name} document" + (" (Peppol BIS Billing 3.0)" if document.peppol else ""))
    schema_el.insert(0, root)


def record_document_losses(api: CanonicalApi, document: UblDocument, losses: LossTracker) -> None:
    """What the export had to choose or invent about the document (filed at the root)."""
    if document.record is None:
        losses.record(LossKind.NA, "ubl-no-record", "The item has no record type to make the document from, so "
                      f"{document.name} holds only its UBL header.", pointer="")
    record_name = next((t.name for t in api.types if t.key == document.record), document.record)
    losses.record(
        LossKind.INFERRED, "ubl-document-root",
        f"A UBL document is one element headed by cbc:UBLVersionID, cbc:CustomizationID and cbc:ProfileID; the export "
        f"adds {document.name}, made from {record_name!r}.",
        pointer="",
    )
    if document.candidates:
        names = ", ".join(next((t.name for t in api.types if t.key == key), key) for key in document.candidates)
        losses.record(LossKind.INFERRED, "ubl-document-record-inferred",
                      f"Several record types could be the document ({names}); the export uses the first. Set "
                      "document_record to choose another.", pointer="")
    other = sorted({t.namespace for t in api.types if t.namespace and ":" in t.namespace
                    and t.namespace != document.namespace})
    for namespace in other:
        losses.record(LossKind.INFERRED, "ubl-namespace-merged",
                      f"A UBL document schema is one namespace; the types of {namespace} are written in "
                      f"{document.namespace}.", pointer="")


def profile_appinfo(schema_el: ET.Element, profile: str) -> None:
    """Name the profile in the schema (``xsd:appinfo``), so a check of the file alone knows what to apply."""
    annotation = ET.Element(ET.QName(XSD_NS, "annotation"))
    ET.SubElement(annotation, ET.QName(XSD_NS, "appinfo"), {"source": PROFILE_APPINFO_SOURCE}).text = profile
    schema_el.insert(0, annotation)


def peppol_problems(schema_text: str) -> List[str]:
    """Where a document schema breaks the Peppol BIS Billing 3.0 conventions the export applies.

    Checks the one global element is ``Invoice`` or ``CreditNote``; its type starts with ``cbc:CustomizationID`` and
    ``cbc:ProfileID``, mandatory and documented with the BIS values; and it carries ``cbc:ID``, ``cbc:IssueDate``, the
    type code and ``cbc:DocumentCurrencyCode``, each mandatory. It does not run Peppol's Schematron rules.

    Args:
        schema_text: The main ``.xsd`` of an export.

    Returns:
        One message per problem (empty when the conventions hold).
    """
    root = ET.fromstring(schema_text)
    q = f"{{{XSD_NS}}}"
    documents = [el for el in root.findall(f"{q}element")]
    if len(documents) != 1 or documents[0].get("name") not in PEPPOL_DOCUMENTS:
        return [f"a Peppol BIS document schema has one global element, Invoice or CreditNote; found "
                f"{[el.get('name') for el in documents]}"]
    document = documents[0].get("name")
    type_name = (documents[0].get("type") or "").split(":")[-1]
    complex_el = next((el for el in root.findall(f"{q}complexType") if el.get("name") == type_name), None)
    sequence = complex_el.find(f"{q}sequence") if complex_el is not None else None
    if sequence is None:
        return [f"{document}'s type {type_name!r} has no sequence"]
    refs = [(el.get("ref"), el.get("minOccurs", "1"), el) for el in sequence.findall(f"{q}element")]
    problems: List[str] = []
    for index, (name, value) in enumerate((("cbc:CustomizationID", PEPPOL_CUSTOMIZATION_ID),
                                           ("cbc:ProfileID", PEPPOL_PROFILE_ID)), start=1):
        found = next(((r, m, el) for r, m, el in refs if r == name), None)
        if found is None:
            problems.append(f"{document} must carry {name}")
            continue
        if found[1] == "0":
            problems.append(f"{name} is mandatory in Peppol BIS Billing 3.0")
        docs = " ".join(d.text or "" for d in found[2].iter(f"{q}documentation"))
        if value not in docs:
            problems.append(f"{name} must be documented with the BIS value {value}")
    for name in _peppol_mandatory(document):
        found = next(((r, m) for r, m, _el in refs if r == f"cbc:{name}"), None)
        if found is None:
            problems.append(f"{document} must carry cbc:{name}")
        elif found[1] == "0":
            problems.append(f"cbc:{name} is mandatory in Peppol BIS Billing 3.0")
    return problems


def ubl_guide(api: CanonicalApi, writer: UblSchemaWriter, document: UblDocument) -> str:
    """The Markdown guide: the document, its header, every value with its UBL data type, and what is not checked."""
    title = api.title or api.identity.name or document.name
    lines = [
        f"# UBL 2.1 {document.name} — {title}" + (" (Peppol BIS Billing 3.0)" if document.peppol else ""),
        "",
        f"Document element `{document.name}` in namespace `{document.namespace}`, schema `{document.schema_path}`. "
        "It imports the OASIS UBL 2.1 component schemas shipped beside it in `common/` (see `NOTICE.md`).",
        "",
        "## Header",
        "",
        "| Component | Cardinality | Value |",
        "| --- | --- | --- |",
    ]
    for name, peppol_min, value in _HEADER:
        cardinality = f"{peppol_min if document.peppol else '0'}..1"
        lines.append(f"| `cbc:{name}` | {cardinality} | {f'`{value}`' if document.peppol and value else '—'} |")
    if document.peppol:
        for name in _peppol_mandatory(document.name):
            lines.append(f"| `cbc:{name}` | 1..1 | — |")
    lines += ["", "## Values", "", "| Element | UBL type | Cardinality | Source |", "| --- | --- | --- | --- |"]
    for name, written, cardinality, source in writer.values:
        lines.append(f"| `{name}` | `{written}` | {cardinality} | `{source}` |")
    if document.peppol:
        lines += ["", "## Not checked", "",
                  "Peppol BIS Billing 3.0 also defines Schematron business rules (EN 16931 and Peppol rules). This "
                  "export applies the document, header and mandatory-component conventions only; validate instances "
                  "with the Peppol validation artifacts as well."]
    return "\n".join(lines).rstrip() + "\n"
