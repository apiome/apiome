"""Detect whether a parsed document is OpenAPI, Arazzo, or JSON Schema 2020-12."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

_OPENAPI_KEYS = frozenset({"openapi", "swagger"})
_ARAZZO_KEY = "arazzo"
_ARAZZO_FILENAME_SUFFIXES = (".arazzo.yaml", ".arazzo.yml", ".arazzo.json")
_DRAFT_2020_12_SCHEMA_URIS = frozenset(
    {
        "https://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft/2020-12/hyper-schema",
    },
)
_DRAFT_2020_12_URI_FRAGMENT = "draft/2020-12"
_RECOGNIZED_JSON_SCHEMA_DRAFT_FRAGMENTS = (
    "draft/2020-12",
    "draft/2019-09",
    "draft/07",
    "draft/7/schema",
    "draft-07",
    "draft/06",
    "draft/6/schema",
    "draft-06",
    "draft/04",
    "draft/4/schema",
    "draft-04",
)
_CANONICAL_JSON_SCHEMA_URIS = frozenset(
    {
        "https://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft/2020-12/hyper-schema",
        "http://json-schema.org/draft/2020-12/schema",
        "https://json-schema.org/draft/2019-09/schema",
        "https://json-schema.org/draft/2019-09/hyper-schema",
        "http://json-schema.org/draft-06/schema#",
        "http://json-schema.org/draft-06/schema",
        "https://json-schema.org/draft-06/schema#",
        "https://json-schema.org/draft/06/schema",
        "http://json-schema.org/draft-07/schema#",
        "http://json-schema.org/draft-07/schema",
        "https://json-schema.org/draft-07/schema#",
        "https://json-schema.org/draft-07/schema",
        "https://json-schema.org/draft/07/schema",
        "http://json-schema.org/draft-04/schema#",
        "http://json-schema.org/draft-04/schema",
        "https://json-schema.org/draft-04/schema#",
        "https://json-schema.org/draft-04/schema",
        "https://json-schema.org/draft/04/schema",
        "https://json-schema.org/draft/4/schema",
    }
)
_JSON_SCHEMA_VOCABULARY_KEYS = frozenset(
    {
        "$defs",
        "$ref",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "properties",
        "items",
        "type",
        "const",
        "enum",
        "format",
    },
)

ImportCommand = Literal[
    "auto",
    "openapi",
    "swagger",
    "json-schema",
    "json-schema-type",
    "arazzo",
]


class DocumentKind(StrEnum):
    """Classification of a parsed import file."""

    openapi = "openapi"
    arazzo = "arazzo"
    json_schema = "json_schema"
    unknown = "unknown"


def looks_like_openapi(document: dict[str, Any]) -> bool:
    """Return True when the payload declares an OpenAPI or Swagger version."""
    return any(key in document for key in _OPENAPI_KEYS)


def looks_like_arazzo(document: dict[str, Any]) -> bool:
    """Return True when the payload declares an Arazzo version."""
    if looks_like_openapi(document):
        return False
    raw = document.get(_ARAZZO_KEY)
    return isinstance(raw, str) and bool(raw.strip())


def looks_like_arazzo_filename(filename: str | None) -> bool:
    """Return True when *filename* uses an Arazzo naming hint.

    Mirrors the REST repository scanner's filename heuristic: a basename ending
    in ``.arazzo.yaml``, ``.arazzo.yml``, or ``.arazzo.json`` signals an Arazzo
    workflow document. Comparison is case-insensitive. ``None`` (stdin) and
    names without the ``.arazzo.`` infix return ``False``.
    """
    if not filename:
        return False
    return filename.strip().lower().endswith(_ARAZZO_FILENAME_SUFFIXES)


def is_draft_2020_12_schema_uri(schema_uri: str) -> bool:
    """Return True when *schema_uri* identifies JSON Schema Draft 2020-12."""
    normalized = schema_uri.strip()
    if normalized in _DRAFT_2020_12_SCHEMA_URIS:
        return True
    return _DRAFT_2020_12_URI_FRAGMENT in normalized


def is_recognized_json_schema_draft_uri(schema_uri: str) -> bool:
    """Return True when *schema_uri* identifies a supported JSON Schema draft."""
    normalized = schema_uri.strip()
    if normalized in _CANONICAL_JSON_SCHEMA_URIS:
        return True
    lower = normalized.lower()
    return any(fragment in lower for fragment in _RECOGNIZED_JSON_SCHEMA_DRAFT_FRAGMENTS)


def json_schema_draft_version_from_uri(schema_uri: str) -> str | None:
    """Return a normalized draft label for a recognized ``$schema`` URI."""
    normalized = schema_uri.strip().split("#", 1)[0].rstrip("/").lower()
    if not normalized:
        return None
    if "2020-12" in normalized or "draft-2020-12" in normalized:
        return "draft-2020-12"
    if "2019-09" in normalized:
        return "draft-2019-09"
    if (
        "draft-07" in normalized
        or "/draft/07/" in normalized
        or normalized.endswith("/draft/7/schema")
    ):
        return "draft-07"
    if (
        "draft-06" in normalized
        or "/draft/06/" in normalized
        or normalized.endswith("/draft/6/schema")
    ):
        return "draft-06"
    if (
        normalized.endswith("/draft-04/schema")
        or "draft-04" in normalized
        or "/draft/04/" in normalized
        or normalized.endswith("/draft/4/schema")
    ):
        return "draft-04"
    return None


def _has_type_library_container(document: dict[str, Any]) -> bool:
    for key in ("$defs", "definitions"):
        container = document.get(key)
        if isinstance(container, dict) and container:
            return True
    return False


def looks_like_json_schema_type(document: dict[str, Any]) -> bool:
    """Return True when the document is a type library (``$defs``/``definitions`` without ``properties`` or concrete ``type``)."""
    if looks_like_openapi(document):
        return False
    has_properties = isinstance(document.get("properties"), dict) and bool(
        document.get("properties")
    )
    has_type = document.get("type") is not None
    return _has_type_library_container(document) and not has_properties and not has_type


def looks_like_json_schema(document: dict[str, Any]) -> bool:
    """Return True when the payload appears to be a JSON Schema document.

    OpenAPI documents are excluded first. A document with ``$schema`` must
    reference Draft 2020-12. Without ``$schema``, common schema vocabulary keys
    (``type``, ``properties``, ``$ref``, …) indicate JSON Schema.
    """
    if looks_like_openapi(document):
        return False

    schema_uri = document.get("$schema")
    if schema_uri is not None:
        if not isinstance(schema_uri, str) or not schema_uri.strip():
            return False
        return is_draft_2020_12_schema_uri(schema_uri)

    return bool(_JSON_SCHEMA_VOCABULARY_KEYS.intersection(document))


def detect_document_kind(document: dict[str, Any]) -> DocumentKind:
    """Classify *document* for routing to the correct import subcommand.

    Args:
        document: Parsed top-level mapping from an import file.

    Returns:
        :attr:`DocumentKind.openapi` when ``openapi`` or ``swagger`` is present,
        :attr:`DocumentKind.json_schema` for Draft 2020-12 or schema-shaped
        payloads without OpenAPI markers, otherwise :attr:`DocumentKind.unknown`.
    """
    if looks_like_openapi(document):
        return DocumentKind.openapi
    if looks_like_arazzo(document):
        return DocumentKind.arazzo
    if looks_like_json_schema(document):
        return DocumentKind.json_schema
    return DocumentKind.unknown


def recommended_import_command(
    kind: DocumentKind,
    *,
    document: dict[str, Any] | None = None,
) -> str | None:
    """Return the Typer subcommand path for *kind*, if known."""
    if kind is DocumentKind.openapi:
        if document is not None and _has_swagger_version(document):
            return "import swagger"
        return "import openapi"
    if kind is DocumentKind.arazzo:
        return "import arazzo"
    if kind is DocumentKind.json_schema:
        if document is not None and looks_like_json_schema_type(document):
            return "import json-schema-type"
        return "import json-schema"
    return None


def _has_swagger_version(document: dict[str, Any]) -> bool:
    raw = document.get("swagger")
    return isinstance(raw, str) and bool(raw.strip())


def _has_openapi_version(document: dict[str, Any]) -> bool:
    raw = document.get("openapi")
    return isinstance(raw, str) and bool(raw.strip())


def resolve_auto_import_command(
    document: dict[str, Any],
    *,
    filename: str | None = None,
) -> ImportCommand | None:
    """Return the import subcommand for *document* based on top-level format headers.

    Detection uses the document's declarative version fields (``openapi``,
    ``swagger``, ``arazzo``, ``$schema``) and JSON Schema vocabulary markers.
    Content markers always win. When *filename* uses an Arazzo naming hint
    (``*.arazzo.{yaml,yml,json}``) and **no** content marker matched, the
    document is routed to ``arazzo`` as a last resort — rescuing Arazzo files
    whose ``arazzo:`` version line is missing or that would otherwise sniff as
    generic YAML.

    Args:
        document: Parsed top-level mapping from an import file.
        filename: Optional source basename used only for the Arazzo extension
            hint; ``None`` (stdin) disables the hint.
    """
    if _has_swagger_version(document):
        return "swagger"
    if _has_openapi_version(document):
        return "openapi"
    if looks_like_arazzo(document):
        return "arazzo"
    if looks_like_json_schema_type(document):
        return "json-schema-type"
    if looks_like_json_schema(document):
        return "json-schema"
    if looks_like_arazzo_filename(filename):
        return "arazzo"
    return None


def describe_document_format(
    document: dict[str, Any],
    *,
    filename: str | None = None,
) -> str:
    """Return a short human-readable label for detected document headers.

    *filename* enables the Arazzo extension hint label (``Arazzo (by
    filename)``) for documents that lack a content marker but use the
    ``*.arazzo.{yaml,yml,json}`` naming convention, matching the routing in
    :func:`resolve_auto_import_command`.
    """
    if _has_swagger_version(document):
        return f"Swagger {document['swagger'].strip()}"
    if _has_openapi_version(document):
        return f"OpenAPI {document['openapi'].strip()}"
    arazzo = document.get("arazzo")
    if isinstance(arazzo, str) and arazzo.strip():
        return f"Arazzo {arazzo.strip()}"
    schema_uri = document.get("$schema")
    if isinstance(schema_uri, str) and schema_uri.strip():
        return f"JSON Schema ({schema_uri.strip()})"
    if looks_like_json_schema_type(document):
        return "JSON Schema type library ($defs)"
    if looks_like_json_schema(document):
        return "JSON Schema"
    if looks_like_arazzo_filename(filename):
        return "Arazzo (by filename)"
    return "unknown"


def unrecognized_auto_import_message(document: dict[str, Any]) -> str:
    """Build a stderr hint when ``import auto`` cannot classify *document*."""
    headers = sorted(key for key in document if isinstance(key, str))
    if headers:
        preview = ", ".join(headers[:8])
        if len(headers) > 8:
            preview = f"{preview}, …"
        return (
            "Could not determine import type from document headers. "
            f"Top-level keys: {preview}. "
            "Expected one of: openapi, swagger, arazzo, or JSON Schema ($schema / schema vocabulary)."
        )
    return (
        "Could not determine import type: document has no recognizable top-level headers."
    )


def type_library_importer_message() -> str:
    """Build a stderr hint when ``import json-schema`` receives a type library."""
    return (
        "This file looks like a JSON Schema type library ($defs without top-level "
        "properties). Use: apiome import json-schema-type <path>"
    )


def wrong_importer_message(
    detected: DocumentKind,
    *,
    attempted: ImportCommand,
) -> str:
    """Build a stderr message when the user invoked the wrong import command.

    Args:
        detected: Classification from :func:`detect_document_kind`.
        attempted: Subcommand the user ran (``openapi`` or ``json-schema``).

    Returns:
        Human-readable hint naming the command to use instead.
    """
    suggested = recommended_import_command(detected, document=None)
    if suggested is None:
        return (
            f"Cannot import this file with 'import {attempted}': "
            "document type could not be determined."
        )
    if attempted in ("openapi", "swagger") and detected is DocumentKind.json_schema:
        return (
            "This file looks like a JSON Schema (Draft 2020-12) document. "
            f"Use: apiome {suggested} <path>"
        )
    if attempted in ("openapi", "swagger") and detected is DocumentKind.arazzo:
        return (
            "This file looks like an Arazzo 1.0 workflow document. "
            "Use: apiome import arazzo <path>"
        )
    if attempted == "arazzo" and detected is DocumentKind.openapi:
        return (
            "This file looks like an OpenAPI document. "
            "Use: apiome import openapi <path>"
        )
    if attempted == "arazzo" and detected is DocumentKind.json_schema:
        return (
            "This file looks like a JSON Schema (Draft 2020-12) document. "
            f"Use: apiome {suggested} <path>"
        )
    if attempted in ("json-schema", "json-schema-type") and detected is DocumentKind.openapi:
        return (
            "This file looks like an OpenAPI document. "
            "Use: apiome import openapi <path>"
        )
    if attempted in ("json-schema", "json-schema-type") and detected is DocumentKind.arazzo:
        return (
            "This file looks like an Arazzo 1.0 workflow document. "
            "Use: apiome import arazzo <path>"
        )
    return (
        f"Cannot import this file with 'import {attempted}': "
        f"expected {detected.value.replace('_', ' ')} content."
    )
