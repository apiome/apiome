"""ISO 8583 emitter: canonical model → field-map JSON — MFX-30.1.

The inverse of :class:`app.iso8583_normalizer.Iso8583Normalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import json
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
from .iso8583_parser import parse_iso8583

__all__ = [
    "Iso8583EmitOptions",
    "Iso8583Emitter",
    "Iso8583FidelityRulePack",
    "validate_iso8583_document",
]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class Iso8583FidelityRulePack(CapabilityRulePack):
    """Fidelity rules for ISO 8583 export."""

    target_label = "ISO 8583"

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


class Iso8583EmitOptions(EmitOptions):
    """Per-target options for :class:`Iso8583Emitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit a `_comment` header in the generated ISO 8583 JSON document.",
    )
    pretty_print: bool = Field(
        default=True,
        description="Pretty-print the generated JSON field map.",
    )


class Iso8583Emitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an ISO 8583 field-map JSON document."""

    key = "iso8583"
    format = "iso8583"
    label = "ISO 8583"
    description = "Export as an ISO 8583 MTI + data-element field map (.json)."
    icon = "credit-card"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = Iso8583EmitOptions

    OUTPUT_MEDIA_TYPE = "application/json"

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
        return Iso8583FidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[Iso8583EmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, Iso8583EmitOptions)
            else Iso8583EmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _Iso8583Writer(api, options)
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


class _Iso8583Writer:
    def __init__(self, api: CanonicalApi, options: Iso8583EmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._elements = api.extras.get("iso8583_data_elements")
        self._mti = api.extras.get("iso8583_mti")
        self._name = api.extras.get("iso8583_name")
        self.output_path = _output_path(api)

    def render(self) -> str:
        if not isinstance(self._elements, list) or not self._elements:
            raise ValueError("ISO 8583 export requires `iso8583_data_elements` extras from import")
        mti = self._mti if isinstance(self._mti, str) and self._mti else "0000"
        document: Dict[str, Any] = {"mti": mti}
        if isinstance(self._name, str) and self._name:
            document["name"] = self._name
        elif self._api.identity.name:
            document["name"] = self._api.identity.name

        data_elements: Dict[str, Dict[str, Any]] = {}
        for item in self._elements:
            if not isinstance(item, dict):
                continue
            number = str(item.get("number", ""))
            if not number:
                continue
            payload: Dict[str, Any] = {
                "name": str(item.get("name", f"Data Element {number}")),
                "type": str(item.get("type", "ans")),
                "value": str(item.get("value", "")),
            }
            if item.get("length") is not None:
                payload["length"] = str(item["length"])
            data_elements[number] = payload
        document["dataElements"] = data_elements

        if self._options.include_comments:
            title = document.get("name") or f"MTI {mti}"
            document = {
                "_comment": f"Generated ISO 8583 field map for {title}",
                **document,
            }

        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "ISO 8583 export is types-only; services and channels are omitted",
            )

        self.tracker.record(self._api.identity.name or "iso8583", Provenance.SOURCE)
        if self._options.pretty_print:
            return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        return json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\n"


def _output_path(api: CanonicalApi) -> str:
    mti = api.extras.get("iso8583_mti")
    base = f"iso8583-{mti}" if isinstance(mti, str) and mti else "message"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", base).strip("_") or "message"
    return f"{safe}.json"


def validate_iso8583_document(content: str) -> None:
    """Validate ISO 8583 JSON by re-parsing it."""
    parse_iso8583(content)
