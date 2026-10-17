"""How ``apiome classes list`` filters and presents a version's classes (CLI 7.1, #3229).

Two server shapes, one call each:

* **lean** — ``GET /v1/classes/{tenant}?version_id=…``: each class with ``property_count`` (its
  top-level properties) and ``tags`` (``{name, …}``; apiome-rest 1.357.0+);
* **hydrated** — ``GET /v1/classes/{tenant}/version/{id}/with-properties-tags``: each class with every
  ``properties`` row (``name``, ``data``, ``parent_id`` for nesting) and ``tags`` (``tag_name``).

These functions hold the filtering and rendering, without HTTP.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from apiome_cli.property_view import is_required, schema_type

#: The longest description the lean table prints before cutting it with "…".
DESCRIPTION_WIDTH = 60


def class_tags(cls: Mapping[str, Any]) -> list[str]:
    """A class's tag names from either shape (``name`` in the lean list, ``tag_name`` hydrated)."""
    tags = cls.get("tags")
    if not isinstance(tags, list):
        return []
    names = [t.get("name") or t.get("tag_name") for t in tags if isinstance(t, Mapping)]
    return [str(n) for n in names if n]


def property_count(cls: Mapping[str, Any]) -> Optional[int]:
    """Top-level properties: ``property_count`` (lean), else counted from ``properties`` (hydrated).

    ``None`` when the server reports neither (apiome-rest before 1.357.0).
    """
    count = cls.get("property_count")
    if isinstance(count, int):
        return count
    props = cls.get("properties")
    if isinstance(props, list):
        return sum(1 for p in props if isinstance(p, Mapping) and not p.get("parent_id"))
    return None


def filter_classes(
    classes: Sequence[Mapping[str, Any]], *, tag: Optional[str] = None, search: Optional[str] = None
) -> list[Mapping[str, Any]]:
    """Apply ``--tag`` (one tag name, any case) and ``--search`` (name or description, any case)."""
    wanted_tag = (tag or "").strip().lower()
    needle = (search or "").strip().lower()
    out = []
    for cls in classes:
        if wanted_tag and wanted_tag not in (t.lower() for t in class_tags(cls)):
            continue
        if needle and needle not in f"{cls.get('name') or ''}\n{cls.get('description') or ''}".lower():
            continue
        out.append(cls)
    return out


def _cut(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _columns(header: Sequence[str], rows: Sequence[Sequence[str]], indent: str = "") -> list[str]:
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    return [indent + "  ".join(c.ljust(widths[i]) for i, c in enumerate(row)).rstrip() for row in (header, *rows)]


def summary_line(*, shown: int, matched: int, total: int, where: str) -> str:
    """``24 classes in payments-api v2.1.0.``, with "match" and "Showing" when filtered or cut."""
    noun = "class" if total == 1 else "classes"
    line = f"{total} {noun} in {where}."
    if matched != total:
        line = f"{matched} of {total} {noun} in {where} match."
    if shown < matched:
        line += f" Showing {shown}; pass --all or --limit N."
    return line


def render_lean(classes: Sequence[Mapping[str, Any]]) -> list[str]:
    """The lean table: NAME, #PROPS, TAGS, DESCRIPTION (``?`` when the server reports no count)."""
    if not classes:
        return []
    rows = []
    for cls in classes:
        count = property_count(cls)
        rows.append(
            (
                str(cls.get("name") or ""),
                "?" if count is None else str(count),
                ", ".join(class_tags(cls)) or "—",
                _cut(str(cls.get("description") or ""), DESCRIPTION_WIDTH) or "—",
            )
        )
    return _columns(("NAME", "#PROPS", "TAGS", "DESCRIPTION"), rows)


def _ordered_properties(props: Sequence[Mapping[str, Any]]) -> list[tuple[int, Mapping[str, Any]]]:
    """Properties depth first (top level by name, each followed by its nested ones), with depth."""
    children: dict[Any, list[Mapping[str, Any]]] = {}
    ids = {p.get("id") for p in props}
    for prop in props:
        parent = prop.get("parent_id") if prop.get("parent_id") in ids else None
        children.setdefault(parent, []).append(prop)
    out: list[tuple[int, Mapping[str, Any]]] = []

    def walk(parent: Any, depth: int) -> None:
        for prop in sorted(children.get(parent, []), key=lambda p: str(p.get("name") or "")):
            out.append((depth, prop))
            if prop.get("id") is not None:
                walk(prop.get("id"), depth + 1)

    walk(None, 0)
    return out


def render_hydrated(classes: Sequence[Mapping[str, Any]]) -> list[str]:
    """``--with-properties``: a header per class, then one line per property (nested ones indented).

    Example::

        Charge  (2 properties · core, financial)  Inbound payment from a customer.
          NAME      TYPE    REQ?
          amount    number  yes
          metadata  object  —
            note    string  —
    """
    lines: list[str] = []
    for cls in classes:
        count = property_count(cls) or 0
        noun = "property" if count == 1 else "properties"
        facts = " · ".join([f"{count} {noun}", *([", ".join(class_tags(cls))] if class_tags(cls) else [])])
        description = _cut(str(cls.get("description") or ""), DESCRIPTION_WIDTH)
        lines.append(f"{cls.get('name')}  ({facts})" + (f"  {description}" if description else ""))
        props = [p for p in cls.get("properties") or [] if isinstance(p, Mapping)]
        rows = [
            ("  " * depth + str(p.get("name") or ""), schema_type(p.get("data")), "yes" if is_required(p) else "—")
            for depth, p in _ordered_properties(props)
        ]
        lines += _columns(("NAME", "TYPE", "REQ?"), rows, indent="  ") if rows else ["  (no properties)"]
        lines.append("")
    return lines
