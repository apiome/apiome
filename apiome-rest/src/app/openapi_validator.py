"""OpenAPI 3.1 document validator — MFI-22.1 (#4002).

The conversion pipeline (MFI-EPIC-22) emits OpenAPI 3.1 documents *out* of the
canonical model (:class:`app.openapi_emitter.OpenApiEmitter`). This module is the
authority that answers *"is this a schema-valid OpenAPI 3.1 document?"* — the
acceptance-criterion check that the emitter's output "validates against the
OpenAPI 3.1 meta-schema".

It mirrors :mod:`app.schema_validation` (which validates JSON-Schema documents
against the draft 2020-12 meta-schema) but one level up: it validates a whole
**OpenAPI document** against the official OpenAPI 3.1 meta-schema shipped with the
package (``data/openapi_3_1_meta_schema.json`` — the published
``spec.openapis.org/oas/3.1/schema`` file). OpenAPI 3.1 schemas *are* JSON Schema
draft 2020-12, so the meta-schema is itself a 2020-12 schema and the same
:class:`jsonschema.validators.Draft202012Validator` engine already in use here
validates it — fully offline, no network fetch.

Everything is pure and side-effect free so the emitter, its tests, and the
downstream fidelity analyzer (MFI-22.3) can share exactly one validator.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from jsonschema.validators import Draft202012Validator

__all__ = [
    "OPENAPI_31_META_SCHEMA_ID",
    "OpenApiValidationError",
    "load_openapi_31_meta_schema",
    "validate_openapi_document",
    "assert_valid_openapi_document",
]

# The published id of the bundled OpenAPI 3.1 meta-schema (the ``$id`` of the
# ``spec.openapis.org/oas/3.1/schema/2022-10-07`` document).
OPENAPI_31_META_SCHEMA_ID = "https://spec.openapis.org/oas/3.1/schema/2022-10-07"

# The bundled meta-schema, vendored so validation needs no network access.
_META_SCHEMA_PATH = Path(__file__).parent / "data" / "openapi_3_1_meta_schema.json"


def load_openapi_31_meta_schema() -> Dict[str, Any]:
    """Return the bundled OpenAPI 3.1 meta-schema document as a ``dict``."""
    with _META_SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


# One shared validator, built from the OpenAPI 3.1 meta-schema. Constructing it
# once resolves the draft 2020-12 vocabulary registry a single time; every call to
# :func:`validate_openapi_document` reuses it. Loaded lazily so importing this
# module is cheap and never fails at import time on a missing/corrupt resource.
_META_VALIDATOR: Draft202012Validator | None = None


def _validator() -> Draft202012Validator:
    """Return the shared OpenAPI 3.1 meta-schema validator, building it once."""
    global _META_VALIDATOR
    if _META_VALIDATOR is None:
        _META_VALIDATOR = Draft202012Validator(load_openapi_31_meta_schema())
    return _META_VALIDATOR


class OpenApiValidationError(Exception):
    """Raised when a document fails OpenAPI 3.1 meta-schema validation.

    Attributes:
        errors: Structured, field-level errors as returned by
            :func:`validate_openapi_document` (never empty for this exception).
    """

    def __init__(self, errors: List[Dict[str, str]]):
        self.errors = errors
        super().__init__(
            f"Document failed OpenAPI 3.1 meta-schema validation "
            f"({len(errors)} error(s))"
        )


def validate_openapi_document(document: Any) -> List[Dict[str, str]]:
    """Validate a document against the OpenAPI 3.1 meta-schema.

    This answers *"is ``document`` a valid OpenAPI 3.1 document?"* — a missing
    ``info``, a response with no ``description``, a malformed ``paths`` entry, and
    so on are reported here.

    Args:
        document: The candidate OpenAPI document (typically a ``dict``).

    Returns:
        A list of structured errors, deduplicated and ordered by location. Each
        entry has:
            * ``path``: a slash-joined location within the document of the
              offending keyword (``"(root)"`` for the top level);
            * ``message``: the human-readable validator message;
            * ``keyword``: the JSON-Schema keyword that failed (e.g. ``required``).
        The list is empty when the document is a valid OpenAPI 3.1 document.
    """
    errors: List[Dict[str, str]] = []
    seen: set = set()
    for error in sorted(
        _validator().iter_errors(document),
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
        OpenApiValidationError: If the document is not a valid OpenAPI 3.1
            document; the exception carries the field-level error list.
    """
    errors = validate_openapi_document(document)
    if errors:
        raise OpenApiValidationError(errors)
