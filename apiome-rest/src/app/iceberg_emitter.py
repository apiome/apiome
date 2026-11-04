"""Apache Iceberg schema emitter — MFX-36.3 (#4319).

Writes an item's tables as **Iceberg schemas**: the ``{"type": "struct", "schema-id": 0, "fields": […]}``
JSON an Iceberg table's metadata holds (and ``pyiceberg.schema.Schema`` parses), one
``<table>.iceberg.json`` per table.

The tables, columns and types are the Arrow export's typed projection
(:func:`app.arrow_emitter.project_arrow_tables`, MFX-36.1) — the same tables BigQuery and Spark get
(MFX-36.2) — written in Iceberg's type vocabulary: ``struct``, ``list`` (``element-id``), ``map``
(``key-id`` / ``value-id``), ``decimal(P, S)``, ``timestamptz``, ``uuid``, ``fixed[L]`` …

Field IDs
---------
Iceberg identifies every column — nested fields, list elements, map keys and values included — by a
**field ID**, unique within the schema and never reused: it is how a table's schema evolves (a rename
keeps the ID; a dropped column's ID is retired). A source rarely has them, so the emitter assigns
them, and the export service keeps every assignment in the MFX-12.2 field-identity store (target
:data:`~app.field_identity_store.ICEBERG_TARGET`): a re-export reuses each column's ID, and a new
column gets the next ID above every one the table has ever had. The store key of a column is its
path in the table (``Order/lines/element/sku``), so a renamed column is a new column with a new ID.
An Arrow source's ``PARQUET:field_id`` metadata is the column's own ID and always wins.

The fidelity report lists each synthesized ID as ``SYNTH``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple, Union

from pydantic import Field, ValidationError
from pydantic.json_schema import SkipJsonSchema

from .arrow_emitter import (
    ArrowEmitOptions,
    ArrowFidelityRulePack,
    ArrowTable,
    _file_stem,
    _reached_types,
    project_arrow_tables,
)
from .arrow_schema import ArrowField, ArrowType
from .canonical_model import ApiParadigm, CanonicalApi, CanonicalField
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitOptionsError,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    Loss,
    LossKind,
    LossTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessReport, LossinessSeverity

__all__ = [
    "ICEBERG_FORMAT_KEY",
    "IcebergEmitOptions",
    "IcebergEmitter",
    "IcebergFidelityRulePack",
    "check_emitted_iceberg",
    "iceberg_schema",
]

ICEBERG_FORMAT_KEY = "iceberg"
ICEBERG_SUFFIX = ".iceberg.json"
JSON_MEDIA_TYPE = "application/json"
#: Loss subjects.
LOSS_ICEBERG_APPROX = "iceberg-type-approximated"
#: An Arrow column's own Iceberg / Parquet field ID.
PARQUET_FIELD_ID_KEY = "PARQUET:field_id"
_EXTENSION_KEY = "ARROW:extension:name"
_MAX_FIELD_ID = 536_870_911  # the store's range (V141); Iceberg IDs are positive 32-bit integers
_MAX_KEY = 512  # the store's field_key column
_ICEBERG_DECIMAL_MAX = 38
_LISTS = ("list", "largelist", "fixedsizelist", "listview", "largelistview")


class IcebergEmitOptions(EmitOptions):
    """Per-target options for :class:`IcebergEmitter`."""

    table: Optional[str] = Field(
        default=None,
        description="Export only this record (its name or key) as the table. Empty means every root record "
        "(a record no other record holds), each as its own schema.",
    )
    indent: int = Field(default=2, ge=0, le=8, description="JSON indentation width (0 for compact output).")
    # Not in the options schema (MFX-36.5): the card never offers it, the export service fills it. It is still
    # dumped, so the service can merge the stored IDs into the options it validates.
    persisted_field_numbers: SkipJsonSchema[Dict[str, int]] = Field(
        default_factory=dict,
        description="Field IDs earlier exports assigned, keyed by column path (`Order/lines/element/sku`); "
        "filled from the MFX-12.2 field-identity store by the export service.",
    )


# ===========================================================================
# Field IDs
# ===========================================================================


def _store_key(table: ArrowTable, path: Sequence[str]) -> str:
    """The field-identity store key of a column: ``<table key>/<path>`` (hashed past the column width)."""
    key = "/".join([table.key, *path])
    if len(key) <= _MAX_KEY:
        return key
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"{key[:_MAX_KEY - 17]}#{digest}"


def _source_id(source: ArrowField) -> Optional[int]:
    """The column's own ID (an Arrow source's ``PARQUET:field_id`` metadata), when valid."""
    value = source.metadata_value(PARQUET_FIELD_ID_KEY)
    try:
        number = int(value) if value is not None else None
    except ValueError:
        return None
    return number if number is not None and 1 <= number <= _MAX_FIELD_ID else None


@dataclass
class _Ids:
    """Assigns a table's field IDs: the source's, then the stored ones, then fresh ones above all of them.

    A fresh ID is never one the table has had (Iceberg never reuses a field ID), so it starts above every
    stored ID for the table, including those of columns the table has since lost.
    """

    table: ArrowTable
    persisted: Mapping[str, int]
    used: Set[int] = field(default_factory=set)
    assigned: Dict[str, int] = field(default_factory=dict)
    synthesized: List[str] = field(default_factory=list)
    _next: int = 1

    def __post_init__(self) -> None:
        prefix = f"{self.table.key}/"
        stored = [n for k, n in self.persisted.items() if k.startswith(prefix)]
        self._next = max(stored, default=0) + 1

    def reserve_sources(self, fields: Sequence[ArrowField]) -> None:
        """Claim every source ID first, so a stored or fresh ID never collides with one."""
        for child in fields:
            number = _source_id(child)
            if number is not None:
                self.used.add(number)
                self._next = max(self._next, number + 1)
            self.reserve_sources(child.children)
            if child.type.name == "map":
                self.reserve_sources(child.children[0].children)

    def take(self, path: Sequence[str], source: Optional[ArrowField]) -> int:
        """The ID of the column at ``path``."""
        own = _source_id(source) if source is not None else None
        if own is not None:
            return own
        key = _store_key(self.table, path)
        stored = self.persisted.get(key)
        if stored is not None and stored not in self.used:
            self.used.add(stored)
            self._next = max(self._next, stored + 1)
            return stored
        while self._next in self.used:
            self._next += 1
        number = self._next
        self._next += 1
        self.used.add(number)
        self.assigned[key] = number
        self.synthesized.append("/".join(path))
        return number


# ===========================================================================
# Serialization
# ===========================================================================


@dataclass
class _IcebergWriter:
    """Writes one table's Arrow fields as Iceberg fields, recording approximations against the table."""

    table: ArrowTable
    ids: _Ids
    losses: LossTracker

    def _approx(self, path: Sequence[str], detail: str) -> None:
        self.losses.record(LossKind.INFERRED, LOSS_ICEBERG_APPROX,
                           f"Iceberg column {'.'.join(path)!r}: {detail}", self.table.key)

    def fields(self, children: Sequence[ArrowField], path: Tuple[str, ...], *,
               optional: bool = False) -> List[Dict[str, Any]]:
        return [self.field(child, path + (child.name,), optional=optional) for child in children]

    def field(self, source: ArrowField, path: Tuple[str, ...], *, optional: bool = False) -> Dict[str, Any]:
        number = self.ids.take(path, source)
        entry: Dict[str, Any] = {"id": number, "name": source.name,
                                 "required": not source.nullable and not optional,
                                 "type": self.type(source, path)}
        description = source.metadata_value("description")
        if description:
            entry["doc"] = description
        return entry

    def type(self, source: ArrowField, path: Tuple[str, ...]) -> Any:
        type_ = source.type
        name = type_.name
        if name in _LISTS:
            element = source.children[0]
            element_path = path + ("element",)
            element_id = self.ids.take(element_path, element)
            return {"type": "list", "element-id": element_id, "element": self.type(element, element_path),
                    "element-required": not element.nullable}
        if name == "struct":
            return {"type": "struct", "fields": self.fields(source.children, path)}
        if name == "map":
            key, value = source.children[0].children
            key_path, value_path = path + ("key",), path + ("value",)
            key_id = self.ids.take(key_path, key)
            value_id = self.ids.take(value_path, value)
            return {"type": "map", "key-id": key_id, "key": self.type(key, key_path), "value-id": value_id,
                    "value": self.type(value, value_path), "value-required": not value.nullable}
        if name == "union":
            self._approx(path, "a union is a struct with one optional field per member (Iceberg has no union)")
            return {"type": "struct", "fields": self.fields(source.children, path, optional=True)}
        return self.primitive(source, type_, path)

    def primitive(self, source: ArrowField, type_: ArrowType, path: Tuple[str, ...]) -> str:
        name = type_.name
        extension = source.metadata_value(_EXTENSION_KEY)
        if extension == "arrow.uuid":
            return "uuid"
        if extension == "arrow.json":
            self._approx(path, "a JSON value is a string (Iceberg v2 has no JSON or variant type)")
            return "string"
        if name in ("utf8", "largeutf8", "utf8view"):
            return "string"
        if name in ("binary", "largebinary", "binaryview"):
            return "binary"
        if name == "fixedsizebinary":
            return f"fixed[{int(type_.parameter('byteWidth', 1))}]"
        if name == "bool":
            return "boolean"
        if name == "int":
            width = int(type_.parameter("bitWidth", 64))
            if type_.parameter("isSigned", True) is False:
                width *= 2  # the next signed width holds every unsigned value
            if width > 64:
                self._approx(path, "an unsigned 64-bit integer is decimal(20, 0) (Iceberg's long is signed)")
                return "decimal(20, 0)"
            return "long" if width > 32 else "int"
        if name == "floatingpoint":
            return "double" if type_.parameter("precision") == "DOUBLE" else "float"
        if name == "decimal":
            precision = int(type_.parameter("precision", 38))
            scale = int(type_.parameter("scale", 0))
            if precision > _ICEBERG_DECIMAL_MAX:
                self._approx(path, f"decimal({precision}, {scale}) is beyond Iceberg's 38 digits; written "
                             f"decimal(38, {min(scale, 38)})")
                precision, scale = _ICEBERG_DECIMAL_MAX, min(scale, _ICEBERG_DECIMAL_MAX)
            return f"decimal({precision}, {scale})"
        if name == "date":
            return "date"
        if name == "time":
            if type_.parameter("unit") == "NANOSECOND":
                self._approx(path, "a nanosecond time is a microsecond `time`")
            return "time"
        if name == "timestamp":
            if type_.parameter("unit") == "NANOSECOND":
                self._approx(path, "a nanosecond timestamp is a microsecond one (`timestamp_ns` is Iceberg v3)")
            return "timestamptz" if type_.parameter("timezone") else "timestamp"
        if name == "duration":
            self._approx(path, "a duration is a long (Iceberg has no duration type)")
            return "long"
        if name == "interval":
            self._approx(path, "an interval is a string (Iceberg has no interval type)")
            return "string"
        self._approx(path, f"Arrow type `{name}` has no Iceberg type; written as a string")
        return "string"


def iceberg_schema(table: ArrowTable, *, persisted: Optional[Mapping[str, int]] = None,
                   losses: Optional[LossTracker] = None) -> Tuple[Dict[str, Any], _Ids]:
    """One table of the projection as an Iceberg schema.

    Args:
        table: The table (from :func:`app.arrow_emitter.project_arrow_tables`).
        persisted: Field IDs earlier exports assigned, by store key.
        losses: Where approximations are recorded.

    Returns:
        The schema JSON object, and the ID allocator (its ``assigned`` map holds the new IDs).
    """
    ids = _Ids(table, persisted or {})
    ids.reserve_sources(table.schema.fields)
    writer = _IcebergWriter(table, ids, losses if losses is not None else LossTracker())
    fields = writer.fields(table.schema.fields, ())
    return {"type": "struct", "schema-id": 0, "fields": fields}, ids


# ===========================================================================
# The export gate
# ===========================================================================


def _collect_ids(node: Any, ids: List[int]) -> None:
    """Every field / element / key / value ID in an Iceberg schema JSON."""
    if isinstance(node, Mapping):
        for key in ("id", "element-id", "key-id", "value-id"):
            if isinstance(node.get(key), int):
                ids.append(node[key])
        for value in node.values():
            _collect_ids(value, ids)
    elif isinstance(node, list):
        for value in node:
            _collect_ids(value, ids)


def check_emitted_iceberg(emit_result: EmitResult) -> List[Dict[str, str]]:
    """The export gate's check: pyiceberg parses each schema, and its field IDs are unique and positive.

    Args:
        emit_result: The emitter's output.

    Returns:
        ``{"rule", "message", "file"}`` per problem; empty when every schema passes.
    """
    from pyiceberg.schema import Schema  # noqa: PLC0415 - only exports need pyiceberg

    problems: List[Dict[str, str]] = []
    schemas = [f for f in emit_result.files if f.path.endswith(ICEBERG_SUFFIX)]
    if not schemas:
        return [{"rule": "schema", "message": "The Iceberg export wrote no `.iceberg.json` schema.", "file": ""}]
    for emitted in schemas:
        text = str(emitted.content)
        try:
            document = json.loads(text)
            Schema.model_validate_json(text)
        except (ValueError, ValidationError) as exc:
            problems.append({"rule": "pyiceberg", "message": f"pyiceberg cannot parse the schema: {exc}",
                             "file": emitted.path})
            continue
        ids: List[int] = []
        _collect_ids(document.get("fields"), ids)
        duplicates = sorted({n for n in ids if ids.count(n) > 1})
        if duplicates:
            problems.append({"rule": "iceberg.field-id", "message": f"field ID(s) {duplicates} are used twice",
                             "file": emitted.path})
        if any(n < 1 for n in ids):
            problems.append({"rule": "iceberg.field-id", "message": "field IDs are positive", "file": emitted.path})
    return problems


# ===========================================================================
# Fidelity
# ===========================================================================


class IcebergFidelityRulePack(ArrowFidelityRulePack):
    """Fidelity rules for Iceberg export.

    The Arrow pack's rules (the types-only advisory, dropped constraints, the projection's losses per
    field), minus the Arrow round trip — no importer reads Iceberg — plus Iceberg's own: each type it
    cannot hold is approximated under its table, and every **field ID the source does not carry is
    synthesized** (``SYNTH``): assigned on the first export and kept by every re-export.
    """

    target_label = "Apache Iceberg"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these options (invalid options fall back to the defaults)."""
        try:
            self._iceberg_options = IcebergEmitOptions.model_validate(dict(options))
        except (ValidationError, ValueError):
            self._iceberg_options = IcebergEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Project once, serialize to Iceberg, index the losses by construct, then walk the model."""
        options = getattr(self, "_iceberg_options", None) or IcebergEmitOptions()
        losses = LossTracker()
        self._tables: List[ArrowTable] = []
        try:
            self._tables = project_arrow_tables(api, ArrowEmitOptions(table=options.table), losses)
        except (EmitPreconditionError, EmitOptionsError, ValueError):
            pass
        for table in self._tables:
            iceberg_schema(table, persisted=options.persisted_field_numbers, losses=losses)
        self._filed: Dict[str, List[Loss]] = {}
        for loss in losses.records():
            self._filed.setdefault(loss.pointer or "", []).append(loss)
        self._changes, self._added = {}, {}
        self._reached = _reached_types(api, self._tables)
        return CapabilityRulePack.evaluate(self, api)

    def _mode(self) -> str:
        """Iceberg's union and enumeration wording (MFX-36.4)."""
        return "iceberg"

    def _field_identity_verdict(self, member: CanonicalField) -> Optional[FidelityVerdict]:
        """``SYNTH`` unless the source carries the column's Iceberg ID (an Arrow ``PARQUET:field_id``)."""
        metadata = (member.extras or {}).get("arrow_metadata") or {}
        if isinstance(metadata, Mapping) and str(metadata.get(PARQUET_FIELD_ID_KEY, "")).isdigit():
            return None
        return FidelityVerdict.synth(
            message=f"{self.target_label} identifies every column by a field ID; one is assigned to "
            f"{member.key!r} on the first export and kept by every re-export",
            severity=LossinessSeverity.INFO,
            target_mapping="synthesized field ID (persisted)",
        )


# ===========================================================================
# Emitter
# ===========================================================================


class IcebergEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as Apache Iceberg schemas, one ``<table>.iceberg.json`` per table."""

    key = ICEBERG_FORMAT_KEY
    requires_source = ("record-type",)
    format = ICEBERG_FORMAT_KEY
    label = "Apache Iceberg"
    description = (
        "Export the types as Apache Iceberg table schemas: one table per root record, with nested structs, "
        "lists and maps, logical types, and field IDs that stay the same on every re-export."
    )
    icon = "database"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = True
    options_model = IcebergEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """Nested types, unions (as structs), nullability and field identity; no operations, events or constraints."""
        return CapabilityProfile(operations=False, events=False, unions=True, nullability=True,
                                 constraints=False, field_identity=True)

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Iceberg rules."""
        return IcebergFidelityRulePack

    def emit(self, api: CanonicalApi, *, opts: Optional[Union[IcebergEmitOptions, EmitOptions]] = None) -> EmitResult:
        """Emit one ``<table>.iceberg.json`` per table.

        Returns:
            The files, the losses, and in ``field_identity_assignments`` every field ID assigned for the
            first time (the export service persists them).

        Raises:
            EmitOptionsError: When ``opts`` is invalid or ``table`` names no record.
            EmitPreconditionError: When the model has no record type.
        """
        options = _coerce_options(opts)
        losses = LossTracker()
        tables = project_arrow_tables(api, ArrowEmitOptions(table=options.table), losses)
        if any(s.operations for s in api.services) or api.channels:
            losses.record(LossKind.NA, "iceberg-services-dropped", "Iceberg schemas describe tables; operations "
                          "and channels are not written", "")
        files: List[EmittedFile] = []
        assigned: Dict[str, int] = {}
        stems: Set[str] = set()
        indent = options.indent or None
        for table in tables:
            schema, ids = iceberg_schema(table, persisted=options.persisted_field_numbers, losses=losses)
            assigned.update(ids.assigned)
            stem = _file_stem(table.name)
            while stem in stems:
                stem += "_"
            stems.add(stem)
            files.append(EmittedFile(path=f"{stem}{ICEBERG_SUFFIX}", media_type=JSON_MEDIA_TYPE,
                                     content=json.dumps(schema, indent=indent, ensure_ascii=False) + "\n"))
        files.sort(key=lambda f: f.path)
        return EmitResult(files=files, media_type=JSON_MEDIA_TYPE if len(files) == 1 else "application/zip",
                          losses=losses.records(), field_identity_assignments=assigned)


def _coerce_options(opts: Optional[Union[IcebergEmitOptions, EmitOptions]]) -> IcebergEmitOptions:
    if isinstance(opts, IcebergEmitOptions):
        return opts
    try:
        return IcebergEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid Iceberg emit options: {exc}") from exc
