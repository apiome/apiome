"""NCPDP parser — FMT-6.8 (#5452).

One adapter, two sub-formats, told apart by their first bytes:

* **SCRIPT** (e-prescribing) — XML whose root is a ``Message`` or ``Messages`` element in the
  SCRIPT namespace; read by :mod:`app.ncpdp_script`.
* **Telecommunication D.0** (pharmacy claims) — a 56-character fixed transaction header followed by
  separator-delimited ``AM`` segments; read by :mod:`app.ncpdp_telecom`.

:func:`parse_ncpdp` returns an :class:`NcpdpDocument` holding exactly one of the two, and every
refusal is an :class:`NcpdpParseError` carrying the sub-reader's intake-taxonomy code. Text that is
neither sub-format is ``FORMAT_MISMATCH``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

from .ncpdp_script import ScriptDocument, ScriptParseError, is_script, parse_script
from .ncpdp_telecom import (
    TelecomParseError,
    TelecomTransmission,
    has_telecom_header,
    is_telecom,
    parse_telecom,
)

__all__ = [
    "NcpdpDocument",
    "NcpdpParseError",
    "SUB_FORMAT_SCRIPT",
    "SUB_FORMAT_TELECOM",
    "is_ncpdp",
    "parse_ncpdp",
    "parse_ncpdp_fileset",
]

SUB_FORMAT_SCRIPT = "script"
SUB_FORMAT_TELECOM = "telecom"


class NcpdpParseError(ValueError):
    """Raised when text is not a readable NCPDP SCRIPT or Telecom document.

    Attributes:
        code: The intake-taxonomy code; ``None`` for an encoding fault the pipeline names itself.
    """

    def __init__(self, message: str, *, code: Optional[str]) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class NcpdpDocument:
    """A parsed NCPDP document: a SCRIPT document or a Telecom transmission, never both.

    Attributes:
        sub_format: ``script`` or ``telecom``.
        raw: The (root) document text.
        source_label: The file name, when known.
        script: The SCRIPT document, for ``script``.
        telecom: The Telecom transmission, for ``telecom``.
    """

    sub_format: str
    raw: str
    source_label: Optional[str]
    script: Optional[ScriptDocument] = None
    telecom: Optional[TelecomTransmission] = None


def is_ncpdp(text: Optional[str]) -> Optional[str]:
    """Return the sub-format ``text`` opens as (``script`` / ``telecom``), or ``None``. Never raises."""
    if not text:
        return None
    if is_script(text):
        return SUB_FORMAT_SCRIPT
    if is_telecom(text):
        return SUB_FORMAT_TELECOM
    return None


def _label(source_label: Optional[str]) -> str:
    return f" ({source_label})" if source_label else ""


def _looks_like_xml(text: str) -> bool:
    return text.lstrip("﻿ \t\r\n").startswith("<") or "\x00" in text[:64]


def parse_ncpdp(text: str, *, source_label: Optional[str] = None) -> NcpdpDocument:
    """Parse an NCPDP SCRIPT document or Telecom D.0 transmission.

    XML-shaped text (and text whose encoding is broken, which is how a UTF-16 SCRIPT file arrives)
    goes to the SCRIPT reader, which refuses a non-SCRIPT root as ``FORMAT_MISMATCH``. Text that opens
    like a Telecom header — even one cut short, or with no segment after it — goes to the Telecom
    reader, which names the fault. Anything else is ``FORMAT_MISMATCH``.

    Args:
        text: The document text.
        source_label: The file name, used in errors.

    Returns:
        The :class:`NcpdpDocument`.

    Raises:
        NcpdpParseError: With the sub-reader's code.
    """
    try:
        if _looks_like_xml(text) or "�" in text[:1024]:
            script = parse_script(text, source_label=source_label)
            return NcpdpDocument(SUB_FORMAT_SCRIPT, text, source_label, script=script)
        if has_telecom_header(text):
            telecom = parse_telecom(text, source_label=source_label)
            return NcpdpDocument(SUB_FORMAT_TELECOM, text, source_label, telecom=telecom)
    except (ScriptParseError, TelecomParseError) as exc:
        raise NcpdpParseError(str(exc), code=exc.code) from exc
    if not text.strip():
        raise NcpdpParseError(f"Document{_label(source_label)} is empty.", code="INPUT_EMPTY")
    raise NcpdpParseError(
        f"Document{_label(source_label)} is neither an NCPDP SCRIPT message (XML in the "
        "http://www.ncpdp.org/schema/SCRIPT namespace) nor a Telecommunication D.0 transmission "
        "(a 56-character transaction header followed by AM segments).",
        code="FORMAT_MISMATCH",
    )


def parse_ncpdp_fileset(members: Mapping[str, str], root: str, *, source_label: Optional[str] = None) -> NcpdpDocument:
    """Parse a fileset from its root.

    A SCRIPT root reads every other SCRIPT member beside it, in path order, as one conversation —
    a ``Status`` or ``RxChangeResponse`` only says which prescription it answers through
    ``RelatesToMessageID``, so the pair is read together. Members that are not SCRIPT are left out.
    A Telecom root is read alone.

    Args:
        members: Member path → text.
        root: The root member's path.
        source_label: Fallback label for the root.

    Returns:
        The :class:`NcpdpDocument` for the set.

    Raises:
        NcpdpParseError: When the root, or a SCRIPT member, is unreadable.
    """
    text = members[root]
    label = root or source_label
    document = parse_ncpdp(text, source_label=label)
    if document.sub_format != SUB_FORMAT_SCRIPT:
        return document
    extra = [(path, members[path]) for path in sorted(members) if path != root and is_script(members[path])]
    if not extra:
        return document
    try:
        script = parse_script(text, source_label=label, members=extra)
    except ScriptParseError as exc:
        raise NcpdpParseError(str(exc), code=exc.code) from exc
    return NcpdpDocument(SUB_FORMAT_SCRIPT, text, label, script=script)
