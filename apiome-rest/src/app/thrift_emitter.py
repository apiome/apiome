"""Apache Thrift emitter: canonical model → ``.thrift`` IDL — MFX-14.1.

The inverse of :class:`app.thrift_normalizer.ThriftNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. It walks a :class:`~app.canonical_model.CanonicalApi` and
produces Apache Thrift IDL text:

* ``RECORD`` / ``UNION`` / exception-shaped types → ``struct`` / ``union`` / ``exception``;
* ``ENUM`` → ``enum``;
* ``MAP`` → ``map<K,V>`` fields;
* RPC :class:`~app.canonical_model.Service`\\s → ``service`` blocks with ``throws`` preserved
  from error :class:`~app.canonical_model.Message`\\s when present.

Constructs Thrift cannot carry (HTTP bindings, event channels, validation constraints) are
recorded as :class:`~app.emitter.Loss` entries rather than silently dropped.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    EnumValue,
    Message,
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

__all__ = ["ThriftEmitOptions", "ThriftEmitter", "ThriftFidelityRulePack"]

_THRIFT_BASE_FROM_CANONICAL: Dict[str, str] = {
    "bool": "bool",
    "int8": "byte",
    "i16": "i16",
    "i32": "i32",
    "i64": "i64",
    "double": "double",
    "string": "string",
    "bytes": "binary",
    "uuid": "uuid",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class ThriftFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Thrift export (MFX-14.2)."""

    target_label = "Thrift"

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
                f"{operation.key!r} as an RPC method",
                target_mapping="HTTP operation → RPC method",
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


class ThriftEmitOptions(EmitOptions):
    """Per-target options for :class:`ThriftEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )


class ThriftEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as Apache Thrift IDL."""

    key = "thrift"
    format = "thrift"
    label = "Apache Thrift"
    description = "Export as an Apache Thrift IDL (.thrift) document."
    icon = "network"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = ThriftEmitOptions

    OUTPUT_MEDIA_TYPE = "application/x-thrift"

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
    def fidelity_rule_pack(cls) -> Optional[type[CapabilityRulePack]]:
        return ThriftFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[ThriftEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, ThriftEmitOptions)
            else ThriftEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _ThriftWriter(api, options)
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


class _ThriftWriter:
    """Render canonical RPC model as Thrift IDL."""

    def __init__(self, api: CanonicalApi, options: ThriftEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self.output_path = _output_path(api)

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported API"
            lines.append(f"// Generated Apache Thrift IDL for {title}")
            lines.append("")

        namespaces = self._api.extras.get("thrift_namespaces") or {}
        if isinstance(namespaces, dict):
            for lang, name in sorted(namespaces.items()):
                lines.append(f"namespace {lang} {name}")
        elif self._api.identity.namespace:
            lines.append(f"namespace py {self._api.identity.namespace}")
        if namespaces or self._api.identity.namespace:
            lines.append("")

        includes = self._api.extras.get("thrift_includes") or []
        if isinstance(includes, list):
            for include in includes:
                lines.append(f'include "{include}"')
            if includes:
                lines.append("")

        for type_ in self._api.types:
            if type_.extras.get("thrift_map"):
                continue
            rendered = self._render_type(type_)
            if rendered:
                lines.extend(rendered)
                lines.append("")

        for service in self._api.services:
            lines.extend(self._render_service(service))
            lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def _render_type(self, type_: Type) -> List[str]:
        thrift_kind = type_.extras.get("thrift_kind")
        if type_.kind is TypeKind.ENUM or thrift_kind == "enum":
            return self._render_enum(type_)
        if type_.kind is TypeKind.UNION or thrift_kind == "union":
            return self._render_struct(type_, keyword="union")
        if thrift_kind == "exception":
            return self._render_struct(type_, keyword="exception")
        if type_.kind is TypeKind.RECORD:
            return self._render_struct(type_, keyword="struct")
        self.losses.record(
            LossKind.NA,
            "unsupported-type",
            f"Type {type_.key!r} ({type_.kind.value}) has no Thrift representation and is skipped",
            pointer=type_.key,
        )
        return []

    def _render_enum(self, type_: Type) -> List[str]:
        lines = [f"enum {type_.name} {{"]
        for value in type_.enum_values:
            suffix = f" = {value.value}" if value.value is not None else ""
            lines.append(f"  {value.name}{suffix},")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_struct(self, type_: Type, *, keyword: str) -> List[str]:
        lines = [f"{keyword} {type_.name} {{"]
        for field in sorted(type_.fields, key=lambda f: f.field_number or 0):
            lines.append(f"  {self._render_field(field)},")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_field(self, field: CanonicalField) -> str:
        required = field.extras.get("thrift_required")
        if required is None:
            required = not field.type.nullable
        modifier = "required " if required else "optional "
        number = field.field_number if field.field_number is not None else 1
        type_expr = self._render_type_ref(field.type)
        default = field.extras.get("thrift_default")
        default_suffix = f" = {default}" if default else ""
        self.tracker.record(field.key, Provenance.SOURCE)
        return f"{number}: {modifier}{type_expr} {field.name}{default_suffix}"

    def _render_type_ref(self, ref: TypeRef) -> str:
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            if ref.extras.get("thrift_container") == "set":
                return f"set<{inner}>"
            return f"list<{inner}>"
        if ref.name:
            mapped = _THRIFT_BASE_FROM_CANONICAL.get(ref.name, ref.name.split(".")[-1])
            target = self._types_by_key.get(ref.name)
            if target and target.kind is TypeKind.MAP:
                key = self._render_type_ref(target.key_type or TypeRef(name="string"))
                value = self._render_type_ref(target.value_type or TypeRef(name="string"))
                return f"map<{key}, {value}>"
            return mapped
        return "string"

    def _render_service(self, service: Service) -> List[str]:
        lines = [f"service {service.name} {{"]
        for operation in service.operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                continue
            rendered = self._render_method(operation)
            if rendered:
                lines.append(f"  {rendered},")
        lines.append("}")
        self.tracker.record(service.key, Provenance.SOURCE)
        return lines

    def _render_method(self, operation: Operation) -> str:
        prefix = "oneway " if operation.extras.get("thrift_oneway") else ""
        return_type = "void"
        response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE), None)
        if response and response.payload:
            return_type = self._render_type_ref(response.payload)

        params: List[str] = []
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request and request.payload:
            params.append(f"1: {self._render_type_ref(request.payload)} arg")
        elif request and request.extras.get("thrift_parameters"):
            for param in request.extras["thrift_parameters"]:
                modifier = "required " if param.get("required") else ""
                params.append(
                    f"{param['id']}: {modifier}{param['type']} {param['name']}"
                )

        throws = [
            m for m in operation.messages if m.role is MessageRole.ERROR and m.payload
        ]
        throws_clause = ""
        if throws:
            throw_parts = []
            for msg in throws:
                field_id = msg.extras.get("thrift_throw_id", 1)
                type_name = msg.payload.name.split(".")[-1] if msg.payload and msg.payload.name else "Exception"
                alias = msg.name or type_name
                throw_parts.append(f"{field_id}: {type_name} {alias}")
            throws_clause = f" throws ({', '.join(throw_parts)})"

        self.tracker.record(operation.key, Provenance.SOURCE)
        return f"{prefix}{return_type} {operation.name}({', '.join(params)}){throws_clause}"


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "api"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "api"
    return f"{safe}.thrift"
