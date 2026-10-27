"""OpenAPI 3.1 ``components/schemas`` importer for the Primitives registry (#3465).

An OpenAPI 3.1 document keeps its reusable types under ``components.schemas``, and since 3.1
every Schema Object there is a JSON Schema draft 2020-12 schema. This module turns such a
document into the same ``name -> schema`` map the JSON Schema and type-def bundle importers
produce, so the shared import path does the rest unchanged:

* each ``components.schemas`` entry becomes one ``odb.primitives`` row;
* sibling refs (``#/components/schemas/Money``) are rewritten to relative registry refs
  (``./money``) by :func:`app.primitives_rewrite.rewrite_import_schema` (#3463), which lists
  ``#/components/schemas/`` among its intra-source prefixes;
* conflicts, dedupe and the draft 2020-12 validation report come from the import review
  (#3464), and the rewritten edges land in the ``refs`` JSONB column through the resolver.

Only the schemas are read. Paths, parameters, responses and the rest of the document describe
an API, not types, and are ignored. Everything here is pure (no network/DB).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "OPENAPI_SCHEMAS_POINTER",
    "OpenApiComponentsError",
    "parse_openapi_components",
]

# JSON Pointer prefix a ``$ref`` uses to name a sibling component schema in the same document.
OPENAPI_SCHEMAS_POINTER = "#/components/schemas/"

# ``jsonSchemaDialect`` values that mean draft 2020-12: the 2020-12 meta-schema itself, and the
# OpenAPI 3.1 base dialect, which is 2020-12 plus OpenAPI's annotation keywords.
_DRAFT_2020_12_DIALECTS: Tuple[str, ...] = (
    "https://json-schema.org/draft/2020-12/schema",
    "https://spec.openapis.org/oas/3.1/dialect/base",
)

# ``major.minor`` at the start of an ``openapi`` version string (``3.1.0`` → ``3``, ``1``).
_VERSION_PATTERN = re.compile(r"^\s*(\d+)\.(\d+)")


class OpenApiComponentsError(ValueError):
    """Raised when a document cannot be imported as OpenAPI ``components/schemas``.

    Attributes:
        message: The user-facing reason, returned as the 400 ``detail``.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _openapi_version(document: Dict[str, Any]) -> Tuple[int, int, str]:
    """Read and check the document's ``openapi`` version field.

    Args:
        document: The parsed OpenAPI document.

    Returns:
        ``(major, minor, raw)`` for an OpenAPI 3.x document.

    Raises:
        OpenApiComponentsError: When the field is missing, unparseable, or not 3.x — a Swagger
            2.0 document is named as such, since its ``definitions`` import as JSON Schema.
    """
    raw = document.get("openapi")
    if not isinstance(raw, str):
        if "swagger" in document:
            raise OpenApiComponentsError(
                "This is a Swagger 2.0 document, not OpenAPI 3.1. Import it as JSON Schema "
                "to read its 'definitions'."
            )
        raise OpenApiComponentsError(
            "Not an OpenAPI document: the 'openapi' version field is missing."
        )
    match = _VERSION_PATTERN.match(raw)
    if match is None or int(match.group(1)) != 3:
        raise OpenApiComponentsError(
            f"Unsupported OpenAPI version '{raw}'. Expected OpenAPI 3.1."
        )
    return int(match.group(1)), int(match.group(2)), raw


def _dialect_warning(document: Dict[str, Any]) -> Optional[str]:
    """Return a warning when ``jsonSchemaDialect`` names something other than draft 2020-12.

    Args:
        document: The parsed OpenAPI document.

    Returns:
        The warning text, or ``None`` when the dialect is absent (2020-12 by default) or 2020-12.
    """
    dialect = document.get("jsonSchemaDialect")
    if dialect is None:
        return None
    if isinstance(dialect, str) and dialect.rstrip("#") in _DRAFT_2020_12_DIALECTS:
        return None
    return (
        f"The document's jsonSchemaDialect '{dialect}' is not JSON Schema draft 2020-12; "
        "its schemas are validated as draft 2020-12."
    )


def parse_openapi_components(document: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Extract an OpenAPI 3.1 document's ``components.schemas`` as import definitions.

    Each entry becomes one definition, keyed by its component name and in declaration order.
    Schemas are returned as written: ``$ref`` rewrite, validation and classification happen in
    the shared import path, so a malformed component is reported per type by the review rather
    than failing the whole document here.

    Args:
        document: The parsed source document.

    Returns:
        ``(definitions, warnings)`` — the ``name -> schema`` map and non-fatal warnings (an
        OpenAPI 3.0 document read as 3.1, or a ``jsonSchemaDialect`` other than 2020-12).

    Raises:
        OpenApiComponentsError: When the document is not an OpenAPI 3.x object, or carries no
            ``components.schemas`` entries.
    """
    if not isinstance(document, dict):
        raise OpenApiComponentsError("An OpenAPI document must be a JSON or YAML object.")

    _, minor, raw_version = _openapi_version(document)
    warnings: List[str] = []
    if minor == 0:
        # 3.0 Schema Objects are a JSON Schema subset with their own keywords (nullable, boolean
        # exclusiveMinimum); they are read as 3.1 schemas, so some may fail 2020-12 validation.
        warnings.append(
            f"This is an OpenAPI {raw_version} document; its schemas are read as OpenAPI 3.1 "
            "(JSON Schema draft 2020-12), so 3.0-only keywords may not validate."
        )
    dialect_warning = _dialect_warning(document)
    if dialect_warning:
        warnings.append(dialect_warning)

    components = document.get("components")
    schemas = components.get("schemas") if isinstance(components, dict) else None
    if not isinstance(schemas, dict) or not schemas:
        raise OpenApiComponentsError(
            "No components.schemas found in the OpenAPI document. Its reusable types must be "
            "declared under components/schemas."
        )

    return dict(schemas), warnings
