"""Any-to-any transcoding guards — source-paradigm ↔ target-paradigm sanity — MFX-3.3 (#3846).

The fidelity engine (MFX-2.2, :mod:`app.fidelity_engine`) predicts *what* a cross-format
export loses, construct by construct, and the advisory (MFX-2.4, :mod:`app.fidelity_advisory`)
turns that into the "may lose fidelity" copy. Both answer *how much detail is lost*. This
module answers a different, coarser question the export UX asks **before** it commits an
emit: *does this conversion even make sense?*

Some conversions are not merely lossy but **nonsensical or extreme-loss** — an event-only
AsyncAPI exported to gRPC (which has no event vocabulary), or any operation-bearing API
exported to Avro (which is *types-only* and drops every operation). A plain fidelity report
does describe the damage, but the product wants a **pre-flight gate**: classify the
conversion into one of four bands and, for the worst of them, *stop and require an explicit
confirmation* rather than silently handing back a near-empty artifact.

**The four bands** (:class:`TranscodeVerdict`):

* ``clean`` — lossless; nothing to warn about, the guard stays out of the way;
* ``lossy`` — some loss, but the source's operational surface survives; the fidelity
  advisory (MFX-2.4) already covers it, so the guard adds no gate;
* ``near-empty`` — the target is **types-only** (no operations, no events) and the source
  carries operations/events, so *only its schemas export*. The guard **warns** that the
  operational surface will not survive (the "operations → Avro" case) but does not block;
* ``severe`` — the target structurally cannot represent the source's essence (an event API
  to an operation-only target, or the reverse), *or* the export drops a ``critical``
  construct. A severe conversion **requires an explicit confirmation** to proceed.

**Why it keys off the report *and* the paradigms.** Whether the target can host the source's
operations/events is a structural fact of the target's :class:`~app.emitter.CapabilityProfile`
(Avro genuinely has no operations; gRPC genuinely has no channels), and whether the loss is
``critical`` is a fact of the :class:`~app.lossiness.LossinessReport`. The guard reads both:
the *why* it surfaces is the fidelity report the user can already inspect, so the guard never
invents a reason the report does not corroborate.

Everything here is **pure and deterministic** — given a model and a target it computes the
same guard, performs no I/O, and (when handed the report the fidelity envelope already
computed) never re-walks the model — so the guard a ``/preview`` shows and the guard the
eventual export enforces are identical for the same inputs.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import ApiParadigm, CanonicalApi
from .emitter import CapabilityProfile, Emitter
from .fidelity_engine import compute_lossiness_for_emitter
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity

__all__ = [
    "TranscodeVerdict",
    "TranscodeGuard",
    "TranscodeGuardError",
    "classify_transcode",
    "enforce_transcode_guard",
]


class TranscodeVerdict(str, Enum):
    """The band a source → target conversion falls into (MFX-3.3).

    A coarse, at-a-glance classification distinct from the per-construct fidelity report:
    it answers *how sane is this conversion?* rather than *what exactly is lost?*. Ordered
    from safest to worst — ``clean`` needs no attention, ``severe`` needs an explicit
    confirmation before the export runs.
    """

    CLEAN = "clean"  # lossless — the conversion carries everything faithfully
    LOSSY = "lossy"  # some loss, but the operational surface survives (advisory covers it)
    NEAR_EMPTY = "near-empty"  # a types-only target: only schemas export, operations dropped
    SEVERE = "severe"  # essence unrepresentable or a critical loss — requires confirmation


class TranscodeGuard(BaseModel):
    """The pre-flight verdict for one (source, target) conversion (MFX-3.3).

    Pairs the coarse :class:`TranscodeVerdict` band with the structured *why* — the source
    and target paradigms, how many operations/events the target cannot carry, and the
    report's dropped / critical counts — plus ready-to-render :attr:`headline` / :attr:`message`
    copy. The single gate the surfaces read is :attr:`requires_confirmation`: ``True`` only
    for a ``severe`` conversion, so a UI/CLI/REST caller blocks the export until the user
    explicitly confirms, while a ``near-empty`` warning is shown but never blocks.

    Every field is derived purely from the source model, the target's capability profile,
    and the fidelity report, so the guard a preview surfaces and the guard the export enforces
    agree for the same inputs.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: TranscodeVerdict = Field(
        description="The conversion band: clean / lossy / near-empty / severe.",
    )
    requires_confirmation: bool = Field(
        description="Whether the export must be explicitly confirmed before it runs. "
        "``True`` only for a ``severe`` conversion; a ``near-empty`` warning does not block.",
    )
    source_paradigm: ApiParadigm = Field(
        description="The source model's paradigm (rest / rpc / event / graph / data_schema).",
    )
    target_paradigm: ApiParadigm = Field(
        description="The target emitter's primary paradigm.",
    )
    target_format: str = Field(
        description="Human label for the target format woven into the copy (e.g. ``Apache Avro``).",
    )
    preserved_percent: int = Field(
        description="Estimated share of constructs carried faithfully, 0–100 (from the report).",
    )
    dropped_operations: int = Field(
        description="Source operations the target structurally cannot represent (``0`` when it "
        "can carry operations).",
    )
    dropped_events: int = Field(
        description="Source event channels the target structurally cannot represent (``0`` when "
        "it can carry events).",
    )
    dropped_constructs: int = Field(
        description="Total constructs the fidelity report drops entirely (LossinessKind.DROP).",
    )
    critical_constructs: int = Field(
        description="Constructs the report drops/degrades at ``critical`` severity.",
    )
    headline: str = Field(
        description="Short banner heading for the guard.",
    )
    message: str = Field(
        description="The full, ready-to-display guard sentence. Consumers render it verbatim.",
    )
    reasons: List[str] = Field(
        default_factory=list,
        description="The structured *why*: one line per contributing factor, drawn from the "
        "paradigm mismatch and the fidelity report.",
    )


class TranscodeGuardError(Exception):
    """Raised when a conversion needs confirmation the caller did not give (MFX-3.3).

    A typed failure the REST surface maps to **409 Conflict**: the export was refused *not*
    because the request was malformed but because the conversion is ``severe`` and the caller
    has not confirmed it. The offending :class:`TranscodeGuard` travels on the exception so the
    surface can hand the client back the verdict (and its *why*) to render a confirmation
    prompt, after which the caller retries with confirmation.
    """

    #: HTTP status the REST layer returns for a guard block (Conflict — the request is valid
    #: but conflicts with the guard's current requirement for confirmation).
    status_code: int = 409

    def __init__(self, guard: TranscodeGuard) -> None:
        """Carry the blocking :class:`TranscodeGuard` and derive the error message from it."""
        self.guard = guard
        super().__init__(guard.message)


def _target_hosts_operations(profile: CapabilityProfile) -> bool:
    """Whether the target can carry request/response (and RPC/GraphQL) operations."""
    return profile.operations


def _target_hosts_events(profile: CapabilityProfile) -> bool:
    """Whether the target can carry event channels / pub-sub flows."""
    return profile.events


def _is_schema_only(profile: CapabilityProfile) -> bool:
    """Whether the target is a *types-only* format — it carries neither operations nor events.

    Such a target (Avro, JSON Schema) can only ever export the source's type shapes; every
    operation and channel is structurally unrepresentable in it.
    """
    return not profile.operations and not profile.events


def _preserved_percent(report: LossinessReport) -> int:
    """Share of constructs carried faithfully (OK ÷ total), 0–100; 100 for an empty report.

    Mirrors :func:`app.export_fidelity.preserved_percent` so the guard and the fidelity
    summary report the same number; kept local to avoid a module import cycle.
    """
    total = report.total
    if total == 0:
        return 100
    preserved = report.kind_counts.get(LossinessKind.OK.value, 0)
    return round(100 * preserved / total)


def _plural(count: int, noun: str) -> str:
    """Return ``"1 noun"`` / ``"N nouns"`` — a small English pluralizer for the copy."""
    suffix = "" if count == 1 else "s"
    return f"{count} {noun}{suffix}"


def _dropped_surface_phrase(dropped_operations: int, dropped_events: int) -> str:
    """Render the dropped operational surface as a noun phrase for the copy.

    Combines the dropped operation and event counts into a single readable clause
    (``"3 operations"``, ``"2 event channels"``, or ``"3 operations and 2 event channels"``).
    At least one of the two counts is non-zero wherever this is called.
    """
    parts: List[str] = []
    if dropped_operations:
        parts.append(_plural(dropped_operations, "operation"))
    if dropped_events:
        parts.append(_plural(dropped_events, "event channel"))
    return " and ".join(parts)


def classify_transcode(
    api: CanonicalApi,
    emitter: type[Emitter],
    *,
    report: Optional[LossinessReport] = None,
) -> TranscodeGuard:
    """Classify a source → target conversion into a :class:`TranscodeGuard` (MFX-3.3).

    The pre-flight sanity check: given the source model and the target emitter, decide which
    :class:`TranscodeVerdict` band the conversion falls into and assemble the *why* — the
    paradigm mismatch and the fidelity report's dropped / critical counts.

    The classification, in precedence order:

    1. **clean** — the report is lossless (nothing is dropped or approximated);
    2. **near-empty** — the source has operations or events *and* the target is types-only, so
       every operation/channel is dropped and only the schemas export (the "operations → Avro"
       case). Warned, but not blocked;
    3. **severe** — the source has operations/events the target structurally cannot carry but
       the target is *not* types-only (a nonsensical paradigm shift, e.g. event-only AsyncAPI →
       gRPC), **or** the report drops a ``critical`` construct. Requires confirmation;
    4. **lossy** — any remaining loss, on a target that does carry the source's operational
       surface. The fidelity advisory already covers it, so the guard adds no gate.

    The classification is derived purely from ``api``, the emitter's static
    :class:`~app.emitter.CapabilityProfile`, and the fidelity report — no I/O.

    Args:
        api: The source canonical model to be exported.
        emitter: The target :class:`~app.emitter.Emitter` class.
        report: The already-computed fidelity report for this export, when the caller has one
            (the fidelity envelope computes it). When ``None`` it is computed here via
            :func:`app.fidelity_engine.compute_lossiness_for_emitter`; passing the envelope's
            report avoids a second walk and guarantees the guard and the report agree.

    Returns:
        The :class:`TranscodeGuard` for the conversion.
    """
    if report is None:
        report = compute_lossiness_for_emitter(api, emitter)

    profile = emitter.capability_profile()
    descriptor = emitter.descriptor()
    label = descriptor.label

    source_operations = len(api.operations())
    source_events = len(api.channels)
    source_types = len(api.types)

    # What the target structurally cannot carry (independent of any rule-pack reframing —
    # a types-only target genuinely has nowhere to put an operation or a channel).
    dropped_operations = source_operations if not _target_hosts_operations(profile) else 0
    dropped_events = source_events if not _target_hosts_events(profile) else 0
    essence_lost = dropped_operations > 0 or dropped_events > 0
    schema_only = _is_schema_only(profile)

    dropped_constructs = report.kind_counts.get(LossinessKind.DROP.value, 0)
    critical_constructs = report.severity_counts.get(LossinessSeverity.CRITICAL.value, 0)
    preserved = _preserved_percent(report)

    reasons: List[str] = []
    if dropped_operations:
        reasons.append(
            f"{label} cannot represent operations — {_plural(dropped_operations, 'operation')} "
            "will be dropped."
        )
    if dropped_events:
        reasons.append(
            f"{label} cannot represent event channels — {_plural(dropped_events, 'event channel')} "
            "will be dropped."
        )
    if critical_constructs:
        reasons.append(
            f"{_plural(critical_constructs, 'construct')} would be dropped or reinterpreted at "
            "critical severity, so the result may not behave equivalently."
        )

    # --- Band selection (precedence: clean → near-empty → severe → lossy) ------------------
    if report.is_lossless:
        verdict = TranscodeVerdict.CLEAN
        headline = f"Exporting to {label} preserves this API."
        message = (
            f"Exporting to {label} is a clean conversion — every construct maps onto the target, "
            "so no transcoding guard applies."
        )
    elif essence_lost and schema_only and source_types > 0:
        verdict = TranscodeVerdict.NEAR_EMPTY
        headline = f"Only schemas will be exported to {label}."
        surface = _dropped_surface_phrase(dropped_operations, dropped_events)
        message = (
            f"{label} is a types-only format: it can carry this API's "
            f"{_plural(source_types, 'schema')} but not its {surface}. Exporting will produce "
            "schemas only — the operational surface is dropped. Review the fidelity report "
            "before downloading."
        )
    elif essence_lost:
        # The source's essence is unrepresentable, but the target is not merely a types-only
        # reduction — this is a nonsensical paradigm shift (event API → operation-only target,
        # or the reverse).
        verdict = TranscodeVerdict.SEVERE
        headline = f"Converting this {api.paradigm.value} API to {label} loses most of it."
        surface = _dropped_surface_phrase(dropped_operations, dropped_events)
        message = (
            f"{label} cannot represent this API's {surface} — the constructs that define it. "
            "This is a severe conversion that would export little of the source; confirm you "
            "want to proceed before exporting."
        )
    elif critical_constructs > 0:
        # The paradigm is compatible (operations/events survive) but a critical construct — a
        # discriminated union, say — has no faithful target representation.
        verdict = TranscodeVerdict.SEVERE
        headline = f"Exporting to {label} drops critical constructs."
        message = (
            f"Exporting to {label} drops or reinterprets "
            f"{_plural(critical_constructs, 'critical construct')}, so the result may not behave "
            "equivalently to the source. Confirm you want to proceed before exporting."
        )
    else:
        verdict = TranscodeVerdict.LOSSY
        headline = f"Exporting to {label} loses some detail."
        message = (
            f"Exporting to {label} is lossy: some constructs are dropped or approximated, but the "
            "operational surface survives. Review the fidelity report before downloading."
        )

    return TranscodeGuard(
        verdict=verdict,
        requires_confirmation=verdict is TranscodeVerdict.SEVERE,
        source_paradigm=api.paradigm,
        target_paradigm=descriptor.paradigm,
        target_format=label,
        preserved_percent=preserved,
        dropped_operations=dropped_operations,
        dropped_events=dropped_events,
        dropped_constructs=dropped_constructs,
        critical_constructs=critical_constructs,
        headline=headline,
        message=message,
        reasons=reasons,
    )


def enforce_transcode_guard(
    guard: TranscodeGuard, *, confirmed: bool
) -> TranscodeGuard:
    """Gate an export on its transcoding guard, raising when confirmation is missing (MFX-3.3).

    The single enforcement point every emit surface calls before running the emitter: when the
    guard classifies the conversion ``severe`` (:attr:`TranscodeGuard.requires_confirmation`)
    and the caller has not explicitly ``confirmed`` it, the export is refused with a
    :class:`TranscodeGuardError` (→ 409). Otherwise — a clean/lossy/near-empty conversion, or a
    severe one the caller has confirmed — the guard is returned unchanged so the caller can
    attach it to the result.

    Args:
        guard: The conversion's classified :class:`TranscodeGuard`.
        confirmed: Whether the caller has explicitly confirmed a severe conversion. Ignored for
            non-severe verdicts (they never require confirmation).

    Returns:
        ``guard`` unchanged, for the caller to attach to its response.

    Raises:
        TranscodeGuardError: When ``guard`` requires confirmation and ``confirmed`` is ``False``.
    """
    if guard.requires_confirmation and not confirmed:
        raise TranscodeGuardError(guard)
    return guard
