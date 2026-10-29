"""JSON Schema emitter: canonical model → standalone JSON Schema — MFX-34.1, MFX-21.1 (#4126).

The inverse of :class:`app.jsonschema_import_source.JsonSchemaImportSource` and an
implementation of the :class:`app.emitter.Emitter` SPI.

**Bundle** (default): one draft 2020-12 document whose ``$defs`` hold every type of the model
(:func:`app.canonical_json_schema.build_bundle_schemas` — the same projection the instance
validator uses, so scalars become real JSON types, ``i32`` → ``{"type": "integer", "format":
"int32"}``, and constraints become keywords). The root ``$ref`` s the type named after the item
when there is one. **Per-type** (``packaging="per-type"``): one ``<Type>.schema.json`` per type,
referencing each other by file name — a multi-file export, delivered as a zip with a manifest.

**Options:** ``draft`` (``2020-12``, or a downgrade to ``draft-07`` / ``draft-04`` through
:mod:`app.jsonschema_drafts`, which records what the older draft cannot carry), ``packaging`` and
``id_base`` (the ``$id`` base URI: each document's ``$id`` is ``<id_base>/<file name>``).

A JSON Schema item is re-emitted as it was imported when nothing asks for a change (a bundle, no
``id_base``, the draft its ``$schema`` names).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from pydantic import Field, field_validator

from .canonical_json_schema import CanonicalSchemaBundle, build_bundle_schemas
from .canonical_model import ApiParadigm, CanonicalApi, Type
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
from .jsonschema_drafts import DRAFT_URIS, JsonSchemaDraft, dialect_of, downgrade_schema
from .jsonschema_import_source import JSON_SCHEMA_FORMAT, JsonSchemaImportSource
from .lossiness import LossinessKind, LossinessReport, LossinessSeverity

__all__ = [
    "JsonSchemaEmitOptions",
    "JsonSchemaEmitter",
    "JsonSchemaFidelityRulePack",
    "validate_jsonschema_document",
]

_TYPES_ONLY_DROP_MESSAGE = "only data schemas are exported"
#: A URI with a scheme (``https://…``, ``urn:…``) — what ``id_base`` must be.
_ABSOLUTE_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:\S+$")


class JsonSchemaFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for JSON Schema export.

    XSD-style types-only rules (operations and channels are dropped), plus what the bundle changes
    about the model as a whole (MFX-21.1): a document of another format is rewritten as JSON Schema,
    and a type whose ``$defs`` key is not its canonical key (``com.example.Status`` → ``Status``)
    reads back under that key, without its namespace. The per-construct rules are MFX-21.2.
    """

    target_label = "JSON Schema"

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Allocate the ``$defs`` keys once (as the export does), then walk the model.

        A 2020-12 JSON Schema item whose imported document is kept is re-emitted as it is under the
        default options, so none of its types is renamed.
        """
        raw = api.raw.get("source") if isinstance(api.raw, dict) else None
        reemitted = (
            api.format == JSON_SCHEMA_FORMAT and isinstance(raw, dict) and (dialect_of(raw) or "2020-12") == "2020-12"
        )
        self._defs_keys = {} if reemitted else build_bundle_schemas(api).defs_keys
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """A document of another format is rewritten as JSON Schema and reads back as a JSON Schema item."""
        if api.format == JSON_SCHEMA_FORMAT:
            return []
        return [
            FidelityVerdict.approx(
                message=f"The {api.format or 'source'} document is written as JSON Schema and reads back as a "
                "JSON Schema item; details specific to its format are not kept",
                severity=LossinessSeverity.INFO,
                target_mapping="document → JSON Schema",
            )
        ]

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """The capability verdict, or a note that the type is keyed by its ``$defs`` name."""
        verdict = super().type_verdict(type_)
        defs_key = self._defs_keys.get(type_.key)
        if verdict.kind is not LossinessKind.OK or defs_key is None or defs_key == type_.key:
            return verdict
        return FidelityVerdict.approx(
            message=f"JSON Schema names a type by its $defs key; {type_.key!r} is written as $defs/{defs_key} "
            "and reads back under that name"
            + (f", without its namespace {type_.namespace!r}" if type_.namespace else ""),
            severity=LossinessSeverity.INFO,
            target_mapping=f"{type_.key} → $defs/{defs_key}",
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


class JsonSchemaEmitOptions(EmitOptions):
    """Per-target options for :class:`JsonSchemaEmitter`."""

    draft: JsonSchemaDraft = Field(
        default="2020-12",
        description="JSON Schema draft: `2020-12` (default), or a downgrade to `draft-07` or `draft-04` "
        "(keywords the older draft lacks are rewritten or dropped, and reported).",
    )
    packaging: Literal["bundle", "per-type"] = Field(
        default="bundle",
        description="`bundle` writes one document with every type in `$defs`; `per-type` writes one "
        "`<Type>.schema.json` per type (a zip with a manifest).",
    )
    id_base: Optional[str] = Field(
        default=None,
        description="Base URI for `$id` (for example `https://example.com/schemas`): each document's `$id` "
        "is `<id_base>/<file name>`.",
    )
    pretty_print: bool = Field(
        default=True,
        description="Pretty-print the generated JSON Schema document.",
    )

    @field_validator("id_base")
    @classmethod
    def _absolute_id_base(cls, value: Optional[str]) -> Optional[str]:
        """``id_base`` must be an absolute URI, so every ``$id`` built from it is one."""
        if value is None or not value.strip():
            return None
        if not _ABSOLUTE_URI.match(value.strip()):
            raise ValueError("id_base must be an absolute URI, such as https://example.com/schemas")
        return value.strip().rstrip("/")


class JsonSchemaEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as standalone JSON Schema (a bundle, or one file per type)."""

    key = "json-schema"
    format = JSON_SCHEMA_FORMAT
    label = "JSON Schema"
    description = "Export as JSON Schema (2020-12, draft-07 or draft-04): one bundle or one file per type."
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
            constraints=True,
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
        files = [
            EmittedFile(path=path, content=content, media_type=self.OUTPUT_MEDIA_TYPE)
            for path, content in writer.render()
        ]
        return EmitResult(
            files=files,
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


class _JsonSchemaWriter:
    """Builds the documents of one JSON Schema export (single use)."""

    def __init__(self, api: CanonicalApi, options: JsonSchemaEmitOptions) -> None:
        self._api = api
        self._options = options
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.output_path = _output_path(api)

    def render(self) -> List[Tuple[str, str]]:
        """Every document as ``(path, text)``: the bundle, or one file per type."""
        if self._api.services or self._api.channels:
            self.losses.record(
                LossKind.NA,
                "services-dropped",
                "JSON Schema export is types-only; services and channels are omitted",
            )
        source = self._source_document()
        if source is not None:
            documents = [(self.output_path, source)]
        else:
            if self._api.format == JSON_SCHEMA_FORMAT:
                self.losses.record(
                    LossKind.INFERRED,
                    "rebuilt-from-canonical",
                    "JSON Schema export rebuilt from canonical types because the imported raw document was "
                    "unavailable or the options ask for a different draft, packaging or $id",
                )
            documents = self._per_type() if self._options.packaging == "per-type" else [self._bundle()]
            documents = [
                (path, downgrade_schema(document, self._options.draft, self.losses)) for path, document in documents
            ]
        self.tracker.record(self._api.identity.name or "json-schema", Provenance.SOURCE)
        return [(path, self._serialize(document)) for path, document in documents]

    def _source_document(self) -> Optional[Dict[str, Any]]:
        """The imported JSON Schema document, when it is re-emitted unchanged."""
        raw = self._api.raw
        source = raw.get("source") if isinstance(raw, dict) else None
        if self._api.format != JSON_SCHEMA_FORMAT or not isinstance(source, dict):
            return None
        options = self._options
        if options.packaging != "bundle" or options.id_base is not None:
            return None
        if (dialect_of(source) or "2020-12") != options.draft:
            return None
        return dict(source)

    def _bundle(self) -> Tuple[str, Dict[str, Any]]:
        """One document: every type in ``$defs``, the root ``$ref`` ing the item's own type."""
        bundle = self._project()
        title = self._api.title or self._api.identity.name or "Schema"
        document: Dict[str, Any] = {"$schema": DRAFT_URIS["2020-12"]}
        schema_id = self._id(self.output_path) or self._api.identity.id
        if schema_id:
            document["$id"] = schema_id
        document["title"] = title
        if self._api.description:
            document["description"] = self._api.description
        root = self._root_key(title)
        if root is not None:
            document["$ref"] = f"#/$defs/{bundle.defs_keys[root]}"
        if bundle.defs:
            document["$defs"] = bundle.defs
        return self.output_path, document

    def _per_type(self) -> List[Tuple[str, Dict[str, Any]]]:
        """One document per type; a reference to another type is a reference to its file."""
        bundle = self._project()
        files = {key: f"{key}.schema.json" for key in bundle.defs}
        documents: List[Tuple[str, Dict[str, Any]]] = []
        for key, schema in bundle.defs.items():
            document: Dict[str, Any] = {"$schema": DRAFT_URIS["2020-12"]}
            schema_id = self._id(files[key])
            if schema_id:
                document["$id"] = schema_id
            document["title"] = key
            document.update(_refs_to_files(schema, files))
            documents.append((files[key], document))
        return documents

    def _project(self) -> CanonicalSchemaBundle:
        """The model's types as ``$defs`` subschemas; scalars with no JSON type are reported."""
        bundle = build_bundle_schemas(self._api, wire_enums=False)
        for name in bundle.unmapped_scalars:
            self.losses.record(
                LossKind.INFERRED,
                "unmapped-scalar",
                f"{name!r} has no JSON Schema type; values of it are written as {{}} (any value).",
                pointer=name,
            )
        return bundle

    def _root_key(self, title: str) -> Optional[str]:
        """The type the document itself describes: the one named like the item, or the only one."""
        named = [t.key for t in self._api.types if t.name == title]
        if len(named) == 1:
            return named[0]
        return self._api.types[0].key if len(self._api.types) == 1 else None

    def _id(self, file_name: str) -> Optional[str]:
        """``<id_base>/<file name>``, or ``None`` without an ``id_base``."""
        return f"{self._options.id_base}/{file_name}" if self._options.id_base else None

    def _serialize(self, document: Dict[str, Any]) -> str:
        if self._options.pretty_print:
            return json.dumps(document, indent=2, ensure_ascii=False) + "\n"
        return json.dumps(document, separators=(",", ":"), ensure_ascii=False) + "\n"


def _refs_to_files(schema: Any, files: Dict[str, str]) -> Any:
    """``schema`` with each ``#/$defs/<key>`` reference pointing at ``<key>.schema.json`` instead."""
    if isinstance(schema, list):
        return [_refs_to_files(item, files) for item in schema]
    if not isinstance(schema, dict):
        return schema
    out: Dict[str, Any] = {}
    for keyword, value in schema.items():
        if keyword == "$ref" and isinstance(value, str) and value.startswith("#/$defs/"):
            target = value[len("#/$defs/"):]
            out[keyword] = files.get(target, value)
        else:
            out[keyword] = _refs_to_files(value, files)
    return out


def _output_path(api: CanonicalApi) -> str:
    base = api.title or api.identity.name or "schema"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", base).strip("-") or "schema"
    return f"{safe}.schema.json"


def validate_jsonschema_document(content: str) -> None:
    """Validate JSON Schema text: it re-parses through the import adapter and passes its draft's metaschema.

    Raises:
        ImportSourceError: The text is not a JSON Schema document.
        ValueError: The document does not validate against the metaschema of the draft it declares
            (2020-12 when it declares none).
    """
    adapter = JsonSchemaImportSource()
    document = adapter.parse(content)
    if not isinstance(document, dict):
        return
    try:
        validator_for(document, default=validator_for({"$schema": DRAFT_URIS["2020-12"]})).check_schema(document)
    except SchemaError as exc:
        raise ValueError(f"Not a valid JSON Schema ({exc.message})") from exc
