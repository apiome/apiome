"""CTG-1.3 changelog generator (#4469).

Turns classified OpenAPI diffs (:class:`~app.change_taxonomy.ClassifiedDiff`) into
an ordered, grouped, human-readable changelog with stable **markdown** and
**JSON** renderers. Also supports **"since <version>"** aggregation across a
chain of intermediate version pairs.

Ordering (deterministic for the same input):

1. Severity: breaking → non-breaking → docs-only
2. Within severity: ``path_group`` (lexicographic)
3. Within group: ``pointer``, then ``rule_id``, then ``change_kind``

This module is pure (no DB, no network). Persist/publish hooks are CTG-3.1+.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from .change_taxonomy import (
    ClassifiedChange,
    ClassifiedDiff,
    Severity,
    classify_openapi_changes,
)
from .change_taxonomy_rules import get_rule

__all__ = [
    "CHANGELOG_SCHEMA_VERSION",
    "Changelog",
    "ChangelogEntry",
    "aggregate_classified_diffs",
    "aggregate_changelogs",
    "build_changelog",
    "changelog_since",
    "path_group_for_pointer",
    "render_changelog_json",
    "render_changelog_json_text",
    "render_changelog_markdown",
]

#: Stable schema id for JSON consumers (CTG-2.2 PR comments, CTG-3.x UI/webhooks).
CHANGELOG_SCHEMA_VERSION = "ctg.changelog.v1"

_SEVERITY_ORDER: Dict[Severity, int] = {
    "breaking": 0,
    "non-breaking": 1,
    "docs-only": 2,
}

_SEVERITY_RANK: Dict[Severity, int] = {
    "docs-only": 0,
    "non-breaking": 1,
    "breaking": 2,
}

_SEVERITY_HEADINGS: Dict[Severity, str] = {
    "breaking": "Breaking changes",
    "non-breaking": "Non-breaking changes",
    "docs-only": "Documentation changes",
}


class ChangelogEntry(BaseModel):
    """One ordered, display-ready change in a changelog.

    Attributes:
        severity: ``breaking`` / ``non-breaking`` / ``docs-only``.
        path_group: Grouping key derived from the JSON Pointer (e.g. path or schema).
        pointer: JSON Pointer to the changed node.
        rule_id: Stable taxonomy rule id.
        change_kind: Raw enumerator kind.
        summary: Human one-liner (from the taxonomy rule, or a fail-safe default).
        before: Value in the older document (``None`` if added).
        after: Value in the newer document (``None`` if removed).
        unclassified: ``True`` when the classifier failed safe.
        from_version: Optional version label for the base of the hop that produced this entry.
        to_version: Optional version label for the head of the hop that produced this entry.
    """

    severity: Severity
    path_group: str
    pointer: str
    rule_id: str
    change_kind: str = ""
    summary: str = ""
    before: Any = None
    after: Any = None
    unclassified: bool = False
    from_version: Optional[str] = None
    to_version: Optional[str] = None


class Changelog(BaseModel):
    """Ordered changelog ready for markdown/JSON rendering.

    Attributes:
        schema_version: Stable format id (``ctg.changelog.v1``).
        entries: Changes in deterministic severity → path_group → pointer order.
        counts: Tallies for breaking / non-breaking / docs-only / unclassified / total.
        max_severity: Worst severity across entries; ``None`` when empty.
        from_version: Optional aggregate base version label (``since`` / pair base).
        to_version: Optional aggregate head version label.
    """

    schema_version: str = Field(default=CHANGELOG_SCHEMA_VERSION)
    entries: List[ChangelogEntry] = Field(default_factory=list)
    counts: Dict[str, int] = Field(default_factory=dict)
    max_severity: Optional[Severity] = None
    from_version: Optional[str] = None
    to_version: Optional[str] = None


def path_group_for_pointer(pointer: str) -> str:
    """Derive a stable grouping key from a JSON Pointer.

    Groups OpenAPI surface under path, component schema, operation-ish nodes,
    servers, tags, info, or the first two pointer segments otherwise.

    Args:
        pointer: JSON Pointer (e.g. ``/paths/~1pets/get/responses/200``).

    Returns:
        A grouping key such as ``/paths/~1pets`` or ``/components/schemas/Pet``.
    """
    if not pointer or pointer == "/":
        return "/"

    raw = pointer if pointer.startswith("/") else f"/{pointer}"
    parts = [p for p in raw.split("/") if p != ""]
    if not parts:
        return "/"

    head = parts[0]

    if head == "paths" and len(parts) >= 2:
        return "/" + "/".join(parts[:2])

    if head == "components" and len(parts) >= 3:
        return "/" + "/".join(parts[:3])

    if head == "components" and len(parts) >= 2:
        return "/" + "/".join(parts[:2])

    if head in ("servers", "tags", "security", "webhooks") and len(parts) >= 1:
        # Keep the collection as the group; index tokens stay under it.
        return f"/{head}"

    if head == "info":
        return "/info"

    if len(parts) >= 2:
        return "/" + "/".join(parts[:2])
    return f"/{head}"


def _summary_for_change(change: ClassifiedChange) -> str:
    rule = get_rule(change.rule_id)
    if rule is not None and rule.summary:
        return rule.summary
    if change.unclassified:
        return "Unclassified change (treated as breaking)."
    if change.change_kind:
        return f"Change of kind `{change.change_kind}`."
    return f"Change under rule `{change.rule_id}`."


def _entry_from_change(
    change: ClassifiedChange,
    *,
    from_version: Optional[str] = None,
    to_version: Optional[str] = None,
) -> ChangelogEntry:
    return ChangelogEntry(
        severity=change.severity,
        path_group=path_group_for_pointer(change.pointer),
        pointer=change.pointer,
        rule_id=change.rule_id,
        change_kind=change.change_kind or "",
        summary=_summary_for_change(change),
        before=change.before,
        after=change.after,
        unclassified=change.unclassified,
        from_version=from_version,
        to_version=to_version,
    )


def _sort_key(entry: ChangelogEntry) -> Tuple[int, str, str, str, str]:
    return (
        _SEVERITY_ORDER.get(entry.severity, 99),
        entry.path_group,
        entry.pointer,
        entry.rule_id,
        entry.change_kind,
    )


def _sort_entries(entries: Iterable[ChangelogEntry]) -> List[ChangelogEntry]:
    return sorted(entries, key=_sort_key)


def _worst(severities: Sequence[Severity]) -> Optional[Severity]:
    if not severities:
        return None
    worst: Severity = "docs-only"
    for severity in severities:
        if _SEVERITY_RANK[severity] > _SEVERITY_RANK[worst]:
            worst = severity
    return worst


def _tally(entries: Sequence[ChangelogEntry]) -> Dict[str, int]:
    counts = {
        "breaking": 0,
        "non-breaking": 0,
        "docs-only": 0,
        "unclassified": 0,
        "total": len(entries),
    }
    for entry in entries:
        counts[entry.severity] = counts.get(entry.severity, 0) + 1
        if entry.unclassified:
            counts["unclassified"] += 1
    return counts


def _finalize(
    entries: Sequence[ChangelogEntry],
    *,
    from_version: Optional[str] = None,
    to_version: Optional[str] = None,
) -> Changelog:
    ordered = _sort_entries(entries)
    return Changelog(
        schema_version=CHANGELOG_SCHEMA_VERSION,
        entries=ordered,
        counts=_tally(ordered),
        max_severity=_worst([e.severity for e in ordered]),
        from_version=from_version,
        to_version=to_version,
    )


def build_changelog(
    classified: ClassifiedDiff,
    *,
    from_version: Optional[str] = None,
    to_version: Optional[str] = None,
) -> Changelog:
    """Build an ordered changelog from a single classified adjacent pair.

    Args:
        classified: Output of :func:`~app.change_taxonomy.classify_openapi_changes`.
        from_version: Optional base version label.
        to_version: Optional head version label.

    Returns:
        A :class:`Changelog` with deterministic entry order.
    """
    entries = [_entry_from_change(c, from_version=from_version, to_version=to_version) for c in classified.changes]
    return _finalize(entries, from_version=from_version, to_version=to_version)


def aggregate_changelogs(
    changelogs: Sequence[Changelog],
    *,
    from_version: Optional[str] = None,
    to_version: Optional[str] = None,
) -> Changelog:
    """Merge multiple changelogs into one ordered aggregate.

    Entries keep their per-hop ``from_version`` / ``to_version`` when present.
    The aggregate's ``from_version`` / ``to_version`` default to the first
    segment's base and the last segment's head when not overridden.

    Args:
        changelogs: Ordered segments (oldest→newest hops).
        from_version: Override for the aggregate base label.
        to_version: Override for the aggregate head label.

    Returns:
        A single :class:`Changelog` re-sorted by severity → path_group → pointer.
    """
    if not changelogs:
        return _finalize([], from_version=from_version, to_version=to_version)

    merged: List[ChangelogEntry] = []
    for cl in changelogs:
        merged.extend(cl.entries)

    base = from_version
    if base is None:
        for cl in changelogs:
            if cl.from_version:
                base = cl.from_version
                break

    head = to_version
    if head is None:
        for cl in reversed(changelogs):
            if cl.to_version:
                head = cl.to_version
                break

    return _finalize(merged, from_version=base, to_version=head)


def aggregate_classified_diffs(
    segments: Sequence[Tuple[Optional[str], Optional[str], ClassifiedDiff]],
    *,
    from_version: Optional[str] = None,
    to_version: Optional[str] = None,
) -> Changelog:
    """Aggregate a chain of ``(from_label, to_label, ClassifiedDiff)`` hops.

    Args:
        segments: Consecutive classified pairs, oldest base → newest head.
        from_version: Optional override for the aggregate base label.
        to_version: Optional override for the aggregate head label.

    Returns:
        Aggregated :class:`Changelog`.
    """
    changelogs = [build_changelog(diff, from_version=frm, to_version=to) for frm, to, diff in segments]
    return aggregate_changelogs(changelogs, from_version=from_version, to_version=to_version)


def changelog_since(
    documents: Sequence[Tuple[str, Mapping[str, Any]]],
    *,
    overrides: Optional[Mapping[str, Severity]] = None,
) -> Changelog:
    """Classify and aggregate changelogs across a version chain ("since <version>").

    ``documents[0]`` is the ``since`` baseline; each subsequent document is
    classified against its predecessor. The aggregate spans
    ``documents[0].label`` → ``documents[-1].label``.

    Args:
        documents: Ordered ``(version_label, openapi_doc)`` pairs, oldest first.
        overrides: Optional per-call taxonomy severity overrides.

    Returns:
        Aggregated :class:`Changelog`. Empty when fewer than two documents.

    Raises:
        ValueError: If any version label is empty.
    """
    if len(documents) < 2:
        label = documents[0][0] if documents else None
        return _finalize([], from_version=label, to_version=label)

    for label, _ in documents:
        if not label or not str(label).strip():
            raise ValueError("version labels in documents must be non-empty")

    segments: List[Tuple[Optional[str], Optional[str], ClassifiedDiff]] = []
    for i in range(1, len(documents)):
        from_label, base_doc = documents[i - 1]
        to_label, head_doc = documents[i]
        diff = classify_openapi_changes(dict(base_doc), dict(head_doc), overrides=overrides)
        segments.append((from_label, to_label, diff))

    return aggregate_classified_diffs(
        segments,
        from_version=documents[0][0],
        to_version=documents[-1][0],
    )


def _display_path_group(path_group: str) -> str:
    """Decode a JSON-Pointer path group for markdown headings."""
    if not path_group.startswith("/"):
        return path_group
    parts = path_group.split("/")[1:]
    decoded = [p.replace("~1", "/").replace("~0", "~") for p in parts]
    if not decoded:
        return "/"
    if decoded[0] == "paths" and len(decoded) >= 2:
        return decoded[1]
    return "/" + "/".join(decoded)


def render_changelog_markdown(changelog: Changelog) -> str:
    """Render a changelog as stable, human-readable markdown.

    Args:
        changelog: Ordered changelog from :func:`build_changelog` or aggregation.

    Returns:
        Markdown text with severity sections and path groups. Empty changelogs
        produce a short "No changes" document.
    """
    lines: List[str] = ["# Changelog", ""]

    if changelog.from_version or changelog.to_version:
        frm = changelog.from_version or "—"
        to = changelog.to_version or "—"
        lines.append(f"**Since** `{frm}` → `{to}`")
        lines.append("")

    counts = changelog.counts or {}
    total = counts.get("total", len(changelog.entries))
    if total == 0:
        lines.append("No changes.")
        lines.append("")
        return "\n".join(lines)

    summary_bits = [
        f"{counts.get('breaking', 0)} breaking",
        f"{counts.get('non-breaking', 0)} non-breaking",
        f"{counts.get('docs-only', 0)} docs-only",
    ]
    if counts.get("unclassified"):
        summary_bits.append(f"{counts['unclassified']} unclassified")
    lines.append(f"_{total} change(s): " + ", ".join(summary_bits) + "._")
    lines.append("")

    current_severity: Optional[Severity] = None
    current_group: Optional[str] = None

    for entry in changelog.entries:
        if entry.severity != current_severity:
            current_severity = entry.severity
            current_group = None
            heading = _SEVERITY_HEADINGS.get(entry.severity, entry.severity)
            lines.append(f"## {heading}")
            lines.append("")

        if entry.path_group != current_group:
            current_group = entry.path_group
            lines.append(f"### `{_display_path_group(entry.path_group)}`")
            lines.append("")

        badge = ""
        if entry.unclassified:
            badge = " _(unclassified)_"
        hop = ""
        if entry.from_version or entry.to_version:
            hop = f" _{entry.from_version or '—'} → {entry.to_version or '—'}_"

        lines.append(f"- **{entry.summary.rstrip('.')}** (`{entry.rule_id}`) — `{entry.pointer}`{badge}{hop}")

    lines.append("")
    return "\n".join(lines)


def render_changelog_json(changelog: Changelog) -> Dict[str, Any]:
    """Render a changelog as a schema-stable JSON-serializable dict.

    Keys use camelCase for downstream UI / webhook / CLI consumers.

    Args:
        changelog: Ordered changelog.

    Returns:
        Dict with ``schemaVersion``, ``fromVersion``, ``toVersion``, ``counts``,
        ``maxSeverity``, and ``entries``.
    """
    return {
        "schemaVersion": changelog.schema_version,
        "fromVersion": changelog.from_version,
        "toVersion": changelog.to_version,
        "counts": dict(changelog.counts),
        "maxSeverity": changelog.max_severity,
        "entries": [
            {
                "severity": e.severity,
                "pathGroup": e.path_group,
                "pointer": e.pointer,
                "ruleId": e.rule_id,
                "changeKind": e.change_kind,
                "summary": e.summary,
                "before": e.before,
                "after": e.after,
                "unclassified": e.unclassified,
                "fromVersion": e.from_version,
                "toVersion": e.to_version,
            }
            for e in changelog.entries
        ],
    }


def render_changelog_json_text(changelog: Changelog, *, indent: Optional[int] = 2) -> str:
    """Serialize :func:`render_changelog_json` to a stable JSON string.

    Args:
        changelog: Ordered changelog.
        indent: ``json.dumps`` indent (``None`` for compact).

    Returns:
        UTF-8 JSON text with sorted keys for byte-stable fixtures.
    """
    return json.dumps(
        render_changelog_json(changelog),
        indent=indent,
        sort_keys=True,
        ensure_ascii=False,
        default=str,
    ) + ("\n" if indent is not None else "")
