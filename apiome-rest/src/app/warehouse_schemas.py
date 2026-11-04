"""BigQuery and Spark schema modes of the Arrow export — MFX-36.2 (#4318).

The Arrow / Parquet export (MFX-36.1, :mod:`app.arrow_emitter`) projects an item's types onto Arrow
tables once (:func:`app.arrow_emitter.project_arrow_tables`). This module serializes that same typed
projection for the two warehouse engines that do not read Arrow schemas:

* **BigQuery** — a table schema as the JSON array ``bq mk --schema`` and the ``tables.insert`` API take
  (``[{"name", "type", "mode", "fields", "description"}, …]``): a ``struct`` is a ``RECORD`` with its
  ``fields``, a ``list`` is its element with ``mode: REPEATED``;
* **Spark** — a ``StructType`` as the DDL string ``DataType.fromDDL`` / ``StructType.fromDDL`` parse
  (``` `id` STRING NOT NULL, `lines` ARRAY<STRUCT<`sku`: STRING>> ```).

Each serializer records what it cannot keep as a loss (a map as a repeated key/value record, a union
as a record of optional members, a type the engine lacks) against the table's key, naming the column.

Neither engine's own tool runs here (``bq`` needs Google credentials, ``fromDDL`` a JVM), so each has
an offline checker the export gate runs: :func:`bigquery_schema_problems` applies BigQuery's documented
``TableFieldSchema`` rules, and :func:`parse_spark_ddl` is a strict parser of Spark's column-type
grammar (``SqlBaseParser``'s ``colTypeList`` / ``dataType`` rules), refusing any type name Spark does
not define.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set, Tuple

from .arrow_schema import ArrowField, ArrowSchema, ArrowType
from .emitter import LossKind, LossTracker

__all__ = [
    "BIGQUERY_MAX_DEPTH",
    "LOSS_BIGQUERY_RENAMED",
    "LOSS_WAREHOUSE_APPROX",
    "SparkDdlError",
    "bigquery_fields",
    "bigquery_schema_problems",
    "parse_spark_ddl",
    "spark_ddl",
    "spark_ddl_problems",
]

#: Loss subjects.
LOSS_WAREHOUSE_APPROX = "warehouse-type-approximated"
LOSS_BIGQUERY_RENAMED = "bigquery-column-renamed"
LOSS_BIGQUERY_DEPTH = "bigquery-nesting-as-json"

_EXTENSION_KEY = "ARROW:extension:name"

# ===========================================================================
# BigQuery
# ===========================================================================

#: BigQuery's documented nesting limit for RECORD columns.
BIGQUERY_MAX_DEPTH = 15
#: The column types a BigQuery table schema may name (with their legacy spellings).
BIGQUERY_TYPES = frozenset({
    "STRING", "BYTES", "INTEGER", "INT64", "FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC", "BOOLEAN", "BOOL",
    "TIMESTAMP", "DATE", "TIME", "DATETIME", "GEOGRAPHY", "JSON", "INTERVAL", "RANGE", "RECORD", "STRUCT",
})
BIGQUERY_MODES = frozenset({"NULLABLE", "REQUIRED", "REPEATED"})
_BQ_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_BQ_NAME_MAX = 300
_BQ_DESCRIPTION_MAX = 1024
#: Column-name prefixes BigQuery reserves (case-insensitive).
_BQ_RESERVED_PREFIXES = ("_table_", "_file_", "_partition", "_row_timestamp", "__root__", "_colidentifier")


def _bq_name(name: str, taken: Set[str]) -> str:
    """A legal, unique (case-insensitively) BigQuery column name for ``name``."""
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name) or "_"
    if not re.match(r"[A-Za-z_]", safe):
        safe = f"_{safe}"
    if safe.lower().startswith(_BQ_RESERVED_PREFIXES):
        safe = f"f{safe}"
    safe = safe[:_BQ_NAME_MAX]
    candidate, n = safe, 2
    while candidate.lower() in taken:
        candidate = f"{safe[:_BQ_NAME_MAX - 4]}_{n}"
        n += 1
    taken.add(candidate.lower())
    return candidate


def _bq_decimal(type_: ArrowType) -> Tuple[str, Optional[int], Optional[int]]:
    """``NUMERIC`` when BigQuery's NUMERIC holds the precision and scale, else ``BIGNUMERIC``."""
    precision = int(type_.parameter("precision", 38))
    scale = int(type_.parameter("scale", 0))
    if scale <= 9 and max(1, scale) <= precision <= scale + 29:
        return "NUMERIC", precision, scale
    if scale <= 38 and max(1, scale) <= precision <= scale + 38:
        return "BIGNUMERIC", precision, scale
    return "BIGNUMERIC", None, None


@dataclass
class _BigQueryWriter:
    """Writes an Arrow schema as BigQuery fields, recording each approximation against ``pointer``."""

    losses: LossTracker
    pointer: str

    def _approx(self, path: str, detail: str, subject: str = LOSS_WAREHOUSE_APPROX) -> None:
        self.losses.record(LossKind.INFERRED, subject, f"BigQuery column {path!r}: {detail}", self.pointer)

    def fields(self, children: Sequence[ArrowField], path: str, depth: int) -> List[Dict[str, Any]]:
        taken: Set[str] = set()
        return [self.field(child, path, depth, taken) for child in children]

    def field(self, source: ArrowField, path: str, depth: int, taken: Set[str]) -> Dict[str, Any]:
        name = _bq_name(source.name, taken)
        here = f"{path}.{source.name}" if path else source.name
        if name != source.name:
            self._approx(here, f"renamed to {name!r} (BigQuery names are letters, digits and underscores)",
                         LOSS_BIGQUERY_RENAMED)
        entry: Dict[str, Any] = {"name": name}
        entry.update(self.column(source, here, depth))
        if "mode" not in entry:
            entry["mode"] = "NULLABLE" if source.nullable else "REQUIRED"
        description = source.metadata_value("description")
        if description:
            entry["description"] = description[:_BQ_DESCRIPTION_MAX]
        # Key order: name, type, mode, fields, description, as BigQuery prints a schema.
        order = ("name", "type", "mode", "precision", "scale", "fields", "description")
        return {k: entry[k] for k in order if k in entry}

    def column(self, source: ArrowField, path: str, depth: int) -> Dict[str, Any]:
        """``type`` (and ``mode`` / ``fields`` / ``precision`` / ``scale``) of one column."""
        type_ = source.type
        name = type_.name
        if name in ("list", "largelist", "fixedsizelist", "listview", "largelistview"):
            element = source.children[0]
            if element.type.name in ("list", "largelist", "fixedsizelist", "listview", "largelistview"):
                # BigQuery has no array of arrays: the inner list is wrapped in a repeated record.
                self._approx(path, "a list of lists is a repeated RECORD holding the inner list as `item`")
                inner = self.field(element, path, depth + 1, set())
                return {"type": "RECORD", "mode": "REPEATED", "fields": [inner]}
            column = self.column(element, path, depth)
            if column.get("mode") == "REPEATED":  # pragma: no cover - lists of lists are handled above
                return column
            return {**column, "mode": "REPEATED"}
        if name == "struct":
            if depth >= BIGQUERY_MAX_DEPTH:
                self._approx(path, f"nested deeper than BigQuery's {BIGQUERY_MAX_DEPTH} levels; written as JSON",
                             LOSS_BIGQUERY_DEPTH)
                return {"type": "JSON"}
            return {"type": "RECORD", "fields": self.fields(source.children, path, depth + 1)}
        if name == "map":
            self._approx(path, "a map is a repeated RECORD of `key` and `value` (BigQuery has no map type)")
            entries = source.children[0]
            return {"type": "RECORD", "mode": "REPEATED", "fields": self.fields(entries.children, path, depth + 1)}
        if name == "union":
            self._approx(path, "a union is a RECORD with one optional field per member (BigQuery has no union)")
            members = [ArrowField(name=c.name, type=c.type, nullable=True, children=c.children,
                                  dictionary=c.dictionary, metadata=c.metadata) for c in source.children]
            if depth >= BIGQUERY_MAX_DEPTH:
                return {"type": "JSON"}
            return {"type": "RECORD", "fields": self.fields(members, path, depth + 1)}
        return self.scalar(source, path)

    def scalar(self, source: ArrowField, path: str) -> Dict[str, Any]:
        type_ = source.type
        name = type_.name
        extension = source.metadata_value(_EXTENSION_KEY)
        if extension == "arrow.json":
            return {"type": "JSON"}
        if extension == "arrow.uuid":
            self._approx(path, "a UUID is a STRING (BigQuery has no UUID type)")
            return {"type": "STRING"}
        if name in ("utf8", "largeutf8", "utf8view"):
            return {"type": "STRING"}
        if name in ("binary", "largebinary", "binaryview", "fixedsizebinary"):
            return {"type": "BYTES"}
        if name == "bool":
            return {"type": "BOOLEAN"}
        if name == "int":
            if int(type_.parameter("bitWidth", 64)) == 64 and type_.parameter("isSigned", True) is False:
                self._approx(path, "an unsigned 64-bit integer is NUMERIC (BigQuery's INT64 is signed)")
                return {"type": "NUMERIC"}
            return {"type": "INTEGER"}
        if name == "floatingpoint":
            return {"type": "FLOAT"}
        if name == "decimal":
            kind, precision, scale = _bq_decimal(type_)
            if precision is None:
                self._approx(path, "the decimal's precision is beyond BIGNUMERIC; written as BIGNUMERIC unbounded")
                return {"type": kind}
            return {"type": kind, "precision": str(precision), "scale": str(scale)}
        if name == "date":
            return {"type": "DATE"}
        if name == "time":
            return {"type": "TIME"}
        if name == "timestamp":
            return {"type": "TIMESTAMP" if type_.parameter("timezone") else "DATETIME"}
        if name in ("duration", "interval"):
            return {"type": "INTERVAL"}
        self._approx(path, f"Arrow type `{name}` has no BigQuery type; written as STRING")
        return {"type": "STRING"}


def bigquery_fields(schema: ArrowSchema, *, losses: LossTracker, pointer: str) -> List[Dict[str, Any]]:
    """An Arrow schema as a BigQuery table schema (the JSON array ``bq mk --schema`` reads).

    Args:
        schema: One table of the projection.
        losses: Where approximations are recorded.
        pointer: The canonical key the losses are filed under (the table's record).

    Returns:
        The table's fields, in column order.
    """
    return _BigQueryWriter(losses, pointer).fields(schema.fields, "", 1)


def bigquery_schema_problems(fields: Any, *, path: str = "", depth: int = 1) -> List[Dict[str, str]]:
    """Check a BigQuery table schema against BigQuery's documented ``TableFieldSchema`` rules.

    The rules: a list of field objects; each has a legal ``name`` (letters, digits, underscores, not
    starting with a digit, at most 300 characters, no reserved prefix), unique case-insensitively among
    its siblings; a known ``type``; a ``mode`` of ``NULLABLE`` / ``REQUIRED`` / ``REPEATED``; a
    ``RECORD`` has at least one sub-field and no other type has any; nesting is at most 15 levels; a
    ``NUMERIC`` / ``BIGNUMERIC`` precision and scale are in range; a description is at most 1024 characters.

    Args:
        fields: The parsed schema (the JSON array).
        path: The enclosing column path (for messages).
        depth: The nesting level of ``fields``.

    Returns:
        ``{"rule", "path", "message"}`` per problem; empty when the schema is valid.
    """
    problems: List[Dict[str, str]] = []

    def bad(rule: str, where: str, message: str) -> None:
        problems.append({"rule": rule, "path": where or "/", "message": message})

    if not isinstance(fields, list) or not fields:
        bad("bigquery.fields", path, "a table schema is a non-empty list of fields")
        return problems
    if depth > BIGQUERY_MAX_DEPTH:
        bad("bigquery.depth", path, f"RECORD columns nest at most {BIGQUERY_MAX_DEPTH} levels deep")
        return problems
    seen: Set[str] = set()
    for index, field_ in enumerate(fields):
        where = f"{path}/{index}"
        if not isinstance(field_, Mapping):
            bad("bigquery.field", where, "a field is an object")
            continue
        unknown = set(field_) - {"name", "type", "mode", "fields", "description", "precision", "scale",
                                 "maxLength", "defaultValueExpression", "policyTags", "collation",
                                 "roundingMode", "rangeElementType"}
        if unknown:
            bad("bigquery.field", where, f"unknown key(s) {', '.join(sorted(unknown))}")
        name = field_.get("name")
        if not isinstance(name, str) or not _BQ_NAME.match(name) or len(name) > _BQ_NAME_MAX:
            bad("bigquery.name", where, f"{name!r} is not a legal column name")
        elif name.lower().startswith(_BQ_RESERVED_PREFIXES):
            bad("bigquery.name", where, f"{name!r} starts with a reserved prefix")
        elif name.lower() in seen:
            bad("bigquery.name", where, f"{name!r} repeats a sibling column (names are case-insensitive)")
        else:
            seen.add(name.lower())
        type_ = str(field_.get("type", "")).upper()
        if type_ not in BIGQUERY_TYPES:
            bad("bigquery.type", where, f"{field_.get('type')!r} is not a BigQuery column type")
        mode = str(field_.get("mode", "NULLABLE")).upper()
        if mode not in BIGQUERY_MODES:
            bad("bigquery.mode", where, f"{field_.get('mode')!r} is not NULLABLE, REQUIRED or REPEATED")
        description = field_.get("description")
        if description is not None and (not isinstance(description, str) or len(description) > _BQ_DESCRIPTION_MAX):
            bad("bigquery.description", where, f"a description is a string of at most {_BQ_DESCRIPTION_MAX} characters")
        sub = field_.get("fields")
        if type_ in ("RECORD", "STRUCT"):
            problems.extend(bigquery_schema_problems(sub, path=f"{where}/fields", depth=depth + 1))
        elif sub is not None:
            bad("bigquery.fields", where, f"only a RECORD has sub-fields, not {type_ or 'a typeless field'}")
        if type_ in ("NUMERIC", "BIGNUMERIC") and ("precision" in field_ or "scale" in field_):
            try:
                precision = int(field_.get("precision"))
                scale = int(field_.get("scale", 0))
            except (TypeError, ValueError):
                bad("bigquery.decimal", where, "precision and scale are integers")
                continue
            limit, span = (9, 29) if type_ == "NUMERIC" else (38, 38)
            if not (0 <= scale <= limit and max(1, scale) <= precision <= scale + span):
                bad("bigquery.decimal", where, f"{type_}({precision}, {scale}) is out of range")
        elif "precision" in field_ or "scale" in field_:
            if type_ not in ("NUMERIC", "BIGNUMERIC"):
                bad("bigquery.decimal", where, "only NUMERIC and BIGNUMERIC take a precision and scale")
    return problems


# ===========================================================================
# Spark
# ===========================================================================

#: Spark SQL's primitive type names (``DataType.fromDDL``), case-insensitive.
SPARK_PRIMITIVES = frozenset({
    "boolean", "tinyint", "byte", "smallint", "short", "int", "integer", "bigint", "long", "float", "real",
    "double", "date", "timestamp", "timestamp_ntz", "timestamp_ltz", "string", "binary", "void", "variant",
})
_SPARK_INTERVAL_FIELDS = ("year", "month", "day", "hour", "minute", "second")
_SPARK_DECIMAL_MAX = 38


def _spark_ident(name: str) -> str:
    """A back-quoted Spark identifier (a back-quote inside is doubled)."""
    return "`" + name.replace("`", "``") + "`"


def _spark_string(text: str) -> str:
    """A single-quoted Spark string literal."""
    escaped = text.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "\\r")
    return "'" + escaped + "'"


@dataclass
class _SparkWriter:
    """Writes an Arrow schema as Spark DDL, recording each approximation against ``pointer``."""

    losses: LossTracker
    pointer: str

    def _approx(self, path: str, detail: str) -> None:
        self.losses.record(LossKind.INFERRED, LOSS_WAREHOUSE_APPROX, f"Spark column {path!r}: {detail}",
                           self.pointer)

    def column(self, source: ArrowField, path: str, *, nested: bool) -> str:
        """One ``name TYPE [NOT NULL] [COMMENT '…']`` entry (``name: TYPE …`` inside a STRUCT)."""
        text = f"{_spark_ident(source.name)}{':' if nested else ''} {self.type(source, path)}"
        if not source.nullable:
            text += " NOT NULL"
        description = source.metadata_value("description")
        if description:
            text += f" COMMENT {_spark_string(description)}"
        return text

    def struct(self, children: Sequence[ArrowField], path: str) -> str:
        inner = ", ".join(self.column(c, f"{path}.{c.name}", nested=True) for c in children)
        return f"STRUCT<{inner}>"

    def type(self, source: ArrowField, path: str) -> str:
        type_ = source.type
        name = type_.name
        if name in ("list", "largelist", "fixedsizelist", "listview", "largelistview"):
            return f"ARRAY<{self.type(source.children[0], path)}>"
        if name == "struct":
            return self.struct(source.children, path)
        if name == "map":
            key, value = source.children[0].children
            return f"MAP<{self.type(key, path)}, {self.type(value, path)}>"
        if name == "union":
            self._approx(path, "a union is a STRUCT with one optional field per member (Spark has no union)")
            members = [ArrowField(name=c.name, type=c.type, nullable=True, children=c.children,
                                  dictionary=c.dictionary, metadata=c.metadata) for c in source.children]
            return self.struct(members, path)
        extension = source.metadata_value(_EXTENSION_KEY)
        if extension == "arrow.uuid":
            self._approx(path, "a UUID is a STRING (Spark has no UUID type)")
            return "STRING"
        if extension == "arrow.json" or name in ("utf8", "largeutf8", "utf8view"):
            return "STRING"
        if name in ("binary", "largebinary", "binaryview", "fixedsizebinary"):
            return "BINARY"
        if name == "bool":
            return "BOOLEAN"
        if name == "null":
            return "VOID"
        if name == "int":
            width = int(type_.parameter("bitWidth", 64))
            signed = type_.parameter("isSigned", True) is not False
            if not signed:
                width *= 2  # the next signed width holds every unsigned value
            if width > 64:
                self._approx(path, "an unsigned 64-bit integer is DECIMAL(20, 0) (Spark's BIGINT is signed)")
                return "DECIMAL(20, 0)"
            return {8: "TINYINT", 16: "SMALLINT", 32: "INT"}.get(width, "BIGINT")
        if name == "floatingpoint":
            return "DOUBLE" if type_.parameter("precision") == "DOUBLE" else "FLOAT"
        if name == "decimal":
            precision = int(type_.parameter("precision", 38))
            scale = int(type_.parameter("scale", 0))
            if precision > _SPARK_DECIMAL_MAX:
                self._approx(path, f"decimal({precision}, {scale}) is beyond Spark's 38 digits; written "
                             f"DECIMAL(38, {min(scale, 38)})")
                precision, scale = _SPARK_DECIMAL_MAX, min(scale, _SPARK_DECIMAL_MAX)
            return f"DECIMAL({precision}, {scale})"
        if name == "date":
            return "DATE"
        if name == "timestamp":
            return "TIMESTAMP" if type_.parameter("timezone") else "TIMESTAMP_NTZ"
        if name == "duration":
            return "INTERVAL DAY TO SECOND"
        if name == "time":
            self._approx(path, "a time of day is a STRING (Spark's DDL has no TIME type)")
            return "STRING"
        if name == "interval":
            self._approx(path, "a calendar interval (months, days and nanoseconds) is a STRING; Spark's intervals "
                         "are year-month or day-time")
            return "STRING"
        self._approx(path, f"Arrow type `{name}` has no Spark type; written as STRING")
        return "STRING"


def spark_ddl(schema: ArrowSchema, *, losses: LossTracker, pointer: str) -> str:
    """An Arrow schema as a Spark ``StructType`` DDL string (what ``DataType.fromDDL`` parses).

    Args:
        schema: One table of the projection.
        losses: Where approximations are recorded.
        pointer: The canonical key the losses are filed under (the table's record).

    Returns:
        ``` `col` TYPE [NOT NULL] [COMMENT '…'], … ``` on one line.
    """
    writer = _SparkWriter(losses, pointer)
    return ", ".join(writer.column(f, f.name, nested=False) for f in schema.fields)


class SparkDdlError(ValueError):
    """A Spark DDL string Spark's parser would refuse; ``position`` is the offending offset."""

    def __init__(self, message: str, position: int) -> None:
        super().__init__(f"{message} (at character {position + 1})")
        self.position = position


_TOKEN = re.compile(r"""\s*(?:
    (?P<quoted>`(?:[^`]|``)*`)
  | (?P<string>'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")
  | (?P<number>\d+)
  | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<punct>[<>(),:])
)""", re.VERBOSE)


class _SparkParser:
    """A recursive-descent parser of Spark's ``colTypeList`` grammar (what ``fromDDL`` accepts).

    ``colTypeList  : colType (',' colType)*``
    ``colType      : identifier dataType (NOT NULL)? (COMMENT string)?``
    ``dataType     : ARRAY '<' dataType '>' | MAP '<' dataType ',' dataType '>'``
    ``             | STRUCT '<' (complexColType (',' complexColType)*)? '>'``
    ``             | INTERVAL field (TO field)? | primitive ('(' INTEGER (',' INTEGER)* ')')?``
    ``complexColType : identifier ':'? dataType (NOT NULL)? (COMMENT string)?``
    """

    def __init__(self, text: str) -> None:
        self.tokens: List[Tuple[str, str, int]] = []
        position = 0
        while position < len(text):
            if text[position:].strip() == "":
                break
            match = _TOKEN.match(text, position)
            if match is None or match.end() == position:
                raise SparkDdlError(f"unexpected character {text[position:].lstrip()[:1]!r}", position)
            kind = match.lastgroup or ""
            self.tokens.append((kind, match.group(kind), match.start(kind)))
            position = match.end()
        self.index = 0
        self.length = len(text)

    def _peek(self) -> Tuple[str, str, int]:
        return self.tokens[self.index] if self.index < len(self.tokens) else ("end", "", self.length)

    def _next(self) -> Tuple[str, str, int]:
        token = self._peek()
        self.index += 1
        return token

    def _expect(self, value: str) -> None:
        kind, text, position = self._next()
        if text.upper() != value.upper():
            raise SparkDdlError(f"expected {value!r}, found {text or 'the end'!r}", position)

    def _accept(self, value: str) -> bool:
        if self._peek()[1].upper() == value.upper() and self._peek()[0] in ("word", "punct"):
            self.index += 1
            return True
        return False

    def _identifier(self) -> str:
        kind, text, position = self._next()
        if kind == "quoted":
            return text[1:-1].replace("``", "`")
        if kind == "word":
            return text
        raise SparkDdlError(f"expected a column name, found {text or 'the end'!r}", position)

    def _suffix(self) -> None:
        if self._accept("NOT"):
            self._expect("NULL")
        if self._accept("COMMENT"):
            kind, text, position = self._next()
            if kind != "string":
                raise SparkDdlError("COMMENT takes a string literal", position)

    def columns(self) -> List[str]:
        names = [self._column(nested=False)]
        while self._accept(","):
            names.append(self._column(nested=False))
        kind, text, position = self._peek()
        if kind != "end":
            raise SparkDdlError(f"unexpected {text!r} after the last column", position)
        return names

    def _column(self, *, nested: bool) -> str:
        name = self._identifier()
        if nested:
            self._accept(":")
        self.data_type()
        self._suffix()
        return name

    def data_type(self) -> None:
        kind, text, position = self._next()
        if kind != "word":
            raise SparkDdlError(f"expected a data type, found {text or 'the end'!r}", position)
        word = text.lower()
        if word == "array":
            self._expect("<")
            self.data_type()
            self._expect(">")
        elif word == "map":
            self._expect("<")
            self.data_type()
            self._expect(",")
            self.data_type()
            self._expect(">")
        elif word == "struct":
            self._expect("<")
            if not self._accept(">"):
                names = [self._column(nested=True)]
                while self._accept(","):
                    names.append(self._column(nested=True))
                self._expect(">")
                lowered = [n.lower() for n in names]
                if len(set(lowered)) != len(lowered):
                    raise SparkDdlError("a STRUCT repeats a field name", position)
        elif word == "interval":
            start = self._interval_field()
            if self._accept("TO"):
                end = self._interval_field()
                if _SPARK_INTERVAL_FIELDS.index(end) <= _SPARK_INTERVAL_FIELDS.index(start) or \
                        (start in ("year", "month")) != (end in ("year", "month")):
                    raise SparkDdlError(f"INTERVAL {start.upper()} TO {end.upper()} is not a Spark interval", position)
        elif word in ("decimal", "dec", "numeric"):
            if self._accept("("):
                precision = self._integer()
                scale = self._integer() if self._accept(",") else 0
                self._expect(")")
                if not 1 <= precision <= _SPARK_DECIMAL_MAX or not 0 <= scale <= precision:
                    raise SparkDdlError(f"DECIMAL({precision}, {scale}) is out of range", position)
        elif word in ("char", "varchar", "character"):
            self._expect("(")
            self._integer()
            self._expect(")")
        elif word not in SPARK_PRIMITIVES:
            raise SparkDdlError(f"{text!r} is not a Spark data type", position)

    def _interval_field(self) -> str:
        kind, text, position = self._next()
        if text.lower() not in _SPARK_INTERVAL_FIELDS:
            raise SparkDdlError(f"expected an interval field, found {text or 'the end'!r}", position)
        return text.lower()

    def _integer(self) -> int:
        kind, text, position = self._next()
        if kind != "number":
            raise SparkDdlError(f"expected an integer, found {text or 'the end'!r}", position)
        return int(text)


def parse_spark_ddl(text: str) -> List[str]:
    """Parse a Spark ``StructType`` DDL string as ``DataType.fromDDL`` does.

    Args:
        text: ``` `col` TYPE, … ``` (or ``STRUCT<…>`` — Spark accepts both).

    Returns:
        The top-level column names.

    Raises:
        SparkDdlError: When Spark's parser would refuse the string.
    """
    if not text.strip():
        raise SparkDdlError("the DDL declares no column", 0)
    stripped = text.strip()
    if stripped.lower().startswith("struct<") and stripped.endswith(">"):
        parser = _SparkParser(stripped)
        parser.data_type()
        if parser._peek()[0] != "end":
            raise SparkDdlError("unexpected text after the STRUCT", parser._peek()[2])
        return []
    names = _SparkParser(text).columns()
    lowered = [n.lower() for n in names]
    if len(set(lowered)) != len(lowered):
        raise SparkDdlError("two columns share a name", 0)
    return names


def spark_ddl_problems(text: str) -> List[Dict[str, str]]:
    """The export gate's Spark check: each non-comment line of a ``.spark.ddl`` file parses.

    Returns:
        ``{"rule", "path", "message"}`` per problem; empty when every DDL line parses.
    """
    problems: List[Dict[str, str]] = []
    lines = [(n, line) for n, line in enumerate(text.splitlines(), 1) if line.strip() and
             not line.lstrip().startswith("--")]
    if not lines:
        return [{"rule": "spark.ddl", "path": "/", "message": "the file holds no DDL"}]
    for number, line in lines:
        try:
            parse_spark_ddl(line)
        except SparkDdlError as exc:
            problems.append({"rule": "spark.ddl", "path": f"line {number}", "message": str(exc)})
    return problems
