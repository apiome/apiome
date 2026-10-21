"""DICOM vocabulary tables — FMT-6.7 (#5451).

The stated tables the DICOM reader works from:

* :data:`VR_SPECS` — every value representation of DICOM PS3.5 Table 6.2-1: its name, the canonical
  primitive it projects onto, its maximum length, and how Part 10 encodes it. The VR **is** the
  canonical type of an attribute; this table is what makes that type readable by every emitter.
* :func:`attribute_info` — what the DICOM data dictionary (PS3.6, as shipped by ``pydicom``) says
  about a tag: keyword, name, VR, VM and whether it is retired. Private tags are not in it.
* :data:`PIXEL_DATA_TAGS` / :func:`is_pixel_data_tag` — the image-content attributes whose values
  the reader **never reads**: Pixel Data, Float and Double Float Pixel Data, and Overlay Data.
* :data:`IDENTIFYING_TAGS` — attributes PS3.15 Annex E's Basic Application Level Confidentiality
  Profile lists for removal or replacement. The reader stores *no* attribute value in the model
  whatever this table says; it is how a reader of the schema learns which attributes carry
  patient-identifying values.
* :data:`STRUCTURAL_VALUE_TAGS` — the few attributes whose *value* is structure (the SOP class, the
  transfer syntax, a content item's value type …) and may therefore be recorded beside the model.

``pydicom`` is used for its data dictionary and UID registry only. Element bytes are read by
:mod:`app.dicom_part10`, which never decodes a pixel-data value.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, Optional, Tuple

from pydicom import datadict
from pydicom.uid import UID

__all__ = [
    "AttributeInfo",
    "CONTENT_SEQUENCE",
    "CONCEPT_NAME_CODE_SEQUENCE",
    "IDENTIFYING_TAGS",
    "LONG_HEADER_VRS",
    "PIXEL_DATA_BOUNDARY_STATEMENT",
    "PIXEL_DATA_TAGS",
    "QUERY_RESULT_TAGS",
    "SOP_CLASS_UID",
    "STRUCTURAL_VALUE_TAGS",
    "TRANSFER_SYNTAXES",
    "TransferSyntax",
    "VR_SPECS",
    "VrSpec",
    "attribute_info",
    "implicit_vr",
    "is_group_length",
    "is_identifying",
    "is_pixel_data_tag",
    "is_private",
    "is_private_creator",
    "parse_tag_key",
    "pascal_name",
    "sop_class_name",
    "tag_hex",
    "tag_text",
    "transfer_syntax",
]

#: The statement the capability panel, the format registry and every imported model carry.
PIXEL_DATA_BOUNDARY_STATEMENT = (
    "Pixel data is never read, never stored and never analysed. Apiome imports DICOM's metadata "
    "layer — the file meta information, the attribute structure and Structured Report content "
    "trees — and steps over every Pixel Data, Float Pixel Data, Double Float Pixel Data and "
    "Overlay Data value by its declared length without decoding it. Each one is recorded as "
    "present and skipped, with its VR and length, so its absence from the model is stated, not "
    "implied."
)

SOP_CLASS_UID = 0x00080016
CONTENT_SEQUENCE = 0x0040A730
CONCEPT_NAME_CODE_SEQUENCE = 0x0040A043


@dataclass(frozen=True)
class VrSpec:
    """One value representation (PS3.5 Table 6.2-1).

    Attributes:
        code: The two-letter VR (``PN``).
        name: Its PS3.5 name (``Person Name``).
        primitive: The canonical primitive the VR projects onto (``string``/``integer``/``number``),
            or ``None`` for ``SQ`` and ``PN``, which are records.
        max_length: Maximum value length in characters (``None`` when unbounded or binary).
        binary: Whether Part 10 stores the value as raw bytes rather than text.
        struct_code: The :mod:`struct` code of one binary number (``H`` for ``US``), if any.
    """

    code: str
    name: str
    primitive: Optional[str]
    max_length: Optional[int] = None
    binary: bool = False
    struct_code: Optional[str] = None


def _spec(code: str, name: str, primitive: Optional[str], **kwargs: object) -> Tuple[str, VrSpec]:
    return code, VrSpec(code=code, name=name, primitive=primitive, **kwargs)  # type: ignore[arg-type]


#: Every VR, keyed by its code.
VR_SPECS: Dict[str, VrSpec] = dict(
    [
        _spec("AE", "Application Entity", "string", max_length=16),
        _spec("AS", "Age String", "string", max_length=4),
        _spec("AT", "Attribute Tag", "string", binary=True, struct_code="H"),
        _spec("CS", "Code String", "string", max_length=16),
        _spec("DA", "Date", "string", max_length=8),
        _spec("DS", "Decimal String", "number", max_length=16),
        _spec("DT", "Date Time", "string", max_length=26),
        _spec("FD", "Floating Point Double", "number", binary=True, struct_code="d"),
        _spec("FL", "Floating Point Single", "number", binary=True, struct_code="f"),
        _spec("IS", "Integer String", "integer", max_length=12),
        _spec("LO", "Long String", "string", max_length=64),
        _spec("LT", "Long Text", "string", max_length=10240),
        _spec("OB", "Other Byte", "string", binary=True),
        _spec("OD", "Other Double", "string", binary=True),
        _spec("OF", "Other Float", "string", binary=True),
        _spec("OL", "Other Long", "string", binary=True),
        _spec("OV", "Other 64-bit Very Long", "string", binary=True),
        _spec("OW", "Other Word", "string", binary=True),
        _spec("PN", "Person Name", None, max_length=64),
        _spec("SH", "Short String", "string", max_length=16),
        _spec("SL", "Signed Long", "integer", binary=True, struct_code="l"),
        _spec("SQ", "Sequence of Items", None),
        _spec("SS", "Signed Short", "integer", binary=True, struct_code="h"),
        _spec("ST", "Short Text", "string", max_length=1024),
        _spec("SV", "Signed 64-bit Very Long", "integer", binary=True, struct_code="q"),
        _spec("TM", "Time", "string", max_length=14),
        _spec("UC", "Unlimited Characters", "string"),
        _spec("UI", "Unique Identifier (UID)", "string", max_length=64),
        _spec("UL", "Unsigned Long", "integer", binary=True, struct_code="L"),
        _spec("UN", "Unknown", "string", binary=True),
        _spec("UR", "Universal Resource Identifier or Locator (URI/URL)", "string"),
        _spec("US", "Unsigned Short", "integer", binary=True, struct_code="H"),
        _spec("UT", "Unlimited Text", "string"),
        _spec("UV", "Unsigned 64-bit Very Long", "integer", binary=True, struct_code="Q"),
    ]
)

#: VRs whose explicit-VR header carries two reserved bytes and a 32-bit length (PS3.5 §7.1.2).
LONG_HEADER_VRS: FrozenSet[str] = frozenset(
    {"OB", "OD", "OF", "OL", "OV", "OW", "SQ", "UC", "UN", "UR", "UT"}
)

#: The image-content attributes whose values are never read.
PIXEL_DATA_TAGS: FrozenSet[int] = frozenset({0x7FE00008, 0x7FE00009, 0x7FE00010})

#: Attributes that mark a dataset as a query/retrieve result (a study-, series- or instance-level
#: C-FIND or QIDO-RS response), which legitimately has no SOP Class UID.
QUERY_RESULT_TAGS: FrozenSet[int] = frozenset(
    {
        0x00080052,  # Query/Retrieve Level
        0x00080061,  # Modalities in Study
        0x00081190,  # Retrieve URL
        0x00201206,  # Number of Study Related Series
        0x00201208,  # Number of Study Related Instances
        0x00201209,  # Number of Series Related Instances
    }
)

#: Attributes whose value describes structure rather than a patient or a study, so it may be
#: recorded beside the canonical model and on analysis attributes.
STRUCTURAL_VALUE_TAGS: FrozenSet[int] = frozenset(
    {
        0x00020002,  # Media Storage SOP Class UID
        0x00020010,  # Transfer Syntax UID
        0x00080005,  # Specific Character Set
        0x00080016,  # SOP Class UID
        0x00080052,  # Query/Retrieve Level
        0x00080060,  # Modality
        0x00081150,  # Referenced SOP Class UID
        0x0040A010,  # Relationship Type
        0x0040A040,  # Value Type
        0x0040DB00,  # Template Identifier
    }
)

#: Attributes PS3.15 Annex E Table E.1-1 (Basic Application Level Confidentiality Profile) lists
#: for removal, replacement or cleaning. A stated subset: the patient, study, series, equipment,
#: operator and UID attributes a typical image or report carries. Every private attribute is
#: treated the same way (the profile removes them all) through :func:`is_identifying`.
IDENTIFYING_TAGS: FrozenSet[int] = frozenset(
    {
        0x00020003,  # Media Storage SOP Instance UID
        0x00080014,  # Instance Creator UID
        0x00080018,  # SOP Instance UID
        0x00080020,  # Study Date
        0x00080021,  # Series Date
        0x00080022,  # Acquisition Date
        0x00080023,  # Content Date
        0x0008002A,  # Acquisition DateTime
        0x00080030,  # Study Time
        0x00080031,  # Series Time
        0x00080032,  # Acquisition Time
        0x00080033,  # Content Time
        0x00080050,  # Accession Number
        0x00080080,  # Institution Name
        0x00080081,  # Institution Address
        0x00080090,  # Referring Physician's Name
        0x00080092,  # Referring Physician's Address
        0x00080094,  # Referring Physician's Telephone Numbers
        0x00081010,  # Station Name
        0x00081030,  # Study Description
        0x0008103E,  # Series Description
        0x00081040,  # Institutional Department Name
        0x00081048,  # Physician(s) of Record
        0x00081050,  # Performing Physician's Name
        0x00081060,  # Name of Physician(s) Reading Study
        0x00081070,  # Operators' Name
        0x00081080,  # Admitting Diagnoses Description
        0x00081155,  # Referenced SOP Instance UID
        0x00082111,  # Derivation Description
        0x00100010,  # Patient's Name
        0x00100020,  # Patient ID
        0x00100021,  # Issuer of Patient ID
        0x00100030,  # Patient's Birth Date
        0x00100032,  # Patient's Birth Time
        0x00100040,  # Patient's Sex
        0x00101000,  # Other Patient IDs
        0x00101001,  # Other Patient Names
        0x00101010,  # Patient's Age
        0x00101020,  # Patient's Size
        0x00101030,  # Patient's Weight
        0x00101040,  # Patient's Address
        0x00101060,  # Patient's Mother's Birth Name
        0x00102154,  # Patient's Telephone Numbers
        0x00102160,  # Ethnic Group
        0x00102180,  # Occupation
        0x001021B0,  # Additional Patient History
        0x00104000,  # Patient Comments
        0x00181000,  # Device Serial Number
        0x00181030,  # Protocol Name
        0x0020000D,  # Study Instance UID
        0x0020000E,  # Series Instance UID
        0x00200010,  # Study ID
        0x00200052,  # Frame of Reference UID
        0x00200200,  # Synchronization Frame of Reference UID
        0x00204000,  # Image Comments
        0x00321032,  # Requesting Physician
        0x00321060,  # Requested Procedure Description
        0x00400244,  # Performed Procedure Step Start Date
        0x00400245,  # Performed Procedure Step Start Time
        0x00400253,  # Performed Procedure Step ID
        0x00400254,  # Performed Procedure Step Description
        0x00400275,  # Request Attributes Sequence
        0x0040A073,  # Verifying Observer Sequence
        0x0040A075,  # Verifying Observer Name
        0x0040A088,  # Verifying Observer Identification Code Sequence
        0x0040A123,  # Person Name
        0x0040A124,  # UID
        0x0040A730,  # Content Sequence
        0x00880140,  # Storage Media File-set UID
        0x30060024,  # Referenced Frame of Reference UID
        0x300600C2,  # Related Frame of Reference UID
    }
)


@dataclass(frozen=True)
class AttributeInfo:
    """What the data dictionary says about one tag.

    Attributes:
        keyword: The PS3.6 keyword (``PatientName``), or ``None`` for a tag the dictionary lacks.
        name: The PS3.6 attribute name (``Patient's Name``), or ``None``.
        vr: The dictionary VR, possibly ambiguous (``OB or OW``), or ``None``.
        vm: The dictionary value multiplicity (``1``, ``1-n``, ``3``), or ``None``.
        retired: Whether the attribute is retired.
    """

    keyword: Optional[str]
    name: Optional[str]
    vr: Optional[str]
    vm: Optional[str]
    retired: bool = False

    @property
    def multi_valued(self) -> bool:
        """Whether the dictionary allows more than one value."""
        return self.vm is not None and self.vm != "1"


_UNKNOWN = AttributeInfo(keyword=None, name=None, vr=None, vm=None)


def attribute_info(tag: int) -> AttributeInfo:
    """Look ``tag`` up in the PS3.6 data dictionary (repeating groups such as ``60xx`` included).

    Args:
        tag: The 32-bit tag (``0x00100010``).

    Returns:
        The dictionary entry, or an all-``None`` entry for a private or unknown tag.
    """
    if is_private(tag):
        return _UNKNOWN
    try:
        vr, vm, name, retired, keyword = datadict.get_entry(tag)
    except KeyError:
        if is_group_length(tag):
            return AttributeInfo(keyword=None, name="Group Length", vr="UL", vm="1")
        return _UNKNOWN
    return AttributeInfo(
        keyword=keyword or None,
        name=name or None,
        vr=vr or None,
        vm=vm or None,
        retired=bool(retired),
    )


def implicit_vr(tag: int) -> str:
    """The VR an implicit-VR transfer syntax implies for ``tag`` (PS3.5 Annex A.1).

    An ambiguous dictionary VR resolves to the form implicit VR little endian uses (``OB or OW`` →
    ``OW``, ``US or SS`` → ``US``); a private creator is ``LO``; anything else unknown is ``UN``.
    """
    if is_private_creator(tag):
        return "LO"
    info = attribute_info(tag)
    if info.vr is None:
        return "UN"
    if info.vr == "OB or OW":
        return "OW"
    return info.vr.split(" or ", 1)[0]


def is_private(tag: int) -> bool:
    """Whether ``tag`` is in an odd (private) group."""
    return bool((tag >> 16) & 1)


def is_private_creator(tag: int) -> bool:
    """Whether ``tag`` is a private creator element (``gggg,0010``–``gggg,00FF``, odd group)."""
    return is_private(tag) and 0x0010 <= (tag & 0xFFFF) <= 0x00FF


def is_group_length(tag: int) -> bool:
    """Whether ``tag`` is a group length element (``gggg,0000``)."""
    return tag & 0xFFFF == 0


def is_pixel_data_tag(tag: int) -> bool:
    """Whether ``tag``'s value is image content the reader must never read.

    Pixel Data and its float variants, plus Overlay Data in every overlay group (``60xx,3000``).
    """
    if tag in PIXEL_DATA_TAGS:
        return True
    group = tag >> 16
    return 0x6000 <= group <= 0x601E and group % 2 == 0 and tag & 0xFFFF == 0x3000


def is_identifying(tag: int) -> bool:
    """Whether ``tag``'s value is patient-identifying under PS3.15 Annex E (private tags included)."""
    return tag in IDENTIFYING_TAGS or (is_private(tag) and not is_private_creator(tag))


def tag_hex(tag: int) -> str:
    """The DICOM JSON spelling of a tag (``00100010``)."""
    return f"{tag:08X}"


def tag_text(tag: int) -> str:
    """The conventional spelling of a tag (``(0010,0010)``)."""
    return f"({tag >> 16:04X},{tag & 0xFFFF:04X})"


_TAG_KEY = re.compile(r"^[0-9A-Fa-f]{8}$")


def parse_tag_key(key: str) -> Optional[int]:
    """Parse a DICOM JSON attribute key (8 hex digits) into a tag, or ``None`` if it is not one."""
    if not isinstance(key, str) or not _TAG_KEY.match(key):
        return None
    return int(key, 16)


_WORD = re.compile(r"[A-Za-z0-9]+")


def pascal_name(text: str) -> str:
    """Turn a registry name into a type name (``CT Image Storage`` → ``CTImageStorage``)."""
    words = _WORD.findall(text)
    name = "".join(word if word.isupper() else word[:1].upper() + word[1:] for word in words)
    if not name or name[0].isdigit():
        name = f"Dicom{name}"
    return name


def sop_class_name(uid: Optional[str]) -> Optional[str]:
    """The registry name of a SOP class UID (``CT Image Storage``), or ``None`` if not registered."""
    if not uid:
        return None
    entry = UID(uid)
    name = entry.name
    if not entry.is_valid or name == uid or entry.type not in ("SOP Class", ""):
        return None
    return name


@dataclass(frozen=True)
class TransferSyntax:
    """How a Part 10 dataset is encoded.

    Attributes:
        uid: The transfer syntax UID.
        name: Its registry name, or the UID when unregistered.
        explicit_vr: Whether each element states its VR.
        little_endian: Byte order of numbers and lengths.
        deflated: Whether the dataset is a raw deflate stream (PS3.5 §10.3).
        encapsulated: Whether pixel data is compressed into fragments (the dataset is not).
    """

    uid: str
    name: str
    explicit_vr: bool = True
    little_endian: bool = True
    deflated: bool = False
    encapsulated: bool = False


IMPLICIT_VR_LITTLE_ENDIAN = "1.2.840.10008.1.2"
EXPLICIT_VR_LITTLE_ENDIAN = "1.2.840.10008.1.2.1"
EXPLICIT_VR_BIG_ENDIAN = "1.2.840.10008.1.2.2"
DEFLATED_EXPLICIT_VR_LITTLE_ENDIAN = "1.2.840.10008.1.2.1.99"

#: The transfer syntaxes whose dataset encoding differs from explicit VR little endian.
TRANSFER_SYNTAXES: Dict[str, TransferSyntax] = {
    IMPLICIT_VR_LITTLE_ENDIAN: TransferSyntax(
        IMPLICIT_VR_LITTLE_ENDIAN, "Implicit VR Little Endian", explicit_vr=False
    ),
    EXPLICIT_VR_LITTLE_ENDIAN: TransferSyntax(EXPLICIT_VR_LITTLE_ENDIAN, "Explicit VR Little Endian"),
    EXPLICIT_VR_BIG_ENDIAN: TransferSyntax(
        EXPLICIT_VR_BIG_ENDIAN, "Explicit VR Big Endian", little_endian=False
    ),
    DEFLATED_EXPLICIT_VR_LITTLE_ENDIAN: TransferSyntax(
        DEFLATED_EXPLICIT_VR_LITTLE_ENDIAN, "Deflated Explicit VR Little Endian", deflated=True
    ),
}


def transfer_syntax(uid: str) -> TransferSyntax:
    """Resolve a transfer syntax UID.

    Every transfer syntax not in :data:`TRANSFER_SYNTAXES` — JPEG, JPEG 2000, RLE, HTJ2K, MPEG … and
    any private one — encodes its dataset as explicit VR little endian (PS3.5 §10); only the pixel
    data inside it is compressed, and that is never read.
    """
    known = TRANSFER_SYNTAXES.get(uid)
    if known is not None:
        return known
    entry = UID(uid)
    registered = entry.name if entry.name and entry.name != uid else uid
    encapsulated = bool(entry.is_valid and entry.is_transfer_syntax and entry.is_encapsulated)
    return TransferSyntax(uid=uid, name=registered, encapsulated=encapsulated)
