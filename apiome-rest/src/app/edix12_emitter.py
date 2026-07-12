"""EDI X12 emitter: canonical model → X12 interchange — MFX-24.1.

The inverse of :class:`app.edix12_normalizer.EdiX12Normalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import io
import re
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    OperationKind,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict

__all__ = ["EdiX12EmitOptions", "EdiX12Emitter", "EdiX12FidelityRulePack", "validate_edix12_interchange"]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class EdiX12FidelityRulePack(CapabilityRulePack):
    """Fidelity rules for EDI X12 export."""

    target_label = "EDI X12"

    def operation_verdict(self, operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            f"the {operation.kind.value} operation is dropped",
            target_mapping="operation → dropped (types-only export)",
        )

    def channel_verdict(self, channel) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only — {_TYPES_ONLY_DROP_MESSAGE}; "
            "the event channel is dropped",
            target_mapping="channel → dropped (types-only export)",
        )


class EdiX12EmitOptions(EmitOptions):
    """Per-target options for :class:`EdiX12Emitter`."""

    include_comments: bool = Field(
        default=False,
        description="EDI interchanges do not carry inline comments; kept for SPI parity.",
    )


class EdiX12Emitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an ANSI X12 EDI interchange."""

    key = "edix12"
    format = "edix12"
    label = "EDI X12"
    description = "Export as an ANSI X12 EDI interchange (.edi) inferred from the catalog schema."
    icon = "file-text"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = EdiX12EmitOptions

    OUTPUT_MEDIA_TYPE = "application/edi-x12"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=False,
            nullability=False,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return EdiX12FidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[EdiX12EmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, EdiX12EmitOptions)
            else EdiX12EmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _EdiX12Writer(api, options)
        content = writer.render()
        return EmitResult(
            files=[
                EmittedFile(
                    path=writer.output_path,
                    content=content,
                    media_type=self.OUTPUT_MEDIA_TYPE,
                )
            ],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _EdiX12Writer:
    def __init__(self, api: CanonicalApi, options: EdiX12EmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.output_path = _output_path(api)

    def render(self) -> str:
        transactions = self._api.extras.get("x12_transactions")
        envelope = self._api.extras.get("x12_envelope")
        if not isinstance(transactions, list) or not transactions:
            raise ValueError("EDI X12 export requires `x12_transactions` extras from import")
        if not isinstance(envelope, dict):
            raise ValueError("EDI X12 export requires `x12_envelope` extras from import")

        elem_sep = str(envelope.get("element_separator") or "*")
        seg_term = str(envelope.get("segment_terminator") or "~")
        transaction = transactions[0]
        if not isinstance(transaction, dict):
            raise ValueError("EDI X12 export requires a transaction template")

        lines: List[str] = []
        lines.append(self._render_isa(envelope, elem_sep=elem_sep, seg_term=seg_term))
        lines.append(self._render_gs(envelope, transaction, elem_sep=elem_sep, seg_term=seg_term))
        lines.append(
            self._render_segment(
                "ST",
                [transaction.get("set_id", self._api.extras.get("x12_set_id", "850")), transaction.get("control_number", "0001")],
                elem_sep=elem_sep,
                seg_term=seg_term,
            )
        )
        for segment in transaction.get("segments", []):
            if not isinstance(segment, dict):
                continue
            values = [
                str(element.get("value", ""))
                for element in segment.get("elements", [])
                if isinstance(element, dict)
            ]
            lines.append(self._render_segment(str(segment.get("id", "")), values, elem_sep=elem_sep, seg_term=seg_term))

        segment_count = len(lines) - 2
        lines.append(
            self._render_segment(
                "SE",
                [str(segment_count + 1), transaction.get("control_number", "0001")],
                elem_sep=elem_sep,
                seg_term=seg_term,
            )
        )
        lines.append(
            self._render_segment(
                "GE",
                ["1", envelope.get("group_control_number", "1")],
                elem_sep=elem_sep,
                seg_term=seg_term,
            )
        )
        lines.append(
            self._render_segment(
                "IEA",
                ["1", envelope.get("interchange_control_number", "000000001")],
                elem_sep=elem_sep,
                seg_term=seg_term,
            )
        )

        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "EDI X12 export is types-only; services and channels are omitted",
            )

        self.tracker.record(self._api.identity.name or "edix12", Provenance.SOURCE)
        return "\n".join(lines) + "\n"

    def _render_segment(
        self,
        seg_id: str,
        values: List[str],
        *,
        elem_sep: str,
        seg_term: str,
    ) -> str:
        return seg_id + elem_sep + elem_sep.join(values) + seg_term

    def _render_isa(self, envelope: Dict[str, Any], *, elem_sep: str, seg_term: str) -> str:
        sender = str(envelope.get("sender_id") or "SENDERID").ljust(15)[:15]
        receiver = str(envelope.get("receiver_id") or "RECEIVERID").ljust(15)[:15]
        values = [
            "00",
            " " * 10,
            "00",
            " " * 10,
            "ZZ",
            sender,
            "ZZ",
            receiver,
            "260115",
            "0830",
            "U",
            str(envelope.get("interchange_version") or "00401"),
            str(envelope.get("interchange_control_number") or "000000001"),
            "0",
            "P",
            ">",
        ]
        return self._render_segment("ISA", values, elem_sep=elem_sep, seg_term=seg_term)

    def _render_gs(
        self,
        envelope: Dict[str, Any],
        transaction: Dict[str, Any],
        *,
        elem_sep: str,
        seg_term: str,
    ) -> str:
        values = [
            str(envelope.get("functional_id") or "PO"),
            str(envelope.get("group_sender") or envelope.get("sender_id") or "SENDERID"),
            str(envelope.get("group_receiver") or envelope.get("receiver_id") or "RECEIVERID"),
            "20260115",
            "0830",
            str(envelope.get("group_control_number") or "1"),
            "X",
            str(self._api.extras.get("x12_version") or "004010"),
        ]
        return self._render_segment("GS", values, elem_sep=elem_sep, seg_term=seg_term)


def _output_path(api: CanonicalApi) -> str:
    set_id = api.extras.get("x12_set_id")
    base = f"x12-{set_id}" if isinstance(set_id, str) and set_id else "interchange"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", base).strip("-") or "interchange"
    return f"{safe}.edi"


def validate_edix12_interchange(content: str) -> None:
    """Validate EDI X12 interchange text by parsing it with ``pyx12``."""
    from pyx12.x12file import X12Reader

    reader = X12Reader(io.StringIO(content))
    segments = list(reader)
    if not segments:
        raise ValueError("EDI X12 interchange contains no segments")
    if segments[0].get_seg_id() != "ISA":
        raise ValueError("EDI X12 interchange must begin with `ISA`")
