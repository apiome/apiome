"""Fidelity report surfacing — tiers, preserved-% and the export envelope — MFX-2.5 (#3842).

MFX-2.2 (:mod:`app.fidelity_engine`) predicts, construct by construct, what an export to a
given target will lose — a :class:`~app.lossiness.LossinessReport`. MFX-2.4
(:mod:`app.fidelity_advisory`) turns that report into the single user-facing "may lose
fidelity" advisory. *This* module is the presentation seam the REST surface (MFX-2.5) needs
on top of both, in two granularities the mockup calls for:

* **cheap, per-target** — a :class:`TargetFidelity`: a one-word ``tier``
  (``lossless`` / ``lossy`` / ``types-only``) plus a ``preserved_percent`` estimate and the
  summary counts, for *every* registered target at once. It drives the export dialog's card
  badges (MFX-6.1) and the version-view pre-summary (MFX-6.5) without emitting an artifact —
  it is derived purely from the prediction engine (no emit).

* **full, per-(source, target)** — an :class:`ExportFidelity`: the target descriptor, its
  tier / preserved-%, the whole :class:`~app.lossiness.LossinessReport`, and the
  :class:`~app.fidelity_advisory.ExportAdvisory`. It backs the dialog's detailed fidelity
  panel via ``POST /export/preview`` and is *the same envelope an export job embeds in its
  result* (MFX-3.1/3.2), so a preview and the eventual export carry byte-identical fidelity.

Everything here is **pure and deterministic** — it computes the prediction report via
:func:`app.fidelity_engine.compute_lossiness_for_emitter`, reads counts off it, and performs
no I/O — so a target badge, a preview, and an export result agree for the same inputs.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi
from .emitter import CapabilityProfile, Emitter, EmitterDescriptor
from .fidelity_advisory import ExportAdvisory, build_export_advisory
from .fidelity_engine import compute_lossiness_for_emitter
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity

__all__ = [
    "ExportFidelityTier",
    "TargetFidelity",
    "ExportFidelity",
    "preserved_percent",
    "classify_tier",
    "build_target_fidelity",
    "build_export_fidelity",
]


class ExportFidelityTier(str, Enum):
    """The one-word fidelity badge shown on a target's export card (MFX-6.1).

    A coarse, at-a-glance summary of a full :class:`~app.lossiness.LossinessReport` — the
    detail lives in the report, this is the headline. Derived from the source's construct
    classes vs the target's capability profile (see :func:`classify_tier`).
    """

    LOSSLESS = "lossless"  # every construct carried faithfully — nothing dropped/approximated
    LOSSY = "lossy"  # some constructs dropped or approximated, but operations survive
    TYPES_ONLY = "types-only"  # a schema-only target that keeps types and drops all operations


class TargetFidelity(BaseModel):
    """The cheap per-target fidelity summary for one (source, target) pairing (MFX-2.5).

    The lightweight half of the surface: a :attr:`tier` badge and a :attr:`preserved_percent`
    estimate plus the per-kind counts, all derived from the prediction report with no emit.
    The export dialog renders one of these per target card (MFX-6.1) and the version view
    aggregates them into its pre-summary (MFX-6.5); the full per-construct detail is fetched
    on demand via ``POST /export/preview`` (:class:`ExportFidelity`).
    """

    model_config = ConfigDict(extra="forbid")

    tier: ExportFidelityTier = Field(
        description="One-word fidelity badge: lossless / lossy / types-only.",
    )
    preserved_percent: int = Field(
        description="Estimated share of constructs carried faithfully to the target, "
        "0–100 (constructs marked OK ÷ total). 100 when the source has no constructs.",
    )
    total: int = Field(
        description="Total source constructs the prediction considered.",
    )
    preserved: int = Field(
        description="Constructs carried faithfully (LossinessKind.OK).",
    )
    dropped: int = Field(
        description="Constructs dropped entirely (LossinessKind.DROP).",
    )
    approximated: int = Field(
        description="Constructs represented imperfectly (LossinessKind.APPROX).",
    )
    synthesized: int = Field(
        description="Constructs invented to satisfy the target (LossinessKind.SYNTH).",
    )


class ExportFidelity(BaseModel):
    """The full fidelity envelope for one (source, target) export (MFX-2.5).

    The heavyweight half of the surface, returned by ``POST /export/preview`` and *embedded
    verbatim in an export job's result* (MFX-3.1/3.2): the target descriptor, the coarse
    :class:`TargetFidelity` summary, the whole :class:`~app.lossiness.LossinessReport`
    (per-construct detail), and the user-facing :class:`~app.fidelity_advisory.ExportAdvisory`.
    Because every field is derived purely from the prediction engine, a preview and the export
    it previews carry identical fidelity.
    """

    model_config = ConfigDict(extra="forbid")

    target: EmitterDescriptor = Field(
        description="The resolved target emitter's descriptor (key/format/label/paradigm/…).",
    )
    summary: TargetFidelity = Field(
        description="The coarse tier / preserved-% summary, matching the /export/targets badge.",
    )
    report: LossinessReport = Field(
        description="The full per-construct lossiness report (DROP/APPROX/SYNTH/OK + severity).",
    )
    advisory: ExportAdvisory = Field(
        description="The user-facing 'may lose fidelity' advisory (MFX-2.4), shown when lossy.",
    )


def preserved_percent(report: LossinessReport) -> int:
    """Estimate the share of constructs carried faithfully, as an integer 0–100.

    Defined as ``round(100 × OK ÷ total)`` over the report's items — the fraction of visited
    constructs that mapped cleanly onto the target. An empty report (a source with no
    constructs) is treated as fully preserved (``100``), since nothing was lost.

    Args:
        report: The prediction report for one export.

    Returns:
        The preserved-fidelity percentage, ``0``–``100``.
    """
    total = report.total
    if total == 0:
        return 100
    preserved = report.kind_counts.get(LossinessKind.OK.value, 0)
    return round(100 * preserved / total)


def classify_tier(
    report: LossinessReport, profile: CapabilityProfile
) -> ExportFidelityTier:
    """Classify an export into a one-word :class:`ExportFidelityTier` badge.

    The tier reflects the *outcome for this specific source*:

    * :attr:`~ExportFidelityTier.LOSSLESS` when the report is lossless (every construct ``OK``)
      — so a types-only source exported to a schema-only target is still ``lossless``;
    * :attr:`~ExportFidelityTier.TYPES_ONLY` for a lossy export to a **schema-only** target —
      one whose capability profile carries neither operations nor events — because such a
      target keeps only the type shapes (an operation-bearing OpenAPI → Avro badges here);
    * :attr:`~ExportFidelityTier.LOSSY` otherwise — some loss, but the target does carry
      operations/events.

    Args:
        report: The prediction report for the export.
        profile: The target emitter's static :class:`~app.emitter.CapabilityProfile`, used to
            distinguish a schema-only target from an operation-bearing one.

    Returns:
        The fidelity tier.
    """
    if report.is_lossless:
        return ExportFidelityTier.LOSSLESS
    schema_only = not profile.operations and not profile.events
    if schema_only:
        return ExportFidelityTier.TYPES_ONLY
    return ExportFidelityTier.LOSSY


def _summarize(report: LossinessReport, profile: CapabilityProfile) -> TargetFidelity:
    """Build the coarse :class:`TargetFidelity` from a report + the target's profile."""
    return TargetFidelity(
        tier=classify_tier(report, profile),
        preserved_percent=preserved_percent(report),
        total=report.total,
        preserved=report.kind_counts.get(LossinessKind.OK.value, 0),
        dropped=report.kind_counts.get(LossinessKind.DROP.value, 0),
        approximated=report.kind_counts.get(LossinessKind.APPROX.value, 0),
        synthesized=report.kind_counts.get(LossinessKind.SYNTH.value, 0),
    )


def build_target_fidelity(
    api: CanonicalApi, emitter: type[Emitter]
) -> TargetFidelity:
    """Compute the cheap per-target :class:`TargetFidelity` for exporting ``api`` to ``emitter``.

    Runs the prediction engine (:func:`app.fidelity_engine.compute_lossiness_for_emitter`,
    honouring the emitter's fidelity rule pack) and reduces the report to a tier + preserved-%
    + counts. No artifact is emitted. Pure and deterministic.

    Args:
        api: The source canonical model to be exported.
        emitter: The target :class:`~app.emitter.Emitter` class.

    Returns:
        The coarse fidelity summary for the target's card badge.
    """
    report = compute_lossiness_for_emitter(api, emitter)
    return _summarize(report, emitter.capability_profile())


def build_export_fidelity(
    api: CanonicalApi,
    emitter: type[Emitter],
    *,
    min_severity: LossinessSeverity = LossinessSeverity.INFO,
) -> ExportFidelity:
    """Compute the full :class:`ExportFidelity` envelope for exporting ``api`` to ``emitter``.

    The single builder shared by the preview endpoint and the export job: it computes the
    prediction report **once** (honouring the emitter's rule pack), the matching advisory
    (MFX-2.4), and the coarse summary, and assembles them with the target descriptor. No
    artifact is emitted. Pure and deterministic — a preview and the export it previews are
    identical for the same inputs.

    Args:
        api: The source canonical model to be exported.
        emitter: The target :class:`~app.emitter.Emitter` class.
        min_severity: The lowest loss severity that raises the advisory (passed through to
            :func:`app.fidelity_advisory.build_export_advisory`); the report and counts are
            unaffected by it.

    Returns:
        The full fidelity envelope (target + summary + report + advisory).
    """
    report = compute_lossiness_for_emitter(api, emitter)
    profile = emitter.capability_profile()
    descriptor = emitter.descriptor()
    advisory = build_export_advisory(
        report, descriptor.label, min_severity=min_severity
    )
    return ExportFidelity(
        target=descriptor,
        summary=_summarize(report, profile),
        report=report,
        advisory=advisory,
    )
