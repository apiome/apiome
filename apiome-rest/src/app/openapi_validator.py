"""OpenAPI 3.1 / 3.2 document validator — MFI-22.1 (#4002), MFI-30.3 (#4396).

The conversion pipeline (MFI-EPIC-22) emits OpenAPI 3.1 documents *out* of the
canonical model (:class:`app.openapi_emitter.OpenApiEmitter`). This module is the
authority that answers *"is this a schema-valid OpenAPI document?"* — the
acceptance-criterion check that the emitter's output "validates against the
OpenAPI 3.1 meta-schema", and — since MFI-30.3 — that imported OpenAPI 3.2
documents validate against the bundled 3.2 meta-schema.

It mirrors :mod:`app.schema_validation` (which validates JSON-Schema documents
against the draft 2020-12 meta-schema) but one level up: it validates a whole
**OpenAPI document** against the official OpenAPI meta-schema shipped with the
package (``data/openapi_3_1_meta_schema.json`` and ``data/openapi_3_2_meta_schema.json``
— the published ``spec.openapis.org/oas/3.x/schema`` files). OpenAPI 3.1+ schemas
*are* JSON Schema draft 2020-12, so each meta-schema is itself a 2020-12 schema
and the same :class:`jsonschema.validators.Draft202012Validator` engine already in
use here validates it — fully offline, no network fetch.

Everything is pure and side-effect free so the emitter, its tests, and the
downstream fidelity analyzer (MFI-22.3) can share exactly one validator.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema.validators import Draft202012Validator

__all__ = [
    "OPENAPI_31_META_SCHEMA_ID",
    "OPENAPI_32_META_SCHEMA_ID",
    "OpenApiValidationError",
    "load_openapi_31_meta_schema",
    "load_openapi_32_meta_schema",
    "validate_openapi_document",
    "assert_valid_openapi_document",
]

# The published id of the bundled OpenAPI 3.1 meta-schema (the ``$id`` of the
# ``spec.openapis.org/oas/3.1/schema/2022-10-07`` document).
OPENAPI_31_META_SCHEMA_ID = "https://spec.openapis.org/oas/3.1/schema/2022-10-07"
# The published id of the bundled OpenAPI 3.2 meta-schema.
OPENAPI_32_META_SCHEMA_ID = "https://spec.openapis.org/oas/3.2/schema/2025-11-23"

_DATA_DIR = Path(__file__).parent / "data"
_META_SCHEMA_PATHS = {
    "3.1": _DATA_DIR / "openapi_3_1_meta_schema.json",
    "3.2": _DATA_DIR / "openapi_3_2_meta_schema.json",
}
_OPENAPI_VERSION_RE = re.compile(r"^3\.(\d+)")


def load_openapi_31_meta_schema() -> Dict[str, Any]:
    """Return the bundled OpenAPI 3.1 meta-schema document as a ``dict``."""
    with _META_SCHEMA_PATHS["3.1"].open(encoding="utf-8") as handle:
        return json.load(handle)


def load_openapi_32_meta_schema() -> Dict[str, Any]:
    """Return the bundled OpenAPI 3.2 meta-schema document as a ``dict``."""
    with _META_SCHEMA_PATHS["3.2"].open(encoding="utf-8") as handle:
        return json.load(handle)


# Shared validators, built once per meta-schema version.
_META_VALIDATORS: Dict[str, Draft202012Validator] = {}


def _openapi_minor_version(document: Any) -> Optional[str]:
    """Return the meta-schema bucket key (``3.1`` / ``3.2``) for ``document``."""
    if not isinstance(document, dict):
        return None
    version = document.get("openapi")
    if not isinstance(version, str):
        return None
    match = _OPENAPI_VERSION_RE.match(version)
    if not match:
        return None
    minor = int(match.group(1))
    if minor >= 2:
        return "3.2"
    if minor == 1:
        return "3.1"
    return "3.1"


def _validator_for(document: Any) -> Draft202012Validator:
    """Return the shared meta-schema validator for ``document``'s OpenAPI version."""
    bucket = _openapi_minor_version(document) or "3.1"
    cached = _META_VALIDATORS.get(bucket)
    if cached is not None:
        return cached
    loader = load_openapi_32_meta_schema if bucket == "3.2" else load_openapi_31_meta_schema
    validator = Draft202012Validator(loader())
    _META_VALIDATORS[bucket] = validator
    return validator


class OpenApiValidationError(Exception):
    """Raised when a document fails OpenAPI meta-schema validation.

    Attributes:
        errors: Structured, field-level errors as returned by
            :func:`validate_openapi_document` (never empty for this exception).
    """

    def __init__(self, errors: List[Dict[str, str]]):
        self.errors = errors
        super().__init__(
            f"Document failed OpenAPI meta-schema validation ({len(errors)} error(s))"
        )


def validate_openapi_document(document: Any) -> List[Dict[str, str]]:
    """Validate a document against the appropriate OpenAPI meta-schema.

    Selects the bundled 3.1 or 3.2 meta-schema from the document's declared
    ``openapi`` version string. Documents without a recognizable ``openapi: 3.x``
    marker fall back to the 3.1 schema for backward compatibility.

    Args:
        document: The candidate OpenAPI document (typically a ``dict``).

    Returns:
        A list of structured errors, deduplicated and ordered by location. Each
        entry has:
            * ``path``: a slash-joined location within the document of the
              offending keyword (``"(root)"`` for the top level);
            * ``message``: the human-readable validator message;
            * ``keyword``: the JSON-Schema keyword that failed (e.g. ``required``).
        The list is empty when the document is valid.
    """
    errors: List[Dict[str, str]] = []
    seen: set = set()
    for error in sorted(
        _validator_for(document).iter_errors(document),
        key=lambda e: list(map(str, e.absolute_path)),
    ):
        path = "/".join(str(part) for part in error.absolute_path)
        # The meta-schema is a union of subschemas, so a single structural fault
        # can surface from several branches with the same message; collapse those
        # to one field-level error per (location, message).
        dedupe_key = (path, error.message)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        errors.append(
            {
                "path": path or "(root)",
                "message": error.message,
                "keyword": str(error.validator),
            }
        )
    return errors


def assert_valid_openapi_document(document: Any) -> None:
    """Validate ``document`` and raise :class:`OpenApiValidationError` if invalid.

    Args:
        document: The candidate OpenAPI document.

    Raises:
        OpenApiValidationError: If the document is not valid; the exception carries
            the field-level error list.
    """
    errors = validate_openapi_document(document)
    if errors:
        raise OpenApiValidationError(errors)
