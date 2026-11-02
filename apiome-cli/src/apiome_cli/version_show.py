"""The rules of ``apiome versions show`` (CLI 4.2, #3209; ported to the Python CLI by #3177).

``versions show`` prints one version's detail view: its state, dates, notes, lineage, the tags
pointing at it, its class and path counts with what changed against the version before it, a
compatibility summary from the server's engine, and the absolute URLs of its published specs.
These functions hold every decision the command makes, without HTTP:

* :func:`previous_version` — the version it is compared with (the most recent **published**
  version created before it, else the most recent one);
* :func:`class_delta` / :func:`path_delta` — added / removed / modified, by class name and by
  pathname;
* :func:`compatibility_summary` — the server's findings counted by severity;
* :func:`spec_urls` — OpenAPI, Swagger UI, Arazzo and JSON Schema URLs on the configured server;
* :func:`render_show` / :func:`to_json` — the human view and the ``--json`` document.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from apiome_cli.version_compat import SEVERITY_OF_CATEGORY, instant, newest_first

#: Keys that change on every copy of a class or property and say nothing about its shape.
_VOLATILE = frozenset(
    {"id", "created_at", "updated_at", "version_id", "class_id", "project_id", "tenant_id", "creator_id"}
)

#: Spec kind → (label, route prefix) of the published-spec routes.
SPEC_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("openapi", "OpenAPI 3.1", "schema"),
    ("swagger", "Swagger UI", "swagger"),
    ("arazzo", "Arazzo", "arazzo"),
    ("jsonSchema", "JSON Schema", "json"),
)


@dataclass(frozen=True)
class Delta:
    """What changed in one collection (classes or paths) against the previous version."""

    total: int
    added: int = 0
    removed: int = 0
    modified: int = 0

    def as_dict(self) -> dict[str, int]:
        return {"total": self.total, "added": self.added, "removed": self.removed, "modified": self.modified}


def previous_version(
    versions: Sequence[Mapping[str, Any]], current: Mapping[str, Any]
) -> Mapping[str, Any] | None:
    """The version ``current`` is compared with.

    Args:
        versions: Every version of the project.
        current: The version being shown.

    Returns:
        The most recent published version created before ``current``, else the most recent
        version of any state created before it, else ``None`` (the first version).
    """
    current_at = instant(current.get("created_at"))
    older = [
        v
        for v in newest_first(versions)
        if str(v.get("id")) != str(current.get("id")) and instant(v.get("created_at")) <= current_at
    ]
    published = [v for v in older if v.get("published")]
    return (published or older or [None])[0]


def _shape(value: Any) -> Any:
    """A record without its volatile keys, recursively, for comparing two copies of it."""
    if isinstance(value, Mapping):
        return {k: _shape(v) for k, v in sorted(value.items()) if k not in _VOLATILE}
    if isinstance(value, list):
        return sorted((_shape(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True, default=str))
    return value


def _delta(current: Sequence[Mapping[str, Any]], previous: Sequence[Mapping[str, Any]] | None, key: str) -> Delta:
    if previous is None:
        return Delta(total=len(current))
    now = {str(item.get(key)): item for item in current}
    before = {str(item.get(key)): item for item in previous}
    shared = now.keys() & before.keys()
    return Delta(
        total=len(current),
        added=len(now.keys() - before.keys()),
        removed=len(before.keys() - now.keys()),
        modified=sum(1 for name in shared if _shape(now[name]) != _shape(before[name])),
    )


def class_delta(
    classes: Sequence[Mapping[str, Any]], previous: Sequence[Mapping[str, Any]] | None
) -> Delta:
    """Classes added, removed and modified (a property added, removed or changed), by name.

    Args:
        classes: ``…/with-properties-tags`` of the shown version.
        previous: The same for the previous version, or ``None`` when there is none.
    """
    return _delta(classes, previous, "name")


def path_delta(paths: Sequence[Mapping[str, Any]], previous: Sequence[Mapping[str, Any]] | None) -> Delta:
    """Paths added, removed and modified (summary, description or metadata changed), by pathname."""
    return _delta(paths, previous, "pathname")


def compatibility_summary(report: Mapping[str, Any] | None, base: Mapping[str, Any] | None) -> dict[str, Any]:
    """The server's compatibility findings against ``base``, counted by severity.

    Args:
        report: ``POST …/compatibility`` (``findings``), or ``None`` when it was skipped or failed.
        base: The version compared with.

    Returns:
        ``{"base", "breaking", "warnings", "info", "skipped"}`` — ``skipped`` names why there is no
        verdict (no previous version, or the server could not compute one).
    """
    if base is None:
        return {"base": None, "breaking": 0, "warnings": 0, "info": 0, "skipped": "no previous version"}
    if report is None:
        return {
            "base": base.get("version_id"),
            "breaking": 0,
            "warnings": 0,
            "info": 0,
            "skipped": "the server could not compare the versions",
        }
    counts = {"error": 0, "warn": 0, "info": 0}
    for finding in report.get("findings") or []:
        severity = SEVERITY_OF_CATEGORY.get(str(finding.get("category") or ""), "warn")
        counts[severity] += 1
    return {
        "base": base.get("version_id"),
        "breaking": counts["error"],
        "warnings": counts["warn"],
        "info": counts["info"],
        "skipped": None,
    }


def spec_urls(base_url: str, tenant_slug: str, project_slug: str, version_label: str) -> dict[str, str]:
    """The absolute URLs of a version's published specs on the configured server.

    Args:
        base_url: The CLI's ``base_url`` (``https://api.example.com``).
        tenant_slug: The tenant.
        project_slug: The project's slug.
        version_label: The version label (``2.1.0``).
    """
    root = base_url.rstrip("/")
    return {
        kind: f"{root}/v1/{route}/{tenant_slug}/{project_slug}/{version_label}" for kind, _, route in SPEC_ROUTES
    }


def tags_for(version_tags: Sequence[Mapping[str, Any]], version_id: str) -> list[str]:
    """The names of the version tags pointing at ``version_id``, in tag order."""
    return [str(t.get("name")) for t in version_tags if str(t.get("version_id")) == version_id and t.get("name")]


def state(version: Mapping[str, Any]) -> str:
    """``published``, ``unpublished`` (published once, then withdrawn) or ``draft``."""
    if version.get("published"):
        return "published"
    if version.get("unpublishedAt"):
        return "unpublished"
    return "draft"


def _delta_text(delta: Delta, base_label: str | None) -> str:
    if base_label is None:
        return str(delta.total)
    return (
        f"{delta.total:<5} ({delta.added} added, {delta.removed} removed, {delta.modified} modified "
        f"vs {base_label})"
    )


def render_show(
    *,
    project_name: str,
    version: Mapping[str, Any],
    tags: Sequence[str],
    frozen: bool | None,
    classes: Delta,
    paths: Delta,
    compatibility: Mapping[str, Any],
    urls: Mapping[str, str],
    matched_tag: str | None = None,
) -> str:
    """The human detail view of one version.

    Args:
        project_name: The project's display name.
        version: The version record.
        tags: Version tags pointing at it.
        frozen: Whether its schema is frozen (``None`` when unknown).
        classes: The class delta.
        paths: The path delta.
        compatibility: :func:`compatibility_summary`.
        urls: :func:`spec_urls`.
        matched_tag: The tag the reference resolved through, when it was a tag.

    Returns:
        The view, without a trailing newline.
    """
    label = str(version.get("version_id") or "")
    heading = f"{project_name} v{label}" if project_name else f"v{label}"
    if tags:
        heading += f"  ★ {', '.join(tags)}"
    lines = []
    if matched_tag:
        lines.append(f"(tag {matched_tag!r} → {label})")
    lines += [heading, "─" * max(len(heading), 40)]

    def row(name: str, value: Any) -> None:
        if value not in (None, ""):
            lines.append(f"{name + ':':<14}{value}")

    row("State", state(version))
    row("Created", _when(version.get("created_at"), version.get("creator_email") or version.get("creator_name")))
    row("Published", _when(version.get("published_at"), None) if version.get("published") else None)
    if version.get("unpublishedAt"):
        row("Unpublished", _when(version.get("unpublishedAt"), version.get("unpublishedBy")))
        row("Reason", version.get("unpublishReason"))
    row("Frozen", "unknown" if frozen is None else ("yes" if frozen else "no"))
    if version.get("forkedFromRevisionId"):
        source = version.get("forkSourceVersionLabel") or version.get("forkedFromRevisionId")
        project = version.get("forkSourceProjectName") or version.get("upstreamProjectName")
        row("Forked from", f"{project} v{source}" if project else f"v{source}")
    row("Notes", version.get("shortMessage"))
    lines.append("")
    base = compatibility.get("base")
    row("Classes", _delta_text(classes, base))
    row("Paths", _delta_text(paths, base))
    if compatibility.get("skipped"):
        row("Compatibility", f"not compared ({compatibility['skipped']})")
    else:
        row(
            "Compatibility",
            f"{compatibility['breaking']} breaking, {compatibility['warnings']} warnings, "
            f"{compatibility['info']} info vs {base}",
        )
    lines += ["", "Specs:"]
    for kind, title, _ in SPEC_ROUTES:
        if kind in urls:
            lines.append(f"  {title:<13} →  {urls[kind]}")
    return "\n".join(lines)


def _when(at: Any, by: Any) -> str | None:
    if not at:
        return None
    text = str(at).replace("T", " ")[:16]
    return f"{text} by {by}" if by else text


def to_json(
    *,
    version: Mapping[str, Any],
    tags: Sequence[str],
    frozen: bool | None,
    classes: Delta,
    paths: Delta,
    compatibility: Mapping[str, Any],
    urls: Mapping[str, str],
    matched_by: str,
) -> dict[str, Any]:
    """The ``--json`` document: the version record plus what the view adds to it."""
    return {
        **dict(version),
        "state": state(version),
        "frozen": frozen,
        "tags": list(tags),
        "matchedBy": matched_by,
        "classes": classes.as_dict(),
        "paths": paths.as_dict(),
        "compatibility_summary": dict(compatibility),
        "spec_urls": dict(urls),
    }
