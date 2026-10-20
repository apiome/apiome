"""Merged fidelity summary for a multi-target export job — MFX-39.1 (#4333).

A multi-target export emits one source version to N targets in a single job. Each target keeps
its own full :class:`~app.export_fidelity.ExportFidelity` envelope (tier + report + advisory) on
the job result; this module folds those envelopes into one **rollup** a caller can show as a
single headline ("3 targets — worst: lossy, 82% preserved at the floor") without walking every
report.

The rollup is pure: it reads only the per-target summaries (and each target's transcode-guard
verdict), so the same inputs always produce the same rollup, whether it is computed for a
dry-run or a real export.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from .export_fidelity import ExportFidelity, ExportFidelityTier
from .transcoding_guards import TranscodeGuard

__all__ = [
    "TIER_ORDER",
    "ExportFidelityRollupEntry",
    "ExportFidelityRollup",
    "build_fidelity_rollup",
]

#: Tiers from best to worst. ``types-only`` ranks below ``lossy`` because it drops every
#: operation, not just some constructs; the rollup headline is the worst tier present.
TIER_ORDER: Tuple[ExportFidelityTier, ...] = (
    ExportFidelityTier.LOSSLESS,
    ExportFidelityTier.LOSSY,
    ExportFidelityTier.TYPES_ONLY,
)


class ExportFidelityRollupEntry(BaseModel):
    """One target's line in the rollup: its tier, preserved share, and guard band."""

    model_config = ConfigDict(extra="forbid")

    target: str = Field(description="The resolved target format key (e.g. ``openapi-3.1``).")
    tier: ExportFidelityTier = Field(description="The target's fidelity tier badge.")
    preserved_percent: int = Field(
        description="Share of source constructs carried faithfully to this target, 0–100."
    )
    total: int = Field(description="Source constructs the prediction considered.")
    dropped: int = Field(description="Constructs dropped entirely for this target.")
    approximated: int = Field(description="Constructs represented imperfectly for this target.")
    guard: str = Field(
        description="The target's transcode-guard verdict (MFX-3.3): ``clean`` / ``lossy`` / "
        "``near-empty`` / ``severe``."
    )
    requires_confirmation: bool = Field(
        description="True when the target's guard needs ``confirm`` before a real export runs."
    )


class ExportFidelityRollup(BaseModel):
    """The merged fidelity summary across every target of a multi-target export."""

    model_config = ConfigDict(extra="forbid")

    target_count: int = Field(description="Number of targets the job covered.")
    tier: ExportFidelityTier = Field(
        description="The worst tier across all targets (lossless < lossy < types-only)."
    )
    min_preserved_percent: int = Field(
        description="The lowest preserved share across targets — the export's fidelity floor."
    )
    mean_preserved_percent: int = Field(
        description="The preserved share averaged across targets, rounded to a whole percent."
    )
    tier_counts: Dict[str, int] = Field(
        description="How many targets landed in each tier, keyed by tier value; every tier is "
        "present (zero when unused)."
    )
    lossy_targets: List[str] = Field(
        default_factory=list,
        description="Targets whose tier is not ``lossless``, in submission order.",
    )
    severe_targets: List[str] = Field(
        default_factory=list,
        description="Targets whose transcode guard requires confirmation (a ``severe`` "
        "conversion that needs ``confirm``), in submission order.",
    )
    targets: List[ExportFidelityRollupEntry] = Field(
        default_factory=list,
        description="One line per target, in submission order.",
    )


def build_fidelity_rollup(
    entries: Sequence[Tuple[str, ExportFidelity, TranscodeGuard]],
) -> ExportFidelityRollup:
    """Fold per-target fidelity envelopes into one merged summary.

    Args:
        entries: ``(target_format, fidelity, guard)`` per target, in submission order. Must be
            non-empty — a multi-target job always has at least one target.

    Returns:
        The rollup: worst tier, preserved-% floor and mean, per-tier counts, the non-lossless
        and severe targets, and one entry per target.

    Raises:
        ValueError: When ``entries`` is empty.
    """
    if not entries:
        raise ValueError("A fidelity rollup needs at least one target.")
    lines = [
        ExportFidelityRollupEntry(
            target=target,
            tier=fidelity.summary.tier,
            preserved_percent=fidelity.summary.preserved_percent,
            total=fidelity.summary.total,
            dropped=fidelity.summary.dropped,
            approximated=fidelity.summary.approximated,
            guard=guard.verdict.value,
            requires_confirmation=guard.requires_confirmation,
        )
        for target, fidelity, guard in entries
    ]
    percents = [line.preserved_percent for line in lines]
    tier_counts = {tier.value: 0 for tier in TIER_ORDER}
    for line in lines:
        tier_counts[line.tier.value] += 1
    return ExportFidelityRollup(
        target_count=len(lines),
        tier=max((line.tier for line in lines), key=TIER_ORDER.index),
        min_preserved_percent=min(percents),
        mean_preserved_percent=round(sum(percents) / len(percents)),
        tier_counts=tier_counts,
        lossy_targets=[line.target for line in lines if line.tier is not ExportFidelityTier.LOSSLESS],
        severe_targets=[line.target for line in lines if line.requires_confirmation],
        targets=lines,
    )
