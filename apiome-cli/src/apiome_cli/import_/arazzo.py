"""Arazzo 1.0.x / 1.1.x document parsing and structural validation.

Supports loading Arazzo workflow documents from:
- Local files with ``.yaml``, ``.yml``, or ``.json`` extensions.
- HTTP or HTTPS URLs (format from path suffix or ``Content-Type``).
- Standard input when the path argument is ``-``.

Structural validation uses the vendored Arazzo JSON Schema (Draft 2020-12) for the
version the document declares in its top-level ``arazzo`` field: the 1.0 schema
(iteration 2025-10-15) for ``1.0.x`` and the 1.1 schema (iteration 2026-04-15) for
``1.1.x``. Any other version is rejected with a message naming the supported lines.
Callers should map :class:`ArazzoStructureError` to CLI exit code 2 (``EXIT_USAGE``).
"""

from __future__ import annotations

import json
import re
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


#: Vendored schema per supported ``(major, minor)`` line: ``(directory, iteration file)``.
#: Mirrors the REST importer's ``SUPPORTED_ARAZZO_VERSIONS`` (``apiome-rest/src/app/arazzo_spec.py``).
_ARAZZO_SCHEMAS: dict[tuple[int, int], tuple[str, str]] = {
    (1, 0): ("1.0", "2025-10-15.json"),
    (1, 1): ("1.1", "2026-04-15.json"),
}

#: A ``major.minor`` prefix, with any remaining patch/pre-release suffix ignored.
_VERSION = re.compile(r"^(?P<major>\d+)\.(?P<minor>\d+)(?:[.\-+].*)?$")


def supported_arazzo_versions() -> tuple[str, ...]:
    """Return the Arazzo version lines this CLI validates, e.g. ``("1.0.x", "1.1.x")``."""
    return tuple(f"{major}.{minor}.x" for major, minor in sorted(_ARAZZO_SCHEMAS))


def arazzo_version_line(doc: dict[str, Any]) -> tuple[int, int]:
    """Return the supported ``(major, minor)`` line *doc* declares.

    Args:
        doc: Parsed top-level Arazzo document mapping.

    Returns:
        The ``(major, minor)`` pair from the ``arazzo`` field; the patch component is
        ignored because Arazzo's compatibility contract is per minor version.

    Raises:
        ArazzoStructureError: When ``arazzo`` is missing, not a ``major.minor[.patch]``
            string, or names a version line with no vendored schema.
    """
    supported = ", ".join(supported_arazzo_versions())
    raw = doc.get("arazzo")
    if not isinstance(raw, str) or not raw.strip():
        raise ArazzoStructureError(
            f"Missing or invalid 'arazzo' version; supported versions are {supported}.",
            pointer="/arazzo" if "arazzo" in doc else "/",
        )
    match = _VERSION.match(raw.strip())
    if match is None:
        raise ArazzoStructureError(
            f"'{raw}' is not a recognizable Arazzo version "
            f"(expected major.minor.patch, for example 1.1.0); supported versions are {supported}.",
            pointer="/arazzo",
        )
    line = (int(match.group("major")), int(match.group("minor")))
    if line not in _ARAZZO_SCHEMAS:
        raise ArazzoStructureError(
            f"Arazzo {raw} is not supported; supported versions are {supported}.",
            pointer="/arazzo",
        )
    return line


@lru_cache(maxsize=len(_ARAZZO_SCHEMAS))
def _arazzo_schema(line: tuple[int, int]) -> dict[str, Any]:
    """Load the vendored Arazzo JSON Schema for one supported version line.

    Args:
        line: A ``(major, minor)`` key of :data:`_ARAZZO_SCHEMAS`.

    Returns:
        The parsed JSON Schema document.
    """
    directory, filename = _ARAZZO_SCHEMAS[line]
    schema_path = (
        resources.files("apiome_cli.import_.schemas.arazzo")
        .joinpath(directory, filename)
    )
    with schema_path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise SchemaError("Vendored Arazzo schema must be a JSON object.")
    return loaded


@lru_cache(maxsize=len(_ARAZZO_SCHEMAS))
def _arazzo_validator(line: tuple[int, int]) -> Draft202012Validator:
    """Return a cached validator for the vendored schema of one version line.

    Args:
        line: A ``(major, minor)`` key of :data:`_ARAZZO_SCHEMAS`.
    """
    return Draft202012Validator(_arazzo_schema(line))


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
    """Validate *doc* against the vendored schema for the version it declares.

    A ``1.0.x`` document is checked against the Arazzo 1.0 schema and a ``1.1.x``
    document against the Arazzo 1.1 schema, so 1.1-only constructs (for example an
    ``asyncapi`` source description) pass only in a document that declares 1.1.

    Args:
        doc: Parsed top-level Arazzo document mapping.

    Raises:
        ArazzoStructureError: When the version is missing or unsupported, or the
            document fails schema validation.
    """
    line = arazzo_version_line(doc)
    try:
        _arazzo_validator(line).validate(doc)
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
