"""Cap'n Proto emitter: canonical model → ``.capnp`` — MFX-17.1.

The inverse of :class:`app.capnproto_normalizer.CapnpNormalizer` and an implementation of
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
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict

__all__ = ["CapnpEmitOptions", "CapnpEmitter", "CapnpFidelityRulePack"]

_CANONICAL_TO_CAPNP: Dict[str, str] = {
    "bool": "Bool",
    "int8": "Int8",
    "uint8": "UInt8",
    "i16": "Int16",
    "uint16": "UInt16",
    "i32": "Int32",
    "uint32": "UInt32",
    "i64": "Int64",
    "uint64": "UInt64",
    "float": "Float32",
    "double": "Float64",
    "string": "Text",
    "bytes": "Data",
    "void": "Void",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class CapnpFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Cap'n Proto export."""

    target_label = "Cap'n Proto"

    def event_verdict(self, event) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no event/channel representation; event {event.key!r} is dropped",
            target_mapping="event → dropped",
        )


class CapnpEmitOptions(EmitOptions):
    """Per-target options for :class:`CapnpEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )


class CapnpEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Cap'n Proto ``.capnp`` schema."""

    key = "capnproto"
    format = "capnproto"
    label = "Cap'n Proto"
    description = "Export as a Cap'n Proto schema (.capnp)."
    icon = "zap"
    paradigm = ApiParadigm.RPC
    multi_file = False
    options_model = CapnpEmitOptions

    OUTPUT_MEDIA_TYPE = "text/x-capnproto"

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
        return CapnpFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[CapnpEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, CapnpEmitOptions)
            else CapnpEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _CapnpWriter(api, options)
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


class _CapnpWriter:
    def __init__(self, api: CanonicalApi, options: CapnpEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {t.key: t for t in api.types}
        self.output_path = _output_path(api)

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported schema"
            lines.append(f"# Generated Cap'n Proto schema for {title}")
            lines.append("")

        file_id = self._api.extras.get("capnp_file_id")
        if isinstance(file_id, str) and file_id:
            normalized = file_id if file_id.startswith("0x") else f"0x{file_id}"
            lines.append(f"@{normalized};")
            lines.append("")

        imports = self._api.extras.get("capnp_imports") or []
        if isinstance(imports, list):
            for include in imports:
                lines.append(f'@import "{include}";')
            if imports:
                lines.append("")

        for type_ in self._api.types:
            rendered = self._render_type(type_)
            if rendered:
                lines.extend(rendered)
                lines.append("")

        for service in self._api.services:
            lines.extend(self._render_interface(service))
            lines.append("")

        if self._api.channels:
            self.losses.record(
                LossKind.NA,
                "channels-dropped",
                "Cap'n Proto export omits event/channel constructs",
                pointer="channels",
            )

        return "\n".join(lines).rstrip() + "\n"

    def _render_type(self, type_: Type) -> List[str]:
        capnp_kind = type_.extras.get("capnp_kind")
        if type_.kind is TypeKind.ENUM or capnp_kind == "enum":
            return self._render_enum(type_)
        if type_.kind is TypeKind.RECORD or capnp_kind == "struct":
            return self._render_struct(type_)
        self.losses.record(
            LossKind.NA,
            "unsupported-type",
            f"Type {type_.key!r} has no Cap'n Proto representation and is skipped",
            pointer=type_.key,
        )
        return []

    def _render_enum(self, type_: Type) -> List[str]:
        qual = type_.extras.get("capnp_qualified_name")
        if isinstance(qual, str) and "." in qual:
            parent, child = qual.rsplit(".", 1)
            lines = [f"  enum {child} {{"]
            for value in type_.enum_values:
                slot = value.value if value.value is not None else 0
                lines.append(f"    {value.name} @{slot};")
            lines.append("  }")
            self.tracker.record(type_.key, Provenance.SOURCE)
            return lines
        lines = [f"enum {type_.name} {{"]
        for value in type_.enum_values:
            slot = value.value if value.value is not None else 0
            lines.append(f"  {value.name} @{slot};")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_struct(self, type_: Type) -> List[str]:
        qual = type_.extras.get("capnp_qualified_name")
        if isinstance(qual, str) and "." in qual:
            child = qual.rsplit(".", 1)[-1]
            lines = [f"  struct {child} {{"]
            for field in sorted(type_.fields, key=lambda f: f.field_number or 0):
                lines.append(f"    {self._render_field(field)};")
            lines.append("  }")
            self.tracker.record(type_.key, Provenance.SOURCE)
            return lines
        lines = [f"struct {type_.name} {{"]
        for field in sorted(type_.fields, key=lambda f: f.field_number or 0):
            lines.append(f"  {self._render_field(field)};")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_field(self, field: CanonicalField) -> str:
        slot = field.extras.get("capnp_slot", field.field_number if field.field_number is not None else 0)
        type_expr = self._render_type_ref(field.type)
        self.tracker.record(field.key, Provenance.SOURCE)
        return f"{field.name} @{slot} :{type_expr}"

    def _render_type_ref(self, ref: TypeRef) -> str:
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            return f"List({inner})"
        if ref.name:
            mapped = _CANONICAL_TO_CAPNP.get(ref.name.lower(), ref.name.split(".")[-1])
            if mapped[0].islower():
                mapped = mapped[0].upper() + mapped[1:]
            return mapped
        return "Text"

    def _render_interface(self, service: Service) -> List[str]:
        lines = [f"interface {service.name} {{"]
        for operation in service.operations:
            if operation.kind in _EVENT_OPERATION_KINDS:
                continue
            rendered = self._render_method(operation)
            if rendered:
                lines.append(f"  {rendered};")
        lines.append("}")
        self.tracker.record(service.key, Provenance.SOURCE)
        return lines

    def _render_method(self, operation: Operation) -> str:
        slot = operation.extras.get("capnp_slot", 0)
        params = self._render_params(operation)
        results = self._render_results(operation)
        return f"{operation.name} @{slot} ({params}) -> ({results})"

    def _render_params(self, operation: Operation) -> str:
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if not request:
            return ""
        inline = request.extras.get("capnp_parameters")
        if isinstance(inline, list):
            parts = []
            for param in inline:
                parts.append(f"{param['name']} :{self._capnp_type_expr(param['type'])}")
            return ", ".join(parts)
        if request.payload:
            name = request.extras.get("capnp_param_name", "arg")
            return f"{name} :{self._render_type_ref(request.payload)}"
        return ""

    def _render_results(self, operation: Operation) -> str:
        response = next((m for m in operation.messages if m.role is MessageRole.RESPONSE), None)
        if not response:
            return ""
        inline = response.extras.get("capnp_results")
        if isinstance(inline, list):
            parts = []
            for result in inline:
                parts.append(f"{result['name']} :{self._capnp_type_expr(result['type'])}")
            return ", ".join(parts)
        if response.payload:
            name = response.extras.get("capnp_result_name", "result")
            return f"{name} :{self._render_type_ref(response.payload)}"
        return ""

    def _capnp_type_expr(self, type_expr: str) -> str:
        list_match = re.fullmatch(r"List\s*\(\s*([^)]+)\s*\)", type_expr.strip(), re.IGNORECASE)
        if list_match:
            return f"List({self._capnp_type_expr(list_match.group(1))})"
        mapped = _CANONICAL_TO_CAPNP.get(type_expr.lower())
        return mapped or type_expr


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "schema"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "schema"
    return f"{safe}.capnp"
