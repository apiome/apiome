"""Lossiness report model + severities — MFX-2.1 (#3838).

Where the *import* direction has a fidelity analyzer (:mod:`app.fidelity`, MFI-22.3)
that reads an :class:`~app.emitter.EmitResult` after a conversion to OpenAPI, the
*export* direction (MFX — canonical model → any target format / cross-protocol
transcoding) needs "fidelity loss" to be **structured data, not prose**, so the UI,
the CLI, and REST can render it, count it, and gate a download on it (MFX-EPIC-2).

This module defines that structure — and only the structure. The engine that
*populates* it by diffing a :class:`~app.canonical_model.CanonicalApi` against a
target emitter's :class:`~app.emitter.CapabilityProfile` and rule pack is MFX-2.2 /
MFX-2.3; this ticket (MFX-2.1) is the pure Pydantic model it produces.

A :class:`LossinessReport` is an ordered list of :class:`LossItem`, each answering
"what happened to *this* construct when targeting this format?" along two axes:

* **kind** (:class:`LossinessKind`) — the representational outcome:
  ``DROP`` (unrepresentable, removed), ``APPROX`` (represented imperfectly — a
  numeric constraint demoted to a doc comment), ``SYNTH`` (invented to satisfy the
  target — a protobuf field number the source never had), or ``OK`` (carried
  cleanly);

* **severity** (:class:`LossinessSeverity`) — how much a user should care:
  ``info`` / ``warn`` / ``critical``. Kind and severity are orthogonal: a ``DROP``
  of an unused optional description is ``info``, a ``DROP`` of a discriminated union
  is ``critical``.

Each item's ``construct`` is a **stable canonical key** reused verbatim from the
:class:`~app.canonical_model.CanonicalApi` tree (``User.email``,
``acme.PetService.GetPet``, ``GET /pets/{id}``), so a report lines up by identity
with the model it describes — the same keys that drive diff and the virtualized
loss tree in the export UI.

The report is **deterministic**: :class:`LossinessReport` sorts its items into a
fixed canonical order and derives the per-kind / per-severity summary counts from
the items themselves, so the counts can never drift out of sync and two reports
built from the same items serialize to byte-identical JSON. :class:`LossinessReportBuilder`
is the ergonomic way to accumulate items (mirroring :class:`app.emitter.LossTracker`)
before handing them to the model.
"""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "LossinessKind",
    "LossinessSeverity",
    "LossItem",
    "LossinessReport",
    "LossinessReportBuilder",
]


class LossinessKind(str, Enum):
    """The representational outcome of one construct when exported to a target.

    Orthogonal to :class:`LossinessSeverity` (how much it matters): the same kind
    can be trivial or serious depending on the construct.
    """

    DROP = "drop"  # unrepresentable in the target — removed entirely
    APPROX = "approx"  # represented, but imperfectly (e.g. a constraint → a comment)
    SYNTH = "synth"  # invented to satisfy the target (e.g. a protobuf field number)
    OK = "ok"  # carried faithfully — no loss


class LossinessSeverity(str, Enum):
    """How much a user should care about a loss, independent of its kind.

    Drives the user-facing advisory thresholds (MFX-2.4) and how loudly the UI /
    CLI flag the export: a ``critical`` item warrants a dismiss-to-proceed
    acknowledgement, an ``info`` item a quiet footnote.
    """

    INFO = "info"  # cosmetic / metadata; safe to ignore
    WARN = "warn"  # meaningful degradation; review recommended
    CRITICAL = "critical"  # semantic loss; the export may not behave equivalently


# Canonical display/sort rank for each kind and severity. Loss (``DROP``) sorts
# before invention (``SYNTH``) before clean (``OK``), and worse severities sort
# first, so the deterministic item order also reads worst-first within a construct.
_KIND_ORDER: Dict[LossinessKind, int] = {
    LossinessKind.DROP: 0,
    LossinessKind.APPROX: 1,
    LossinessKind.SYNTH: 2,
    LossinessKind.OK: 3,
}
_SEVERITY_ORDER: Dict[LossinessSeverity, int] = {
    LossinessSeverity.CRITICAL: 0,
    LossinessSeverity.WARN: 1,
    LossinessSeverity.INFO: 2,
}


class LossItem(BaseModel):
    """One construct's fate when exported to a target format.

    ``construct`` reuses the source model's stable ``key`` (see
    :mod:`app.canonical_model`) so the item lines up by identity with the model —
    a diff, a lint finding, and a loss item about ``User.email`` all share the key.
    ``target_mapping`` describes *how* the construct landed in the target when it
    was not dropped ("numeric range → schema ``description`` note", "synthesized
    field number ``3``"); it is ``None`` for a clean ``OK`` with nothing to explain
    or a ``DROP`` with no target counterpart.

    The construct key is exposed in JSON as ``construct`` (the UI/CLI/REST contract)
    but named ``construct_key`` on the model to (a) match the canonical model's own
    "key" terminology and (b) avoid shadowing :class:`~pydantic.BaseModel`'s
    deprecated ``construct`` method. ``populate_by_name`` lets callers construct with
    either name; ``serialize_by_alias`` keeps ``construct`` as the emitted key.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )

    construct_key: str = Field(
        alias="construct",
        description="Stable canonical construct key this item concerns, reused "
        "verbatim from the CanonicalApi (e.g. ``User.email``, "
        "``acme.PetService.GetPet``, ``GET /pets/{id}``). Serialized as ``construct``.",
    )
    kind: LossinessKind = Field(
        description="Representational outcome: drop / approx / synth / ok.",
    )
    severity: LossinessSeverity = Field(
        description="How much the loss matters: info / warn / critical.",
    )
    message: str = Field(
        description="Human-readable explanation of what happened to the construct.",
    )
    target_mapping: Optional[str] = Field(
        default=None,
        description="How the construct is represented in the target when not "
        "dropped (e.g. ``constraint → doc comment``); ``None`` when nothing "
        "was emitted (a ``DROP``) or nothing needs explaining (a clean ``OK``).",
    )


class LossinessReport(BaseModel):
    """A structured, per-target export lossiness report (MFX-2.1).

    Holds the ordered :class:`LossItem` list plus summary counts per
    :class:`LossinessKind` and per :class:`LossinessSeverity`. The model is its own
    guarantee of the two acceptance criteria that outlive any producer:

    * **stable ordering** — items are sorted into a fixed canonical order (by
      construct key, then kind, then severity, then message / mapping) on
      construction *and* on re-validation, so however a report is built — via
      :class:`LossinessReportBuilder`, a direct constructor, or ``model_validate``
      of persisted JSON — the same items yield byte-identical JSON;

    * **consistent counts** — ``kind_counts`` and ``severity_counts`` are recomputed
      from ``items`` on every (re)validation, so they can never drift and always
      carry every enum member zero-filled (a stable key set for consumers).

    It is plain Pydantic v2, so it serializes to/from JSON losslessly for the REST
    surfacing (MFX-2.5) and the export-job result envelope.
    """

    model_config = ConfigDict(extra="forbid")

    items: List[LossItem] = Field(
        default_factory=list,
        description="The loss items, sorted into a deterministic canonical order.",
    )
    kind_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of items per LossinessKind, zero-filled for every kind. "
        "Derived from ``items``; any supplied value is recomputed.",
    )
    severity_counts: Dict[str, int] = Field(
        default_factory=dict,
        description="Count of items per LossinessSeverity, zero-filled for every "
        "severity. Derived from ``items``; any supplied value is recomputed.",
    )

    @model_validator(mode="after")
    def _order_and_count(self) -> "LossinessReport":
        """Sort ``items`` deterministically and (re)derive the summary counts.

        Runs on construction and on ``model_validate``, so ordering and counts are
        an invariant of the model rather than a promise the producer must keep. Any
        ``kind_counts`` / ``severity_counts`` supplied by a caller (or present in
        round-tripped JSON) is discarded and rebuilt from ``items``.
        """
        self.items.sort(
            key=lambda item: (
                item.construct_key,
                _KIND_ORDER[item.kind],
                _SEVERITY_ORDER[item.severity],
                item.message,
                item.target_mapping or "",
            )
        )
        kind_counts = {kind.value: 0 for kind in LossinessKind}
        severity_counts = {severity.value: 0 for severity in LossinessSeverity}
        for item in self.items:
            kind_counts[item.kind.value] += 1
            severity_counts[item.severity.value] += 1
        self.kind_counts = kind_counts
        self.severity_counts = severity_counts
        return self

    @property
    def total(self) -> int:
        """Total number of loss items in the report (of any kind)."""
        return len(self.items)

    @property
    def is_lossless(self) -> bool:
        """``True`` when nothing was lost — every item is ``OK`` (or there are none).

        The advisory message (MFX-2.4) is suppressed for a lossless export, so this
        is the gate consumers read rather than re-deriving it from the counts.
        """
        return all(item.kind is LossinessKind.OK for item in self.items)

    @property
    def worst_severity(self) -> Optional[LossinessSeverity]:
        """The most severe severity present among *lossy* (non-``OK``) items.

        ``None`` when the report is lossless. Consumers threshold on this to decide
        how loud the export warning should be (MFX-2.4).
        """
        worst: Optional[LossinessSeverity] = None
        worst_rank = len(_SEVERITY_ORDER)
        for item in self.items:
            if item.kind is LossinessKind.OK:
                continue
            rank = _SEVERITY_ORDER[item.severity]
            if rank < worst_rank:
                worst_rank = rank
                worst = item.severity
        return worst

    def items_of_kind(self, kind: LossinessKind) -> List[LossItem]:
        """Return the items whose :class:`LossinessKind` is ``kind`` (ordered)."""
        return [item for item in self.items if item.kind is kind]

    def items_of_severity(self, severity: LossinessSeverity) -> List[LossItem]:
        """Return the items whose :class:`LossinessSeverity` is ``severity`` (ordered)."""
        return [item for item in self.items if item.severity is severity]


class LossinessReportBuilder:
    """Accumulates :class:`LossItem`s and builds a :class:`LossinessReport`.

    Mirrors :class:`app.emitter.LossTracker`: the fidelity computation engine
    (MFX-2.2) walks a :class:`~app.canonical_model.CanonicalApi`, records one item
    per construct as it goes, and calls :meth:`build` to get the finished report.
    The builder imposes no order of its own — :class:`LossinessReport` sorts on
    construction — so items may be recorded in whatever order the walk visits them.
    """

    def __init__(self) -> None:
        self._items: List[LossItem] = []

    def add(
        self,
        construct: str,
        kind: LossinessKind,
        severity: LossinessSeverity,
        message: str,
        target_mapping: Optional[str] = None,
    ) -> LossItem:
        """Record one loss item and return it.

        Args:
            construct: Stable canonical key of the affected construct.
            kind: The representational outcome (drop / approx / synth / ok).
            severity: How much the loss matters (info / warn / critical).
            message: Human-readable explanation of what happened.
            target_mapping: How the construct landed in the target, when not dropped.

        Returns:
            The recorded :class:`LossItem` (for the caller to reference if needed).
        """
        item = LossItem(
            construct_key=construct,
            kind=kind,
            severity=severity,
            message=message,
            target_mapping=target_mapping,
        )
        self._items.append(item)
        return item

    def ok(
        self,
        construct: str,
        message: str = "carried faithfully to the target",
        target_mapping: Optional[str] = None,
    ) -> LossItem:
        """Record a clean (:attr:`LossinessKind.OK`) item — always ``info`` severity."""
        return self.add(
            construct,
            LossinessKind.OK,
            LossinessSeverity.INFO,
            message,
            target_mapping,
        )

    def build(self) -> LossinessReport:
        """Return a :class:`LossinessReport` over the accumulated items.

        The returned report owns a copy of the items, so the builder may be reused
        or extended afterwards without mutating an already-built report.
        """
        return LossinessReport(items=list(self._items))
