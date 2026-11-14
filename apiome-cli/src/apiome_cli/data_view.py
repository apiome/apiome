"""Rendering for ``apiome data list`` (CLI 10.1, #3253): the records table and its footer.

Nothing here talks to the network. The table is plain aligned text (like ``classes list``):
``ID``, ``CREATED``, one column per data field, and ``DELETED_AT`` with ``--include-deleted``.

* :func:`data_columns` — the data fields to show: ``--columns``, else every top-level field in
  the order the records first use them;
* :func:`render_table` — the table lines;
* :func:`render_footer` — ``20 of 1,234 (use --next <cursor> or --all).``
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

#: The longest a data cell is shown before it is cut with ``…``.
MAX_CELL_WIDTH = 40


def parse_columns(text: Optional[str]) -> list[str]:
    """``--columns amount,currency`` → ``["amount", "currency"]`` (blank entries dropped)."""
    if not text:
        return []
    return [name.strip() for name in text.split(",") if name.strip()]


def data_columns(items: Sequence[Mapping[str, Any]], requested: Sequence[str]) -> list[str]:
    """The data fields to show: ``requested`` when given, else each field in first-use order.

    Args:
        items: The records (each with a ``data`` object).
        requested: The ``--columns`` names (may be empty).

    Returns:
        Field names, without duplicates.
    """
    if requested:
        return list(dict.fromkeys(requested))
    seen: dict[str, None] = {}
    for item in items:
        data = item.get("data")
        if isinstance(data, Mapping):
            for key in data:
                seen.setdefault(str(key), None)
    return list(seen)


def format_time(value: Any) -> str:
    """An ISO 8601 timestamp as ``2026-05-04 12:42``; anything unparseable is shown as given."""
    if not value:
        return ""
    try:
        return datetime.fromisoformat(str(value)).strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return str(value)


def format_cell(value: Any) -> str:
    """One data value as text: strings as-is, ``true``/``false``/``null`` as JSON, objects compact.

    Cut to :data:`MAX_CELL_WIDTH` characters with ``…``; whitespace runs become one space.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    elif isinstance(value, bool):
        text = "true" if value else "false"
    elif isinstance(value, (int, float)):
        text = str(value)
    else:
        text = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= MAX_CELL_WIDTH else text[: MAX_CELL_WIDTH - 1].rstrip() + "…"


def render_table(
    items: Sequence[Mapping[str, Any]], columns: Sequence[str], *, include_deleted: bool = False
) -> list[str]:
    """The records as aligned text lines: a header row, then one row per record.

    Args:
        items: The records (``record_id``, ``created_at``, ``deleted_at``, ``data``).
        columns: The data fields to show (see :func:`data_columns`).
        include_deleted: Add the ``DELETED_AT`` column.

    Returns:
        The lines, without trailing spaces.
    """
    header = ["ID", "CREATED", *(name.upper() for name in columns)]
    if include_deleted:
        header.append("DELETED_AT")
    rows = []
    for item in items:
        data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
        row = [str(item.get("record_id") or ""), format_time(item.get("created_at"))]
        row += [format_cell(data.get(name)) for name in columns]
        if include_deleted:
            row.append(format_time(item.get("deleted_at")))
        rows.append(row)
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) if rows else len(header[i]) for i in range(len(header))]
    return ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in (header, *rows)]


def render_footer(shown: int, total: int, next_cursor: Optional[str]) -> str:
    """``20 of 1,234 (use --next <cursor> or --all).`` — or ``3 of 3.`` when nothing is left."""
    line = f"{shown:,} of {total:,}"
    if next_cursor:
        return f"{line} (use --next {next_cursor} or --all)."
    return f"{line}."
