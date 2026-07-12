"""JSON Schema emitter: canonical model → JSON Schema document — MFX-34.1.

The inverse of :class:`app.jsonschema_import_source.JsonSchemaImportSource` and an
implementation of the :class:`app.emitter.Emitter` SPI.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Union

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
from .jsonschema_import_source import JSON_SCHEMA_FORMAT, JsonSchemaImportSource

__all__ = [
    "JsonSchemaEmitOptions",
    "JsonSchemaEmitter",
    "JsonSchemaFidelityRulePack",
    "validate_jsonschema_document",
]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"
_DEFAULT_SCHEMA_URI = "https://json-schema.org/draft/2020-12/schema"


class JsonSchemaFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for JSON Schema export."""

    target_label = "JSON Schema"

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


class JsonSchemaEmitOptions(EmitOptions):
    """Per-target options for :class:`JsonSchemaEmitter`."""

    pretty_print: bool = Field(
        default=True,
        description="Pretty-print the generated JSON Schema document.",
    )
    schema_uri: str = Field(
        default=_DEFAULT_SCHEMA_URI,
        description="`$schema` dialect URI when rebuilding from canonical types.",
    )


class JsonSchemaEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a JSON Schema document."""

    key = "json-schema"
    format = JSON_SCHEMA_FORMAT
    label = "JSON Schema"
    description = "Export as a JSON Schema (2020-12) document (.json)."
    icon = "braces"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = JsonSchemaEmitOptions

    OUTPUT_MEDIA_TYPE = "application/json"

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
        return JsonSchemaFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[JsonSchemaEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, JsonSchemaEmitOptions)
            else JsonSchemaEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _JsonSchemaWriter(api, options)
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


class _JsonSchemaWriter:
    def __init__(self, api: CanonicalApi, options: JsonSchemaEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self._types_by_name = {type_.name: type_ for type_ in api.types}
        self.output_path = _output_path(api)

    def render(self) -> str:
        document = self._source_document()
        if document is None:
            document = self._rebuild_document()
            self.losses.record(
                LossKind.INFERRED,
                "rebuilt-from-canonical",
                "JSON Schema export rebuilt from canonical types because the imported raw "
                "document was unavailable",
            )

        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "JSON Schema export is types-only; services and channels are omitted",
            )

        self.tracker.record(self._api.identity.name or "json-schema", Provenance.SOURCE)
        if self._options.pretty_print:
            return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        return json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\n"

    def _source_document(self) -> Optional[Dict[str, Any]]:
        raw = self._api.raw
        if isinstance(raw, dict):
            source = raw.get("source")
            if isinstance(source, dict):
                return dict(source)
        return None

    def _rebuild_document(self) -> Dict[str, Any]:
        defs: Dict[str, Any] = {}
        root_name = self._api.title or self._api.identity.name or "Schema"
        root_schema: Optional[Dict[str, Any]] = None

        for type_ in self._api.types:
            schema = self._type_to_schema(type_)
            if type_.name == root_name:
                root_schema = schema
            else:
                defs[type_.name] = schema

        if root_schema is None and len(self._api.types) == 1:
            root_schema = self._type_to_schema(self._api.types[0])
            defs = {}

        document: Dict[str, Any] = {
            "$schema": self._options.schema_uri,
            "title": root_name,
        }
        if self._api.description:
            document["description"] = self._api.description
        if self._api.identity.id:
            document["$id"] = self._api.identity.id
        if root_schema is None:
            root_schema = {"type": "object", "properties": {}}
        document.update(root_schema)
        if defs:
            document["$defs"] = defs
        return document

    def _type_to_schema(self, type_: Type) -> Dict[str, Any]:
        if type_.kind is TypeKind.ENUM:
            schema: Dict[str, Any] = {
                "type": "string",
                "enum": [value.value for value in type_.enum_values],
            }
        elif type_.kind is TypeKind.UNION:
            schema = {
                "oneOf": [
                    {"$ref": f"#/$defs/{member}"}
                    for member in type_.union_members
                ]
            }
        elif type_.kind is TypeKind.RECORD:
            properties: Dict[str, Any] = {}
            required: List[str] = []
            for field in type_.fields:
                properties[field.name] = self._field_to_schema(field)
                if field.type.nullable is False:
                    required.append(field.name)
            schema = {"type": "object", "properties": properties}
            if required:
                schema["required"] = required
        elif type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            schema = self._ref_to_schema(type_.aliased)
        else:
            schema = {"type": "string"}
        if type_.description:
            schema["description"] = type_.description
        return schema

    def _field_to_schema(self, field: CanonicalField) -> Dict[str, Any]:
        schema = self._ref_to_schema(field.type)
        if field.description:
            schema["description"] = field.description
        return schema

    def _ref_to_schema(self, ref: TypeRef) -> Dict[str, Any]:
        if ref.is_list():
            item = ref.item or TypeRef(name="string")
            return {"type": "array", "items": self._ref_to_schema(item)}
        if ref.name in self._types_by_name:
            return {"$ref": f"#/$defs/{ref.name}"}
        schema: Dict[str, Any] = {"type": ref.name}
        if ref.nullable:
            return {"type": [schema["type"], "null"]}
        return schema


def _output_path(api: CanonicalApi) -> str:
    base = api.title or api.identity.name or "schema"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "schema"
    return f"{safe}.schema.json"


def validate_jsonschema_document(content: str) -> None:
    """Validate JSON Schema text by re-parsing it through the import adapter."""
    adapter = JsonSchemaImportSource()
    adapter.parse(content)
