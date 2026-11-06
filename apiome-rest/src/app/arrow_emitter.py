"""Apache Arrow / Parquet schema emitter: canonical types → Arrow schemas — MFX-36.1 (#4317).

The inverse of the Arrow importer (FMT-4.5, :mod:`app.arrow_normalizer`): the item's types become
**Arrow schemas**, one per table, written as

* ``<table>.arrow.json`` — the Arrow **JSON integration form** (``{"schema": {"fields": …}}``), the
  same shape :mod:`app.arrow_parser` reads, so an export imports straight back; and
* ``<table>.parquet.txt`` — the **Parquet message** the same schema becomes (``message schema {
  required binary order_id (STRING); … }``), as pyarrow's Parquet writer derives it.

The projection (:func:`project_arrow_tables`) builds :class:`~app.arrow_schema.ArrowSchema` values —
Apiome's own Arrow vocabulary — and every one is constructed by **pyarrow**
(:func:`app.arrow_ipc.schema_to_pyarrow`) before it is written, so a schema pyarrow cannot build
cannot ship. MFX-36.2 serializes the same projection as BigQuery and Spark schemas.

Tables
------
An Arrow schema is one table. The tables are the **root records** — the records no other record
holds — and every record they reach is nested inside them as a ``struct``; an item imported from
Arrow has exactly one root, its own table. Option ``table`` exports one record instead.

Types
-----
* **Nested types map natively.** A record is a ``struct``, a list a ``list`` (its element named
  ``item``), a map a ``map`` (``entries`` of a non-null ``key`` and a ``value``), a union a dense
  ``union`` of its members, an enumeration a dictionary-encoded ``utf8`` column.
* **Logical types.** A date is ``date32`` (``DAY``), a date-time a ``timestamp`` in microseconds,
  UTC; a time ``time64`` in microseconds, a duration ``duration`` in microseconds; a decimal a
  ``decimal128`` with its precision and scale (the scale from ``multipleOf``, else synthesized);
  a UUID a 16-byte ``fixedsizebinary`` with the canonical ``arrow.uuid`` extension; integers keep
  their width and signedness.
* **An item imported from Arrow** keeps each field's own type — unit, time zone, width, precision,
  dictionary encoding, extension and metadata — so it exports back as it was read.
* A record that contains itself cannot be a ``struct`` of itself; the inner occurrence is a
  ``utf8`` column with the ``arrow.json`` extension, and that is reported.

Every decision made up is recorded as a loss; the fidelity rules beyond the profile's are MFX-36.4.
"""

from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Set, Tuple, Union

from pydantic import Field, ValidationError

from .arrow_schema import (
    ARROW_EXTENSION_METADATA_KEY,
    ARROW_EXTENSION_NAME_KEY,
    ArrowDictionaryEncoding,
    ArrowField,
    ArrowParseError,
    ArrowSchema,
    ArrowType,
)
from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
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
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict, types_only_advisory
from .import_source import DiffChangeKind
from .lossiness import LossinessReport, LossinessSeverity

__all__ = [
    "ARROW_FORMAT_KEY",
    "ArrowEmitOptions",
    "ArrowEmitter",
    "ArrowFidelityRulePack",
    "ArrowTable",
    "arrow_schema_json",
    "check_emitted_arrow",
    "parquet_message",
    "project_arrow_tables",
]

#: Registry key and format — the Arrow importer's, so ``arrow -> arrow`` pairs in the round-trip matrix.
ARROW_FORMAT_KEY = "arrow"
JSON_MEDIA_TYPE = "application/json"
PARQUET_MEDIA_TYPE = "text/plain"
SCHEMA_SUFFIX = ".arrow.json"
PARQUET_SUFFIX = ".parquet.txt"
#: MFX-36.2 (#4318): the BigQuery and Spark schema modes.
BIGQUERY_SUFFIX = ".bigquery.json"
SPARK_SUFFIX = ".spark.ddl"
BIGQUERY_BUNDLE = f"schemas{BIGQUERY_SUFFIX}"
SPARK_BUNDLE = f"schemas{SPARK_SUFFIX}"
OUTPUT_MODES = ("arrow", "bigquery", "spark")
#: The root name the Arrow importer uses when a schema names nothing (its ``DEFAULT_ROOT_NAME``).
_DEFAULT_ROOT_NAME = "Schema"

#: Loss subjects.
LOSS_RECURSION = "arrow-recursive-record-as-json"
LOSS_ANY_AS_JSON = "arrow-untyped-as-json"
LOSS_DECIMAL_SYNTHESIZED = "arrow-decimal-precision-synthesized"
LOSS_ENUM_DICTIONARY = "arrow-enum-as-dictionary"
LOSS_MAP_KEY = "arrow-map-key-as-utf8"
LOSS_EMPTY_RECORD = "arrow-empty-record-as-json"
LOSS_INTERVAL_UNIT = "arrow-interval-as-month-day-nano"
LOSS_PARQUET_UNSUPPORTED = "parquet-message-not-written"
LOSS_SERVICES = "arrow-services-dropped"
SYNTH_SUBJECTS = frozenset({LOSS_DECIMAL_SYNTHESIZED})

#: Canonical scalar (lower-case) → Arrow type.
_SCALARS: Dict[str, ArrowType] = {
    "string": ArrowType("utf8"), "str": ArrowType("utf8"), "text": ArrowType("utf8"),
    "bool": ArrowType("bool"), "boolean": ArrowType("bool"),
    "int8": ArrowType("int", {"bitWidth": 8, "isSigned": True}),
    "int16": ArrowType("int", {"bitWidth": 16, "isSigned": True}),
    "int32": ArrowType("int", {"bitWidth": 32, "isSigned": True}),
    "int": ArrowType("int", {"bitWidth": 32, "isSigned": True}),
    "integer": ArrowType("int", {"bitWidth": 64, "isSigned": True}),
    "int64": ArrowType("int", {"bitWidth": 64, "isSigned": True}),
    "long": ArrowType("int", {"bitWidth": 64, "isSigned": True}),
    "uint8": ArrowType("int", {"bitWidth": 8, "isSigned": False}),
    "uint16": ArrowType("int", {"bitWidth": 16, "isSigned": False}),
    "uint32": ArrowType("int", {"bitWidth": 32, "isSigned": False}),
    "uint64": ArrowType("int", {"bitWidth": 64, "isSigned": False}),
    "float": ArrowType("floatingpoint", {"precision": "SINGLE"}),
    "float32": ArrowType("floatingpoint", {"precision": "SINGLE"}),
    "double": ArrowType("floatingpoint", {"precision": "DOUBLE"}),
    "float64": ArrowType("floatingpoint", {"precision": "DOUBLE"}),
    "number": ArrowType("floatingpoint", {"precision": "DOUBLE"}),
    "bytes": ArrowType("binary"), "binary": ArrowType("binary"), "byte": ArrowType("binary"),
    "null": ArrowType("null"),
}
#: Logical types, by canonical scalar or ``format``.
_DATE = ArrowType("date", {"unit": "DAY"})
_TIMESTAMP = ArrowType("timestamp", {"unit": "MICROSECOND", "timezone": "UTC"})
_TIME = ArrowType("time", {"unit": "MICROSECOND", "bitWidth": 64})
_DURATION = ArrowType("duration", {"unit": "MICROSECOND"})
_UUID = ArrowType("fixedsizebinary", {"byteWidth": 16})
_LOGICAL: Dict[str, ArrowType] = {
    "date": _DATE, "date-time": _TIMESTAMP, "datetime": _TIMESTAMP, "timestamp": _TIMESTAMP,
    "time": _TIME, "duration": _DURATION, "uuid": _UUID,
}
#: Default decimal precision, and the scale written when nothing states one.
_DECIMAL_PRECISION = 38
_DECIMAL_SCALE = 9
#: Arrow type names that are nested (built from canonical structure, never copied from a field's extras).
_NESTED = frozenset({"struct", "list", "largelist", "fixedsizelist", "listview", "largelistview", "map",
                     "union", "runendencoded"})
_FILE_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


class ArrowEmitOptions(EmitOptions):
    """Per-target options for :class:`ArrowEmitter`."""

    table: Optional[str] = Field(
        default=None,
        description="Export only this record (its name or key) as the table. Empty means every root record "
        "(a record no other record holds), each as its own schema.",
    )
    output: Literal["arrow", "bigquery", "spark"] = Field(
        default="arrow",
        description="What to write for each table: `arrow` (an Arrow schema, plus its Parquet message), "
        "`bigquery` (a BigQuery table schema, the JSON `bq mk --schema` reads) or `spark` (a Spark StructType "
        "DDL string, what `DataType.fromDDL` parses). All three serialize the same typed projection.",
    )
    parquet: bool = Field(
        default=True,
        description="Also write each table's Parquet message (`<table>.parquet.txt`), as pyarrow derives it "
        "(output `arrow` only).",
    )
    bundle: bool = Field(
        default=False,
        description="Output `bigquery` / `spark`: write every table into one file (`schemas.bigquery.json`, an "
        "object of table → schema; `schemas.spark.ddl`, a `-- <table>` line before each DDL line) instead of "
        "one file per table.",
    )
    indent: int = Field(default=2, ge=0, le=8, description="JSON indentation width (0 for compact output).")


@dataclass(frozen=True)
class ArrowTable:
    """One table of the projection.

    Attributes:
        name: The table's name (the root record's name).
        key: The root record's key.
        schema: The table's Arrow schema.
    """

    name: str
    key: str
    schema: ArrowSchema


# ===========================================================================
# The projection
# ===========================================================================


class _Projector:
    """Builds Arrow fields from canonical types, recording every loss."""

    def __init__(self, api: CanonicalApi, losses: LossTracker) -> None:
        self.api = api
        self.losses = losses
        self.types: Dict[str, Type] = {t.key: t for t in api.types}
        self._dictionary_ids = 0

    def _type(self, name: Optional[str]) -> Optional[Type]:
        if name is None:
            return None
        return self.types.get(name) or next((t for t in self.api.types if t.name == name), None)

    def record_fields(self, record: Type, stack: Tuple[str, ...]) -> Tuple[ArrowField, ...]:
        """The fields of a record (in field-number order when the source numbered them)."""
        members = sorted(record.fields, key=lambda m: (m.field_number is None, m.field_number or 0))
        return tuple(self.field(m, stack + (record.key,)) for m in members)

    def field(self, member: CanonicalField, stack: Tuple[str, ...]) -> ArrowField:
        """One canonical field as an Arrow field."""
        extras = member.extras or {}
        arrow_field = self.ref_field(member.name, member.type, constraints=member.constraints, extras=extras,
                                     stack=stack, pointer=member.key)
        metadata = dict(arrow_field.metadata)
        for key, value in (extras.get("arrow_metadata") or {}).items():
            metadata.setdefault(str(key), str(value))
        if member.description and "description" not in metadata:
            metadata["description"] = member.description
        if metadata != dict(arrow_field.metadata):
            arrow_field = ArrowField(name=arrow_field.name, type=arrow_field.type, nullable=arrow_field.nullable,
                                     children=arrow_field.children, dictionary=arrow_field.dictionary,
                                     metadata=tuple(metadata.items()))
        return arrow_field

    def ref_field(self, name: str, ref: TypeRef, *, constraints: Optional[Constraints], extras: Mapping[str, Any],
                  stack: Tuple[str, ...], pointer: str) -> ArrowField:
        """An Arrow field named ``name`` for the canonical reference ``ref``."""
        nullable = ref.nullable is not False
        if ref.item is not None:
            item_extras = _bag(extras.get("arrow_item"))
            element = self.ref_field(str(item_extras.get("name") or "item"), ref.item, constraints=None,
                                     extras=item_extras, stack=stack, pointer=pointer)
            declared = extras.get("arrow_type") if isinstance(extras.get("arrow_type"), Mapping) else {}
            if declared.get("name") == "fixedsizelist" and constraints is not None and constraints.max_items:
                list_type = ArrowType("fixedsizelist", {"listSize": int(constraints.max_items)})
            else:
                list_type = ArrowType("list")
            return ArrowField(name=name, type=list_type, nullable=nullable, children=(element,))
        target = self._type(ref.name)
        if target is not None and target.kind is not TypeKind.SCALAR:
            return self.named_field(name, target, nullable=nullable, extras=extras, stack=stack, pointer=pointer)
        return self.scalar_field(name, ref.name or "any", nullable=nullable, constraints=constraints, extras=extras,
                                 pointer=pointer, named=target)

    def named_field(self, name: str, target: Type, *, nullable: bool, extras: Mapping[str, Any],
                    stack: Tuple[str, ...], pointer: str) -> ArrowField:
        """A field whose type is a named canonical type (record, map, union, enum, alias)."""
        if target.kind is TypeKind.ALIAS and target.aliased is not None and target.key not in stack:
            return self.ref_field(name, target.aliased, constraints=target.constraints, extras=extras,
                                  stack=stack + (target.key,), pointer=pointer)
        if target.kind is TypeKind.RECORD:
            if target.key in stack:
                self.losses.record(LossKind.INFERRED, LOSS_RECURSION,
                                   f"{pointer!r} refers back to {target.key!r}, which contains it; Arrow has no "
                                   "recursive struct, so this occurrence is a JSON string (arrow.json)", pointer)
                return _json_field(name, nullable)
            if not target.fields:
                self.losses.record(LossKind.INFERRED, LOSS_EMPTY_RECORD,
                                   f"{pointer!r} holds {target.key!r}, a record with no fields; Arrow defines a "
                                   "struct by its children, so this column is a JSON string (arrow.json)", pointer)
                return _json_field(name, nullable)
            return ArrowField(name=name, type=ArrowType("struct"), nullable=nullable,
                              children=self.record_fields(target, stack))
        if target.kind is TypeKind.MAP:
            return self.map_field(name, target, nullable=nullable, stack=stack, pointer=pointer)
        if target.kind is TypeKind.UNION:
            return self.union_field(name, target, nullable=nullable, stack=stack, pointer=pointer)
        if target.kind is TypeKind.ENUM:
            self._dictionary_ids += 1
            self.losses.record(LossKind.INFERRED, LOSS_ENUM_DICTIONARY,
                               f"enum {target.key!r} is a dictionary-encoded utf8 column; Arrow keeps no list of "
                               "allowed values", pointer)
            return ArrowField(name=name, type=ArrowType("utf8"), nullable=nullable,
                              dictionary=ArrowDictionaryEncoding(index_type=ArrowType(
                                  "int", {"bitWidth": 32, "isSigned": True})))
        return self.scalar_field(name, "any", nullable=nullable, constraints=None, extras={}, pointer=pointer)

    def map_field(self, name: str, target: Type, *, nullable: bool, stack: Tuple[str, ...], pointer: str) -> ArrowField:
        """A ``map`` of a non-null key and a value."""
        key_ref = target.key_type or TypeRef(name="string")
        key_target = self._type(key_ref.name)
        if key_ref.item is not None or (key_target is not None and key_target.kind is not TypeKind.SCALAR
                                        and key_target.kind is not TypeKind.ENUM):
            self.losses.record(LossKind.INFERRED, LOSS_MAP_KEY,
                               f"map {target.key!r} has a structured key; an Arrow map key is written as utf8",
                               pointer)
            key_ref = TypeRef(name="string")
        type_extras = target.extras or {}
        key_bag = _bag(type_extras.get("arrow_key")) if key_ref is target.key_type else {}
        key = self.ref_field("key", TypeRef(name=key_ref.name, item=key_ref.item, nullable=False), constraints=None,
                             extras=key_bag, stack=stack, pointer=pointer)
        key = ArrowField(name="key", type=key.type, nullable=False, children=key.children, dictionary=None)
        value = self.ref_field("value", target.value_type or TypeRef(name="string"), constraints=None,
                               extras=_bag(type_extras.get("arrow_value")), stack=stack, pointer=pointer)
        entries = ArrowField(name="entries", type=ArrowType("struct"), nullable=False, children=(key, value))
        sorted_keys = bool((target.extras or {}).get("arrow_keys_sorted", False))
        return ArrowField(name=name, type=ArrowType("map", {"keysSorted": sorted_keys}), nullable=nullable,
                          children=(entries,))

    def union_field(self, name: str, target: Type, *, nullable: bool, stack: Tuple[str, ...],
                    pointer: str) -> ArrowField:
        """A dense ``union`` of the union's members (variant names and type codes kept from an Arrow source)."""
        arrow_union = (target.extras or {}).get("arrow_union") or {}
        variants = arrow_union.get("variants") if isinstance(arrow_union, Mapping) else None
        children: List[ArrowField] = []
        codes: List[int] = []
        if isinstance(variants, list) and variants:
            for index, variant in enumerate(variants):
                member = str(variant.get("member") or "any")
                child = self.ref_field(str(variant.get("name") or member), TypeRef(name=member), constraints=None,
                                       extras={"arrow_type": variant.get("type") or {}}, stack=stack, pointer=pointer)
                children.append(child)
                codes.append(int(variant.get("typeId", index)))
        else:
            for index, member in enumerate(target.union_members):
                member_type = self._type(member)
                child_name = member_type.name if member_type is not None else member
                children.append(self.ref_field(child_name, TypeRef(name=member), constraints=None, extras={},
                                               stack=stack, pointer=pointer))
                codes.append(index)
        mode = str(arrow_union.get("mode", "DENSE")).upper() if isinstance(arrow_union, Mapping) else "DENSE"
        return ArrowField(name=name, type=ArrowType("union", {"mode": mode if mode in ("DENSE", "SPARSE") else "DENSE",
                                                               "typeIds": codes}),
                          nullable=nullable, children=tuple(children))

    def scalar_field(self, name: str, scalar: str, *, nullable: bool, constraints: Optional[Constraints],
                     extras: Mapping[str, Any], pointer: str, named: Optional[Type] = None) -> ArrowField:
        """A leaf field: the Arrow source's own type when recorded, else the scalar's logical type."""
        declared = extras.get("arrow_type") if isinstance(extras.get("arrow_type"), Mapping) else None
        metadata: Dict[str, str] = {}
        if declared and declared.get("name") and declared.get("name") not in _NESTED:
            arrow_type = ArrowType(str(declared["name"]), {k: v for k, v in declared.items() if k != "name"})
            if arrow_type.name == "interval" and arrow_type.parameter("unit") != "MONTH_DAY_NANO":
                self.losses.record(LossKind.INFERRED, LOSS_INTERVAL_UNIT,
                                   f"{pointer!r} is a {arrow_type.parameter('unit')} interval, which pyarrow cannot "
                                   "construct; written as a MONTH_DAY_NANO interval", pointer)
                arrow_type = ArrowType("interval", {"unit": "MONTH_DAY_NANO"})
        else:
            arrow_type, extension = self._logical(scalar, constraints, extras, pointer, named)
            if extension is not None:
                metadata[ARROW_EXTENSION_NAME_KEY] = extension
                metadata[ARROW_EXTENSION_METADATA_KEY] = ""
        extension_extra = extras.get("arrow_extension")
        if isinstance(extension_extra, Mapping) and extension_extra.get("name"):
            metadata[ARROW_EXTENSION_NAME_KEY] = str(extension_extra["name"])
            metadata[ARROW_EXTENSION_METADATA_KEY] = str(extension_extra.get("metadata") or "")
        dictionary = None
        dictionary_extra = extras.get("arrow_dictionary")
        if isinstance(dictionary_extra, Mapping):
            index = dictionary_extra.get("indexType") or {"name": "int", "bitWidth": 32, "isSigned": True}
            dictionary = ArrowDictionaryEncoding(
                index_type=ArrowType(str(index.get("name", "int")), {k: v for k, v in index.items() if k != "name"}),
                is_ordered=bool(dictionary_extra.get("isOrdered", False)))
        # A `null` column holds nothing but nulls, so it is nullable whatever the source said.
        return ArrowField(name=name, type=arrow_type, nullable=nullable or arrow_type.name == "null",
                          dictionary=dictionary, metadata=tuple(metadata.items()))

    def _logical(self, scalar: str, constraints: Optional[Constraints], extras: Mapping[str, Any], pointer: str,
                 named: Optional[Type]) -> Tuple[ArrowType, Optional[str]]:
        """The Arrow type (and canonical extension name, if any) of a canonical scalar."""
        lowered = scalar.lower()
        fmt = (constraints.format or "").lower() if constraints is not None and constraints.format else ""
        if fmt in _LOGICAL and lowered in ("string", "str", "text"):
            return _LOGICAL[fmt], "arrow.uuid" if fmt == "uuid" else None
        if lowered in _LOGICAL:
            return _LOGICAL[lowered], "arrow.uuid" if lowered == "uuid" else None
        if lowered in ("decimal", "numeric", "bigdecimal"):
            return self._decimal(constraints, extras, pointer), None
        if lowered in ("bytes", "binary", "byte") and constraints is not None and constraints.max_length \
                and constraints.min_length == constraints.max_length:
            return ArrowType("fixedsizebinary", {"byteWidth": int(constraints.max_length)}), None
        if lowered in _SCALARS:
            return _SCALARS[lowered], None
        self.losses.record(LossKind.INFERRED, LOSS_ANY_AS_JSON,
                           f"{pointer!r} has the untyped or unknown type {scalar!r}; written as a JSON string "
                           "(utf8, arrow.json)", pointer)
        return ArrowType("utf8"), "arrow.json"

    def _decimal(self, constraints: Optional[Constraints], extras: Mapping[str, Any], pointer: str) -> ArrowType:
        """A ``decimal128``: the source's precision and scale, the scale from ``multipleOf``, else synthesized."""
        recorded = extras.get("arrow_decimal") if isinstance(extras.get("arrow_decimal"), Mapping) else None
        if recorded and recorded.get("precision") is not None:
            return ArrowType("decimal", {"precision": int(recorded["precision"]),
                                         "scale": int(recorded.get("scale") or 0),
                                         "bitWidth": int(recorded.get("bitWidth") or 128)})
        from .sql_ddl_emitter import _scale_of  # noqa: PLC0415 - one rule for multipleOf → scale

        scale = _scale_of(constraints.multiple_of) if constraints is not None and constraints.multiple_of else None
        if scale is None:
            scale = _DECIMAL_SCALE
            self.losses.record(LossKind.INFERRED, LOSS_DECIMAL_SYNTHESIZED,
                               f"{pointer!r} is a decimal with no precision or scale; written decimal128"
                               f"({_DECIMAL_PRECISION}, {_DECIMAL_SCALE})", pointer)
        return ArrowType("decimal", {"precision": _DECIMAL_PRECISION, "scale": scale, "bitWidth": 128})


def _bag(value: Any) -> Dict[str, Any]:
    """A list element's or map key's / value's extras bag, its declared type filed as ``arrow_type``.

    The Arrow importer keeps what a wrapped type declared (``type``) and records (``arrow_decimal`` …)
    in a bag on the wrapper, since a canonical reference has nowhere else to hold it.
    """
    if not isinstance(value, Mapping):
        return {}
    bag = dict(value)
    if isinstance(bag.get("type"), Mapping):
        bag.setdefault("arrow_type", bag["type"])
    return bag


def _json_field(name: str, nullable: bool) -> ArrowField:
    """A ``utf8`` column holding JSON text (the canonical ``arrow.json`` extension)."""
    return ArrowField(name=name, type=ArrowType("utf8"), nullable=nullable,
                      metadata=((ARROW_EXTENSION_NAME_KEY, "arrow.json"), (ARROW_EXTENSION_METADATA_KEY, "")))


def _referenced(api: CanonicalApi) -> Set[str]:
    """Every type key some record field (or map / union / alias) refers to."""
    seen: Set[str] = set()
    by_name = {t.name: t.key for t in api.types}

    def visit(ref: Optional[TypeRef]) -> None:
        while ref is not None and ref.item is not None:
            ref = ref.item
        if ref is not None and ref.name:
            seen.add(ref.name if ref.name in {t.key for t in api.types} else by_name.get(ref.name, ref.name))

    for type_ in api.types:
        for member in type_.fields:
            visit(member.type)
        visit(type_.key_type)
        visit(type_.value_type)
        visit(type_.aliased)
        for member in type_.union_members:
            seen.add(member if member in {t.key for t in api.types} else by_name.get(member, member))
    return seen


def _roots(api: CanonicalApi, options: ArrowEmitOptions) -> List[Type]:
    """The records written as tables."""
    records = [t for t in api.types if t.kind is TypeKind.RECORD]
    if options.table:
        chosen = [t for t in records if options.table in (t.key, t.name)]
        if not chosen:
            raise EmitOptionsError(f"No record named {options.table!r} to export as the table.")
        return chosen[:1]
    arrow_root = ((api.extras or {}).get("arrow") or {}).get("root")
    if arrow_root and any(t.key == arrow_root for t in records):
        return [t for t in records if t.key == arrow_root]
    referenced = _referenced(api)
    roots = [t for t in records if t.key not in referenced]
    return roots or records


def project_arrow_tables(api: CanonicalApi, options: Optional[ArrowEmitOptions] = None,
                         losses: Optional[LossTracker] = None) -> List[ArrowTable]:
    """Project a canonical model onto Arrow tables (the typed projection MFX-36.2 also serializes).

    Args:
        api: The canonical model.
        options: The emit options (``table`` picks one record).
        losses: Where the projection records what it makes up or approximates.

    Returns:
        One :class:`ArrowTable` per root record (or the chosen one).

    Raises:
        EmitPreconditionError: When the model has no record type.
        EmitOptionsError: When ``table`` names no record.
    """
    options = options or ArrowEmitOptions()
    losses = losses if losses is not None else LossTracker()
    if not any(t.kind is TypeKind.RECORD for t in api.types):
        raise EmitPreconditionError("An Arrow schema is a table of columns, and this model has no record type.")
    projector = _Projector(api, losses)
    arrow_extras = (api.extras or {}).get("arrow") or {}
    tables: List[ArrowTable] = []
    for root in _roots(api, options):
        metadata: Dict[str, str] = {}
        if root.key == arrow_extras.get("root"):
            metadata.update({str(k): str(v) for k, v in (arrow_extras.get("schema_metadata") or {}).items()})
        if root.name != _DEFAULT_ROOT_NAME:
            metadata.setdefault("name", root.name)
        if root.description and not any(k in metadata for k in ("description", "comment", "doc")):
            metadata["description"] = root.description
        schema = ArrowSchema(fields=projector.record_fields(root, ()), metadata=tuple(metadata.items()))
        tables.append(ArrowTable(name=root.name, key=root.key, schema=schema))
    return tables


# ===========================================================================
# Serialization
# ===========================================================================


def _type_json(type_: ArrowType) -> Dict[str, Any]:
    return {"name": type_.name, **dict(type_.parameters)}


def _field_json(field_: ArrowField, ids: List[int]) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"name": field_.name, "nullable": field_.nullable, "type": _type_json(field_.type),
                             "children": [_field_json(child, ids) for child in field_.children]}
    if field_.dictionary is not None:
        ids[0] += 1
        entry["dictionary"] = {"id": ids[0], "indexType": _type_json(field_.dictionary.index_type),
                               "isOrdered": field_.dictionary.is_ordered}
    if field_.metadata:
        entry["metadata"] = [{"key": k, "value": v} for k, v in field_.metadata]
    return entry


def arrow_schema_json(schema: ArrowSchema) -> Dict[str, Any]:
    """An :class:`~app.arrow_schema.ArrowSchema` as the Arrow JSON integration form."""
    ids = [0]
    body: Dict[str, Any] = {"fields": [_field_json(f, ids) for f in schema.fields]}
    if schema.metadata:
        body["metadata"] = [{"key": k, "value": v} for k, v in schema.metadata]
    return {"schema": body}


def parquet_message(schema: ArrowSchema) -> str:
    """The Parquet message the schema becomes, as pyarrow's Parquet writer derives it.

    Raises:
        ValueError: When Parquet cannot hold the schema (a union, a ``null`` column …).
    """
    import pyarrow.parquet as pq  # noqa: PLC0415 - pyarrow is heavy; only exports need it

    from .arrow_ipc import schema_to_pyarrow  # noqa: PLC0415

    buffer = io.BytesIO()
    try:
        pq.write_table(schema_to_pyarrow(schema).empty_table(), buffer)
    except Exception as exc:  # noqa: BLE001 - pyarrow raises ArrowNotImplementedError / ArrowInvalid
        raise ValueError(str(exc)) from exc
    buffer.seek(0)
    text = str(pq.read_metadata(buffer).schema)
    lines = [line.replace(" field_id=-1", "") for line in text.splitlines() if not line.startswith("<pyarrow")]
    return "\n".join(lines).strip() + "\n"


def check_emitted_arrow(emit_result: EmitResult) -> List[Dict[str, str]]:
    """The export gate's check: every emitted Arrow schema parses, pyarrow constructs it, and it imports.

    The ``.parquet.txt`` messages are derived by pyarrow itself and are not re-checked.

    Args:
        emit_result: The emitter's output.

    Returns:
        ``{"rule", "message", "file"}`` per problem; empty when every schema passes.
    """
    from .arrow_ipc import schema_to_pyarrow  # noqa: PLC0415
    from .arrow_parser import parse_arrow  # noqa: PLC0415
    from .arrow_schema import ArrowParseError  # noqa: PLC0415
    from .import_source import ImportSourceError, get_import_source  # noqa: PLC0415

    problems: List[Dict[str, str]] = _warehouse_problems(emit_result)
    schemas = [f for f in emit_result.files if f.path.endswith(SCHEMA_SUFFIX)]
    if not schemas:
        if any(f.path.endswith((BIGQUERY_SUFFIX, SPARK_SUFFIX)) for f in emit_result.files):
            return problems
        return [{"rule": "schema", "message": "The Arrow export wrote no `.arrow.json`, `.bigquery.json` or "
                 "`.spark.ddl` schema.", "file": ""}]
    for emitted in schemas:
        text = str(emitted.content)
        try:
            document = parse_arrow(text, source_label=emitted.path)
        except (ArrowParseError, ValueError) as exc:
            problems.append({"rule": "arrow.schema", "message": str(exc), "file": emitted.path})
            continue
        try:
            schema_to_pyarrow(document.schema)
        except Exception as exc:  # noqa: BLE001 - pyarrow raises its own error types
            problems.append({"rule": "pyarrow", "message": f"pyarrow cannot construct the schema: {exc}",
                             "file": emitted.path})
            continue
        source = get_import_source(ARROW_FORMAT_KEY)
        if source is None:
            continue
        try:
            source.normalize(source.parse(text, source_label=emitted.path), include_raw=False)
        except (ImportSourceError, ValueError) as exc:
            problems.append({"rule": "reimport", "message": f"the schema does not import: {exc}",
                             "file": emitted.path})
    return problems


def _warehouse_problems(emit_result: EmitResult) -> List[Dict[str, str]]:
    """The BigQuery and Spark checks (MFX-36.2): BigQuery's documented schema rules, Spark's DDL grammar."""
    from .warehouse_schemas import bigquery_schema_problems, spark_ddl_problems  # noqa: PLC0415

    problems: List[Dict[str, str]] = []
    for emitted in emit_result.files:
        text = str(emitted.content)
        if emitted.path.endswith(BIGQUERY_SUFFIX):
            try:
                document = json.loads(text)
            except ValueError as exc:
                problems.append({"rule": "json", "message": str(exc), "file": emitted.path})
                continue
            # A bundle is an object of table name → schema; a per-table file is the schema itself.
            schemas = document.items() if isinstance(document, dict) else [("", document)]
            for table, fields in schemas:
                problems += [{"rule": p["rule"], "message": f"{table + ': ' if table else ''}{p['path']}: "
                              f"{p['message']}", "file": emitted.path} for p in bigquery_schema_problems(fields)]
        elif emitted.path.endswith(SPARK_SUFFIX):
            problems += [{"rule": p["rule"], "message": f"{p['path']}: {p['message']}", "file": emitted.path}
                         for p in spark_ddl_problems(text)]
    return problems


def _file_stem(name: str) -> str:
    return _FILE_SAFE.sub("-", name).strip("-") or "schema"


# ===========================================================================
# Fidelity
# ===========================================================================


class ArrowFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for Arrow / Parquet export (the full rule set is MFX-36.4).

    Operations, channels and services are ``DROP``ped with the critical types-only advisory. Each loss
    the projection recorded (a recursive record or untyped value written as JSON, an enum as a
    dictionary column, a synthesized decimal precision) is filed under its construct, and a constraint
    has no Arrow form and is dropped.

    What a re-import of the export reads back is **measured**, not guessed: the pack emits the export,
    imports it through the Arrow import source as the round-trip matrix does (an Arrow schema is one
    table, so the bundle's first schema), and files each difference under the type it concerns with
    the reason — a nested record is read back under the path of the column that holds it, a second
    table lives in its own file, an enumeration is a dictionary column with no list of values.
    """

    target_label = "Apache Arrow"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these options (invalid options fall back to the defaults)."""
        try:
            self._options = ArrowEmitOptions.model_validate(dict(options))
        except (ValidationError, ValueError):
            self._options = ArrowEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Project and round-trip once, index what changed by construct, then walk the model."""
        options = getattr(self, "_options", None) or ArrowEmitOptions()
        losses = LossTracker()
        self._tables: List[ArrowTable] = []
        try:
            self._tables = project_arrow_tables(api, options, losses)
        except (EmitPreconditionError, EmitOptionsError, ValueError):
            pass
        if options.output != "arrow":
            # BigQuery and Spark are read by no importer, so there is no round trip to measure; what the
            # serializer approximates is filed under each table instead.
            _warehouse_files(self._tables, options, losses)
        self._filed: Dict[str, List[Loss]] = {}
        for loss in losses.records():
            self._filed.setdefault(loss.pointer or "", []).append(loss)
        self._changes, self._added = (_measure_round_trip(api, options) if options.output == "arrow" else ({}, {}))
        self._reached = _reached_types(api, self._tables)
        return super().evaluate(api)

    def _filed_verdicts(self, construct: str) -> List[FidelityVerdict]:
        verdicts = []
        for loss in getattr(self, "_filed", {}).get(construct, []):
            if loss.subject in SYNTH_SUBJECTS:
                verdicts.append(FidelityVerdict.synth(message=loss.detail, severity=LossinessSeverity.INFO,
                                                      target_mapping=loss.subject))
            else:
                verdicts.append(FidelityVerdict.approx(message=loss.detail, severity=LossinessSeverity.INFO,
                                                       target_mapping=loss.subject))
        return verdicts

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        verdicts: List[FidelityVerdict] = []
        advisory = types_only_advisory(api, target_label=self.target_label, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            verdicts.append(advisory)
        if self._changes.get("") is not None:
            verdicts.append(FidelityVerdict.approx(
                message=f"{self.target_label} keeps the table's name (schema metadata `name`) and its metadata; "
                "the title, version, description and servers of the API are not kept",
                severity=LossinessSeverity.INFO, target_mapping="identity → schema metadata"))
        return verdicts

    def _mode(self) -> str:
        """The output mode the report is for: ``arrow``, ``bigquery`` or ``spark`` (``iceberg`` in its pack)."""
        return (getattr(self, "_options", None) or ArrowEmitOptions()).output

    def _union_verdict(self, type_: Type) -> FidelityVerdict:
        """A union is ``APPROX`` in every mode — MFX-36.4: kept as a dense union by Arrow, flattened elsewhere."""
        return FidelityVerdict.approx(message=_UNION_MESSAGES[self._mode()].format(key=type_.key),
                                      severity=LossinessSeverity.INFO,
                                      target_mapping=f"union → {_UNION_MAPPINGS[self._mode()]}")

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """An enumeration is ``APPROX`` (its column keeps no list of allowed values); else the profile's verdict."""
        if type_.kind is TypeKind.ENUM:
            return FidelityVerdict.approx(message=_ENUM_MESSAGES[self._mode()].format(key=type_.key),
                                          severity=LossinessSeverity.INFO,
                                          target_mapping="enum → string column (no allowed values)")
        return super().type_verdict(type_)

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        # A BigQuery / Spark approximation is filed under its table, and replaces the table's OK.
        filed = self._filed_verdicts(type_.key)
        if filed:
            return filed
        change = self._changes.get(type_.key)
        if change is DiffChangeKind.REMOVED:
            dropped = FidelityVerdict.drop(message=self._removed_reason(type_), severity=LossinessSeverity.INFO,
                                           target_mapping="type → re-keyed or not kept")
            # A union or enumeration also says how it is written (MFX-36.4), not only that it is re-keyed.
            if type_.kind in (TypeKind.UNION, TypeKind.ENUM):
                return [dropped, self.type_verdict(type_)]
            return [dropped]
        if change is DiffChangeKind.CHANGED:
            return [FidelityVerdict.approx(
                message=f"{type_.kind.value} {type_.key!r} reads back from the Arrow schema changed (types, "
                "nullability and constraints follow Arrow's columns)",
                severity=LossinessSeverity.INFO, target_mapping="type → Arrow columns")]
        return [self.type_verdict(type_)]

    def _removed_reason(self, type_: Type) -> str:
        """Why a type does not read back under its key."""
        roots = [t.key for t in self._tables]
        if type_.key in roots:
            return (f"{type_.key!r} is written as its own table ({_file_stem(type_.name)}{SCHEMA_SUFFIX}); an Arrow "
                    "schema is one table, so importing the export reads its first schema only")
        if type_.key not in self._reached:
            return f"{type_.kind.value} {type_.key!r} is not reached from any table, so no column holds it"
        if type_.kind is TypeKind.ENUM:
            return (f"enum {type_.key!r} is a dictionary-encoded utf8 column; Arrow keeps no list of values, so it "
                    "reads back as a string")
        if type_.kind is TypeKind.ALIAS:
            return f"alias {type_.key!r} is written as the type it names; Arrow has no type aliases"
        if type_.kind is TypeKind.SCALAR:
            return f"scalar {type_.key!r} is written as its Arrow type; Arrow has no named scalars"
        return (f"{type_.kind.value} {type_.key!r} is nested in the column that holds it; Arrow types have no names, "
                "so a re-import names it after that column's path")

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        return [(key, FidelityVerdict.synth(
            message=f"a re-import names the nested {entity} {key!r} after the path of the column that holds it",
            severity=LossinessSeverity.INFO, target_mapping="type named by column path"))
            for key, entity in sorted(getattr(self, "_added", {}).items())]

    def field_verdicts(self, member: CanonicalField) -> List[FidelityVerdict]:
        return [*super().field_verdicts(member), *self._filed_verdicts(member.key)]

    def _constraints_verdict(self, member: CanonicalField) -> Optional[FidelityVerdict]:
        """Arrow has no validation constraints: they are dropped (not demoted to documentation)."""
        if member.constraints is None:
            return None
        facets = set(member.constraints.model_dump(exclude={"extras", "format"}, exclude_none=True))
        facets -= _kept_facets(member)
        if not facets:
            return None
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no validation constraints; {', '.join(sorted(facets))} of "
            f"{member.key!r} are dropped",
            severity=LossinessSeverity.INFO,
            target_mapping="constraints → dropped",
        )

    def _field_identity_verdict(self, member: CanonicalField) -> Optional[FidelityVerdict]:
        """A field number is the column's position: the projection orders columns by it, so it is kept."""
        return None

    def service_verdicts(self, service: Any) -> List[FidelityVerdict]:
        return [FidelityVerdict.drop(message=f"{self.target_label} is types-only; the service {service.key!r} has "
                                     "no schema", target_mapping="service → dropped (types-only export)")]


#: MFX-36.4 (#4320): how each mode writes a union and an enumeration, for the fidelity report.
_UNION_MESSAGES = {
    "arrow": "union {key!r} is a dense Arrow union of its members; Parquet has no union type, so a table that "
    "holds it gets no Parquet message",
    "bigquery": "BigQuery has no union type; {key!r} is flattened to a RECORD with one NULLABLE field per member, "
    "so exactly-one-of is not enforced",
    "spark": "Spark has no union type; {key!r} is flattened to a STRUCT with one optional field per member, so "
    "exactly-one-of is not enforced",
    "iceberg": "Iceberg has no union type; {key!r} is flattened to a struct with one optional field per member, "
    "so exactly-one-of is not enforced",
}
_UNION_MAPPINGS = {"arrow": "dense union", "bigquery": "RECORD of optional members",
                   "spark": "STRUCT of optional members", "iceberg": "struct of optional members"}
_ENUM_MESSAGES = {
    "arrow": "enum {key!r} is a dictionary-encoded utf8 column; Arrow keeps no list of allowed values",
    "bigquery": "enum {key!r} is a STRING column; BigQuery keeps no list of allowed values",
    "spark": "enum {key!r} is a STRING column; Spark keeps no list of allowed values",
    "iceberg": "enum {key!r} is a string column; Iceberg keeps no list of allowed values",
}


def _kept_facets(member: CanonicalField) -> Set[str]:
    """The constraint facets the column's own type keeps: a fixed width or a fixed list size."""
    constraints = member.constraints
    if constraints is None:
        return set()
    declared = (member.extras or {}).get("arrow_type")
    declared_name = declared.get("name") if isinstance(declared, Mapping) else None
    kept: Set[str] = set()
    scalar = (member.type.name or "").lower()
    if constraints.max_length and constraints.min_length == constraints.max_length and (
            declared_name == "fixedsizebinary" or (declared_name is None and scalar in ("bytes", "binary", "byte"))):
        kept |= {"min_length", "max_length"}
    if member.type.item is not None and constraints.max_items and declared_name == "fixedsizelist" \
            and constraints.min_items == constraints.max_items:
        kept |= {"min_items", "max_items"}
    return kept


def _reached_types(api: CanonicalApi, tables: Sequence[ArrowTable]) -> Set[str]:
    """Every type key a table's columns reach (the tables' records and all they hold)."""
    by_key = {t.key: t for t in api.types}
    by_name = {t.name: t for t in api.types}
    reached: Set[str] = set()
    pending = [t.key for t in tables]
    while pending:
        key = pending.pop()
        type_ = by_key.get(key) or by_name.get(key)
        if type_ is None or type_.key in reached:
            continue
        reached.add(type_.key)
        refs = [m.type for m in type_.fields] + [type_.key_type, type_.value_type, type_.aliased]
        for ref in refs:
            while ref is not None and ref.item is not None:
                ref = ref.item
            if ref is not None and ref.name:
                pending.append(ref.name)
        pending.extend(type_.union_members)
    return reached


def _measure_round_trip(api: CanonicalApi,
                        options: ArrowEmitOptions) -> Tuple[Dict[str, DiffChangeKind], Dict[str, str]]:
    """What a re-import of the export changes, by type key (``""`` for the root), and the keys it adds.

    The export is imported as the round-trip matrix imports a bundle (its first file is the root). An
    export that cannot be made or read back yields no measurement; the gate reports that instead.
    """
    from .import_source import ImportSourceError, canonical_diff, get_import_source  # noqa: PLC0415
    from .roundtrip_matrix import reimport_emitted  # noqa: PLC0415 - the matrix's own reader

    source = get_import_source(ARROW_FORMAT_KEY)
    if source is None:
        return {}, {}
    try:
        result = ArrowEmitter().emit(api, opts=options.model_copy(update={"parquet": False}))
        back = reimport_emitted(source, result, multi_file=True)
    except (EmitPreconditionError, EmitOptionsError, ImportSourceError, ArrowParseError, ValueError):
        # ArrowParseError covers a runtime without pyarrow (ArrowIpcError): no measurement, not a crash.
        return {}, {}
    diff = canonical_diff(api, back)
    changes: Dict[str, DiffChangeKind] = {}
    added: Dict[str, str] = {}
    for entry in diff.entries:
        if entry.entity not in ("type", "root"):
            continue
        if entry.change is DiffChangeKind.ADDED:
            added[entry.key] = "type"
        else:
            changes[entry.key] = entry.change
    return changes, added


# ===========================================================================
# Emitter
# ===========================================================================


class ArrowEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as Arrow schemas (JSON integration form) and Parquet messages."""

    key = ARROW_FORMAT_KEY
    requires_source = ("record-type",)
    format = ARROW_FORMAT_KEY
    label = "Apache Arrow / Parquet"
    description = (
        "Export the types as Apache Arrow schemas (the JSON integration form) and the Parquet message each "
        "becomes: one table per root record, with nested structs, lists, maps and unions, and logical types "
        "for dates, timestamps, decimals and UUIDs."
    )
    icon = "database"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = True
    options_model = ArrowEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """Nested types, unions and nullability; no operations, events, constraints or field identity."""
        return CapabilityProfile(operations=False, events=False, unions=True, nullability=True, constraints=False,
                                 field_identity=False)

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        """Return the Arrow rules."""
        return ArrowFidelityRulePack

    def emit(self, api: CanonicalApi, *, opts: Optional[Union[ArrowEmitOptions, EmitOptions]] = None) -> EmitResult:
        """Emit one ``<table>.arrow.json`` (and ``<table>.parquet.txt``) per table.

        Every schema is constructed by pyarrow before it is written.

        Raises:
            EmitOptionsError: When ``opts`` is invalid or ``table`` names no record.
            EmitPreconditionError: When the model has no record type.
            ValueError: When pyarrow cannot construct a schema (an internal invariant).
        """
        from .arrow_ipc import schema_to_pyarrow  # noqa: PLC0415

        options = _coerce_options(opts)
        losses = LossTracker()
        tracker = ProvenanceTracker()
        tables = project_arrow_tables(api, options, losses)
        if (api.services or api.channels) and any(op for s in api.services for op in s.operations):
            losses.record(LossKind.NA, LOSS_SERVICES, "Arrow schemas describe tables; operations and channels are "
                          "not written", "")
        if options.output != "arrow":
            for table in tables:
                schema_to_pyarrow(table.schema)  # the same projection pyarrow builds
            files = _warehouse_files(tables, options, losses)
            return EmitResult(files=files, media_type=files[0].media_type if len(files) == 1 else "application/zip",
                              provenance=[], losses=losses.records())
        files: List[EmittedFile] = []
        stems: Set[str] = set()
        for table in tables:
            schema_to_pyarrow(table.schema)  # pyarrow must construct it
            stem = _file_stem(table.name)
            while stem in stems:
                stem += "_"
            stems.add(stem)
            indent = options.indent or None
            files.append(EmittedFile(path=f"{stem}{SCHEMA_SUFFIX}",
                                     content=json.dumps(arrow_schema_json(table.schema), indent=indent,
                                                        ensure_ascii=False) + "\n",
                                     media_type=JSON_MEDIA_TYPE))
            tracker.record(f"/{stem}", Provenance.SOURCE)
            if options.parquet:
                try:
                    files.append(EmittedFile(path=f"{stem}{PARQUET_SUFFIX}", content=parquet_message(table.schema),
                                             media_type=PARQUET_MEDIA_TYPE))
                except ValueError as exc:
                    losses.record(LossKind.NA, LOSS_PARQUET_UNSUPPORTED,
                                  f"table {table.name!r} has no Parquet form ({exc}); only its Arrow schema is written",
                                  table.key)
        files.sort(key=lambda f: f.path)
        return EmitResult(files=files, media_type=JSON_MEDIA_TYPE if len(files) == 1 else "application/zip",
                          provenance=tracker.records(), losses=losses.records())


def _warehouse_files(tables: Sequence[ArrowTable], options: ArrowEmitOptions,
                     losses: LossTracker) -> List[EmittedFile]:
    """The BigQuery or Spark files for the tables: one per table, or one bundle (MFX-36.2)."""
    from .warehouse_schemas import bigquery_fields, spark_ddl  # noqa: PLC0415

    indent = options.indent or None
    bigquery = options.output == "bigquery"
    serialized: List[Tuple[str, Any]] = []
    for table in tables:
        if bigquery:
            serialized.append((table.name, bigquery_fields(table.schema, losses=losses, pointer=table.key)))
        else:
            serialized.append((table.name, spark_ddl(table.schema, losses=losses, pointer=table.key)))
    media = JSON_MEDIA_TYPE if bigquery else PARQUET_MEDIA_TYPE
    if options.bundle:
        if bigquery:
            content = json.dumps(dict(serialized), indent=indent, ensure_ascii=False) + "\n"
            return [EmittedFile(path=BIGQUERY_BUNDLE, content=content, media_type=media)]
        body = "".join(f"-- {name}\n{ddl}\n" for name, ddl in serialized)
        return [EmittedFile(path=SPARK_BUNDLE, content=body, media_type=media)]
    files: List[EmittedFile] = []
    stems: Set[str] = set()
    for name, value in serialized:
        stem = _file_stem(name)
        while stem in stems:
            stem += "_"
        stems.add(stem)
        if bigquery:
            files.append(EmittedFile(path=f"{stem}{BIGQUERY_SUFFIX}", media_type=media,
                                     content=json.dumps(value, indent=indent, ensure_ascii=False) + "\n"))
        else:
            files.append(EmittedFile(path=f"{stem}{SPARK_SUFFIX}", content=value + "\n", media_type=media))
    return sorted(files, key=lambda f: f.path)


def _coerce_options(opts: Optional[Union[ArrowEmitOptions, EmitOptions]]) -> ArrowEmitOptions:
    if isinstance(opts, ArrowEmitOptions):
        return opts
    try:
        return ArrowEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid Arrow emit options: {exc}") from exc
