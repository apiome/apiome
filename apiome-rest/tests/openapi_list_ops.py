"""Find the list operations of an OpenAPI document (DBP-1.13, #7196).

Shared by ``tests/test_openapi_list_bounds.py`` (the gate) and by anyone classifying a new
endpoint: run ``python -m tests.openapi_list_ops`` from ``apiome-rest/`` to print every list
operation that has neither a bounded ``limit`` nor an allowlist entry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional

ROOT = Path(__file__).resolve().parent.parent
OPENAPI_FILE = ROOT / "openapi.json"
ALLOWLIST_FILE = Path(__file__).with_name("openapi_list_bounds_allowlist.json")

#: Why a list operation may go without a ``limit``. Anything that grows with what a tenant
#: stores is none of these and must page.
REASONS = {
    "fixed-catalog": "A set defined by code or deployment configuration (rules, presets, formats).",
    "single-resource": "One resource's detail; its arrays are parts of that one document.",
    "bounded-by-parent": "Children of one parent whose count a product limit or the parent caps.",
    "capped-in-sql": "The query has a fixed LIMIT the caller cannot raise.",
}


class ListOperation(NamedTuple):
    """One ``GET`` that answers with a list.

    Attributes:
        path: The path template.
        shape: ``array`` for a bare JSON array, ``envelope`` for an object carrying one.
        arrays: The array properties of an envelope (empty for a bare array).
        limit_maximum: The ``limit`` parameter's documented maximum; ``None`` when there is no
            ``limit`` or it has no maximum.
    """

    path: str
    shape: str
    arrays: List[str]
    limit_maximum: Optional[int]


def _resolve(schema: Any, components: Dict[str, Any]) -> Dict[str, Any]:
    """Follow ``$ref`` (and a nullable ``anyOf``) to the schema it names."""
    seen = 0
    while isinstance(schema, dict) and seen < 20:
        seen += 1
        if "$ref" in schema:
            schema = components.get(schema["$ref"].rsplit("/", 1)[-1], {})
            continue
        options = [o for o in schema.get("anyOf", []) if o.get("type") != "null"]
        if len(options) == 1 and "type" not in schema:
            schema = options[0]
            continue
        break
    return schema if isinstance(schema, dict) else {}


def _is_object_array(schema: Any, components: Dict[str, Any]) -> bool:
    """Whether a property is an array whose items are objects (rows, not a list of scalars)."""
    resolved = _resolve(schema, components)
    if resolved.get("type") != "array":
        return False
    items = _resolve(resolved.get("items"), components)
    return items.get("type") == "object" or "properties" in items or "additionalProperties" in items


def _limit_maximum(operation: Dict[str, Any]) -> Optional[int]:
    """The documented maximum of an operation's ``limit`` query parameter, if it has one."""
    for parameter in operation.get("parameters", []):
        if parameter.get("name") != "limit" or parameter.get("in") != "query":
            continue
        schema = parameter.get("schema", {})
        for candidate in [schema, *schema.get("anyOf", [])]:
            if isinstance(candidate.get("maximum"), int):
                return candidate["maximum"]
    return None


def list_operations(spec: Dict[str, Any]) -> Iterator[ListOperation]:
    """Yield every ``GET`` whose ``200`` JSON body is, or carries, a list of rows.

    Args:
        spec: A parsed OpenAPI document.

    Yields:
        One :class:`ListOperation` per list endpoint, in document order.
    """
    components = spec.get("components", {}).get("schemas", {})
    for path, item in spec.get("paths", {}).items():
        operation = item.get("get")
        if not operation:
            continue
        body = (
            operation.get("responses", {})
            .get("200", {})
            .get("content", {})
            .get("application/json", {})
            .get("schema")
        )
        schema = _resolve(body, components)
        if schema.get("type") == "array":
            yield ListOperation(path, "array", [], _limit_maximum(operation))
            continue
        arrays = [
            name
            for name, prop in schema.get("properties", {}).items()
            if _is_object_array(prop, components)
        ]
        if arrays:
            yield ListOperation(path, "envelope", arrays, _limit_maximum(operation))


def load_allowlist() -> Dict[str, str]:
    """The allowlisted paths and the reason each needs no ``limit``."""
    entries = json.loads(ALLOWLIST_FILE.read_text())["paths"]
    return {path: reason for path, reason in entries.items()}


def unbounded(spec: Dict[str, Any], allowlist: Dict[str, str]) -> List[ListOperation]:
    """The list operations with neither a bounded ``limit`` nor an allowlist entry."""
    return [
        operation
        for operation in list_operations(spec)
        if operation.limit_maximum is None and operation.path not in allowlist
    ]


if __name__ == "__main__":  # pragma: no cover - a helper for whoever adds an endpoint
    import sys

    source = Path(sys.argv[1]) if len(sys.argv) > 1 else OPENAPI_FILE
    for found in unbounded(json.loads(source.read_text()), load_allowlist()):
        print(f"{found.shape:8} {found.path}  {','.join(found.arrays)}")
