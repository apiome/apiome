"""Render emitter-registry export results for the ``export`` command (MFX-9.4 / MFX-8.2).

Pure, stream-agnostic formatting helpers (no HTTP) so the fidelity summary the export commands
print and the ``export targets`` table are unit-testable in isolation. The authoritative fidelity
is computed server-side by apiome-rest's prediction engine (MFX-2.3/2.5) and returned by
``POST /export/preview``; this module only *presents* the envelope the API returns — it never
recomputes a tier, a percentage, or a count.

The fidelity envelope (``ExportPreviewResponse.fidelity``) is serialized snake_case and carries:

* ``summary`` — the coarse badge: ``tier`` (``lossless`` / ``lossy`` / ``types-only``),
  ``preserved_percent`` and per-kind counts (``dropped`` / ``approximated`` / ``synthesized``);
* ``advisory`` — the user-facing "may lose fidelity" message (MFX-2.4), shown only when lossy;
* ``report`` — the per-construct ``LossinessReport`` rendered as a concise loss table;
* ``target`` — the resolved emitter descriptor (``key`` / ``format`` / ``label`` / …).

``lossless`` is the only non-blocking tier: ``is_lossy`` turns every other tier into the non-zero
exit hint the export commands emit unless ``--force`` or the user confirms at an interactive
prompt (MFX-8.2).
"""

from __future__ import annotations

import sys
from typing import Any, Mapping, Sequence

import typer

from apiome_cli.exit_codes import EXIT_ERROR
from apiome_cli.output import ListColumn

# The one fidelity tier that carries every source construct faithfully; anything else is a loss the
# command blocks on (unless --force or interactive confirm). Mirrors ExportFidelityTier in
# apiome-rest/export_fidelity.py.
LOSSLESS_TIER = "lossless"

# Worst-first ordering mirrors apiome-ui/exportFidelityPreview.ts (MFX-6.2).
_KIND_ORDER: dict[str, int] = {"drop": 0, "approx": 1, "synth": 2, "ok": 3}
_SEVERITY_ORDER: dict[str, int] = {"critical": 0, "warn": 1, "warning": 1, "info": 2}

# Non-OK rows shown in the CLI loss table; overflow points callers at --json.
_MAX_LOSS_TABLE_ROWS = 12


def _summary(fidelity: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return the coarse ``summary`` badge mapping, or an empty mapping when absent."""
    summary = fidelity.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def fidelity_tier(fidelity: Mapping[str, Any]) -> str:
    """Return the export's coarse fidelity tier (``lossless`` / ``lossy`` / ``types-only``), lowered."""
    return str(_summary(fidelity).get("tier", "")).strip().lower()


def is_lossy(fidelity: Mapping[str, Any] | None) -> bool:
    """True when the export loses fidelity — the signal the command turns into a non-zero hint.

    A missing or tier-less envelope is treated as **not** lossy: with nothing to prove a loss, the
    command should not block the write. Only a present tier other than ``lossless`` blocks.
    """
    if not isinstance(fidelity, Mapping):
        return False
    tier = fidelity_tier(fidelity)
    return bool(tier) and tier != LOSSLESS_TIER


def _target_label(fidelity: Mapping[str, Any], fallback: str) -> str:
    """Return the resolved emitter's human label (e.g. ``OpenAPI 3.1``), or ``fallback``."""
    target = fidelity.get("target")
    if isinstance(target, Mapping):
        label = target.get("label")
        if isinstance(label, str) and label.strip():
            return label.strip()
    return fallback


def _item_message(item: Mapping[str, Any]) -> str:
    """Return the human explanation for one loss item (``message`` or legacy ``detail``)."""
    for key in ("message", "detail"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def kind_label(kind: str) -> str:
    """Return the uppercase kind badge label (``DROP``, ``APPROX``, …)."""
    return kind.strip().upper() or "?"


def sort_report_items_worst_first(items: Sequence[Any]) -> list[Mapping[str, Any]]:
    """Order report items worst-first: kind, severity, construct key (MFX-6.2 / MFX-8.2)."""

    def sort_key(item: Mapping[str, Any]) -> tuple[int, int, str]:
        kind = str(item.get("kind", "")).strip().lower()
        severity = str(item.get("severity", "")).strip().lower()
        construct = str(item.get("construct", "")).strip().lower()
        return (
            _KIND_ORDER.get(kind, 99),
            _SEVERITY_ORDER.get(severity, 99),
            construct,
        )

    rows = [item for item in items if isinstance(item, Mapping)]
    return sorted(rows, key=sort_key)


def _loss_table_items(fidelity: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return non-OK report rows for the concise loss table."""
    report = fidelity.get("report")
    if not isinstance(report, Mapping):
        return []
    items = report.get("items")
    if not isinstance(items, list):
        return []
    return [
        item
        for item in sort_report_items_worst_first(items)
        if isinstance(item, Mapping) and str(item.get("kind", "")).strip().lower() != "ok"
    ]


def format_loss_table_lines(
    fidelity: Mapping[str, Any] | None,
    *,
    max_rows: int = _MAX_LOSS_TABLE_ROWS,
) -> list[str]:
    """Build the concise per-construct loss table for stderr (MFX-8.2)."""
    if not isinstance(fidelity, Mapping):
        return []

    rows = _loss_table_items(fidelity)
    if not rows:
        return []

    lines = ["Per-construct losses:"]
    for item in rows[:max_rows]:
        kind = kind_label(str(item.get("kind", "")))
        construct = str(item.get("construct", "")).strip() or "construct"
        message = _item_message(item)
        mapping = item.get("target_mapping")
        detail = message
        if isinstance(mapping, str) and mapping.strip():
            detail = f"{message} → {mapping.strip()}" if message else mapping.strip()
        if detail:
            lines.append(f"  {kind:<6} {construct} — {detail}")
        else:
            lines.append(f"  {kind:<6} {construct}")

    overflow = len(rows) - max_rows
    if overflow > 0:
        lines.append(f"  … and {overflow} more (use --json for the full report).")
    return lines


def format_export_fidelity_summary(
    fidelity: Mapping[str, Any] | None,
    *,
    target: str,
) -> list[str]:
    """Build the human-readable fidelity summary lines for an export.

    Parameters
    ----------
    fidelity:
        The ``fidelity`` envelope from ``POST /export/preview`` (``summary`` + ``advisory`` +
        ``report`` + ``target``), or ``None`` when the preview was unavailable.
    target:
        The requested target key/format (``openapi``), used as the label fallback.

    Returns
    -------
    list[str]
        A headline (tier + preserved-%), per-kind loss counts, the server advisory (MFX-2.4),
        and the concise per-construct loss table when the export is lossy.
    """
    if not isinstance(fidelity, Mapping):
        return ["Fidelity preview unavailable; the document was exported without a fidelity report."]

    summary = _summary(fidelity)
    tier = fidelity_tier(fidelity) or "unknown"
    preserved = summary.get("preserved_percent")
    label = _target_label(fidelity, target)

    lines: list[str] = []
    if isinstance(preserved, int):
        lines.append(f"Export to {label}: fidelity {tier} ({preserved}% preserved).")
    else:
        lines.append(f"Export to {label}: fidelity {tier}.")

    counts = [
        (summary.get("dropped"), "dropped"),
        (summary.get("approximated"), "approximated"),
        (summary.get("synthesized"), "synthesized"),
    ]
    detail = ", ".join(f"{value} {name}" for value, name in counts if isinstance(value, int) and value)
    if detail:
        lines.append(f"Constructs: {detail}.")

    advisory = fidelity.get("advisory")
    if isinstance(advisory, Mapping) and advisory.get("show"):
        headline = advisory.get("headline")
        if isinstance(headline, str) and headline.strip():
            lines.append(headline.strip())
        message = advisory.get("message")
        if isinstance(message, str) and message.strip():
            lines.append(message.strip())

    lines.extend(format_loss_table_lines(fidelity))
    return lines


_LOSSY_EXIT_HINT = (
    "Lossy export — the emitted document does not carry every source construct. "
    "Re-run with --force to accept."
)


def enforce_export_fidelity_gate(
    fidelity: Mapping[str, Any] | None,
    *,
    force: bool,
) -> None:
    """Exit non-zero when the export is lossy and not accepted via ``--force`` or a TTY confirm."""
    if not is_lossy(fidelity):
        return
    if force:
        return
    if sys.stdin.isatty() and typer.confirm(
        "Export anyway despite fidelity loss?",
        default=False,
    ):
        return
    typer.echo(_LOSSY_EXIT_HINT, err=True)
    raise typer.Exit(EXIT_ERROR)


def _target_row(target: Mapping[str, Any]) -> dict[str, Any]:
    """Flatten one ``ExportTargetFidelity`` into a flat row for the targets table."""
    descriptor = target.get("descriptor") if isinstance(target.get("descriptor"), Mapping) else {}
    fidelity = target.get("fidelity") if isinstance(target.get("fidelity"), Mapping) else {}
    available = descriptor.get("available")
    return {
        "key": descriptor.get("key"),
        "format": descriptor.get("format"),
        "label": descriptor.get("label"),
        "paradigm": descriptor.get("paradigm"),
        "tier": fidelity.get("tier"),
        "preserved_percent": fidelity.get("preserved_percent"),
        "available": "yes" if available or available is None else "no",
    }


def target_rows(targets: Sequence[Any]) -> list[dict[str, Any]]:
    """Flatten the ``targets`` list from ``GET /export/targets`` into table rows."""
    return [_target_row(target) for target in targets if isinstance(target, Mapping)]


def _format_percent(value: Any) -> str:
    """Format a preserved-percent cell as ``NN%`` (empty when absent)."""
    return f"{value}%" if isinstance(value, int) else ""


# Column layout for the ``export targets`` table (header, row key, optional formatter).
EXPORT_TARGET_COLUMNS: tuple[ListColumn, ...] = (
    ("Key", "key", None),
    ("Format", "format", None),
    ("Label", "label", None),
    ("Paradigm", "paradigm", None),
    ("Fidelity", "tier", None),
    ("Preserved", "preserved_percent", _format_percent),
    ("Available", "available", None),
)
