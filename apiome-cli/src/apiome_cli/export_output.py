"""Render emitter-registry export results for the ``export`` command (MFX-9.4).

Pure, stream-agnostic formatting helpers (no HTTP, no ``typer``) so the fidelity summary the
``export openapi`` command prints and the ``export targets`` table are unit-testable in isolation.
The authoritative fidelity is computed server-side by apiome-rest's prediction engine (MFX-2.3/2.5)
and returned by ``POST /export/preview``; this module only *presents* the envelope the API returns —
it never recomputes a tier, a percentage, or a count.

The fidelity envelope (``ExportPreviewResponse.fidelity``) is serialized snake_case and carries:

* ``summary`` — the coarse badge: ``tier`` (``lossless`` / ``lossy`` / ``types-only``),
  ``preserved_percent`` and per-kind counts (``dropped`` / ``approximated`` / ``synthesized``);
* ``advisory`` — the user-facing "may lose fidelity" message (MFX-2.4), shown only when lossy;
* ``target`` — the resolved emitter descriptor (``key`` / ``format`` / ``label`` / …).

``lossless`` is the only non-blocking tier: ``is_lossy`` turns every other tier into the non-zero
exit hint the ``export openapi`` command emits unless ``--force`` is given (mirroring ``convert``).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from apiome_cli.output import ListColumn

# The one fidelity tier that carries every source construct faithfully; anything else is a loss the
# command blocks on (unless --force). Mirrors ExportFidelityTier in apiome-rest/export_fidelity.py.
LOSSLESS_TIER = "lossless"


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
        ``target``), or ``None`` when the preview was unavailable.
    target:
        The requested target key/format (``openapi``), used as the label fallback.

    Returns
    -------
    list[str]
        A headline (tier + preserved-%), the per-kind loss counts when any, and — when the export is
        lossy — the server's advisory message.
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
        message = advisory.get("message")
        if isinstance(message, str) and message.strip():
            lines.append(message.strip())

    return lines


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
