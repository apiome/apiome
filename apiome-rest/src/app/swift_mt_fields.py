"""SWIFT MT field catalogue — FMT-6.3 (#5447).

The field structure of the MT categories the ``swift-mt`` adapter reads: MT103 (customer credit
transfer), MT202 / MT202 COV (financial institution transfer and its cover form), MT940 (customer
statement) and MT942 (interim transaction report). It is deliberately small and stated: each entry
says what a field's lines are made of, so the parser can model a field as its **components** — the
option letter, the account, the BIC, the currency and amount, the debit/credit mark, the code words
(``/INV/``, ``/OCMT/``) — instead of one opaque string.

A field whose content does not match its documented shape is kept as its lines and marked
not-well-formed; it is never refused for that alone, because this catalogue is a reading aid, not a
validator. The one exception is the last field of a text block that never terminates — there an
incomplete field is the evidence of truncation (see :mod:`app.swift_mt_parser`).

The MT → MX correspondences in :data:`MX_CORRESPONDENCE` are **notes**: the counterpart message SWIFT's
published MT and MX Equivalence Tables name for each MT. Nothing here translates a message, and
:data:`MX_CORRESPONDENCE_DISCLAIMER` is stated wherever a correspondence is shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

__all__ = [
    "MX_CORRESPONDENCE",
    "MX_CORRESPONDENCE_DISCLAIMER",
    "SUPPORTED_MESSAGE_TYPES",
    "CodeWord",
    "FieldReading",
    "MxCorrespondence",
    "NumberedLine",
    "field_name",
    "read_field",
]

#: Message types the adapter models, by the three-digit number block 2 carries.
SUPPORTED_MESSAGE_TYPES: Tuple[str, ...] = ("103", "202", "940", "942")


@dataclass(frozen=True)
class MxCorrespondence:
    """A documented MT → MX correspondence — a note, never a conversion.

    Attributes:
        mt: The MT message (``MT103``, ``MT202COV``).
        mx: The ISO 20022 message identifier (``pacs.008``).
        mx_name: Its name.
        basis: Where the correspondence is documented.
    """

    mt: str
    mx: str
    mx_name: str
    basis: str = "the SWIFT Standards MT and MX Equivalence Tables"


#: The statement every correspondence carries.
MX_CORRESPONDENCE_DISCLAIMER = (
    "This is a documented correspondence, recorded as a note. Apiome has not translated this "
    "message, has not checked it against the MX usage guidelines, and does not claim that a "
    "translation would be valid: field mappings, truncation and character-set rules, and data "
    "requirements of the MX message are outside what was read."
)

#: MT message → its documented MX counterpart.
MX_CORRESPONDENCE: Dict[str, MxCorrespondence] = {
    "MT103": MxCorrespondence("MT103", "pacs.008", "FI To FI Customer Credit Transfer"),
    "MT202": MxCorrespondence("MT202", "pacs.009", "Financial Institution Credit Transfer"),
    "MT202COV": MxCorrespondence(
        "MT202COV", "pacs.009 (COV)", "Financial Institution Credit Transfer, cover form"
    ),
    "MT940": MxCorrespondence("MT940", "camt.053", "Bank To Customer Statement"),
    "MT942": MxCorrespondence("MT942", "camt.052", "Bank To Customer Account Report"),
}

#: Field names by tag and option letter (``None`` for a field with no option).
_FIELD_NAMES: Dict[Tuple[str, Optional[str]], str] = {
    ("13", "C"): "Time Indication",
    ("13", "D"): "Date/Time Indication",
    ("20", None): "Transaction Reference Number",
    ("21", None): "Related Reference",
    ("23", "B"): "Bank Operation Code",
    ("23", "E"): "Instruction Code",
    ("25", None): "Account Identification",
    ("26", "T"): "Transaction Type Code",
    ("28", "C"): "Statement Number/Sequence Number",
    ("32", "A"): "Value Date/Currency/Interbank Settled Amount",
    ("33", "B"): "Currency/Instructed Amount",
    ("34", "F"): "Floor Limit Indicator",
    ("36", None): "Exchange Rate",
    ("50", None): "Ordering Customer",
    ("51", "A"): "Sending Institution",
    ("52", None): "Ordering Institution",
    ("53", None): "Sender's Correspondent",
    ("54", None): "Receiver's Correspondent",
    ("55", None): "Third Reimbursement Institution",
    ("56", None): "Intermediary Institution",
    ("57", None): "Account With Institution",
    ("58", None): "Beneficiary Institution",
    ("59", None): "Beneficiary Customer",
    ("60", "F"): "Opening Balance (first)",
    ("60", "M"): "Opening Balance (intermediate)",
    ("61", None): "Statement Line",
    ("62", "F"): "Closing Balance (final)",
    ("62", "M"): "Closing Balance (intermediate)",
    ("64", None): "Closing Available Balance",
    ("65", None): "Forward Available Balance",
    ("70", None): "Remittance Information",
    ("71", "A"): "Details of Charges",
    ("71", "F"): "Sender's Charges",
    ("71", "G"): "Receiver's Charges",
    ("72", None): "Sender to Receiver Information",
    ("77", "B"): "Regulatory Reporting",
    ("79", None): "Narrative",
    ("86", None): "Information to Account Owner",
    ("90", "C"): "Number and Sum of Credit Entries",
    ("90", "D"): "Number and Sum of Debit Entries",
}


def field_name(tag: str, option: Optional[str]) -> Optional[str]:
    """The documented name of a field, or ``None`` when the catalogue does not list it.

    Party fields (50–59) are named once for all their options.
    """
    return _FIELD_NAMES.get((tag, option)) or _FIELD_NAMES.get((tag, None))


@dataclass(frozen=True)
class NumberedLine:
    """One numbered line of an option-F party field (``1/ACME RETAIL BV``)."""

    number: str
    text: str


@dataclass(frozen=True)
class CodeWord:
    """One code word of a narrative field (``/INV/INV-10042``) — the qualifier and its text."""

    code: str
    text: str


@dataclass(frozen=True)
class FieldReading:
    """What the catalogue made of one field's content.

    Attributes:
        format: The shape the content was read as (``currency_amount``, ``party_bic``…), or
            ``lines`` when the catalogue has no shape for the field.
        components: Named scalar components, in reading order (``currency`` → ``EUR``).
        lines: Free lines (name and address, narrative lines without a code word).
        numbered_lines: Option-F numbered lines.
        code_words: Code words with their qualifier.
        well_formed: Whether the content matched its documented shape. ``False`` means the content
            is kept as ``lines`` only.
    """

    format: str
    components: Tuple[Tuple[str, str], ...] = ()
    lines: Tuple[str, ...] = ()
    numbered_lines: Tuple[NumberedLine, ...] = ()
    code_words: Tuple[CodeWord, ...] = ()
    well_formed: bool = True


_AMOUNT = r"(?P<amount>\d[\d,]*)"
_CODEWORD_RE = re.compile(r"^/(?P<code>[A-Z0-9]{1,8})/(?P<text>.*)$")
_NUMBERED_RE = re.compile(r"^(?P<number>\d)/(?P<text>.*)$")
_BIC_RE = re.compile(r"^[A-Z0-9]{6,14}$")

#: Single-line shapes: field format name → pattern whose named groups are the components.
_SINGLE_LINE: Dict[str, re.Pattern] = {
    "reference": re.compile(r"^(?P<reference>.{1,16})$"),
    "code": re.compile(r"^(?P<code>[A-Z0-9]{3,4})$"),
    "instruction": re.compile(r"^(?P<code>[A-Z0-9]{4})(?:/(?P<information>.{1,30}))?$"),
    "account": re.compile(r"^(?P<account>.{1,35})$"),
    "time_indication": re.compile(
        r"^/(?P<code>[A-Z]{1,8})/(?P<time>\d{4})(?P<sign>[+-])(?P<offset>\d{4})$"
    ),
    "datetime_indication": re.compile(
        r"^(?P<date>\d{6})(?P<time>\d{4})(?P<sign>[+-])(?P<offset>\d{4})$"
    ),
    "statement_number": re.compile(
        r"^(?P<statementNumber>\d{1,5})(?:/(?P<sequenceNumber>\d{1,5}))?$"
    ),
    "date_currency_amount": re.compile(r"^(?P<date>\d{6})(?P<currency>[A-Z]{3})" + _AMOUNT + "$"),
    "currency_amount": re.compile(r"^(?P<currency>[A-Z]{3})" + _AMOUNT + "$"),
    "floor_limit": re.compile(r"^(?P<currency>[A-Z]{3})(?P<mark>[DC])?" + _AMOUNT + "$"),
    "rate": re.compile(r"^(?P<rate>\d[\d,]*)$"),
    "balance": re.compile(
        r"^(?P<mark>[DC])(?P<date>\d{6})(?P<currency>[A-Z]{3})" + _AMOUNT + "$"
    ),
    "entry_summary": re.compile(r"^(?P<count>\d{1,5})(?P<currency>[A-Z]{3})" + _AMOUNT + "$"),
}

_STATEMENT_LINE_RE = re.compile(
    r"^(?P<valueDate>\d{6})(?P<entryDate>\d{4})?(?P<mark>R?[DC])(?P<fundsCode>[A-Z])?"
    + _AMOUNT
    + r"(?P<transactionType>[NFS][A-Z0-9]{3})(?P<customerReference>.{1,16}?)"
    r"(?://(?P<bankReference>.{1,16}))?$"
)

#: Tag (and option) → shape. Party fields are resolved by option in :func:`_party_format`.
_FORMATS: Dict[Tuple[str, Optional[str]], str] = {
    ("13", "C"): "time_indication",
    ("13", "D"): "datetime_indication",
    ("20", None): "reference",
    ("21", None): "reference",
    ("23", "B"): "code",
    ("23", "E"): "instruction",
    ("25", None): "account",
    ("26", "T"): "code",
    ("28", "C"): "statement_number",
    ("32", "A"): "date_currency_amount",
    ("33", "B"): "currency_amount",
    ("34", "F"): "floor_limit",
    ("36", None): "rate",
    ("60", "F"): "balance",
    ("60", "M"): "balance",
    ("61", None): "statement_line",
    ("62", "F"): "balance",
    ("62", "M"): "balance",
    ("64", None): "balance",
    ("65", None): "balance",
    ("70", None): "narrative",
    ("71", "A"): "code",
    ("71", "F"): "currency_amount",
    ("71", "G"): "currency_amount",
    ("72", None): "narrative",
    ("77", "B"): "narrative",
    ("79", None): "narrative",
    ("86", None): "narrative",
    ("90", "C"): "entry_summary",
    ("90", "D"): "entry_summary",
}

#: Party tags, whose shape depends on the option letter alone.
_PARTY_TAGS = frozenset({"50", "51", "52", "53", "54", "55", "56", "57", "58", "59"})


def _party_format(option: Optional[str]) -> str:
    """The shape of a party field by its option letter."""
    return {
        "A": "party_bic",
        "B": "party_location",
        "C": "party_account",
        "D": "party_name_address",
        "F": "party_structured",
        "K": "party_name_address",
        None: "party_name_address",
    }.get(option, "lines")


def _format_for(tag: str, option: Optional[str]) -> str:
    if tag in _PARTY_TAGS and (tag, option) not in _FORMATS:
        return _party_format(option)
    return _FORMATS.get((tag, option), "lines")


def _components(match: re.Match) -> Tuple[Tuple[str, str], ...]:
    return tuple((name, value) for name, value in match.groupdict().items() if value is not None)


def _split_account(lines: List[str]) -> Tuple[Optional[str], List[str]]:
    """Take a leading ``/account`` (or ``/D/account``-style party identifier) line off a party field."""
    if lines and lines[0].startswith("/"):
        return lines[0][1:], lines[1:]
    return None, lines


def _read_party(format_name: str, lines: List[str]) -> Optional[FieldReading]:
    """Read a party field (50–59) by its option's shape, or ``None`` when it does not match."""
    account, rest = _split_account(lines)
    account_component = (("account", account),) if account is not None else ()
    if format_name == "party_bic":
        if len(rest) == 1 and _BIC_RE.match(rest[0]):
            return FieldReading(format_name, account_component + (("bic", rest[0]),))
        return None
    if format_name == "party_account":
        return FieldReading(format_name, account_component) if account is not None and not rest else None
    if format_name == "party_location":
        if len(rest) <= 1 and (account is not None or rest):
            location = (("location", rest[0]),) if rest else ()
            return FieldReading(format_name, account_component + location)
        return None
    if format_name == "party_structured":
        if account is None and lines and "/" in lines[0]:
            account, rest = lines[0], lines[1:]
            account_component = (("partyIdentifier", account),)
        numbered = [_NUMBERED_RE.match(line) for line in rest]
        if not rest or not all(numbered):
            return None
        return FieldReading(
            format_name,
            account_component,
            numbered_lines=tuple(NumberedLine(m["number"], m["text"]) for m in numbered if m),
        )
    # Name and address (options D, K, and 59 with no option): at least one name line.
    if not rest or len(rest) > 4:
        return None
    return FieldReading(format_name, account_component, lines=tuple(rest))


def _read_narrative(lines: List[str]) -> FieldReading:
    """Read a narrative field: code-word lines keep their qualifier, the rest stay lines.

    A line that does not open a code word continues the previous code word's text when there is
    one (``/REMI/`` text wraps onto the next line), and is a free line otherwise.
    """
    words: List[CodeWord] = []
    free: List[str] = []
    for line in lines:
        match = _CODEWORD_RE.match(line)
        if match:
            words.append(CodeWord(match["code"], match["text"]))
        elif words and not free:
            words[-1] = CodeWord(words[-1].code, words[-1].text + "\n" + line)
        else:
            free.append(line)
    return FieldReading("narrative", lines=tuple(free), code_words=tuple(words))


def _read_supplementary(line: str) -> Tuple[CodeWord, ...]:
    """Read ``/OCMT/EUR12500,00/CHGS/EUR7,50/`` into its code words."""
    words: List[CodeWord] = []
    for match in re.finditer(r"/(?P<code>[A-Z]{4})/(?P<text>[^/]*)", line):
        words.append(CodeWord(match["code"], match["text"]))
    return tuple(words)


def _read_statement_line(lines: List[str]) -> Optional[FieldReading]:
    match = _STATEMENT_LINE_RE.match(lines[0]) if lines else None
    if match is None or len(lines) > 2:
        return None
    supplementary = lines[1] if len(lines) == 2 else None
    words = _read_supplementary(supplementary) if supplementary else ()
    return FieldReading(
        "statement_line",
        _components(match),
        lines=(supplementary,) if supplementary and not words else (),
        code_words=words,
    )


_READERS: Dict[str, Callable[[List[str]], Optional[FieldReading]]] = {
    "narrative": _read_narrative,
    "statement_line": _read_statement_line,
}


def read_field(tag: str, option: Optional[str], lines: List[str]) -> FieldReading:
    """Read one field's content lines into components.

    Args:
        tag: The two-digit tag (``50``).
        option: The option letter (``K``), or ``None``.
        lines: The content lines, without the ``:tag:`` prefix.

    Returns:
        The reading. A content that does not match its documented shape comes back as ``lines`` with
        ``well_formed`` false — kept, never refused.
    """
    format_name = _format_for(tag, option)
    reading: Optional[FieldReading]
    if format_name in _SINGLE_LINE:
        match = _SINGLE_LINE[format_name].match(lines[0]) if len(lines) == 1 else None
        reading = FieldReading(format_name, _components(match)) if match else None
    elif format_name.startswith("party_"):
        reading = _read_party(format_name, lines)
    elif format_name in _READERS:
        reading = _READERS[format_name](lines)
    else:
        return FieldReading("lines", lines=tuple(lines))
    if reading is None:
        return FieldReading(format_name, lines=tuple(lines), well_formed=False)
    return reading
