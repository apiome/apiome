"""Fidelity rule packs that predict a writer's own losses — shared by the Smithy (MFX-20.2) and TypeSpec
(MFX-15.1) packs.

A target whose losses depend on details the capability profile cannot see (which constraint has a trait,
which parameter a protocol can bind, which name is renamed) predicts them most reliably by asking the
writer itself. :class:`WriterLossRulePack` builds the target's model once with the emitter's writer — pure,
no I/O — files every :class:`~app.emitter.Loss` the writer records under the construct the fidelity
report keys it by (:func:`losses_by_construct`), and turns each into a verdict: an ``NA`` loss is a
``DROP``, an ``INFERRED`` loss an ``APPROX``. A construct with no loss gets the capability verdict, whose
``target_mapping`` names what it became when the writer can say (:meth:`WriterLossRulePack.written_as`).

So the report predicts exactly what the export reports, and the two cannot drift apart.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

from .canonical_model import CanonicalApi, CanonicalField, Channel, Operation, Type, TypeKind
from .emitter import Loss, LossKind
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessReport, LossinessSeverity

__all__ = ["WriterLossRulePack", "losses_by_construct"]


class WriterLossRulePack(CapabilityRulePack):
    """A capability pack whose losses come from building the target with its writer.

    Subclasses implement :meth:`build_writer` and may refine the class-level subject sets that pick a
    verdict's severity, :meth:`root_verdicts` and the per-construct fall-backs.

    Attributes:
        critical_drops: Subjects of ``NA`` losses that leave out a whole construct (or a parameter, body or
            error of an operation) — a ``critical`` ``DROP``; any other ``NA`` loss is a ``warn`` ``DROP``.
        info_drops: Subjects of ``NA`` losses that drop nothing a reader relies on (a field number) — an
            ``info`` ``DROP``.
        cosmetic: Subjects of ``INFERRED`` losses that only change a name — an ``info`` ``APPROX``; any
            other ``INFERRED`` loss is a ``warn`` ``APPROX``.
    """

    critical_drops: FrozenSet[str] = frozenset()
    info_drops: FrozenSet[str] = frozenset()
    cosmetic: FrozenSet[str] = frozenset()

    @abstractmethod
    def build_writer(self, api: CanonicalApi) -> Any:
        """Build the target's model for ``api`` and return the writer.

        The writer exposes ``losses`` (a :class:`~app.emitter.LossTracker`) and ``written_as(key)``
        (what a type or operation became, or ``None``).
        """
        raise NotImplementedError

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Build the model once, file the writer's losses by construct, then walk the model."""
        self._writer = self.build_writer(api)
        self._losses = losses_by_construct(api, self._writer.losses.records())
        return super().evaluate(api)

    def written_as(self, key: str) -> Optional[str]:
        """What the writer made of the type or operation ``key``, or ``None``."""
        return self._writer.written_as(key)

    def loss_verdicts(self, key: str) -> List[FidelityVerdict]:
        """One verdict per distinct writer loss filed under ``key`` (``[]`` when there is none)."""
        verdicts: List[FidelityVerdict] = []
        seen: Set[Tuple[str, str]] = set()
        for loss in self._losses.get(key, []):
            if (loss.subject, loss.detail) in seen:
                continue
            seen.add((loss.subject, loss.detail))
            if loss.kind is LossKind.NA:
                severity = (
                    LossinessSeverity.CRITICAL if loss.subject in self.critical_drops
                    else LossinessSeverity.INFO if loss.subject in self.info_drops
                    else LossinessSeverity.WARN
                )
                verdicts.append(FidelityVerdict.drop(message=loss.detail, severity=severity,
                                                     target_mapping=loss.subject))
            else:
                severity = LossinessSeverity.INFO if loss.subject in self.cosmetic else LossinessSeverity.WARN
                verdicts.append(FidelityVerdict.approx(message=loss.detail, severity=severity,
                                                       target_mapping=loss.subject))
        return verdicts

    def operation_verdicts(self, operation: Operation) -> List[FidelityVerdict]:
        """The writer's losses for the operation and its parameters, else :meth:`operation_verdict`."""
        return self.loss_verdicts(operation.key) or [self.operation_verdict(operation)]

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """``OK`` naming what the operation became, else the capability verdict."""
        written = self.written_as(operation.key)
        if written is None:
            return super().operation_verdict(operation)
        return FidelityVerdict.ok(message=f"operation carried to {self.target_label}", target_mapping=written)

    def channel_verdicts(self, channel: Channel) -> List[FidelityVerdict]:
        """The writer's losses for the channel, else the capability verdict."""
        return self.loss_verdicts(channel.key) or [self.channel_verdict(channel)]

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """The writer's losses for the type (its union members, enum values), else :meth:`type_verdict`."""
        return self.loss_verdicts(type_.key) or [self.type_verdict(type_)]

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """``OK`` naming what the type became, else the capability verdict."""
        written = self.written_as(type_.key)
        if written is None:
            return super().type_verdict(type_)
        return FidelityVerdict.ok(message=f"{type_.kind.value} type carried to {self.target_label}",
                                  target_mapping=written)

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """The writer's losses for the field."""
        return self.loss_verdicts(field.key)


def losses_by_construct(api: CanonicalApi, losses: List[Loss]) -> Dict[str, List[Loss]]:
    """File each writer loss under the construct the fidelity report keys it by.

    A record field keeps its own key; a union member and an enum value belong to their type; a parameter
    and a message belong to their operation. A loss with no construct of the model is filed under the root,
    except the channel loss (pointer ``channels``), which each channel's own ``DROP`` already reports.

    Args:
        api: The model the writer wrote.
        losses: The writer's losses.

    Returns:
        Construct key → its losses, in the order recorded.
    """
    owners: Dict[str, str] = {}
    for type_ in api.types:
        owners[type_.key] = type_.key
        for field in type_.fields:
            owners[field.key] = field.key if type_.kind is TypeKind.RECORD else type_.key
        for value in type_.enum_values:
            owners[value.key] = type_.key
    for channel in api.channels:
        owners[channel.key] = channel.key
    for operation in api.operations():
        owners[operation.key] = operation.key
        for param in operation.parameters:
            owners[param.key] = operation.key
        for message in operation.messages:
            owners.setdefault(message.key, operation.key)
    filed: Dict[str, List[Loss]] = {}
    for loss in losses:
        if loss.pointer == "channels":
            continue
        filed.setdefault(owners.get(loss.pointer or "", ROOT_CONSTRUCT_KEY), []).append(loss)
    return filed
