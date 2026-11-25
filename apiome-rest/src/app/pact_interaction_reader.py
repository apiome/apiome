"""Read the parts of a Pact HTTP interaction, whatever specification version wrote it.

Pact specifications 1 to 4 spell the same request and response differently: a query is a string
(v2) or an object of value lists (v3, v4); a header is one value or, in v4, a list; a body is the
JSON value itself or, in v4, an object carrying ``content``, ``contentType`` and ``encoded``. The
bi-directional comparison (PFX-2.2, :mod:`app.pact_oas_compare`) and the contract-suite compiler
(PFX-3.1, :mod:`app.contract_suite_pact`) read pacts through these helpers so the two can never
disagree about what an interaction sends and expects.

Pure: no I/O, and nothing here raises for a malformed section — a reader returns an empty value,
and :func:`read_body` says why a body could not be decoded.
"""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs

from .pact_contract_import import unwrap_matcher

__all__ = [
    "V4_BODY_KEYS",
    "PactBody",
    "as_dict",
    "is_json_media_type",
    "media_type_of",
    "read_body",
    "read_headers",
    "read_query",
    "strip_embedded_matchers",
]

#: Keys a Pact 4 body object may carry; anything else is a plain JSON body that happens to
#: have a ``content`` property.
V4_BODY_KEYS = frozenset({"content", "contentType", "encoded", "contentTypeHint"})


def as_dict(value: Any) -> Dict[str, Any]:
    """Coerce a document node to a dict.

    Args:
        value: Any node.

    Returns:
        The dict, or an empty one for anything else.
    """
    return value if isinstance(value, dict) else {}


def media_type_of(value: Any) -> Optional[str]:
    """Normalize a content type to its bare, lowercase media type.

    Args:
        value: A ``Content-Type`` value, possibly with parameters.

    Returns:
        ``application/json`` for ``Application/JSON; charset=utf-8``; ``None`` for no value.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    return value.split(";", 1)[0].strip().lower()


def is_json_media_type(media_type: Optional[str]) -> bool:
    """Whether a media type carries JSON.

    Args:
        media_type: A bare media type.

    Returns:
        True for ``application/json`` and any ``+json`` type.
    """
    return media_type is not None and media_type.endswith(("/json", "+json"))


def read_headers(section: Mapping[str, Any]) -> Dict[str, Tuple[str, str]]:
    """Read a request's or response's headers.

    Args:
        section: The pact ``request`` or ``response`` object.

    Returns:
        Lowercase name to ``(name as written, value)``; a Pact 4 list of values is joined
        with ``, `` as HTTP does.
    """
    found: Dict[str, Tuple[str, str]] = {}
    for name, value in as_dict(section.get("headers")).items():
        if isinstance(value, list):
            text = ", ".join(str(item) for item in value)
        else:
            text = "" if value is None else str(value)
        found[str(name).lower()] = (str(name), text)
    return found


def read_query(section: Mapping[str, Any]) -> Dict[str, List[str]]:
    """Read a request's query in either spelling.

    Args:
        section: The pact ``request`` object.

    Returns:
        Parameter name to its values (Pact 2 writes a query string, 3 and 4 an object).
    """
    query = section.get("query")
    if isinstance(query, str):
        return {name: list(values) for name, values in parse_qs(query, keep_blank_values=True).items()}
    if isinstance(query, dict):
        return {
            str(name): [str(item) for item in value] if isinstance(value, list) else [str(value)]
            for name, value in query.items()
        }
    return {}


def strip_embedded_matchers(value: Any, found: List[bool]) -> Any:
    """Strip Pact 1 matcher wrappers (``json_class`` / ``pact:matcher:type``) out of a body.

    Args:
        value: A node of an example body.
        found: One-element list set to ``True`` when any wrapper was removed.

    Returns:
        The plain example.
    """
    plain = unwrap_matcher(value)
    if plain is not value:
        found[0] = True
    if isinstance(plain, dict):
        return {key: strip_embedded_matchers(item, found) for key, item in plain.items()}
    if isinstance(plain, list):
        return [strip_embedded_matchers(item, found) for item in plain]
    return plain


@dataclass
class PactBody:
    """A request or response body as the pact records it.

    Attributes:
        present: Whether the pact carries a body at all.
        value: The parsed body (JSON value, or text for a non-JSON body).
        media_type: The media type the pact states for it, if any (v4 ``contentType`` only).
        pointer: JSON Pointer of the body's content in the pact document.
        problem: Why the content could not be decoded, when it could not.
        embedded: Whether embedded matchers were stripped from it.
        empty: Whether the pact records the body as explicitly empty — ``"body": null``, or a
            Pact 4 body whose ``content`` is ``null`` or ``""`` (PFX-3.4). ``present`` is false
            for such a body (a request sends none), but a response expectation reads it as "the
            body must be empty", as the Pact specification test suite requires.
    """

    present: bool
    value: Any = None
    media_type: Optional[str] = None
    pointer: str = ""
    problem: Optional[str] = None
    embedded: bool = False
    empty: bool = False


def read_body(section: Mapping[str, Any], pointer: str, v4: bool) -> PactBody:
    """Read a body in the shape its specification version writes.

    Args:
        section: The pact ``request`` or ``response`` object.
        pointer: JSON Pointer of that object.
        v4: Whether the pact declares specification 4, whose body is an object with
            ``content``, ``contentType`` and ``encoded``.

    Returns:
        The :class:`PactBody`; ``present`` is false for a missing, ``null`` or empty body.
    """
    raw = section.get("body")
    if raw is None:
        return PactBody(present=False, empty="body" in section)
    if v4 and isinstance(raw, dict) and "content" in raw and set(raw) <= V4_BODY_KEYS:
        content = raw["content"]
        media_type = media_type_of(raw.get("contentType"))
        where = f"{pointer}/body/content"
        if content is None or content == "":
            return PactBody(present=False, empty=True)
        encoded = raw.get("encoded")
        encoding = encoded.strip().lower() if isinstance(encoded, str) else ""
        if encoding == "base64" and isinstance(content, str):
            try:
                content = base64.b64decode(content, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError, ValueError):
                return PactBody(True, None, media_type, where, "the base64 content is not text")
            encoding = "json"
        if isinstance(content, str) and (encoding == "json" or is_json_media_type(media_type)):
            try:
                content = json.loads(content)
            except ValueError:
                if encoding == "json":
                    return PactBody(True, None, media_type, where, "the content is not valid JSON")
        value, raw_pointer = content, where
    else:
        value, media_type, raw_pointer = raw, None, f"{pointer}/body"
    found = [False]
    plain = strip_embedded_matchers(value, found)
    return PactBody(True, plain, media_type, raw_pointer, None, found[0])
