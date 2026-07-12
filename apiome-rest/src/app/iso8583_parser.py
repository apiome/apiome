"""ISO 8583 message parser — MFI-22.6.

Parses ISO 8583 field-map JSON (MTI + numbered Data Elements) into a typed
:class:`Iso8583Document` AST. Syntax errors surface as :class:`Iso8583ParseError`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "Iso8583ParseError",
    "Iso8583DataElement",
    "Iso8583Document",
    "is_iso8583",
    "parse_iso8583",
]

_MTI_RE = re.compile(r"^\d{4}$")
_OTHER_JSON_MARKERS = (
    "openrpc",
    "asyncapi",
    "openapi",
    "swagger",
    "resourceType",
    "specversion",
    "arazzo",
    "edmx:Edmx",
)


class Iso8583ParseError(ValueError):
    """Raised when ISO 8583 content cannot be parsed."""


@dataclass(frozen=True)
class Iso8583DataElement:
    number: str
    name: str
    type_expr: str
    length: Optional[str]
    value: str


@dataclass(frozen=True)
class Iso8583Document:
    mti: str
    name: Optional[str]
    data_elements: Tuple[Iso8583DataElement, ...]
    raw: str


def _document_dict(content: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise Iso8583ParseError(f"Invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise Iso8583ParseError("ISO 8583 document must be a JSON object")
    return parsed


def _data_elements_mapping(document: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for key in ("dataElements", "data_elements"):
        value = document.get(key)
        if isinstance(value, dict):
            return value
    return None


def _looks_like_data_element(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if "value" not in value:
        return False
    return any(key in value for key in ("name", "type", "length"))


def is_iso8583(content: str) -> bool:
    """Return ``True`` when ``content`` looks like an ISO 8583 field-map JSON document."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed.startswith("{"):
        return False
    lowered = trimmed.lower()
    if any(marker.lower() in lowered for marker in _OTHER_JSON_MARKERS):
        return False
    try:
        document = json.loads(trimmed)
    except json.JSONDecodeError:
        return False
    if not isinstance(document, dict):
        return False
    mti = document.get("mti")
    if not isinstance(mti, str) or not _MTI_RE.fullmatch(mti):
        return False
    elements = _data_elements_mapping(document)
    if not elements:
        return False
    valid = [value for value in elements.values() if _looks_like_data_element(value)]
    return len(valid) >= 1


def _parse_data_element(number: str, payload: Dict[str, Any]) -> Iso8583DataElement:
    name = str(payload.get("name") or f"Data Element {number}")
    type_expr = str(payload.get("type") or "ans")
    length = payload.get("length")
    length_expr = str(length) if length is not None else None
    value = payload.get("value")
    if value is None:
        raise Iso8583ParseError(f"Data element {number} is missing a `value`")
    return Iso8583DataElement(
        number=number,
        name=name,
        type_expr=type_expr,
        length=length_expr,
        value=str(value),
    )


def parse_iso8583(content: str, *, source_label: Optional[str] = None) -> Iso8583Document:
    """Parse ISO 8583 JSON into an :class:`Iso8583Document`."""
    if not content or not content.strip():
        raise Iso8583ParseError("Invalid or empty ISO 8583 content")
    if not is_iso8583(content):
        raise Iso8583ParseError("Content does not appear to be an ISO 8583 field-map document")

    document = _document_dict(content)
    mti = str(document["mti"])
    elements = _data_elements_mapping(document)
    if elements is None:
        label = f" ({source_label})" if source_label else ""
        raise Iso8583ParseError(f"Missing `dataElements` object{label}")

    data_elements: List[Iso8583DataElement] = []
    for number in sorted(elements, key=lambda item: int(item) if item.isdigit() else item):
        payload = elements[number]
        if not isinstance(payload, dict):
            continue
        if not _looks_like_data_element(payload):
            continue
        data_elements.append(_parse_data_element(str(number), payload))

    if not data_elements:
        label = f" ({source_label})" if source_label else ""
        raise Iso8583ParseError(f"No ISO 8583 data elements found{label}")

    name = document.get("name")
    return Iso8583Document(
        mti=mti,
        name=str(name) if isinstance(name, str) and name.strip() else None,
        data_elements=tuple(data_elements),
        raw=content,
    )


def data_element_template(element: Iso8583DataElement) -> Dict[str, object]:
    """Serialize a data element for round-trip extras."""
    payload: Dict[str, object] = {
        "number": element.number,
        "name": element.name,
        "type": element.type_expr,
        "value": element.value,
    }
    if element.length is not None:
        payload["length"] = element.length
    return payload
