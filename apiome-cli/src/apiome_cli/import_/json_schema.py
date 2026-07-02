"""JSON Schema 2020-12 document parsing and structural validation.

Supports loading JSON Schema documents from:
- Local files with ``.yaml``, ``.yml``, or ``.json`` extensions.
- HTTP or HTTPS URLs (format from path suffix or ``Content-Type``).
- Standard input when the path argument is ``-``.

Structural validation uses ``jsonschema.Draft202012Validator`` so invalid
schemas fail before REST upload. Callers should map
:class:`JsonSchemaStructureError` to CLI exit code 2 (``EXIT_USAGE``).
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path, PurePath
from typing import Any
from urllib.parse import unquote, urlparse

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError as JsonSchemaValidationError
from jsonschema.validators import validator_for

from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.import_.detect import (
    is_recognized_json_schema_draft_uri,
    json_schema_draft_version_from_uri,
    looks_like_openapi,
)
from apiome_cli.import_.source import (
    is_remote_source,
    parse_mapping_document,
    read_document_text,
    source_basename as _source_basename,
    suffix_from_source,
)

_DRAFT_2020_12_SCHEMA_URIS = frozenset(
    {
        "https://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft/2020-12/hyper-schema",
    }
)
_JSONSCHEMA_META_SCHEMA_URIS: dict[str, str] = {
    "draft-04": "http://json-schema.org/draft-04/schema",
    "draft-06": "http://json-schema.org/draft-06/schema",
    "draft-07": "http://json-schema.org/draft-07/schema",
    "draft-2019-09": "https://json-schema.org/draft/2019-09/schema",
    "draft-2020-12": "https://json-schema.org/draft/2020-12/schema",
}
_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]{0,254}$")


class JsonSchemaTarget(StrEnum):
    """Import destination entity for a standalone JSON Schema file."""

    property = "property"
    properties = "properties"
    schema = "schema"


JSON_SCHEMA_IMPORT_TYPE = "json-schema"


class JsonSchemaStructureError(ValueError):
    """Raised when a JSON Schema document fails structural validation.

    CLI commands should exit with :data:`~apiome_cli.exit_codes.EXIT_USAGE`
    (2) and print :attr:`message` to stderr.
    """

    exit_code: int = EXIT_USAGE

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def load_json_schema_file(
    path: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
) -> dict[str, Any]:
    """Load and parse a JSON Schema document from *path*, a URL, or stdin.

    The format is determined as follows:

    * ``-`` — read from stdin; try JSON first, then YAML on failure.
    * ``*.json`` — parse as JSON.
    * ``*.yaml`` / ``.yml`` — parse as YAML.
    * ``http://`` / ``https://`` URL — fetch the body; use the URL path suffix
      or ``Content-Type`` when present, otherwise try JSON then YAML.

    Args:
        path: File system path, HTTP(S) URL, or ``"-"`` for stdin.
        timeout: HTTP connect + read timeout when fetching a URL.
        verify: Whether to verify TLS certificates for URL fetches.

    Returns:
        The parsed JSON Schema document as a plain Python dict.

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


def validate_json_schema_structure(document: dict[str, Any]) -> None:
    """Reject OpenAPI payloads and validate against Draft 2020-12 meta-schema.

    When ``$schema`` is present it must be one of the official Draft 2020-12
    schema or hyper-schema URIs so local CLI validation matches the REST
    import endpoint. The document is then checked with
    :meth:`~jsonschema.Draft202012Validator.check_schema`.

    Args:
        document: Parsed top-level JSON Schema mapping.

    Raises:
        JsonSchemaStructureError: If the document looks like OpenAPI, declares
            an unsupported ``$schema``, or fails meta-schema validation.
    """
    if looks_like_openapi(document):
        raise JsonSchemaStructureError(
            "Document looks like OpenAPI; use `apiome import openapi` instead."
        )

    schema_uri = document.get("$schema")
    if schema_uri is not None:
        if not isinstance(schema_uri, str) or not schema_uri.strip():
            raise JsonSchemaStructureError(
                "$schema must be a non-empty string URI when present."
            )
        if schema_uri not in _DRAFT_2020_12_SCHEMA_URIS:
            raise JsonSchemaStructureError(
                f"Unsupported $schema {schema_uri!r}; "
                "only Draft 2020-12 schemas are accepted."
            )

    try:
        Draft202012Validator.check_schema(document)
    except (SchemaError, JsonSchemaValidationError) as exc:
        raise JsonSchemaStructureError(str(exc).strip()) from exc


def validate_json_schema_type_structure(document: dict[str, Any]) -> None:
    """Reject OpenAPI payloads and validate JSON Schema type import documents.

    Accepts Draft 4 through 2020-12 when ``$schema`` is present. Documents
    without ``$schema`` are validated with the Draft 2020-12 meta-schema.
    """
    if looks_like_openapi(document):
        raise JsonSchemaStructureError(
            "Document looks like OpenAPI; use `apiome import openapi` instead."
        )

    schema_uri = document.get("$schema")
    if schema_uri is not None:
        if not isinstance(schema_uri, str) or not schema_uri.strip():
            raise JsonSchemaStructureError(
                "$schema must be a non-empty string URI when present."
            )
        if not is_recognized_json_schema_draft_uri(schema_uri):
            raise JsonSchemaStructureError(
                f"Unsupported $schema {schema_uri!r}; "
                "recognized JSON Schema draft URIs are required when $schema is present."
            )

    try:
        _json_schema_type_validator_for(document).check_schema(document)
    except (SchemaError, JsonSchemaValidationError) as exc:
        raise JsonSchemaStructureError(str(exc).strip()) from exc


def _json_schema_type_validator_for(document: dict[str, Any]) -> type:
    """Return the meta-schema validator class for a type-import document."""
    schema_uri = document.get("$schema")
    if not isinstance(schema_uri, str) or not schema_uri.strip():
        return Draft202012Validator

    draft = json_schema_draft_version_from_uri(schema_uri)
    if draft is not None:
        return validator_for({"$schema": _JSONSCHEMA_META_SCHEMA_URIS[draft]})

    try:
        return validator_for(document)
    except Exception:
        return Draft202012Validator


def iter_defs_property_entries(
    document: dict[str, Any],
) -> list[tuple[str, dict[str, Any], str]]:
    """Return ``(name, definition, path)`` for each entry in top-level ``$defs``."""
    defs = document.get("$defs")
    if not isinstance(defs, dict) or not defs:
        return []

    entries: list[tuple[str, dict[str, Any], str]] = []
    for name, body in defs.items():
        if isinstance(name, str) and isinstance(body, dict):
            entries.append((name, body, f"/$defs/{name}"))
    return entries


def detect_target(
    document: dict[str, Any],
    *,
    explicit: JsonSchemaTarget | None = None,
) -> JsonSchemaTarget:
    """Resolve whether the document should become properties, a property, or a schema.

    Args:
        document: Parsed JSON Schema mapping.
        explicit: User override from ``--as`` when set.

    Returns:
        ``property`` for scalar-style definitions; ``properties`` when the document
        is a ``$defs`` bundle without a top-level ``type``; ``schema`` when the
        document has a non-empty top-level ``properties`` object (unless overridden).
    """
    if explicit is not None:
        return explicit
    properties_value = document.get("properties")
    if isinstance(properties_value, dict) and properties_value:
        return JsonSchemaTarget.schema
    if iter_defs_property_entries(document) and document.get("type") is None:
        return JsonSchemaTarget.properties
    return JsonSchemaTarget.property


def infer_name(
    document: dict[str, Any],
    *,
    explicit_name: str | None,
    source_file: str | None,
) -> str:
    """Derive a stable property or schema name from CLI hints and the document.

    Args:
        document: Parsed JSON Schema mapping.
        explicit_name: ``--name`` override when provided.
        source_file: Basename of the import path (``None`` for stdin).

    Returns:
        A name satisfying the database identifier pattern.

    Raises:
        ValueError: When no valid name can be derived.
    """
    if explicit_name is not None and explicit_name.strip():
        candidate = explicit_name.strip()
    else:
        title = document.get("title")
        if isinstance(title, str) and title.strip():
            candidate = title.strip()
        else:
            schema_id = document.get("$id")
            if isinstance(schema_id, str) and schema_id.strip():
                parsed = urlparse(schema_id.strip())
                path = unquote(parsed.path or schema_id.strip())
                candidate = PurePath(path).stem or path.rstrip("/").split("/")[-1]
            elif source_file:
                candidate = PurePath(source_file).stem
            else:
                candidate = "imported-schema"

    candidate = candidate.strip()
    if not _NAME_RE.fullmatch(candidate):
        msg = (
            f"Cannot derive a valid name from {candidate!r}; "
            "provide --name matching [a-zA-Z_][a-zA-Z0-9_-]*."
        )
        raise ValueError(msg)
    return candidate


def source_basename(path: str) -> str | None:
    """Return a filename hint for *path*, or ``None`` when reading stdin."""
    return _source_basename(path)


def load_and_validate_json_schema_file(path: str) -> dict[str, Any]:
    """Load, parse, and structurally validate a JSON Schema document.

    Combines :func:`load_json_schema_file` and
    :func:`validate_json_schema_structure`.

    Args:
        path: File path or ``"-"`` for stdin.

    Returns:
        The parsed and validated JSON Schema document.

    Raises:
        ValueError: On parse errors (see :func:`load_json_schema_file`).
        OSError: If a named file cannot be read.
        JsonSchemaStructureError: If structural validation fails.
    """
    document = load_json_schema_file(path)
    validate_json_schema_structure(document)
    return document
