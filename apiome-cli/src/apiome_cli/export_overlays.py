"""``--overlay`` support for ``apiome export`` (GVM-4.2).

Reads Overlay 1.0 / 1.1 / 1.2 files (JSON or YAML) into the inline ``overlays`` list the REST
export job accepts (``[{name, document}]``, applied in the order given), and renders what the
overlays did — the applied chain and every action that could not be applied — as stderr lines.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import typer

from apiome_cli.exit_codes import EXIT_USAGE
from apiome_cli.import_.yaml_load import safe_load

__all__ = [
    "MAX_OVERLAYS",
    "OVERLAY_HELP",
    "format_overlay_summary",
    "load_overlay_files",
]

#: The most overlays one export job accepts (apiome-rest ``MAX_EXPORT_OVERLAYS``).
MAX_OVERLAYS = 10

OVERLAY_HELP = (
    "Overlay file (JSON or YAML, Overlay 1.0–1.2) to apply to the version's OpenAPI document "
    "before it is exported. Repeatable; applied in the order given."
)


def load_overlay_files(paths: Sequence[str]) -> list[dict[str, Any]]:
    """Read ``--overlay`` files into the REST ``overlays`` list, in the order given.

    Args:
        paths: The ``--overlay`` values.

    Returns:
        ``[{"name": <file name>, "document": <parsed overlay>}, …]`` — empty when no paths.

    Raises:
        typer.Exit: :data:`EXIT_USAGE` when there are more than :data:`MAX_OVERLAYS` files, or a
            file cannot be read, does not parse, or is not an Overlay document.
    """
    if len(paths) > MAX_OVERLAYS:
        typer.echo(f"One export applies at most {MAX_OVERLAYS} overlays; got {len(paths)}.", err=True)
        raise typer.Exit(EXIT_USAGE)
    overlays: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            typer.echo(f"Cannot read overlay {raw_path!r}: {exc}", err=True)
            raise typer.Exit(EXIT_USAGE) from None
        try:
            document = safe_load(text)
        except ValueError as exc:
            typer.echo(f"Overlay {raw_path!r} is not valid JSON or YAML: {exc}", err=True)
            raise typer.Exit(EXIT_USAGE) from None
        if not isinstance(document, dict) or not isinstance(document.get("overlay"), str):
            typer.echo(
                f"{raw_path!r} is not an Overlay document: it needs a top-level `overlay: 1.x` marker.",
                err=True,
            )
            raise typer.Exit(EXIT_USAGE)
        overlays.append({"name": path.name, "document": document})
    return overlays


def format_overlay_summary(report: Mapping[str, Any] | None) -> list[str]:
    """Render a job result's ``overlay`` report as human stderr lines.

    Args:
        report: ``result.overlay`` from a completed export job, or ``None``.

    Returns:
        One summary line, then one line per finding; empty when the export had no overlays.
    """
    if not isinstance(report, Mapping):
        return []
    applied = [str(name) for name in report.get("applied") or []]
    changes = report.get("changes") or 0
    lines = [f"Overlays: applied {', '.join(applied) or 'none'} — {changes} value(s) changed"]
    if report.get("truncated"):
        lines[0] += " (ledger lists the first 500)"
    for finding in report.get("findings") or []:
        if not isinstance(finding, Mapping):
            continue
        target = finding.get("target")
        where = f" (action #{finding.get('action_index')}, target {target})" if target else ""
        lines.append(
            f"  {finding.get('rule')} in {finding.get('overlay')!r}{where}: {finding.get('message')}"
        )
    return lines
