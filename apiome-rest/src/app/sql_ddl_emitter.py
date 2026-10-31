"""SQL DDL emitter: canonical types → ``CREATE TABLE`` (ANSI, PostgreSQL, MySQL) — MFX-35.1 (#4311).

The inverse of :class:`app.sql_ddl_import_source.SqlDdlImportSource` (FMT-5.6): a **relational
projection** of the model's types into one SQL script, ``<Name>.sql``.

Projection
----------
* **Tables.** Every record type becomes a table, named after the type.
* **Columns.** A scalar field is a typed column (:data:`_SCALAR_FAMILIES` → the dialect's type).
  ``nullable=False`` (the canonical "required") is ``NOT NULL``. A ``maxLength`` sizes a ``VARCHAR``;
  the other constraints become ``CHECK`` clauses (bounds, lengths, a pattern where the dialect has a
  regular-expression operator); an enum is a ``CREATE TYPE … AS ENUM`` (PostgreSQL), an inline
  ``ENUM(…)`` (MySQL) or a ``CHECK (… IN …)`` (ANSI).
* **Nested objects** (``nested``): ``json`` (default) writes a field whose type is a record — or a
  union or a map — as one ``JSONB`` / ``JSON`` column. ``tables`` writes it as a foreign key to that
  record's table instead, giving every table a key (its declared one, a non-null ``id`` field, or a
  synthesized ``id``) and a **junction table** for a list of records.
* **Arrays** of scalars: a native array on PostgreSQL (``TEXT[]``), a JSON column otherwise — or,
  with ``nested=tables``, a child table of ``(owner_id, position, value)``.
* **Identifiers** are mangled deterministically: ``snake_case``, letters/digits/``_`` only, a leading
  digit prefixed, cut to the dialect's length limit (with a stable hash suffix), deduplicated with
  ``_2``, ``_3`` … and quoted when they are a reserved word.

Every decision the projection *makes up* — a synthesized key, a junction or child table, a renamed
identifier, a synthesized decimal precision — is recorded as a loss and reported ``SYNTH`` by
:class:`SqlDdlFidelityRulePack`, so a reader can see exactly what the script invented.

An item imported **from SQL** keeps its declared primary keys, unique keys and foreign keys, and —
when written in the dialect it was read in — its column types, defaults and checks verbatim.

Every script is parsed back with **sqlglot** in the target dialect before it is returned, so a
script that does not parse cannot ship.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Mapping, Optional, Set, Tuple, Union

import sqlglot
from pydantic import Field, ValidationError

from .canonical_model import ApiParadigm, CanonicalApi, CanonicalField, Constraints, Type, TypeKind, TypeRef
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
from .lossiness import LossinessReport, LossinessSeverity

__all__ = [
    "SQL_DDL_FORMAT_KEY",
    "SqlDdlEmitOptions",
    "SqlDdlEmitter",
    "SqlDdlFidelityRulePack",
    "parse_sql_script",
]

#: Registry key and format — the SQL DDL importer's key, so the round-trip matrix pairs them.
SQL_DDL_FORMAT_KEY = "sql-ddl"
OUTPUT_MEDIA_TYPE = "application/sql"

#: The dialects the emitter writes (the importer's :class:`app.sql_ddl_dialects.SqlDialect` spellings).
Dialect = Literal["postgres", "mysql", "ansi"]
#: sqlglot's name for each dialect (``None``: sqlglot's generic, standard-SQL dialect).
_SQLGLOT_DIALECT: Dict[str, Optional[str]] = {"postgres": "postgres", "mysql": "mysql", "ansi": None}
#: The longest identifier each dialect keeps (PostgreSQL truncates at 63 bytes; MySQL refuses past 64).
_MAX_IDENTIFIER: Dict[str, int] = {"postgres": 63, "mysql": 64, "ansi": 128}

#: Loss subjects — the vocabulary the fidelity pack files under each construct.
LOSS_KEY_SYNTHESIZED = "sql-key-synthesized"
LOSS_KEY_INFERRED = "sql-key-inferred"
LOSS_JUNCTION_TABLE = "sql-junction-table"
LOSS_CHILD_TABLE = "sql-child-table"
LOSS_IDENTIFIER_RENAMED = "sql-identifier-renamed"
LOSS_AS_JSON = "sql-as-json"
LOSS_PRECISION = "sql-precision-synthesized"
LOSS_TYPE_APPROX = "sql-type-approximated"
LOSS_CONSTRAINT_DROPPED = "sql-constraint-dropped"
LOSS_UNKNOWN_SCALAR = "sql-unknown-scalar"
LOSS_CYCLE = "sql-alias-cycle"
LOSS_DIALECT_CLAUSE = "sql-dialect-clause-dropped"
LOSS_SERVICES = "services-dropped"
#: Subjects that are a decision the projection made up (``SYNTH``), not a degradation.
SYNTH_SUBJECTS = frozenset({
    LOSS_KEY_SYNTHESIZED, LOSS_KEY_INFERRED, LOSS_JUNCTION_TABLE, LOSS_CHILD_TABLE,
    LOSS_IDENTIFIER_RENAMED, LOSS_PRECISION,
})
#: Subjects that lose a rule or a value outright (``DROP``); the rest are ``APPROX``.
DROP_SUBJECTS = frozenset({LOSS_CONSTRAINT_DROPPED, LOSS_DIALECT_CLAUSE, LOSS_CYCLE})

#: Canonical scalar name (lower-cased) → its SQL family. Spellings follow
#: :data:`app.canonical_json_schema.CANONICAL_SCALAR_SCHEMAS` (the names the normalizers emit).
_SCALAR_FAMILIES: Dict[str, str] = {
    **{name: "text" for name in ("string", "str", "text", "char", "id", "uri", "url", "email", "hostname",
                                  "ipv4", "ipv6", "xml")},
    **{name: "uuid" for name in ("uuid", "guid")},
    "date": "date",
    "time": "time",
    **{name: "timestamp" for name in ("datetime", "date-time", "timestamp", "instant")},
    "duration": "duration",
    **{name: "bytes" for name in ("bytes", "binary", "blob")},
    **{name: "int8" for name in ("byte", "sbyte", "i8", "int8", "uint8")},
    **{name: "int16" for name in ("short", "i16", "int16", "uint16")},
    **{name: "int32" for name in ("i32", "int32", "uint32", "fixed32", "sfixed32", "sint32", "int")},
    **{name: "int64" for name in ("i64", "int64", "uint64", "fixed64", "sfixed64", "sint64", "long", "bigint",
                                   "integer")},
    **{name: "float" for name in ("float", "f32")},
    **{name: "double" for name in ("double", "f64", "number")},
    "decimal": "decimal",
    "numeric": "decimal",
    "money": "decimal",
    **{name: "boolean" for name in ("boolean", "bool")},
    **{name: "json" for name in ("any", "object", "json", "map", "value", "unknown", "variant")},
}

#: SQL family → column type, per dialect. ``{n}`` is a length; decimals are sized separately.
_FAMILY_TYPES: Dict[str, Dict[str, str]] = {
    "postgres": {
        "text": "TEXT", "uuid": "UUID", "date": "DATE", "time": "TIME", "timestamp": "TIMESTAMPTZ",
        "duration": "INTERVAL", "bytes": "BYTEA", "int8": "SMALLINT", "int16": "SMALLINT",
        "int32": "INTEGER", "int64": "BIGINT", "float": "REAL", "double": "DOUBLE PRECISION",
        "boolean": "BOOLEAN", "json": "JSONB",
    },
    "mysql": {
        "text": "TEXT", "uuid": "CHAR(36)", "date": "DATE", "time": "TIME(6)", "timestamp": "DATETIME(6)",
        "duration": "VARCHAR(64)", "bytes": "LONGBLOB", "int8": "TINYINT", "int16": "SMALLINT",
        "int32": "INT", "int64": "BIGINT", "float": "FLOAT", "double": "DOUBLE", "boolean": "BOOLEAN",
        "json": "JSON",
    },
    "ansi": {
        "text": "CLOB", "uuid": "CHAR(36)", "date": "DATE", "time": "TIME", "timestamp": "TIMESTAMP WITH TIME ZONE",
        "duration": "VARCHAR(64)", "bytes": "BLOB", "int8": "SMALLINT", "int16": "SMALLINT",
        "int32": "INTEGER", "int64": "BIGINT", "float": "REAL", "double": "DOUBLE PRECISION",
        "boolean": "BOOLEAN", "json": "JSON",
    },
}

#: Families a dialect writes as an approximation (and why), reported ``APPROX``.
_APPROX_FAMILIES: Dict[Tuple[str, str], str] = {
    ("mysql", "uuid"): "MySQL has no UUID type; written CHAR(36)",
    ("ansi", "uuid"): "standard SQL has no UUID type; written CHAR(36)",
    ("mysql", "timestamp"): "MySQL DATETIME keeps no time zone",
    ("mysql", "duration"): "MySQL has no interval type; written as text",
    ("ansi", "duration"): "a standard INTERVAL needs a fixed qualifier; written as text",
    ("postgres", "int8"): "PostgreSQL has no 1-byte integer; written SMALLINT",
    ("ansi", "int8"): "standard SQL has no 1-byte integer; written SMALLINT",
}

#: Words quoted when an identifier collides with them (the SQL:2016 reserved words most often hit by
#: API field names, plus MySQL's, plus words sqlglot reads as keywords — ``type``, ``name`` …). Quoting is
#: the dialect's: ``"…"`` or MySQL's backtick, and harmless where the database would have accepted the word.
_RESERVED = frozenset("""
all alter and any array as asc between both by case cast check collate column constraint create cross
current current_date current_time current_timestamp current_user default delete desc distinct do drop else
end except exists false fetch for foreign from full grant group having in index inner insert intersect into
is join key leading left like limit natural not null offset on only or order outer overlaps primary
references right select session_user some table then to trailing true union unique user using values when
where window with interval range rank row rows value time timestamp date year month day hour minute second
schema status type name role option comment
""".split())

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_UNSAFE = re.compile(r"[^a-z0-9_]+")


class SqlDdlEmitOptions(EmitOptions):
    """Per-target options for :class:`SqlDdlEmitter`."""

    dialect: Dialect = Field(
        default="postgres",
        description="SQL dialect: `postgres` (default), `mysql`, or `ansi` (standard SQL).",
    )
    nested: Literal["json", "tables"] = Field(
        default="json",
        description="`json` (default) writes a nested object, union or map as one JSON column; `tables` "
        "writes a nested object as a foreign key to its table (with synthesized keys) and a list of "
        "records or values as a junction or child table.",
    )
    schema_name: Optional[str] = Field(
        default=None,
        description="Qualify every table with this schema and create it first (`CREATE SCHEMA`).",
    )

    def model_post_init(self, __context: Any) -> None:  # noqa: D401 - pydantic hook
        """Reject a schema name that is not a plain SQL identifier."""
        if self.schema_name is not None and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", self.schema_name):
            raise ValueError("schema_name must be a plain identifier (letters, digits, _)")


def parse_sql_script(script: str, dialect: str) -> List[Any]:
    """Parse ``script`` with sqlglot in ``dialect``; raise ``ValueError`` when it does not parse.

    Args:
        script: The SQL text.
        dialect: ``postgres``, ``mysql`` or ``ansi``.

    Returns:
        The parsed statements (never empty for a script with DDL).
    """
    try:
        statements = sqlglot.parse(script, read=_SQLGLOT_DIALECT[dialect])
    except sqlglot.errors.ParseError as exc:
        raise ValueError(f"The emitted {dialect} DDL does not parse: {exc}") from exc
    return [statement for statement in statements if statement is not None]


# ===========================================================================
# Identifiers
# ===========================================================================


def snake_case(name: str) -> str:
    """``OrderLine`` / ``orderLine`` / ``order-line`` → ``order_line`` (letters, digits, ``_``)."""
    text = _CAMEL.sub("_", name.strip()).lower()
    text = _UNSAFE.sub("_", text).strip("_")
    text = re.sub(r"_+", "_", text)
    return text or "x"


class _Namer:
    """Deterministic identifier mangling within one namespace (the schema, or one table)."""

    def __init__(self, dialect: str, prefix: str) -> None:
        self._dialect = dialect
        self._prefix = prefix
        self._taken: Set[str] = set()

    def name(self, source: str) -> str:
        """The unique SQL identifier for ``source`` in this namespace."""
        base = snake_case(source)
        if base[0].isdigit():
            base = f"{self._prefix}_{base}"
        limit = _MAX_IDENTIFIER[self._dialect]
        if len(base) > limit:
            digest = hashlib.sha256(base.encode()).hexdigest()[:8]
            base = f"{base[: limit - 9]}_{digest}"
        candidate, counter = base, 2
        while candidate in self._taken:
            suffix = f"_{counter}"
            candidate = f"{base[: limit - len(suffix)]}{suffix}"
            counter += 1
        self._taken.add(candidate)
        return candidate


# ===========================================================================
# The projection
# ===========================================================================


@dataclass
class _Column:
    """One column of a table being written."""

    name: str
    sql_type: str
    not_null: bool = False
    default: Optional[str] = None
    checks: List[str] = field(default_factory=list)
    primary: bool = False
    identity: bool = False


@dataclass
class _Table:
    """One table being written."""

    key: str  # the canonical type key (or a synthesized key for a junction / child table)
    name: str
    columns: List[_Column] = field(default_factory=list)
    primary_key: List[str] = field(default_factory=list)
    unique: List[List[str]] = field(default_factory=list)
    checks: List[str] = field(default_factory=list)
    foreign_keys: List[Tuple[List[str], str, List[str]]] = field(default_factory=list)


class _SqlDdlWriter:
    """Builds one SQL script from a canonical model (single use)."""

    def __init__(self, api: CanonicalApi, options: SqlDdlEmitOptions) -> None:
        self._api = api
        self._options = options
        self._dialect = options.dialect
        self.losses = LossTracker()
        self.tracker = ProvenanceTracker()
        self._types: Dict[str, Type] = {t.key: t for t in api.types}
        self._records = [t for t in api.types if t.kind is TypeKind.RECORD]
        self._table_namer = _Namer(self._dialect, "t")
        self._table_names: Dict[str, str] = {}
        self._enum_types: Dict[str, str] = {}  # enum type key → PostgreSQL type name
        self._tables: List[_Table] = []
        self._keys: Dict[str, Tuple[str, str]] = {}  # record key → (key column, its SQL type)
        source = (api.extras or {}).get("sql_ddl") or {}
        self._same_dialect = api.format == SQL_DDL_FORMAT_KEY and source.get("dialect") == self._dialect

    # -- helpers ------------------------------------------------------------

    def _q(self, identifier: str) -> str:
        """Quote ``identifier`` when it is a reserved word."""
        if identifier not in _RESERVED:
            return identifier
        return f"`{identifier}`" if self._dialect == "mysql" else f'"{identifier}"'

    def _qualified(self, table: str) -> str:
        schema = self._options.schema_name
        return f"{self._q(schema)}.{self._q(table)}" if schema else self._q(table)

    def _loss(self, kind: LossKind, subject: str, detail: str, pointer: str) -> None:
        self.losses.record(kind, subject, detail, pointer=pointer)

    def _resolve(self, ref: TypeRef, depth: int = 0) -> TypeRef:
        """Follow aliases to the reference a column is typed by."""
        if ref.item is not None or ref.name is None or depth > 16:
            return ref
        target = self._types.get(ref.name)
        if target is not None and target.kind is TypeKind.ALIAS and target.aliased is not None:
            resolved = self._resolve(target.aliased, depth + 1)
            return TypeRef(name=resolved.name, item=resolved.item, nullable=ref.nullable and resolved.nullable)
        return ref

    # -- the script ---------------------------------------------------------

    def render(self) -> str:
        """The whole script, ending in a newline."""
        if not self._records:
            raise EmitPreconditionError(
                "SQL DDL export lays out record types as tables, and this model has none (only enums, "
                "scalars or operations)."
            )
        advisory = types_only_advisory(self._api, target_label="SQL DDL", keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            self._loss(LossKind.NA, LOSS_SERVICES, advisory.message, "")
        for record in self._records:
            name = self._table_namer.name(record.name)
            self._table_names[record.key] = name
            if name != record.key:
                # Compared with the *key*: a namespaced type (`commerce.customer`) loses its namespace too.
                self._loss(LossKind.INFERRED, LOSS_IDENTIFIER_RENAMED,
                           f"type {record.key!r} is written as the table {name!r}"
                           + (f", without its namespace {record.namespace!r}" if record.namespace else ""),
                           record.key)
        self._plan_keys()
        for record in self._records:
            self._tables.append(self._table(record))
        statements: List[str] = []
        if self._options.schema_name:
            statements.append(f"CREATE SCHEMA {self._q(self._options.schema_name)};")
        statements += self._enum_statements()
        statements += [self._create_table(table) for table in self._tables]
        statements += self._foreign_key_statements()
        title = self._api.title or self._api.identity.name or "schema"
        header = f"-- {title}: SQL DDL ({self._dialect}), generated by Apiome.\n"
        script = header + "\n\n".join(statements) + "\n"
        parse_sql_script(script, self._dialect)
        return script

    # -- keys ---------------------------------------------------------------

    def _plan_keys(self) -> None:
        """Choose each table's key column — needed only to point foreign keys at it (``nested=tables``)."""
        if self._options.nested != "tables":
            return
        for record in self._records:
            declared = ((record.extras or {}).get("sql_key") or {}).get("primary_key") or {}
            columns = declared.get("columns") or []
            names = self._column_names(record)
            if len(columns) == 1:
                member = next((f for f in record.fields if f.name == columns[0]), None)
                if member is not None:
                    self._keys[record.key] = (names[member.key], self._key_type(member))
                    continue
            identity = next((f for f in record.fields if f.name.lower() == "id" and f.type.nullable is False
                             and self._is_scalar_column(f)), None)
            if identity is not None and not columns:
                self._keys[record.key] = (names[identity.key], self._key_type(identity))
                self._loss(LossKind.INFERRED, LOSS_KEY_INFERRED,
                           f"{record.name!r} is keyed by its non-null `id` field", record.key)
                continue
            synthesized = self._synthesized_key_name(record)
            self._keys[record.key] = (synthesized, "BIGINT")
            self._loss(LossKind.INFERRED, LOSS_KEY_SYNTHESIZED,
                       f"{record.name!r} has no single-column key; a generated `{synthesized}` BIGINT key is added",
                       record.key)

    def _is_scalar_column(self, member: CanonicalField) -> bool:
        """Whether ``member`` is written as one scalar column (not a list, record, union, map or enum)."""
        ref = self._resolve(member.type)
        target = self._types.get(ref.name or "")
        return ref.item is None and (target is None or target.kind is TypeKind.SCALAR)

    @staticmethod
    def _synthesized_key_name(record: Type) -> str:
        """``id``, or ``row_id`` (``row_id_2`` …) when a field already takes the name."""
        taken = {snake_case(f.name) for f in record.fields}
        name, counter = ("id" if "id" not in taken else "row_id"), 2
        while name in taken:
            name, counter = f"row_id_{counter}", counter + 1
        return name

    def _key_type(self, member: CanonicalField) -> str:
        sql_type, _ = self._scalar_type(member, self._resolve(member.type).name or "string", pointer=member.key)
        return sql_type

    def _column_names(self, record: Type) -> Dict[str, str]:
        """Field key → the column name :meth:`_table` will give it (same namer, same order)."""
        namer = _Namer(self._dialect, "c")
        key = self._keys.get(record.key)
        if key is not None and key[0] not in {snake_case(f.name) for f in record.fields}:
            namer.name(key[0])
        return {member.key: namer.name(member.name) for member in record.fields}

    # -- tables -------------------------------------------------------------

    def _table(self, record: Type) -> _Table:
        table = _Table(key=record.key, name=self._table_names[record.key])
        namer = _Namer(self._dialect, "c")
        key = self._keys.get(record.key)
        synthesized_key = key is not None and key[0] not in {snake_case(f.name) for f in record.fields}
        if synthesized_key:
            namer.name(key[0])
            table.columns.append(_Column(name=key[0], sql_type="BIGINT", not_null=True, identity=True))
            table.primary_key = [key[0]]
        self._field_columns: List[str] = []
        for member in record.fields:
            self._add_field(table, record, member, namer)
        self._apply_declared_keys(table, record)
        if key is not None and not table.primary_key:
            table.primary_key = [key[0]]
        if self._same_dialect:
            for check in (record.extras or {}).get("sql_checks") or []:
                if isinstance(check, Mapping) and check.get("expression"):
                    table.checks.append(str(check["expression"]))
        return table

    def _apply_declared_keys(self, table: _Table, record: Type) -> None:
        """An imported SQL table's primary and unique keys (column names mangled the same way)."""
        declared = (record.extras or {}).get("sql_key") or {}
        by_source = {member.name: name for member, name in zip(record.fields, self._field_columns)}
        primary = [by_source.get(c) for c in (declared.get("primary_key") or {}).get("columns") or []]
        if primary and all(primary):
            table.primary_key = primary
        for unique in declared.get("unique") or []:
            cols = [by_source.get(c) for c in unique.get("columns") or []]
            if cols and all(cols):
                table.unique.append(cols)

    def _add_field(self, table: _Table, record: Type, member: CanonicalField, namer: _Namer) -> None:
        column_name = namer.name(member.name)
        self._field_columns.append(column_name)
        if column_name != member.name:
            self._loss(LossKind.INFERRED, LOSS_IDENTIFIER_RENAMED,
                       f"column for {member.name!r} is named {column_name!r}", member.key)
        ref = self._resolve(member.type)
        not_null = member.type.nullable is False
        if ref.item is not None:
            self._add_list(table, record, member, column_name, ref, not_null)
            return
        target = self._types.get(ref.name or "")
        if target is not None and target.kind in (TypeKind.RECORD, TypeKind.UNION, TypeKind.MAP):
            if target.kind is TypeKind.RECORD and self._options.nested == "tables":
                self._add_reference(table, member, column_name, target, not_null)
                return
            self._loss(LossKind.NA, LOSS_AS_JSON,
                       f"{member.key!r} ({target.kind.value} {target.name!r}) is written as one JSON column",
                       member.key)
            table.columns.append(_Column(name=column_name, sql_type=_FAMILY_TYPES[self._dialect]["json"],
                                         not_null=not_null))
            return
        if target is not None and target.kind is TypeKind.ENUM:
            table.columns.append(self._enum_column(member, column_name, target, not_null))
            return
        sql_type, checks = self._scalar_type(member, ref.name or "string", pointer=member.key)
        if self._same_dialect and isinstance((member.extras or {}).get("sql_data_type"), str):
            sql_type = member.extras["sql_data_type"]
        column = _Column(name=column_name, sql_type=sql_type, not_null=not_null, checks=checks)
        column.default = self._default(member)
        if self._same_dialect:
            column.checks += [str(c) for c in (member.extras or {}).get("sql_checks") or [] if isinstance(c, str)]
        table.columns.append(column)
        self._record_relationship(table, member, column_name)

    def _record_relationship(self, table: _Table, member: CanonicalField, column_name: str) -> None:
        """An imported SQL column's foreign key, pointed at the target table's mangled names."""
        for relationship in (member.extras or {}).get("sql_relationship") or []:
            if not isinstance(relationship, Mapping):
                continue
            target_key = relationship.get("table") or relationship.get("to_table") or relationship.get("target")
            target_column = relationship.get("column") or relationship.get("to_column")
            to = relationship.get("to")
            if (not target_key or not target_column) and isinstance(to, str) and "." in to:
                target_key, target_column = to.rsplit(".", 1)
            target_name = self._table_names.get(str(target_key)) or next(
                (name for key, name in self._table_names.items()
                 if key.rsplit(".", 1)[-1] == str(target_key).rsplit(".", 1)[-1]), None)
            if target_name and target_column:
                table.foreign_keys.append(([column_name], target_name, [snake_case(str(target_column))]))

    def _add_reference(self, table: _Table, member: CanonicalField, column_name: str, target: Type,
                       not_null: bool) -> None:
        """A to-one nested record as a foreign-key column (``nested=tables``)."""
        key_column, key_type = self._keys[target.key]
        name = column_name if column_name.endswith("_id") else f"{column_name}_id"
        taken = {snake_case(f.name) for f in self._types[table.key].fields} | {c.name for c in table.columns}
        if name != column_name and name in taken:
            # A field already takes `<field>_id`: keep the reference distinct, deterministically.
            name = f"{column_name}_ref_id"
        table.columns.append(_Column(name=name, sql_type=key_type, not_null=not_null))
        table.foreign_keys.append(([name], self._table_names[target.key], [key_column]))
        self._loss(LossKind.INFERRED, LOSS_KEY_SYNTHESIZED,
                   f"{member.key!r} is written as the foreign key {name!r} to {self._table_names[target.key]!r}",
                   member.key)

    def _add_list(self, table: _Table, record: Type, member: CanonicalField, column_name: str, ref: TypeRef,
                  not_null: bool) -> None:
        """A list: a native array, a JSON column, or a junction / child table."""
        item = self._resolve(ref.item) if ref.item is not None else TypeRef(name="string")
        target = self._types.get(item.name or "")
        is_record = target is not None and target.kind is TypeKind.RECORD
        if self._options.nested == "tables" and item.item is None:
            self._child_table(record, member, item, target if is_record else None)
            return
        scalar_like = item.item is None and (target is None or target.kind is TypeKind.ENUM)
        if self._dialect == "postgres" and scalar_like:
            if target is not None:
                base = self._enum_type_name(target)
            else:
                base, _ = self._scalar_type(member, item.name or "string", pointer=member.key, constraints=False)
            table.columns.append(_Column(name=column_name, sql_type=f"{base}[]", not_null=not_null))
            self._drop_item_constraints(member)
            return
        self._loss(LossKind.NA, LOSS_AS_JSON, f"the list {member.key!r} is written as one JSON column", member.key)
        table.columns.append(_Column(name=column_name, sql_type=_FAMILY_TYPES[self._dialect]["json"],
                                     not_null=not_null))

    def _child_table(self, record: Type, member: CanonicalField, item: TypeRef, target: Optional[Type]) -> None:
        """A list as its own table: a junction to the item's table, or ``(owner_id, position, value)``."""
        owner_key, owner_type = self._keys[record.key]
        owner = self._table_names[record.key]
        name = self._table_namer.name(f"{owner}_{snake_case(member.name)}")
        child = _Table(key=f"{member.key}#table", name=name)
        owner_column = f"{owner}_id"
        child.columns.append(_Column(name=owner_column, sql_type=owner_type, not_null=True))
        child.foreign_keys.append(([owner_column], owner, [owner_key]))
        if target is not None:
            item_key, item_type = self._keys[target.key]
            item_table = self._table_names[target.key]
            item_column = f"{item_table}_id" if item_table != owner else f"{item_table}_ref_id"
            child.columns.append(_Column(name=item_column, sql_type=item_type, not_null=True))
            child.columns.append(_Column(name="position", sql_type="INTEGER", not_null=True))
            child.foreign_keys.append(([item_column], item_table, [item_key]))
            child.primary_key = [owner_column, "position"]
            self._loss(LossKind.INFERRED, LOSS_JUNCTION_TABLE,
                       f"the list {member.key!r} of {target.name!r} is written as the junction table {name!r}",
                       member.key)
        else:
            child.columns.append(_Column(name="position", sql_type="INTEGER", not_null=True))
            enum = self._types.get(item.name or "")
            if enum is not None and enum.kind is TypeKind.ENUM:
                value = self._enum_column(member, "value", enum, True)
            else:
                sql_type, checks = self._scalar_type(member, item.name or "string", pointer=member.key,
                                                     constraints=False)
                value = _Column(name="value", sql_type=sql_type, not_null=item.nullable is False, checks=checks)
            child.columns.append(value)
            child.primary_key = [owner_column, "position"]
            self._loss(LossKind.INFERRED, LOSS_CHILD_TABLE,
                       f"the list {member.key!r} is written as the child table {name!r}", member.key)
        self._drop_item_constraints(member)
        self._tables.append(child)

    def _drop_item_constraints(self, member: CanonicalField) -> None:
        c = member.constraints
        if c is not None and (c.min_items is not None or c.max_items is not None or c.unique_items):
            self._loss(LossKind.NA, LOSS_CONSTRAINT_DROPPED,
                       f"the item counts / uniqueness of the list {member.key!r} have no SQL column rule", member.key)

    # -- enums --------------------------------------------------------------

    @staticmethod
    def _enum_values(enum: Type) -> List[str]:
        """The enum's labels: a member's string wire value, else its name.

        A numeric wire value (an Avro or protobuf ordinal) is a position, not a label, so the member's
        name is what a row stores — which is also what a default (``'ACTIVE'``) names.
        """
        return [str(v.value) if isinstance(v.value, str) else v.name for v in enum.enum_values]

    def _enum_type_name(self, enum: Type) -> str:
        if enum.key not in self._enum_types:
            self._enum_types[enum.key] = self._table_namer.name(enum.name)
        return self._qualified(self._enum_types[enum.key])

    def _enum_column(self, member: CanonicalField, name: str, enum: Type, not_null: bool) -> _Column:
        values = self._enum_values(enum)
        literal = ", ".join(_literal(v) for v in values)
        if self._dialect == "postgres":
            return _Column(name=name, sql_type=self._enum_type_name(enum), not_null=not_null,
                           default=self._default(member))
        if self._dialect == "mysql":
            return _Column(name=name, sql_type=f"ENUM({literal})", not_null=not_null, default=self._default(member))
        width = max([len(v) for v in values] or [1])
        return _Column(name=name, sql_type=f"VARCHAR({width})", not_null=not_null,
                       checks=[f"{self._q(name)} IN ({literal})"], default=self._default(member))

    def _enum_statements(self) -> List[str]:
        """``CREATE TYPE … AS ENUM`` for every enum a PostgreSQL column uses."""
        statements = []
        for key, name in self._enum_types.items():
            values = ", ".join(_literal(v) for v in self._enum_values(self._types[key]))
            statements.append(f"CREATE TYPE {self._qualified(name)} AS ENUM ({values});")
        return statements

    # -- scalars and constraints -------------------------------------------

    def _scalar_type(self, member: CanonicalField, scalar: str, *, pointer: str,
                     constraints: bool = True) -> Tuple[str, List[str]]:
        """The column type of a scalar field, and the ``CHECK`` expressions its constraints become."""
        family = _SCALAR_FAMILIES.get(scalar.lower())
        c = member.constraints if constraints else None
        if family is None:
            family = "text"
            self._loss(LossKind.NA, LOSS_UNKNOWN_SCALAR, f"{scalar!r} has no SQL type; written as text", pointer)
        reason = _APPROX_FAMILIES.get((self._dialect, family))
        if reason:
            self._loss(LossKind.INFERRED, LOSS_TYPE_APPROX, f"{pointer!r}: {reason}", pointer)
        if family == "text" and c is not None and c.max_length:
            sql_type = f"VARCHAR({int(c.max_length)})"
        elif family == "text" and self._dialect == "mysql" and member.key and self._is_keyish(member):
            sql_type = "VARCHAR(255)"
        elif family == "decimal":
            sql_type = self._decimal_type(c, pointer)
        else:
            sql_type = _FAMILY_TYPES[self._dialect][family]
        return sql_type, self._checks(member, c, family) if c is not None else []

    @staticmethod
    def _is_keyish(member: CanonicalField) -> bool:
        # MySQL cannot key a TEXT column; a field that is likely a key (named id or *_id) gets VARCHAR(255).
        name = member.name.lower()
        return name == "id" or name.endswith("_id") or name.endswith("id") and len(name) > 2

    def _decimal_type(self, c: Optional[Constraints], pointer: str) -> str:
        scale = _scale_of(c.multiple_of) if c is not None and c.multiple_of else None
        if self._dialect == "postgres" and scale is None:
            return "NUMERIC"
        if scale is None:
            scale = 10
            self._loss(LossKind.INFERRED, LOSS_PRECISION,
                       f"{pointer!r} is a decimal with no scale; written DECIMAL(38, 10)", pointer)
        return f"NUMERIC(38, {scale})" if self._dialect == "postgres" else f"DECIMAL(38, {scale})"

    def _checks(self, member: CanonicalField, c: Constraints, family: str) -> List[str]:
        name = self._q(snake_case(member.name))
        checks: List[str] = []
        for value, op in ((c.minimum, ">="), (c.maximum, "<="), (c.exclusive_minimum, ">"),
                          (c.exclusive_maximum, "<")):
            if value is not None and family in ("int8", "int16", "int32", "int64", "float", "double", "decimal"):
                checks.append(f"{name} {op} {_number(value)}")
        length = "CHAR_LENGTH" if self._dialect != "ansi" else "CHARACTER_LENGTH"
        if c.min_length is not None and family == "text":
            checks.append(f"{length}({name}) >= {int(c.min_length)}")
        if c.enum:
            literal = ", ".join(_literal(v) for v in c.enum)
            checks.append(f"{name} IN ({literal})")
        if c.pattern:
            if self._dialect == "postgres":
                checks.append(f"{name} ~ {_literal(c.pattern)}")
            elif self._dialect == "mysql":
                checks.append(f"REGEXP_LIKE({name}, {_literal(c.pattern)})")
            else:
                self._loss(LossKind.NA, LOSS_CONSTRAINT_DROPPED,
                           f"standard SQL has no regular-expression check; the pattern of {member.key!r} is dropped",
                           member.key)
        if c.multiple_of and family != "decimal":
            self._loss(LossKind.NA, LOSS_CONSTRAINT_DROPPED,
                       f"the multipleOf of {member.key!r} has no SQL column rule", member.key)
        return checks

    def _default(self, member: CanonicalField) -> Optional[str]:
        """A literal default (portable), or the imported expression in its own dialect."""
        expression = (member.extras or {}).get("sql_default_expression")
        if isinstance(expression, str) and expression:
            if self._same_dialect:
                return expression
            self._loss(LossKind.NA, LOSS_DIALECT_CLAUSE,
                       f"the default {expression!r} of {member.key!r} is written for another dialect; dropped",
                       member.key)
            return None
        if member.default is None or isinstance(member.default, (dict, list)):
            return None
        if isinstance(member.default, bool):
            return "TRUE" if member.default else "FALSE"
        if isinstance(member.default, (int, float)):
            return _number(member.default)
        return _literal(str(member.default))

    # -- rendering ----------------------------------------------------------

    def _create_table(self, table: _Table) -> str:
        lines: List[str] = []
        for column in table.columns:
            parts = [self._q(column.name), column.sql_type]
            if column.identity:
                parts.append({"postgres": "GENERATED BY DEFAULT AS IDENTITY", "mysql": "AUTO_INCREMENT",
                              "ansi": "GENERATED BY DEFAULT AS IDENTITY"}[self._dialect])
            if column.not_null:
                parts.append("NOT NULL")
            if column.default is not None:
                parts.append(f"DEFAULT {column.default}")
            for check in column.checks:
                parts.append(f"CHECK ({check})")
            lines.append("  " + " ".join(parts))
        if table.primary_key:
            lines.append(f"  PRIMARY KEY ({', '.join(self._q(c) for c in table.primary_key)})")
        for unique in table.unique:
            lines.append(f"  UNIQUE ({', '.join(self._q(c) for c in unique)})")
        for check in table.checks:
            lines.append(f"  CHECK ({check})")
        return f"CREATE TABLE {self._qualified(table.name)} (\n" + ",\n".join(lines) + "\n);"

    def _foreign_key_statements(self) -> List[str]:
        """Foreign keys last, as ``ALTER TABLE``, so table order never matters (cycles included)."""
        statements = []
        for table in self._tables:
            for index, (columns, target, target_columns) in enumerate(table.foreign_keys, start=1):
                name = f"fk_{table.name}_{index}"[: _MAX_IDENTIFIER[self._dialect]]
                statements.append(
                    f"ALTER TABLE {self._qualified(table.name)} ADD CONSTRAINT {self._q(name)} FOREIGN KEY "
                    f"({', '.join(self._q(c) for c in columns)}) REFERENCES {self._qualified(target)} "
                    f"({', '.join(self._q(c) for c in target_columns)});"
                )
        return statements


def _literal(value: Any) -> str:
    """A single-quoted SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _number(value: Any) -> str:
    """A numeric literal without a trailing ``.0`` for whole numbers."""
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)


def _scale_of(multiple_of: float) -> Optional[int]:
    """The decimal places a ``multipleOf`` of ``10^-k`` implies (``0.01`` → 2), else ``None``."""
    text = f"{multiple_of:.12f}".rstrip("0")
    if multiple_of <= 0 or multiple_of >= 1 or "." not in text:
        return None
    digits = text.split(".")[1]
    return len(digits) if set(digits[:-1]) <= {"0"} and digits[-1] == "1" else None


# ===========================================================================
# Fidelity
# ===========================================================================


class SqlDdlFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for SQL DDL export — MFX-35.1.

    The pack builds the script once for the report's options (:meth:`apply_options`) and files each
    loss the writer recorded under the type or field it came from:

    * ``SYNTH`` — a synthesized or inferred key, a junction or child table, a renamed identifier, a
      synthesized decimal precision: decisions the projection made up, deterministic for the same
      model and options;
    * ``APPROX`` — a nested object, union, map or list written as one JSON column; a type the dialect
      approximates (``CHAR(36)`` for a UUID, ``DATETIME`` with no time zone);
    * ``DROP`` — a constraint with no SQL column rule, an imported dialect clause written for another
      dialect; operations and channels (the types-only advisory).
    """

    target_label = "SQL DDL"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these options (invalid options fall back to the defaults)."""
        try:
            self._options = SqlDdlEmitOptions.model_validate(dict(options))
        except (ValidationError, ValueError):
            self._options = SqlDdlEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Write the script once, index its losses by construct, then walk the model."""
        options = getattr(self, "_options", None) or SqlDdlEmitOptions()
        writer = _SqlDdlWriter(api, options)
        try:
            writer.render()
        except ValueError:
            pass
        self._writer = writer
        self._schema = options.schema_name
        self._filed: Dict[str, List[Loss]] = {}
        for loss in writer.losses.records():
            self._filed.setdefault(loss.pointer or "", []).append(loss)
        return super().evaluate(api)

    def _reimport_key(self, name: str) -> str:
        """The key the SQL DDL reader gives a table or type named ``name``."""
        return f"{self._schema}.{name}" if self._schema else name

    def _verdicts(self, construct: str) -> List[FidelityVerdict]:
        verdicts = []
        for loss in getattr(self, "_filed", {}).get(construct, []):
            if loss.subject in SYNTH_SUBJECTS:
                verdicts.append(FidelityVerdict.synth(message=loss.detail, severity=LossinessSeverity.INFO,
                                                      target_mapping=loss.subject))
            elif loss.subject in DROP_SUBJECTS:
                verdicts.append(FidelityVerdict.drop(message=loss.detail, severity=LossinessSeverity.WARN,
                                                     target_mapping=loss.subject))
            elif loss.subject != LOSS_SERVICES:
                verdicts.append(FidelityVerdict.approx(message=loss.detail, severity=LossinessSeverity.INFO,
                                                       target_mapping=loss.subject))
        return verdicts

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The types-only advisory, and the document identity a script has no field for."""
        verdicts: List[FidelityVerdict] = []
        advisory = types_only_advisory(api, target_label=self.target_label, keep_in="OpenAPI or AsyncAPI")
        if advisory is not None:
            verdicts.append(advisory)
        if api.title or api.identity.name or api.version or api.description:
            verdicts.append(FidelityVerdict.approx(
                message="a SQL script has no title, version or description; the header comment names the API, "
                "and a re-import names the item after its file",
                severity=LossinessSeverity.INFO,
                target_mapping="document identity → comment",
            ))
        return verdicts

    def type_verdicts(self, type_: Type) -> List[FidelityVerdict]:
        """What became of a type: a table (renamed or not), a PostgreSQL enum type, or nothing of its own."""
        writer = getattr(self, "_writer", None)
        filed = [v for v in self._verdicts(type_.key) if v.target_mapping != LOSS_IDENTIFIER_RENAMED]
        if writer is None:
            return filed or [self.type_verdict(type_)]
        if type_.kind is TypeKind.RECORD:
            name = writer._table_names.get(type_.key)
            if name is not None and self._reimport_key(name) != type_.key:
                return [FidelityVerdict.drop(
                    message=f"type {type_.key!r} is written as the table {name!r} and reads back under that name",
                    severity=LossinessSeverity.INFO, target_mapping=f"{type_.key} → table {name}"), *filed]
            if not filed and any(self._verdicts(member.key) for member in type_.fields):
                # A column of the table was renamed, re-typed or re-shaped: the table is not carried as is.
                return [FidelityVerdict.approx(
                    message=f"the table for {type_.key!r} changes some of its columns (see its fields)",
                    severity=LossinessSeverity.INFO, target_mapping="record → table (columns changed)")]
            return filed or [self.type_verdict(type_)]
        if type_.kind is TypeKind.ENUM and type_.key in writer._enum_types:
            name = writer._enum_types[type_.key]
            if self._reimport_key(name) != type_.key:
                return [FidelityVerdict.drop(
                    message=f"enum {type_.key!r} is written as the type {name!r} and reads back under that name",
                    severity=LossinessSeverity.INFO, target_mapping=f"{type_.key} → enum type {name}"), *filed]
            return filed or [self.type_verdict(type_)]
        what = {TypeKind.ENUM: "its values are written into each column that uses it",
                TypeKind.UNION: "a column of it is JSON", TypeKind.MAP: "a column of it is JSON"}.get(
                    type_.kind, "a column of it takes the type it names")
        return [FidelityVerdict.drop(
            message=f"{type_.kind.value} {type_.key!r} has no table or type of its own in SQL; {what}",
            severity=LossinessSeverity.INFO, target_mapping=f"{type_.kind.value} → no SQL object"), *filed]

    def synthesized_verdicts(self, api: CanonicalApi) -> List[Tuple[str, FidelityVerdict]]:
        """Every table and enum type the script declares under a key the source does not have."""
        writer = getattr(self, "_writer", None)
        if writer is None:
            return []
        source_keys = {t.key for t in api.types}
        created: List[Tuple[str, FidelityVerdict]] = []
        for table in writer._tables:
            key = self._reimport_key(table.name)
            if key in source_keys:
                continue
            origin = "a junction or child table" if table.key.endswith("#table") else f"the table for {table.key!r}"
            created.append((key, FidelityVerdict.synth(message=f"{key!r} is {origin}", severity=LossinessSeverity.INFO,
                                                       target_mapping="sql table")))
        for type_key, name in writer._enum_types.items():
            key = self._reimport_key(name)
            if key not in source_keys:
                created.append((key, FidelityVerdict.synth(message=f"{key!r} is the enum type for {type_key!r}",
                                                           severity=LossinessSeverity.INFO,
                                                           target_mapping="sql enum type")))
        return created

    def field_verdicts(self, member: CanonicalField) -> List[FidelityVerdict]:
        return [*super().field_verdicts(member), *self._verdicts(member.key)]

    def service_verdicts(self, service) -> List[FidelityVerdict]:
        """A service has no table: SQL DDL is types-only."""
        return [FidelityVerdict.drop(
            message=f"{self.target_label} is types-only; the service {service.key!r} has no table",
            target_mapping="service → dropped (types-only export)",
        )]

    def operation_verdict(self, operation) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only; the {operation.kind.value} operation has no table",
            target_mapping="operation → dropped (types-only export)",
        )

    def channel_verdict(self, channel) -> FidelityVerdict:
        return FidelityVerdict.drop(
            message=f"{self.target_label} is types-only; the event channel has no table",
            target_mapping="channel → dropped (types-only export)",
        )


# ===========================================================================
# Emitter
# ===========================================================================


class SqlDdlEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as one SQL DDL script."""

    key = SQL_DDL_FORMAT_KEY
    requires_source = ("record-type",)
    format = SQL_DDL_FORMAT_KEY
    label = "SQL DDL"
    description = (
        "Export the types as SQL CREATE TABLE statements for PostgreSQL, MySQL or standard SQL: typed "
        "columns, NOT NULL and CHECK constraints, enums, and nested objects as JSON columns or tables."
    )
    icon = "database"
    paradigm = ApiParadigm.DATA_SCHEMA
    multi_file = False
    options_model = SqlDdlEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=False,
            events=False,
            unions=False,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return SqlDdlFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[SqlDdlEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as one SQL script, parsed back with sqlglot before it is returned.

        Raises:
            EmitOptionsError: When ``opts`` is invalid.
            EmitPreconditionError: When the model has no record type.
            ValueError: When the script does not parse in its dialect (an internal invariant).
        """
        options = _coerce_options(opts)
        writer = _SqlDdlWriter(api, options)
        script = writer.render()
        for table in writer._tables:
            writer.tracker.record(f"/{table.name}", Provenance.SOURCE if not table.key.endswith("#table")
                                  else Provenance.INFERRED)
        base = re.sub(r"[^A-Za-z0-9_.-]+", "-", api.title or api.identity.name or "schema").strip("-") or "schema"
        return EmitResult(
            files=[EmittedFile(path=f"{base}.sql", content=script, media_type=OUTPUT_MEDIA_TYPE)],
            media_type=OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


def _coerce_options(opts: Optional[Union[SqlDdlEmitOptions, EmitOptions]]) -> SqlDdlEmitOptions:
    if isinstance(opts, SqlDdlEmitOptions):
        return opts
    try:
        return SqlDdlEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid SQL DDL emit options: {exc}") from exc
