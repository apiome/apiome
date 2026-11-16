"""Project changelog as Markdown for the public browse surface (PCX-2.1, #5896).

Backs ``GET /v1/browse/tenants/{t}/projects/{p}/changelog.md`` and the apiome-browse
``/tenant/{t}/{p}/changelog.md`` route: the same content as the Browse changelog page, as text.

The document is one block per published version, newest first, joined by a horizontal rule
(:data:`VERSION_SEPARATOR`). A classified (``ready``) version's block is **exactly**
:func:`~app.changelog_generator.render_changelog_markdown` of its stored ``ctg.changelog.v1``
payload (after the optional severity / path-group filter), so the text is byte-identical to the
generator for the same rows. Initial, failed and pending versions get a short explicit block in the
same shape (``# Changelog`` + ``**Since**`` line + note) — never an empty block.

Pure: no DB, no network. Rows come from ``Database.list_public_version_changelogs_for_project``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .changelog_generator import (
    CHANGELOG_SCHEMA_VERSION,
    Changelog,
    ChangelogEntry,
    render_changelog_markdown,
)

__all__ = [
    "CHANGELOG_SEVERITIES",
    "VERSION_SEPARATOR",
    "changelog_from_payload",
    "filter_changelog",
    "render_project_changelog_markdown",
]

#: Severities accepted by the ``severity`` filter, worst first.
CHANGELOG_SEVERITIES = ("breaking", "non-breaking", "docs-only")

#: Text placed between two version blocks.
VERSION_SEPARATOR = "\n---\n\n"


def changelog_from_payload(payload: Mapping[str, Any]) -> Changelog:
    """Rebuild a :class:`Changelog` from a stored camelCase ``ctg.changelog.v1`` payload.

    Entries keep their stored order (already severity → path group → pointer) and the stored
    ``counts`` are kept as-is, so rendering matches what the generator produced at publish time.

    Args:
        payload: The ``changelog_json`` object.

    Returns:
        The equivalent :class:`Changelog`.
    """
    entries = [
        ChangelogEntry(
            severity=e.get("severity", "docs-only"),
            path_group=e.get("pathGroup", ""),
            pointer=e.get("pointer", ""),
            rule_id=e.get("ruleId", ""),
            change_kind=e.get("changeKind") or "",
            summary=e.get("summary") or "",
            before=e.get("before"),
            after=e.get("after"),
            unclassified=bool(e.get("unclassified", False)),
            from_version=e.get("fromVersion"),
            to_version=e.get("toVersion"),
        )
        for e in payload.get("entries") or []
        if isinstance(e, Mapping)
    ]
    counts = payload.get("counts")
    return Changelog(
        schema_version=str(payload.get("schemaVersion") or CHANGELOG_SCHEMA_VERSION),
        entries=entries,
        counts=dict(counts) if isinstance(counts, Mapping) else _tally(entries),
        max_severity=payload.get("maxSeverity"),
        from_version=payload.get("fromVersion"),
        to_version=payload.get("toVersion"),
    )


def _tally(entries: Sequence[ChangelogEntry]) -> Dict[str, int]:
    """Severity / unclassified / total counts for a list of entries."""
    counts = {"breaking": 0, "non-breaking": 0, "docs-only": 0, "unclassified": 0, "total": len(entries)}
    for entry in entries:
        counts[entry.severity] = counts.get(entry.severity, 0) + 1
        if entry.unclassified:
            counts["unclassified"] += 1
    return counts


def filter_changelog(
    changelog: Changelog,
    *,
    severity: Optional[str] = None,
    path_group: Optional[str] = None,
) -> Changelog:
    """Keep only entries matching ``severity`` and ``path_group`` (each optional).

    Order is preserved (never re-sorted); counts and ``max_severity`` are recomputed for the kept
    entries. With no filter the changelog is returned unchanged.

    Args:
        changelog: The source changelog.
        severity: Keep only this severity.
        path_group: Keep only entries whose ``path_group`` equals this.

    Returns:
        The filtered changelog.
    """
    if not severity and not path_group:
        return changelog
    kept = [
        e
        for e in changelog.entries
        if (not severity or e.severity == severity) and (not path_group or e.path_group == path_group)
    ]
    worst = next((s for s in CHANGELOG_SEVERITIES if any(e.severity == s for e in kept)), None)
    return changelog.model_copy(update={"entries": kept, "counts": _tally(kept), "max_severity": worst})


def _state(row: Mapping[str, Any]) -> str:
    """``ready`` / ``initial`` / ``failed`` / ``pending`` — the same rule as the Browse page."""
    status = row.get("status")
    payload = row.get("changelog_json")
    if status == "failed":
        return "failed"
    if status == "initial" or (isinstance(payload, Mapping) and payload.get("initialPublication")):
        return "initial"
    if status == "ready" and isinstance(payload, Mapping):
        return "ready"
    return "pending"


def _state_block(row: Mapping[str, Any], state: str) -> str:
    """The explicit block for an initial / failed / pending version."""
    version = str(row.get("version_label") or "—")
    baseline = row.get("baseline_version_label") or "—"
    if state == "failed":
        note = f"_Classification failed for {version} — plain diff only._"
    elif state == "initial":
        note = "_Initial publication — no prior baseline to compare against._"
    else:
        note = f"_Changes for {version} are pending classification._"
    return "\n".join(["# Changelog", "", f"**Since** `{baseline}` → `{version}`", "", note, ""])


def render_project_changelog_markdown(
    rows: Sequence[Mapping[str, Any]],
    *,
    severity: Optional[str] = None,
    path_group: Optional[str] = None,
    since: Optional[str] = None,
) -> str:
    """Render a project's changelog rows (newest first) as one Markdown document.

    Args:
        rows: Rows from ``list_public_version_changelogs_for_project``.
        severity: Optional severity filter (entries of ``ready`` versions).
        path_group: Optional path-group filter (entries of ``ready`` versions).
        since: Optional version label; only versions published after it are kept. An unknown
            label keeps every version (matching the Browse page).

    Returns:
        The Markdown text (ends with a newline).
    """
    in_range: Sequence[Mapping[str, Any]] = rows
    if since:
        labels = [str(r.get("version_label")) for r in rows]
        if since in labels:
            in_range = rows[: labels.index(since)]

    if not in_range:
        return "# Changelog\n\nNo published versions.\n"

    blocks: List[str] = []
    for row in in_range:
        state = _state(row)
        if state == "ready":
            changelog = filter_changelog(
                changelog_from_payload(row["changelog_json"]),
                severity=severity,
                path_group=path_group,
            )
            blocks.append(render_changelog_markdown(changelog))
        else:
            blocks.append(_state_block(row, state))
    return VERSION_SEPARATOR.join(blocks)
