"""Normalize OpenAPI path keys that incorrectly embed query strings."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any
from urllib.parse import parse_qsl

from apiome_cli.import_.schema_type_coercion import SchemaTypeCoercionWarning

_CODE_EMBEDDED_QUERY_PATH_NORMALIZED = "embedded_query_path_normalized"
_EMBEDDED_QUERY_PARAM_VALUE = re.compile(r"^\{([^{}]+)\}$")
_PATH_MAP_KEYS: tuple[str, ...] = ("paths", "webhooks")
_OPERATION_KEYS: frozenset[str] = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace", "query"}
)


def _escape_json_pointer_token(token: str) -> str:
    return token.replace("~", "~0").replace("/", "~1")


def _join_pointer(base: str, token: str) -> str:
    escaped = _escape_json_pointer_token(token)
    if base == "/":
        return f"/{escaped}"
    return f"{base}/{escaped}"


def _extract_embedded_query_parameters(query_string: str) -> list[dict[str, Any]]:
    """Return query parameter objects inferred from ``name={name}`` templates."""
    parameters: list[dict[str, Any]] = []
    for name, raw_value in parse_qsl(query_string, keep_blank_values=True):
        if not name:
            continue
        match = _EMBEDDED_QUERY_PARAM_VALUE.fullmatch(raw_value)
        if match is None:
            continue
        template_name = match.group(1)
        if template_name != name:
            continue
        parameters.append(
            {
                "name": name,
                "in": "query",
                "required": True,
                "schema": {"type": "string"},
            }
        )
    return parameters


def split_embedded_query_path(path_name: str) -> tuple[str, list[dict[str, Any]]] | None:
    """Split *path_name* into a path template and inferred query parameters."""
    if "?" not in path_name:
        return None
    base_path, query_string = path_name.split("?", 1)
    if not base_path.startswith("/"):
        return None
    parameters = _extract_embedded_query_parameters(query_string)
    if not parameters:
        return None
    return base_path, parameters


def _parameter_identity(parameter: dict[str, Any]) -> tuple[str | None, str | None]:
    return parameter.get("name"), parameter.get("in")


def _promote_misplaced_path_parameters_to_query(
    path_item: dict[str, Any],
    *,
    query_names: set[str],
) -> None:
    containers: list[dict[str, Any]] = [path_item]
    for method in _OPERATION_KEYS:
        operation = path_item.get(method)
        if isinstance(operation, dict):
            containers.append(operation)
    for container in containers:
        parameters = container.get("parameters")
        if not isinstance(parameters, list):
            continue
        for parameter in parameters:
            if not isinstance(parameter, dict):
                continue
            name = parameter.get("name")
            if name in query_names and parameter.get("in") == "path":
                parameter["in"] = "query"


def _merge_query_parameters(
    target: dict[str, Any],
    *,
    query_parameters: list[dict[str, Any]],
) -> None:
    existing = [
        item for item in target.get("parameters", []) if isinstance(item, dict)
    ]
    seen = {_parameter_identity(item) for item in existing}
    seen_names = {item.get("name") for item in existing if isinstance(item.get("name"), str)}
    merged = [deepcopy(item) for item in existing]
    for parameter in query_parameters:
        name = parameter.get("name")
        if isinstance(name, str) and name in seen_names:
            continue
        identity = _parameter_identity(parameter)
        if identity in seen:
            continue
        merged.append(deepcopy(parameter))
        seen.add(identity)
        if isinstance(name, str):
            seen_names.add(name)
    if merged:
        target["parameters"] = merged


def _inject_embedded_query_parameters(
    path_item: dict[str, Any],
    *,
    query_parameters: list[dict[str, Any]],
) -> None:
    query_names = {
        name
        for parameter in query_parameters
        if isinstance(parameter.get("name"), str)
        for name in [parameter["name"]]
    }
    _promote_misplaced_path_parameters_to_query(path_item, query_names=query_names)
    _merge_query_parameters(path_item, query_parameters=query_parameters)
    for method in _OPERATION_KEYS:
        operation = path_item.get(method)
        if isinstance(operation, dict):
            _merge_query_parameters(operation, query_parameters=query_parameters)


def _merge_path_items(
    canonical: dict[str, Any],
    duplicate: dict[str, Any],
) -> dict[str, Any]:
    merged = deepcopy(canonical)
    for key, value in duplicate.items():
        if key in _OPERATION_KEYS:
            if key not in merged:
                merged[key] = deepcopy(value)
            continue
        if key not in merged:
            merged[key] = deepcopy(value)
    return merged


def normalize_paths_with_embedded_query_strings(
    document: dict[str, Any],
) -> tuple[dict[str, Any], tuple[SchemaTypeCoercionWarning, ...]]:
    """Move ``{param}`` templates from path keys into query parameter objects."""
    working = deepcopy(document)
    warnings: list[SchemaTypeCoercionWarning] = []

    for map_key in _PATH_MAP_KEYS:
        path_map = working.get(map_key)
        if not isinstance(path_map, dict):
            continue

        replacements: list[tuple[str, str, list[dict[str, Any]]]] = []
        for path_name, path_item in list(path_map.items()):
            if not isinstance(path_name, str) or not isinstance(path_item, dict):
                continue
            split = split_embedded_query_path(path_name)
            if split is None:
                continue
            base_path, query_parameters = split
            replacements.append((path_name, base_path, query_parameters))

        for original_path, base_path, query_parameters in replacements:
            path_item = path_map.pop(original_path)
            assert isinstance(path_item, dict)
            _inject_embedded_query_parameters(
                path_item,
                query_parameters=query_parameters,
            )
            existing = path_map.get(base_path)
            if isinstance(existing, dict):
                path_map[base_path] = _merge_path_items(existing, path_item)
            else:
                path_map[base_path] = path_item
            warnings.append(
                SchemaTypeCoercionWarning(
                    code=_CODE_EMBEDDED_QUERY_PATH_NORMALIZED,
                    message=(
                        f"Path key {original_path!r} was normalized to "
                        f"{base_path!r} with embedded query parameters moved "
                        "into parameter objects."
                    ),
                    path=_join_pointer(f"/{map_key}", original_path),
                )
            )

    return working, tuple(warnings)
