"""YAML loading for import documents (JSON-serializable output)."""

from __future__ import annotations

import re
from typing import Any

from yaml12 import parse_yaml

__all__ = [
    "normalize_yaml_source_text",
    "safe_load",
    "safe_load_mapping",
]


def normalize_yaml_source_text(text: str) -> str:
    """Normalize YAML source text so common authoring mistakes still parse.

    Some published OpenAPI YAML files embed literal tab characters inside
    unquoted description scalars; YAML 1.1 forbids tabs starting tokens
    within plain scalars. Other files include whitespace-only lines inside
    literal block scalars (``|-``), which also breaks strict YAML parsers.
    Unicode line/paragraph separators (U+2028/U+2029) also break block
    scalars when they appear mid-line.
    """
    if not text:
        return text
    normalized = re.sub(r"(?m)^[ \t]+\n", "", text)
    normalized = normalized.replace("\u2028", " ").replace("\u2029", " ")
    if "\t" not in normalized:
        return normalized
    return normalized.replace("\t", " ")


def _coerce_yaml_input(text: str | bytes) -> str:
    if isinstance(text, bytes):
        return text.decode("utf-8")
    return text


def safe_load(text: str | bytes) -> Any:
    """Parse YAML *text* with YAML 1.2 semantics and JSON-serializable output."""
    try:
        return parse_yaml(normalize_yaml_source_text(_coerce_yaml_input(text)))
    except ValueError as exc:
        message = str(exc)
        if message.startswith("YAML parse error:"):
            raise ValueError(message.removeprefix("YAML parse error:").strip()) from exc
        raise


def safe_load_mapping(text: str | bytes) -> dict[str, Any]:
    """Parse YAML *text* to a top-level mapping without timestamp coercion."""
    data = safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(
            f"Expected a YAML mapping at the top level, got {type(data).__name__}."
        )
    return data
