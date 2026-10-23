"""Shared XML intake for the IoT device-model readers — FMT-9.5 (#5472).

LwM2M object definitions (:mod:`app.lwm2m_parser`) and Matter cluster / device-type definitions
(:mod:`app.matter_parser`) are both small XML registries. This module holds the pieces the two
readers share, so they classify faults the same way:

* :func:`root_element_name` — the local name of a document's first element, read from the head
  only (comments removed), so a truncated or malformed file is still recognised by its sniffer;
* :func:`read_device_model_xml` — the hardened parse (:func:`app.secure_xml.parse_xml`: no DTDs,
  entities or external references) with the intake taxonomy code for each fault;
* :func:`identifier` — a source display name (``Sensor Value``, ``On/Off``) as the identifier the
  canonical keys use (``SensorValue``, ``OnOff``), the spelling both ecosystems' code generators use;
* :func:`child` / :func:`children` / :func:`child_text` — namespace-blind element helpers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import List, Optional

from .secure_xml import SecureXmlError, parse_xml

__all__ = [
    "DeviceModelXmlError",
    "child",
    "child_text",
    "children",
    "identifier",
    "local_name",
    "read_device_model_xml",
    "root_element_name",
]

#: Expat messages that mean the document stopped early rather than being mis-nested.
_TRUNCATION_MESSAGES = ("no element found", "unclosed token")

#: Characters that betray a non-UTF-8 upload decoded as UTF-8 (NULs from UTF-16, U+FFFD).
_ENCODING_FAULT_MARKERS = ("\x00", "\ufffd")

#: How much of a document the root sniff reads.
_SNIFF_WINDOW = 65536

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_DECLARATION_RE = re.compile(r"<[?!][^>]*>", re.S)
_ROOT_NAME_RE = re.compile(r"<\s*(?:[A-Za-z_][\w.-]*:)?([A-Za-z_][\w.-]*)(?=[\s>/])")
_WORD_RE = re.compile(r"[A-Za-z0-9]+")


class DeviceModelXmlError(ValueError):
    """An XML device-model document could not be read.

    Attributes:
        code: The intake taxonomy code (:mod:`app.intake_error_taxonomy`).
    """

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def local_name(tag: str) -> str:
    """An element tag without its ``{namespace}`` prefix."""
    return tag.rsplit("}", 1)[-1]


def root_element_name(text: Optional[str]) -> Optional[str]:
    """The local name of the first element of ``text``, or ``None`` when there is none.

    Only the head is examined, after removing comments and the XML declaration, so a truncated
    document still reports its root.

    Args:
        text: The candidate document.

    Returns:
        The root element's local name (``LWM2M``, ``configurator`` …), or ``None``.
    """
    if not text:
        return None
    head = _DECLARATION_RE.sub("", _COMMENT_RE.sub("", text[:_SNIFF_WINDOW])).lstrip("\ufeff \t\r\n")
    if not head.startswith("<"):
        return None
    match = _ROOT_NAME_RE.match(head)
    return match.group(1) if match else None


def read_device_model_xml(text: str, *, source_label: Optional[str], kind: str) -> ET.Element:
    """Parse one device-model document through the hardened XML parser.

    Args:
        text: The document text.
        source_label: The file name, used in messages.
        kind: What the document should be (``LwM2M object definition``), used in messages.

    Returns:
        The parsed root element.

    Raises:
        DeviceModelXmlError: ``INPUT_EMPTY`` for blank text, ``INPUT_ENCODING_INVALID`` for a
            non-UTF-8 upload (NULs, replacement characters or a byte-order mark), ``FORMAT_MISMATCH``
            for text that is not XML at all, ``INPUT_TRUNCATED`` for a document that ends early,
            ``INPUT_MALFORMED`` for any other syntax fault, and the hardened parser's own code for
            an unsafe construct, an oversized or an over-deep document.
    """
    where = f" ({source_label})" if source_label else ""
    if not text or not text.strip():
        raise DeviceModelXmlError(f"The {kind}{where} is empty", code="INPUT_EMPTY")
    if text.startswith("\ufeff") or any(marker in text[:4096] for marker in _ENCODING_FAULT_MARKERS):
        raise DeviceModelXmlError(
            f"The {kind}{where} is not UTF-8 text (NULs, replacement characters or a byte-order mark); "
            "save it as UTF-8 and import it again",
            code="INPUT_ENCODING_INVALID",
        )
    if not text.lstrip(" \t\r\n").startswith("<"):
        raise DeviceModelXmlError(f"The {kind}{where} is not XML", code="FORMAT_MISMATCH")
    try:
        return parse_xml(text, source_label=source_label)
    except SecureXmlError as exc:
        message = str(exc)
        if exc.code not in (None, "INPUT_MALFORMED"):
            raise DeviceModelXmlError(message, code=exc.code) from exc
        truncated = any(marker in message for marker in _TRUNCATION_MESSAGES) and not text.rstrip().endswith(">")
        if truncated:
            raise DeviceModelXmlError(f"The {kind}{where} ends early: {message}", code="INPUT_TRUNCATED") from exc
        raise DeviceModelXmlError(
            f"The {kind}{where} is not well-formed XML: {message}", code="INPUT_MALFORMED"
        ) from exc


def children(element: Optional[ET.Element], name: str) -> List[ET.Element]:
    """The direct children of ``element`` whose local name is ``name``."""
    if element is None:
        return []
    return [item for item in element if isinstance(item.tag, str) and local_name(item.tag) == name]


def child(element: Optional[ET.Element], name: str) -> Optional[ET.Element]:
    """The first direct child of ``element`` whose local name is ``name``."""
    found = children(element, name)
    return found[0] if found else None


def child_text(element: Optional[ET.Element], name: str) -> Optional[str]:
    """The stripped text of the first ``name`` child, or ``None`` when absent or blank."""
    found = child(element, name)
    if found is None or found.text is None:
        return None
    value = found.text.strip()
    return value or None


def identifier(name: str, *, fallback: str) -> str:
    """A display name as an identifier: words joined with their first letters upper-cased.

    ``Sensor Value`` → ``SensorValue``; ``On/Off`` → ``OnOff``; ``PkgName`` stays ``PkgName``. A
    name that starts with a digit is prefixed with ``_``.

    Args:
        name: The source name.
        fallback: The identifier to use when ``name`` has no letters or digits.

    Returns:
        The identifier.
    """
    words = _WORD_RE.findall(name or "")
    if not words:
        return fallback
    joined = "".join(word[:1].upper() + word[1:] for word in words)
    return f"_{joined}" if joined[0].isdigit() else joined
