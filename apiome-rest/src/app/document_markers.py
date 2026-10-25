"""Cheap, parse-free markers for format detection.

Format detection polls every import adapter and sniffer against the same text. Two kinds of
mistake follow when a sniffer reads raw text without knowing what *kind* of text it is:

* An OpenAPI document that does not fully parse — a stray YAML error, or one large enough to
  breach an intake limit (``INPUT_ENTITY_LIMIT``) — drops out of detection entirely, because the
  OpenAPI adapter recognises a document only by its parsed ``openapi`` key. The top-level
  ``openapi: 3.1.0`` line is still right there in the text.
* An IDL sniffer (Thrift, WIT, FlatBuffers, gRPC's keyword fallback) matches its keywords
  anywhere — inside a YAML description, a JSON string, a comment — so prose such as
  ``namespace to its primitives`` makes a YAML document "Thrift".

This module answers both questions from the text alone, in linear time, without parsing:
:func:`top_level_api_marker` finds a column-0 ``openapi`` / ``swagger`` / ``swaggerVersion`` key,
and :func:`looks_like_structured_document` says whether the text is a JSON or YAML document at
all, which no IDL source ever is.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

#: How much of the text to look through for the first meaningful line, and for a JSON
#: document's top-level marker. A real document states either within its first few lines;
#: bounding the scan keeps detection linear on multi-megabyte inputs.
_HEAD_CHARS = 16_384

#: A top-level YAML key: at column 0, a single plain or quoted token, then ``:`` and a space or
#: the end of the line. A single token is what rules out IDL lines that merely contain a colon
#: (Thrift ``const map<string,string> M = {"a": "b"}``, WIT ``package ns:name;``).
_YAML_KEY_LINE = re.compile(
    r"""(?:"[^"\n]+"|'[^'\n]+'|[A-Za-z_$][\w$.\-]*)\s*:(?:[ \t]|$)"""
)

#: The opening of a JSON object or array: ``{`` then a string key or ``}``, or ``[`` then a
#: JSON value or ``]``.
_JSON_START = re.compile(r'\{\s*(?:"|\})|\[\s*(?:[\[{"\]\-0-9]|true|false|null)')

#: ``openapi: 3.1.0`` / ``swagger: "2.0"`` / ``swaggerVersion: '1.2'`` at column 0.
_YAML_API_MARKER = re.compile(
    r"""^(openapi|swagger|swaggerVersion)[ \t]*:[ \t]*["']?([0-9][0-9A-Za-z.\-+]*)["']?[ \t]*(?:#.*)?$""",
    re.MULTILINE,
)

#: ``"openapi": "3.1.0"`` in a JSON document's head.
_JSON_API_MARKER = re.compile(
    r'"(openapi|swagger|swaggerVersion)"\s*:\s*"([0-9][0-9A-Za-z.\-+]*)"'
)


def _first_meaningful_line(text: str) -> Optional[str]:
    """The first line that is not blank, a ``#`` comment, a YAML directive or a ``---`` marker."""
    for line in text[:_HEAD_CHARS].lstrip("﻿").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("%"):
            continue
        if stripped in ("---", "..."):
            continue
        return line
    return None


def looks_like_structured_document(text: Optional[str]) -> bool:
    """Whether ``text`` is a JSON or YAML document rather than an IDL source.

    True when the first meaningful line opens a JSON object or array, or is a top-level YAML
    mapping key (``openapi: 3.1.0``, ``"name": …``). No Thrift, WIT, FlatBuffers or Protobuf file
    begins that way, so an IDL sniffer that sees ``True`` here is reading words inside a data
    document and must not claim it.

    Args:
        text: The raw document text.

    Returns:
        ``True`` for a JSON or YAML document; ``False`` for anything else, including empty text.
    """
    if not text:
        return False
    line = _first_meaningful_line(text)
    if line is None:
        return False
    stripped = line.lstrip()
    if stripped.startswith(("{", "[")):
        # A genuine JSON opening, read across lines: `{` then a key or `}`, `[` then a value or
        # `]`. SWIFT MT blocks (`{1:F01…}`) and similar brace-framed records are not JSON.
        head = text[:_HEAD_CHARS].lstrip("﻿ \t\r\n")
        return _JSON_START.match(head) is not None
    # Only a column-0 key is a *top-level* mapping key; an indented one is a nested value.
    return line == stripped and _YAML_KEY_LINE.match(line) is not None


def top_level_api_marker(text: Optional[str]) -> Optional[Tuple[str, str]]:
    """The top-level ``openapi`` / ``swagger`` / ``swaggerVersion`` marker, read from the text.

    For a document the parser could not read — malformed YAML, or one over an intake limit — this
    is what still identifies it. Only a column-0 YAML key (or a key in a JSON document's head)
    counts: an indented ``openapi:`` is a nested value, not the document's own marker.

    Args:
        text: The raw document text.

    Returns:
        ``(key, version)``, e.g. ``("openapi", "3.1.0")``; ``None`` when there is no marker.
    """
    if not text or not looks_like_structured_document(text):
        return None
    head = text[:_HEAD_CHARS]
    stripped = head.lstrip("﻿ \t\r\n")
    if stripped.startswith("{"):
        match = _JSON_API_MARKER.search(stripped)
    else:
        match = _YAML_API_MARKER.search(text.lstrip("\ufeff"))
    if match is None:
        return None
    return match.group(1), match.group(2)
