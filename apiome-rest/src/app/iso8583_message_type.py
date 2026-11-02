"""ISO 8583 message-type and bitmap vocabulary — MFI-20.6 (#3990).

An ISO 8583 message starts with a four-digit **Message Type Indicator** (MTI) and one or two
**bitmaps** that say which of the 128 numbered data elements follow. The field-map JSON Apiome
imports lists the MTI and the data elements by number; this module decodes the MTI and derives the
bitmaps from the elements present, so the catalog item records the message's definition rather
than only its sample values. :mod:`app.iso8583_normalizer` writes the results to ``extras``;
:mod:`app.iso8583_lint` and :mod:`app.iso8583_breaking` read them.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

__all__ = [
    "DATA_ELEMENT_RANGE",
    "KNOWN_TYPE_CODES",
    "MTI_CLASSES",
    "MTI_FUNCTIONS",
    "MTI_ORIGINS",
    "MTI_VERSIONS",
    "bitmaps_for",
    "decode_mti",
    "is_response_function",
]

#: Data element numbers a message may carry (1 is the secondary bitmap itself).
DATA_ELEMENT_RANGE = range(2, 129)

#: The type codes ISO 8583 uses for a data element's content.
KNOWN_TYPE_CODES = frozenset({"a", "n", "s", "an", "as", "ns", "ans", "b", "z", "x+n", "p"})

#: MTI position 1 — the ISO 8583 release the message follows.
MTI_VERSIONS: Dict[str, str] = {
    "0": "ISO 8583:1987",
    "1": "ISO 8583:1993",
    "2": "ISO 8583:2003",
    "8": "National use",
    "9": "Private use",
}

#: MTI position 2 — the message class.
MTI_CLASSES: Dict[str, str] = {
    "1": "Authorization",
    "2": "Financial",
    "3": "File actions",
    "4": "Reversal and chargeback",
    "5": "Reconciliation",
    "6": "Administrative",
    "7": "Fee collection",
    "8": "Network management",
}

#: MTI position 3 — the message function.
MTI_FUNCTIONS: Dict[str, str] = {
    "0": "Request",
    "1": "Request response",
    "2": "Advice",
    "3": "Advice response",
    "4": "Notification",
    "5": "Notification acknowledgement",
    "6": "Instruction",
    "7": "Instruction acknowledgement",
}

#: MTI position 4 — who originated the message.
MTI_ORIGINS: Dict[str, str] = {
    "0": "Acquirer",
    "1": "Acquirer repeat",
    "2": "Issuer",
    "3": "Issuer repeat",
    "4": "Other",
    "5": "Other repeat",
}


def decode_mti(mti: str) -> Dict[str, Optional[str]]:
    """Decode a Message Type Indicator into its four positions.

    Args:
        mti: The four-digit MTI (``"0100"``).

    Returns:
        ``version``, ``class``, ``function`` and ``origin`` — each the digit and, under
        ``*_label``, its meaning, or ``None`` for a digit the standard reserves — plus
        ``summary`` (``"Authorization request (acquirer)"``). An MTI that is not four digits
        decodes to ``None`` labels.
    """
    digits = list(mti) if isinstance(mti, str) and len(mti) == 4 and mti.isdigit() else [None] * 4
    version, klass, function, origin = digits
    labels = {
        "version_label": MTI_VERSIONS.get(version) if version else None,
        "class_label": MTI_CLASSES.get(klass) if klass else None,
        "function_label": MTI_FUNCTIONS.get(function) if function else None,
        "origin_label": MTI_ORIGINS.get(origin) if origin else None,
    }
    summary = None
    if labels["class_label"] and labels["function_label"]:
        summary = f"{labels['class_label']} {labels['function_label'].lower()}"
        if labels["origin_label"]:
            summary += f" ({labels['origin_label'].lower()})"
    return {"version": version, "class": klass, "function": function, "origin": origin, **labels, "summary": summary}


def is_response_function(function: Optional[str]) -> bool:
    """Whether an MTI function digit names a response or acknowledgement (``1``, ``3``, ``5``, ``7``)."""
    return function in {"1", "3", "5", "7"}


def _bitmap_hex(numbers: Iterable[int], first: int) -> str:
    """The 64-bit bitmap covering data elements ``first`` … ``first + 63`` as 16 hex digits."""
    bits = 0
    for number in numbers:
        offset = number - first
        if 0 <= offset < 64:
            bits |= 1 << (63 - offset)
    return f"{bits:016X}"


def bitmaps_for(numbers: Iterable[object]) -> Dict[str, object]:
    """Derive the primary and secondary bitmaps from the data elements a message carries.

    Bit 1 of the primary bitmap is set when a secondary bitmap follows, which is the case as soon
    as any data element above 64 is present. Numbers that are not integers in 1–128 are ignored.

    Args:
        numbers: The data element numbers present (``"2"``, ``11``, …).

    Returns:
        ``primary`` (16 hex digits), ``secondary`` (16 hex digits or ``None``),
        ``has_secondary`` and ``elements`` (the sorted numbers the bitmaps describe).
    """
    present: List[int] = sorted(
        {int(n) for n in numbers if isinstance(n, (int, str)) and str(n).isdigit() and 1 <= int(n) <= 128}
    )
    has_secondary = any(number > 64 for number in present)
    primary_numbers = [n for n in present if n <= 64] + ([1] if has_secondary else [])
    return {
        "primary": _bitmap_hex(primary_numbers, 1),
        "secondary": _bitmap_hex([n for n in present if n > 64], 65) if has_secondary else None,
        "has_secondary": has_secondary,
        "elements": present,
    }
