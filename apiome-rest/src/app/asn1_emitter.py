"""ASN.1 emitter: canonical model → ASN.1 module — MFX-27.1.

The inverse of :class:`app.asn1_normalizer.Asn1Normalizer` and an implementation of
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

__all__ = ["Asn1EmitOptions", "Asn1Emitter", "Asn1FidelityRulePack", "validate_asn1_module"]

_CANONICAL_TO_ASN1: Dict[str, str] = {
    "bool": "BOOLEAN",
    "string": "UTF8String",
    "integer": "INTEGER",
    "i32": "INTEGER",
    "i64": "INTEGER",
    "float": "REAL",
    "double": "REAL",
    "bytes": "OCTET STRING",
    "null": "NULL",
}

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


class Asn1FidelityRulePack(CapabilityRulePack):
    """Fidelity rules for ASN.1 export."""

    target_label = "ASN.1"

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


class Asn1EmitOptions(EmitOptions):
    """Per-target options for :class:`Asn1Emitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit brief generated-file header comments.",
    )
    automatic_tags: bool = Field(
        default=True,
        description="Emit `AUTOMATIC TAGS` on the module header.",
    )


class Asn1Emitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as an ASN.1 module."""

    key = "asn1"
    format = "asn1"
    label = "ASN.1"
    description = "Export as an ASN.1 module (.asn1) with SEQUENCE / CHOICE / ENUMERATED types."
    icon = "binary"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = Asn1EmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=True,
            nullability=True,
            field_identity=True,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return Asn1FidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[Asn1EmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, Asn1EmitOptions)
            else Asn1EmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _Asn1Writer(api, options)
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


class _Asn1Writer:
    def __init__(self, api: CanonicalApi, options: Asn1EmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_key = {type_.key: type_ for type_ in api.types}
        self.output_path = _output_path(api)

    def render(self) -> str:
        lines: List[str] = []
        if self._options.include_comments:
            title = self._api.identity.name or "Exported schema"
            lines.append(f"-- Generated ASN.1 module for {title}")
            lines.append("")

        module_name = (
            self._api.extras.get("asn1_module_name")
            if isinstance(self._api.extras.get("asn1_module_name"), str)
            else None
        ) or _sanitize_module_name(self._api.identity.name or "ExportedModule")
        tags = self._api.extras.get("asn1_tags")
        tag_clause = ""
        if self._options.automatic_tags:
            tag_clause = " AUTOMATIC TAGS"
        elif isinstance(tags, str) and tags:
            tag_clause = f" {tags}"

        lines.append(f"{module_name} DEFINITIONS{tag_clause} ::= BEGIN")
        lines.append("")

        for type_ in sorted(self._api.types, key=lambda item: item.name):
            rendered = self._render_type(type_)
            if rendered:
                lines.extend(rendered)
                lines.append("")

        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "ASN.1 export is types-only; services and channels are omitted",
            )

        lines.append("END")
        return "\n".join(lines).rstrip() + "\n"

    def _render_type(self, type_: Type) -> List[str]:
        if type_.kind is TypeKind.RECORD:
            return self._render_sequence(type_)
        if type_.kind is TypeKind.ENUM:
            return self._render_enumerated(type_)
        if type_.kind is TypeKind.UNION:
            return self._render_choice(type_)
        if type_.kind is TypeKind.ALIAS and type_.alias_of is not None:
            element = self._render_type_ref(type_.alias_of)
            return [f"  {type_.name} ::= SEQUENCE OF {element}"]
        if type_.kind is TypeKind.SCALAR:
            asn1_type = _CANONICAL_TO_ASN1.get(type_.scalar or "", "UTF8String")
            return [f"  {type_.name} ::= {asn1_type}"]
        self.losses.record(
            LossKind.NA,
            "type-skipped",
            f"Type {type_.key!r} has no ASN.1 representation and is skipped",
            pointer=type_.key,
        )
        return []

    def _render_sequence(self, type_: Type) -> List[str]:
        lines = [f"  {type_.name} ::= SEQUENCE {{"]
        ordered = sorted(type_.fields, key=lambda field: field.field_number or 0)
        for index, field in enumerate(ordered):
            rendered = self._render_field(field)
            if index < len(ordered) - 1:
                rendered += ","
            lines.append(f"    {rendered}")
        lines.append("  }")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_choice(self, type_: Type) -> List[str]:
        lines = [f"  {type_.name} ::= CHOICE {{"]
        choice_members = type_.extras.get("asn1_choice_members")
        if isinstance(choice_members, list) and choice_members:
            for index, member in enumerate(choice_members):
                if not isinstance(member, dict):
                    continue
                member_name = member.get("name")
                member_type = member.get("type")
                if not isinstance(member_name, str) or not isinstance(member_type, str):
                    continue
                asn1_type = self._render_type_ref(TypeRef(name=member_type))
                suffix = "," if index < len(choice_members) - 1 else ""
                lines.append(f"    {member_name} {asn1_type}{suffix}")
        else:
            members = list(type_.union_members)
            for index, member_key in enumerate(members):
                member_name = member_key.split(".")[-1]
                member_type = self._types_by_key.get(member_key)
                asn1_type = (
                    member_type.name
                    if member_type is not None
                    else _CANONICAL_TO_ASN1.get(member_key, member_name)
                )
                suffix = "," if index < len(members) - 1 else ""
                lines.append(f"    {member_name} {asn1_type}{suffix}")
        lines.append("  }")
        self.tracker.record(type_.key, Provenance.SOURCE)
        return lines

    def _render_enumerated(self, type_: Type) -> List[str]:
        values = ", ".join(
            f"{value.name}({value.value})" if value.value is not None else value.name
            for value in type_.enum_values
        )
        self.tracker.record(type_.key, Provenance.SOURCE)
        return [f"  {type_.name} ::= ENUMERATED {{ {values} }}"]

    def _render_field(self, field: CanonicalField) -> str:
        type_expr = self._render_type_ref(field.type, field=field)
        suffix = ""
        if field.type.nullable:
            suffix += " OPTIONAL"
        if field.default is not None:
            suffix += f" DEFAULT {field.default}"
        self.tracker.record(field.key, Provenance.SOURCE)
        return f"{field.name} {type_expr}{suffix}"

    def _render_type_ref(self, ref: TypeRef, *, field: Optional[CanonicalField] = None) -> str:
        if ref.item is not None:
            inner = self._render_type_ref(ref.item, field=field)
            return f"SEQUENCE OF {inner}"
        if field is not None and field.constraints and field.constraints.format == "date-time":
            return "GeneralizedTime"
        if ref.name:
            mapped = _CANONICAL_TO_ASN1.get(ref.name)
            if mapped:
                return mapped
            type_ = self._types_by_key.get(ref.name)
            if type_ is not None:
                return type_.name
            return ref.name.split(".")[-1]
        return "UTF8String"


def _sanitize_module_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", value)
    if not cleaned:
        return "ExportedModule"
    if cleaned[0].isdigit():
        return f"Module{cleaned}"
    return cleaned


def _output_path(api: CanonicalApi) -> str:
    module_name = api.extras.get("asn1_module_name")
    if isinstance(module_name, str) and module_name:
        base = _sanitize_module_name(module_name)
    else:
        base = _sanitize_module_name(api.identity.name or "schema")
    return f"{base}.asn1"


def validate_asn1_module(content: str) -> None:
    """Validate ASN.1 module text by compiling it with ``asn1tools``."""
    import asn1tools

    asn1tools.compile_string(content)
