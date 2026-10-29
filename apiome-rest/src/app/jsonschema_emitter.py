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
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple, Union

from jsonschema.exceptions import SchemaError
from jsonschema.validators import validator_for
from pydantic import Field, ValidationError, field_validator

from .canonical_json_schema import CanonicalSchemaBundle, build_bundle_schemas
from .canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Type
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitResult,
    EmittedFile,
    Emitter,
    Loss,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict, types_only_advisory
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
    """Fidelity rules for JSON Schema export — MFX-21.1, MFX-21.2 (#4127).

    The pack builds the export with the JSON Schema writer, for the options the report is computed for
    (:meth:`apply_options`; the target defaults otherwise), and reports:

    * **types-only** — every operation and channel is a critical ``DROP``, and a source that has any
      carries the critical root advisory with counts (:func:`~app.fidelity_rulepack.types_only_advisory`);
    * **the rewrite** — a document of another format is rewritten as JSON Schema (info ``APPROX``), and a
      type written under a ``$defs`` key other than its canonical key reads back under that key (info
      ``APPROX``, its namespace dropped);
    * **draft downgrades** — each keyword the chosen draft drops (``DROP``) or writes another way
      (``APPROX``: ``prefixItems`` → tuple ``items``, ``unevaluatedProperties`` → ``additionalProperties``,
      draft-04 boolean exclusive bounds and ``const`` → ``enum``), filed under the type or field it is in;
    * **format** — a value written with a ``format`` is only annotated: validators do not assert it
      unless format assertion is switched on (info ``APPROX`` note).
    """

    target_label = "JSON Schema"

    #: Writer loss subjects that are draft-downgrade rewrites, and those that keep the rule exactly.
    _DOWNGRADE_SUBJECTS = frozenset({
        "keyword-dropped", "exclusive-bound-merged", "exclusive-bound-boolean", "const-as-enum",
        "prefix-items-as-tuple", "unevaluated-as-additional",
    })
    _EXACT_REWRITES = frozenset({"exclusive-bound-boolean", "const-as-enum"})

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these emit options (invalid options fall back to the defaults)."""
        try:
            self._options = JsonSchemaEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = JsonSchemaEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Build the export once (as it will be emitted), file its downgrade losses, then walk the model."""
        writer = _JsonSchemaWriter(api, getattr(self, "_options", None) or JsonSchemaEmitOptions())
        writer.render()
        bundle = writer.bundle
        self._defs_keys = bundle.defs_keys if bundle is not None else {}
        self._defs = bundle.defs if bundle is not None else {}
        self._owners = {field.key: type_.key for type_ in api.types for field in type_.fields}
        self._downgrades = self._file_downgrades(api, writer.losses.records())
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The types-only advisory, the rewrite of another format, and downgrades of the document root."""
        verdicts: List[FidelityVerdict] = []
        advisory = types_only_advisory(api, target_label=self.target_label, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            verdicts.append(advisory)
        if api.format != JSON_SCHEMA_FORMAT:
            verdicts.append(
                FidelityVerdict.approx(
                    message=f"The {api.format or 'source'} document is written as JSON Schema and reads back as a "
                    "JSON Schema item; details specific to its format are not kept",
                    severity=LossinessSeverity.INFO,
                    target_mapping="document → JSON Schema",
                )
            )
        return verdicts + self._downgrades.get(ROOT_CONSTRUCT_KEY, [])

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """The type's verdict, its format note, and the downgrades of its schema."""
        verdicts = [self.type_verdict(type_)]
        fmt = self._defs.get(self._defs_keys.get(type_.key, ""), {}).get("format")
        if fmt:
            verdicts.append(_format_note(fmt))
        return verdicts + self._downgrades.get(type_.key, [])

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

    def field_verdicts(self, field: CanonicalField) -> List[FidelityVerdict]:
        """The capability verdicts, the field's format note, and the downgrades of its schema."""
        verdicts = super().field_verdicts(field)
        fmt = _format_of(self._property_schema(field))
        if fmt:
            verdicts.append(_format_note(fmt))
        return verdicts + self._downgrades.get(field.key, [])

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

    # --- helpers ------------------------------------------------------------

    def _property_schema(self, field: CanonicalField) -> Dict[str, Any]:
        """The schema the export writes for ``field`` (``{}`` when it writes none)."""
        definition = self._defs.get(self._defs_keys.get(self._owners.get(field.key, ""), ""), {})
        return (definition.get("properties") or {}).get(field.name) or {}

    def _file_downgrades(self, api: CanonicalApi, losses: List[Loss]) -> Dict[str, List[FidelityVerdict]]:
        """Each draft-downgrade loss as a verdict, filed under the type or field its JSON Pointer is in."""
        owners: Dict[str, Tuple[str, Dict[str, str]]] = {}
        for type_ in api.types:
            defs_key = self._defs_keys.get(type_.key)
            if defs_key is not None:
                owners[defs_key] = (type_.key, {f.name: f.key for f in type_.fields})
        filed: Dict[str, List[FidelityVerdict]] = {}
        seen = set()
        for loss in losses:
            if loss.subject not in self._DOWNGRADE_SUBJECTS or (loss.subject, loss.detail) in seen:
                continue
            seen.add((loss.subject, loss.detail))
            key = _construct_of(loss.pointer or "#", owners)
            if loss.kind is LossKind.NA:
                verdict = FidelityVerdict.drop(message=loss.detail, severity=LossinessSeverity.WARN,
                                               target_mapping=loss.subject)
            else:
                severity = LossinessSeverity.INFO if loss.subject in self._EXACT_REWRITES else LossinessSeverity.WARN
                verdict = FidelityVerdict.approx(message=loss.detail, severity=severity, target_mapping=loss.subject)
            filed.setdefault(key, []).append(verdict)
        return filed


def _construct_of(pointer: str, owners: Dict[str, Tuple[str, Dict[str, str]]]) -> str:
    """The construct a downgrade's JSON Pointer is in: a field, a type, else the root.

    ``#/$defs/Order/properties/sku/…`` is the field ``Order.sku``, ``#/$defs/Order/…`` the type ``Order``.
    """
    parts = pointer.split("/")
    if len(parts) < 3 or parts[1] != "$defs" or parts[2] not in owners:
        return ROOT_CONSTRUCT_KEY
    type_key, fields = owners[parts[2]]
    if len(parts) >= 5 and parts[3] == "properties" and parts[4] in fields:
        return fields[parts[4]]
    return type_key


def _format_of(schema: Dict[str, Any]) -> Optional[str]:
    """The ``format`` a property schema (or its array items) carries."""
    if schema.get("format"):
        return str(schema["format"])
    items = schema.get("items")
    return str(items["format"]) if isinstance(items, dict) and items.get("format") else None


def _format_note(fmt: str) -> FidelityVerdict:
    """A ``format`` is an annotation: validators do not check it unless format assertion is on."""
    return FidelityVerdict.approx(
        message=f"JSON Schema treats `format: {fmt}` as an annotation: a validator does not check it unless "
        "format assertion is switched on",
        severity=LossinessSeverity.INFO,
        target_mapping=f"format {fmt} → annotation",
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
        #: The projected types (``None`` when the imported document is re-emitted).
        self.bundle: Optional[CanonicalSchemaBundle] = None

    def render(self) -> List[Tuple[str, str]]:
        """Every document as ``(path, text)``: the bundle, or one file per type."""
        advisory = types_only_advisory(self._api, target_label="JSON Schema", keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            self.losses.record(LossKind.NA, "services-dropped", advisory.message)
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
            per_type = self._options.packaging == "per-type"
            documents = [
                (
                    path,
                    # A per-type file's losses point where its schema sits in the bundle (`#/$defs/<key>`).
                    downgrade_schema(
                        document, self._options.draft, self.losses,
                        pointer=f"#/$defs/{path[: -len('.schema.json')]}" if per_type else "#",
                    ),
                )
                for path, document in documents
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
        self.bundle = bundle
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
