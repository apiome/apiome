"""DBML and Prisma serializers of the SQL DDL relational projection — MFX-35.2 (#4312).

:class:`app.sql_ddl_emitter._SqlDdlWriter` lays a canonical model out as tables once — columns,
keys, enums, foreign keys, junction and child tables, and the losses each decision makes. The SQL
serializer lives with it; this module holds the other two (option ``output``):

* :func:`render_dbml` — the tables as DBML (``Table``, ``Enum``, ``Ref``, ``indexes`` and ``checks``
  blocks) — the language dbdiagram.io and dbdocs read. Column types are the dialect's SQL types, so a
  DBML file says exactly what the DDL would create.
* :func:`render_prisma` — the tables as a ``schema.prisma``: one ``model`` per table (PascalCase, with
  ``@@map`` back to the table name), Prisma scalar types with ``@db.*`` native types, ``@id`` /
  ``@@id``, ``@unique`` / ``@@unique``, ``@default``, an ``enum`` per enum type, and both sides of
  every foreign key as a named ``@relation``.

What a language cannot say is recorded on the projection's loss tracker, so the fidelity report
lists it: Prisma has no ``CHECK`` constraint, no interval type and no nullable list; DBML cannot hold
a backtick inside an expression.

Each output is checked by its reference tool — ``@dbml/core`` and ``prisma validate`` — in the export
validation step (:mod:`app.db_schema_validation`), not here: the serializers stay pure functions.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .emitter import LossKind

if TYPE_CHECKING:  # pragma: no cover - typing only (the emitter imports this module lazily)
    from .sql_ddl_emitter import _Column, _SqlDdlWriter, _Table

__all__ = ["render_dbml", "render_prisma"]

_PLAIN_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _loss_subjects() -> Tuple[str, str]:
    """The emitter's serializer loss subjects (imported late: the emitter imports this module)."""
    from .sql_ddl_emitter import LOSS_SERIALIZER_APPROX, LOSS_SERIALIZER_DROPPED

    return LOSS_SERIALIZER_DROPPED, LOSS_SERIALIZER_APPROX


def _one_line(text: str) -> str:
    """``text`` on one line (a header comment must not run into the next line)."""
    return " ".join(text.split())


def _number(value: float) -> str:
    """A numeric literal without a trailing ``.0`` for whole numbers."""
    number = float(value)
    return str(int(number)) if number.is_integer() else repr(number)


def _enum_keys(tables: Iterable["_Table"]) -> List[str]:
    """Every enum a column holds, in first-use order."""
    keys: List[str] = []
    for table in tables:
        for column in table.columns:
            if column.enum_key and column.enum_key not in keys:
                keys.append(column.enum_key)
    return keys


def _fk_name(projection: "_SqlDdlWriter", table: "_Table", index: int) -> str:
    """The foreign key's constraint name — the one the SQL script gives it."""
    from .sql_ddl_emitter import _MAX_IDENTIFIER

    return f"fk_{table.name}_{index}"[: _MAX_IDENTIFIER[projection.dialect]]


# ===========================================================================
# DBML
# ===========================================================================

#: Words DBML reads as syntax; an identifier spelled like one is quoted.
_DBML_KEYWORDS = frozenset(
    "table ref enum project note indexes checks tablegroup tablepartial records as pk null not unique "
    "increment default primary key".split()
)
#: A type DBML takes bare: a word, optionally sized (``varchar(64)``).
_DBML_BARE_TYPE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\(\d+\))?")
#: A dialect-quoted identifier inside a SQL expression (MySQL's backticks).
_BACKTICK_IDENTIFIER = re.compile(r"`([A-Za-z0-9_]+)`")
_DBML_DATABASE_TYPE = {"postgres": "PostgreSQL", "mysql": "MySQL"}


def _dbml_id(name: str) -> str:
    """``name`` as a DBML identifier, double-quoted when it is not a plain word or is a keyword."""
    if _PLAIN_IDENTIFIER.fullmatch(name) and name.lower() not in _DBML_KEYWORDS:
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dbml_string(text: str) -> str:
    """A single-quoted DBML string."""
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"


def _dbml_expression(expression: str) -> Optional[str]:
    """A SQL expression as a DBML backtick expression, or ``None`` when it cannot be one.

    MySQL quotes identifiers in backticks, which a DBML expression cannot contain; those become
    standard double quotes. Any backtick left (inside a literal) makes the expression unwritable.
    """
    text = _BACKTICK_IDENTIFIER.sub(r'"\1"', expression)
    return None if "`" in text else f"`{text}`"


class _DbmlWriter:
    """Writes one projection as DBML (single use)."""

    def __init__(self, projection: "_SqlDdlWriter") -> None:
        self._p = projection
        self._schema = projection.options.schema_name
        self._dropped, _ = _loss_subjects()

    def _qualified(self, name: str) -> str:
        return f"{_dbml_id(self._schema)}.{_dbml_id(name)}" if self._schema else _dbml_id(name)

    def _drop(self, detail: str, pointer: str) -> None:
        self._p.record_loss(LossKind.NA, self._dropped, detail, pointer)

    def render(self) -> str:
        p = self._p
        blocks: List[str] = []
        database_type = _DBML_DATABASE_TYPE.get(p.dialect)
        if database_type:
            blocks.append(f"Project {_dbml_id(p.title)} {{\n  database_type: {_dbml_string(database_type)}\n}}")
        for enum_key in _enum_keys(p.tables):
            values = "\n".join(f"  {_dbml_id_always(label)}" for label in p.enum_labels(enum_key))
            blocks.append(f"Enum {self._qualified(p.enum_name(enum_key))} {{\n{values}\n}}")
        blocks += [self._table(table) for table in p.tables]
        refs = self._refs()
        if refs:
            blocks.append("\n".join(refs))
        header = f"// {_one_line(p.title)}: DBML ({p.dialect}), generated by Apiome.\n"
        return header + "\n\n".join(blocks) + "\n"

    def _type(self, column: "_Column") -> str:
        if column.enum_key:
            enum = self._qualified(self._p.enum_name(column.enum_key))
            return f'"{enum.replace(chr(34), "")}[]"' if column.is_list else enum
        if _DBML_BARE_TYPE.fullmatch(column.sql_type):
            return column.sql_type
        return '"' + column.sql_type.replace("\\", "\\\\").replace('"', '\\"') + '"'

    def _default(self, column: "_Column") -> Optional[str]:
        if column.default is None:
            return None
        if column.default_expression is not None:
            expression = _dbml_expression(column.default_expression)
            if expression is None:
                self._drop(f"the default of column {column.name!r} holds a backtick, which DBML cannot write; "
                           "dropped", column.pointer)
            return expression
        value = column.default_value
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return _number(value)
        return _dbml_string(str(value))

    def _table(self, table: "_Table") -> str:
        lines: List[str] = []
        single_unique = {tuple(u) for u in table.unique if len(u) == 1}
        for column in table.columns:
            settings: List[str] = []
            is_pk = table.primary_key == [column.name]
            if is_pk:
                settings.append("pk")
            if column.identity:
                settings.append("increment")
            if column.not_null and not is_pk:
                settings.append("not null")
            if (column.name,) in single_unique:
                settings.append("unique")
            default = self._default(column)
            if default is not None:
                settings.append(f"default: {default}")
            if not column.enum_key:  # an enum's values are its DBML Enum, not a CHECK
                for check in column.checks:
                    expression = _dbml_expression(check)
                    if expression is None:
                        self._drop(f"a check of column {column.name!r} holds a backtick, which DBML cannot "
                                   "write; dropped", column.pointer)
                    else:
                        settings.append(f"check: {expression}")
            suffix = f" [{', '.join(settings)}]" if settings else ""
            lines.append(f"  {_dbml_id(column.name)} {self._type(column)}{suffix}")
        checks = []
        for check in table.checks:
            expression = _dbml_expression(check)
            if expression is None:
                self._drop(f"a check of table {table.name!r} holds a backtick, which DBML cannot write; dropped",
                           table.key)
            else:
                checks.append(f"    {expression}")
        if checks:
            lines.append("\n  checks {\n" + "\n".join(checks) + "\n  }")
        indexes = []
        if len(table.primary_key) > 1:
            indexes.append(f"    ({', '.join(_dbml_id(c) for c in table.primary_key)}) [pk]")
        for unique in table.unique:
            if len(unique) > 1:
                indexes.append(f"    ({', '.join(_dbml_id(c) for c in unique)}) [unique]")
        if indexes:
            lines.append("\n  indexes {\n" + "\n".join(indexes) + "\n  }")
        return f"Table {self._qualified(table.name)} {{\n" + "\n".join(lines) + "\n}"

    def _refs(self) -> List[str]:
        refs = []
        for table in self._p.tables:
            for index, (columns, target, target_columns) in enumerate(table.foreign_keys, start=1):
                refs.append(f"Ref {_dbml_id(_fk_name(self._p, table, index))}: "
                            f"{self._endpoint(table.name, columns)} > {self._endpoint(target, target_columns)}")
        return refs

    def _endpoint(self, table: str, columns: Sequence[str]) -> str:
        if len(columns) == 1:
            return f"{self._qualified(table)}.{_dbml_id(columns[0])}"
        return f"{self._qualified(table)}.({', '.join(_dbml_id(c) for c in columns)})"


def _dbml_id_always(name: str) -> str:
    """``name`` double-quoted (enum values are always quoted: they are labels, not identifiers)."""
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_dbml(projection: "_SqlDdlWriter") -> str:
    """The projection as one DBML document, ending in a newline.

    Args:
        projection: A projected :class:`~app.sql_ddl_emitter._SqlDdlWriter`.

    Returns:
        The DBML text.
    """
    return _DbmlWriter(projection).render()


# ===========================================================================
# Prisma
# ===========================================================================

_PRISMA_PROVIDER = {"postgres": "postgresql", "mysql": "mysql"}
#: Names a Prisma model or enum may not take (the client's own names and the scalar types).
_PRISMA_RESERVED = frozenset(
    "PrismaClient Prisma String Boolean Int BigInt Float Decimal DateTime Json Bytes Unsupported".split()
)
#: Dialect SQL type → (Prisma scalar, ``@db.`` native type template or ``None``, approximation or ``None``).
_PRISMA_TYPES: Dict[str, List[Tuple[str, str, Optional[str], Optional[str]]]] = {
    "postgres": [
        (r"TEXT", "String", None, None),
        (r"VARCHAR\((\d+)\)", "String", "VarChar({0})", None),
        (r"CHAR\((\d+)\)", "String", "Char({0})", None),
        (r"UUID", "String", "Uuid", None),
        (r"DATE", "DateTime", "Date", None),
        (r"TIME", "DateTime", "Time", None),
        (r"TIMESTAMPTZ", "DateTime", "Timestamptz", None),
        (r"INTERVAL", "String", None, "Prisma has no interval type; written as String"),
        (r"BYTEA", "Bytes", None, None),
        (r"SMALLINT", "Int", "SmallInt", None),
        (r"INTEGER", "Int", None, None),
        (r"BIGINT", "BigInt", None, None),
        (r"REAL", "Float", "Real", None),
        (r"DOUBLE PRECISION", "Float", None, None),
        (r"BOOLEAN", "Boolean", None, None),
        (r"JSONB", "Json", None, None),
        (r"NUMERIC", "Decimal", None, "an unsized NUMERIC is written as Prisma's Decimal, decimal(65, 30)"),
        (r"NUMERIC\((\d+), (\d+)\)", "Decimal", "Decimal({0}, {1})", None),
    ],
    "mysql": [
        (r"TEXT", "String", "Text", None),
        (r"VARCHAR\((\d+)\)", "String", "VarChar({0})", None),
        (r"CHAR\((\d+)\)", "String", "Char({0})", None),
        (r"DATE", "DateTime", "Date", None),
        (r"TIME\((\d+)\)", "DateTime", "Time({0})", None),
        (r"DATETIME\((\d+)\)", "DateTime", "DateTime({0})", None),
        (r"LONGBLOB", "Bytes", "LongBlob", None),
        (r"TINYINT", "Int", "TinyInt", None),
        (r"SMALLINT", "Int", "SmallInt", None),
        (r"INT", "Int", None, None),
        (r"BIGINT", "BigInt", None, None),
        (r"FLOAT", "Float", "Float", None),
        (r"DOUBLE", "Float", None, None),
        (r"BOOLEAN", "Boolean", None, None),
        (r"JSON", "Json", None, None),
        (r"DECIMAL\((\d+), (\d+)\)", "Decimal", "Decimal({0}, {1})", None),
    ],
}
#: SQL family → Prisma scalar, for a column type the table above does not know (an imported type).
_FAMILY_PRISMA = {
    "text": "String", "uuid": "String", "duration": "String", "date": "DateTime", "time": "DateTime",
    "timestamp": "DateTime", "bytes": "Bytes", "int8": "Int", "int16": "Int", "int32": "Int",
    "int64": "BigInt", "float": "Float", "double": "Float", "decimal": "Decimal", "boolean": "Boolean",
    "json": "Json",
}
_NUMERIC_PRISMA = frozenset({"Int", "BigInt", "Float", "Decimal"})


def _pascal(name: str) -> str:
    """``order_line`` → ``OrderLine``."""
    return "".join(part[:1].upper() + part[1:] for part in name.split("_") if part) or "Model"


def _prisma_string(text: str) -> str:
    """A double-quoted Prisma string."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _unique_name(base: str, taken: Set[str]) -> str:
    """``base``, or ``base2``, ``base3`` … — the first one not in ``taken`` (which it joins)."""
    candidate, counter = base, 2
    while candidate in taken:
        candidate, counter = f"{base}{counter}", counter + 1
    taken.add(candidate)
    return candidate


class _PrismaWriter:
    """Writes one projection as a ``schema.prisma`` (single use)."""

    def __init__(self, projection: "_SqlDdlWriter") -> None:
        self._p = projection
        self._dropped, self._approx = _loss_subjects()
        self._schema = projection.options.schema_name if projection.dialect == "postgres" else None
        taken: Set[str] = set(_PRISMA_RESERVED)
        self._models: Dict[str, str] = {}
        for table in projection.tables:
            self._models[table.name] = _unique_name(_pascal(table.name), taken)
        self._enums: Dict[str, str] = {}
        self._enum_values: Dict[str, Dict[str, str]] = {}  # enum key → label → Prisma value name
        for enum_key in _enum_keys(projection.tables):
            self._enums[enum_key] = _unique_name(_pascal(projection.enum_name(enum_key)), taken)
        self._tables = {table.name: table for table in projection.tables}
        self._types: Dict[Tuple[str, str], Tuple[str, Optional[str]]] = {}
        for table in projection.tables:
            for column in table.columns:
                self._types[(table.name, column.name)] = self._scalar(column)
        # table name → its relation field lines (its own foreign keys, then the ones pointing at it),
        # filled before the models are written.
        self._relation_lines: Dict[str, List[str]] = {table.name: [] for table in projection.tables}
        self._back_lines: Dict[str, List[str]] = {table.name: [] for table in projection.tables}
        self._field_names: Dict[str, Set[str]] = {
            table.name: {column.name for column in table.columns} for table in projection.tables
        }

    def _approximate(self, detail: str, pointer: str) -> None:
        self._p.record_loss(LossKind.INFERRED, self._approx, detail, pointer)

    def _drop(self, detail: str, pointer: str) -> None:
        self._p.record_loss(LossKind.NA, self._dropped, detail, pointer)

    # -- types ----------------------------------------------------------------

    def _scalar(self, column: "_Column") -> Tuple[str, Optional[str]]:
        """The column's Prisma scalar (or enum) type and its ``@db.`` native type, if any."""
        if column.enum_key:
            return self._enums[column.enum_key], None
        sql_type = column.sql_type[:-2] if column.is_list else column.sql_type
        for pattern, scalar, native, approx in _PRISMA_TYPES[self._p.dialect]:
            match = re.fullmatch(pattern, sql_type)
            if match:
                if approx:
                    self._approximate(f"column {column.name!r}: {approx}", column.pointer)
                return scalar, native.format(*match.groups()) if native else None
        scalar = _FAMILY_PRISMA.get(column.family or "")
        if scalar is None:
            scalar = "String"
        self._approximate(f"column {column.name!r} of type {column.sql_type} is written as Prisma {scalar}",
                          column.pointer)
        return scalar, None

    def _default(self, column: "_Column", scalar: str) -> Optional[str]:
        if column.identity:
            return "@default(autoincrement())"
        if column.default is None:
            return None
        if column.default_expression is not None:
            return f"@default(dbgenerated({_prisma_string(column.default_expression)}))"
        value = column.default_value
        if column.enum_key:
            name = self._enum_values.get(column.enum_key, {}).get(str(value))
            if name is not None:
                return f"@default({name})"
        elif isinstance(value, bool) and scalar == "Boolean":
            return f"@default({'true' if value else 'false'})"
        elif isinstance(value, (int, float)) and not isinstance(value, bool) and scalar in _NUMERIC_PRISMA:
            if scalar in ("Int", "BigInt") and not float(value).is_integer():
                return f"@default(dbgenerated({_prisma_string(column.default)}))"
            return f"@default({_number(value)})"
        elif isinstance(value, str) and scalar == "String":
            return f"@default({_prisma_string(value)})"
        return f"@default(dbgenerated({_prisma_string(column.default)}))"

    # -- the document ---------------------------------------------------------

    def render(self) -> str:
        p = self._p
        datasource = [f"  provider = {_prisma_string(_PRISMA_PROVIDER[p.dialect])}"]
        if self._schema:
            datasource.append(f"  schemas  = [{_prisma_string(self._schema)}]")
        blocks = ["datasource db {\n" + "\n".join(datasource) + "\n}"]
        blocks += [self._enum(enum_key) for enum_key in self._enums]
        self._plan_relations()
        blocks += [self._model(table) for table in p.tables]
        header = f"// {_one_line(p.title)}: Prisma schema ({p.dialect}), generated by Apiome.\n"
        return header + "\n\n".join(blocks) + "\n"

    def _enum(self, enum_key: str) -> str:
        lines: List[str] = []
        taken: Set[str] = set()
        values: Dict[str, str] = {}
        for label in self._p.enum_labels(enum_key):
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", label):
                name = _unique_name(label, taken)
            else:
                base = re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_") or "value"
                name = _unique_name(base if base[0].isalpha() else f"v_{base}", taken)
            values[label] = name
            lines.append(f"  {name}" + (f" @map({_prisma_string(label)})" if name != label else ""))
        self._enum_values[enum_key] = values
        db_name = self._p.enum_name(enum_key)
        if self._p.dialect == "postgres" and db_name != self._enums[enum_key]:
            lines.append(f"\n  @@map({_prisma_string(db_name)})")
        if self._schema:
            lines.append(f"  @@schema({_prisma_string(self._schema)})")
        return f"enum {self._enums[enum_key]} {{\n" + "\n".join(lines) + "\n}"

    def _plan_relations(self) -> None:
        """Both sides of every foreign key Prisma can model, as named ``@relation`` fields."""
        for table in self._p.tables:
            for index, (columns, target, target_columns) in enumerate(table.foreign_keys, start=1):
                name = _fk_name(self._p, table, index)
                reason = self._relation_problem(table, columns, target, target_columns)
                if reason is not None:
                    pointer = next((c.pointer for c in table.columns if c.name == columns[0]), table.key)
                    self._drop(f"the foreign key {name!r} is kept as plain columns, not a Prisma relation: "
                               f"{reason}", pointer)
                    continue
                owner_model, target_model = self._models[table.name], self._models[target]
                owner_columns = {c.name: c for c in table.columns}
                required = all(owner_columns[c].not_null for c in columns)
                if len(columns) == 1:
                    stem = re.sub(r"(_ref)?_id$", "", columns[0])
                    base = stem if stem != columns[0] else f"{columns[0]}_rel"
                else:
                    base = target
                if base in self._field_names[table.name]:
                    base = f"{base}_rel"
                forward = _unique_name(base, self._field_names[table.name])
                self._relation_lines[table.name].append(
                    f"  {forward} {target_model}{'' if required else '?'} @relation({_prisma_string(name)}, "
                    f"fields: [{', '.join(columns)}], references: [{', '.join(target_columns)}])"
                )
                one_to_one = set(columns) == set(table.primary_key) or any(
                    set(columns) == set(u) for u in table.unique)
                back_base = table.name if table.name not in self._field_names[target] else f"{table.name}_{forward}"
                back = _unique_name(back_base, self._field_names[target])
                self._back_lines[target].append(
                    f"  {back} {owner_model}{'?' if one_to_one else '[]'} @relation({_prisma_string(name)})"
                )

    def _relation_problem(self, table: "_Table", columns: Sequence[str], target: str,
                          target_columns: Sequence[str]) -> Optional[str]:
        """Why Prisma cannot model this foreign key as a relation, or ``None`` when it can."""
        other = self._tables.get(target)
        if other is None:
            return f"its table {target!r} is not in the schema"
        owner_names = {c.name for c in table.columns}
        target_names = {c.name for c in other.columns}
        if not set(columns) <= owner_names or not set(target_columns) <= target_names:
            return "it names a column the tables do not have"
        unique_sets = [set(other.primary_key), *(set(u) for u in other.unique)]
        if set(target_columns) not in unique_sets:
            return f"the columns it references in {target!r} are not its primary or a unique key"
        for column, referenced in zip(columns, target_columns):
            if self._types[(table.name, column)][0] != self._types[(target, referenced)][0]:
                return f"{column!r} and {target}.{referenced} have different Prisma types"
        return None

    def _model(self, table: "_Table") -> str:
        lines: List[str] = []
        single_unique = {u[0] for u in table.unique if len(u) == 1}
        for column in table.columns:
            scalar, native = self._types[(table.name, column.name)]
            is_pk = column.name in table.primary_key
            if column.is_list:
                type_text = f"{scalar}[]"
                if not column.not_null:
                    self._approximate(f"column {column.name!r}: a Prisma list is never null; written as a "
                                      "required list", column.pointer)
            else:
                type_text = scalar if column.not_null or is_pk else f"{scalar}?"
            attributes: List[str] = []
            if table.primary_key == [column.name]:
                attributes.append("@id")
            default = self._default(column, scalar)
            if default is not None:
                attributes.append(default)
            if column.name in single_unique and table.primary_key != [column.name]:
                attributes.append("@unique")
            if native:
                attributes.append(f"@db.{native}")
            if column.checks and not (column.enum_key and self._p.dialect == "ansi"):
                self._drop(f"Prisma has no CHECK constraint; the checks of column {column.name!r} "
                           f"({'; '.join(column.checks)}) are dropped", column.pointer)
            lines.append(f"  {column.name} {type_text}" + (f" {' '.join(attributes)}" if attributes else ""))
        lines += self._relation_lines[table.name] + self._back_lines[table.name]
        if table.checks:
            self._drop(f"Prisma has no CHECK constraint; the checks of table {table.name!r} are dropped", table.key)
        block: List[str] = []
        if len(table.primary_key) > 1:
            block.append(f"  @@id([{', '.join(table.primary_key)}])")
        for unique in table.unique:
            if len(unique) > 1:
                block.append(f"  @@unique([{', '.join(unique)}])")
        if self._models[table.name] != table.name:
            block.append(f"  @@map({_prisma_string(table.name)})")
        if self._schema:
            block.append(f"  @@schema({_prisma_string(self._schema)})")
        body = "\n".join(lines) + ("\n\n" + "\n".join(block) if block else "")
        return f"model {self._models[table.name]} {{\n{body}\n}}"


def render_prisma(projection: "_SqlDdlWriter") -> str:
    """The projection as one ``schema.prisma``, ending in a newline.

    Args:
        projection: A projected :class:`~app.sql_ddl_emitter._SqlDdlWriter` (PostgreSQL or MySQL).

    Returns:
        The Prisma schema text.
    """
    return _PrismaWriter(projection).render()
