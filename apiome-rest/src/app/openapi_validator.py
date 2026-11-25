"""OpenAPI / Swagger document validator — MFI-22.1 (#4002), MFI-30.3 (#4396), COA-2.2 (#7045).

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

Since COA-2.2 (#7045) every OpenAPI generation has a vendored meta-schema: the
3.0 (``openapi_3_0_meta_schema.json``, ``oas/3.0/schema/2021-09-28``) and Swagger
2.0 (``openapi_2_0_meta_schema.json``) schemas are JSON Schema **draft-04** documents,
so they are checked with :class:`jsonschema.validators.Draft4Validator`. All 3.1.x
patch releases (3.1.0, 3.1.1, 3.1.2) share the 3.1 meta-schema — the patch releases
are clarifications only — and are covered explicitly by the test suite. A document
whose version has no meta-schema is reported as ``not_validated`` by
:func:`validation_status`, never as valid.

Everything is pure and side-effect free so the emitter, its tests, and the
downstream fidelity analyzer (MFI-22.3) can share exactly one validator.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from jsonschema.validators import Draft4Validator, Draft202012Validator

__all__ = [
    "OPENAPI_31_META_SCHEMA_ID",
    "OPENAPI_32_META_SCHEMA_ID",
    "OPENAPI_30_META_SCHEMA_ID",
    "SWAGGER_20_META_SCHEMA_ID",
    "VALIDATED",
    "INVALID",
    "NOT_VALIDATED",
    "OpenApiValidationError",
    "load_openapi_30_meta_schema",
    "load_swagger_20_meta_schema",
    "has_meta_schema",
    "validation_status",
    "load_openapi_31_meta_schema",
    "load_openapi_32_meta_schema",
    "validate_openapi_document",
    "openapi_document_errors_at",
    "assert_valid_openapi_document",
]

# The published id of the bundled OpenAPI 3.1 meta-schema (the ``$id`` of the
# ``spec.openapis.org/oas/3.1/schema/2022-10-07`` document).
OPENAPI_31_META_SCHEMA_ID = "https://spec.openapis.org/oas/3.1/schema/2022-10-07"
# The published id of the bundled OpenAPI 3.2 meta-schema.
OPENAPI_32_META_SCHEMA_ID = "https://spec.openapis.org/oas/3.2/schema/2025-11-23"

# The published id of the bundled OpenAPI 3.0 meta-schema (covers every 3.0.x).
OPENAPI_30_META_SCHEMA_ID = "https://spec.openapis.org/oas/3.0/schema/2021-09-28"
# The Swagger 2.0 meta-schema carries no ``id``; this is its canonical location.
SWAGGER_20_META_SCHEMA_ID = "http://swagger.io/v2/schema.json#"

#: ``validation_status`` verdicts. ``not_validated`` is *not* a pass: it means no
#: meta-schema covers the document, so nothing was checked (the RC7 rule).
VALIDATED = "validated"
INVALID = "invalid"
NOT_VALIDATED = "not_validated"

_DATA_DIR = Path(__file__).parent / "data"
_META_SCHEMA_PATHS = {
    "2.0": _DATA_DIR / "openapi_2_0_meta_schema.json",
    "3.0": _DATA_DIR / "openapi_3_0_meta_schema.json",
    "3.1": _DATA_DIR / "openapi_3_1_meta_schema.json",
    "3.2": _DATA_DIR / "openapi_3_2_meta_schema.json",
}
_OPENAPI_VERSION_RE = re.compile(r"^3\.(\d+)")
_SWAGGER_VERSION_RE = re.compile(r"^2\.0(?:\.\d+)?$")


def load_openapi_31_meta_schema() -> Dict[str, Any]:
    """Return the bundled OpenAPI 3.1 meta-schema document as a ``dict``."""
    with _META_SCHEMA_PATHS["3.1"].open(encoding="utf-8") as handle:
        return json.load(handle)


def load_openapi_32_meta_schema() -> Dict[str, Any]:
    """Return the bundled OpenAPI 3.2 meta-schema document as a ``dict``."""
    with _META_SCHEMA_PATHS["3.2"].open(encoding="utf-8") as handle:
        return json.load(handle)


def load_openapi_30_meta_schema() -> Dict[str, Any]:
    """Return the bundled OpenAPI 3.0 meta-schema document (JSON Schema draft-04)."""
    with _META_SCHEMA_PATHS["3.0"].open(encoding="utf-8") as handle:
        return json.load(handle)


def load_swagger_20_meta_schema() -> Dict[str, Any]:
    """Return the bundled Swagger 2.0 meta-schema document (JSON Schema draft-04)."""
    with _META_SCHEMA_PATHS["2.0"].open(encoding="utf-8") as handle:
        return json.load(handle)


# Shared validators, built once per meta-schema version.
_META_VALIDATORS: Dict[str, Any] = {}


def _openapi_minor_version(document: Any) -> Optional[str]:
    """Return the meta-schema bucket key (``2.0`` / ``3.0`` / ``3.1`` / ``3.2``).

    ``None`` when the document declares no recognizable version.
    """
    if not isinstance(document, dict):
        return None
    swagger = document.get("swagger")
    if isinstance(swagger, str) and _SWAGGER_VERSION_RE.match(swagger):
        return "2.0"
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
    if minor == 0:
        return "3.0"
    return None


def has_meta_schema(document: Any) -> bool:
    """Whether a bundled meta-schema genuinely covers ``document``'s declared version.

    True for Swagger 2.0 and every OpenAPI 3.0.x / 3.1.x / 3.2.x document. False
    for anything else (no version marker, ``openapi: 4.x``, not an object) — such a
    document is *not validated*, and callers must say so rather than report it valid.
    """
    return _openapi_minor_version(document) is not None


def _validator_for(document: Any) -> Any:
    """Return the shared meta-schema validator for ``document``'s version.

    Documents without a recognizable version fall back to the 3.1 schema so
    :func:`validate_openapi_document` still reports their structural faults.
    """
    bucket = _openapi_minor_version(document) or "3.1"
    cached = _META_VALIDATORS.get(bucket)
    if cached is not None:
        return cached
    loaders = {
        "2.0": (Draft4Validator, load_swagger_20_meta_schema),
        "3.0": (Draft4Validator, load_openapi_30_meta_schema),
        "3.1": (Draft202012Validator, load_openapi_31_meta_schema),
        "3.2": (Draft202012Validator, load_openapi_32_meta_schema),
    }
    engine, loader = loaders[bucket]
    validator = engine(loader())
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

    Selects the bundled Swagger 2.0, OpenAPI 3.0, 3.1 or 3.2 meta-schema from the
    document's declared ``swagger`` / ``openapi`` version string. Documents without
    a recognizable marker fall back to the 3.1 schema for backward compatibility —
    use :func:`validation_status` to learn whether a meta-schema really covers it.

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


def _json_pointer(parts: Any) -> str:
    """Render a jsonschema ``absolute_path`` as an RFC 6901 JSON Pointer (``""`` is the root)."""
    return "".join("/" + str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def openapi_document_errors_at(document: Any) -> List[Dict[str, str]]:
    """Validate like :func:`validate_openapi_document`, locating each error by JSON Pointer.

    :func:`validate_openapi_document` joins path segments with ``/`` unescaped, so a path key such
    as ``/pets/{id}`` cannot be told apart from nesting. This variant escapes each segment
    (RFC 6901), so the location can be followed back into the document.

    Args:
        document: The candidate OpenAPI document.

    Returns:
        Errors ordered by location, one per (pointer, message), each with ``pointer`` (``""`` for
        the root), ``message`` and ``keyword``. Empty when the document is valid.
    """
    errors: List[Dict[str, str]] = []
    seen: set = set()
    for error in sorted(
        _validator_for(document).iter_errors(document),
        key=lambda e: list(map(str, e.absolute_path)),
    ):
        pointer = _json_pointer(error.absolute_path)
        if (pointer, error.message) in seen:
            continue
        seen.add((pointer, error.message))
        errors.append({"pointer": pointer, "message": error.message, "keyword": str(error.validator)})
    return errors


def validation_status(document: Any) -> str:
    """Three-state verdict that never says "valid" without having validated.

    Returns:
        :data:`NOT_VALIDATED` when no bundled meta-schema covers the document's
        declared version (nothing was checked); otherwise :data:`INVALID` when the
        meta-schema reports errors, else :data:`VALIDATED`.
    """
    if not has_meta_schema(document):
        return NOT_VALIDATED
    return INVALID if validate_openapi_document(document) else VALIDATED


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
