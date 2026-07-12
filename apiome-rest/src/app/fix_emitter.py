"""FIX emitter: canonical model → tag=value message — MFX-32.1.

The inverse of :class:`app.fix_normalizer.FixNormalizer` and an implementation of
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
from .fix_parser import parse_fix

__all__ = ["FixEmitOptions", "FixEmitter", "FixFidelityRulePack", "validate_fix_message"]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class FixFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for FIX export."""

    target_label = "FIX"

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


class FixEmitOptions(EmitOptions):
    """Per-target options for :class:`FixEmitter`."""

    delimiter: str = Field(
        default="|",
        description="Field delimiter to emit (`|` for human-readable samples, SOH for wire format).",
    )


class FixEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a FIX tag=value message."""

    key = "fix"
    format = "fix"
    label = "FIX"
    description = "Export as a FIX tag=value trading message (.fix)."
    icon = "trending-up"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = FixEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

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
        return FixFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[FixEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, FixEmitOptions)
            else FixEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _FixWriter(api, options)
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


class _FixWriter:
    def __init__(self, api: CanonicalApi, options: FixEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._fields = api.extras.get("fix_fields")
        stored_delimiter = api.extras.get("fix_delimiter")
        self._delimiter = (
            str(stored_delimiter)
            if isinstance(stored_delimiter, str) and stored_delimiter
            else options.delimiter
        )
        self.output_path = _output_path(api)

    def render(self) -> str:
        if not isinstance(self._fields, list) or not self._fields:
            raise ValueError("FIX export requires `fix_fields` extras from import")

        delimiter = self._options.delimiter or self._delimiter
        tokens: List[str] = []
        for item in self._fields:
            if not isinstance(item, dict):
                continue
            tag = str(item.get("tag", ""))
            if not tag:
                continue
            tokens.append(f"{tag}={item.get('value', '')}")

        if not tokens:
            raise ValueError("FIX export found no tag=value fields in extras")

        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "FIX export is types-only; services and channels are omitted",
            )

        self.tracker.record(self._api.identity.name or "fix", Provenance.SOURCE)
        rendered = delimiter.join(tokens)
        if delimiter == "|" and not rendered.endswith("|"):
            rendered += "|"
        return rendered + "\n"


def _output_path(api: CanonicalApi) -> str:
    msg_type = api.extras.get("fix_msg_type")
    msg_name = api.extras.get("fix_msg_type_name")
    if isinstance(msg_name, str) and msg_name:
        base = msg_name
    elif isinstance(msg_type, str) and msg_type:
        base = f"message-{msg_type}"
    else:
        base = "message"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "message"
    return f"{safe}.fix"


def validate_fix_message(content: str) -> None:
    """Validate FIX message text by re-parsing it."""
    parse_fix(content)
