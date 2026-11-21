"""JSON Type Definition emitter: canonical model → JTD document."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple, Union

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
from .conversion_verdicts import envelope_verdicts, rekey_verdicts
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
from .jtd_import_source import JTD_FORMAT, JtdImportSource, is_jtd_document
from .lossiness import LossinessReport

__all__ = [
    "JtdEmitOptions",
    "JtdEmitter",
    "JtdFidelityRulePack",
    "validate_jtd_document",
]

_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"


def _source_document(api: CanonicalApi) -> Optional[Dict[str, Any]]:
    """The imported JTD document ``api`` carries, which an export writes back as it stands."""
    raw = api.raw
    if isinstance(raw, dict) and isinstance(raw.get("source"), dict):
        return dict(raw["source"])
    return None


def _root_name(api: CanonicalApi) -> str:
    """The name of the type a rebuilt document writes as its root schema."""
    return api.title or api.identity.name or "Schema"


class JtdFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for JTD export.

    A document rebuilt from another format's model (COA-3.1, #7052) names each definition by the
    type's bare name — JTD has no namespaces — so a namespace-qualified type reads back under a new
    key (``DROP`` + ``SYNTH``), the namespace itself is not written, and when no type is named after
    the document the first type is also written as the root schema (``SYNTH``).
    """

    target_label = "JSON Type Definition"

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Note whether the document is rebuilt (not the imported one written back), then walk."""
        self._rebuilt = _source_document(api) is None
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The namespace a rebuilt document has no place for."""
        verdicts = list(super().root_verdicts(api))
        if self._rebuilt:
            verdicts += envelope_verdicts(api, target_label=self.target_label, keeps_namespace=False)
        return verdicts

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """The re-key ``DROP`` of a namespace-qualified type, else the inherited verdicts."""
        rekey = self._rekey(type_)
        return [rekey[0]] if rekey else super().type_verdicts(type_)

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """The bare-name keys of re-keyed types, and the root schema copied from the first type."""
        pairs = list(super().synthesized_verdicts(api))
        if not self._rebuilt:
            return pairs
        pairs += [rekey[1] for rekey in map(self._rekey, api.types) if rekey]
        root = _root_name(api)
        if api.types and all(type_.name != root for type_ in api.types):
            pairs.append((root, FidelityVerdict.synth(
                message=f"a JTD document is one root schema and no type is named {root!r}; type "
                f"{api.types[0].key!r} is also written as the root",
                target_mapping=f"{api.types[0].key} → root schema",
            )))
        return pairs

    def _rekey(self, type_: Type) -> Optional[Tuple[FidelityVerdict, Tuple[str, FidelityVerdict]]]:
        """The re-key verdicts of a type whose key is not the bare name a definition gets."""
        if not getattr(self, "_rebuilt", False):
            return None
        return rekey_verdicts(
            type_.key, type_.name, target_label=self.target_label, noun="type",
            reason="definitions have no namespaces",
        )

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


class JtdEmitOptions(EmitOptions):
    """Per-target options for :class:`JtdEmitter`."""

    pretty_print: bool = Field(
        default=True,
        description="Pretty-print the generated JTD document.",
    )


class JtdEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a JTD schema document."""

    key = "jtd"
    format = JTD_FORMAT
    label = "JSON Type Definition"
    description = "Export as a JSON Type Definition (RFC 8927) document (.jtd.json)."
    icon = "braces"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = JtdEmitOptions

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
        return JtdFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[JtdEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, JtdEmitOptions)
            else JtdEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _JtdWriter(api, options)
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


def _output_path(api: CanonicalApi) -> str:
    base = re.sub(r"[^\w\-]+", "-", (api.title or api.identity.name or "schema").strip()) or "schema"
    return f"{base.lower()}.jtd.json"


class _JtdWriter:
    def __init__(self, api: CanonicalApi, options: JtdEmitOptions) -> None:
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
                "JTD export rebuilt from canonical types because the imported raw "
                "document was unavailable",
            )

        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "JTD export is types-only; services and channels are omitted",
            )

        self.tracker.record(self._api.identity.name or "jtd", Provenance.SOURCE)
        if self._options.pretty_print:
            return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        return json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\n"

    def _source_document(self) -> Optional[Dict[str, Any]]:
        return _source_document(self._api)

    def _rebuild_document(self) -> Dict[str, Any]:
        root_name = _root_name(self._api)
        definitions: Dict[str, Any] = {}
        root_schema: Optional[Dict[str, Any]] = None

        for type_ in self._api.types:
            schema = self._type_to_schema(type_)
            if type_.name == root_name:
                root_schema = schema
            else:
                definitions[type_.name] = schema

        if root_schema is None and self._api.types:
            root_schema = self._type_to_schema(self._api.types[0])

        document: Dict[str, Any] = dict(root_schema or {"properties": {}})
        if definitions:
            document["definitions"] = definitions
        if self._api.title or self._api.description:
            metadata: Dict[str, Any] = {}
            if self._api.title:
                metadata["title"] = self._api.title
            if self._api.description:
                metadata["description"] = self._api.description
            document["metadata"] = metadata
        return document

    def _type_to_schema(self, type_: Type) -> Dict[str, Any]:
        if type_.kind == TypeKind.ENUM:
            return {"enum": [value.name for value in type_.enum_values]}
        if type_.kind == TypeKind.UNION:
            discriminator = type_.extras.get("jtd_discriminator", "type")
            mapping: Dict[str, Any] = {}
            for member in type_.union_members:
                mapping[member.lower()] = {"ref": member}
            return {"discriminator": discriminator, "mapping": mapping}
        if type_.kind == TypeKind.RECORD:
            return self._record_to_schema(type_)
        return {"type": "string"}

    def _record_to_schema(self, type_: Type) -> Dict[str, Any]:
        properties: Dict[str, Any] = {}
        optional_properties: Dict[str, Any] = {}
        for field in type_.fields:
            schema = self._field_to_schema(field)
            if field.type.nullable:
                optional_properties[field.name] = schema
            else:
                properties[field.name] = schema
        document: Dict[str, Any] = {}
        if properties:
            document["properties"] = properties
        if optional_properties:
            document["optionalProperties"] = optional_properties
        return document or {"properties": {}}

    def _field_to_schema(self, field: CanonicalField) -> Dict[str, Any]:
        return self._type_ref_to_schema(field.type)

    def _type_ref_to_schema(self, ref: TypeRef) -> Dict[str, Any]:
        if ref.item is not None:
            schema: Dict[str, Any] = {"elements": self._type_ref_to_schema(ref.item)}
            if ref.nullable:
                schema["nullable"] = True
            return schema

        if ref.name in self._types_by_name:
            target = self._types_by_name[ref.name]
            if target.kind in {TypeKind.RECORD, TypeKind.UNION, TypeKind.ENUM}:
                return {"ref": ref.name}

        if ref.name in {
            "boolean",
            "string",
            "timestamp",
            "float32",
            "float64",
            "int8",
            "uint8",
            "int16",
            "uint16",
            "int32",
            "uint32",
        }:
            schema = {"type": ref.name}
            if ref.nullable:
                schema["nullable"] = True
            return schema

        schema = {"type": "string"}
        if ref.nullable:
            schema["nullable"] = True
        return schema


def validate_jtd_document(content: str) -> None:
    """Parse and validate that ``content`` is a JTD schema document."""
    from .import_ingestion import IngestionError, parse_document

    try:
        document = parse_document(content)
    except IngestionError as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(document, dict):
        raise ValueError("JTD document must be a JSON object.")
    if not is_jtd_document(document):
        raise ValueError("Emitted content is not a recognizable JTD schema document.")
    JtdImportSource().normalize(document)
