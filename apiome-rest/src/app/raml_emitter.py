"""RAML emitter: canonical model → RAML 1.0 — MFX-19.1.

The inverse of :class:`app.raml_normalizer.RamlNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    MessageRole,
    Operation,
    OperationKind,
    ParameterLocation,
    Type,
    TypeKind,
    TypeRef,
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

__all__ = ["RamlEmitOptions", "RamlEmitter", "RamlFidelityRulePack"]

_CANONICAL_TO_RAMl: Dict[str, str] = {
    "string": "string",
    "bool": "boolean",
    "double": "number",
    "float": "number",
    "i32": "integer",
    "i64": "integer",
    "uint32": "integer",
    "uint64": "integer",
    "int8": "integer",
    "uint8": "integer",
    "uint16": "integer",
    "bytes": "file",
    "null": "nil",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class RamlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for RAML export."""

    target_label = "RAML"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )


class RamlEmitOptions(EmitOptions):
    """Per-target options for :class:`RamlEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit a brief generated-file header comment.",
    )


class RamlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a RAML 1.0 document."""

    key = "raml"
    format = "raml"
    label = "RAML"
    description = "Export as a RAML 1.0 REST API definition."
    icon = "book-marked"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = RamlEmitOptions

    OUTPUT_MEDIA_TYPE = "application/raml+yaml"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=False,
            nullability=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return RamlFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[RamlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, RamlEmitOptions)
            else RamlEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _RamlWriter(api, options)
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


class _RamlWriter:
    def __init__(self, api: CanonicalApi, options: RamlEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self.output_path = _output_path(api)
        self._raml_version = str(api.extras.get("raml_version") or "1.0")
        self._media_type = str(api.extras.get("raml_media_type") or "application/json")

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported API"
            lines.append(f"# Generated RAML for {title}")
            lines.append("")
        lines.append(f"#%RAML {self._raml_version}")
        lines.append(f"title: {self._api.title or self._api.identity.name}")
        if self._api.version:
            lines.append(f"version: {self._api.version}")
        if self._api.description:
            lines.append(f"description: {_yaml_scalar(self._api.description)}")
        if self._api.servers:
            lines.append(f"baseUri: {self._api.servers[0].url}")
        lines.append(f"mediaType: {self._media_type}")
        lines.append("")

        record_types = [t for t in self._api.types if t.kind in {TypeKind.RECORD, TypeKind.ENUM}]
        if record_types:
            lines.append("types:")
            for type_ in record_types:
                lines.extend(self._render_type(type_, indent=2))
            lines.append("")

        operations = [op for svc in self._api.services for op in svc.operations]
        grouped: Dict[str, List[Operation]] = {}
        for operation in operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                continue
            path = operation.http_path or "/"
            grouped.setdefault(path, []).append(operation)

        for path in sorted(grouped):
            lines.append(f"{path}:")
            for operation in grouped[path]:
                lines.extend(self._render_operation(operation, indent=2))
            lines.append("")

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "RAML export omits event/channel constructs",
                pointer="channels",
            )

        return "\n".join(lines).rstrip() + "\n"

    def _render_type(self, type_: Type, *, indent: int) -> List[str]:
        pad = " " * indent
        lines = [f"{pad}{type_.name}:"]
        if type_.description:
            lines.append(f"{pad}  description: {_yaml_scalar(type_.description)}")
        if type_.kind is TypeKind.ENUM:
            lines.append(f"{pad}  type: string")
            if type_.enum_values:
                values = ", ".join(value.name for value in type_.enum_values)
                lines.append(f"{pad}  enum: [{values}]")
            self.tracker.record(type_.key, Provenance.SOURCE)
            return lines
        lines.append(f"{pad}  type: object")
        if type_.fields:
            lines.append(f"{pad}  properties:")
            for field in type_.fields:
                suffix = "" if field.type.nullable is False else ""
                prop_name = field.name if field.type.nullable is False else f"{field.name}?"
                type_expr = self._render_type_ref(field.type)
                if field.description:
                    lines.append(f"{pad}    {prop_name}:")
                    lines.append(f"{pad}      type: {type_expr}")
                    lines.append(f"{pad}      description: {_yaml_scalar(field.description)}")
                else:
                    lines.append(f"{pad}    {prop_name}: {type_expr}{suffix}")
                self.tracker.record(field.key, Provenance.SOURCE)
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_operation(self, operation: Operation, *, indent: int) -> List[str]:
        pad = " " * indent
        method = (operation.http_method or "get").lower()
        lines = [f"{pad}{method}:"]
        if operation.description:
            lines.append(f"{pad}  description: {_yaml_scalar(operation.description)}")
        uri_params = [p for p in operation.parameters if p.location is ParameterLocation.PATH]
        if uri_params:
            lines.append(f"{pad}  uriParameters:")
            for param in uri_params:
                lines.append(f"{pad}    {param.name}:")
                lines.append(f"{pad}      type: {self._render_type_ref(param.type)}")
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request and request.payload:
            body_type = self._render_type_ref(request.payload)
            lines.append(f"{pad}  body:")
            lines.append(f"{pad}    {self._media_type}:")
            lines.append(f"{pad}      type: {body_type}")
        responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE]
        if responses:
            lines.append(f"{pad}  responses:")
            for response in responses:
                status = str(response.extras.get("http_status") or "200")
                lines.append(f"{pad}    {status}:")
                if response.payload:
                    body_type = self._render_type_ref(response.payload)
                    lines.append(f"{pad}      body:")
                    lines.append(f"{pad}        {self._media_type}:")
                    lines.append(f"{pad}          type: {body_type}")
        self.tracker.record(operation.key, Provenance.SOURCE)
        return lines

    def _render_type_ref(self, ref: Optional[TypeRef]) -> str:
        if ref is None:
            return "string"
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            return f"{inner}[]"
        if ref.name:
            mapped = _CANONICAL_TO_RAMl.get(ref.name.lower())
            if mapped:
                return mapped
            target = self._types_by_key.get(ref.name)
            if target:
                return target.name
            return ref.name.split(".")[-1]
        return "string"


def _yaml_scalar(value: str) -> str:
    if re.search(r"[:\n#'\"]", value):
        return json_escape_yaml(value)
    return value


def json_escape_yaml(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.raml"
