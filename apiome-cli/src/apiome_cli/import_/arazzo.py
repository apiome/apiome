"""Arazzo 1.0 document parsing and structural validation.

Supports loading Arazzo workflow documents from:
- Local files with ``.yaml``, ``.yml``, or ``.json`` extensions.
- HTTP or HTTPS URLs (format from path suffix or ``Content-Type``).
- Standard input when the path argument is ``-``.

Structural validation uses the vendored Arazzo 1.0 JSON Schema (Draft 2020-12).
Callers should map :class:`ArazzoStructureError` to CLI exit code 2 (``EXIT_USAGE``).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JsonSchemaValidationError

from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.import_.source import (
    is_remote_source,
    parse_mapping_document,
    read_document_text,
    suffix_from_source,
)


class ArazzoStructureError(ValueError):
    """Raised when an Arazzo document fails structural validation.

    CLI commands should exit with :data:`~apiome_cli.exit_codes.EXIT_USAGE`
    (2) and print :attr:`message` to stderr.
    """

    exit_code: int = EXIT_USAGE

    def __init__(self, message: str, *, pointer: str | None = None) -> None:
        if pointer is not None:
            rendered = f"At {pointer}: {message}"
        else:
            rendered = message
        super().__init__(rendered)
        self.message = rendered
        self.pointer = pointer


def _escape_json_pointer_token(token: str) -> str:
    """Escape one JSON Pointer token according to RFC 6901."""
    return token.replace("~", "~0").replace("/", "~1")


def _pointer_from_absolute_path(path: Sequence[Any]) -> str:
    """Build an RFC 6901 JSON Pointer from a ``jsonschema`` absolute path."""
    if not path:
        return "/"
    return "/" + "/".join(_escape_json_pointer_token(str(segment)) for segment in path)


@lru_cache(maxsize=1)
def _arazzo_schema() -> dict[str, Any]:
    """Load the vendored Arazzo 1.0 JSON Schema (iteration 2025-10-15)."""
    schema_path = (
        resources.files("apiome_cli.import_.schemas.arazzo")
        .joinpath("1.0", "2025-10-15.json")
    )
    with schema_path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise SchemaError("Vendored Arazzo schema must be a JSON object.")
    return loaded


@lru_cache(maxsize=1)
def _arazzo_validator() -> Draft202012Validator:
    """Return a cached validator for the vendored Arazzo 1.0 schema."""
    return Draft202012Validator(_arazzo_schema())


def load_arazzo_file(
    path: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
) -> dict[str, Any]:
    """Load and parse an Arazzo document from *path*, a URL, or stdin.

    Args:
        path: File system path, HTTP(S) URL, or ``"-"`` for stdin.
        timeout: HTTP connect + read timeout when fetching a URL.
        verify: Whether to verify TLS certificates for URL fetches.

    Returns:
        The parsed Arazzo document as a plain Python dict.

    Raises:
        ValueError: If the file extension is not supported, if the document
                    cannot be parsed, or if the top-level value is not a
                    mapping/object.
        OSError: If the file cannot be opened or read, or the URL fetch fails.
    """
    if not is_remote_source(path) and path != "-":
        suffix = suffix_from_source(path)
        if suffix is None:
            raise ValueError(
                f"Unsupported file extension '{Path(path).suffix.lower()}'. "
                "Accepted extensions are: .json, .yaml, .yml"
            )

    text, suffix = read_document_text(path, timeout=timeout, verify=verify)
    return parse_mapping_document(text, source=path, suffix=suffix)


def validate_arazzo_structure(doc: dict[str, Any]) -> None:
    """Validate *doc* against the vendored Arazzo 1.0 JSON Schema.

    Args:
        doc: Parsed top-level Arazzo document mapping.

    Raises:
        ArazzoStructureError: When the document fails schema validation.
    """
    try:
        _arazzo_validator().validate(doc)
    except JsonSchemaValidationError as exc:
        raise ArazzoStructureError(
            exc.message,
            pointer=_pointer_from_absolute_path(exc.absolute_path),
        ) from exc
    except SchemaError as exc:
        raise ArazzoStructureError(str(exc).strip()) from exc


def load_and_validate_arazzo_file(path: str) -> dict[str, Any]:
    """Load, parse, and structurally validate an Arazzo document.

    Args:
        path: File path, URL, or ``"-"`` for stdin.

    Returns:
        The validated parsed document.

    Raises:
        ValueError: On parse errors (see :func:`load_arazzo_file`).
        OSError: If a named file cannot be read.
        ArazzoStructureError: If structural validation fails.
    """
    doc = load_arazzo_file(path)
    validate_arazzo_structure(doc)
    return doc
