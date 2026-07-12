"""HL7 v2 emitter: canonical model → HL7 message — MFX-28.1.

The inverse of :class:`app.hl7v2_normalizer.Hl7V2Normalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import ApiParadigm, CanonicalApi, OperationKind
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
from .hl7v2_parser import parse_hl7v2

__all__ = ["Hl7V2EmitOptions", "Hl7V2Emitter", "Hl7V2FidelityRulePack", "validate_hl7v2_message"]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class Hl7V2FidelityRulePack(CapabilityRulePack):
    """Fidelity rules for HL7 v2 export."""

    target_label = "HL7 v2"

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


class Hl7V2EmitOptions(EmitOptions):
    """Per-target options for :class:`Hl7V2Emitter`."""

    include_comments: bool = Field(
        default=False,
        description="HL7 messages do not carry inline comments; kept for SPI parity.",
    )
    segment_terminator: str = Field(
        default="\r",
        description="Segment terminator to use when emitting HL7 v2 messages.",
    )


class Hl7V2Emitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an HL7 v2.x message."""

    key = "hl7v2"
    format = "hl7v2"
    label = "HL7 v2"
    description = "Export as an HL7 v2.x healthcare message (.hl7) inferred from the catalog schema."
    icon = "heart-pulse"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = Hl7V2EmitOptions

    OUTPUT_MEDIA_TYPE = "application/hl7-v2"

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
        return Hl7V2FidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[Hl7V2EmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, Hl7V2EmitOptions)
            else Hl7V2EmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _Hl7V2Writer(api, options)
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


class _Hl7V2Writer:
    def __init__(self, api: CanonicalApi, options: Hl7V2EmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.output_path = _output_path(api)

    def render(self) -> str:
        segments = self._api.extras.get("hl7v2_segments")
        envelope = self._api.extras.get("hl7v2_envelope")
        if not isinstance(segments, list) or not segments:
            raise ValueError("HL7 v2 export requires `hl7v2_segments` extras from import")
        if not isinstance(envelope, dict):
            raise ValueError("HL7 v2 export requires `hl7v2_envelope` extras from import")

        field_sep = str(envelope.get("field_separator") or "|")
        seg_term = self._options.segment_terminator
        lines: List[str] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            seg_id = str(segment.get("id", ""))
            fields = segment.get("fields") or []
            if seg_id == "MSH":
                lines.append(self._render_msh(segment, field_sep=field_sep))
            else:
                values = [
                    str(field.get("value", ""))
                    for field in fields
                    if isinstance(field, dict)
                ]
                lines.append(field_sep.join([seg_id, *values]))

        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "HL7 v2 export is types-only; services and channels are omitted",
            )

        self.tracker.record(self._api.identity.name or "hl7v2", Provenance.SOURCE)
        return seg_term.join(lines) + seg_term

    def _render_msh(self, segment: Dict[str, Any], *, field_sep: str) -> str:
        fields = segment.get("fields") or []
        values = [
            str(field.get("value", ""))
            for field in fields
            if isinstance(field, dict) and field.get("index") not in {1}
        ]
        if not values:
            encoding = "|^~\\&"
            return f"MSH{field_sep}{encoding}"
        encoding = values[0]
        remainder = values[1:]
        return f"MSH{field_sep}{encoding}{field_sep}{field_sep.join(remainder)}"


def _output_path(api: CanonicalApi) -> str:
    message_type = api.extras.get("hl7v2_message_type")
    base = f"hl7-{message_type}" if isinstance(message_type, str) and message_type else "message"
    safe = re.sub(r"[^A-Za-z0-9_-]+", "-", base).strip("-") or "message"
    return f"{safe}.hl7"


def validate_hl7v2_message(content: str) -> None:
    """Validate HL7 v2 message text by re-parsing it."""
    parse_hl7v2(content)
