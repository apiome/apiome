"""How ``apiome tags list`` / ``tags show`` present version tags (CLI 11.4, #3263).

Version tags (``stable``, ``latest``, ``prod`` …) are named pointers to a project's versions,
listed by ``GET /v1/version-tags/{tenant}/{project}``. The server records who **created** a tag
and when it was last **updated**, but not who moved it or where it pointed before — so the output
says "created by" and shows no history. These functions hold the presentation, without HTTP.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence
from uuid import UUID


class TagNotFound(ValueError):
    """No tag with that name or id (exit 2)."""


def _when(value: Any, *, with_time: bool = False) -> str:
    """``2026-05-04T12:43:10Z`` → ``2026-05-04`` (or ``2026-05-04 12:43 UTC``); blank if missing."""
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        moment = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return value
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%d %H:%M UTC") if with_time else moment.strftime("%Y-%m-%d")


def _creator(tag: Mapping[str, Any]) -> str:
    return str(tag.get("created_by_email") or tag.get("created_by") or "")


def sort_tags(tags: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Tags in name order (what the server returns, made explicit)."""
    return sorted(tags, key=lambda t: str(t.get("name") or ""))


def find_tag(tags: Sequence[Mapping[str, Any]], ref: str) -> Mapping[str, Any]:
    """The tag named ``ref`` (exact), or with id ``ref``.

    Raises:
        TagNotFound: When neither matches.
    """
    wanted = ref.strip()
    for tag in tags:
        if str(tag.get("name")) == wanted:
            return tag
    try:
        UUID(wanted)
    except ValueError:
        pass
    else:
        for tag in tags:
            if str(tag.get("id")) == wanted:
                return tag
    raise TagNotFound(f"No version tag {ref!r} in this project.")


def render_tag_list(tags: Sequence[Mapping[str, Any]], *, total: Optional[int] = None) -> str:
    """The ``tags list`` table: TAG, POINTS TO, CHANNEL, UPDATED, CREATED BY.

    Args:
        tags: The tags to show (already limited).
        total: How many the project has, when more exist than are shown.
    """
    if not tags:
        return "No version tags."
    header = ("TAG", "POINTS TO", "CHANNEL", "UPDATED", "CREATED BY")
    rows = [
        (
            str(t.get("name") or ""),
            str(t.get("target_version_string") or t.get("version_id") or ""),
            str(t.get("channel") or ""),
            _when(t.get("updated_at") or t.get("created_at")),
            _creator(t),
        )
        for t in tags
    ]
    widths = [max(len(header[i]), *(len(r[i]) for r in rows)) for i in range(len(header))]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() for row in (header, *rows)]
    if total is not None and total > len(tags):
        lines.append(f"Showing {len(tags)} of {total} tags; pass --all for every tag or --limit N.")
    return "\n".join(lines)


def render_tag_show(tag: Mapping[str, Any]) -> str:
    """The ``tags show`` record."""
    flags = [name for name, on in (("immutable", tag.get("immutable")), ("protected", tag.get("protected"))) if on]
    rows = [
        ("Tag:", str(tag.get("name") or "")),
        ("Points to:", f"{tag.get('target_version_string') or ''}  ({tag.get('version_id')})"),
        ("Channel:", str(tag.get("channel") or "—")),
        ("Message:", str(tag.get("message") or "—")),
        ("Locks:", ", ".join(flags) or "—"),
        ("Updated:", _when(tag.get("updated_at"), with_time=True) or "—"),
        ("Created:", " by ".join(p for p in (_when(tag.get("created_at"), with_time=True), _creator(tag)) if p) or "—"),
        ("History:", "not recorded by the server (only the current pointer is kept)"),
    ]
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label.ljust(width)}  {value}" for label, value in rows)
