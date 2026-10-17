"""How ``apiome properties show`` finds and presents one library property (CLI 6.2, #3224).

The property is named by its name or UUID, like ``projects get`` resolves a project. Names are
matched against the project's property list (``GET /v1/properties/{tenant}/{project}``): exact
first, then ignoring case; a miss suggests the closest names. The single-property GET (apiome-rest
1.354.0 or later) adds ``usage`` — the class attributes that use the property. Properties carry no
tags and are not bound to primitives, so the pane shows the schema's ``$ref`` (when it has one) in
place of a primitive and has no tags row. These functions hold the decisions, without HTTP.
"""

from __future__ import annotations

import difflib
import json
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID

from apiome_cli.property_view import is_required, schema_type

#: JSON Schema keywords shown on the **Constraints** row, in this order.
CONSTRAINT_KEYWORDS: tuple[str, ...] = (
    "minimum",
    "exclusiveMinimum",
    "maximum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minProperties",
    "maxProperties",
    "enum",
    "const",
)

#: How many "did you mean" names a miss suggests.
SUGGESTIONS = 3


class PropertyNotFound(ValueError):
    """No property with that name or id, or more than one by a case-insensitive name (exit 2)."""


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def find_property(props: Sequence[Mapping[str, Any]], ref: str, *, project: str) -> Mapping[str, Any]:
    """The property ``ref`` names: exact name, then name ignoring case, then id.

    Args:
        props: The project's properties (the list endpoint's items).
        ref: What the user typed — a property name or UUID.
        project: The project as the user named it (for the message).

    Returns:
        The matching property list item.

    Raises:
        PropertyNotFound: When nothing matches (with up to :data:`SUGGESTIONS` close names), or when
            the name matches several properties only ignoring case.
    """
    wanted = ref.strip()
    for prop in props:
        if str(prop.get("name")) == wanted:
            return prop
    folded = [p for p in props if str(p.get("name") or "").lower() == wanted.lower()]
    if len(folded) == 1:
        return folded[0]
    if len(folded) > 1:
        names = ", ".join(sorted(str(p.get("name")) for p in folded))
        raise PropertyNotFound(f"{ref!r} matches more than one property ({names}); type the name exactly.")
    if _is_uuid(wanted):
        for prop in props:
            if str(prop.get("id")).lower() == wanted.lower():
                return prop
    message = f"No property {ref!r} in project '{project}'."
    names = [str(p.get("name")) for p in props if p.get("name")]
    close = difflib.get_close_matches(wanted, names, n=SUGGESTIONS, cutoff=0.6)
    if not close:
        lowered = {n.lower(): n for n in names}
        close = [lowered[n] for n in difflib.get_close_matches(wanted.lower(), list(lowered), n=SUGGESTIONS)]
    if close:
        message += " Did you mean: " + ", ".join(close) + "?"
    raise PropertyNotFound(message)


def _compact(value: Any) -> str:
    """A constraint or example value as it reads in JSON (strings unquoted at the top level)."""
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def constraints(schema: Any) -> str:
    """The **Constraints** row: ``minimum=0, multipleOf=0.01`` from the schema, or ``—``."""
    if not isinstance(schema, Mapping):
        return "—"
    parts = [f"{key}={_compact(schema[key])}" for key in CONSTRAINT_KEYWORDS if key in schema]
    return ", ".join(parts) or "—"


def examples(schema: Any) -> str:
    """The **Examples** row from ``examples`` (a list) or ``example``, or ``—``."""
    if not isinstance(schema, Mapping):
        return "—"
    values = schema.get("examples")
    if not isinstance(values, list):
        values = [schema["example"]] if "example" in schema else []
    return ", ".join(_compact(v) for v in values) or "—"


def usage_lines(usage: Optional[Sequence[Mapping[str, Any]]]) -> list[str]:
    """The **Used by** row, one ``Class.attribute  (required)`` line per class attribute.

    ``None`` (a server older than apiome-rest 1.354.0) reads "not reported"; an empty list reads
    "no class uses it".
    """
    if usage is None:
        return ["not reported by this server (apiome-rest 1.354.0 or later reports it)"]
    if not usage:
        return ["— (no class uses it)"]
    refs = [f"{u.get('class_name')}.{u.get('attribute_name')}" for u in usage]
    width = max(len(r) for r in refs)
    return [
        f"{ref.ljust(width)}  ({'required' if u.get('required') else 'optional'})"
        for ref, u in zip(refs, usage)
    ]


def render_show(prop: Mapping[str, Any]) -> str:
    """The ``properties show`` pane: a heading, a rule and one labelled row per fact.

    Args:
        prop: The single-property GET response (``data`` holds the JSON Schema fragment).
    """
    data = prop.get("data") if isinstance(prop.get("data"), Mapping) else {}
    heading = f"{prop.get('name') or ''}  ({prop.get('id') or ''})"
    rows: list[tuple[str, list[str]]] = []
    if isinstance(data.get("$ref"), str):
        rows.append(("Primitive:", [data["$ref"]]))
    rows += [
        ("Type:", [schema_type(data)]),
        ("Required:", ["yes" if is_required(prop) else "no"]),
        ("Constraints:", [constraints(data)]),
        ("Examples:", [examples(data)]),
        ("Description:", [str(prop.get("description") or data.get("description") or "—")]),
        ("Enabled:", ["no" if prop.get("enabled") is False else "yes"]),
        ("Used by:", usage_lines(prop.get("usage"))),
    ]
    width = max(len(label) for label, _ in rows)
    lines = [heading, "─" * max(len(heading), 46)]
    for label, values in rows:
        lines.append(f"{label.ljust(width)}  {values[0]}")
        lines += [f"{' ' * width}  {value}" for value in values[1:]]
    return "\n".join(lines)
