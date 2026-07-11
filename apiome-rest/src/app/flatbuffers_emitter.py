"""FlatBuffers emitter: canonical model → ``.fbs`` — MFX-16.1.

The inverse of :class:`app.flatbuffers_normalizer.FlatBuffersNormalizer` and an implementation of
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
    OperationKind,
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

__all__ = ["FlatBuffersEmitOptions", "FlatBuffersEmitter", "FlatBuffersFidelityRulePack"]

_CANONICAL_TO_FBS: Dict[str, str] = {
    "bool": "bool",
    "int8": "byte",
    "uint8": "ubyte",
    "i16": "short",
    "uint16": "ushort",
    "i32": "int",
    "uint32": "uint",
    "i64": "long",
    "uint64": "ulong",
    "float": "float",
    "double": "double",
    "string": "string",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})


class FlatBuffersFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for FlatBuffers export."""

    target_label = "FlatBuffers"

    def operation_verdict(self, operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is a data-schema format; "
            f"operation {operation.key!r} has no representation and is dropped",
            target_mapping="operation → dropped",
        )


class FlatBuffersEmitOptions(EmitOptions):
    """Per-target options for :class:`FlatBuffersEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )


class FlatBuffersEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a FlatBuffers ``.fbs`` schema."""

    key = "flatbuffers"
    format = "flatbuffers"
    label = "FlatBuffers"
    description = "Export as a FlatBuffers serialization schema (.fbs)."
    icon = "boxes"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = FlatBuffersEmitOptions

    OUTPUT_MEDIA_TYPE = "text/x-flatbuffers"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=True,
            nullability=False,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return FlatBuffersFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[FlatBuffersEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, FlatBuffersEmitOptions)
            else FlatBuffersEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _FlatBuffersWriter(api, options)
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


class _FlatBuffersWriter:
    def __init__(self, api: CanonicalApi, options: FlatBuffersEmitOptions) -> None:
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
            lines.append(f"// Generated FlatBuffers schema for {title}")
            lines.append("")

        if self._api.identity.namespace:
            lines.append(f"namespace {self._api.identity.namespace};")
            lines.append("")

        includes = self._api.extras.get("fbs_includes") or []
        if isinstance(includes, list):
            for include in includes:
                lines.append(f'include "{include}";')
            if includes:
                lines.append("")

        for type_ in self._api.types:
            rendered = self._render_type(type_)
            if rendered:
                lines.extend(rendered)
                lines.append("")

        root_type = self._api.extras.get("fbs_root_type")
        if isinstance(root_type, str) and root_type:
            lines.append(f"root_type {root_type};")
            lines.append("")

        if self._api.services:
            self.losses.record(
                LossKind.NA,
                "operations-dropped",
                "FlatBuffers export omits RPC/service operations (data-schema only)",
                pointer="services",
            )

        return "\n".join(lines).rstrip() + "\n"

    def _render_type(self, type_: Type) -> List[str]:
        fbs_kind = type_.extras.get("fbs_kind")
        if type_.kind is TypeKind.ENUM or fbs_kind == "enum":
            return self._render_enum(type_)
        if type_.kind is TypeKind.UNION or fbs_kind == "union":
            members = ", ".join(
                member.split(".")[-1] for member in (type_.union_members or [])
            )
            lines = [f"union {type_.name} {{", f"  {members}", "}"]
            self.tracker.record(type_.key, Provenance.SOURCE)
            return lines
        if fbs_kind == "struct":
            return self._render_record(type_, keyword="struct")
        if type_.kind is TypeKind.RECORD:
            keyword = "table" if fbs_kind != "struct" else "struct"
            return self._render_record(type_, keyword=keyword)
        self.losses.record(
            LossKind.NA,
            "unsupported-type",
            f"Type {type_.key!r} has no FlatBuffers representation and is skipped",
            pointer=type_.key,
        )
        return []

    def _render_enum(self, type_: Type) -> List[str]:
        base = type_.extras.get("fbs_base_type")
        header = f"enum {type_.name}" + (f" : {base}" if base else "")
        lines = [f"{header} {{"]
        for value in type_.enum_values:
            suffix = f" = {value.value}" if value.value is not None else ""
            lines.append(f"  {value.name}{suffix},")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_record(self, type_: Type, *, keyword: str) -> List[str]:
        lines = [f"{keyword} {type_.name} {{"]
        ordered = sorted(type_.fields, key=lambda f: f.field_number or 0)
        for field in ordered:
            lines.append(f"  {self._render_field(field)};")
        lines.append("}")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_field(self, field: CanonicalField) -> str:
        type_expr = self._render_type_ref(field.type)
        default = field.extras.get("fbs_default", field.default)
        default_suffix = f" = {default}" if default is not None else ""
        self.tracker.record(field.key, Provenance.SOURCE)
        return f"{field.name}: {type_expr}{default_suffix}"

    def _render_type_ref(self, ref: TypeRef) -> str:
        if ref.item is not None:
            inner = self._render_type_ref(ref.item)
            return f"[{inner}]"
        if ref.name:
            mapped = _CANONICAL_TO_FBS.get(ref.name, ref.name.split(".")[-1])
            return mapped
        return "string"


def _output_path(api: CanonicalApi) -> str:
    base = api.identity.name or "schema"
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", base).strip("_") or "schema"
    return f"{safe}.fbs"
