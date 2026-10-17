"""The rules of ``apiome versions freeze`` (CLI 4.7, #3214).

Freezing stores a published version's OpenAPI document byte-for-byte on the server
(``POST /v1/versions/{tenant}/{project}/{id}/freeze-schema``); from then on
``GET /v1/schema/{tenant}/{project}/{version}`` serves those bytes, whatever later happens to the
version's classes, properties and paths. The command asks for a dry run first so the preview shows
the snapshot's real SHA-256 and size. Unfreezing (``DELETE …/freeze-schema``) is refused once the
snapshot has been downloaded, unless ``--force-unfreeze`` (tenant administrators).

These functions turn the server's freeze responses into the command's output, without HTTP.
"""

from __future__ import annotations

from typing import Any, Mapping

from apiome_cli.project_export import human_size


def _rows(plan: Mapping[str, Any]) -> list[tuple[str, str]]:
    return [
        ("Classes:", f"{int(plan.get('classCount') or 0):,}"),
        ("Properties:", f"{int(plan.get('propertyCount') or 0):,}"),
        ("Paths:", f"{int(plan.get('pathCount') or 0):,}"),
        ("SHA-256:", str(plan.get("sha256") or "")),
        ("Size:", human_size(int(plan.get("sizeBytes") or 0))),
    ]


def _table(rows: list[tuple[str, str]]) -> list[str]:
    width = max(len(label) for label, _ in rows)
    return [f"  {label.ljust(width)} {value}" for label, value in rows]


def render_freeze_preview(plan: Mapping[str, Any]) -> str:
    """The summary shown before the confirmation, from the server's dry run."""
    label = plan.get("versionLabel")
    return "\n".join(
        [
            f"Schema snapshot for {label}:",
            *_table(_rows(plan)),
            "",
            f"After freeze, edits to {label}'s classes, properties and paths will NOT alter the",
            f"published schema at {plan.get('snapshotUrl')}.",
        ]
    )


def render_frozen(result: Mapping[str, Any]) -> str:
    """The line printed after a freeze."""
    return f"✔ Frozen. Snapshot stored at {result.get('snapshotUrl')} (SHA-256 {result.get('sha256')})"


def render_unfreeze_preview(status: Mapping[str, Any]) -> str:
    """The summary shown before unfreezing, from ``GET …/freeze-schema``."""
    label = status.get("versionLabel")
    downloads = int(status.get("downloadCount") or 0)
    return "\n".join(
        [
            f"Frozen snapshot of {label}:",
            *_table([*_rows(status), ("Downloads:", f"{downloads:,}")]),
            "",
            f"After unfreeze, {status.get('snapshotUrl')} is generated from {label}'s current classes,",
            "properties and paths again, and may no longer match the snapshot.",
        ]
    )


def render_unfrozen(result: Mapping[str, Any]) -> str:
    """The line printed after an unfreeze."""
    return f"✔ Unfrozen {result.get('versionLabel')}. {result.get('snapshotUrl')} is generated live again."


def downloaded_hint(status: Mapping[str, Any]) -> str:
    """Why ``--unfreeze`` stops (exit 6) when the snapshot has been downloaded."""
    downloads = int(status.get("downloadCount") or 0)
    return (
        f"{status.get('versionLabel')}'s snapshot has been downloaded {downloads:,} time(s); a consumer may "
        "depend on it, so it was not unfrozen. A tenant administrator can pass --force-unfreeze."
    )


def json_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """The ``--json`` shape: ``{frozen, sha256, size_bytes, snapshot_url, …}``."""
    return {
        "frozen": bool(result.get("frozen")),
        "sha256": result.get("sha256"),
        "size_bytes": result.get("sizeBytes"),
        "snapshot_url": result.get("snapshotUrl"),
        "version": result.get("versionLabel"),
        "version_record_id": result.get("versionId"),
        "classes": result.get("classCount"),
        "properties": result.get("propertyCount"),
        "paths": result.get("pathCount"),
        "download_count": result.get("downloadCount"),
        "frozen_at": result.get("frozenAt"),
    }
