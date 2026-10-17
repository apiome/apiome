"""The rules of ``apiome tags update`` (CLI 11.6, #3265) — move a tag to another version.

``PATCH /v1/version-tags/{tenant}/{project}/{tag_id}`` with ``{version_id, message}``. Before the
move the command shows its blast radius, best-effort: Apiome does not count spec downloads per
version, so it reports what it does know about the version the tag points at **now** — mock
requests in the last 7 days, downloads of its frozen snapshot, and the other tags on it. A figure
that cannot be read is shown as unavailable and never stops the command.

These functions hold the presentation and decisions, without HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

#: The window the mock-request figure covers.
MOCK_WINDOW_DAYS = 7


class TagLocked(ValueError):
    """The tag cannot be moved (exit 6): it is immutable."""


@dataclass(frozen=True)
class BlastRadius:
    """What the move may affect; ``None`` means the figure could not be read."""

    mock_requests: Optional[int]
    #: ``None`` unknown; ``-1`` the version is not frozen.
    snapshot_downloads: Optional[int]
    other_tags: list[str]


def check_movable(tag: Mapping[str, Any]) -> None:
    """Refuse an immutable tag before anything is sent.

    Raises:
        TagLocked: When the tag is immutable.
    """
    if tag.get("immutable"):
        raise TagLocked(f"Tag '{tag.get('name')}' is immutable: it can never be moved.")


def sum_mock_requests(usage: Any) -> Optional[int]:
    """Total ``requestCount`` of ``GET /v1/mocks/{tenant}/usage`` daily rollups; ``None`` if unreadable."""
    if not isinstance(usage, Mapping):
        return None
    rollups = usage.get("dailyRollups")
    if not isinstance(rollups, list):
        return None
    return sum(int(r.get("requestCount") or r.get("request_count") or 0) for r in rollups if isinstance(r, Mapping))


def other_tags_on(tags: Sequence[Mapping[str, Any]], version_id: str, *, besides: str) -> list[str]:
    """Names of the other tags pointing at ``version_id``."""
    return sorted(
        str(t.get("name")) for t in tags if str(t.get("version_id")) == version_id and str(t.get("id")) != besides
    )


def render_plan(
    *,
    name: str,
    from_label: Optional[str],
    to_label: Optional[str],
    moves: bool,
    message: Optional[str],
    message_changes: bool,
    radius: Optional[BlastRadius],
) -> str:
    """The summary shown before the confirmation (and for ``--dry-run``)."""
    lines = []
    if moves:
        lines.append(f"Moving '{name}' from {from_label} → {to_label}.")
    else:
        lines.append(f"'{name}' already points to {to_label}; only its description changes.")
    if message_changes:
        lines.append(f"Description: {message}" if message else "Description: cleared")
    if moves and radius is not None:
        mocks = "unavailable" if radius.mock_requests is None else f"{radius.mock_requests:,}"
        if radius.snapshot_downloads is None:
            downloads = "unavailable"
        elif radius.snapshot_downloads < 0:
            downloads = "not frozen"
        else:
            downloads = f"{radius.snapshot_downloads:,}"
        rows = [
            (f"Mock requests, last {MOCK_WINDOW_DAYS} days:", mocks),
            ("Frozen-snapshot downloads:", downloads),
            (f"Other tags on {from_label}:", ", ".join(radius.other_tags) or "none"),
        ]
        width = max(len(label) for label, _ in rows)
        lines.append(f"Affected consumers of {from_label} (best effort):")
        lines.extend(f"  {label.ljust(width)} {value}" for label, value in rows)
    return "\n".join(lines)


def dry_run_json(
    *,
    tag: Mapping[str, Any],
    to_version: Mapping[str, Any],
    message: Optional[str],
    message_changes: bool,
    radius: Optional[BlastRadius],
) -> dict[str, Any]:
    """The ``--json --dry-run`` document."""
    return {
        "dryRun": True,
        "tag": tag.get("name"),
        "tagId": tag.get("id"),
        "from": {"id": tag.get("version_id"), "version": tag.get("target_version_string")},
        "to": {"id": to_version.get("id"), "version": to_version.get("version_id")},
        "message": message if message_changes else tag.get("message"),
        "affected": None
        if radius is None
        else {
            "mockRequests7d": radius.mock_requests,
            "snapshotDownloads": None if radius.snapshot_downloads is None or radius.snapshot_downloads < 0 else radius.snapshot_downloads,
            "frozen": None if radius.snapshot_downloads is None else radius.snapshot_downloads >= 0,
            "otherTags": radius.other_tags,
        },
    }
