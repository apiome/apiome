"""Round-trip fidelity measurement — MFX-2.6 (#3843).

The fidelity engine (MFX-2.2, :func:`app.fidelity_engine.compute_lossiness_for_emitter`)
*predicts* what an export loses. This module *measures* it: given the canonical diff
between a source model and the same model after export → re-import through the
matching MFI parser (:func:`app.import_source.canonical_diff`, the MFI-EPIC-3 diff),
it turns every observed difference into an **empirical loss** and corroborates the
predicted report against it in both directions:

* every **predicted DROP** is checked against the diff — it is *corroborated* when
  the dropped construct (or the entity that owns it) was removed or changed by the
  round trip, and an **unobserved drop** when the construct came back untouched;
* every **empirical loss** the report does not explain is an **unpredicted loss**;
* every ``OK`` finding the round trip contradicts is an **over-claim**.

Any of the three is a *divergence* between prediction and measurement, and
:attr:`FidelityMeasurement.diverges` flags it. The matching rules are exactly
:func:`app.roundtrip_matrix.reconcile`'s (which already pairs each difference with the
finding that explains it), so the measurement and the IXH-1.7 matrix verdict never
disagree about which differences are explained; this module adds the reverse check
(prediction → reality) and the empirical loss list.

The module is pure: no I/O, no emit, no re-import — callers run the loop
(:func:`app.export_roundtrip.run_export_roundtrip`) and hand in the diff and report.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .import_source import CanonicalDiff, CanonicalDiffEntry, DiffChangeKind
from .lossiness import LossinessKind, LossinessReport, LossItem
from .roundtrip_matrix import ReconciliationResult, construct_relates_to, reconcile

__all__ = [
    "DropCorroboration",
    "EmpiricalLoss",
    "FidelityDivergence",
    "FidelityDivergenceKind",
    "FidelityMeasurement",
    "empirical_kind",
    "measure_roundtrip_fidelity",
]

#: The lossiness kind an observed change is expressed as. A construct that vanished
#: was dropped; one that appeared was synthesized by the target; one that came back
#: different was approximated.
_EMPIRICAL_KIND: Dict[DiffChangeKind, LossinessKind] = {
    DiffChangeKind.REMOVED: LossinessKind.DROP,
    DiffChangeKind.ADDED: LossinessKind.SYNTH,
    DiffChangeKind.CHANGED: LossinessKind.APPROX,
}

#: Observed changes that can corroborate a predicted DROP: the construct vanished, or
#: the entity that carries it came back without part of itself.
_DROP_EVIDENCE = frozenset({DiffChangeKind.REMOVED, DiffChangeKind.CHANGED})


class FidelityDivergenceKind(str, Enum):
    """How a prediction and the round-trip measurement disagree."""

    #: The round trip lost (or changed, or invented) something the report did not predict.
    UNPREDICTED_LOSS = "unpredicted_loss"
    #: The report predicted a DROP, but the construct came back unchanged.
    UNOBSERVED_DROP = "unobserved_drop"
    #: The report claimed a construct is preserved (``OK``), but it changed or vanished.
    OVERCLAIM = "overclaim"


class EmpiricalLoss(BaseModel):
    """One difference the round trip actually produced, in the lossiness vocabulary."""

    model_config = ConfigDict(extra="forbid")

    entity: str = Field(description="Entity family: root/service/operation/type/channel.")
    key: str = Field(description="The entity's stable canonical key (empty for ``root``).")
    change: DiffChangeKind = Field(description="The observed change: added / removed / changed.")
    kind: LossinessKind = Field(
        description="The change as a loss kind: removed → ``drop``, added → ``synth``, "
        "changed → ``approx``.",
    )
    predicted: bool = Field(description="True when a fidelity finding explains this loss.")
    finding: Optional[LossItem] = Field(
        default=None,
        description="The predicted finding that explains this loss; null when it was not predicted.",
    )


class DropCorroboration(BaseModel):
    """One predicted DROP checked against what the round trip actually did."""

    model_config = ConfigDict(extra="forbid")

    finding: LossItem = Field(description="The predicted ``drop`` finding.")
    corroborated: bool = Field(
        description="True when the round trip removed or changed the dropped construct "
        "(or the entity that owns it).",
    )
    evidence: List[CanonicalDiffEntry] = Field(
        default_factory=list,
        description="The removed/changed differences that corroborate the drop; empty when "
        "the construct came back unchanged.",
    )


class FidelityDivergence(BaseModel):
    """One place where the predicted report and the measurement disagree."""

    model_config = ConfigDict(extra="forbid")

    kind: FidelityDivergenceKind = Field(
        description="unpredicted_loss / unobserved_drop / overclaim.",
    )
    construct: str = Field(description="The canonical construct or entity key concerned.")
    message: str = Field(description="Human-readable explanation of the disagreement.")


class FidelityMeasurement(BaseModel):
    """The empirical loss list and its corroboration of the predicted report (MFX-2.6)."""

    model_config = ConfigDict(extra="forbid")

    empirical_losses: List[EmpiricalLoss] = Field(
        default_factory=list,
        description="Every difference between the source and its re-import, in diff order.",
    )
    drops: List[DropCorroboration] = Field(
        default_factory=list,
        description="Every predicted ``drop`` finding, in report order, with its evidence.",
    )
    divergences: List[FidelityDivergence] = Field(
        default_factory=list,
        description="Every disagreement between prediction and measurement: unpredicted losses "
        "first, then unobserved drops, then over-claims.",
    )
    predicted_drop_count: int = Field(default=0, description="``drop`` findings in the report.")
    corroborated_drop_count: int = Field(
        default=0, description="Predicted drops the round trip confirmed."
    )
    unpredicted_loss_count: int = Field(
        default=0, description="Empirical losses no finding explains."
    )
    diverges: bool = Field(
        default=False,
        description="True when the prediction and the measurement disagree anywhere "
        "(``divergences`` is non-empty).",
    )


def empirical_kind(change: DiffChangeKind) -> LossinessKind:
    """Express an observed canonical change as a lossiness kind.

    Args:
        change: The diff entry's change.

    Returns:
        ``DROP`` for a removal, ``SYNTH`` for an addition, ``APPROX`` for a change.
    """
    return _EMPIRICAL_KIND[change]


def _corroborate_drop(finding: LossItem, diff: CanonicalDiff) -> DropCorroboration:
    """Find the removed/changed differences that confirm one predicted DROP.

    Args:
        finding: A ``drop`` finding from the predicted report.
        diff: The source → re-import canonical diff.

    Returns:
        The finding with its evidence; ``corroborated`` is True when evidence exists.
    """
    evidence = [
        entry
        for entry in diff.entries
        if entry.change in _DROP_EVIDENCE and construct_relates_to(finding.construct_key, entry.key)
    ]
    return DropCorroboration(finding=finding, corroborated=bool(evidence), evidence=evidence)


def _describe_entry(entry: CanonicalDiffEntry) -> str:
    """Render a diff entry as ``type 'User'`` (``the API root`` for the root entity)."""
    return "the API root" if entry.entity == "root" else f"{entry.entity} '{entry.key}'"


def measure_roundtrip_fidelity(
    diff: CanonicalDiff,
    report: LossinessReport,
    *,
    reconciliation: Optional[ReconciliationResult] = None,
) -> FidelityMeasurement:
    """Measure actual loss from a round-trip diff and corroborate the predicted report.

    Args:
        diff: :func:`~app.import_source.canonical_diff` from the source model to its
            re-import (export → re-import through the matching parser).
        report: The predicted :class:`~app.lossiness.LossinessReport` for the same emit.
        reconciliation: The :func:`~app.roundtrip_matrix.reconcile` result for this
            ``diff`` and ``report`` when the caller already computed it; computed here
            otherwise. Passing it keeps the finding paired with each loss identical to
            the caller's verdict.

    Returns:
        The :class:`FidelityMeasurement`: the empirical loss list, every predicted drop
        with its evidence, and every divergence. An empty diff with no predicted drops
        measures clean (no losses, ``diverges`` False).
    """
    result = reconciliation if reconciliation is not None else reconcile(diff, report)
    explained: Dict[CanonicalDiffEntry, LossItem] = {m.entry: m.finding for m in result.matched}

    empirical_losses = [
        EmpiricalLoss(
            entity=entry.entity,
            key=entry.key,
            change=entry.change,
            kind=empirical_kind(entry.change),
            predicted=entry in explained,
            finding=explained.get(entry),
        )
        for entry in diff.entries
    ]
    drops = [
        _corroborate_drop(item, diff) for item in report.items if item.kind is LossinessKind.DROP
    ]

    divergences: List[FidelityDivergence] = [
        FidelityDivergence(
            kind=FidelityDivergenceKind.UNPREDICTED_LOSS,
            construct=entry.key,
            message=(
                f"The round trip {entry.change.value} {_describe_entry(entry)}, "
                "but the fidelity report did not predict it."
            ),
        )
        for entry in result.unexplained
    ]
    divergences.extend(
        FidelityDivergence(
            kind=FidelityDivergenceKind.UNOBSERVED_DROP,
            construct=drop.finding.construct_key,
            message=(
                f"The fidelity report predicted '{drop.finding.construct_key or 'root'}' "
                "would be dropped, but it came back unchanged."
            ),
        )
        for drop in drops
        if not drop.corroborated
    )
    divergences.extend(
        FidelityDivergence(
            kind=FidelityDivergenceKind.OVERCLAIM,
            construct=item.construct_key,
            message=(
                f"The fidelity report said '{item.construct_key or 'root'}' is preserved, "
                "but the round trip removed or changed it."
            ),
        )
        for item in result.overclaims
    )

    return FidelityMeasurement(
        empirical_losses=empirical_losses,
        drops=drops,
        divergences=divergences,
        predicted_drop_count=len(drops),
        corroborated_drop_count=sum(1 for drop in drops if drop.corroborated),
        unpredicted_loss_count=len(result.unexplained),
        diverges=bool(divergences),
    )
