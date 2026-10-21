"""NCPDP Telecommunication D.0 reader — FMT-6.8 (#5452).

Reads an NCPDP Telecommunication Standard **D.0 request transmission** — the pharmacy claim format —
into a :class:`TelecomTransmission`:

.. code-block:: text

    610011D0B1PCN0000001101…EXAMPLESW1      56-character fixed transaction header
    <SS|GS> AM04 <FS> C2… <FS> CC…          segments: a segment id field, then fields
    <SS|GS> AM07 <FS> EM… <FS> D2…          whose first two characters are the field id

The header is positional (:data:`HEADER_LAYOUT`). Everything after it is delimited: ``0x1E`` (segment
separator) or ``0x1D`` (group separator) opens a segment, ``0x1C`` (field separator) opens a field,
and the first field of every segment is its ``AM`` segment identification (``AM07`` = claim). A
segment-id field may be written with or without the field separator before it.

**Transactions.** The patient (``AM01``) and insurance (``AM04``) segments belong to the transmission;
every other segment belongs to a transaction. A transaction opens with its first transaction-level
segment, and a second claim segment (``AM07``) opens the next one — the rule that separates the
transactions of a multi-claim billing whichever separator the sender used between them.

**Labels, not a data dictionary.** :data:`SEGMENT_NAMES` names the request segments and
:data:`FIELD_LABELS` the field ids most claims carry, so a reader sees ``302-C2 Cardholder ID``
rather than ``C2``. An id not in the table keeps its bare id. No NCPDP implementation guide or
payer sheet is consulted: a field's presence is recorded, never its requiredness.

Errors are :class:`TelecomParseError` with an intake-taxonomy code:

* ``INPUT_TRUNCATED`` — the text stops inside the fixed header;
* ``INPUT_MALFORMED`` — a segment without its ``AM`` identification, a field shorter than its
  two-character id, a line break inside the transmission, or a header whose BIN is not numeric;
* ``INPUT_SEMANTIC_INVALID`` — a version other than ``D0``, an unknown transaction code, an
  unreadable transaction count, or a header with no segments after it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "CLAIM_TRANSACTION_CODES",
    "FIELD_LABELS",
    "FIELD_SEPARATOR",
    "GROUP_SEPARATOR",
    "HEADER_LAYOUT",
    "HEADER_LENGTH",
    "SEGMENT_NAMES",
    "SEGMENT_SEPARATOR",
    "SUPPORTED_TELECOM_VERSIONS",
    "TRANSACTION_CODES",
    "TRANSMISSION_SEGMENTS",
    "TelecomField",
    "TelecomHeaderField",
    "TelecomParseError",
    "TelecomSegment",
    "TelecomTransmission",
    "has_telecom_header",
    "is_telecom",
    "parse_telecom",
    "segment_name",
]

#: Field separator: opens every field, including (optionally) the segment-id field.
FIELD_SEPARATOR = "\x1c"
#: Group separator: opens a transaction group; also accepted as a segment opener.
GROUP_SEPARATOR = "\x1d"
#: Segment separator: opens a segment.
SEGMENT_SEPARATOR = "\x1e"
_SEGMENT_OPENERS = (SEGMENT_SEPARATOR, GROUP_SEPARATOR)

#: The only version/release the reader accepts (``102-A2``).
SUPPORTED_TELECOM_VERSIONS: Tuple[str, ...] = ("D0",)

#: Transaction codes (``103-A3``) and what they request.
TRANSACTION_CODES: Dict[str, str] = {
    "B1": "Billing",
    "B2": "Reversal",
    "B3": "Rebill",
    "E1": "Eligibility Verification",
    "N1": "Information Reporting",
    "N2": "Information Reporting Reversal",
    "N3": "Information Reporting Rebill",
    "P1": "Prior Authorization Request and Billing",
    "P2": "Prior Authorization Reversal",
    "P3": "Prior Authorization Inquiry",
    "P4": "Prior Authorization Request Only",
    "C1": "Controlled Substance Reporting",
    "C2": "Controlled Substance Reporting Reversal",
    "C3": "Controlled Substance Reporting Rebill",
    "S1": "Service Billing",
    "S2": "Service Reversal",
    "S3": "Service Rebill",
}

#: Transaction codes whose every transaction carries one claim segment, so the header's declared
#: transaction count can be compared with the claim segments observed. For the other codes the
#: declared count is recorded and not compared.
CLAIM_TRANSACTION_CODES: Tuple[str, ...] = ("B1", "B2", "B3")

#: Request segments by their two-digit ``111-AM`` id.
SEGMENT_NAMES: Dict[str, str] = {
    "01": "Patient",
    "02": "Pharmacy Provider",
    "03": "Prescriber",
    "04": "Insurance",
    "05": "Coordination of Benefits/Other Payments",
    "06": "Workers' Compensation",
    "07": "Claim",
    "08": "DUR/PPS",
    "09": "Coupon",
    "10": "Compound",
    "11": "Pricing",
    "12": "Prior Authorization",
    "13": "Clinical",
    "14": "Additional Documentation",
    "15": "Facility",
    "16": "Narrative",
}

#: Segments that belong to the transmission rather than to one transaction.
TRANSMISSION_SEGMENTS: Tuple[str, ...] = ("01", "04")

#: The claim segment, which opens each transaction of a multi-claim transmission.
_CLAIM_SEGMENT = "07"

#: Labels for the field ids most claims carry (``id`` → ``data element number and name``). Not the
#: data dictionary: an id absent here is kept under its bare id.
FIELD_LABELS: Dict[str, str] = {
    # Patient
    "C4": "304-C4 Date of Birth",
    "C5": "305-C5 Patient Gender Code",
    "CA": "310-CA Patient First Name",
    "CB": "311-CB Patient Last Name",
    "CP": "325-CP Patient ZIP/Postal Zone",
    # Insurance
    "C1": "301-C1 Group ID",
    "C2": "302-C2 Cardholder ID",
    "C3": "303-C3 Person Code",
    "C6": "306-C6 Patient Relationship Code",
    "CC": "312-CC Cardholder First Name",
    "CD": "313-CD Cardholder Last Name",
    "FO": "524-FO Plan ID",
    # Claim
    "EM": "455-EM Prescription/Service Reference Number Qualifier",
    "D2": "402-D2 Prescription/Service Reference Number",
    "E1": "436-E1 Product/Service ID Qualifier",
    "D7": "407-D7 Product/Service ID",
    "E7": "442-E7 Quantity Dispensed",
    "D3": "403-D3 Fill Number",
    "D5": "405-D5 Days Supply",
    "D6": "406-D6 Compound Code",
    "D8": "408-D8 Dispense As Written/Product Selection Code",
    "DE": "414-DE Date Prescription Written",
    "DF": "415-DF Number of Refills Authorized",
    # Pricing
    "D9": "409-D9 Ingredient Cost Submitted",
    "DC": "412-DC Dispensing Fee Submitted",
    "DQ": "426-DQ Usual and Customary Charge",
    "DU": "430-DU Gross Amount Due",
    "DN": "423-DN Basis of Cost Determination",
    # Prescriber
    "EZ": "466-EZ Prescriber ID Qualifier",
    "DB": "411-DB Prescriber ID",
    "DR": "427-DR Prescriber Last Name",
}


@dataclass(frozen=True)
class TelecomHeaderField:
    """One positional field of the fixed transaction header.

    Attributes:
        name: The field's camelCase name (``binNumber``).
        label: The data element number and name (``101-A1 BIN Number``).
        start: 1-based first column.
        length: Width in characters.
    """

    name: str
    label: str
    start: int
    length: int

    @property
    def end(self) -> int:
        """1-based last column."""
        return self.start + self.length - 1


def _layout(*fields: Tuple[str, str, int]) -> Tuple[TelecomHeaderField, ...]:
    out: List[TelecomHeaderField] = []
    start = 1
    for name, label, length in fields:
        out.append(TelecomHeaderField(name, label, start, length))
        start += length
    return tuple(out)


#: The D.0 request transaction header, in column order.
HEADER_LAYOUT: Tuple[TelecomHeaderField, ...] = _layout(
    ("binNumber", "101-A1 BIN Number", 6),
    ("versionReleaseNumber", "102-A2 Version/Release Number", 2),
    ("transactionCode", "103-A3 Transaction Code", 2),
    ("processorControlNumber", "104-A4 Processor Control Number", 10),
    ("transactionCount", "109-A9 Transaction Count", 1),
    ("serviceProviderIdQualifier", "202-B2 Service Provider ID Qualifier", 2),
    ("serviceProviderId", "201-B1 Service Provider ID", 15),
    ("dateOfService", "401-D1 Date of Service", 8),
    ("softwareVendorCertificationId", "110-AK Software Vendor/Certification ID", 10),
)
#: Width of the request header.
HEADER_LENGTH = HEADER_LAYOUT[-1].end

# Header shape the sniffer claims: a numeric BIN, then version and transaction code.
_HEADER_RE = re.compile(r"^\d{6}[A-Z0-9]{2}[A-Z0-9]{2}")
_SEGMENT_ID_RE = re.compile(r"^AM(\d{2})$")
_FIELD_ID_RE = re.compile(r"^[A-Z0-9]{2}$")


class TelecomParseError(ValueError):
    """Raised when text is not a readable Telecom D.0 request transmission.

    Attributes:
        code: The intake-taxonomy code naming the failure.
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class TelecomField:
    """One field of a segment.

    Attributes:
        field_id: The two-character field id (``C2``).
        value: The field's value, the id removed.
        offset: 0-based character offset of the field id.
        length: Characters from the field id to the end of the value.
    """

    field_id: str
    value: str
    offset: int
    length: int


@dataclass
class TelecomSegment:
    """One segment: its ``AM`` id and its fields, with where its bytes sit.

    Attributes:
        segment_id: The two-digit id (``07``).
        fields: The fields after the segment id, in source order.
        separator: ``SS`` or ``GS`` — the separator that opened it.
        offset: 0-based offset of the opening separator.
        length: Characters from the separator to the end of the last field.
        line: 1-based line (a transmission is one line).
        column: 1-based column of the opening separator.
    """

    segment_id: str
    fields: List[TelecomField]
    separator: str
    offset: int
    length: int
    line: int = 1
    column: int = 1

    @property
    def tag(self) -> str:
        """The segment identification as written (``AM07``)."""
        return f"AM{self.segment_id}"

    @property
    def name(self) -> str:
        """The segment's name (``Claim``), or ``Segment AMnn`` for an id not in the table."""
        return segment_name(self.segment_id)


@dataclass
class TelecomTransmission:
    """A parsed D.0 request transmission.

    Attributes:
        raw: The transmission text.
        source_label: The file name, when known.
        header: Header field name → value, as written (padding kept).
        segments: Every segment in source order.
        transmission_segments: The patient and insurance segments.
        transactions: Transaction-level segments, grouped per transaction.
    """

    raw: str
    source_label: Optional[str]
    header: Dict[str, str]
    segments: List[TelecomSegment]
    transmission_segments: List[TelecomSegment] = field(default_factory=list)
    transactions: List[List[TelecomSegment]] = field(default_factory=list)

    @property
    def version(self) -> str:
        """The version/release (``D0``)."""
        return self.header["versionReleaseNumber"]

    @property
    def transaction_code(self) -> str:
        """The transaction code (``B1``)."""
        return self.header["transactionCode"]

    @property
    def transaction_name(self) -> str:
        """What the transaction code requests (``Billing``)."""
        return TRANSACTION_CODES[self.transaction_code]

    @property
    def declared_transaction_count(self) -> Optional[int]:
        """The header's transaction count, or ``None`` when unreadable."""
        text = self.header["transactionCount"].strip()
        return int(text) if text.isdigit() else None


def segment_name(segment_id: str) -> str:
    """The name of a segment id (``07`` → ``Claim``); ``Segment AMnn`` for an unnamed id."""
    return SEGMENT_NAMES.get(segment_id, f"Segment AM{segment_id}")


def _label(source_label: Optional[str]) -> str:
    return f" ({source_label})" if source_label else ""


def has_telecom_header(text: Optional[str]) -> bool:
    """Whether ``text`` opens like a request header: a numeric BIN, then version and transaction code.

    Looser than :func:`is_telecom` — a header cut short, or one with no segment after it, still
    qualifies — so the reader, not the sniffer, says what is wrong with it. Never raises.
    """
    return bool(text) and bool(_HEADER_RE.match(text))  # type: ignore[arg-type]


def is_telecom(text: Optional[str]) -> bool:
    """Whether ``text`` opens with a Telecom request header followed by an ``AM`` segment.

    The version is not checked here, so a header naming another version is still claimed and the
    parser can say what is wrong with it. Never raises.
    """
    if not text or not _HEADER_RE.match(text):
        return False
    body = text[HEADER_LENGTH : HEADER_LENGTH + 8]
    return bool(body) and body[0] in _SEGMENT_OPENERS and "AM" in body


def _read_header(text: str, source_label: Optional[str]) -> Dict[str, str]:
    if len(text) < HEADER_LENGTH:
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)} stops at column {len(text)}, inside its "
            f"{HEADER_LENGTH}-character transaction header. The transmission was truncated.",
            code="INPUT_TRUNCATED",
        )
    header = {spec.name: text[spec.start - 1 : spec.end] for spec in HEADER_LAYOUT}
    if not header["binNumber"].isdigit():
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)} has a non-numeric BIN number "
            f"({header['binNumber']!r}) in columns 1-6.",
            code="INPUT_MALFORMED",
        )
    version = header["versionReleaseNumber"]
    if version not in SUPPORTED_TELECOM_VERSIONS:
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)} declares version/release {version!r}; only "
            "Telecommunication Standard D.0 (`D0`) is read.",
            code="INPUT_SEMANTIC_INVALID",
        )
    code = header["transactionCode"]
    if code not in TRANSACTION_CODES:
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)} declares transaction code {code!r}, which is "
            f"not a D.0 request transaction ({', '.join(TRANSACTION_CODES)}).",
            code="INPUT_SEMANTIC_INVALID",
        )
    if not header["transactionCount"].strip().isdigit():
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)} has an unreadable transaction count "
            f"({header['transactionCount']!r}) in column 21.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return header


def _split_segments(body: str, base: int) -> List[Tuple[str, int, str]]:
    """Cut the body into ``(separator, offset, text)`` per segment; offsets are absolute."""
    pieces: List[Tuple[str, int, str]] = []
    start = 0
    for index in range(1, len(body) + 1):
        if index == len(body) or body[index] in _SEGMENT_OPENERS:
            pieces.append((body[start], base + start, body[start + 1 : index]))
            start = index
    return pieces


def _read_segment(separator: str, offset: int, text: str, source_label: Optional[str]) -> TelecomSegment:
    """Read one segment's id and fields."""
    cursor = offset + 1
    if text.startswith(FIELD_SEPARATOR):
        text = text[1:]
        cursor += 1
    parts = text.split(FIELD_SEPARATOR)
    match = _SEGMENT_ID_RE.match(parts[0])
    if match is None:
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)}: the segment at offset {offset} does not open "
            f"with its `AM` segment identification (found {parts[0][:8]!r}).",
            code="INPUT_MALFORMED",
        )
    fields: List[TelecomField] = []
    cursor += len(parts[0])
    for part in parts[1:]:
        cursor += 1  # the field separator
        field_id = part[:2]
        if not _FIELD_ID_RE.match(field_id):
            raise TelecomParseError(
                f"Telecom transmission{_label(source_label)}: segment AM{match.group(1)} has a field at "
                f"offset {cursor} without a two-character field id (found {part[:8]!r}).",
                code="INPUT_MALFORMED",
            )
        fields.append(TelecomField(field_id=field_id, value=part[2:], offset=cursor, length=len(part)))
        cursor += len(part)
    return TelecomSegment(
        segment_id=match.group(1),
        fields=fields,
        separator="SS" if separator == SEGMENT_SEPARATOR else "GS",
        offset=offset,
        length=cursor - offset,
        column=offset + 1,
    )


def _group(segments: List[TelecomSegment]) -> Tuple[List[TelecomSegment], List[List[TelecomSegment]]]:
    """Split segments into transmission-level ones and per-transaction groups."""
    transmission: List[TelecomSegment] = []
    transactions: List[List[TelecomSegment]] = []
    for segment in segments:
        if segment.segment_id in TRANSMISSION_SEGMENTS:
            transmission.append(segment)
            continue
        opens_next = (
            segment.segment_id == _CLAIM_SEGMENT
            and transactions
            and any(item.segment_id == _CLAIM_SEGMENT for item in transactions[-1])
        )
        if not transactions or opens_next:
            transactions.append([])
        transactions[-1].append(segment)
    return transmission, transactions


def parse_telecom(text: str, *, source_label: Optional[str] = None) -> TelecomTransmission:
    """Parse a Telecom D.0 request transmission.

    Args:
        text: The transmission text. One trailing line break is tolerated.
        source_label: The file name, used in error messages.

    Returns:
        The :class:`TelecomTransmission`.

    Raises:
        TelecomParseError: When the text is not a readable D.0 request (see the module docstring).
    """
    content = text.rstrip("\r\n")
    header = _read_header(content, source_label)
    body = content[HEADER_LENGTH:]
    if "\n" in body or "\r" in body:
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)} contains a line break; a transmission is one "
            "unbroken run of segments.",
            code="INPUT_MALFORMED",
        )
    if not body:
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)} carries a transaction header and no segments.",
            code="INPUT_SEMANTIC_INVALID",
        )
    if body[0] not in _SEGMENT_OPENERS:
        raise TelecomParseError(
            f"Telecom transmission{_label(source_label)}: column {HEADER_LENGTH + 1} must open a segment "
            f"with a segment or group separator (found {body[:8]!r}).",
            code="INPUT_MALFORMED",
        )
    segments = [
        _read_segment(separator, offset, piece, source_label)
        for separator, offset, piece in _split_segments(body, HEADER_LENGTH)
    ]
    transmission_segments, transactions = _group(segments)
    return TelecomTransmission(
        raw=text,
        source_label=source_label,
        header=header,
        segments=segments,
        transmission_segments=transmission_segments,
        transactions=transactions,
    )
