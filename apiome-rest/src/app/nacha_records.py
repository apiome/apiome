"""NACHA ACH record layouts — FMT-6.6 (#5450).

An ACH file is fixed-width: every record is exactly :data:`RECORD_LENGTH` characters, and the first
character — the *record type code* — decides how the other 93 are cut into fields. This module is
that decision and nothing else: one :class:`NachaFieldSpec` table per record type (and, for the
``7`` addenda record, per addenda type code), positions 1-based and inclusive exactly as the NACHA
Operating Rules' record formats print them.

.. code-block:: text

    1  File header      immediate destination/origin, creation date/time, record size, blocking
    5  Batch header     service class, company name/id, SEC code, entry description, dates
    6  Entry detail     transaction code, RDFI routing + check digit, account, amount, trace
    7  Addenda          05 payment-related information · 98 notification of change · 99 return
    8  Batch control    entry/addenda count, entry hash, total debit, total credit
    9  File control     batch count, block count, entry/addenda count, entry hash, totals

Nothing here reads a file. :mod:`app.nacha_parser` slices records with :func:`record_fields`, the
normalizer turns each table into a record type, and the analysis turns each slice into a value node.

What the tables do not do
-------------------------
They describe the *domestic* layouts. An ``IAT`` (international) batch reuses the record type codes
with different entry and addenda layouts; it is read with the domestic tables and the analysis says
so. Field names follow the PPD wording (``individualName``); a CCD writes a receiving company in the
same positions, which the tables record as an alternate label rather than a second layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "ADDENDA_LAYOUTS",
    "BLOCKING_FACTOR",
    "FIELD_ALPHANUMERIC",
    "FIELD_AMOUNT",
    "FIELD_NUMERIC",
    "FILLER_RECORD",
    "GENERIC_ADDENDA_LAYOUT",
    "NachaFieldSpec",
    "RECORD_LAYOUTS",
    "RECORD_LENGTH",
    "RECORD_NAMES",
    "RECORD_SIZE",
    "addenda_layout",
    "credit_or_debit",
    "is_prenote",
    "layout_for",
    "record_fields",
    "routing_check_digit",
]

#: Characters in every ACH record.
RECORD_LENGTH = 94
#: The record size the file header declares (positions 35-37).
RECORD_SIZE = "094"
#: Records per block; the file is padded to a multiple of this with :data:`FILLER_RECORD` lines.
BLOCKING_FACTOR = 10
#: A block-padding record: 94 nines.
FILLER_RECORD = "9" * RECORD_LENGTH

#: Field kinds. ``numeric`` is right-justified digits (a count, a code, a routing number);
#: ``amount`` is numeric in cents with no decimal point; ``alphanumeric`` is left-justified text.
FIELD_ALPHANUMERIC = "alphanumeric"
FIELD_NUMERIC = "numeric"
FIELD_AMOUNT = "amount"


@dataclass(frozen=True)
class NachaFieldSpec:
    """One field of a fixed-width record.

    Attributes:
        name: Stable camelCase field name (``receivingDfiIdentification``).
        start: 1-based first position, as the record format prints it.
        end: 1-based last position, inclusive.
        kind: :data:`FIELD_ALPHANUMERIC`, :data:`FIELD_NUMERIC` or :data:`FIELD_AMOUNT`.
        label: Human label (``Receiving DFI identification``).
        note: Optional reading note (``YYMMDD``, ``CCD: receiving company name``).
    """

    name: str
    start: int
    end: int
    kind: str
    label: str
    note: Optional[str] = None

    @property
    def length(self) -> int:
        """Number of characters the field occupies."""
        return self.end - self.start + 1

    def slice(self, record: str) -> str:
        """Return the field's characters from ``record``, as written (no trimming)."""
        return record[self.start - 1 : self.end]


def _f(name: str, start: int, end: int, kind: str, label: str, note: Optional[str] = None) -> NachaFieldSpec:
    """Shorthand constructor for the layout tables below."""
    return NachaFieldSpec(name=name, start=start, end=end, kind=kind, label=label, note=note)


_A, _N, _M = FIELD_ALPHANUMERIC, FIELD_NUMERIC, FIELD_AMOUNT

FILE_HEADER: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("priorityCode", 2, 3, _N, "Priority code"),
    _f("immediateDestination", 4, 13, _A, "Immediate destination", "Receiving point routing number"),
    _f("immediateOrigin", 14, 23, _A, "Immediate origin"),
    _f("fileCreationDate", 24, 29, _N, "File creation date", "YYMMDD"),
    _f("fileCreationTime", 30, 33, _N, "File creation time", "HHMM"),
    _f("fileIdModifier", 34, 34, _A, "File ID modifier"),
    _f("recordSize", 35, 37, _N, "Record size"),
    _f("blockingFactor", 38, 39, _N, "Blocking factor"),
    _f("formatCode", 40, 40, _N, "Format code"),
    _f("immediateDestinationName", 41, 63, _A, "Immediate destination name"),
    _f("immediateOriginName", 64, 86, _A, "Immediate origin name"),
    _f("referenceCode", 87, 94, _A, "Reference code"),
)

BATCH_HEADER: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("serviceClassCode", 2, 4, _N, "Service class code", "200 mixed, 220 credits, 225 debits"),
    _f("companyName", 5, 20, _A, "Company name"),
    _f("companyDiscretionaryData", 21, 40, _A, "Company discretionary data"),
    _f("companyIdentification", 41, 50, _A, "Company identification"),
    _f("standardEntryClassCode", 51, 53, _A, "Standard entry class code"),
    _f("companyEntryDescription", 54, 63, _A, "Company entry description"),
    _f("companyDescriptiveDate", 64, 69, _A, "Company descriptive date"),
    _f("effectiveEntryDate", 70, 75, _N, "Effective entry date", "YYMMDD"),
    _f("settlementDate", 76, 78, _A, "Settlement date", "Julian day; inserted by the ACH operator"),
    _f("originatorStatusCode", 79, 79, _A, "Originator status code"),
    _f("originatingDfiIdentification", 80, 87, _N, "Originating DFI identification"),
    _f("batchNumber", 88, 94, _N, "Batch number"),
)

ENTRY_DETAIL: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("transactionCode", 2, 3, _N, "Transaction code"),
    _f("receivingDfiIdentification", 4, 11, _N, "Receiving DFI identification"),
    _f("checkDigit", 12, 12, _N, "Check digit"),
    _f("dfiAccountNumber", 13, 29, _A, "DFI account number"),
    _f("amount", 30, 39, _M, "Amount", "Cents, no decimal point"),
    _f(
        "individualIdentificationNumber",
        40,
        54,
        _A,
        "Individual identification number",
        "CCD: identification number",
    ),
    _f("individualName", 55, 76, _A, "Individual name", "CCD: receiving company name"),
    _f("discretionaryData", 77, 78, _A, "Discretionary data"),
    _f("addendaRecordIndicator", 79, 79, _N, "Addenda record indicator"),
    _f("traceNumber", 80, 94, _N, "Trace number"),
)

BATCH_CONTROL: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("serviceClassCode", 2, 4, _N, "Service class code"),
    _f("entryAddendaCount", 5, 10, _N, "Entry/addenda count"),
    _f("entryHash", 11, 20, _N, "Entry hash"),
    _f("totalDebitEntryDollarAmount", 21, 32, _M, "Total debit entry dollar amount", "Cents"),
    _f("totalCreditEntryDollarAmount", 33, 44, _M, "Total credit entry dollar amount", "Cents"),
    _f("companyIdentification", 45, 54, _A, "Company identification"),
    _f("messageAuthenticationCode", 55, 73, _A, "Message authentication code"),
    _f("reserved", 74, 79, _A, "Reserved"),
    _f("originatingDfiIdentification", 80, 87, _N, "Originating DFI identification"),
    _f("batchNumber", 88, 94, _N, "Batch number"),
)

FILE_CONTROL: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("batchCount", 2, 7, _N, "Batch count"),
    _f("blockCount", 8, 13, _N, "Block count"),
    _f("entryAddendaCount", 14, 21, _N, "Entry/addenda count"),
    _f("entryHash", 22, 31, _N, "Entry hash"),
    _f("totalDebitEntryDollarAmount", 32, 43, _M, "Total debit entry dollar amount", "Cents"),
    _f("totalCreditEntryDollarAmount", 44, 55, _M, "Total credit entry dollar amount", "Cents"),
    _f("reserved", 56, 94, _A, "Reserved"),
)

#: ``05`` — payment-related information (PPD, CCD, WEB, TEL… remittance such as an ``RMR`` segment).
ADDENDA_05: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("addendaTypeCode", 2, 3, _N, "Addenda type code"),
    _f("paymentRelatedInformation", 4, 83, _A, "Payment-related information"),
    _f("addendaSequenceNumber", 84, 87, _N, "Addenda sequence number"),
    _f("entryDetailSequenceNumber", 88, 94, _N, "Entry detail sequence number"),
)

#: ``98`` — notification of change.
ADDENDA_98: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("addendaTypeCode", 2, 3, _N, "Addenda type code"),
    _f("changeCode", 4, 6, _A, "Change code"),
    _f("originalEntryTraceNumber", 7, 21, _N, "Original entry trace number"),
    _f("reserved", 22, 27, _A, "Reserved"),
    _f("originalReceivingDfiIdentification", 28, 35, _N, "Original receiving DFI identification"),
    _f("correctedData", 36, 64, _A, "Corrected data"),
    _f("reservedTrailing", 65, 79, _A, "Reserved"),
    _f("traceNumber", 80, 94, _N, "Trace number"),
)

#: ``99`` — return.
ADDENDA_99: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("addendaTypeCode", 2, 3, _N, "Addenda type code"),
    _f("returnReasonCode", 4, 6, _A, "Return reason code"),
    _f("originalEntryTraceNumber", 7, 21, _N, "Original entry trace number"),
    _f("dateOfDeath", 22, 27, _A, "Date of death", "YYMMDD; R14/R15 only"),
    _f("originalReceivingDfiIdentification", 28, 35, _N, "Original receiving DFI identification"),
    _f("addendaInformation", 36, 79, _A, "Addenda information"),
    _f("traceNumber", 80, 94, _N, "Trace number"),
)

#: An addenda type these tables do not model: its 91 characters after the type code are kept whole.
GENERIC_ADDENDA_LAYOUT: Tuple[NachaFieldSpec, ...] = (
    _f("recordTypeCode", 1, 1, _N, "Record type code"),
    _f("addendaTypeCode", 2, 3, _N, "Addenda type code"),
    _f("addendaContent", 4, 94, _A, "Addenda content", "Layout not modelled; kept whole"),
)

#: Record type code → its layout. The addenda record (``7``) is resolved by :func:`addenda_layout`.
RECORD_LAYOUTS: Dict[str, Tuple[NachaFieldSpec, ...]] = {
    "1": FILE_HEADER,
    "5": BATCH_HEADER,
    "6": ENTRY_DETAIL,
    "8": BATCH_CONTROL,
    "9": FILE_CONTROL,
}

#: Addenda type code → its layout.
ADDENDA_LAYOUTS: Dict[str, Tuple[NachaFieldSpec, ...]] = {
    "05": ADDENDA_05,
    "98": ADDENDA_98,
    "99": ADDENDA_99,
}

#: Record type code → display name.
RECORD_NAMES: Dict[str, str] = {
    "1": "File header",
    "5": "Batch header",
    "6": "Entry detail",
    "7": "Addenda",
    "8": "Batch control",
    "9": "File control",
}


def addenda_layout(addenda_type: str) -> Tuple[NachaFieldSpec, ...]:
    """Return the layout for an addenda type code, or the generic whole-content layout.

    Args:
        addenda_type: Positions 2-3 of a ``7`` record (``05``, ``98``, ``99``).

    Returns:
        The modelled layout, or :data:`GENERIC_ADDENDA_LAYOUT` for any other code.
    """
    return ADDENDA_LAYOUTS.get(addenda_type, GENERIC_ADDENDA_LAYOUT)


def layout_for(record: str) -> Tuple[NachaFieldSpec, ...]:
    """Return the layout a full-length record is read with.

    Args:
        record: A 94-character record.

    Returns:
        The record type's layout (the addenda type's, for a ``7`` record).

    Raises:
        KeyError: When the record type code is not one of ``1 5 6 7 8 9``.
    """
    code = record[:1]
    if code == "7":
        return addenda_layout(record[1:3])
    return RECORD_LAYOUTS[code]


def record_fields(record: str) -> List[Tuple[NachaFieldSpec, str]]:
    """Cut a full-length record into ``(field, value)`` pairs, in position order.

    Args:
        record: A 94-character record.

    Returns:
        Every field of the record's layout with its characters as written.
    """
    return [(spec, spec.slice(record)) for spec in layout_for(record)]


def credit_or_debit(transaction_code: str) -> Optional[str]:
    """Classify an entry's transaction code.

    The second digit carries the direction across every account type (checking ``2x``, savings
    ``3x``, general ledger ``4x``, loan ``5x``): ``1``–``4`` credit (return/NOC, live, prenote,
    zero-dollar), ``5``–``9`` debit.

    Args:
        transaction_code: Positions 2-3 of an entry detail record.

    Returns:
        ``"credit"``, ``"debit"``, or ``None`` for a code that is not two digits ending 1–9.
    """
    if len(transaction_code) != 2 or not transaction_code.isdigit():
        return None
    last = transaction_code[1]
    if last in "1234":
        return "credit"
    if last in "56789":
        return "debit"
    return None


def is_prenote(transaction_code: str) -> bool:
    """Whether the transaction code is a prenotification (``23``, ``28``, ``33``, ``38``, …)."""
    return len(transaction_code) == 2 and transaction_code.isdigit() and transaction_code[1] in "38"


def routing_check_digit(routing8: str) -> Optional[int]:
    """Compute the ABA check digit for an 8-digit routing prefix (weights 3, 7, 1).

    Args:
        routing8: The receiving DFI identification (entry positions 4-11).

    Returns:
        The check digit 0–9, or ``None`` when the input is not eight digits.
    """
    if len(routing8) != 8 or not routing8.isdigit():
        return None
    weights = (3, 7, 1, 3, 7, 1, 3, 7)
    total = sum(int(digit) * weight for digit, weight in zip(routing8, weights))
    return (10 - total % 10) % 10
