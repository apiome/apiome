"""SEPA recognition on the ISO 20022 adapter — FMT-6.6 (#5450).

SEPA credit transfers and direct debits are ISO 20022 messages: a SEPA ``pain.001`` is an ISO 20022
``pain.001`` used under the European Payments Council's rulebooks. So SEPA is a **profile** on the
shipped ``iso20022`` adapter, not a parser of its own — the same move the EDI dialect profiles make
on the EDIFACT engine (:mod:`app.edi_dialect_profiles`), with the same :class:`DialectProfile` /
:class:`ProfileMatch` vocabulary:

* :func:`sepa_match` recognises a SEPA payment message from the message-definition identifier its
  ``<Document>`` namespace declares (``urn:iso:std:iso:20022:tech:xsd:pain.001.001.09``) and records
  that identifier as evidence. The normalizer stores the match under the canonical
  ``format_profile`` extras, so the import pipeline lifts it into the revision's provenance
  (``format_metadata.formatProfile``) beside ``iso20022_message_id``.
* :func:`check_sepa_document` applies the two structural rules every one of those messages carries
  in its own message definition, whatever the rulebook: a payment block must carry at least one
  transaction, and the message-definition version must be one Apiome recognises.

Recognised messages: ``pain.001`` (customer credit transfer initiation — SEPA Credit Transfer),
``pain.008`` (customer direct debit initiation — SEPA Direct Debit) and ``pacs.008`` (FI-to-FI
customer credit transfer — interbank SCT). Other ISO 20022 messages (``camt.053``, ``pain.002``…)
import exactly as before, with no profile.

What the profile does not do: the EPC rulebooks and implementation guidelines are not consulted —
the EUR-only rule, character-set restrictions, IBAN/BIC validity, field-length restrictions and the
scheme's business rules are not evaluated, so a structurally valid message is never presented as a
rulebook-conformant one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from .edi_dialect_profiles import DialectProfile, ProfileMatch
from .iso20022_parser import Iso20022Document, Iso20022Element, Iso20022ParseError

__all__ = [
    "SEPA",
    "SEPA_MESSAGES",
    "SepaMessage",
    "check_sepa_document",
    "parse_message_id",
    "sepa_match",
    "sepa_message",
    "sepa_profile_extras",
]


@dataclass(frozen=True)
class SepaMessage:
    """One ISO 20022 message family SEPA uses, and the structure its definition requires.

    Attributes:
        family: ``pain.001``, ``pain.008`` or ``pacs.008``.
        name: The message definition's name.
        scheme: The SEPA scheme it carries.
        container: The repeating payment block that must carry transactions (``PmtInf``), or
            ``None`` when transactions sit directly under the business element (``pacs.008``).
        transaction: The transaction element (``CdtTrfTxInf``, ``DrctDbtTxInf``).
        max_version: The highest message-definition version Apiome recognises for the family.
    """

    family: str
    name: str
    scheme: str
    container: Optional[str]
    transaction: str
    max_version: int


#: Family → its recognition facts. ``max_version`` is a stated ceiling reviewed against the ISO 20022
#: message catalogue; a version above it (``pain.001.001.99``) is refused as unrecognised rather
#: than read as if it were a known definition. Raise a ceiling when the catalogue publishes a new
#: version.
SEPA_MESSAGES: Dict[str, SepaMessage] = {
    "pain.001": SepaMessage(
        family="pain.001",
        name="Customer credit transfer initiation",
        scheme="SEPA Credit Transfer (SCT)",
        container="PmtInf",
        transaction="CdtTrfTxInf",
        max_version=12,
    ),
    "pain.008": SepaMessage(
        family="pain.008",
        name="Customer direct debit initiation",
        scheme="SEPA Direct Debit (SDD Core / B2B)",
        container="PmtInf",
        transaction="DrctDbtTxInf",
        max_version=11,
    ),
    "pacs.008": SepaMessage(
        family="pacs.008",
        name="FI-to-FI customer credit transfer",
        scheme="SEPA Credit Transfer (SCT), interbank",
        container=None,
        transaction="CdtTrfTxInf",
        max_version=13,
    ),
}

#: The SEPA profile: what it is, how it is recognised and where its modelling stops.
SEPA = DialectProfile(
    key="sepa",
    label="SEPA",
    engine="iso20022",
    governing_body="European Payments Council (EPC)",
    message_set=tuple(sorted(SEPA_MESSAGES)),
    code_lists=("ISO 20022 external code sets", "EPC rulebook codes (local instrument, sequence type)"),
    recognition=(
        "Applied when the ISO 20022 `<Document>` namespace names a pain.001, pain.008 or pacs.008 "
        "message definition; the full identifier (`pain.001.001.09`) is recorded as the message id."
    ),
    boundaries=(
        "The EPC rulebooks and implementation guidelines are not consulted: the EUR-only rule, the "
        "SEPA character set, IBAN/BIC validity and field-length restrictions are not evaluated.",
        "A payment block with no transactions, and a message-definition version above the "
        "recognised ceiling, are refused; nothing else is.",
    ),
)

_MESSAGE_ID_RE = re.compile(
    r"^(?P<area>[a-z]{4})\.(?P<number>\d{3})\.(?P<variant>\d{3})\.(?P<version>\d{2})$"
)


def parse_message_id(message_id: str) -> Optional[Tuple[str, str, int]]:
    """Split a message-definition identifier into ``(family, variant, version)``.

    Args:
        message_id: ``pain.001.001.09``.

    Returns:
        ``("pain.001", "001", 9)``, or ``None`` when the identifier is not in that shape.
    """
    match = _MESSAGE_ID_RE.match(message_id.strip().lower())
    if match is None:
        return None
    family = f"{match['area']}.{match['number']}"
    return family, match["variant"], int(match["version"])


def sepa_message(message_id: str) -> Optional[SepaMessage]:
    """Return the SEPA family a message-definition identifier belongs to, or ``None``."""
    parts = parse_message_id(message_id)
    return SEPA_MESSAGES.get(parts[0]) if parts else None


def sepa_match(message_id: str) -> Optional[ProfileMatch]:
    """Recognise a SEPA payment message from its message-definition identifier.

    Args:
        message_id: The identifier the ``<Document>`` namespace declares.

    Returns:
        The SEPA :class:`ProfileMatch` with the identifier as evidence, or ``None`` for any other
        message.
    """
    message = sepa_message(message_id)
    if message is None:
        return None
    return ProfileMatch(
        SEPA,
        (
            f"The `<Document>` namespace names message definition {message_id} "
            f"({message.name}), which carries the {message.scheme} scheme.",
        ),
    )


def sepa_profile_extras(message_id: str) -> Optional[Dict[str, object]]:
    """The ``format_profile`` extras for a SEPA message, with its message id; ``None`` otherwise."""
    match = sepa_match(message_id)
    if match is None:
        return None
    message = SEPA_MESSAGES[parse_message_id(message_id)[0]]
    extras = match.extras()
    extras.update({"message_id": message_id, "message_family": message.family, "scheme": message.scheme})
    return extras


def _children(element: Iso20022Element, tag: str):
    return [child for child in element.children if child.tag == tag]


def check_sepa_document(document: Iso20022Document) -> None:
    """Refuse a SEPA payment message its own message definition would refuse.

    A document whose message is not a SEPA family is left alone.

    Args:
        document: The parsed ISO 20022 document.

    Raises:
        Iso20022ParseError: ``FORMAT_VERSION_UNSUPPORTED`` for a version above the family's
            recognised ceiling (or ``00``); ``INPUT_SEMANTIC_INVALID`` for a payment block — or a
            ``pacs.008`` business element — that carries no transaction.
    """
    parts = parse_message_id(document.message_id)
    message = SEPA_MESSAGES.get(parts[0]) if parts else None
    if message is None:
        return
    version = parts[2]
    if version < 1 or version > message.max_version:
        raise Iso20022ParseError(
            f"{document.message_id} is not a recognised {message.family} message-definition version "
            f"(versions 01–{message.max_version:02d} are recognised).",
            code="FORMAT_VERSION_UNSUPPORTED",
        )
    business = document.root.children[0]
    blocks = _children(business, message.container) if message.container else [business]
    if message.container and not blocks:
        raise Iso20022ParseError(
            f"{document.message_id} carries no {message.container} payment block.",
            code="INPUT_SEMANTIC_INVALID",
        )
    for index, block in enumerate(blocks):
        if not _children(block, message.transaction):
            where = f"{message.container} {index + 1}" if message.container else business.tag
            raise Iso20022ParseError(
                f"{document.message_id}: {where} carries no {message.transaction} transaction; the "
                "message definition requires at least one.",
                code="INPUT_SEMANTIC_INVALID",
            )
