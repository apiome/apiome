"""OpenAPI document parsing and structural validation.

Supports loading OpenAPI documents from:
- Local files with ``.yaml``, ``.yml``, or ``.json`` extensions.
- HTTP or HTTPS URLs (format from path suffix or ``Content-Type``).
- Standard input when the path argument is ``-``.

The module detects the format automatically (YAML vs JSON) based on the
file extension for named files, and attempts both parsers for stdin.

Structural validation uses ``openapi-spec-validator`` and supports OpenAPI
2.0 (Swagger), 3.0.x, 3.1.x, and 3.2.x.  Callers should map
:class:`OpenApiStructureError` to CLI exit code 2 (``EXIT_USAGE``).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

from openapi_schema_validator import (
    OAS30Validator,
    OAS31Validator,
    OAS32Validator,
)
from openapi_spec_validator import validate as validate_openapi_spec
from openapi_spec_validator.validation.exceptions import (
    OpenAPIValidationError,
    ValidatorDetectError,
)
from referencing.exceptions import PointerToNowhere, Unresolvable
from openapi_spec_validator.versions.consts import (
    OPENAPIV2,
    OPENAPIV30,
    OPENAPIV31,
    OPENAPIV32,
)
from openapi_spec_validator.versions.datatypes import SpecVersion
from openapi_spec_validator.versions.exceptions import OpenAPIVersionNotFound
from openapi_spec_validator.versions.shortcuts import get_spec_version

from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.import_.openapi_path_query_string import (
    normalize_paths_with_embedded_query_strings,
)
from apiome_cli.import_.openapi_path_template_dedup import (
    merge_equivalent_path_templates,
)
from apiome_cli.import_.schema_type_coercion import (
    SchemaTypeCoercionWarning,
    coerce_empty_response_descriptions,
    coerce_openapi_schema_type_mismatches,
    restore_oas30_numeric_exclusive_bounds_for_spec_validation,
)
from apiome_cli.import_.source import (
    is_local_file_source,
    is_remote_source,
    parse_mapping_document,
    read_document_text,
    suffix_from_source,
)

_CODE_EXTERNAL_REF_NOT_FOLLOWED = "external_ref_not_followed"

# Supported OpenAPI / Swagger families for detection reporting.
_SUPPORTED_SPEC_VERSIONS: tuple[SpecVersion, ...] = (
    OPENAPIV2,
    OPENAPIV30,
    OPENAPIV31,
    OPENAPIV32,
)
_SUPPORTED_VERSION_KEYWORDS: tuple[str, ...] = tuple(
    dict.fromkeys(spec_version.keyword for spec_version in _SUPPORTED_SPEC_VERSIONS)
)


@dataclasses.dataclass(frozen=True)
class OpenApiVersionInfo:
    """Detected OpenAPI or Swagger version for a parsed document.

    Attributes:
        keyword: Top-level version field name (``openapi`` or ``swagger``).
        version: Raw version string from the document (e.g. ``3.1.0``).
        family: Normalised family label (e.g. ``3.1.x``, ``2.0``).
    """

    keyword: str
    version: str
    family: str


def validation_base_uri(source: str | None) -> str:
    """Return the document base URI for resolving relative ``$ref`` values."""
    if not source or source == "-":
        return ""
    if is_remote_source(source):
        return source
    if is_local_file_source(source):
        return Path(source).resolve().as_uri()
    return ""


def _is_external_file_ref(ref: str) -> bool:
    """Return whether *ref* points outside the current document (file or URL)."""
    if not ref or ref.startswith("#"):
        return False
    if ref.startswith(("http://", "https://")):
        return True
    path_part = ref.split("#", 1)[0]
    if not path_part:
        return False
    if path_part.startswith(("./", "../")):
        return True
    lower = path_part.lower()
    return lower.endswith((".json", ".yaml", ".yml"))


def _unresolved_ref_message(ref: str) -> str:
    return (
        f"Unresolved $ref {ref!r}: reference target could not be loaded. "
        "For file imports, ensure sibling files exist next to the spec."
    )


def _handle_unresolvable_ref(
    exc: Unresolvable,
    *,
    version_info: OpenApiVersionInfo,
    preparation_warnings: list[SchemaTypeCoercionWarning] | None,
) -> OpenApiVersionInfo:
    ref = getattr(exc, "ref", None)
    ref_str = ref if isinstance(ref, str) else str(ref) if ref is not None else ""
    message = (
        _unresolved_ref_message(ref_str)
        if ref_str
        else "Unresolved $ref: reference target could not be loaded."
    )
    if ref_str and _is_external_file_ref(ref_str) and preparation_warnings is not None:
        preparation_warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_EXTERNAL_REF_NOT_FOLLOWED,
                message=(
                    f"External $ref {ref_str!r} was not resolved during validation; "
                    "import will not follow this reference."
                ),
                path=ref_str,
            )
        )
        return version_info
    raise OpenApiStructureError(message) from exc


class OpenApiStructureError(ValueError):
    """Raised when an OpenAPI document fails structural validation.

    CLI commands should exit with :data:`~apiome_cli.exit_codes.EXIT_USAGE`
    (2) and print :attr:`message` to stderr.
    """

    exit_code: int = EXIT_USAGE

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def load_openapi_file(
    path: str,
    *,
    timeout: float = 30.0,
    verify: bool = True,
) -> dict[str, Any]:
    """Load and parse an OpenAPI document from *path*, a URL, or stdin.

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
        The parsed OpenAPI document as a plain Python dict.

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


def _spec_version_family(spec_version: SpecVersion) -> str:
    """Return a human-readable family label for *spec_version*."""
    if spec_version == OPENAPIV2:
        return "2.0"
    return f"{spec_version.major}.{spec_version.minor}.x"


def detect_openapi_version(spec: dict[str, Any]) -> OpenApiVersionInfo:
    """Detect the OpenAPI or Swagger version of a parsed document.

    Supports Swagger 2.0 and OpenAPI 3.0.x, 3.1.x, and 3.2.x per
    ``openapi-spec-validator`` version tables.

    Args:
        spec: Parsed top-level OpenAPI document mapping.

    Returns:
        :class:`OpenApiVersionInfo` with the version field keyword, raw
        version string, and normalised family label.

    Raises:
        OpenApiStructureError: If no supported ``openapi`` / ``swagger`` version
            field is present or the version is not recognised.
    """
    for keyword in _SUPPORTED_VERSION_KEYWORDS:
        raw = spec.get(keyword)
        if isinstance(raw, str) and raw.strip():
            try:
                detected = get_spec_version(spec)
            except OpenAPIVersionNotFound as exc:
                supported = ", ".join(_spec_version_family(v) for v in _SUPPORTED_SPEC_VERSIONS)
                raise OpenApiStructureError(
                    f"Unsupported {keyword} version {raw!r}. "
                    f"Supported families: {supported}."
                ) from exc
            return OpenApiVersionInfo(
                keyword=detected.keyword,
                version=raw.strip(),
                family=_spec_version_family(detected),
            )

    supported = ", ".join(_spec_version_family(v) for v in _SUPPORTED_SPEC_VERSIONS)
    raise OpenApiStructureError(
        "OpenAPI document must include a supported top-level version field "
        f"({supported})."
    )


def _prepare_openapi_for_validation(
    spec: dict[str, Any],
) -> tuple[dict[str, Any], tuple[SchemaTypeCoercionWarning, ...]]:
    """Apply the same in-memory normalizations REST uses before OpenAPI validation."""
    working, coercion_warnings = coerce_openapi_schema_type_mismatches(spec)
    working, response_description_warnings = coerce_empty_response_descriptions(working)
    working, query_path_warnings = normalize_paths_with_embedded_query_strings(working)
    working, path_merge_warnings = merge_equivalent_path_templates(working)
    return working, (
        coercion_warnings
        + response_description_warnings
        + query_path_warnings
        + path_merge_warnings
    )


# Keys whose presence marks a node as a Schema Object (so its sibling
# ``default`` / ``example`` is a value to validate against that schema).
_SCHEMA_MARKER_KEYS = (
    "type",
    "enum",
    "properties",
    "items",
    "allOf",
    "anyOf",
    "oneOf",
    "not",
    "format",
    "additionalProperties",
    "required",
    "patternProperties",
)


def _schema_value_validator_cls(version_info: OpenApiVersionInfo) -> Any:
    """Pick the OAS value-validator class matching the document version."""
    version = getattr(version_info, "version", None)
    minor = getattr(version, "minor", None)
    if getattr(version, "major", None) == 3 and minor == 1:
        return OAS31Validator
    if getattr(version, "major", None) == 3 and minor == 2:
        return OAS32Validator
    # OpenAPI 3.0.x and Swagger 2.0 both validate values with the 3.0 dialect
    # (matching openapi-spec-validator's own keyword registry).
    return OAS30Validator


def _looks_like_schema(node: dict[str, Any]) -> bool:
    return any(key in node for key in _SCHEMA_MARKER_KEYS)


def _drop_nonconforming_schema_values(
    node: Any,
    validator_cls: Any,
    removed: list[str],
    pointer: str = "",
) -> None:
    """Recursively remove schema ``default`` / ``example`` values that fail their
    own schema, recording an RFC 6901 pointer for each removal.

    Third-party specs (e.g. those in the openapi-directory) frequently carry
    documentation-placeholder defaults/examples like ``"<all available types>"``
    that do not satisfy the schema's ``enum`` / ``type``. These advisory values
    should not abort an import. Nodes whose validation needs ``$ref`` resolution
    are left untouched (validation raises and is treated as "cannot judge").
    """
    if isinstance(node, dict):
        if _looks_like_schema(node) and "$ref" not in node:
            base = {k: v for k, v in node.items() if k not in ("default", "example")}
            for keyword in ("default", "example"):
                if keyword not in node:
                    continue
                try:
                    errors = list(validator_cls(base).iter_errors(node[keyword]))
                except Exception:  # noqa: BLE001 — unresolved $ref etc.: cannot judge, keep it
                    errors = []
                if errors:
                    del node[keyword]
                    removed.append(f"{pointer}/{keyword}")
        for key, value in list(node.items()):
            _drop_nonconforming_schema_values(value, validator_cls, removed, f"{pointer}/{key}")
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _drop_nonconforming_schema_values(item, validator_cls, removed, f"{pointer}/{index}")


def validate_openapi_structure(
    spec: dict[str, Any],
    *,
    source: str | None = None,
    preparation_warnings: list[SchemaTypeCoercionWarning] | None = None,
) -> OpenApiVersionInfo:
    """Validate *spec* against the OpenAPI JSON Schema for its detected version.

    Runs ``openapi-spec-validator`` locally so invalid documents fail before
    REST upload. Schema defaults that disagree with declared ``type`` values are
    coerced when safely recoverable, matching the REST import pipeline.

    Args:
        spec: Parsed top-level OpenAPI document mapping. Coerced defaults are
            written back into this mapping in place.
        source: Import path, URL, or ``"-"`` for stdin. When set, relative
            file ``$ref`` values are resolved from the document location.
        preparation_warnings: When provided, schema coercion warnings are
            appended for the caller to surface. Unresolvable external file
            ``$ref`` values become warnings instead of hard failures.

    Returns:
        Version metadata for the validated document.

    Raises:
        OpenApiStructureError: If version detection or schema validation fails.
            The exception message includes the validator diagnostic.
    """
    coerced, preparation = _prepare_openapi_for_validation(spec)
    spec.clear()
    spec.update(coerced)
    if preparation:
        if preparation_warnings is not None:
            preparation_warnings.extend(preparation)

    version_info = detect_openapi_version(spec)
    restore_oas30_numeric_exclusive_bounds_for_spec_validation(spec)
    base_uri = validation_base_uri(source)
    try:
        validate_openapi_spec(spec, base_uri=base_uri)
    except OpenAPIValidationError as exc:
        # A non-conformant advisory `default` / `example` value (common in
        # third-party specs) should not abort the import. Drop only the offending
        # values, then re-validate; if the document is now valid, continue with a
        # warning. Any remaining failure is structural and is re-raised.
        removed: list[str] = []
        _drop_nonconforming_schema_values(
            spec, _schema_value_validator_cls(version_info), removed
        )
        if not removed:
            raise OpenApiStructureError(str(exc).strip()) from exc
        try:
            validate_openapi_spec(spec, base_uri=base_uri)
        except OpenAPIValidationError as exc2:
            raise OpenApiStructureError(str(exc2).strip()) from exc2
        except Unresolvable as exc2:
            return _handle_unresolvable_ref(
                exc2,
                version_info=version_info,
                preparation_warnings=preparation_warnings,
            )
        if preparation_warnings is not None:
            preview = ", ".join(removed[:5])
            if len(removed) > 5:
                preview += ", …"
            preparation_warnings.append(
                SchemaTypeCoercionWarning(
                    code="schema.value.nonconforming_dropped",
                    message=(
                        f"Dropped {len(removed)} schema default/example value(s) that "
                        f"did not satisfy their schema: {preview}"
                    ),
                    path=removed[0],
                )
            )
    except Unresolvable as exc:
        return _handle_unresolvable_ref(
            exc,
            version_info=version_info,
            preparation_warnings=preparation_warnings,
        )
    except PointerToNowhere as exc:
        pointer = exc.ref if isinstance(getattr(exc, "ref", None), str) else None
        message = f"Unresolved $ref {pointer}: component or pointer target is missing."
        raise OpenApiStructureError(message) from exc
    except ValidatorDetectError as exc:
        raise OpenApiStructureError(
            "Could not determine which OpenAPI validator to use for this document."
        ) from exc
    return version_info


def load_and_validate_openapi_file(path: str) -> tuple[dict[str, Any], OpenApiVersionInfo]:
    """Load, parse, and structurally validate an OpenAPI document.

    Combines :func:`load_openapi_file` and :func:`validate_openapi_structure`.

    Args:
        path: File path or ``"-"`` for stdin.

    Returns:
        Tuple of the parsed document and detected version metadata.

    Raises:
        ValueError: On parse errors (see :func:`load_openapi_file`).
        OSError: If a named file cannot be read.
        OpenApiStructureError: If structural validation fails.
    """
    spec = load_openapi_file(path)
    version_info = validate_openapi_structure(spec, source=path)
    return spec, version_info
