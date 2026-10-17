"""How ``apiome properties list`` filters and presents library properties (CLI 6.1, #3223).

A project's properties (``GET /v1/properties/{tenant}/{project}``) are reusable field definitions:
a name, a description and ``data`` — a JSON Schema fragment such as ``{"type": "string", "format":
"uuid"}``. The list endpoint also reports where each one is used (``used_by`` class names and
``used_by_count``). Properties are not bound to primitive types and carry no tags, so the command
shows the schema's **type** instead. These functions hold the decisions, without HTTP.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

#: How many class names the table shows before "+N".
USED_BY_SHOWN = 3


class UsageUnavailable(ValueError):
    """``--unused`` against a server that does not report property usage (exit 2)."""


def schema_type(schema: Any) -> str:
    """A short type label for a property's JSON Schema fragment.

    ``format`` wins over ``type`` (``uuid``, ``date-time``); arrays read ``array<item>``; unions
    (``type: [..]``, ``anyOf`` / ``oneOf``) join with ``|``; a ``$ref`` shows its last segment;
    ``enum`` / ``const`` without a type show ``enum`` / ``const``; anything else is ``—``.
    """
    if not isinstance(schema, Mapping):
        return "—"
    if isinstance(schema.get("$ref"), str):
        return schema["$ref"].rstrip("/").rsplit("/", 1)[-1]
    if isinstance(schema.get("format"), str) and schema["format"].strip():
        return schema["format"].strip()
    kind = schema.get("type")
    if isinstance(kind, list):
        return "|".join(str(k) for k in kind)
    if kind == "array":
        return f"array<{schema_type(schema.get('items'))}>"
    if isinstance(kind, str) and kind:
        return kind
    for key in ("anyOf", "oneOf"):
        members = schema.get(key)
        if isinstance(members, list) and members:
            return "|".join(schema_type(m) for m in members)
    if "enum" in schema:
        return "enum"
    if "const" in schema:
        return "const"
    return "—"


def type_matches(label: str, wanted: str) -> bool:
    """``--type``: the whole label, or one of its ``|`` alternatives, case-insensitive."""
    want = wanted.strip().lower()
    whole = label.lower()
    return whole == want or want in whole.split("|")


def is_required(prop: Mapping[str, Any]) -> bool:
    """Whether the property's data marks it required (``"required": true``)."""
    data = prop.get("data")
    return isinstance(data, Mapping) and data.get("required") is True


def filter_properties(
    items: Sequence[Mapping[str, Any]],
    *,
    type_filter: Optional[str] = None,
    search: Optional[str] = None,
    unused: bool = False,
) -> list[Mapping[str, Any]]:
    """Apply ``--type``, ``--search`` (name or description, case-insensitive) and ``--unused``.

    Raises:
        UsageUnavailable: ``unused`` when the server did not report ``used_by_count``.
    """
    if unused and any(p.get("used_by_count") is None for p in items):
        raise UsageUnavailable(
            "This server does not report where properties are used (apiome-rest 1.353.0 or later does); "
            "--unused cannot be applied."
        )
    needle = (search or "").strip().lower()
    out = []
    for prop in items:
        if type_filter and not type_matches(schema_type(prop.get("data")), type_filter):
            continue
        if needle and needle not in f"{prop.get('name') or ''}\n{prop.get('description') or ''}".lower():
            continue
        if unused and int(prop.get("used_by_count") or 0) > 0:
            continue
        out.append(prop)
    return out


def _used_by_cell(prop: Mapping[str, Any]) -> str:
    names = prop.get("used_by")
    if names is None:
        return "?"
    if not names:
        return "—"
    shown = ",".join(str(n) for n in names[:USED_BY_SHOWN])
    return shown + (f" +{len(names) - USED_BY_SHOWN}" if len(names) > USED_BY_SHOWN else "")


def render_table(
    props: Sequence[Mapping[str, Any]], *, matched: int, project: str, total: int
) -> str:
    """The ``properties list`` table and its summary line.

    Args:
        props: The properties to show (already filtered and limited).
        matched: How many matched the filters.
        project: The project as the user named it.
        total: How many properties the project has.
    """
    lines: list[str] = []
    if props:
        header = ("NAME", "TYPE", "REQ?", "USED BY")
        rows = [
            (str(p.get("name") or ""), schema_type(p.get("data")), "yes" if is_required(p) else "—", _used_by_cell(p))
            for p in props
        ]
        widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
        lines += ["  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip() for row in (header, *rows)]
        lines.append("")
    noun = "property" if total == 1 else "properties"
    summary = f"{total} {noun} in project '{project}'."
    if matched != total:
        summary = f"{matched} of {total} {noun} in project '{project}' match."
    if len(props) < matched:
        summary += f" Showing {len(props)}; pass --all or --limit N."
    lines.append(summary)
    return "\n".join(lines)
