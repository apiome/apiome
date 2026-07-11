"""API Blueprint emitter: canonical model → API Blueprint 1A markdown.

The inverse of :class:`app.apiblueprint_normalizer.ApiblueprintNormalizer` and an
implementation of the :class:`app.emitter.Emitter` SPI.
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

__all__ = ["ApiblueprintEmitOptions", "ApiblueprintEmitter", "ApiblueprintFidelityRulePack"]

_CANONICAL_TO_APIB: Dict[str, str] = {
    "string": "string",
    "bool": "boolean",
    "boolean": "boolean",
    "double": "number",
    "float": "number",
    "i32": "number",
    "i64": "number",
    "integer": "number",
    "object": "object",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class ApiblueprintFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for API Blueprint export."""

    target_label = "API Blueprint"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )


class ApiblueprintEmitOptions(EmitOptions):
    """Per-target options for :class:`ApiblueprintEmitter`."""

    format_version: str = Field(default="1A", description="API Blueprint `FORMAT` value.")
    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )


class ApiblueprintEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an API Blueprint 1A document."""

    key = "apiblueprint"
    format = "apiblueprint"
    label = "API Blueprint"
    description = "Export as an API Blueprint 1A markdown document."
    icon = "file-text"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = ApiblueprintEmitOptions

    OUTPUT_MEDIA_TYPE = "text/markdown"

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
        return ApiblueprintFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[ApiblueprintEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, ApiblueprintEmitOptions)
            else ApiblueprintEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _ApiblueprintWriter(api, options)
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


class _ApiblueprintWriter:
    def __init__(self, api: CanonicalApi, options: ApiblueprintEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self.output_path = _output_path(api)

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.title or self._api.identity.name or "Exported API"
            lines.append(f"<!-- Generated API Blueprint for {title} -->")
            lines.append("")

        format_version = str(self._api.extras.get("apib_format_version") or self._options.format_version)
        lines.append(f"FORMAT: {format_version}")
        host = self._api.extras.get("apib_host")
        if isinstance(host, str) and host:
            lines.append(f"HOST: {host}")
        elif self._api.servers:
            lines.append(f"HOST: {self._api.servers[0].url}")
        lines.append("")

        title = self._api.title or self._api.identity.name or "Exported API"
        lines.append(f"# {title}")
        lines.append("")
        if self._api.description:
            lines.append(self._api.description)
            lines.append("")

        operations = [op for svc in self._api.services for op in svc.operations]
        grouped: Dict[str, List[Operation]] = {}
        for operation in operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                continue
            path = operation.http_path or "/"
            grouped.setdefault(path, []).append(operation)

        for path in sorted(grouped):
            resource_name = self._resource_name(path)
            lines.append(f"## {resource_name} [{path}]")
            lines.append("")
            path_params = [
                param
                for operation in grouped[path]
                for param in operation.parameters
                if param.location is ParameterLocation.PATH
            ]
            if path_params:
                lines.append("+ Parameters")
                seen: set[str] = set()
                for param in path_params:
                    if param.name in seen:
                        continue
                    seen.add(param.name)
                    type_expr = param.extras.get("apib_type") or self._render_type_ref(param.type)
                    suffix = f" - {param.description}" if param.description else ""
                    lines.append(f"    + {param.name} ({type_expr}){suffix}")
                lines.append("")

            for operation in grouped[path]:
                lines.extend(self._render_operation(operation))
                lines.append("")

        record_types = [t for t in self._api.types if t.kind in {TypeKind.RECORD, TypeKind.ENUM}]
        if record_types:
            lines.append("# Data Structures")
            lines.append("")
            for type_ in record_types:
                lines.extend(self._render_type(type_))
                lines.append("")

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "API Blueprint export omits event/channel constructs",
                pointer="channels",
            )

        return "\n".join(lines).rstrip() + "\n"

    def _resource_name(self, path: str) -> str:
        segments = [segment for segment in path.strip("/").split("/") if segment]
        if not segments:
            return "Root"
        last = segments[-1]
        if last.startswith("{") and last.endswith("}"):
            if len(segments) > 1:
                last = segments[-2]
            else:
                return "Resource"
        return last.replace("-", " ").replace("_", " ").title()

    def _render_operation(self, operation: Operation) -> List[str]:
        method = (operation.http_method or "GET").upper()
        lines = [f"### {operation.name} [{method}]"]
        if operation.description:
            lines.append("")
            lines.append(operation.description)
        lines.append("")

        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request:
            media = (
                request.content_types[0]
                if request.content_types
                else "application/json"
            )
            lines.append(f"+ Request ({media})")
            if request.payload:
                type_name = self._render_attributes_type(request.payload)
                lines.append(f"    + Attributes ({type_name})")
            lines.append("")

        responses = [m for m in operation.messages if m.role is MessageRole.RESPONSE]
        for response in responses:
            status = str(response.extras.get("http_status") or "200")
            media = response.content_types[0] if response.content_types else None
            if media:
                lines.append(f"+ Response {status} ({media})")
            else:
                lines.append(f"+ Response {status}")
            if response.payload:
                array_type = response.extras.get("apib_response_array")
                if isinstance(array_type, str):
                    type_name = f"array[{array_type}]"
                else:
                    type_name = self._render_attributes_type(response.payload)
                lines.append(f"    + Attributes ({type_name})")
            lines.append("")

        self.tracker.record(operation.key, Provenance.SOURCE)
        return lines

    def _render_type(self, type_: Type) -> List[str]:
        kind = "enum" if type_.kind is TypeKind.ENUM else "object"
        lines = [f"## {type_.name} ({kind})"]
        if type_.kind is TypeKind.ENUM:
            for value in type_.enum_values:
                lines.append(f"+ {value.name}")
        else:
            for field in type_.fields:
                lines.append(self._render_field(field))
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_field(self, field: CanonicalField) -> str:
        sample = field.extras.get("apib_sample")
        type_expr = field.extras.get("apib_type") or self._render_type_ref(field.type)
        modifiers = type_expr
        if field.type.nullable is False:
            modifiers = f"{type_expr}, required"
        sample_text = ""
        if isinstance(sample, str) and sample:
            sample_text = f" `{sample}`"
        elif sample is not None:
            sample_text = f" {sample}"
        suffix = f" - {field.description}" if field.description else ""
        self.tracker.record(field.key, Provenance.SOURCE)
        return f"+ {field.name}:{sample_text} ({modifiers}){suffix}"

    def _render_attributes_type(self, ref: TypeRef) -> str:
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            return f"array[{inner}]"
        return self._render_type_ref(ref)

    def _render_type_ref(self, ref: Optional[TypeRef]) -> str:
        if ref is None:
            return "string"
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            return f"array[{inner}]"
        if ref.name:
            mapped = _CANONICAL_TO_APIB.get(ref.name.lower())
            if mapped:
                return mapped
            target = self._types_by_key.get(ref.name)
            if target:
                return target.name
            return ref.name.split(".")[-1]
        return "string"


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or api.title or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.apib"
