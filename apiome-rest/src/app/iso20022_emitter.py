"""ISO 20022 emitter: canonical model → XML message — MFX-29.1.

The inverse of :class:`app.iso20022_normalizer.Iso20022Normalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
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
from .iso20022_parser import parse_iso20022

__all__ = [
    "Iso20022EmitOptions",
    "Iso20022Emitter",
    "Iso20022FidelityRulePack",
    "validate_iso20022_document",
]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class Iso20022FidelityRulePack(CapabilityRulePack):
    """Fidelity rules for ISO 20022 export."""

    target_label = "ISO 20022"

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


class Iso20022EmitOptions(EmitOptions):
    """Per-target options for :class:`Iso20022Emitter`."""

    include_xml_declaration: bool = Field(
        default=True,
        description="Emit the XML declaration prologue.",
    )
    include_comments: bool = Field(
        default=True,
        description="Emit a header comment in the generated ISO 20022 XML document.",
    )


class Iso20022Emitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an ISO 20022 XML message."""

    key = "iso20022"
    format = "iso20022"
    label = "ISO 20022"
    description = "Export as an ISO 20022 financial XML message (.xml)."
    icon = "landmark"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = Iso20022EmitOptions

    OUTPUT_MEDIA_TYPE = "application/xml"

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
        return Iso20022FidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[Iso20022EmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, Iso20022EmitOptions)
            else Iso20022EmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _Iso20022Writer(api, options)
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


class _Iso20022Writer:
    def __init__(self, api: CanonicalApi, options: Iso20022EmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._tree = api.extras.get("iso20022_tree")
        self._namespace = api.extras.get("iso20022_namespace")
        self.output_path = _output_path(api)

    def render(self) -> str:
        if not isinstance(self._tree, dict):
            raise ValueError("ISO 20022 export requires `iso20022_tree` extras from import")
        namespace = self._namespace
        if not isinstance(namespace, str) or not namespace:
            message_id = self._api.extras.get("iso20022_message_id")
            if isinstance(message_id, str) and message_id:
                namespace = f"urn:iso:std:iso:20022:tech:xsd:{message_id}"
            else:
                namespace = "urn:iso:std:iso:20022:tech:xsd:Document"

        root = self._build_element(self._tree, namespace=namespace)
        xml = ET.tostring(root, encoding="unicode")
        lines: List[str] = []
        if self._options.include_xml_declaration:
            lines.append('<?xml version="1.0" encoding="UTF-8"?>')
        if self._options.include_comments:
            title = self._api.identity.name or "Exported message"
            lines.append(f"<!-- Generated ISO 20022 XML for {title} -->")
        lines.append(xml)
        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "ISO 20022 export is types-only; services and channels are omitted",
            )
        self.tracker.record(self._api.identity.name or "iso20022", Provenance.SOURCE)
        return "\n".join(lines) + "\n"

    def _build_element(self, node: Dict[str, Any], *, namespace: str) -> ET.Element:
        tag = str(node.get("tag", "Document"))
        if tag == "Document":
            element = ET.Element(f"{{{namespace}}}{tag}")
        else:
            element = ET.Element(tag)
        attributes = node.get("attributes") or []
        if isinstance(attributes, list):
            for item in attributes:
                if isinstance(item, list) and len(item) == 2:
                    element.set(str(item[0]), str(item[1]))
        text = node.get("text")
        children = node.get("children") or []
        if isinstance(children, list) and children:
            for child in children:
                if isinstance(child, dict):
                    element.append(self._build_element(child, namespace=namespace))
        elif text is not None:
            element.text = str(text)
        return element


def _output_path(api: CanonicalApi) -> str:
    message_id = api.extras.get("iso20022_message_id")
    base = f"iso20022-{message_id}" if isinstance(message_id, str) and message_id else "message"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", base).strip("_") or "message"
    return f"{safe}.xml"


def validate_iso20022_document(content: str) -> None:
    """Validate ISO 20022 XML by re-parsing it."""
    parse_iso20022(content)
