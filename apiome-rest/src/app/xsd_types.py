"""Canonical types and names → XML Schema (XSD 1.0) — MFX-14.1 (#3889).

Shared by the XML-family emitters (WSDL today; the standalone XSD emitter can adopt it). Two jobs:

* :func:`xsd_builtin` maps a canonical scalar to the XSD built-in type that keeps its precision:
  an OpenAPI ``integer`` with ``format: int64`` is ``long``, not ``int``; ``string`` with
  ``format: date-time`` is ``dateTime``; ``decimal`` stays ``decimal``. A field imported from XSD
  carries its original type in ``extras["xsd_type"]``, which wins, so a WSDL → WSDL export writes
  back exactly what was read.
* :func:`ncname` turns a source name into a legal XML ``NCName`` (no ``/``, ``{``, spaces or a
  leading digit), so the emitted names are valid element, type and operation names.
"""

from __future__ import annotations

import re
from typing import Dict, Optional

from elementpath.regex import RegexError, translate_pattern

from .scalar_aliases import scalar_kind

__all__ = ["XSD_BUILTINS", "is_ncname", "ncname", "xsd_builtin", "xsd_pattern"]

#: XSD 1.0 built-in types (Part 2 §3–4), keyed by lower-case name → the spelling XSD uses.
XSD_BUILTINS: Dict[str, str] = {
    name.lower(): name
    for name in (
        "anyType",
        "anySimpleType",
        "string",
        "normalizedString",
        "token",
        "language",
        "Name",
        "NCName",
        "ID",
        "IDREF",
        "NMTOKEN",
        "boolean",
        "decimal",
        "integer",
        "nonPositiveInteger",
        "negativeInteger",
        "nonNegativeInteger",
        "positiveInteger",
        "long",
        "int",
        "short",
        "byte",
        "unsignedLong",
        "unsignedInt",
        "unsignedShort",
        "unsignedByte",
        "float",
        "double",
        "duration",
        "dateTime",
        "date",
        "time",
        "gYear",
        "gYearMonth",
        "gMonth",
        "gMonthDay",
        "gDay",
        "hexBinary",
        "base64Binary",
        "anyURI",
        "QName",
    )
}

#: Scalar kind (:mod:`app.scalar_aliases`) → XSD built-in. XSD has every width, signed and
#: unsigned, so nothing narrows or widens.
_KIND_TO_XSD: Dict[str, str] = {
    "bool": "boolean",
    "int8": "byte",
    "int16": "short",
    "int32": "int",
    "int64": "long",
    "uint8": "unsignedByte",
    "uint16": "unsignedShort",
    "uint32": "unsignedInt",
    "uint64": "unsignedLong",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "base64Binary",
}

#: A string's ``format`` → the XSD built-in that keeps its meaning.
_STRING_FORMAT_TO_XSD: Dict[str, str] = {
    "date-time": "dateTime",
    "datetime": "dateTime",
    "date": "date",
    "time": "time",
    "duration": "duration",
    "uri": "anyURI",
    "url": "anyURI",
    "uri-reference": "anyURI",
    "iri": "anyURI",
    "byte": "base64Binary",
    "binary": "base64Binary",
    "decimal": "decimal",
}

#: Canonical spellings that are not scalar kinds but have an exact XSD type.
_NAMED_TO_XSD: Dict[str, str] = {
    "decimal": "decimal",
    "date": "date",
    "datetime": "dateTime",
    "date-time": "dateTime",
    "timestamp": "dateTime",
    "time": "time",
    "duration": "duration",
    "uri": "anyURI",
    "url": "anyURI",
    "any": "anyType",
}


def xsd_builtin(
    name: Optional[str], fmt: Optional[str] = None, xsd_hint: Optional[str] = None
) -> Optional[str]:
    """Return the XSD built-in type for a canonical scalar, or ``None`` when it is not a scalar.

    Args:
        name: The :class:`~app.canonical_model.TypeRef` name (``integer``, ``i64``, ``string`` …).
        fmt: The field's ``format`` constraint, when it has one (``int64``, ``date-time`` …).
        xsd_hint: The XSD type an XSD/WSDL import recorded (``extras["xsd_type"]``); used when it
            names a built-in.

    Returns:
        The built-in's local name (``long``, ``dateTime`` …), or ``None`` for a named type.
    """
    if xsd_hint:
        local = xsd_hint.split(":")[-1].lower()
        if local in XSD_BUILTINS:
            return XSD_BUILTINS[local]
    if not name:
        return None
    key = name.strip().lower()
    hint = (fmt or "").strip().lower()
    if key in ("string", "str", "text") and hint in _STRING_FORMAT_TO_XSD:
        return _STRING_FORMAT_TO_XSD[hint]
    if key == "number" and hint == "decimal":
        return "decimal"
    kind = scalar_kind(name, fmt)
    if kind is not None:
        return _KIND_TO_XSD[kind]
    if key in _NAMED_TO_XSD:
        return _NAMED_TO_XSD[key]
    if key in XSD_BUILTINS:
        return XSD_BUILTINS[key]
    return None


_NCNAME = re.compile(r"^[^\W\d][\w.\-]*$", re.UNICODE)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def is_ncname(value: str) -> bool:
    """Whether ``value`` is a legal XML ``NCName`` (a name with no colon)."""
    return bool(value) and bool(_NCNAME.match(value))


def ncname(raw: str, *, pascal: bool = False, fallback: str = "item") -> str:
    """Return ``raw`` unchanged when it is a legal ``NCName``, else a camelCase (or PascalCase) one.

    Args:
        raw: The source name (``GET /pets/{petId}``, ``2xx``, ``first name`` …).
        pascal: Start with a capital letter (type names), else lower-case (operations, fields).
        fallback: Used when ``raw`` has no letters or digits.

    Returns:
        A legal ``NCName``: ``GET /pets/{petId}`` → ``getPetsPetId``; ``2xx`` → ``_2xx``.
    """
    if is_ncname(raw):
        return raw
    words = _WORD.findall(raw or "")
    if not words:
        return fallback
    first = words[0][:1].upper() + words[0][1:] if pascal else words[0].lower()
    name = first + "".join(word[:1].upper() + word[1:] for word in words[1:])
    return name if is_ncname(name) else f"_{name}"


#: ECMA-262 regex constructs XSD's regex dialect does not have.
_UNSUPPORTED_REGEX = re.compile(r"\(\?|\\[bB]|\\[1-9]|[*+?}]\?")


def xsd_pattern(pattern: str) -> Optional[str]:
    """Translate a JSON Schema (ECMA-262) ``pattern`` to an XSD ``pattern`` facet.

    JSON Schema matches a pattern anywhere in the value; XSD matches the whole value and has no
    anchors (``^`` and ``$`` are literal characters there). So a leading ``^`` / trailing ``$`` is
    removed, and an unanchored end is padded with ``.*``.

    Args:
        pattern: The source pattern, e.g. ``^[A-Z]{3}$``.

    Returns:
        The XSD pattern (``[A-Z]{3}``), or ``None`` when the pattern uses a construct XSD lacks
        (lookaround, lazy quantifier, ``\\b``, backreference) or is not a valid XSD regular
        expression — the caller reports it as dropped.
    """
    if _UNSUPPORTED_REGEX.search(pattern):
        return None
    body = pattern
    if body.startswith("^"):
        body = body[1:]
    else:
        body = f".*{body}"
    if body.endswith("$") and not body.endswith("\\$"):
        body = body[:-1]
    else:
        body = f"{body}.*"
    # `\/` is a common JSON Schema escape that XSD's regex grammar does not define; `/` means the same.
    body = re.sub(r"(?<!\\)\\/", "/", body)
    try:
        translate_pattern(body, xsd_version="1.0")
    except RegexError:
        return None
    return body
