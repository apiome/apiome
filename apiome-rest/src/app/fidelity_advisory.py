"""User-facing fidelity advisory message — MFX-2.4 (#3841).

MFX-2.1 (:mod:`app.lossiness`) gives fidelity loss a *structure* — an ordered list
of :class:`~app.lossiness.LossItem` — and MFX-2.2 (:mod:`app.fidelity_engine`) is the
engine that *populates* it for a given source → target export. This module is the
last mile: it turns that structured report into the single **user-facing advisory**
the product promised — the plain-language *"exporting to {format} may lose some
fidelity"* message, with the counts that make it honest and the severity threshold
that decides whether it is shown at all.

**One string source, many consumers.** The wording lives here, in Python, once. The
export dialog (MFX-6.2, apiome-ui), the public browse export (MFX-7.2, apiome-browse),
and the CLI (MFX-8.2) all render the *same* :class:`ExportAdvisory` — the message is
computed server-side and carried verbatim in the export / dry-run response
(MFX-2.5), so the wording is identical across every surface by construction, never
re-templated per client. TypeScript consumers mirror the model field-for-field (see
``apiome-ui/src/app/utils/export-advisory.ts``) and display ``message`` /
``headline`` directly; they never recompute the copy.

**Shown only when it matters.** A high-fidelity, lossless export (e.g. a same-format
round-trip) says nothing — :attr:`ExportAdvisory.show` is ``False`` and the surfaces
stay quiet. A lossy export raises the advisory, and the counts (``dropped`` /
``approximated`` / ``synthesized``) come straight from the report so the message can
never overstate or understate the loss. The ``min_severity`` threshold lets a caller
relax the advisory to *warn-and-above* (suppressing cosmetic ``info`` losses) without
changing the wording.

The message is **derived purely** from a :class:`~app.lossiness.LossinessReport` and a
target label — no I/O, no clock — so a preview advisory and the advisory attached to
the eventual export are identical for the same inputs.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .lossiness import (
    _SEVERITY_ORDER,
    LossinessKind,
    LossinessReport,
    LossinessSeverity,
)

__all__ = [
    "ADVISORY_HEADLINE_TEMPLATE",
    "ADVISORY_MESSAGE_TEMPLATE",
    "LOSSLESS_HEADLINE_TEMPLATE",
    "LOSSLESS_MESSAGE_TEMPLATE",
    "ExportAdvisory",
    "build_export_advisory",
]


# ---------------------------------------------------------------------------
# Canonical copy (the "string source" — kept as module constants for i18n).
# ``{format}`` is the human target label; ``{constructs}`` is an already-pluralized
# noun phrase ("1 construct" / "7 constructs"). Consumers must NOT re-template these;
# they render the finished ``ExportAdvisory.message`` / ``.headline``.
# ---------------------------------------------------------------------------

#: The advisory shown for a lossy export. Mirrors the ROADMAP MFX-2.4 wording.
ADVISORY_MESSAGE_TEMPLATE = (
    "Exporting to {format} may lose some fidelity. The destination format can't "
    "represent everything in this API, so {constructs} will be dropped or "
    "approximated — review the fidelity report before downloading."
)

#: Short banner heading that accompanies the advisory message.
ADVISORY_HEADLINE_TEMPLATE = (
    "Fidelity notice — exporting to {format} may lose detail."
)

#: Reassurance copy for a lossless export. Carried on the advisory even though
#: :attr:`ExportAdvisory.show` is ``False``, so a surface that wants to affirm a
#: clean round-trip has ready wording instead of inventing its own.
LOSSLESS_MESSAGE_TEMPLATE = (
    "Exporting to {format} preserves full fidelity — every construct in this API "
    "maps cleanly onto the target format."
)

#: Short banner heading for a lossless export.
LOSSLESS_HEADLINE_TEMPLATE = "No fidelity loss exporting to {format}."


def _pluralize_constructs(count: int) -> str:
    """Return an English noun phrase for ``count`` constructs.

    ``1`` → ``"1 construct"``; any other count → ``"N constructs"``. Used to build
    the advisory message so its count reads grammatically without the surfaces
    having to pluralize.
    """
    noun = "construct" if count == 1 else "constructs"
    return f"{count} {noun}"


class ExportAdvisory(BaseModel):
    """The single user-facing advisory for one cross-format (or lossy) export.

    Built from a :class:`~app.lossiness.LossinessReport` and a human target label by
    :func:`build_export_advisory`, then carried verbatim in the export / dry-run REST
    response (MFX-2.5) so every surface — apiome-ui (MFX-6.2), apiome-browse
    (MFX-7.2), apiome-cli (MFX-8.2) — renders identical wording.

    The two acceptance criteria of MFX-2.4 are properties of this model:

    * **reflects real counts** — ``dropped`` / ``approximated`` / ``synthesized`` and
      the ``{constructs}`` woven into ``message`` come straight from the report's
      per-kind counts, so the copy can never drift from the loss it describes;
    * **shown when lossy, hidden when lossless** — :attr:`show` is ``False`` for a
      clean export (or one whose only losses fall below the caller's severity
      threshold), and consumers gate their banner on it.
    """

    model_config = ConfigDict(extra="forbid")

    show: bool = Field(
        description="Whether to surface the advisory at all. ``False`` for a "
        "lossless export (or one whose losses are all below the requested "
        "severity threshold); consumers hide their banner when this is ``False``.",
    )
    severity: Optional[LossinessSeverity] = Field(
        default=None,
        description="The worst severity among the lossy constructs, driving how "
        "loudly the surface flags the export. ``None`` for a lossless export.",
    )
    requires_ack: bool = Field(
        default=False,
        description="Whether the export warrants an explicit dismiss-to-proceed "
        "acknowledgement — ``True`` only when a ``critical`` construct is lost.",
    )
    target_format: str = Field(
        description="Human label for the target format woven into the copy "
        "(e.g. ``Protobuf``, ``OpenAPI 3.1``).",
    )
    dropped: int = Field(
        description="Number of constructs dropped entirely (LossinessKind.DROP).",
    )
    approximated: int = Field(
        description="Number of constructs represented imperfectly (APPROX).",
    )
    synthesized: int = Field(
        description="Number of constructs invented to satisfy the target (SYNTH).",
    )
    affected: int = Field(
        description="Total constructs changed by the export "
        "(``dropped + approximated + synthesized``) — the count woven into the "
        "message.",
    )
    headline: str = Field(
        description="Short banner heading for the advisory (or the lossless "
        "reassurance heading when :attr:`show` is ``False``).",
    )
    message: str = Field(
        description="The full, ready-to-display advisory sentence. Consumers render "
        "this verbatim — they must not re-template it — so wording is identical "
        "across UI, browse, and CLI.",
    )


def build_export_advisory(
    report: LossinessReport,
    target_format: str,
    *,
    min_severity: LossinessSeverity = LossinessSeverity.INFO,
) -> ExportAdvisory:
    """Build the user-facing :class:`ExportAdvisory` for one export.

    Derives the advisory purely from ``report`` and ``target_format`` — no I/O, no
    clock — so a dry-run preview and the advisory attached to the eventual export are
    identical for the same inputs.

    The advisory is **shown** when the export is lossy *and* its worst loss reaches
    ``min_severity``; it is **suppressed** (``show=False``) for a lossless export or
    one whose only losses fall below the threshold. Whether shown or not, the counts
    and copy always reflect the report, so a consumer may still read the counts off a
    suppressed advisory.

    Args:
        report: The computed fidelity report for the export (MFX-2.2).
        target_format: Human label for the target format woven into the copy
            (e.g. ``"Protobuf"``, ``"OpenAPI 3.1"``).
        min_severity: The lowest severity that raises the advisory. Defaults to
            :attr:`~app.lossiness.LossinessSeverity.INFO` (any real loss shows);
            pass :attr:`~app.lossiness.LossinessSeverity.WARN` to suppress cosmetic
            info-level losses without changing the wording.

    Returns:
        The :class:`ExportAdvisory` for the export.
    """
    dropped = report.kind_counts.get(LossinessKind.DROP.value, 0)
    approximated = report.kind_counts.get(LossinessKind.APPROX.value, 0)
    synthesized = report.kind_counts.get(LossinessKind.SYNTH.value, 0)
    affected = dropped + approximated + synthesized

    worst = report.worst_severity
    # Show when the export is lossy and its worst loss reaches the threshold. A lower
    # ``_SEVERITY_ORDER`` rank is *more* severe, so "reaches the threshold" is
    # rank(worst) <= rank(min_severity).
    show = worst is not None and _SEVERITY_ORDER[worst] <= _SEVERITY_ORDER[min_severity]

    if show:
        constructs = _pluralize_constructs(affected)
        message = ADVISORY_MESSAGE_TEMPLATE.format(
            format=target_format, constructs=constructs
        )
        headline = ADVISORY_HEADLINE_TEMPLATE.format(format=target_format)
        return ExportAdvisory(
            show=True,
            severity=worst,
            requires_ack=worst is LossinessSeverity.CRITICAL,
            target_format=target_format,
            dropped=dropped,
            approximated=approximated,
            synthesized=synthesized,
            affected=affected,
            headline=headline,
            message=message,
        )

    # Lossless (or all losses below threshold): stay quiet, but carry reassurance copy
    # and the true (possibly non-zero, sub-threshold) counts for any consumer that
    # wants them.
    return ExportAdvisory(
        show=False,
        severity=worst,
        requires_ack=False,
        target_format=target_format,
        dropped=dropped,
        approximated=approximated,
        synthesized=synthesized,
        affected=affected,
        headline=LOSSLESS_HEADLINE_TEMPLATE.format(format=target_format),
        message=LOSSLESS_MESSAGE_TEMPLATE.format(format=target_format),
    )
