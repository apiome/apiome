"""z/OS Connect emitter: canonical model → JSON descriptor — MFX-33.1.

The inverse of :class:`app.zosconnect_normalizer.ZosConnectNormalizer` and an implementation of
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
from .zosconnect_parser import parse_zosconnect

__all__ = [
    "ZosConnectEmitOptions",
    "ZosConnectEmitter",
    "ZosConnectFidelityRulePack",
    "validate_zosconnect_document",
]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class ZosConnectFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for z/OS Connect export."""

    target_label = "z/OS Connect"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )

    def operation_verdict(self, operation) -> FidelityVerdict:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if not operation.http_method or not operation.http_path:
            return FidelityVerdict.drop(
                message=f"{self.target_label} requires HTTP operations; operation {operation.key!r} is dropped",
                target_mapping="non-HTTP operation → dropped",
            )
        return FidelityVerdict.ok(message=f"operation carried to {self.target_label}")


class ZosConnectEmitOptions(EmitOptions):
    """Per-target options for :class:`ZosConnectEmitter`."""

    pretty_print: bool = Field(
        default=True,
        description="Pretty-print the generated z/OS Connect JSON descriptor.",
    )


class ZosConnectEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a z/OS Connect JSON descriptor."""

    key = "zosconnect"
    format = "zosconnect"
    label = "z/OS Connect"
    description = "Export as a z/OS Connect API requester/provider descriptor (.json)."
    icon = "server"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = ZosConnectEmitOptions

    OUTPUT_MEDIA_TYPE = "application/json"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=False,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return ZosConnectFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[ZosConnectEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, ZosConnectEmitOptions)
            else ZosConnectEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _ZosConnectWriter(api, options)
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


class _ZosConnectWriter:
    def __init__(self, api: CanonicalApi, options: ZosConnectEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._descriptor = api.extras.get("zosconnect_descriptor")
        self._api_block = api.extras.get("zosconnect_api")
        self._language = api.extras.get("zosconnect_language")
        self._operations = api.extras.get("zosconnect_operations")
        self._kind = api.extras.get("zosconnect_kind", "requester")
        self.output_path = _output_path(api)

    def render(self) -> str:
        if not isinstance(self._descriptor, dict):
            raise ValueError("z/OS Connect export requires `zosconnect_descriptor` extras from import")
        if not isinstance(self._operations, list) or not self._operations:
            raise ValueError("z/OS Connect export requires `zosconnect_operations` extras from import")

        descriptor_payload = {
            "name": self._descriptor.get("name") or self._api.identity.name or "ZosConnectApi",
            "version": self._descriptor.get("version") or self._api.version or "1.0.0",
        }
        if self._descriptor.get("description") or self._api.description:
            descriptor_payload["description"] = (
                self._descriptor.get("description") or self._api.description
            )

        document: Dict[str, Any] = {}
        if self._kind == "provider":
            document["apiProvider"] = descriptor_payload
        else:
            document["apiRequester"] = descriptor_payload

        api_block = self._api_block if isinstance(self._api_block, dict) else {}
        document["api"] = {
            "title": api_block.get("title") or self._api.title or descriptor_payload["name"],
            "specification": api_block.get("specification") or "openapi-3.0",
            "basePath": api_block.get("basePath")
            or (self._api.servers[0].url if self._api.servers else "/"),
        }

        language = self._language if isinstance(self._language, dict) else {}
        document["language"] = {
            "type": language.get("type") or "cobol",
            "codepage": language.get("codepage") or "IBM-1047",
        }

        operations: List[Dict[str, Any]] = []
        for item in self._operations:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            path_parameters = payload.get("pathParameters")
            if isinstance(path_parameters, list):
                payload["pathParameters"] = [
                    param for param in path_parameters if isinstance(param, dict)
                ]
            operations.append(payload)
        document["operations"] = operations

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "z/OS Connect export has no event/channel representation; channels are omitted",
            )

        self.tracker.record(self._api.identity.name or "zosconnect", Provenance.SOURCE)
        if self._options.pretty_print:
            return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        return json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\n"


def _output_path(api: CanonicalApi) -> str:
    descriptor = api.extras.get("zosconnect_descriptor")
    kind = api.extras.get("zosconnect_kind", "requester")
    name = None
    if isinstance(descriptor, dict):
        name = descriptor.get("name")
    base = str(name) if isinstance(name, str) and name else api.identity.name or "zosconnect"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "zosconnect"
    suffix = "provider" if kind == "provider" else "requester"
    return f"{safe}-{suffix}.json"


def validate_zosconnect_document(content: str) -> None:
    """Validate z/OS Connect JSON by re-parsing it."""
    parse_zosconnect(content)
