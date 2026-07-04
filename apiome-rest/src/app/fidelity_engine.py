"""Fidelity computation engine — MFX-2.2 (#3839).

MFX-2.1 (:mod:`app.lossiness`) defines *the shape* of a fidelity report — an ordered
list of :class:`~app.lossiness.LossItem`, each recording what happened to one
construct (``DROP`` / ``APPROX`` / ``SYNTH`` / ``OK``) and how much it matters
(``info`` / ``warn`` / ``critical``). This module is *the engine that produces one*:
given a source :class:`~app.canonical_model.CanonicalApi` and a target emitter's
static :class:`~app.emitter.CapabilityProfile`, it walks the model construct by
construct and predicts each construct's fate **before** any emit runs.

It is the headline of MFX-EPIC-2 (the fidelity / lossiness engine): a cross-format
export honestly tells the user *what it will lose* — a discriminated union a target
can't carry, a numeric constraint demoted to a doc comment, a protobuf field number
the source never had — rather than dropping detail silently.

The engine is a **pure function** (:func:`compute_lossiness`): no network, no
database, no clock. Given the same model and profile it returns an equal report,
which the :class:`~app.lossiness.LossinessReport` then sorts into a deterministic
canonical order — so a preview and the report attached to the eventual export are
byte-identical.

**Capability profile, today; rule pack, tomorrow.** The ticket calls for consulting
the emitter's capability profile *and* its per-target rule pack (MFX-2.3, #3840,
which describes *how* a given construct degrades for a specific format). The rule
pack SPI is not yet built, so this engine derives its verdicts from the capability
profile alone — the six boolean axes (:class:`~app.emitter.CapabilityProfile`) that
already encode exactly the acceptance criteria: operations, events, unions,
nullability, constraints, and field identity. The decision logic lives in one
place (:class:`_FidelityWalker`) so that, when 2.3 lands, a rule pack can refine a
per-construct verdict (the exact ``APPROX`` target mapping, a downgraded severity)
without changing this module's contract.

**What the engine reports, per construct class**

* **Operations** — carried when the target supports them (``operations`` for
  request/response, query, mutation; ``events`` for publish/subscribe), else
  ``DROP`` (critical): the whole operation is unrepresentable (e.g. any
  operation-bearing API exported to a types-only target such as Avro).
* **Channels** — carried when ``events``, else ``DROP`` (critical).
* **Union types** — carried when ``unions``, else ``DROP`` (critical): a
  discriminated union with no faithful target representation.
* **Record fields** — the record itself is carried (``OK``); each field is then
  inspected for three orthogonal losses the target may not survive:

  * a non-null guarantee (``nullable=False``) when the target lacks
    ``nullability`` → ``APPROX`` (warn);
  * validation ``constraints`` when the target lacks ``constraints`` → ``APPROX``
    (warn), the classic "range → doc comment" demotion;
  * field identity — when the target *requires* stable field numbers
    (``field_identity``) but the source field has none → ``SYNTH`` (warn), a
    field number invented to satisfy the target; conversely a source field number
    a non-identity target can't keep → ``DROP`` (info).
* **Scalar types** — carried (``OK``), unless they carry ``constraints`` the
  target can't (``APPROX`` warn).
* **Enum / map / alias types** — carried (``OK``); representable everywhere the
  canonical model can name them.

Clean same-paradigm exports (REST → OpenAPI) therefore report mostly ``OK``, while
a rich source → a lossy target (Protobuf) surfaces its unions, constraints,
nullability, and synthesized field numbers exactly.
"""

from __future__ import annotations

from typing import Optional, Union

from .canonical_model import (
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    Operation,
    OperationKind,
    Type,
    TypeKind,
)
from .emitter import CapabilityProfile, Emitter
from .lossiness import (
    LossinessKind,
    LossinessReport,
    LossinessReportBuilder,
    LossinessSeverity,
)

__all__ = [
    "compute_lossiness",
    "compute_lossiness_for_emitter",
]


# Operation kinds whose representability depends on the target's *event* capability
# rather than its *operation* capability: a publish/subscribe operation is an event
# flow, so it survives only on a target that can carry events (AsyncAPI, Kafka),
# not merely one that can carry request/response operations.
_EVENT_OPERATION_KINDS = frozenset(
    {OperationKind.PUBLISH, OperationKind.SUBSCRIBE}
)


def _has_any_constraint(constraints: Optional[Constraints]) -> bool:
    """Return ``True`` when ``constraints`` carries at least one set validation facet.

    A :class:`~app.canonical_model.Constraints` with every field ``None`` (or a
    ``None`` constraints object) expresses no validation and so is nothing for a
    target to lose. The ``extras`` bag is ignored — it holds format-specific facets
    the canonical constraint vocabulary does not model, whose portability the
    capability profile does not describe.

    Args:
        constraints: The canonical constraints to inspect, or ``None``.

    Returns:
        ``True`` if any first-class constraint facet (minimum, pattern, format, …)
        is set; ``False`` for ``None`` or an all-empty constraints object.
    """
    if constraints is None:
        return False
    facets = constraints.model_dump(exclude={"extras"}, exclude_none=True)
    return bool(facets)


class _FidelityWalker:
    """Walks a :class:`CanonicalApi` and records one loss verdict per construct.

    All decision logic lives here — the single seam a future fidelity rule pack
    (MFX-2.3) refines — so :func:`compute_lossiness` stays a thin, pure entry point.
    The walker records items in model order (services, then channels, then types);
    the :class:`~app.lossiness.LossinessReport` sorts them into canonical order on
    build, so the walk order does not affect the output.
    """

    def __init__(self, profile: CapabilityProfile, target_label: str) -> None:
        """Create a walker for one (source, target) pairing.

        Args:
            profile: The target emitter's static capability profile.
            target_label: Human label for the target, woven into item messages
                (e.g. "OpenAPI 3.1", "Protobuf"); purely cosmetic.
        """
        self._profile = profile
        self._target = target_label
        self._builder = LossinessReportBuilder()

    def walk(self, api: CanonicalApi) -> LossinessReport:
        """Walk ``api`` end to end and return the finished report."""
        for operation in api.operations():
            self._walk_operation(operation)
        for channel in api.channels:
            self._walk_channel(channel)
        for type_ in api.types:
            self._walk_type(type_)
        return self._builder.build()

    # --- operations & channels ---------------------------------------------

    def _walk_operation(self, operation: Operation) -> None:
        """Record an operation as ``OK`` when the target can carry it, else ``DROP``.

        A publish/subscribe operation needs the target's *event* capability; every
        other kind needs its *operation* capability. When the needed capability is
        absent the whole operation — parameters, messages, and all — is
        unrepresentable, so it is a single critical ``DROP`` (an operation-bearing
        API exported to a types-only target loses every operation this way).
        """
        needs_events = operation.kind in _EVENT_OPERATION_KINDS
        supported = self._profile.events if needs_events else self._profile.operations
        if supported:
            self._builder.ok(
                operation.key,
                message=f"operation carried to {self._target}",
            )
            return
        axis = "event operations" if needs_events else "operations"
        self._builder.add(
            operation.key,
            LossinessKind.DROP,
            LossinessSeverity.CRITICAL,
            message=f"{self._target} cannot represent {axis}; the operation is dropped",
        )

    def _walk_channel(self, channel: Channel) -> None:
        """Record an event channel as ``OK`` when ``events``, else critical ``DROP``."""
        if self._profile.events:
            self._builder.ok(
                channel.key, message=f"event channel carried to {self._target}"
            )
            return
        self._builder.add(
            channel.key,
            LossinessKind.DROP,
            LossinessSeverity.CRITICAL,
            message=f"{self._target} cannot represent event channels; the channel is dropped",
        )

    # --- types --------------------------------------------------------------

    def _walk_type(self, type_: Type) -> None:
        """Dispatch a named type to the handler for its :class:`TypeKind`."""
        if type_.kind is TypeKind.UNION:
            self._walk_union(type_)
        elif type_.kind is TypeKind.RECORD:
            self._walk_record(type_)
        elif type_.kind is TypeKind.SCALAR:
            self._walk_scalar(type_)
        else:  # ENUM / MAP / ALIAS — representable wherever the model can name them.
            self._builder.ok(
                type_.key,
                message=f"{type_.kind.value} type carried to {self._target}",
            )

    def _walk_union(self, type_: Type) -> None:
        """Record a union as ``OK`` when ``unions``, else critical ``DROP``.

        A discriminated union / one-of has no faithful representation on a target
        that cannot carry alternatives (the profile's ``unions`` flag is the source
        of truth), so its variant semantics are lost — a critical ``DROP``.
        """
        if self._profile.unions:
            self._builder.ok(
                type_.key,
                message=f"union carried to {self._target}",
                target_mapping="one-of / discriminated alternatives",
            )
            return
        self._builder.add(
            type_.key,
            LossinessKind.DROP,
            LossinessSeverity.CRITICAL,
            message=f"{self._target} cannot represent discriminated unions; "
            "the type's alternative semantics are dropped",
        )

    def _walk_scalar(self, type_: Type) -> None:
        """Record a scalar as ``OK``, or ``APPROX`` when it carries lost constraints."""
        if not self._profile.constraints and _has_any_constraint(type_.constraints):
            self._builder.add(
                type_.key,
                LossinessKind.APPROX,
                LossinessSeverity.WARN,
                message=f"{self._target} cannot enforce validation constraints; "
                "they are demoted to documentation",
                target_mapping="constraints → doc comment",
            )
            return
        self._builder.ok(type_.key, message=f"scalar carried to {self._target}")

    def _walk_record(self, type_: Type) -> None:
        """Record the object itself as ``OK`` and inspect each field for losses.

        The record as a container is always carried; the potential losses are per
        field (nullability, constraints, field identity), each a separate item
        keyed by the field's own canonical key so the report lines up construct by
        construct with the model.
        """
        self._builder.ok(type_.key, message=f"object carried to {self._target}")
        for field in type_.fields:
            self._walk_field(field)

    def _walk_field(self, field: CanonicalField) -> None:
        """Record every representational loss a single record field incurs.

        A field can incur more than one independent loss (a required, constrained
        field on a target lacking both nullability and constraints), so each is a
        distinct item. All share the field's canonical key; the report keeps them
        together and orders them worst-first within the key.
        """
        # Non-null guarantee the target can't express.
        if not self._profile.nullability and field.type.nullable is False:
            self._builder.add(
                field.key,
                LossinessKind.APPROX,
                LossinessSeverity.WARN,
                message=f"{self._target} cannot express a non-null guarantee; "
                "the field becomes optional",
                target_mapping="required/non-null → optional",
            )

        # Validation constraints the target can't enforce.
        if not self._profile.constraints and _has_any_constraint(field.constraints):
            self._builder.add(
                field.key,
                LossinessKind.APPROX,
                LossinessSeverity.WARN,
                message=f"{self._target} cannot enforce validation constraints; "
                "they are demoted to documentation",
                target_mapping="constraints → doc comment",
            )

        # Field identity: synthesized when required-but-absent, dropped when
        # present-but-unrepresentable.
        if self._profile.field_identity and field.field_number is None:
            self._builder.add(
                field.key,
                LossinessKind.SYNTH,
                LossinessSeverity.WARN,
                message=f"{self._target} requires stable field numbers; "
                "one is synthesized for this field",
                target_mapping="synthesized field number",
            )
        elif not self._profile.field_identity and field.field_number is not None:
            self._builder.add(
                field.key,
                LossinessKind.DROP,
                LossinessSeverity.INFO,
                message=f"{self._target} has no stable field numbers; "
                "the source field number is dropped",
            )


def compute_lossiness(
    api: CanonicalApi,
    profile: CapabilityProfile,
    *,
    target_label: str = "the target",
) -> LossinessReport:
    """Compute the fidelity :class:`~app.lossiness.LossinessReport` for one export.

    Walks ``api`` construct by construct and, consulting only the target's static
    ``profile`` (MFX-2.3 rule packs will refine this later), predicts each
    construct's fate — ``OK`` when the target carries it faithfully, ``DROP`` /
    ``APPROX`` / ``SYNTH`` when it cannot. Pure and deterministic: no I/O, and the
    returned report is sorted into a stable canonical order, so a preview and the
    report attached to the eventual emit are byte-identical for the same inputs.

    Args:
        api: The source canonical model to be exported.
        profile: The target emitter's static :class:`~app.emitter.CapabilityProfile`.
        target_label: Human label for the target woven into item messages (e.g.
            "OpenAPI 3.1"); cosmetic only, it does not affect verdicts.

    Returns:
        A :class:`~app.lossiness.LossinessReport` with one or more items per
        top-level construct and one item per lossy field, its summary counts
        derived from those items.
    """
    return _FidelityWalker(profile, target_label).walk(api)


def compute_lossiness_for_emitter(
    api: CanonicalApi,
    emitter: Union[Emitter, type[Emitter]],
) -> LossinessReport:
    """Compute the fidelity report for exporting ``api`` through ``emitter``.

    Convenience wrapper over :func:`compute_lossiness` that reads the target's
    capability profile and a human label straight from the emitter, so callers
    (the export dispatch in MFX-3.2, the dry-run preview in MFX-2.5) need not
    unpack them. Accepts an emitter instance or its class.

    Args:
        api: The source canonical model to be exported.
        emitter: The target :class:`~app.emitter.Emitter` (instance or class).

    Returns:
        The predicted :class:`~app.lossiness.LossinessReport` for the export.
    """
    emitter_cls = emitter if isinstance(emitter, type) else type(emitter)
    profile = emitter_cls.capability_profile()
    label = emitter_cls.label or emitter_cls.key or emitter_cls.format or "the target"
    return compute_lossiness(api, profile, target_label=label)
