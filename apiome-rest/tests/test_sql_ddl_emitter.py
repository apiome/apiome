"""SQL DDL emitter — MFX-35.1 (#4311).

Covers :mod:`app.sql_ddl_emitter` against the issue's acceptance criteria:

* **the DDL parses per dialect (sqlglot) and applies to a live PostgreSQL** — every corpus source with a
  record type, in all three dialects and both ``nested`` modes, emits a script that sqlglot parses in
  its dialect (the emitter refuses to return one that does not); every PostgreSQL script is applied to
  the local database inside a transaction, in a throwaway schema, and rolled back (skipped when no
  database is reachable);
* **projection decisions are deterministic and reported SYNTH** — the same model always writes the same
  script (pinned in ``fixtures/sql_ddl_output/``, regenerate with ``APIOME_REGEN_SQL_DDL_OUTPUT=1``);
  synthesized keys, junction and child tables, renamed identifiers and synthesized precisions are
  ``SYNTH`` verdicts in the fidelity report.

Plus the column rules (types, ``NOT NULL``, ``CHECK``, enums, arrays, JSON columns), identifier mangling,
an imported SQL item's keys and dialect clauses, the re-import through the SQL DDL reader and the gate.
"""

from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, Iterator, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    EnumValue,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitPreconditionError, coerce_emit_options, load_builtin_emitters
from app.export_routes import build_target_fidelity_entries
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind
from app.sql_ddl_emitter import (
    LOSS_JUNCTION_TABLE,
    LOSS_KEY_INFERRED,
    LOSS_KEY_SYNTHESIZED,
    SqlDdlEmitOptions,
    SqlDdlEmitter,
    parse_sql_script,
    snake_case,
)

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "sql_ddl_output"
_REGEN = bool(os.environ.get("APIOME_REGEN_SQL_DDL_OUTPUT"))
DIALECTS = ("postgres", "mysql", "ansi")
MODES = ("json", "tables")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _f(owner: str, name: str, ref: TypeRef, **kw: Any) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, **kw)


def _shop() -> CanonicalApi:
    """A model touching every projection rule."""
    o, line, addr = "Order", "OrderLine", "Address"
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="Shop"), title="Shop",
        types=[
            Type(key=o, name=o, kind=TypeKind.RECORD, fields=[
                _f(o, "orderId", TypeRef(name="uuid", nullable=False)),
                _f(o, "user", TypeRef(name="string", nullable=False), constraints=Constraints(max_length=40)),
                _f(o, "status", TypeRef(name="Status", nullable=False), default="open"),
                _f(o, "total", TypeRef(name="decimal", nullable=False),
                   constraints=Constraints(multiple_of=0.01, minimum=0)),
                _f(o, "weight", TypeRef(name="double"), constraints=Constraints(exclusive_maximum=500)),
                _f(o, "code", TypeRef(name="string"),
                   constraints=Constraints(pattern="^[A-Z]{3}$", min_length=3)),
                _f(o, "placedAt", TypeRef(name="timestamp", nullable=False)),
                _f(o, "shipTo", TypeRef(name=addr)),
                _f(o, "lines", TypeRef(item=TypeRef(name=line), nullable=False)),
                _f(o, "tags", TypeRef(item=TypeRef(name="string"))),
                _f(o, "payment", TypeRef(name="Payment")),
            ]),
            Type(key=line, name=line, kind=TypeKind.RECORD, fields=[
                _f(line, "sku", TypeRef(name="string", nullable=False), constraints=Constraints(max_length=16)),
                _f(line, "qty", TypeRef(name="i32", nullable=False), constraints=Constraints(minimum=1)),
            ]),
            Type(key=addr, name=addr, kind=TypeKind.RECORD, fields=[
                _f(addr, "id", TypeRef(name="i64", nullable=False)),
                _f(addr, "city", TypeRef(name="string")),
            ]),
            Type(key="Status", name="Status", kind=TypeKind.ENUM, enum_values=[
                EnumValue(key="Status.open", name="open", value="open"),
                EnumValue(key="Status.shipped", name="shipped", value="shipped"),
            ]),
            Type(key="Payment", name="Payment", kind=TypeKind.UNION, union_members=[line, addr]),
        ],
    )


def _emit(api: CanonicalApi, **options: Any) -> Any:
    return SqlDdlEmitter().emit(api, opts=coerce_emit_options(SqlDdlEmitter, options))


def _sql(api: CanonicalApi, **options: Any) -> str:
    return _emit(api, **options).files[0].content


def _subjects(result: Any) -> List[str]:
    return sorted({loss.subject for loss in result.losses})


# ===========================================================================
# Deterministic, pinned output
# ===========================================================================


@pytest.mark.parametrize("nested", MODES)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_shop_script_matches_its_golden(dialect: str, nested: str) -> None:
    script = _sql(_shop(), dialect=dialect, nested=nested)
    assert script == _sql(_shop(), dialect=dialect, nested=nested)  # deterministic
    golden = _GOLDEN / f"shop-{dialect}-{nested}.sql"
    if _REGEN:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(script, encoding="utf-8")
    assert script == golden.read_text(encoding="utf-8")


# ===========================================================================
# Column rules
# ===========================================================================


def test_postgres_columns_types_and_checks() -> None:
    sql = _sql(_shop())
    assert "CREATE TYPE \"status\" AS ENUM ('open', 'shipped');" in sql
    assert "order_id UUID NOT NULL" in sql
    assert '"user" VARCHAR(40) NOT NULL' in sql  # reserved word quoted, maxLength sizes the VARCHAR
    assert "\"status\" \"status\" NOT NULL DEFAULT 'open'" in sql
    assert "total NUMERIC(38, 2) NOT NULL CHECK (total >= 0)" in sql
    assert "weight DOUBLE PRECISION CHECK (weight < 500)" in sql
    assert "CHECK (CHAR_LENGTH(code) >= 3) CHECK (code ~ '^[A-Z]{3}$')" in sql
    assert "placed_at TIMESTAMPTZ NOT NULL" in sql
    assert "tags TEXT[]" in sql
    assert "ship_to JSONB" in sql and "payment JSONB" in sql and "lines JSONB NOT NULL" in sql


def test_mysql_and_ansi_spell_the_same_model_their_way() -> None:
    mysql = _sql(_shop(), dialect="mysql")
    assert "`status` ENUM('open', 'shipped') NOT NULL DEFAULT 'open'" in mysql
    assert "order_id CHAR(36) NOT NULL" in mysql
    assert "`user` VARCHAR(40) NOT NULL" in mysql
    assert "REGEXP_LIKE(code, '^[A-Z]{3}$')" in mysql
    assert "placed_at DATETIME(6) NOT NULL" in mysql
    assert "tags JSON" in mysql
    ansi = _sql(_shop(), dialect="ansi")
    assert "\"status\" VARCHAR(7) NOT NULL DEFAULT 'open' CHECK (\"status\" IN ('open', 'shipped'))" in ansi
    assert "placed_at TIMESTAMP WITH TIME ZONE NOT NULL" in ansi
    assert "~" not in ansi and "REGEXP" not in ansi  # no regular-expression check in standard SQL


def test_what_a_dialect_cannot_carry_is_reported() -> None:
    ansi = _emit(_shop(), dialect="ansi")
    assert "sql-constraint-dropped" in _subjects(ansi)  # the pattern
    mysql = _emit(_shop(), dialect="mysql")
    assert "sql-type-approximated" in _subjects(mysql)  # UUID as CHAR(36), DATETIME without a zone
    assert "sql-as-json" in _subjects(_emit(_shop()))   # nested object, union, list of records


# ===========================================================================
# nested=tables: keys, foreign keys, junction and child tables — all SYNTH
# ===========================================================================


def test_tables_mode_writes_keys_foreign_keys_and_junction_tables() -> None:
    result = _emit(_shop(), nested="tables")
    sql = result.files[0].content
    assert "CREATE TABLE \"order\" (\n  id BIGINT GENERATED BY DEFAULT AS IDENTITY NOT NULL" in sql
    assert "PRIMARY KEY (id)" in sql
    assert "ship_to_id BIGINT" in sql                       # Address is keyed by its non-null id
    assert "CREATE TABLE order_lines (" in sql               # junction to order_line
    assert "CREATE TABLE order_tags (" in sql                # child table of values
    assert "FOREIGN KEY (ship_to_id) REFERENCES address (id)" in sql
    assert "FOREIGN KEY (order_id) REFERENCES \"order\" (id)" in sql
    assert {LOSS_KEY_SYNTHESIZED, LOSS_KEY_INFERRED, LOSS_JUNCTION_TABLE, "sql-child-table"} <= set(_subjects(result))


def test_projection_decisions_are_synth_verdicts_in_the_report() -> None:
    report = compute_lossiness_for_emitter(_shop(), SqlDdlEmitter, options={"nested": "tables"})
    synth = {item.target_mapping for item in report.items if item.kind is LossinessKind.SYNTH}
    assert {LOSS_KEY_SYNTHESIZED, LOSS_KEY_INFERRED, LOSS_JUNCTION_TABLE, "sql-child-table",
            "sql-identifier-renamed"} <= synth
    json_report = compute_lossiness_for_emitter(_shop(), SqlDdlEmitter, options={"nested": "json"})
    assert LOSS_JUNCTION_TABLE not in {item.target_mapping for item in json_report.items}
    approx = {item.target_mapping for item in json_report.items if item.kind is LossinessKind.APPROX}
    assert "sql-as-json" in approx


def test_a_key_is_never_taken_from_a_nested_id_field() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="x"),
                       types=[
                           Type(key="A", name="A", kind=TypeKind.RECORD,
                                fields=[_f("A", "Id", TypeRef(name="B", nullable=False))]),
                           Type(key="B", name="B", kind=TypeKind.RECORD,
                                fields=[_f("B", "v", TypeRef(name="string"))]),
                       ])
    sql = _sql(api, nested="tables")
    assert "row_id BIGINT GENERATED BY DEFAULT AS IDENTITY NOT NULL" in sql
    assert "PRIMARY KEY (row_id)" in sql


# ===========================================================================
# Identifiers
# ===========================================================================


@pytest.mark.parametrize(("source", "expected"), [
    ("OrderLine", "order_line"), ("orderLine", "order_line"), ("HTTPStatus", "http_status"),
    ("order-line items", "order_line_items"), ("__x__", "x"), ("", "x"),
])
def test_snake_case(source: str, expected: str) -> None:
    assert snake_case(source) == expected


def test_identifiers_are_unique_capped_and_prefixed() -> None:
    long_name = "a" * 80
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="x"),
                       types=[Type(key="T", name="9lives", kind=TypeKind.RECORD, fields=[
                           _f("T", "orderId", TypeRef(name="string")),
                           _f("T", "order_id", TypeRef(name="string")),
                           _f("T", long_name, TypeRef(name="string")),
                       ])])
    sql = _sql(api)
    assert "CREATE TABLE t_9lives (" in sql
    assert "order_id TEXT" in sql and "order_id_2 TEXT" in sql
    column = next(line.split()[0] for line in sql.splitlines() if line.strip().startswith("aaaa"))
    assert len(column) == 63 and re.fullmatch(r"a+_[0-9a-f]{8}", column)


# ===========================================================================
# An imported SQL item
# ===========================================================================


def _sql_item(path: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source({"id": "i", "name": file.stem, "source_format": "sql-ddl",
                                    "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api


def test_a_postgres_item_written_as_postgres_keeps_its_keys_types_and_defaults() -> None:
    result = _emit(_sql_item("sql-ddl/02-typical-postgres.sql"))
    assert not [s for s in _subjects(result) if s != "sql-identifier-renamed"]
    sql = result.files[0].content
    assert "PRIMARY KEY" in sql and "FOREIGN KEY" in sql and "DEFAULT" in sql


def test_a_dialect_clause_written_for_another_dialect_is_dropped_and_reported() -> None:
    result = _emit(_sql_item("sql-ddl/02-typical-postgres.sql"), dialect="mysql")
    assert "sql-dialect-clause-dropped" in _subjects(result)


@pytest.mark.parametrize("dialect", DIALECTS)
def test_the_script_reads_back_through_the_sql_ddl_importer(dialect: str) -> None:
    api = _shop()
    source = get_import_source("sql-ddl")
    back = source.normalize(source.parse(_sql(api, dialect=dialect)))
    tables = sorted(t.name for t in back.types if t.kind is TypeKind.RECORD)
    assert tables == ["address", "order", "order_line"]
    order = next(t for t in back.types if t.name == "order")
    assert {"order_id", "user", "status", "total", "placed_at"} <= {f.name for f in order.fields}
    assert next(f for f in order.fields if f.name == "user").type.nullable is False


# ===========================================================================
# Every corpus source: parses per dialect, applies to PostgreSQL
# ===========================================================================


def _corpus_models() -> Iterator[tuple[str, CanonicalApi]]:
    from corpus_roundtrip import representatives_by_format
    from export_conformance import _import_entry

    for family, entry in sorted(representatives_by_format().items()):
        if entry is None:
            continue
        try:
            api = _import_entry(entry)
        except Exception:  # noqa: BLE001 - the import matrix owns import failures
            continue
        if any(t.kind is TypeKind.RECORD for t in api.types):
            yield family, api


def test_every_corpus_script_parses_in_its_dialect() -> None:
    checked, failures = 0, []
    for family, api in _corpus_models():
        for dialect in DIALECTS:
            for nested in MODES:
                try:
                    script = _sql(api, dialect=dialect, nested=nested)  # the emitter parses it with sqlglot
                    parse_sql_script(script, dialect)
                    checked += 1
                except Exception as exc:  # noqa: BLE001 - collect every failure
                    failures.append(f"{family} {dialect}/{nested}: {exc}")
    assert checked > 300
    assert not failures, "\n".join(failures[:20])


def test_a_script_that_does_not_parse_is_refused() -> None:
    with pytest.raises(ValueError, match="does not parse"):
        parse_sql_script("CREATE TABLE (", "postgres")


@pytest.fixture(scope="module")
def pg() -> Iterator[Any]:
    """A connection to the local PostgreSQL, or skip."""
    psycopg2 = pytest.importorskip("psycopg2")
    from app.config import settings

    try:
        connection = psycopg2.connect(settings.effective_database_url, connect_timeout=3)
    except Exception as exc:  # noqa: BLE001 - no database here
        pytest.skip(f"no PostgreSQL reachable: {exc}")
    yield connection
    connection.close()


def _apply(pg: Any, script: str) -> None:
    """Run ``script`` in a transaction and roll it back: nothing persists."""
    cursor = pg.cursor()
    try:
        cursor.execute(script)
    finally:
        pg.rollback()


@pytest.mark.parametrize("nested", MODES)
def test_the_shop_script_applies_to_postgres(pg: Any, nested: str) -> None:
    schema = f"apiome_ddl_{uuid.uuid4().hex[:8]}"
    _apply(pg, _sql(_shop(), nested=nested, schema_name=schema))


def test_every_corpus_postgres_script_applies_to_postgres(pg: Any) -> None:
    failures = []
    for family, api in _corpus_models():
        for nested in MODES:
            script = _sql(api, nested=nested, schema_name=f"apiome_ddl_{uuid.uuid4().hex[:8]}")
            try:
                _apply(pg, script)
            except Exception as exc:  # noqa: BLE001 - collect every failure
                failures.append(f"{family} {nested}: {str(exc).splitlines()[0]}")
    assert not failures, "\n".join(failures[:20])


# ===========================================================================
# Options, refusals, the card and the gate
# ===========================================================================


@pytest.mark.parametrize("options", [{"dialect": "oracle"}, {"nested": "flat"}, {"schema_name": "bad name"}])
def test_invalid_options_are_rejected(options: Dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        SqlDdlEmitOptions(**options)


def test_schema_name_qualifies_every_table_and_type() -> None:
    sql = _sql(_shop(), schema_name="shop")
    assert sql.count("CREATE SCHEMA shop;") == 1
    assert 'CREATE TYPE shop."status" AS ENUM' in sql and 'CREATE TABLE shop."order"' in sql
    assert '"status" shop."status" NOT NULL' in sql


def test_a_model_with_no_record_is_refused_and_offered_greyed_out() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="x"),
                       types=[Type(key="E", name="E", kind=TypeKind.ENUM,
                                   enum_values=[EnumValue(key="E.a", name="a")])])
    with pytest.raises(EmitPreconditionError):
        _emit(api)
    card = next(e for e in build_target_fidelity_entries(api) if e.descriptor.key == "sql-ddl")
    assert card.descriptor.available is False


def test_operations_get_the_types_only_advisory() -> None:
    file = _EXAMPLES / "openapi/30-openapi-3.0-petstore.yaml"
    api = build_conversion_source({"id": "i", "name": "pets", "source_format": "openapi",
                                   "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api
    card = next(e for e in build_target_fidelity_entries(api) if e.descriptor.key == "sql-ddl")
    assert card.fidelity.tier.value == "types-only"
    assert "services-dropped" in _subjects(_emit(api))


async def test_the_gate_reads_the_script_back() -> None:
    api = _shop()
    verdict = await validate_emitted_artifact("sql-ddl", _emit(api), api=api)
    assert verdict.validated and verdict.valid, verdict.errors
