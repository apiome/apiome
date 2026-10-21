"""NCPDP SCRIPT reader — FMT-6.8 (#5452).

Reads an NCPDP SCRIPT e-prescribing document — a ``Message`` (or a ``Messages`` batch of them) in
the ``http://www.ncpdp.org/schema/SCRIPT`` namespace — into :class:`ScriptMessage` records:

.. code-block:: text

    Message  version / release (10.x) · TransactionVersion (2017071 and later)
      Header   To · From · MessageID · RelatesToMessageID · SentTime · …
      Body     exactly one transaction element: NewRx · RxFill · RxChangeRequest · Status · Error …

The **transaction type** of each message is the local name of its ``Body``'s one child, detected per
message, never per file. A name outside :data:`SCRIPT_TRANSACTIONS` is still read and recorded as
not recognised. The version attributes are recorded as the sender's claim: one element grammar is
read for every SCRIPT version and no implementation guide is consulted.

XML goes through :func:`app.secure_xml.parse_xml`. **Errors** are :class:`ScriptParseError`:

* ``INPUT_TRUNCATED`` — the XML ends before the document does;
* ``INPUT_MALFORMED`` — the XML is not well formed;
* ``FORMAT_MISMATCH`` — the text is not XML, or its root is not a SCRIPT ``Message``/``Messages``;
* ``INPUT_SEMANTIC_INVALID`` — a message without ``Header`` or ``Body``, a ``Body`` that carries no
  transaction (or more than one), or a ``Messages`` batch with no message in it.

A guard code from :mod:`app.secure_xml` is kept, and an encoding fault is refused code-less so the
import pipeline's encoding rule names it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "SCRIPT_NAMESPACE",
    "SCRIPT_TRANSACTIONS",
    "ScriptDocument",
    "ScriptMessage",
    "ScriptParseError",
    "element_children",
    "is_script",
    "local_name",
    "parse_script",
]

#: The SCRIPT XML namespace.
SCRIPT_NAMESPACE = "http://www.ncpdp.org/schema/SCRIPT"
_NS = "{" + SCRIPT_NAMESPACE + "}"

#: Transaction element names the reader recognises (SCRIPT 10.x and 2017071-era names).
SCRIPT_TRANSACTIONS: Tuple[str, ...] = (
    "NewRx",
    "NewRxRequest",
    "NewRxResponseDenied",
    "RxChangeRequest",
    "RxChangeResponse",
    "RxRenewalRequest",
    "RxRenewalResponse",
    "RefillRequest",
    "RefillResponse",
    "RxFill",
    "RxFillIndicatorChange",
    "CancelRx",
    "CancelRxResponse",
    "RxHistoryRequest",
    "RxHistoryResponse",
    "RxTransferRequest",
    "RxTransferResponse",
    "RxTransferConfirm",
    "Census",
    "Resupply",
    "DrugAdministration",
    "PAInitiationRequest",
    "PAInitiationResponse",
    "PARequest",
    "PAResponse",
    "PAAppealRequest",
    "PAAppealResponse",
    "PACancelRequest",
    "PACancelResponse",
    "REMSInitiationRequest",
    "REMSInitiationResponse",
    "REMSRequest",
    "REMSResponse",
    "Status",
    "Error",
    "Verify",
)

_TRUNCATION_MESSAGES = ("no element found", "unclosed token")
_ENCODING_FAULT_MARKERS = ("\x00", "�")
_ENCODING_WINDOW = 1024
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_FIRST_ELEMENT_RE = re.compile(r"<(?![?!])")
_ROOT_RE = re.compile(r"<(?:[A-Za-z_][\w.-]*:)?(Messages?)\b[^>]*?www\.ncpdp\.org/schema/SCRIPT", re.S)
_SNIFF_WINDOW = 65536


class ScriptParseError(ValueError):
    """Raised when text is not a readable SCRIPT document.

    Attributes:
        code: The intake-taxonomy code; ``None`` for an encoding fault, which the import pipeline
            names more precisely than the parser can.
    """

    def __init__(self, message: str, *, code: Optional[str]) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class ScriptMessage:
    """One SCRIPT message and the facts read off its header.

    Attributes:
        element: The ``Message`` element.
        path: Where it sits (``Message``, ``Messages/Message[2]``, ``status.xml:Message``).
        transaction: The ``Body``'s transaction element.
        transaction_type: Its local name (``NewRx``).
        recognized: Whether the name is in :data:`SCRIPT_TRANSACTIONS`.
        version: The ``version`` attribute (``010``), when written.
        release: The ``release`` attribute (``006``), when written.
        transaction_version: The ``TransactionVersion`` attribute (``2017071``), when written.
        message_id: The header's ``MessageID``.
        relates_to: The header's ``RelatesToMessageID``, when written.
        source_label: The file the message came from, when known.
    """

    element: ET.Element
    path: str
    transaction: ET.Element
    transaction_type: str
    recognized: bool
    version: Optional[str]
    release: Optional[str]
    transaction_version: Optional[str]
    message_id: Optional[str]
    relates_to: Optional[str]
    source_label: Optional[str] = None

    @property
    def version_label(self) -> Optional[str]:
        """The version the message claims (``10.6``, ``2017071``), or ``None``."""
        if self.transaction_version:
            return self.transaction_version
        if self.version and self.release and self.version.isdigit() and self.release.isdigit():
            return f"{int(self.version)}.{int(self.release)}"
        return None


@dataclass
class ScriptDocument:
    """A parsed SCRIPT document (or the documents of a fileset).

    Attributes:
        raw: The root document's text.
        source_label: The root file name, when known.
        root_name: ``Message`` or ``Messages``.
        messages: Every message in document order (root first, then fileset members).
        members: The fileset members read beside the root, in order.
    """

    raw: str
    source_label: Optional[str]
    root_name: str
    messages: List[ScriptMessage]
    members: List[str] = field(default_factory=list)


def local_name(element: ET.Element) -> str:
    """The element's local name, without its namespace."""
    tag = element.tag if isinstance(element.tag, str) else ""
    return tag.rsplit("}", 1)[-1]


def element_children(element: ET.Element) -> List[ET.Element]:
    """The element's child elements (comments and processing instructions skipped)."""
    return [child for child in element if isinstance(child.tag, str)]


def _label(source_label: Optional[str]) -> str:
    return f" ({source_label})" if source_label else ""


def is_script(text: Optional[str]) -> Optional[str]:
    """Return ``Message`` or ``Messages`` when ``text`` opens with a SCRIPT root element.

    Only the first start tag is examined, so a truncated or malformed document is still claimed and
    the parser names the fault. Never raises.
    """
    if not text or "www.ncpdp.org/schema/SCRIPT" not in text:
        return None
    head = _COMMENT_RE.sub("", text[:_SNIFF_WINDOW])
    start = _FIRST_ELEMENT_RE.search(head)
    if start is None:
        return None
    end = head.find(">", start.start())
    match = _ROOT_RE.match(head[start.start() : end + 1 if end >= 0 else len(head)])
    return match.group(1) if match else None


def _parse_root(text: str, source_label: Optional[str]) -> ET.Element:
    """Parse XML safely, mapping parser messages onto intake codes."""
    head = text[:_ENCODING_WINDOW] if text else ""
    if any(marker in head for marker in _ENCODING_FAULT_MARKERS):
        raise ScriptParseError(f"Document{_label(source_label)} is not valid text in its declared encoding.", code=None)
    if text.strip() and not text.lstrip("﻿ \t\r\n").startswith("<"):
        raise ScriptParseError(
            f"Document{_label(source_label)} is not XML, so it cannot be an NCPDP SCRIPT message.",
            code="FORMAT_MISMATCH",
        )
    try:
        return parse_xml(text, source_label=source_label)
    except SecureXmlError as exc:
        message = str(exc)
        if exc.code not in (None, "INPUT_MALFORMED"):
            raise ScriptParseError(message, code=exc.code) from exc
        truncated = any(marker in message for marker in _TRUNCATION_MESSAGES) and not text.rstrip().endswith(">")
        raise ScriptParseError(
            message + (" The document was truncated." if truncated else ""),
            code="INPUT_TRUNCATED" if truncated else "INPUT_MALFORMED",
        ) from exc


def _child(element: ET.Element, name: str) -> Optional[ET.Element]:
    return next((child for child in element_children(element) if child.tag == _NS + name), None)


def _text(element: Optional[ET.Element]) -> Optional[str]:
    if element is None:
        return None
    return (element.text or "").strip() or None


def _message(element: ET.Element, path: str, source_label: Optional[str]) -> ScriptMessage:
    """Read one ``Message``: its header facts and its one transaction."""
    where = f"{path}{_label(source_label)}"
    header = _child(element, "Header")
    body = _child(element, "Body")
    missing = [name for name, found in (("Header", header), ("Body", body)) if found is None]
    if missing:
        raise ScriptParseError(
            f"SCRIPT message {where} is missing its {' and '.join(missing)}.",
            code="INPUT_SEMANTIC_INVALID",
        )
    assert header is not None and body is not None
    transactions = element_children(body)
    if len(transactions) != 1:
        found = ", ".join(local_name(item) for item in transactions)
        raise ScriptParseError(
            f"SCRIPT message {where} has a Body carrying "
            + (
                "no transaction element (NewRx, RxFill, Status …)."
                if not transactions
                else f"{len(transactions)} transaction elements ({found}); a Body carries one."
            ),
            code="INPUT_SEMANTIC_INVALID",
        )
    transaction = transactions[0]
    name = local_name(transaction)
    return ScriptMessage(
        element=element,
        path=path,
        transaction=transaction,
        transaction_type=name,
        recognized=name in SCRIPT_TRANSACTIONS,
        version=element.get("version"),
        release=element.get("release"),
        transaction_version=element.get("TransactionVersion"),
        message_id=_text(_child(header, "MessageID")),
        relates_to=_text(_child(header, "RelatesToMessageID")),
        source_label=source_label,
    )


def _messages(root: ET.Element, source_label: Optional[str], prefix: str = "") -> List[ScriptMessage]:
    """Every message under a ``Message`` or ``Messages`` root."""
    name = local_name(root)
    if root.tag == _NS + "Message":
        return [_message(root, f"{prefix}Message", source_label)]
    if root.tag != _NS + "Messages":
        raise ScriptParseError(
            f"Document{_label(source_label)} is not NCPDP SCRIPT: its <{name}> root is not a Message or "
            f"Messages element in the {SCRIPT_NAMESPACE} namespace.",
            code="FORMAT_MISMATCH",
        )
    items = [child for child in element_children(root) if child.tag == _NS + "Message"]
    if not items:
        raise ScriptParseError(f"SCRIPT batch{_label(source_label)} carries no Message.", code="INPUT_SEMANTIC_INVALID")
    return [
        _message(item, f"{prefix}Messages/Message[{index}]", source_label) for index, item in enumerate(items, start=1)
    ]


def parse_script(
    text: str,
    *,
    source_label: Optional[str] = None,
    members: Optional[List[Tuple[str, str]]] = None,
) -> ScriptDocument:
    """Parse a SCRIPT document, and optionally the SCRIPT members of its fileset.

    Args:
        text: The root document's text.
        source_label: Its file name, used in errors.
        members: ``(path, text)`` of further SCRIPT documents read as part of the same conversation,
            in order; their messages follow the root's, with paths prefixed by the member path.

    Returns:
        The :class:`ScriptDocument`.

    Raises:
        ScriptParseError: When the root or a member is not a readable SCRIPT document.
    """
    root = _parse_root(text, source_label)
    messages = _messages(root, source_label)
    member_paths: List[str] = []
    for path, member_text in members or ():
        member_root = _parse_root(member_text, path)
        messages.extend(_messages(member_root, path, prefix=f"{path}:"))
        member_paths.append(path)
    return ScriptDocument(
        raw=text,
        source_label=source_label,
        root_name=local_name(root),
        messages=messages,
        members=member_paths,
    )
