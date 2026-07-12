"""FIX message parser — MFI-22.8.

Parses FIX tag=value messages (SOH- or pipe-delimited) into a typed
:class:`FixDocument` AST. Syntax errors surface as :class:`FixParseError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "FixParseError",
    "FixField",
    "FixMessage",
    "FixDocument",
    "is_fix",
    "parse_fix",
    "field_template",
]

_BEGIN_STRING_RE = re.compile(r"^FIX\.\d+\.\d+$", re.IGNORECASE)
_TAG_VALUE_RE = re.compile(r"^(\d+)=([\s\S]*)$")
_HL7_LINE_RE = re.compile(r"^MSH.", re.MULTILINE)
_JSON_MARKERS = ('"mti"', '"resourceType"', '"openrpc"', '"asyncapi"', '"openapi"')


class FixParseError(ValueError):
    """Raised when FIX content cannot be parsed."""


@dataclass(frozen=True)
class FixField:
    tag: str
    value: str


@dataclass(frozen=True)
class FixMessage:
    begin_string: Optional[str]
    msg_type: Optional[str]
    sender_comp_id: Optional[str]
    target_comp_id: Optional[str]
    fields: Tuple[FixField, ...]


@dataclass(frozen=True)
class FixDocument:
    message: FixMessage
    delimiter: str
    raw: str


_FIX_TAG_NAMES: Dict[str, str] = {
    "6": "AvgPx",
    "8": "BeginString",
    "9": "BodyLength",
    "10": "CheckSum",
    "11": "ClOrdID",
    "14": "CumQty",
    "17": "ExecID",
    "20": "ExecTransType",
    "34": "MsgSeqNum",
    "35": "MsgType",
    "37": "OrderID",
    "38": "OrderQty",
    "39": "OrdStatus",
    "40": "OrdType",
    "44": "Price",
    "49": "SenderCompID",
    "52": "SendingTime",
    "54": "Side",
    "55": "Symbol",
    "56": "TargetCompID",
    "59": "TimeInForce",
    "60": "TransactTime",
    "150": "ExecType",
    "151": "LeavesQty",
}

_FIX_MSG_TYPE_NAMES: Dict[str, str] = {
    "8": "ExecutionReport",
    "D": "NewOrderSingle",
    "F": "OrderCancelRequest",
    "G": "OrderCancelReplaceRequest",
}


def tag_name(tag: str) -> str:
    """Return the standard FIX field name for ``tag``, or ``Tag{tag}``."""
    return _FIX_TAG_NAMES.get(tag, f"Tag{tag}")


def msg_type_name(msg_type: Optional[str]) -> Optional[str]:
    """Return the standard FIX message name for ``msg_type``."""
    if not msg_type:
        return None
    return _FIX_MSG_TYPE_NAMES.get(msg_type, f"Message{msg_type}")


def _detect_delimiter(content: str) -> str:
    if "\x01" in content:
        return "\x01"
    if "|" in content:
        return "|"
    raise FixParseError("No FIX field delimiter found (expected SOH or `|`)")


def _split_fields(content: str, delimiter: str) -> List[str]:
    parts = content.split(delimiter)
    return [part for part in parts if part]


def _parse_tag_values(tokens: List[str]) -> List[FixField]:
    fields: List[FixField] = []
    for token in tokens:
        match = _TAG_VALUE_RE.match(token.strip())
        if not match:
            raise FixParseError(f"Invalid FIX field: {token!r}")
        fields.append(FixField(tag=match.group(1), value=match.group(2)))
    return fields


def is_fix(content: str) -> bool:
    """Return ``True`` when ``content`` looks like a FIX tag=value message."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    lowered = trimmed.lower()
    if any(marker in lowered for marker in _JSON_MARKERS):
        return False
    if trimmed.startswith("{") or _HL7_LINE_RE.search(trimmed):
        return False
    try:
        delimiter = _detect_delimiter(trimmed)
    except FixParseError:
        return False
    fields = _parse_tag_values(_split_fields(trimmed, delimiter))
    if len(fields) < 3:
        return False
    begin = next((field.value for field in fields if field.tag == "8"), None)
    if not begin or not _BEGIN_STRING_RE.match(begin):
        return False
    return any(field.tag == "35" for field in fields)


def parse_fix(content: str, *, source_label: Optional[str] = None) -> FixDocument:
    """Parse FIX message text into a :class:`FixDocument`."""
    if not content or not content.strip():
        raise FixParseError("Invalid or empty FIX content")
    if not is_fix(content):
        label = f" ({source_label})" if source_label else ""
        raise FixParseError(f"Content does not appear to be a FIX message{label}")

    delimiter = _detect_delimiter(content)
    fields = tuple(_parse_tag_values(_split_fields(content.strip(), delimiter)))
    if not fields:
        label = f" ({source_label})" if source_label else ""
        raise FixParseError(f"No FIX fields found{label}")

    by_tag = {field.tag: field.value for field in fields}
    message = FixMessage(
        begin_string=by_tag.get("8"),
        msg_type=by_tag.get("35"),
        sender_comp_id=by_tag.get("49"),
        target_comp_id=by_tag.get("56"),
        fields=fields,
    )
    return FixDocument(message=message, delimiter=delimiter, raw=content)


def field_template(field: FixField) -> Dict[str, object]:
    """Serialize a :class:`FixField` for round-trip extras."""
    return {
        "tag": field.tag,
        "name": tag_name(field.tag),
        "value": field.value,
    }
