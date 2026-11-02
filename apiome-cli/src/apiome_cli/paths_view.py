"""The rules of ``apiome paths list`` / ``apiome paths show`` (CLI 8.1, #3237).

Pure functions, no HTTP:

* :func:`decode_path_ref` — a path reference as the user may type it: the literal template
  (``/charges/{id}``), the template without its leading slash, its URL-encoded form
  (``/charges/%7Bid%7D``), or its JSON Pointer token (``~1charges~1{id}``, RFC 6901, optionally
  prefixed ``#/paths/``);
* :func:`group_by_path` — one inventory row per path template: its methods, operation ids and
  tags (``paths list``);
* :func:`render_tree` — the compact ASCII tree of one path from ``GET …/{path_id}/full``:
  operations, then each operation's parameters, request body and responses (``paths show``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import unquote

#: HTTP methods in the order OpenAPI lists them in a Path Item; others sort after, alphabetically.
METHOD_ORDER = ("GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE")


def decode_path_ref(ref: str) -> str:
    """The path template a reference names.

    Args:
        ref: What the user typed (see the module docstring for the accepted forms).

    Returns:
        The template with a leading ``/`` (``/users/{id}``); ``""`` for a blank reference.
    """
    text = ref.strip()
    text = text.removeprefix("#/paths/")
    text = unquote(text)
    if "~1" in text or "~0" in text:
        # RFC 6901: "~1" is "/" and "~0" is "~"; "~1" is replaced first so "~01" stays "~1".
        text = text.replace("~1", "/").replace("~0", "~")
    if text and not text.startswith("/"):
        text = f"/{text}"
    return text


def method_sort_key(method: str) -> tuple[int, str]:
    """Sort key putting methods in :data:`METHOD_ORDER`."""
    upper = method.upper()
    return (METHOD_ORDER.index(upper), upper) if upper in METHOD_ORDER else (len(METHOD_ORDER), upper)


def _unique(values: Iterable[str]) -> list[str]:
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def group_by_path(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per path template from the per-operation inventory rows.

    Args:
        rows: Rows of :func:`apiome_cli.paths_inventory.build_path_operation_rows` (``pathname``,
            ``method``, ``operationId``, ``tags``, ``path_id``), in path order.

    Returns:
        ``{"pathname", "path_id", "methods", "operations", "tags"}`` per path, methods ordered as
        in an OpenAPI Path Item and operation ids following them. A path with no operation keeps
        empty lists.
    """
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("pathname", "")), []).append(row)
    result: list[dict[str, Any]] = []
    for pathname, members in grouped.items():
        ops = sorted((m for m in members if m.get("method")), key=lambda m: method_sort_key(str(m["method"])))
        result.append(
            {
                "pathname": pathname,
                "path_id": members[0].get("path_id", ""),
                "methods": _unique(str(m["method"]).upper() for m in ops),
                "operations": _unique(str(m.get("operationId") or "") for m in ops),
                "tags": _unique(str(tag) for m in ops for tag in (m.get("tags") or [])),
            }
        )
    return result


def _schema_label(schema_owner: Mapping[str, Any]) -> str:
    """What a parameter / content / response holds: its class, an inline type, or nothing."""
    if schema_owner.get("class_name"):
        return str(schema_owner["class_name"])
    data = schema_owner.get("data")
    schema = None
    if isinstance(data, Mapping):
        schema = data.get("schema") if isinstance(data.get("schema"), Mapping) else None
    inline = schema_owner.get("inline_schema")
    schema = schema or (inline if isinstance(inline, Mapping) else None)
    if not schema:
        return ""
    if schema.get("$ref"):
        return str(schema["$ref"]).rsplit("/", 1)[-1]
    kind = schema.get("type")
    if kind == "array" and isinstance(schema.get("items"), Mapping):
        return f"{_schema_label({'inline_schema': schema['items']}) or 'any'}[]"
    return str(kind) if kind else "inline"


def _parameter_line(parameter: Mapping[str, Any]) -> str:
    data = parameter.get("data") if isinstance(parameter.get("data"), Mapping) else {}
    location = parameter.get("in_location") or data.get("in") or "?"
    flags = [str(location)]
    if data.get("required") or location == "path":
        flags.append("required")
    label = _schema_label(parameter)
    return f"{parameter.get('name', '')} ({', '.join(flags)}){' ' + label if label else ''}"


def _contents_line(contents: Any) -> str:
    """``application/json → Charge, text/csv`` from content-type rows."""
    parts: list[str] = []
    for content in contents or []:
        if not isinstance(content, Mapping):
            continue
        media = str(content.get("media_type") or "")
        label = _schema_label(content)
        parts.append(f"{media} → {label}" if label else media)
    return ", ".join(part for part in parts if part)


def _operation_title(operation: Mapping[str, Any]) -> str:
    description = operation.get("description") if isinstance(operation.get("description"), Mapping) else {}
    parts = [str(operation.get("operation") or "").upper()]
    if description.get("operation_id"):
        parts.append(str(description["operation_id"]))
    text = " ".join(part for part in parts if part)
    if description.get("summary"):
        text += f" — {description['summary']}"
    tags = description.get("tags")
    if isinstance(tags, list) and tags:
        text += f"  [{', '.join(str(t) for t in tags)}]"
    if description.get("deprecated"):
        text += "  (deprecated)"
    return text


def _children(operation: Mapping[str, Any]) -> list[tuple[str, list[str]]]:
    """The ``(label, leaves)`` groups under one operation: params, body, responses."""
    groups: list[tuple[str, list[str]]] = []
    parameters = [p for p in operation.get("parameters") or [] if isinstance(p, Mapping)]
    if parameters:
        groups.append(("params", [_parameter_line(p) for p in parameters]))
    body = operation.get("requestBody")
    if isinstance(body, Mapping):
        label = "body" + (" (required)" if body.get("required") else "")
        line = _contents_line(body.get("content_types"))
        groups.append((label, [line or "(no content types)"]))
    responses = [r for r in operation.get("responses") or [] if isinstance(r, Mapping)]
    if responses:
        leaves = []
        for response in responses:
            status = str(response.get("status_code") or "default")
            detail = _contents_line(response.get("content_types")) or _schema_label(response)
            leaves.append(f"{status} {detail}".rstrip())
        groups.append(("responses", leaves))
    return groups


def render_tree(full: Mapping[str, Any]) -> list[str]:
    """The compact ASCII tree of one path (``GET …/paths/{tenant}/{version}/{path_id}/full``).

    Args:
        full: The path record with its ``operations`` (each with ``description``, ``parameters``,
            ``requestBody`` and ``responses``).

    Returns:
        The tree's lines: the path template, then each operation (methods in Path Item order),
        then its params, body and responses, children indented with box-drawing connectors.
    """
    lines = [str(full.get("pathname") or "")]
    if full.get("summary"):
        lines[0] += f" — {full['summary']}"
    operations = sorted(
        (op for op in full.get("operations") or [] if isinstance(op, Mapping)),
        key=lambda op: method_sort_key(str(op.get("operation") or "")),
    )
    if not operations:
        lines.append("└── (no operations)")
        return lines
    for op_index, operation in enumerate(operations):
        last_op = op_index == len(operations) - 1
        lines.append(f"{'└──' if last_op else '├──'} {_operation_title(operation)}")
        branch = "    " if last_op else "│   "
        groups = _children(operation)
        for group_index, (label, leaves) in enumerate(groups):
            last_group = group_index == len(groups) - 1
            lines.append(f"{branch}{'└──' if last_group else '├──'} {label}")
            leaf_branch = branch + ("    " if last_group else "│   ")
            for leaf_index, leaf in enumerate(leaves):
                connector = "└──" if leaf_index == len(leaves) - 1 else "├──"
                lines.append(f"{leaf_branch}{connector} {leaf}")
    return lines
