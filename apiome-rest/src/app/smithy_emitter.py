"""Smithy emitter: canonical model → Smithy IDL.

The inverse of :class:`app.smithy_normalizer.SmithyNormalizer` and an implementation
of the :class:`app.emitter.Emitter` SPI.
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
    Service,
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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, _has_any_constraint

__all__ = ["SmithyEmitOptions", "SmithyEmitter", "SmithyFidelityRulePack"]

_CANONICAL_TO_SMITHY: Dict[str, str] = {
    "string": "String",
    "integer": "Integer",
    "float": "Float",
    "double": "Double",
    "boolean": "Boolean",
    "bytes": "Blob",
    "datetime": "Timestamp",
    "object": "Document",
    "number": "BigDecimal",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class SmithyFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Smithy export."""

    target_label = "Smithy"

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if operation.http_method or operation.http_path:
            return FidelityVerdict.approx(
                message=f"{self.target_label} has no HTTP binding; reframing "
                f"{operation.key!r} as an RPC operation",
                target_mapping="HTTP operation → RPC operation",
            )
        return super().operation_verdict(operation)

    def field_verdict(self, field: CanonicalField) -> Optional[FidelityVerdict]:
        if _has_any_constraint(field.constraints):
            return FidelityVerdict.approx(
                message=f"{self.target_label} cannot enforce validation constraints; "
                f"{field.key!r} is approximated without facets",
                target_mapping="constraints → dropped",
            )
        return super().field_verdict(field)


class SmithyEmitOptions(EmitOptions):
    """Per-target options for :class:`SmithyEmitter`."""

    smithy_version: str = Field(default="2.0", description="Smithy `$version` control value.")
    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )


class SmithyEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as Smithy IDL."""

    key = "smithy"
    format = "smithy"
    label = "Smithy"
    description = "Export as a Smithy 2.x IDL model."
    icon = "hammer"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = SmithyEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> Optional[type[CapabilityRulePack]]:
        return SmithyFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[SmithyEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, SmithyEmitOptions)
            else SmithyEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _SmithyWriter(api, options)
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


class _SmithyWriter:
    def __init__(self, api: CanonicalApi, options: SmithyEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self._types_by_name = {t.name: t for t in api.types}
        self.output_path = _output_path(api)

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.title or self._api.identity.name or "Exported API"
            lines.append(f"// Generated Smithy IDL for {title}")
            lines.append("")

        version = self._api.extras.get("smithy_version") or self._options.smithy_version
        lines.append(f'$version: "{version}"')
        lines.append("")

        namespace = self._api.extras.get("smithy_namespace") or self._api.identity.namespace
        if isinstance(namespace, str) and namespace:
            lines.append(f"namespace {namespace}")
            lines.append("")

        rendered_names: set[str] = set()
        for type_ in self._api.types:
            rendered = self._render_type(type_)
            if rendered:
                lines.extend(rendered)
                lines.append("")
                rendered_names.add(type_.name)

        operation_names = self._collect_operation_names()
        for op_name in sorted(operation_names):
            rendered = self._render_operation_by_name(op_name)
            if rendered:
                lines.extend(rendered)
                lines.append("")

        for service in self._api.services:
            lines.extend(self._render_service(service))
            lines.append("")

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "Smithy export omits event/channel constructs",
                pointer="channels",
            )

        return "\n".join(lines).rstrip() + "\n"

    def _collect_operation_names(self) -> set[str]:
        names: set[str] = set()
        for service in self._api.services:
            for operation in service.operations:
                if operation.kind in _EVENT_OPERATION_KINDS:
                    continue
                names.add(operation.name)
        return names

    def _render_type(self, type_: Type) -> List[str]:
        smithy_kind = type_.extras.get("smithy_kind")
        if type_.kind is TypeKind.ENUM or smithy_kind == "enum":
            return self._render_enum(type_)
        if smithy_kind == "list":
            return self._render_list(type_)
        if smithy_kind == "map" or type_.kind is TypeKind.MAP:
            return self._render_map(type_)
        if type_.kind is TypeKind.UNION or smithy_kind == "union":
            return self._render_structure(type_, keyword="union")
        if type_.kind is TypeKind.RECORD or smithy_kind in {"structure", "resource", None}:
            return self._render_structure(type_, keyword="structure")
        self.losses.record(
            LossKind.NA,
            "unsupported-type",
            f"Type {type_.key!r} ({type_.kind.value}) has no Smithy representation and is skipped",
            pointer=type_.key,
        )
        return []

    def _render_enum(self, type_: Type) -> List[str]:
        lines: List[str] = []
        if type_.description:
            lines.append(f"/// {type_.description}")
        lines.append(f"enum {type_.name} {{")
        for value in type_.enum_values:
            lines.append(f"    {value.name}")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_list(self, type_: Type) -> List[str]:
        member = "Document"
        if type_.aliased and type_.aliased.item:
            member = self._render_type_ref(type_.aliased.item)
        lines: List[str] = []
        if type_.description:
            lines.append(f"/// {type_.description}")
        lines.append(f"list {type_.name} {{")
        lines.append(f"    member: {member}")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_map(self, type_: Type) -> List[str]:
        key = self._render_type_ref(type_.key_type or TypeRef(name="string"))
        value = self._render_type_ref(type_.value_type or TypeRef(name="Document"))
        lines: List[str] = []
        if type_.description:
            lines.append(f"/// {type_.description}")
        lines.append(f"map {type_.name} {{")
        lines.append(f"    key: {key}")
        lines.append(f"    value: {value}")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_structure(self, type_: Type, *, keyword: str) -> List[str]:
        lines: List[str] = []
        if type_.description:
            lines.append(f"/// {type_.description}")
        lines.append(f"{keyword} {type_.name} {{")
        for field in type_.fields:
            lines.append(f"    {self._render_field(field)}")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_field(self, field: CanonicalField) -> str:
        traits = field.extras.get("smithy_traits") or []
        required = "required" in traits or not field.type.nullable
        trait_prefix = "@required\n    " if required and "required" not in traits else ""
        type_name = self._render_type_ref(field.type)
        self.tracker.record(field.key, Provenance.SOURCE)
        return f"{trait_prefix}{field.name}: {type_name}"

    def _render_type_ref(self, ref: TypeRef) -> str:
        if ref.item is not None:
            return self._render_type_ref(ref.item)
        if ref.name:
            mapped = _CANONICAL_TO_SMITHY.get(ref.name)
            if mapped:
                return mapped
            target = self._types_by_key.get(ref.name) or self._types_by_name.get(ref.name)
            if target:
                return target.name
            return ref.name.split(".")[-1]
        return "String"

    def _render_operation_by_name(self, name: str) -> List[str]:
        for service in self._api.services:
            for operation in service.operations:
                if operation.name == name:
                    return self._render_operation(operation)
        return []

    def _render_operation(self, operation: Operation) -> List[str]:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return []
        lines: List[str] = []
        if operation.description:
            lines.append(f"/// {operation.description}")
        lines.append(f"operation {operation.name} {{")
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE), None)
        if request and request.payload:
            lines.append(f"    input: {self._render_type_ref(request.payload)}")
        if response and response.payload:
            lines.append(f"    output: {self._render_type_ref(response.payload)}")
        lines.append("}")
        self.tracker.record(operation.key, Provenance.SOURCE)
        return lines

    def _render_service(self, service: Service) -> List[str]:
        lines: List[str] = []
        if service.description:
            lines.append(f"/// {service.description}")
        lines.append(f"service {service.name} {{")
        version = service.extras.get("smithy_version")
        if isinstance(version, str) and version:
            lines.append(f'    version: "{version}"')
        op_names = service.extras.get("smithy_operations")
        if isinstance(op_names, list) and op_names:
            rendered_ops = ", ".join(str(name) for name in op_names)
        else:
            rendered_ops = ", ".join(
                operation.name
                for operation in service.operations
                if operation.kind not in _EVENT_OPERATION_KINDS
            )
        if rendered_ops:
            lines.append(f"    operations: [{rendered_ops}]")
        lines.append("}")
        self.tracker.record(service.key, Provenance.SOURCE)
        return lines


def _output_path(api: CanonicalApi) -> str:
    base = api.services[0].name if api.services else (api.identity.name or "model")
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "model"
    return f"{safe}.smithy"
