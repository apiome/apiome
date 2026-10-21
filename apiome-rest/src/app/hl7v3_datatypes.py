"""HL7 v3 RIM data types and C-CDA template vocabulary — FMT-6.4 (#5448).

The stated tables the HL7 v3 / CDA reader works from:

* :data:`DATATYPES` — every RIM data type (Data Types R1, the release CDA R2 is bound to) the reader
  maps onto canonical types, each with its declared shape. A ``xsi:type`` naming a data type that is
  **not** in the table is a *declared parsing limit*: the element is kept as text and recorded, never
  silently guessed at and never refused.
* :func:`datatype_for` — which data type an element carries: its ``xsi:type`` when it has one,
  otherwise the type the CDA R2 schema binds that element name to.
* :data:`KNOWN_TEMPLATES` — C-CDA R2.1 template ids the reader can *name*. Naming a template is not
  validating it: every ``templateId`` is an **asserted** conformance claim, recorded with
  :data:`TEMPLATE_CLAIM_STATEMENT`, whether or not its OID is in this table.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

__all__ = [
    "CDA_NAMESPACE",
    "DATATYPES",
    "DatatypeField",
    "DatatypeShape",
    "KNOWN_TEMPLATES",
    "NARRATIVE",
    "SDTC_NAMESPACE",
    "TEMPLATE_CLAIM_STATEMENT",
    "TS_PATTERN",
    "UNSUPPORTED_DATATYPE_STATEMENT",
    "XSI_NAMESPACE",
    "datatype_for",
    "template_name",
]

#: The HL7 v3 XML namespace every CDA element lives in.
CDA_NAMESPACE = "urn:hl7-org:v3"

#: The HL7 SDTC extension namespace (``sdtc:deceasedInd`` and friends).
SDTC_NAMESPACE = "urn:hl7-org:sdtc"

#: The XML Schema instance namespace that carries ``xsi:type``.
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"

#: The statement every template claim carries — a ``templateId`` is what the document *asserts* it
#: conforms to, and nothing in the import checks the assertion.
TEMPLATE_CLAIM_STATEMENT = (
    "Asserted by the document, not validated: a templateId records which implementation-guide "
    "template the document claims to conform to. Apiome reads the claim; it does not check the "
    "document against the template's constraints, and a recognised template name is not a "
    "conformance verdict."
)

#: The statement a data type outside :data:`DATATYPES` carries.
UNSUPPORTED_DATATYPE_STATEMENT = (
    "Declared parsing limit: this RIM data type is not mapped onto canonical types, so the element "
    "is kept as text."
)

#: Pseudo data type for a section's narrative block (``StrucDoc.Text``): mixed XHTML-like markup,
#: kept as text rather than modelled element by element.
NARRATIVE = "StrucDoc.Text"

#: HL7 TS: ``YYYY[MM[DD[HH[MM[SS[.S+]]]]]][+|-ZZZZ]`` — not ISO 8601, so it is a patterned string.
TS_PATTERN = r"^\d{4}(\d{2}(\d{2}(\d{2}(\d{2}(\d{2}(\.\d+)?)?)?)?)?)?([+-]\d{4})?$"


@dataclass(frozen=True)
class DatatypeField:
    """One member of a data type's canonical shape.

    Attributes:
        name: The attribute or child element name (``root``, ``translation``).
        type: A canonical primitive (``string``, ``bool``, ``i32``, ``double``) or another data
            type's name (``TS``, ``PQ``, ``CD``).
        repeated: Whether the member may occur more than once.
        pattern: A lexical pattern the value follows, when the data type defines one.
    """

    name: str
    type: str
    repeated: bool = False
    pattern: Optional[str] = None


@dataclass(frozen=True)
class DatatypeShape:
    """A RIM data type and how it maps onto the canonical model.

    Attributes:
        name: The data type name (``II``, ``IVL_TS``).
        title: Its spelled-out name.
        primitive: When set, the data type is plain text and maps to this canonical primitive
            instead of a record (``ST`` → ``string``).
        fields: The record members, when ``primitive`` is unset.
    """

    name: str
    title: str
    primitive: Optional[str] = None
    fields: Tuple[DatatypeField, ...] = ()


_NULL = DatatypeField("nullFlavor", "string")
_CODE_MEMBERS = (
    DatatypeField("code", "string"),
    DatatypeField("codeSystem", "string"),
    DatatypeField("codeSystemName", "string"),
    DatatypeField("codeSystemVersion", "string"),
    DatatypeField("displayName", "string"),
    DatatypeField("originalText", "string"),
)


def _shape(name: str, title: str, *fields: DatatypeField) -> DatatypeShape:
    return DatatypeShape(name=name, title=title, fields=(*fields, _NULL))


#: The RIM data types mapped onto canonical types, by name.
DATATYPES: Dict[str, DatatypeShape] = {
    shape.name: shape
    for shape in (
        _shape(
            "II",
            "Instance identifier",
            DatatypeField("root", "string"),
            DatatypeField("extension", "string"),
            DatatypeField("assigningAuthorityName", "string"),
            DatatypeField("displayable", "bool"),
        ),
        _shape("CD", "Concept descriptor", *_CODE_MEMBERS, DatatypeField("translation", "CD", True)),
        _shape("CE", "Coded with equivalents", *_CODE_MEMBERS, DatatypeField("translation", "CD", True)),
        _shape("CV", "Coded value", *_CODE_MEMBERS),
        _shape("CS", "Coded simple value", DatatypeField("code", "string")),
        _shape("TS", "Point in time", DatatypeField("value", "string", pattern=TS_PATTERN)),
        _shape(
            "IVL_TS",
            "Interval of points in time",
            DatatypeField("value", "string", pattern=TS_PATTERN),
            DatatypeField("low", "TS"),
            DatatypeField("high", "TS"),
            DatatypeField("center", "TS"),
            DatatypeField("width", "PQ"),
        ),
        _shape("PQ", "Physical quantity", DatatypeField("value", "double"), DatatypeField("unit", "string")),
        _shape("IVL_PQ", "Interval of physical quantities", DatatypeField("low", "PQ"), DatatypeField("high", "PQ")),
        _shape(
            "RTO_PQ_PQ",
            "Ratio of physical quantities",
            DatatypeField("numerator", "PQ"),
            DatatypeField("denominator", "PQ"),
        ),
        _shape("INT", "Integer number", DatatypeField("value", "i32")),
        _shape("REAL", "Real number", DatatypeField("value", "double")),
        _shape("BL", "Boolean", DatatypeField("value", "bool")),
        _shape(
            "AD",
            "Postal address",
            DatatypeField("use", "string"),
            DatatypeField("streetAddressLine", "string", True),
            DatatypeField("houseNumber", "string"),
            DatatypeField("streetName", "string"),
            DatatypeField("city", "string"),
            DatatypeField("county", "string"),
            DatatypeField("state", "string"),
            DatatypeField("postalCode", "string"),
            DatatypeField("country", "string"),
            DatatypeField("useablePeriod", "IVL_TS"),
        ),
        _shape(
            "PN",
            "Person name",
            DatatypeField("use", "string"),
            DatatypeField("prefix", "string", True),
            DatatypeField("given", "string", True),
            DatatypeField("family", "string", True),
            DatatypeField("suffix", "string", True),
            DatatypeField("validTime", "IVL_TS"),
        ),
        _shape(
            "TEL",
            "Telecommunication address",
            DatatypeField("value", "string"),
            DatatypeField("use", "string"),
        ),
        _shape(
            "ED",
            "Encapsulated data",
            DatatypeField("mediaType", "string"),
            DatatypeField("language", "string"),
            DatatypeField("representation", "string"),
            DatatypeField("reference", "TEL"),
            DatatypeField("text", "string"),
        ),
        DatatypeShape("ST", "Character string", primitive="string"),
        DatatypeShape("SC", "Character string with code", primitive="string"),
        DatatypeShape("ON", "Organization name", primitive="string"),
        DatatypeShape(NARRATIVE, "Section narrative block", primitive="string"),
    )
}

#: Element names whose data type is fixed by the CDA R2 schema, wherever they occur.
_ELEMENT_DATATYPES: Dict[str, str] = {
    "id": "II",
    "setId": "II",
    "typeId": "II",
    "templateId": "II",
    "code": "CD",
    "statusCode": "CS",
    "languageCode": "CS",
    "realmCode": "CS",
    "confidentialityCode": "CE",
    "effectiveTime": "TS",
    "time": "TS",
    "birthTime": "TS",
    "creationTime": "TS",
    "addr": "AD",
    "telecom": "TEL",
    "versionNumber": "INT",
    "sequenceNumber": "INT",
    "repeatNumber": "INT",
    "preferenceInd": "BL",
    "deceasedInd": "BL",
    "title": "ST",
    "doseQuantity": "PQ",
    "rateQuantity": "PQ",
    "quantity": "PQ",
    "manufacturerModelName": "SC",
    "softwareName": "SC",
    "lotNumberText": "ST",
}

#: Element names that hold an interval when written with ``low``/``high``/``center``/``width``.
_INTERVAL_PARTS = frozenset({"low", "high", "center", "width"})


def datatype_for(
    local_name: str,
    *,
    xsi_type: Optional[str],
    parent: Optional[str],
    child_names: Tuple[str, ...],
    has_text: bool,
) -> Optional[str]:
    """Return the RIM data type an element carries, or ``None`` when it is a RIM class.

    Args:
        local_name: The element's local name (``effectiveTime``).
        xsi_type: The local part of its ``xsi:type``, when it declares one; this wins over the
            schema binding and may name a data type outside :data:`DATATYPES`.
        parent: The parent element's local name (a section's ``text`` is narrative, an entry's
            ``text`` is ``ED``).
        child_names: The local names of the element's children.
        has_text: Whether the element carries character content of its own.

    Returns:
        The data type name, or ``None`` for a structural (class) element.
    """
    if xsi_type:
        return xsi_type
    if local_name == "text":
        return NARRATIVE if parent == "section" else "ED"
    if local_name == "name":
        # A person name is written in parts; an organization or device name is plain text.
        return "PN" if child_names else "ON"
    if local_name == "effectiveTime":
        # CDA R2 binds the document's own effectiveTime to TS and every act's to IVL_TS (whose
        # ``value`` member covers the single-point form); intervals are spotted anywhere else.
        if parent != "ClinicalDocument" or _INTERVAL_PARTS.intersection(child_names):
            return "IVL_TS"
        return "TS"
    if local_name.endswith("Code") and local_name not in _ELEMENT_DATATYPES:
        return "CE"
    return _ELEMENT_DATATYPES.get(local_name)


#: C-CDA R2.1 template ids this reader can name (HL7 C-CDA R2.1 template list). Being named here
#: says only what the document claims to be; it is never a validation result.
KNOWN_TEMPLATES: Dict[str, str] = {
    "2.16.840.1.113883.10.20.22.1.1": "US Realm Header",
    "2.16.840.1.113883.10.20.22.1.2": "Continuity of Care Document (CCD)",
    "2.16.840.1.113883.10.20.22.1.8": "Discharge Summary",
    "2.16.840.1.113883.10.20.22.2.1.1": "Medications Section (entries required)",
    "2.16.840.1.113883.10.20.22.2.3.1": "Results Section (entries required)",
    "2.16.840.1.113883.10.20.22.2.5.1": "Problem Section (entries required)",
    "2.16.840.1.113883.10.20.22.2.6.1": "Allergies and Intolerances Section (entries required)",
    "2.16.840.1.113883.10.20.22.2.7.1": "Procedures Section (entries required)",
    "2.16.840.1.113883.10.20.22.2.24": "Discharge Diagnosis Section",
    "2.16.840.1.113883.10.20.22.2.41": "Hospital Discharge Instructions Section",
    "2.16.840.1.113883.10.20.22.4.1": "Result Organizer",
    "2.16.840.1.113883.10.20.22.4.2": "Result Observation",
    "2.16.840.1.113883.10.20.22.4.3": "Problem Concern Act",
    "2.16.840.1.113883.10.20.22.4.14": "Procedure Activity Procedure",
    "2.16.840.1.113883.10.20.22.4.16": "Medication Activity",
    "2.16.840.1.113883.10.20.22.4.30": "Allergy Concern Act",
}


def template_name(root: Optional[str]) -> Optional[str]:
    """The C-CDA name of template ``root``, or ``None`` when the reader does not recognise it."""
    return KNOWN_TEMPLATES.get(root or "")
