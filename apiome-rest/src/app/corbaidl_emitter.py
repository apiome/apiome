"""CORBA / OMG IDL emitter: canonical model → ``.idl`` — MFX-24.1.

The inverse of :class:`app.corbaidl_normalizer.CorbaIdlNormalizer` and an implementation of
the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    MessageRole,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .corbaidl_parser import parse_corbaidl
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

__all__ = [
    "CorbaIdlEmitOptions",
    "CorbaIdlEmitter",
    "CorbaIdlFidelityRulePack",
    "validate_corbaidl_document",
]

_CANONICAL_TO_CORBA: Dict[str, str] = {
    "bool": "boolean",
    "i16": "short",
    "i32": "long",
    "i64": "long long",
    "uint16": "unsigned short",
    "uint32": "unsigned long",
    "float": "float",
    "double": "double",
    "string": "string",
    "bytes": "octet",
    "void": "void",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class CorbaIdlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for CORBA IDL export."""

    target_label = "CORBA IDL"

    def operation_verdict(self, operation) -> FidelityVerdict:
        if operation.kind in _EVENT_OPERATION_KINDS:
            return FidelityVerdict.drop(
                message=f"{self.target_label} has no event vocabulary; "
                f"{operation.kind.value} operation {operation.key!r} is dropped",
                target_mapping="event operation → dropped",
            )
        if operation.http_method or operation.http_path:
            return FidelityVerdict.approx(
                message=f"{self.target_label} has no HTTP binding; reframing "
                f"{operation.key!r} as an IDL operation",
                target_mapping="HTTP operation → IDL operation",
            )
        return super().operation_verdict(operation)


class CorbaIdlEmitOptions(EmitOptions):
    """Per-target options for :class:`CorbaIdlEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )


class CorbaIdlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a CORBA / OMG IDL ``.idl`` document."""

    key = "corbaidl"
    format = "corbaidl"
    label = "CORBA IDL"
    description = "Export as a CORBA / OMG IDL definition (.idl)."
    icon = "network"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = CorbaIdlEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

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
        return CorbaIdlFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[CorbaIdlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, CorbaIdlEmitOptions)
            else CorbaIdlEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _CorbaIdlWriter(api, options)
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


class _CorbaIdlWriter:
    def __init__(self, api: CanonicalApi, options: CorbaIdlEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self._typedefs = api.extras.get("corbaidl_typedefs") or {}
        self._interfaces = api.extras.get("corbaidl_interfaces") or []
        self._module = api.extras.get("corbaidl_module") or api.identity.namespace or "Exported"
        self.output_path = _output_path(api)

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported API"
            lines.append(f"// Generated CORBA / OMG IDL for {title}")
            lines.append("")

        body: List[str] = []
        if isinstance(self._typedefs, dict):
            for name, type_expr in sorted(self._typedefs.items()):
                body.append(f"  typedef {type_expr} {name};")
            if self._typedefs:
                body.append("")

        for type_ in sorted(self._api.types, key=lambda item: item.name):
            rendered = self._render_type(type_)
            if rendered:
                body.extend(rendered)
                body.append("")

        if isinstance(self._interfaces, list) and self._interfaces:
            for interface in self._interfaces:
                body.extend(self._render_interface(interface))
                body.append("")
        elif self._api.services:
            for service in self._api.services:
                body.extend(self._render_interface_from_service(service))
                body.append("")

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "CORBA IDL export has no event channel representation",
            )

        lines.append(f"module {self._module} {{")
        lines.extend(body)
        lines.append("};")
        return "\n".join(lines).rstrip() + "\n"

    def _render_type(self, type_: Type) -> List[str]:
        corba_kind = type_.extras.get("corbaidl_kind")
        if type_.kind is TypeKind.ENUM or corba_kind == "enum":
            return self._render_enum(type_)
        if corba_kind == "exception":
            return self._render_struct(type_, keyword="exception")
        if type_.kind is TypeKind.RECORD:
            return self._render_struct(type_, keyword="struct")
        self.losses.record(
            LossKind.NA,
            "unsupported-type",
            f"Type {type_.key!r} ({type_.kind.value}) has no CORBA IDL representation and is skipped",
            pointer=type_.key,
        )
        return []

    def _render_enum(self, type_: Type) -> List[str]:
        values = ", ".join(
            f"{value.name} = {value.value}" if value.value is not None else value.name
            for value in type_.enum_values
        )
        self.tracker.record(type_.key, Provenance.SOURCE)
        return [f"  enum {type_.name} {{ {values} }};"]

    def _render_struct(self, type_: Type, *, keyword: str) -> List[str]:
        lines = [f"  {keyword} {type_.name} {{"]
        for field in sorted(type_.fields, key=lambda item: item.field_number or 0):
            lines.append(f"    {self._render_field(field)};")
        lines.append("  };")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_field(self, field: CanonicalField) -> str:
        type_expr = field.extras.get("corbaidl_type_expr")
        if isinstance(type_expr, str) and type_expr:
            rendered = f"{type_expr} {field.name}"
        else:
            rendered = f"{self._render_type_ref(field.type)} {field.name}"
        self.tracker.record(field.key, Provenance.SOURCE)
        return rendered

    def _render_type_ref(self, ref: TypeRef) -> str:
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            return f"sequence<{inner}>"
        if ref.name:
            mapped = _CANONICAL_TO_CORBA.get(ref.name)
            if mapped:
                return mapped
            target = self._types_by_key.get(ref.name)
            if target is not None:
                return target.name
            return ref.name.split(".")[-1]
        return "string"

    def _render_interface(self, interface: Dict[str, Any]) -> List[str]:
        name = str(interface.get("name", "Interface"))
        lines = [f"  interface {name} {{"]
        for operation in interface.get("operations", []):
            if not isinstance(operation, dict):
                continue
            rendered = self._render_operation(operation)
            if rendered:
                lines.append(f"    {rendered};")
        lines.append("  };")
        self.tracker.record(name, Provenance.SOURCE)
        return lines

    def _render_interface_from_service(self, service: Service) -> List[str]:
        lines = [f"  interface {service.name} {{"]
        for operation in service.operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                continue
            rendered = self._render_operation_from_service(operation)
            if rendered:
                lines.append(f"    {rendered};")
        lines.append("  };")
        return lines

    def _render_operation(self, operation: Dict[str, Any]) -> str:
        return_type = str(operation.get("return_type", "void"))
        name = str(operation.get("name", "operation"))
        params = operation.get("parameters", [])
        param_parts: List[str] = []
        if isinstance(params, list):
            for param in params:
                if not isinstance(param, dict):
                    continue
                direction = str(param.get("direction", "in"))
                param_parts.append(
                    f"{direction} {param.get('type', 'string')} {param.get('name', 'arg')}"
                )
        raises = operation.get("raises", [])
        raises_clause = ""
        if isinstance(raises, list) and raises:
            raises_clause = f" raises ({', '.join(str(item) for item in raises)})"
        return f"{return_type} {name}({', '.join(param_parts)}){raises_clause}"

    def _render_operation_from_service(self, operation) -> str:
        return_type = "void"
        response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE), None)
        if response and response.payload:
            return_type = self._render_type_ref(response.payload)

        params: List[str] = []
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request and request.payload:
            direction = request.extras.get("corbaidl_direction", "in")
            params.append(f"{direction} {self._render_type_ref(request.payload)} arg")
        elif request and request.extras.get("corbaidl_parameters"):
            for param in request.extras["corbaidl_parameters"]:
                params.append(
                    f"{param.get('direction', 'in')} {param.get('type', 'string')} {param.get('name', 'arg')}"
                )

        raises = [
            m for m in operation.messages if m.role is MessageRole.ERROR and m.payload
        ]
        raises_clause = ""
        if raises:
            names = []
            for msg in raises:
                type_name = msg.payload.name.split(".")[-1] if msg.payload and msg.payload.name else msg.name
                if type_name:
                    names.append(type_name)
            if names:
                raises_clause = f" raises ({', '.join(names)})"

        return f"{return_type} {operation.name}({', '.join(params)}){raises_clause}"


def _output_path(api: CanonicalApi) -> str:
    module = api.extras.get("corbaidl_module")
    if isinstance(module, str) and module:
        base = module
    elif api.services:
        base = api.services[0].name
    else:
        base = api.identity.name or "module"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "module"
    return f"{safe}.idl"


def validate_corbaidl_document(content: str) -> None:
    """Validate CORBA / OMG IDL text by re-parsing it."""
    parse_corbaidl(content)
