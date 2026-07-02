"""Merge OpenAPI path templates that differ only by parameter names."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping

from apiome_cli.import_.schema_type_coercion import SchemaTypeCoercionWarning

_PATH_TEMPLATE_PARAM = re.compile(r"\{([^{}/]+)\}")
_COMPONENT_PARAM_REF = re.compile(r"^#/components/parameters/([^/]+)$")
_CODE_EQUIVALENT_PATH_TEMPLATE_MERGED = "equivalent_path_template_merged"

_OPERATION_KEYS: frozenset[str] = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace", "query"}
)
_PATH_MAP_KEYS: tuple[str, ...] = ("paths", "webhooks")


def normalize_path_template(path: str) -> str:
    """Collapse path template parameter names to detect equivalent templates."""
    return _PATH_TEMPLATE_PARAM.sub("{}", path)


def path_template_param_names(path: str) -> list[str]:
    """Return path parameter names in template order."""
    return _PATH_TEMPLATE_PARAM.findall(path)


def _parameter_name_remap(
    canonical_path: str,
    duplicate_path: str,
) -> dict[str, str]:
    canonical_names = path_template_param_names(canonical_path)
    duplicate_names = path_template_param_names(duplicate_path)
    if len(canonical_names) != len(duplicate_names):
        return {}
    return dict(zip(duplicate_names, canonical_names, strict=True))


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _join_pointer(base: str, token: str) -> str:
    escaped = _escape_json_pointer_token(token)
    if base == "/":
        return f"/{escaped}"
    return f"{base}/{escaped}"


def _path_items_mergeable(canonical: dict[str, Any], duplicate: dict[str, Any]) -> bool:
    return True


def _combine_descriptions(left: str, right: str) -> str:
    if not left:
        return right
    if not right or left == right:
        return left
    return f"{left}; {right}"


def _merge_parameter_lists(
    canonical: Any,
    duplicate: Any,
) -> list[dict[str, Any]]:
    merged_params = [
        deepcopy(item) for item in canonical if isinstance(item, dict)
    ] if isinstance(canonical, list) else []
    seen = {
        (item.get("name"), item.get("in"))
        for item in merged_params
        if isinstance(item, dict)
    }
    if not isinstance(duplicate, list):
        return merged_params
    for item in duplicate:
        if not isinstance(item, dict):
            continue
        identity = (item.get("name"), item.get("in"))
        if identity in seen:
            continue
        merged_params.append(deepcopy(item))
        seen.add(identity)
    return merged_params


def _merge_content_map(
    canonical: dict[str, Any],
    duplicate: Mapping[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(canonical)
    for media_type, media_object in duplicate.items():
        if not isinstance(media_object, dict):
            continue
        if media_type not in merged:
            merged[media_type] = deepcopy(media_object)
            continue
        existing = merged[media_type]
        if not isinstance(existing, dict):
            merged[media_type] = deepcopy(media_object)
            continue
        canonical_schema = existing.get("schema")
        duplicate_schema = media_object.get("schema")
        if (
            isinstance(canonical_schema, dict)
            and isinstance(duplicate_schema, dict)
            and canonical_schema != duplicate_schema
        ):
            existing["schema"] = {
                "oneOf": [deepcopy(canonical_schema), deepcopy(duplicate_schema)],
            }
    return merged


def _merge_response_values(
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(canonical)
    duplicate_content = duplicate.get("content")
    if isinstance(duplicate_content, dict):
        canonical_content = merged.get("content")
        merged["content"] = _merge_content_map(
            canonical_content if isinstance(canonical_content, dict) else {},
            duplicate_content,
        )
    duplicate_description = duplicate.get("description")
    if isinstance(duplicate_description, str):
        merged["description"] = _combine_descriptions(
            merged.get("description", ""),
            duplicate_description,
        )
    return merged


def _merge_responses(canonical: Any, duplicate: Any) -> dict[str, Any]:
    merged = deepcopy(canonical) if isinstance(canonical, dict) else {}
    if not isinstance(duplicate, dict):
        return merged
    for status_code, response in duplicate.items():
        if not isinstance(response, dict):
            continue
        if status_code not in merged or not isinstance(merged[status_code], dict):
            merged[status_code] = deepcopy(response)
            continue
        merged[status_code] = _merge_response_values(merged[status_code], response)
    return merged


def _merge_operation_values(
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(canonical)
    for key, value in duplicate.items():
        if key == "parameters":
            merged["parameters"] = _merge_parameter_lists(merged.get("parameters"), value)
            continue
        if key == "responses":
            merged["responses"] = _merge_responses(merged.get("responses"), value)
            continue
        if key == "description":
            if isinstance(value, str):
                merged["description"] = _combine_descriptions(
                    merged.get("description", ""),
                    value,
                )
            continue
        if key == "operationId":
            continue
        if key not in merged:
            merged[key] = deepcopy(value)
    return merged


def _iter_path_item_parameters(path_item: dict[str, Any]) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    path_level = path_item.get("parameters")
    if isinstance(path_level, list):
        parameters.extend(item for item in path_level if isinstance(item, dict))
    for key in _OPERATION_KEYS:
        operation = path_item.get(key)
        if not isinstance(operation, dict):
            continue
        operation_params = operation.get("parameters")
        if isinstance(operation_params, list):
            parameters.extend(item for item in operation_params if isinstance(item, dict))
    return parameters


def _parameter_uses_mismatched_component_ref(
    parameter: dict[str, Any],
    *,
    parameter_rename: dict[str, str],
) -> bool:
    ref = parameter.get("$ref")
    if not isinstance(ref, str):
        return False
    match = _COMPONENT_PARAM_REF.fullmatch(ref.strip())
    if match is None:
        return False
    component_name = match.group(1)
    canonical_name = parameter_rename.get(component_name)
    if canonical_name is None:
        return False
    return component_name != canonical_name


def _duplicate_uses_incompatible_component_param_refs(
    duplicate_item: dict[str, Any],
    *,
    parameter_rename: dict[str, str],
) -> bool:
    """Return True when merge would leave component $ref path params mismatched."""
    return any(
        _parameter_uses_mismatched_component_ref(parameter, parameter_rename=parameter_rename)
        for parameter in _iter_path_item_parameters(duplicate_item)
    )


def _rename_path_parameters(value: Any, *, rename: dict[str, str]) -> Any:
    if isinstance(value, dict):
        renamed = {key: _rename_path_parameters(item, rename=rename) for key, item in value.items()}
        if renamed.get("in") == "path":
            name = renamed.get("name")
            if isinstance(name, str) and name in rename:
                renamed["name"] = rename[name]
        return renamed
    if isinstance(value, list):
        return [_rename_path_parameters(item, rename=rename) for item in value]
    return value


def _merge_path_item_values(
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
    *,
    parameter_rename: dict[str, str],
) -> dict[str, Any]:
    duplicate = _rename_path_parameters(duplicate, rename=parameter_rename)
    merged = deepcopy(canonical)
    for key, value in duplicate.items():
        if key in _OPERATION_KEYS:
            if key not in merged:
                merged[key] = deepcopy(value)
            else:
                merged[key] = _merge_operation_values(merged[key], value)
            continue
        if key == "parameters":
            merged["parameters"] = _merge_parameter_lists(merged.get("parameters"), value)
            continue
        if key not in merged:
            merged[key] = deepcopy(value)
    return merged


def can_merge_equivalent_path_items(
    canonical_path: str,
    duplicate_path: str,
    canonical_item: dict[str, Any],
    duplicate_item: dict[str, Any],
) -> bool:
    """Return whether two path items differ only by template parameter names and can merge."""
    if normalize_path_template(canonical_path) != normalize_path_template(duplicate_path):
        return False
    if canonical_path == duplicate_path:
        return False
    if not _path_items_mergeable(canonical_item, duplicate_item):
        return False
    parameter_rename = _parameter_name_remap(canonical_path, duplicate_path)
    if not parameter_rename:
        return False
    return not _duplicate_uses_incompatible_component_param_refs(
        duplicate_item,
        parameter_rename=parameter_rename,
    )


def merge_equivalent_path_templates(
    document: dict[str, Any],
) -> tuple[dict[str, Any], tuple[SchemaTypeCoercionWarning, ...]]:
    """Return a copy of *document* with mergeable equivalent path templates collapsed."""
    working = deepcopy(document)
    warnings: list[SchemaTypeCoercionWarning] = []

    for map_key in _PATH_MAP_KEYS:
        path_map = working.get(map_key)
        if not isinstance(path_map, dict):
            continue

        templates: dict[str, str] = {}
        to_remove: list[str] = []

        for path_name, path_item in list(path_map.items()):
            if not isinstance(path_name, str) or not isinstance(path_item, dict):
                continue

            normalized = normalize_path_template(path_name)
            pointer = _join_pointer(f"/{map_key}", path_name)
            canonical_path = templates.get(normalized)
            if canonical_path is None:
                templates[normalized] = path_name
                continue
            if canonical_path == path_name:
                continue

            canonical_item = path_map.get(canonical_path)
            if not isinstance(canonical_item, dict):
                templates[normalized] = path_name
                continue
            if not can_merge_equivalent_path_items(
                canonical_path,
                path_name,
                canonical_item,
                path_item,
            ):
                continue

            parameter_rename = _parameter_name_remap(canonical_path, path_name)
            assert parameter_rename
            path_map[canonical_path] = _merge_path_item_values(
                canonical_item,
                path_item,
                parameter_rename=parameter_rename,
            )
            to_remove.append(path_name)
            warnings.append(
                SchemaTypeCoercionWarning(
                    code=_CODE_EQUIVALENT_PATH_TEMPLATE_MERGED,
                    message=(
                        f"Path template {path_name!r} was merged into "
                        f"{canonical_path!r} (only parameter names differ)."
                    ),
                    path=pointer,
                )
            )

        for path_name in to_remove:
            del path_map[path_name]

    return working, tuple(warnings)
