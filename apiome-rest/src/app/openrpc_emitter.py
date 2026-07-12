"""OpenRPC emitter: canonical model → OpenRPC JSON — MFX-21.1.

The inverse of :class:`app.openrpc_normalizer.OpenRpcNormalizer` and an implementation
of the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    MessageRole,
    Operation,
    OperationKind,
    Type,
    TypeKind,
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
    SchemaEmitter,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict

__all__ = ["OpenRpcEmitOptions", "OpenRpcEmitter", "OpenRpcFidelityRulePack"]

_REF_PREFIX = "#/components/schemas/"
_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class OpenRpcFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for OpenRPC export."""

    target_label = "OpenRPC"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if operation.http_method or operation.http_path:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no HTTP binding; operation {operation.key!r} is dropped",
                target_mapping="HTTP operation → dropped",
            )
        return FidelityVerdict.ok(message=f"operation carried to {self.target_label}")


class OpenRpcEmitOptions(EmitOptions):
    """Per-target options for :class:`OpenRpcEmitter`."""

    indent: int = Field(default=2, description="JSON indentation width (0 for compact output).")


class OpenRpcEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an OpenRPC JSON document."""

    key = "openrpc"
    format = "openrpc"
    label = "OpenRPC"
    description = "Export as an OpenRPC JSON-RPC 2.0 service description."
    icon = "workflow"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = OpenRpcEmitOptions

    OUTPUT_MEDIA_TYPE = "application/json"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return OpenRpcFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[OpenRpcEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, OpenRpcEmitOptions)
            else OpenRpcEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _OpenRpcWriter(api, options)
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


class _OpenRpcWriter:
    def __init__(self, api: CanonicalApi, options: OpenRpcEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._schema = SchemaEmitter(ref_prefix=_REF_PREFIX)
        self.output_path = _output_path(api)
        self._openrpc_version = str(api.extras.get("openrpc_version") or "1.2.6")

    def render(self) -> str:
        document: Dict[str, Any] = {
            "openrpc": self._openrpc_version,
            "info": self._info(),
            "methods": self._methods(),
        }
        servers = self._servers()
        if servers:
            document["servers"] = servers
        components = self._components()
        if components:
            document["components"] = components
        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "OpenRPC export omits event/channel constructs",
                pointer="channels",
            )
        indent = self._options.indent if self._options.indent > 0 else None
        return json.dumps(document, indent=indent, ensure_ascii=False) + "\n"

    def _info(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {"title": self._api.title or self._api.identity.name}
        if self._api.version:
            info["version"] = self._api.version
        if self._api.description:
            info["description"] = self._api.description
        return info

    def _servers(self) -> List[Dict[str, Any]]:
        servers: List[Dict[str, Any]] = []
        for index, server in enumerate(self._api.servers):
            entry: Dict[str, Any] = {"url": server.url}
            if server.description:
                entry["name"] = server.description
            elif index == 0:
                entry["name"] = "default"
            servers.append(entry)
        return servers

    def _components(self) -> Dict[str, Any]:
        schemas: Dict[str, Any] = {}
        for type_ in sorted(self._api.types, key=lambda t: t.name):
            if type_.kind in {TypeKind.RECORD, TypeKind.ENUM, TypeKind.UNION, TypeKind.MAP, TypeKind.ALIAS}:
                schemas[type_.name] = self._schema.named_schema(type_)
                self.tracker.record(type_.key, Provenance.SOURCE)
        return {"schemas": schemas} if schemas else {}

    def _methods(self) -> List[Dict[str, Any]]:
        methods: List[Dict[str, Any]] = []
        for service in self._api.services:
            for operation in service.operations:
                if operation.kind in _EVENT_OPERATION_KINDS:
                    continue
                if operation.http_method or operation.http_path:
                    continue
                method: Dict[str, Any] = {"name": operation.name}
                summary = operation.extras.get("openrpc_summary")
                if isinstance(summary, str) and summary:
                    method["summary"] = summary
                elif operation.description:
                    method["summary"] = operation.description
                if operation.description and method.get("summary") != operation.description:
                    method["description"] = operation.description
                params = self._params(operation)
                if params:
                    method["params"] = params
                result = self._result(operation)
                if result:
                    method["result"] = result
                methods.append(method)
                self.tracker.record(operation.key, Provenance.SOURCE)
        return methods

    def _params(self, operation: Operation) -> List[Dict[str, Any]]:
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is None:
            return []
        openrpc_params = request.extras.get("openrpc_params")
        if isinstance(openrpc_params, list):
            return [
                {
                    "name": entry["name"],
                    "required": bool(entry.get("required")),
                    "schema": entry.get("schema") or {},
                    **(
                        {"description": entry["description"]}
                        if isinstance(entry.get("description"), str)
                        else {}
                    ),
                }
                for entry in openrpc_params
                if isinstance(entry, dict) and isinstance(entry.get("name"), str)
            ]
        if request.payload is not None:
            return [
                {
                    "name": "params",
                    "required": bool(request.required),
                    "schema": self._schema.type_ref(request.payload),
                }
            ]
        return []

    def _result(self, operation: Operation) -> Optional[Dict[str, Any]]:
        response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE), None)
        if response is None or response.payload is None:
            return None
        result_name = operation.extras.get("openrpc_result_name")
        if not isinstance(result_name, str) or not result_name:
            result_name = response.name or "result"
        return {
            "name": result_name,
            "schema": self._schema.type_ref(response.payload),
        }


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.openrpc.json"
