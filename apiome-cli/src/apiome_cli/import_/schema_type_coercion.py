"""Coerce schema defaults and examples that disagree with declared JSON Schema types.

Mirrors ``apiome-rest/src/import_/schema_type_coercion.py`` so local
pre-upload validation accepts the same recoverable OpenAPI quirks as the REST
import pipeline. Keep both files in sync when changing coercion behavior.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

_CODE_SCHEMA_DEFAULT_TYPE_COERCION = "schema_default_type_coercion"
_CODE_SCHEMA_EXAMPLE_TYPE_COERCION = "schema_example_type_coercion"
_CODE_SCHEMA_NULL_DEFAULT_NORMALIZATION = "schema_null_default_normalization"
_CODE_SWAGGER_LEGACY_TYPE_NORMALIZED = "swagger_legacy_type_normalized"
_CODE_INVALID_SCHEMA_TYPE_REMOVED = "invalid_schema_type_removed"
_CODE_NESTED_SCHEMA_TYPE_HOISTED = "nested_schema_type_hoisted"
_CODE_SCHEMA_ENUM_DEFAULT_REMOVED = "schema_enum_default_removed"
_CODE_SCHEMA_ENUM_TYPE_COERCION = "schema_enum_type_coercion"
_CODE_SCHEMA_ENUM_DEDUPLICATED = "schema_enum_deduplicated"
_CODE_SCHEMA_REQUIRED_NORMALIZED = "schema_required_normalized"
_CODE_SCHEMA_NUMERIC_DEFAULT_REMOVED = "schema_numeric_default_removed"
_CODE_SCHEMA_DEFAULT_REMOVED = "schema_default_removed"
_CODE_SCHEMA_DATETIME_DEFAULT_NORMALIZED = "schema_datetime_default_normalized"
_CODE_SCHEMA_FORMAT_DEFAULT_REMOVED = "schema_format_default_removed"
_CODE_SCHEMA_PATTERN_DEFAULT_REMOVED = "schema_pattern_default_removed"
_CODE_INVALID_SCHEMA_PATTERN_REMOVED = "invalid_schema_pattern_removed"
_CODE_SCHEMA_BOOLEAN_LITERAL_NORMALIZED = "schema_boolean_literal_normalized"
_CODE_SCHEMA_EXAMPLES_NORMALIZED = "schema_examples_normalized"
_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED = "legacy_exclusive_bound_normalized"
_CODE_RESPONSE_STATUS_CODE_KEY_NORMALIZED = "response_status_code_key_normalized"
_CODE_OPENAPI_BOOLEAN_FIELD_COERCED = "openapi_boolean_field_coerced"
_CODE_EMPTY_PARAMETER_NAME_REMOVED = "empty_parameter_name_removed"
_CODE_INDEXED_COMPOSITOR_NORMALIZED = "indexed_compositor_normalized"
_CODE_EMPTY_RESPONSE_DESCRIPTION_COERCION = "empty_response_description_coercion"
_EMPTY_RESPONSE_DESCRIPTION_PLACEHOLDER = "<No description>"
_JSON_SCHEMA_SIMPLE_TYPES = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)
_DOMAIN_SCHEMA_TYPE_MARKERS = frozenset(
    {"graphql", "openapi1", "openapi2", "openapi3", "raml"}
)
_MEDIA_TYPE_PATTERN = re.compile(r"^[a-zA-Z0-9!#$&^_.+-]+/[a-zA-Z0-9!#$&^_.+-]+$")
_DATETIME_DEFAULT_WITHOUT_TZ = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$"
)
_RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_OPENAPI_OPERATION_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace", "query"}
)
_COMPOSITOR_LIST_KEYS = frozenset({"allOf", "anyOf", "oneOf"})
_COMPONENTS_SCHEMA_REF_PREFIX = "#/components/schemas/"


@dataclass(frozen=True, slots=True)
class SchemaTypeCoercionWarning:
    """Import warning emitted when a schema value is coerced to match ``type``."""

    code: str
    message: str
    path: str


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _join_pointer(base: str, token: str) -> str:
    escaped = _escape_json_pointer_token(token)
    if base == "/":
        return f"/{escaped}"
    return f"{base}/{escaped}"


def _iter_mutable_objects(
    value: Any,
    *,
    pointer: str = "/",
) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(pointer, object)`` for every mutable mapping node in *value*."""
    if isinstance(value, dict):
        yield pointer, value
        for key, child in value.items():
            if isinstance(key, str):
                yield from _iter_mutable_objects(
                    child,
                    pointer=_join_pointer(pointer, key),
                )
            else:
                yield from _iter_mutable_objects(child, pointer=pointer)
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _iter_mutable_objects(
                child,
                pointer=_join_pointer(pointer, str(index)),
            )


def _primary_schema_type(schema_type: Any) -> str | None:
    if isinstance(schema_type, str):
        return schema_type
    if isinstance(schema_type, list):
        for item in schema_type:
            if item != "null" and isinstance(item, str):
                return item
    return None


def _value_matches_schema_type(value: Any, schema_type: str) -> bool:
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "object":
        return isinstance(value, dict)
    return True


def _try_parse_json_array_string(value: str) -> list[Any] | None:
    trimmed = value.strip()
    if not trimmed.startswith("["):
        return None
    try:
        parsed = json.loads(trimmed)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _coerce_value_to_schema_type(value: Any, schema_type: str) -> Any | None:
    if _value_matches_schema_type(value, schema_type):
        return value

    if schema_type == "integer":
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                return None
            try:
                if trimmed.isdecimal() or (
                    trimmed.startswith("-") and trimmed[1:].isdecimal()
                ):
                    return int(trimmed)
                as_float = float(trimmed)
            except ValueError:
                return None
            else:
                if as_float.is_integer():
                    return int(as_float)
                return None
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return None

    if schema_type == "number":
        if isinstance(value, str):
            trimmed = value.strip()
            if not trimmed:
                return None
            try:
                return float(trimmed)
            except ValueError:
                return None
        if isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        return None

    if schema_type == "boolean":
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        if isinstance(value, int) and not isinstance(value, bool):
            if value == 1:
                return True
            if value == 0:
                return False
        if isinstance(value, float) and not isinstance(value, bool):
            if value == 1.0:
                return True
            if value == 0.0:
                return False
        return None

    if schema_type == "string":
        if isinstance(value, list):
            if len(value) == 1:
                return _coerce_value_to_schema_type(value[0], "string")
            return None
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return None

    if schema_type == "array":
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return None
        if value is None:
            return None
        if isinstance(value, str):
            parsed = _try_parse_json_array_string(value)
            if parsed is not None:
                return parsed
            if "," in value:
                parts = [part.strip() for part in value.split(",") if part.strip()]
                if parts:
                    return parts
            return [value]
        return [value]

    return None


def _append_coercion_warning(
    *,
    warnings: list[SchemaTypeCoercionWarning],
    code: str,
    label: str,
    schema_type: str,
    value: Any,
    coerced: Any,
    path: str,
) -> None:
    warnings.append(
        SchemaTypeCoercionWarning(
            code=code,
            message=(
                f"Schema {label} {value!r} was coerced to {schema_type} value "
                f"{coerced!r} to satisfy the declared type."
            ),
            path=path,
        )
    )


def _coerce_field_to_schema_type(
    target: dict[str, Any],
    *,
    field: str,
    schema_type: str,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
    code: str,
    label: str,
) -> None:
    if field not in target:
        return
    value = target[field]
    if value is None and _schema_allows_null(target):
        return
    if _value_matches_schema_type(value, schema_type):
        return
    if schema_type == "array" and isinstance(value, str):
        parsed = _try_parse_json_array_string(value)
        if parsed is not None:
            target[field] = parsed
            return
    coerced = _coerce_value_to_schema_type(value, schema_type)
    if coerced is not None:
        if type(coerced) is not type(value) or coerced != value:
            target[field] = coerced
            _append_coercion_warning(
                warnings=warnings,
                code=code,
                label=label,
                schema_type=schema_type,
                value=value,
                coerced=coerced,
                path=_join_pointer(pointer, field),
            )
        return
    if field != "default":
        return
    removed = target.pop(field)
    warnings.append(
        SchemaTypeCoercionWarning(
            code=_CODE_SCHEMA_DEFAULT_REMOVED,
            message=(
                f"Removed schema default {removed!r} because it cannot be coerced "
                f"to the declared type {schema_type!r}."
            ),
            path=_join_pointer(pointer, field),
        )
    )


def _coerce_schema_enum_values(
    node: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if "$ref" in node:
        return
    enum_values = node.get("enum")
    if not isinstance(enum_values, list) or not enum_values:
        return
    schema_type = _primary_schema_type(node.get("type"))
    if schema_type is None or schema_type == "boolean":
        return
    coerced_values: list[Any] = []
    for value in enum_values:
        if _value_matches_schema_type(value, schema_type):
            coerced_values.append(value)
            continue
        coerced = _coerce_value_to_schema_type(value, schema_type)
        coerced_values.append(coerced if coerced is not None else value)
    if coerced_values == enum_values:
        return
    node["enum"] = coerced_values
    warnings.append(
        SchemaTypeCoercionWarning(
            code=_CODE_SCHEMA_ENUM_TYPE_COERCION,
            message=(
                f"Schema enum {enum_values!r} was coerced to {coerced_values!r} "
                f"to satisfy the declared type {schema_type!r}."
            ),
            path=_join_pointer(pointer, "enum"),
        )
    )


def _coerce_schema_defaults(
    node: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if "$ref" in node:
        return
    if "default" not in node:
        return
    schema_type = _primary_schema_type(node.get("type"))
    if schema_type is None:
        return
    _coerce_field_to_schema_type(
        node,
        field="default",
        schema_type=schema_type,
        pointer=pointer,
        warnings=warnings,
        code=_CODE_SCHEMA_DEFAULT_TYPE_COERCION,
        label="default",
    )


def _coerce_schema_array_examples(
    node: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if "$ref" in node:
        return
    if _primary_schema_type(node.get("type")) != "array":
        return

    _coerce_field_to_schema_type(
        node,
        field="example",
        schema_type="array",
        pointer=pointer,
        warnings=warnings,
        code=_CODE_SCHEMA_EXAMPLE_TYPE_COERCION,
        label="example",
    )

    examples = node.get("examples")
    if not isinstance(examples, list):
        return
    for index, item in enumerate(examples):
        if isinstance(item, list):
            continue
        if isinstance(item, str):
            parsed = _try_parse_json_array_string(item)
            if parsed is not None:
                examples[index] = parsed
                continue
        coerced = _coerce_value_to_schema_type(item, "array")
        if coerced is None or coerced == item:
            continue
        examples[index] = coerced
        _append_coercion_warning(
            warnings=warnings,
            code=_CODE_SCHEMA_EXAMPLE_TYPE_COERCION,
            label="examples entry",
            schema_type="array",
            value=item,
            coerced=coerced,
            path=_join_pointer(pointer, f"examples/{index}"),
        )


def _coerce_container_array_values(
    node: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    schema = node.get("schema")
    if not isinstance(schema, dict) or "$ref" in schema:
        return
    if _primary_schema_type(schema.get("type")) != "array":
        return

    _coerce_field_to_schema_type(
        node,
        field="default",
        schema_type="array",
        pointer=pointer,
        warnings=warnings,
        code=_CODE_SCHEMA_DEFAULT_TYPE_COERCION,
        label="default",
    )
    _coerce_field_to_schema_type(
        node,
        field="example",
        schema_type="array",
        pointer=pointer,
        warnings=warnings,
        code=_CODE_SCHEMA_EXAMPLE_TYPE_COERCION,
        label="example",
    )

    examples = node.get("examples")
    if not isinstance(examples, dict):
        return
    for key, example_obj in examples.items():
        if not isinstance(example_obj, dict) or "value" not in example_obj:
            continue
        value = example_obj["value"]
        if isinstance(value, list):
            continue
        if isinstance(value, str):
            parsed = _try_parse_json_array_string(value)
            if parsed is not None:
                example_obj["value"] = parsed
                continue
        coerced = _coerce_value_to_schema_type(value, "array")
        if coerced is None or coerced == value:
            continue
        example_obj["value"] = coerced
        _append_coercion_warning(
            warnings=warnings,
            code=_CODE_SCHEMA_EXAMPLE_TYPE_COERCION,
            label="example value",
            schema_type="array",
            value=value,
            coerced=coerced,
            path=_join_pointer(pointer, f"examples/{key}/value"),
        )


def _openapi_uses_nullable_type_array(document: dict[str, Any]) -> bool:
    """Return True when OpenAPI 3.1+ nullability should use a ``type`` array."""
    raw = document.get("openapi")
    if not isinstance(raw, str):
        return False
    parts = raw.strip().split(".")
    if len(parts) < 2:
        return False
    try:
        major = int(parts[0])
        minor = int(parts[1])
    except ValueError:
        return False
    return major > 3 or (major == 3 and minor >= 1)


def _schema_allows_null(node: dict[str, Any]) -> bool:
    if node.get("nullable") is True:
        return True
    schema_type = node.get("type")
    if isinstance(schema_type, list) and "null" in schema_type:
        return True
    for composite_key in ("anyOf", "oneOf", "allOf"):
        composite = node.get(composite_key)
        if isinstance(composite, list):
            for item in composite:
                if isinstance(item, dict) and item.get("type") == "null":
                    return True
    return False


def _ensure_nullable_for_null_default(
    node: dict[str, Any],
    *,
    use_type_array: bool,
) -> str | None:
    """Return a short description of the nullability encoding that was added."""
    if use_type_array:
        schema_type = node.get("type")
        if isinstance(schema_type, str):
            if schema_type == "null":
                return None
            node["type"] = [schema_type, "null"]
            return f"type {schema_type!r} extended with 'null'"
        if isinstance(schema_type, list):
            if "null" in schema_type:
                return None
            node["type"] = [*schema_type, "null"]
            return "type array extended with 'null'"
        return None
    if node.get("nullable") is True:
        return None
    node["nullable"] = True
    return "nullable=true"


def _normalize_null_schema_default(
    node: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
    use_type_array: bool,
) -> None:
    if "$ref" in node:
        return
    if "default" not in node or node.get("default") is not None:
        return
    if node.get("type") is None:
        return
    if _schema_allows_null(node):
        return
    encoding = _ensure_nullable_for_null_default(node, use_type_array=use_type_array)
    if encoding is None:
        return
    warnings.append(
        SchemaTypeCoercionWarning(
            code=_CODE_SCHEMA_NULL_DEFAULT_NORMALIZATION,
            message=(
                f"Schema default is null but nullability was not declared; "
                f"added {encoding} for OpenAPI validation."
            ),
            path=pointer,
        )
    )


def _is_swagger_2_document(document: dict[str, Any]) -> bool:
    swagger = document.get("swagger")
    return isinstance(swagger, str) and swagger.strip().startswith("2.")


def _normalize_swagger_legacy_schema_types(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Normalize legacy Swagger ``type: file`` schemas before JSON Schema validation."""
    for pointer, node in _iter_mutable_objects(document):
        if node.get("type") != "file":
            continue
        node["type"] = "string"
        node["format"] = "binary"
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SWAGGER_LEGACY_TYPE_NORMALIZED,
                message=(
                    "Legacy schema type 'file' was normalized to "
                    "string/binary for validation."
                ),
                path=pointer,
            )
        )


def _normalize_numeric_type_with_string_format(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Normalize upgraded Swagger parameters that declare numeric type with string format."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node:
            continue
        schema_type = _primary_schema_type(node.get("type"))
        if schema_type not in {"number", "integer"}:
            continue
        if node.get("format") != "string":
            continue
        node["type"] = "string"
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SWAGGER_LEGACY_TYPE_NORMALIZED,
                message=(
                    f"Schema type {schema_type!r} with format 'string' was normalized "
                    "to type 'string' for validation."
                ),
                path=_join_pointer(pointer, "type"),
            )
        )


def _is_valid_schema_type_declaration(value: Any) -> bool:
    if isinstance(value, str):
        return value in _JSON_SCHEMA_SIMPLE_TYPES
    if isinstance(value, list):
        return bool(value) and all(
            isinstance(item, str) and item in _JSON_SCHEMA_SIMPLE_TYPES for item in value
        )
    return False


def _looks_like_media_type(value: str) -> bool:
    trimmed = value.strip()
    return bool(trimmed) and bool(_MEDIA_TYPE_PATTERN.fullmatch(trimmed))


def _should_remove_invalid_schema_type(
    node: dict[str, Any],
    *,
    pointer: str,
) -> tuple[bool, Any]:
    raw_type = node.get("type")
    if raw_type is None or _is_valid_schema_type_declaration(raw_type):
        return False, None
    if pointer.endswith("/properties") or pointer.endswith("/patternProperties"):
        return False, None
    if "/components/securitySchemes/" in pointer:
        return False, None
    if "$ref" in node:
        return True, raw_type
    if isinstance(raw_type, str) and _looks_like_media_type(raw_type):
        return True, raw_type
    if isinstance(raw_type, str) and raw_type in _DOMAIN_SCHEMA_TYPE_MARKERS:
        return True, raw_type
    return False, None


def _looks_like_schema_body(value: dict[str, Any]) -> bool:
    if _is_valid_schema_type_declaration(value.get("type")):
        return True
    return bool(
        {"enum", "format", "properties", "items", "allOf", "oneOf", "anyOf", "$ref", "const"}
        & value.keys()
    )


def _should_hoist_nested_schema_type(node: dict[str, Any], *, pointer: str) -> bool:
    if pointer.endswith("/properties") or pointer.endswith("/patternProperties"):
        return False
    if "$ref" in node:
        return False
    raw_type = node.get("type")
    if not isinstance(raw_type, dict):
        return False
    if not _looks_like_schema_body(raw_type):
        return False
    return set(node.keys()) == {"type"}


def _normalize_nested_schema_type_wrappers(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Hoist schemas that were incorrectly nested under a lone ``type`` key."""
    for pointer, node in _iter_mutable_objects(document):
        if not _should_hoist_nested_schema_type(node, pointer=pointer):
            continue
        inner = node.pop("type")
        assert isinstance(inner, dict)
        node.update(inner)
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_NESTED_SCHEMA_TYPE_HOISTED,
                message=(
                    "Schema was nested under a misplaced ``type`` key; "
                    "hoisted inner schema keywords to the parent object."
                ),
                path=pointer,
            )
        )


def _is_string_boolean_literal(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return value.strip().lower() in {"true", "false"}


def _coerce_string_boolean_literal(value: str) -> bool:
    return value.strip().lower() == "true"


def _normalize_boolean_schema_string_literals(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Coerce ``\"true\"``/``\"false\"`` enum members and defaults on boolean schemas."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node:
            continue
        if _primary_schema_type(node.get("type")) != "boolean":
            continue
        enum_values = node.get("enum")
        if isinstance(enum_values, list) and enum_values:
            if all(_is_string_boolean_literal(value) for value in enum_values):
                coerced_enum = [
                    _coerce_string_boolean_literal(value) for value in enum_values
                ]
                if coerced_enum != enum_values:
                    node["enum"] = coerced_enum
                    warnings.append(
                        SchemaTypeCoercionWarning(
                            code=_CODE_SCHEMA_BOOLEAN_LITERAL_NORMALIZED,
                            message=(
                                f"Schema enum {enum_values!r} was normalized to "
                                f"{coerced_enum!r} for boolean type validation."
                            ),
                            path=_join_pointer(pointer, "enum"),
                        )
                    )
        if "default" in node and _is_string_boolean_literal(node["default"]):
            raw_default = node["default"]
            coerced_default = _coerce_string_boolean_literal(raw_default)
            if coerced_default != raw_default:
                node["default"] = coerced_default
                warnings.append(
                    SchemaTypeCoercionWarning(
                        code=_CODE_SCHEMA_BOOLEAN_LITERAL_NORMALIZED,
                        message=(
                            f"Schema default {raw_default!r} was normalized to "
                            f"{coerced_default!r} for boolean type validation."
                        ),
                        path=_join_pointer(pointer, "default"),
                    )
                )


def _normalize_invalid_schema_enum_defaults(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Remove schema defaults that are not members of a declared ``enum`` list."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node or "default" not in node:
            continue
        enum_values = node.get("enum")
        if not isinstance(enum_values, list) or not enum_values:
            continue
        default = node["default"]
        if default in enum_values:
            continue
        node.pop("default", None)
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SCHEMA_ENUM_DEFAULT_REMOVED,
                message=(
                    f"Removed schema default {default!r} because it is not listed "
                    f"in enum {enum_values!r}."
                ),
                path=_join_pointer(pointer, "default"),
            )
        )


_OPENAPI_EXAMPLE_OBJECT_KEYS = frozenset(
    {"value", "summary", "description", "externalValue"}
)
_JSON_SCHEMA_OBJECT_MARKERS = frozenset(
    {
        "$ref",
        "type",
        "properties",
        "items",
        "allOf",
        "oneOf",
        "anyOf",
        "enum",
        "const",
        "$defs",
        "definitions",
        "additionalProperties",
        "pattern",
        "format",
        "required",
    }
)


def _looks_like_openapi_example_object(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return "value" in value and set(value.keys()) <= _OPENAPI_EXAMPLE_OBJECT_KEYS


def _is_json_schema_object(node: dict[str, Any]) -> bool:
    if "schema" in node:
        return False
    return bool(_JSON_SCHEMA_OBJECT_MARKERS & node.keys())


def _extract_openapi_style_schema_examples(raw: Any) -> list[Any] | None:
    """Convert OpenAPI-style named example maps to JSON Schema ``examples`` arrays."""
    if isinstance(raw, dict):
        if not raw:
            return []
        if not all(_looks_like_openapi_example_object(item) for item in raw.values()):
            return None
        return [item["value"] for item in raw.values()]

    if isinstance(raw, list):
        extracted: list[Any] = []
        for item in raw:
            if _looks_like_openapi_example_object(item):
                extracted.append(item["value"])
                continue
            if isinstance(item, dict) and len(item) == 1:
                wrapped = next(iter(item.values()))
                if _looks_like_openapi_example_object(wrapped):
                    extracted.append(wrapped["value"])
                    continue
            return None
        return extracted

    return None


def _normalize_openapi_style_schema_examples(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Normalize OpenAPI-style schema ``examples`` maps to JSON Schema example arrays."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node or not _is_json_schema_object(node):
            continue
        if "examples" not in node:
            continue
        raw_examples = node["examples"]
        normalized = _extract_openapi_style_schema_examples(raw_examples)
        if normalized is None or normalized == raw_examples:
            continue
        node["examples"] = normalized
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SCHEMA_EXAMPLES_NORMALIZED,
                message=(
                    "Normalized OpenAPI-style schema examples to a JSON Schema "
                    f"examples array with {len(normalized)} item(s)."
                ),
                path=_join_pointer(pointer, "examples"),
            )
        )


def _is_oas30_document(document: dict[str, Any]) -> bool:
    raw = document.get("openapi")
    return isinstance(raw, str) and raw.strip().startswith("3.0")


def _uses_draft4_boolean_exclusive_bounds(document: dict[str, Any]) -> bool:
    if _is_swagger_2_document(document):
        return True
    return _is_oas30_document(document)


def restore_oas30_numeric_exclusive_bounds_for_spec_validation(
    document: dict[str, Any],
) -> None:
    """Revert numeric exclusive bounds to Draft 4 booleans for legacy validators."""
    if not _uses_draft4_boolean_exclusive_bounds(document):
        return
    for _, node in _iter_mutable_objects(document):
        if "$ref" in node:
            continue
        exclusive_minimum = node.get("exclusiveMinimum")
        if isinstance(exclusive_minimum, (int, float)) and not isinstance(
            exclusive_minimum, bool
        ):
            node["minimum"] = exclusive_minimum
            node["exclusiveMinimum"] = True
        exclusive_maximum = node.get("exclusiveMaximum")
        if isinstance(exclusive_maximum, (int, float)) and not isinstance(
            exclusive_maximum, bool
        ):
            node["maximum"] = exclusive_maximum
            node["exclusiveMaximum"] = True


def _normalize_legacy_boolean_exclusive_bounds(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Convert Draft 4 boolean ``exclusiveMinimum``/``exclusiveMaximum`` keywords."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node:
            continue

        exclusive_minimum = node.get("exclusiveMinimum")
        if isinstance(exclusive_minimum, bool):
            if not exclusive_minimum:
                node.pop("exclusiveMinimum", None)
                warnings.append(
                    SchemaTypeCoercionWarning(
                        code=_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED,
                        message=(
                            "Removed boolean exclusiveMinimum=false; "
                            "JSON Schema 2020-12 uses numeric exclusiveMinimum."
                        ),
                        path=_join_pointer(pointer, "exclusiveMinimum"),
                    )
                )
            else:
                minimum = node.get("minimum")
                if isinstance(minimum, (int, float)) and not isinstance(minimum, bool):
                    schema_type = _primary_schema_type(node.get("type"))
                    if schema_type == "integer" and isinstance(minimum, int):
                        inclusive_minimum = minimum + 1
                        node["minimum"] = inclusive_minimum
                        node.pop("exclusiveMinimum", None)
                        warnings.append(
                            SchemaTypeCoercionWarning(
                                code=_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED,
                                message=(
                                    f"Converted exclusiveMinimum=true with minimum={minimum!r} "
                                    f"to inclusive minimum={inclusive_minimum!r}."
                                ),
                                path=_join_pointer(pointer, "minimum"),
                            )
                        )
                    else:
                        node["exclusiveMinimum"] = minimum
                        node.pop("minimum", None)
                        warnings.append(
                            SchemaTypeCoercionWarning(
                                code=_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED,
                                message=(
                                    f"Converted exclusiveMinimum=true with minimum={minimum!r} "
                                    f"to numeric exclusiveMinimum={minimum!r}."
                                ),
                                path=_join_pointer(pointer, "exclusiveMinimum"),
                            )
                        )
                else:
                    node.pop("exclusiveMinimum", None)
                    warnings.append(
                        SchemaTypeCoercionWarning(
                            code=_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED,
                            message=(
                                "Removed boolean exclusiveMinimum=true without a numeric "
                                "minimum bound."
                            ),
                            path=_join_pointer(pointer, "exclusiveMinimum"),
                        )
                    )

        exclusive_maximum = node.get("exclusiveMaximum")
        if isinstance(exclusive_maximum, bool):
            if not exclusive_maximum:
                node.pop("exclusiveMaximum", None)
                warnings.append(
                    SchemaTypeCoercionWarning(
                        code=_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED,
                        message=(
                            "Removed boolean exclusiveMaximum=false; "
                            "JSON Schema 2020-12 uses numeric exclusiveMaximum."
                        ),
                        path=_join_pointer(pointer, "exclusiveMaximum"),
                    )
                )
            else:
                maximum = node.get("maximum")
                if isinstance(maximum, (int, float)) and not isinstance(maximum, bool):
                    schema_type = _primary_schema_type(node.get("type"))
                    if schema_type == "integer" and isinstance(maximum, int):
                        inclusive_maximum = maximum - 1
                        node["maximum"] = inclusive_maximum
                        node.pop("exclusiveMaximum", None)
                        warnings.append(
                            SchemaTypeCoercionWarning(
                                code=_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED,
                                message=(
                                    f"Converted exclusiveMaximum=true with maximum={maximum!r} "
                                    f"to inclusive maximum={inclusive_maximum!r}."
                                ),
                                path=_join_pointer(pointer, "maximum"),
                            )
                        )
                    else:
                        node["exclusiveMaximum"] = maximum
                        node.pop("maximum", None)
                        warnings.append(
                            SchemaTypeCoercionWarning(
                                code=_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED,
                                message=(
                                    f"Converted exclusiveMaximum=true with maximum={maximum!r} "
                                    f"to numeric exclusiveMaximum={maximum!r}."
                                ),
                                path=_join_pointer(pointer, "exclusiveMaximum"),
                            )
                        )
                else:
                    node.pop("exclusiveMaximum", None)
                    warnings.append(
                        SchemaTypeCoercionWarning(
                            code=_CODE_LEGACY_EXCLUSIVE_BOUND_NORMALIZED,
                            message=(
                                "Removed boolean exclusiveMaximum=true without a numeric "
                                "maximum bound."
                            ),
                            path=_join_pointer(pointer, "exclusiveMaximum"),
                        )
                    )


def _looks_like_indexed_compositor_map(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    return all(
        isinstance(key, str) and key.isdigit() and isinstance(item, dict)
        for key, item in value.items()
    )


def _ref_prefix_variants(pointer: str) -> tuple[str, ...]:
    base = pointer if pointer.startswith("/") else f"/{pointer}"
    variants = [f"#{base}"]
    encoded = base.replace("{", "%7B").replace("}", "%7D")
    if encoded != base:
        variants.append(f"#{encoded}")
    return tuple(variants)


def _rewrite_document_ref_prefixes(
    document: dict[str, Any],
    *,
    old_prefix: str,
    new_prefix: str,
) -> int:
    rewritten = 0
    for _, node in _iter_mutable_objects(document):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith(old_prefix):
            node["$ref"] = f"{new_prefix}{ref[len(old_prefix):]}"
            rewritten += 1
    return rewritten


def _normalize_indexed_compositor_overlays(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Normalize compositor maps keyed by index and rewrite sibling overlay refs."""
    overlay_rewrites: list[tuple[str, str, str, str]] = []
    array_conversions: list[tuple[str, str, list[Any]]] = []
    overlay_removals: list[tuple[str, str]] = []

    for pointer, node in _iter_mutable_objects(document):
        component_ref = node.get("$ref")
        for compositor_key in _COMPOSITOR_LIST_KEYS:
            compositor = node.get(compositor_key)
            if not _looks_like_indexed_compositor_map(compositor):
                continue
            assert isinstance(compositor, dict)
            if (
                isinstance(component_ref, str)
                and component_ref.startswith(_COMPONENTS_SCHEMA_REF_PREFIX)
            ):
                for index_key in compositor:
                    for prefix in _ref_prefix_variants(pointer):
                        old_prefix = f"{prefix}/{compositor_key}/{index_key}/"
                        new_prefix = f"{component_ref}/{compositor_key}/{index_key}/"
                        overlay_rewrites.append(
                            (old_prefix, new_prefix, pointer, compositor_key)
                        )
                overlay_removals.append((pointer, compositor_key))
                continue
            array_conversions.append(
                (
                    pointer,
                    compositor_key,
                    [compositor[key] for key in sorted(compositor, key=int)],
                )
            )

    seen_rewrites: set[tuple[str, str]] = set()
    for old_prefix, new_prefix, pointer, compositor_key in overlay_rewrites:
        if (old_prefix, new_prefix) in seen_rewrites:
            continue
        seen_rewrites.add((old_prefix, new_prefix))
        rewritten = _rewrite_document_ref_prefixes(
            document,
            old_prefix=old_prefix,
            new_prefix=new_prefix,
        )
        if rewritten:
            warnings.append(
                SchemaTypeCoercionWarning(
                    code=_CODE_INDEXED_COMPOSITOR_NORMALIZED,
                    message=(
                        f"Rewrote {rewritten} overlay $ref(s) from {old_prefix!r} "
                        f"to {new_prefix!r}."
                    ),
                    path=pointer,
                )
            )

    for pointer, compositor_key in overlay_removals:
        node = _node_at_pointer(document, pointer)
        if node is None:
            continue
        compositor = node.pop(compositor_key, None)
        if compositor is None:
            continue
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_INDEXED_COMPOSITOR_NORMALIZED,
                message=(
                    f"Removed indexed {compositor_key} overlay keyed by "
                    f"{sorted(compositor, key=int)!r}; component $ref already "
                    "defines the schema."
                ),
                path=_join_pointer(pointer, compositor_key),
            )
        )

    for pointer, compositor_key, converted in array_conversions:
        node = _node_at_pointer(document, pointer)
        if node is None:
            continue
        node[compositor_key] = converted
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_INDEXED_COMPOSITOR_NORMALIZED,
                message=(
                    f"Converted indexed {compositor_key} map to a JSON Schema "
                    f"{compositor_key} array with {len(converted)} item(s)."
                ),
                path=_join_pointer(pointer, compositor_key),
            )
        )


def _node_at_pointer(document: dict[str, Any], pointer: str) -> dict[str, Any] | None:
    if pointer in {"", "/"}:
        return document
    if not pointer.startswith("/"):
        return None
    current: Any = document
    for token in pointer.lstrip("/").split("/"):
        decoded = token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or decoded not in current:
            return None
        current = current[decoded]
    return current if isinstance(current, dict) else None


def _enum_dedup_key(value: Any) -> Any:
    """Return a hashable key for order-preserving enum deduplication."""
    try:
        hash(value)
    except TypeError:
        return json.dumps(value, sort_keys=True, default=str)
    return value


def _deduplicate_preserve_order(values: list[Any]) -> tuple[list[Any], bool]:
    seen: set[Any] = set()
    deduplicated: list[Any] = []
    changed = False
    for value in values:
        key = _enum_dedup_key(value)
        if key in seen:
            changed = True
            continue
        seen.add(key)
        deduplicated.append(value)
    return deduplicated, changed


def _normalize_duplicate_schema_enum_values(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Remove duplicate entries from schema ``enum`` arrays while preserving order."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node:
            continue
        enum_values = node.get("enum")
        if not isinstance(enum_values, list) or len(enum_values) < 2:
            continue
        deduplicated, changed = _deduplicate_preserve_order(enum_values)
        if not changed:
            continue
        node["enum"] = deduplicated
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SCHEMA_ENUM_DEDUPLICATED,
                message=(
                    f"Removed duplicate enum entries from {enum_values!r}; "
                    f"normalized to {deduplicated!r}."
                ),
                path=_join_pointer(pointer, "enum"),
            )
        )


def _default_violates_numeric_bounds(node: dict[str, Any]) -> bool:
    default = node.get("default")
    if default is None or isinstance(default, bool) or not isinstance(default, (int, float)):
        return False
    minimum = node.get("minimum")
    maximum = node.get("maximum")
    if isinstance(minimum, (int, float)) and default < minimum:
        return True
    return bool(isinstance(maximum, (int, float)) and default > maximum)


def _normalize_invalid_schema_numeric_defaults(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Remove schema defaults that violate declared ``minimum`` or ``maximum`` bounds."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node or "default" not in node:
            continue
        if not _default_violates_numeric_bounds(node):
            continue
        default = node.pop("default")
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SCHEMA_NUMERIC_DEFAULT_REMOVED,
                message=(
                    f"Removed schema default {default!r} because it falls outside "
                    f"minimum={node.get('minimum')!r} maximum={node.get('maximum')!r}."
                ),
                path=_join_pointer(pointer, "default"),
            )
        )


def _normalize_schema_datetime_defaults(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Append ``Z`` to date-time defaults that omit a timezone offset."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node or "default" not in node:
            continue
        if node.get("format") != "date-time":
            continue
        default = node["default"]
        if not isinstance(default, str):
            continue
        trimmed = default.strip()
        if not _DATETIME_DEFAULT_WITHOUT_TZ.fullmatch(trimmed):
            continue
        normalized = f"{trimmed}Z"
        if normalized == default:
            continue
        node["default"] = normalized
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SCHEMA_DATETIME_DEFAULT_NORMALIZED,
                message=(
                    f"Schema date-time default {default!r} was normalized to "
                    f"{normalized!r} for RFC 3339 validation."
                ),
                path=_join_pointer(pointer, "default"),
            )
        )


def _is_valid_date_time_default(value: str) -> bool:
    trimmed = value.strip()
    if not trimmed:
        return False
    return bool(
        _DATETIME_DEFAULT_WITHOUT_TZ.fullmatch(trimmed)
        or _RFC3339_DATE_TIME.fullmatch(trimmed)
    )


def _default_violates_declared_format(default: Any, schema_format: str) -> bool:
    if schema_format == "date-time":
        return not isinstance(default, str) or not _is_valid_date_time_default(default)
    if isinstance(default, str):
        return not default.strip()
    return False


def _is_valid_schema_pattern(pattern: str) -> bool:
    try:
        re.compile(pattern)
    except re.error:
        return False
    return True


def _default_violates_declared_pattern(default: Any, pattern: str) -> bool:
    if not _is_valid_schema_pattern(pattern):
        return False
    if default is None:
        return False
    if isinstance(default, bool):
        return True
    if isinstance(default, (int, float)):
        candidate = str(default)
    elif isinstance(default, str):
        candidate = default
    else:
        return True
    return re.fullmatch(pattern, candidate) is None


def _normalize_invalid_schema_patterns(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Remove schema ``pattern`` keywords that are not valid ECMAScript regex."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node:
            continue
        pattern = node.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        if _is_valid_schema_pattern(pattern):
            continue
        node.pop("pattern")
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_INVALID_SCHEMA_PATTERN_REMOVED,
                message=(
                    f"Removed invalid schema pattern {pattern!r}; "
                    "JSON Schema pattern values must be valid ECMAScript regex."
                ),
                path=_join_pointer(pointer, "pattern"),
            )
        )


def _normalize_invalid_schema_pattern_defaults(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Remove schema defaults that do not satisfy a declared ``pattern``."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node or "default" not in node:
            continue
        pattern = node.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            continue
        default = node["default"]
        if not _default_violates_declared_pattern(default, pattern):
            continue
        removed = node.pop("default")
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SCHEMA_PATTERN_DEFAULT_REMOVED,
                message=(
                    f"Removed schema default {removed!r} because it does not "
                    f"match pattern {pattern!r}."
                ),
                path=_join_pointer(pointer, "default"),
            )
        )


def _normalize_invalid_schema_format_defaults(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Remove schema defaults that violate declared ``format`` keywords."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node or "default" not in node:
            continue
        if _primary_schema_type(node.get("type")) != "string":
            continue
        schema_format = node.get("format")
        if not isinstance(schema_format, str) or not schema_format.strip():
            continue
        default = node["default"]
        if not _default_violates_declared_format(default, schema_format):
            continue
        removed = node.pop("default")
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SCHEMA_FORMAT_DEFAULT_REMOVED,
                message=(
                    f"Removed schema default {removed!r} because it is not valid "
                    f"for format {schema_format!r}."
                ),
                path=_join_pointer(pointer, "default"),
            )
        )


def _normalize_invalid_schema_types(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Drop legacy media-type or sibling ``type`` values that fail JSON Schema validation."""
    for pointer, node in _iter_mutable_objects(document):
        should_remove, raw_type = _should_remove_invalid_schema_type(
            node,
            pointer=pointer,
        )
        if not should_remove:
            continue
        node.pop("type", None)
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_INVALID_SCHEMA_TYPE_REMOVED,
                message=(
                    f"Removed invalid schema type {raw_type!r}; "
                    "OpenAPI schemas must use JSON Schema type keywords."
                ),
                path=_join_pointer(pointer, "type"),
            )
        )


def _resolve_components_schema_ref(
    document: dict[str, Any],
    ref: str,
) -> dict[str, Any] | None:
    prefix = "#/components/schemas/"
    if not isinstance(ref, str) or not ref.startswith(prefix):
        return None
    components = document.get("components")
    if not isinstance(components, dict):
        return None
    schemas = components.get("schemas")
    if not isinstance(schemas, dict):
        return None
    schema = schemas.get(ref[len(prefix) :])
    return schema if isinstance(schema, dict) else None


def _collect_schema_property_names(
    document: dict[str, Any],
    node: dict[str, Any],
    *,
    visited_refs: set[str] | None = None,
) -> set[str]:
    names: set[str] = set()
    properties = node.get("properties")
    if isinstance(properties, dict):
        names.update(key for key in properties if isinstance(key, str))

    if visited_refs is None:
        visited_refs = set()

    for compositor in ("allOf", "anyOf", "oneOf"):
        items = node.get(compositor)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            ref = item.get("$ref")
            if isinstance(ref, str) and ref.strip():
                if ref in visited_refs:
                    continue
                visited_refs.add(ref)
                resolved = _resolve_components_schema_ref(document, ref.strip())
                if resolved is not None:
                    names.update(
                        _collect_schema_property_names(
                            document,
                            resolved,
                            visited_refs=visited_refs,
                        )
                    )
                continue
            names.update(
                _collect_schema_property_names(
                    document,
                    item,
                    visited_refs=visited_refs,
                )
            )
    return names


def _normalize_invalid_schema_required_properties(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Remove ``required`` entries that are not declared on the schema object."""
    for pointer, node in _iter_mutable_objects(document):
        if "$ref" in node:
            continue
        required = node.get("required")
        if not isinstance(required, list):
            continue
        if not required:
            node.pop("required", None)
            continue
        allowed_names = _collect_schema_property_names(document, node)
        if not allowed_names:
            continue
        filtered = [
            name for name in required if isinstance(name, str) and name in allowed_names
        ]
        if filtered == required:
            continue
        removed = [
            name
            for name in required
            if not (isinstance(name, str) and name in allowed_names)
        ]
        if filtered:
            node["required"] = filtered
        else:
            node.pop("required", None)
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_SCHEMA_REQUIRED_NORMALIZED,
                message=(
                    "Removed required entries that are not declared in schema "
                    f"properties: {removed!r}."
                ),
                path=_join_pointer(pointer, "required"),
            )
        )


def normalize_response_status_code_key(key: Any) -> str | None:
    """Return a string HTTP status code key, or ``None`` when *key* is unusable."""
    if isinstance(key, bool):
        return None
    if isinstance(key, int):
        return str(key)
    if isinstance(key, str) and key:
        return key
    return None


def _normalize_responses_map_status_code_keys(
    responses: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    for key in list(responses.keys()):
        normalized = normalize_response_status_code_key(key)
        if normalized is None:
            responses.pop(key)
            warnings.append(
                SchemaTypeCoercionWarning(
                    code=_CODE_RESPONSE_STATUS_CODE_KEY_NORMALIZED,
                    message=(
                        f"Removed invalid response status code key {key!r}; "
                        "OpenAPI response keys must be strings."
                    ),
                    path=_join_pointer(pointer, str(key)),
                )
            )
            continue
        if normalized == key:
            continue
        body = responses.pop(key)
        if normalized in responses:
            warnings.append(
                SchemaTypeCoercionWarning(
                    code=_CODE_RESPONSE_STATUS_CODE_KEY_NORMALIZED,
                    message=(
                        f"Dropped duplicate response status code {key!r}; "
                        f"{normalized!r} was already declared."
                    ),
                    path=_join_pointer(pointer, str(key)),
                )
            )
            continue
        responses[normalized] = body
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_RESPONSE_STATUS_CODE_KEY_NORMALIZED,
                message=(
                    f"Response status code key {key!r} was normalized to "
                    f"{normalized!r} for OpenAPI validation."
                ),
                path=_join_pointer(pointer, str(key)),
            )
        )


def _normalize_path_item_response_status_code_keys(
    path_item: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    responses = path_item.get("responses")
    if isinstance(responses, dict):
        _normalize_responses_map_status_code_keys(
            responses,
            pointer=_join_pointer(pointer, "responses"),
            warnings=warnings,
        )
    for method in _OPENAPI_OPERATION_METHODS:
        operation = path_item.get(method)
        if not isinstance(operation, dict):
            continue
        operation_responses = operation.get("responses")
        if isinstance(operation_responses, dict):
            _normalize_responses_map_status_code_keys(
                operation_responses,
                pointer=_join_pointer(_join_pointer(pointer, method), "responses"),
                warnings=warnings,
            )


def _normalize_document_response_status_code_keys(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    for section_pointer, section in (
        ("/paths", document.get("paths")),
        ("/webhooks", document.get("webhooks")),
    ):
        if not isinstance(section, dict):
            continue
        for pathname, path_item in section.items():
            if not isinstance(pathname, str) or not isinstance(path_item, dict):
                continue
            _normalize_path_item_response_status_code_keys(
                path_item,
                pointer=_join_pointer(section_pointer, pathname),
                warnings=warnings,
            )


def _normalize_openapi_boolean_field(
    obj: dict[str, Any],
    *,
    field: str,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    value = obj.get(field)
    if value is None or isinstance(value, bool):
        return
    coerced = _coerce_value_to_schema_type(value, "boolean")
    field_pointer = _join_pointer(pointer, field)
    if coerced is None:
        obj.pop(field, None)
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_OPENAPI_BOOLEAN_FIELD_COERCED,
                message=(
                    f"Removed invalid boolean value {value!r} from {field!r}; "
                    "OpenAPI expects true or false."
                ),
                path=field_pointer,
            )
        )
        return
    if type(coerced) is not type(value):
        obj[field] = coerced
        warnings.append(
            SchemaTypeCoercionWarning(
                code=_CODE_OPENAPI_BOOLEAN_FIELD_COERCED,
                message=(
                    f"Coerced {field!r} value {value!r} to {coerced!r} for OpenAPI "
                    "validation."
                ),
                path=field_pointer,
            )
        )


def _parameter_has_empty_name(parameter: dict[str, Any]) -> bool:
    if "$ref" in parameter:
        return False
    name = parameter.get("name")
    return not isinstance(name, str) or not name.strip()


def _remove_empty_named_parameters_from_list(
    parameters: Any,
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if not isinstance(parameters, list):
        return
    kept: list[Any] = []
    for index, parameter in enumerate(parameters):
        if isinstance(parameter, dict) and _parameter_has_empty_name(parameter):
            warnings.append(
                SchemaTypeCoercionWarning(
                    code=_CODE_EMPTY_PARAMETER_NAME_REMOVED,
                    message=(
                        "Removed parameter with empty or missing name; "
                        "OpenAPI requires a non-empty parameter.name."
                    ),
                    path=_join_pointer(pointer, str(index)),
                )
            )
            continue
        kept.append(parameter)
    if len(kept) != len(parameters):
        parameters[:] = kept


def _normalize_parameter_object_booleans(
    parameter: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if "$ref" in parameter and set(parameter.keys()) <= {"$ref", "summary", "description"}:
        return
    for field in ("required", "deprecated", "allowEmptyValue", "allowReserved"):
        _normalize_openapi_boolean_field(
            parameter,
            field=field,
            pointer=pointer,
            warnings=warnings,
        )


def _normalize_parameters_list_booleans(
    parameters: Any,
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if not isinstance(parameters, list):
        return
    for index, parameter in enumerate(parameters):
        if isinstance(parameter, dict):
            _normalize_parameter_object_booleans(
                parameter,
                pointer=_join_pointer(pointer, str(index)),
                warnings=warnings,
            )


def _normalize_request_body_booleans(
    request_body: Any,
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if not isinstance(request_body, dict):
        return
    if "$ref" in request_body and set(request_body.keys()) <= {"$ref", "summary", "description"}:
        return
    _normalize_openapi_boolean_field(
        request_body,
        field="required",
        pointer=pointer,
        warnings=warnings,
    )


def _normalize_response_headers_booleans(
    headers: Any,
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if not isinstance(headers, dict):
        return
    for name, header in headers.items():
        if not isinstance(name, str) or not isinstance(header, dict):
            continue
        if "$ref" in header and set(header.keys()) <= {"$ref", "summary", "description"}:
            continue
        for field in ("required", "deprecated"):
            _normalize_openapi_boolean_field(
                header,
                field=field,
                pointer=_join_pointer(pointer, name),
                warnings=warnings,
            )


def _normalize_responses_map_booleans(
    responses: Any,
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if not isinstance(responses, dict):
        return
    for status_code, body in responses.items():
        if not isinstance(status_code, str) or not isinstance(body, dict):
            continue
        _normalize_response_headers_booleans(
            body.get("headers"),
            pointer=_join_pointer(_join_pointer(pointer, status_code), "headers"),
            warnings=warnings,
        )


def _normalize_path_item_empty_parameter_names(
    path_item: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    _remove_empty_named_parameters_from_list(
        path_item.get("parameters"),
        pointer=_join_pointer(pointer, "parameters"),
        warnings=warnings,
    )
    for method in _OPENAPI_OPERATION_METHODS:
        operation = path_item.get(method)
        if not isinstance(operation, dict):
            continue
        _remove_empty_named_parameters_from_list(
            operation.get("parameters"),
            pointer=_join_pointer(_join_pointer(pointer, method), "parameters"),
            warnings=warnings,
        )


def _normalize_document_empty_parameter_names(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    _remove_empty_named_parameters_from_list(
        document.get("parameters"),
        pointer="/parameters",
        warnings=warnings,
    )

    components = document.get("components")
    if isinstance(components, dict):
        shared_parameters = components.get("parameters")
        if isinstance(shared_parameters, dict):
            removed: list[str] = []
            for name, parameter in shared_parameters.items():
                if isinstance(name, str) and isinstance(parameter, dict):
                    if _parameter_has_empty_name(parameter):
                        removed.append(name)
                        warnings.append(
                            SchemaTypeCoercionWarning(
                                code=_CODE_EMPTY_PARAMETER_NAME_REMOVED,
                                message=(
                                    "Removed shared parameter with empty or missing name; "
                                    "OpenAPI requires a non-empty parameter.name."
                                ),
                                path=_join_pointer("/components/parameters", name),
                            )
                        )
            for name in removed:
                shared_parameters.pop(name, None)

    for section_pointer, section in (
        ("/paths", document.get("paths")),
        ("/webhooks", document.get("webhooks")),
    ):
        if not isinstance(section, dict):
            continue
        for pathname, path_item in section.items():
            if not isinstance(pathname, str) or not isinstance(path_item, dict):
                continue
            _normalize_path_item_empty_parameter_names(
                path_item,
                pointer=_join_pointer(section_pointer, pathname),
                warnings=warnings,
            )


def _normalize_path_item_openapi_boolean_fields(
    path_item: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    _normalize_parameters_list_booleans(
        path_item.get("parameters"),
        pointer=_join_pointer(pointer, "parameters"),
        warnings=warnings,
    )
    _normalize_responses_map_booleans(
        path_item.get("responses"),
        pointer=_join_pointer(pointer, "responses"),
        warnings=warnings,
    )
    for method in _OPENAPI_OPERATION_METHODS:
        operation = path_item.get(method)
        if not isinstance(operation, dict):
            continue
        operation_pointer = _join_pointer(pointer, method)
        _normalize_parameters_list_booleans(
            operation.get("parameters"),
            pointer=_join_pointer(operation_pointer, "parameters"),
            warnings=warnings,
        )
        _normalize_request_body_booleans(
            operation.get("requestBody"),
            pointer=_join_pointer(operation_pointer, "requestBody"),
            warnings=warnings,
        )
        _normalize_responses_map_booleans(
            operation.get("responses"),
            pointer=_join_pointer(operation_pointer, "responses"),
            warnings=warnings,
        )


def _normalize_document_openapi_boolean_fields(
    document: dict[str, Any],
    *,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    _normalize_parameters_list_booleans(
        document.get("parameters"),
        pointer="/parameters",
        warnings=warnings,
    )

    components = document.get("components")
    if isinstance(components, dict):
        shared_parameters = components.get("parameters")
        if isinstance(shared_parameters, dict):
            for name, parameter in shared_parameters.items():
                if isinstance(name, str) and isinstance(parameter, dict):
                    _normalize_parameter_object_booleans(
                        parameter,
                        pointer=_join_pointer("/components/parameters", name),
                        warnings=warnings,
                    )
        shared_headers = components.get("headers")
        if isinstance(shared_headers, dict):
            for name, header in shared_headers.items():
                if isinstance(name, str) and isinstance(header, dict):
                    for field in ("required", "deprecated"):
                        _normalize_openapi_boolean_field(
                            header,
                            field=field,
                            pointer=_join_pointer("/components/headers", name),
                            warnings=warnings,
                        )
        shared_responses = components.get("responses")
        if isinstance(shared_responses, dict):
            for name, body in shared_responses.items():
                if isinstance(name, str) and isinstance(body, dict):
                    _normalize_response_headers_booleans(
                        body.get("headers"),
                        pointer=_join_pointer(
                            _join_pointer("/components/responses", name),
                            "headers",
                        ),
                        warnings=warnings,
                    )

    for section_pointer, section in (
        ("/paths", document.get("paths")),
        ("/webhooks", document.get("webhooks")),
    ):
        if not isinstance(section, dict):
            continue
        for pathname, path_item in section.items():
            if not isinstance(pathname, str) or not isinstance(path_item, dict):
                continue
            _normalize_path_item_openapi_boolean_fields(
                path_item,
                pointer=_join_pointer(section_pointer, pathname),
                warnings=warnings,
            )


def _coerce_response_description(
    response: dict[str, Any],
    *,
    pointer: str,
    fallback_name: str | None,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    """Ensure an OpenAPI Response object has a non-empty ``description``."""
    description = response.get("description")
    if isinstance(description, str) and description.strip():
        return
    fallback = fallback_name.strip() if isinstance(fallback_name, str) and fallback_name.strip() else (
        _EMPTY_RESPONSE_DESCRIPTION_PLACEHOLDER
    )
    response["description"] = fallback
    warnings.append(
        SchemaTypeCoercionWarning(
            code=_CODE_EMPTY_RESPONSE_DESCRIPTION_COERCION,
            message=(
                "Response description was empty or missing; "
                f"coerced to {fallback!r} for import persistence."
            ),
            path=pointer,
        )
    )


def _coerce_responses_map(
    responses: Any,
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    if not isinstance(responses, dict):
        return
    _normalize_responses_map_status_code_keys(
        responses,
        pointer=pointer,
        warnings=warnings,
    )
    for status_code, body in responses.items():
        if not isinstance(status_code, str) or not isinstance(body, dict):
            continue
        ref = body.get("$ref")
        if isinstance(ref, str) and ref.strip() and set(body.keys()) <= {"$ref", "summary", "description"}:
            if isinstance(body.get("description"), str) and not body["description"].strip():
                body.pop("description", None)
            if len(body) == 1:
                continue
        _coerce_response_description(
            body,
            pointer=_join_pointer(pointer, status_code),
            fallback_name=status_code,
            warnings=warnings,
        )


def _coerce_path_item_responses(
    path_item: dict[str, Any],
    *,
    pointer: str,
    warnings: list[SchemaTypeCoercionWarning],
) -> None:
    _coerce_responses_map(
        path_item.get("responses"),
        pointer=_join_pointer(pointer, "responses"),
        warnings=warnings,
    )
    for method, operation in path_item.items():
        if method not in _OPENAPI_OPERATION_METHODS or not isinstance(operation, dict):
            continue
        _coerce_responses_map(
            operation.get("responses"),
            pointer=_join_pointer(_join_pointer(pointer, method), "responses"),
            warnings=warnings,
        )


def coerce_empty_response_descriptions(
    document: dict[str, Any],
) -> tuple[dict[str, Any], tuple[SchemaTypeCoercionWarning, ...]]:
    """Return a copy of *document* with empty response descriptions normalized."""
    working = deepcopy(document)
    warnings: list[SchemaTypeCoercionWarning] = []
    _normalize_document_response_status_code_keys(working, warnings=warnings)

    components = working.get("components")
    if isinstance(components, dict):
        responses = components.get("responses")
        if isinstance(responses, dict):
            for name, body in responses.items():
                if isinstance(name, str) and isinstance(body, dict):
                    _coerce_response_description(
                        body,
                        pointer=_join_pointer("/components/responses", name),
                        fallback_name=name,
                        warnings=warnings,
                    )

    for section_pointer, section in (
        ("/paths", working.get("paths")),
        ("/webhooks", working.get("webhooks")),
    ):
        if not isinstance(section, dict):
            continue
        for pathname, path_item in section.items():
            if not isinstance(pathname, str) or not isinstance(path_item, dict):
                continue
            _coerce_path_item_responses(
                path_item,
                pointer=_join_pointer(section_pointer, pathname),
                warnings=warnings,
            )

    return working, tuple(warnings)


def coerce_openapi_schema_type_mismatches(
    document: dict[str, Any],
) -> tuple[dict[str, Any], tuple[SchemaTypeCoercionWarning, ...]]:
    """Return a copy of *document* with coercible schema defaults and examples normalized."""
    working = deepcopy(document)
    warnings: list[SchemaTypeCoercionWarning] = []
    _normalize_document_response_status_code_keys(working, warnings=warnings)
    _normalize_document_openapi_boolean_fields(working, warnings=warnings)
    _normalize_document_empty_parameter_names(working, warnings=warnings)
    _normalize_nested_schema_type_wrappers(working, warnings=warnings)
    _normalize_swagger_legacy_schema_types(working, warnings=warnings)
    _normalize_numeric_type_with_string_format(working, warnings=warnings)
    _normalize_invalid_schema_types(working, warnings=warnings)
    _normalize_invalid_schema_required_properties(working, warnings=warnings)
    _normalize_boolean_schema_string_literals(working, warnings=warnings)
    _normalize_duplicate_schema_enum_values(working, warnings=warnings)
    _normalize_invalid_schema_numeric_defaults(working, warnings=warnings)
    _normalize_schema_datetime_defaults(working, warnings=warnings)
    _normalize_invalid_schema_format_defaults(working, warnings=warnings)
    _normalize_invalid_schema_patterns(working, warnings=warnings)
    _normalize_invalid_schema_pattern_defaults(working, warnings=warnings)
    _normalize_openapi_style_schema_examples(working, warnings=warnings)
    _normalize_legacy_boolean_exclusive_bounds(working, warnings=warnings)
    _normalize_indexed_compositor_overlays(working, warnings=warnings)
    use_type_array = _openapi_uses_nullable_type_array(working)
    normalize_null_defaults = isinstance(working.get("openapi"), str)
    for pointer, node in _iter_mutable_objects(working):
        if "type" in node or "enum" in node or "default" in node or "example" in node or "examples" in node:
            if normalize_null_defaults:
                _normalize_null_schema_default(
                    node,
                    pointer=pointer,
                    warnings=warnings,
                    use_type_array=use_type_array,
                )
            _coerce_schema_enum_values(node, pointer=pointer, warnings=warnings)
            _coerce_schema_defaults(node, pointer=pointer, warnings=warnings)
            _coerce_schema_array_examples(node, pointer=pointer, warnings=warnings)
        if "schema" in node and (
            "default" in node or "example" in node or "examples" in node
        ):
            _coerce_container_array_values(node, pointer=pointer, warnings=warnings)
    _normalize_invalid_schema_enum_defaults(working, warnings=warnings)
    return working, tuple(warnings)
