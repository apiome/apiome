"""DBML and Prisma outputs of the SQL DDL export — MFX-35.2 (#4312).

Covers :mod:`app.sql_ddl_serializers` (and the ``output`` option of :mod:`app.sql_ddl_emitter`) against
the issue's acceptance criteria:

* **DBML parses via @dbml/core; the Prisma schema passes ``prisma validate``** — every corpus source with
  a record type is written as DBML and as a Prisma schema (PostgreSQL with tables and a schema name,
  MySQL with JSON columns) and checked by the bundled ``dbml-validator`` / ``prisma-validator`` tools;
  the export validation step runs the same tools (skipped when the toolchain is not installed here);
* **one projection, three serializers** — the DBML and Prisma outputs carry the same tables, columns,
  keys, enums and foreign keys the SQL script does (pinned in ``fixtures/sql_ddl_output/``, regenerate
  with ``APIOME_REGEN_SQL_DDL_OUTPUT=1``).

Plus what each language cannot say (Prisma's missing CHECK, a relation Prisma cannot model), the
option rules, and the MySQL key fixes the Prisma output surfaced.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, List

import pytest
from test_sql_ddl_emitter import _corpus_models, _f, _shop

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, EnumValue, Type, TypeKind, TypeRef
from app.db_schema_validation import (
    DBML_VALIDATOR_TOOL_KEY,
    PRISMA_VALIDATOR_TOOL_KEY,
    db_schema_validator_available,
    validate_dbml,
    validate_prisma,
)
from app.emitter import EmitOptionsError, coerce_emit_options, load_builtin_emitters
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import get_import_source, load_builtin_import_sources
from app.lossiness import LossinessKind
from app.sql_ddl_emitter import (
    LOSS_KEY_SYNTHESIZED,
    LOSS_SERIALIZER_DROPPED,
    LOSS_TYPE_APPROX,
    SqlDdlEmitOptions,
    SqlDdlEmitter,
)

_GOLDEN = Path(__file__).resolve().parent / "fixtures" / "sql_ddl_output"
_REGEN = bool(os.environ.get("APIOME_REGEN_SQL_DDL_OUTPUT"))

needs_dbml = pytest.mark.skipif(
    not db_schema_validator_available(DBML_VALIDATOR_TOOL_KEY),
    reason="bundled dbml-validator not installed (./scripts/install_dev_toolchain.sh dbml-validator)",
)
needs_prisma = pytest.mark.skipif(
    not db_schema_validator_available(PRISMA_VALIDATOR_TOOL_KEY),
    reason="bundled prisma-validator not installed (./scripts/install_dev_toolchain.sh prisma-validator)",
)

#: An imported SQL schema: declared keys, a unique column, a 1:1 table, a foreign key to a non-unique
#: column (which Prisma cannot model), a column and a table CHECK, and an expression default.
_SQL = """
CREATE TABLE customer (id BIGINT PRIMARY KEY, email VARCHAR(200) NOT NULL UNIQUE, name TEXT,
  created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE orders (id BIGINT PRIMARY KEY, customer_email VARCHAR(200) REFERENCES customer(email),
  customer_name TEXT REFERENCES customer(name), customer_id BIGINT NOT NULL REFERENCES customer(id),
  total NUMERIC(10, 2) CHECK (total >= 0), CHECK (id > 0));
CREATE TABLE profile (customer_id BIGINT PRIMARY KEY REFERENCES customer(id), bio TEXT);
"""


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _emit(api: CanonicalApi, **options: Any) -> Any:
    return SqlDdlEmitter().emit(api, opts=coerce_emit_options(SqlDdlEmitter, options))


def _text(api: CanonicalApi, **options: Any) -> str:
    return _emit(api, **options).files[0].content


def _imported() -> CanonicalApi:
    source = get_import_source("sql-ddl")
    return source.normalize(source.parse(_SQL))


# ===========================================================================
# Deterministic, pinned output
# ===========================================================================


@pytest.mark.parametrize("nested", ("json", "tables"))
@pytest.mark.parametrize(("output", "dialect"), [
    ("dbml", "postgres"), ("dbml", "mysql"), ("dbml", "ansi"), ("prisma", "postgres"), ("prisma", "mysql"),
])
def test_the_shop_output_matches_its_golden(output: str, dialect: str, nested: str) -> None:
    text = _text(_shop(), output=output, dialect=dialect, nested=nested)
    assert text == _text(_shop(), output=output, dialect=dialect, nested=nested)  # deterministic
    golden = _GOLDEN / f"shop-{dialect}-{nested}.{output}"
    if _REGEN:
        golden.write_text(text, encoding="utf-8")
    assert text == golden.read_text(encoding="utf-8")


def test_each_output_has_its_own_file_name() -> None:
    assert _emit(_shop()).files[0].path == "Shop.sql"
    assert _emit(_shop(), output="dbml").files[0].path == "Shop.dbml"
    assert _emit(_shop(), output="prisma").files[0].path == "schema.prisma"


def test_the_outputs_share_one_projection() -> None:
    """The same tables, keys and references, whichever language writes them."""
    sql = _text(_shop(), nested="tables")
    dbml = _text(_shop(), output="dbml", nested="tables")
    prisma = _text(_shop(), output="prisma", nested="tables")
    for table in ("order_line", "address", "order_lines", "order_tags"):
        assert f"CREATE TABLE {table} (" in sql
        assert f"Table {table} {{" in dbml
        assert f'@@map("{table}")' in prisma
    assert "ALTER TABLE order_lines ADD CONSTRAINT fk_order_lines_2 FOREIGN KEY (order_line_id)" in sql
    assert "Ref fk_order_lines_2: order_lines.order_line_id > order_line.id" in dbml
    assert ('order_line OrderLine @relation("fk_order_lines_2", fields: [order_line_id], references: [id])'
            in prisma)


# ===========================================================================
# DBML
# ===========================================================================


def test_dbml_writes_enums_as_dbml_enums_in_every_dialect() -> None:
    for dialect in ("postgres", "mysql", "ansi"):
        dbml = _text(_shop(), output="dbml", dialect=dialect)
        assert 'Enum status {\n  "open"\n  "shipped"\n}' in dbml
        assert "status status [not null, default: 'open']" in dbml
        assert "ENUM(" not in dbml and " IN (" not in dbml


def test_dbml_writes_checks_as_expressions_without_backticks() -> None:
    dbml = _text(_shop(), output="dbml", dialect="mysql")
    assert "check: `REGEXP_LIKE(code, '^[A-Z]{3}$')`" in dbml
    imported = _text(_imported(), output="dbml")
    assert "checks {\n    `total >= 0`\n    `id > 0`\n  }" in imported
    assert "created_at TIMESTAMPTZ [default: `now()`]" in imported


def test_dbml_writes_composite_keys_and_the_database_type() -> None:
    dbml = _text(_shop(), output="dbml", nested="tables")
    assert "indexes {\n    (order_id, position) [pk]\n  }" in dbml
    assert "Project Shop {\n  database_type: 'PostgreSQL'\n}" in dbml
    assert "Project" not in _text(_shop(), output="dbml", dialect="ansi")


def test_dbml_gives_a_record_with_no_fields_a_key() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="x"),
                       types=[Type(key="Empty", name="Empty", kind=TypeKind.RECORD, fields=[])])
    result = _emit(api, output="dbml")
    assert "Table empty {\n  id BIGINT [pk, increment]\n}" in result.files[0].content
    assert LOSS_KEY_SYNTHESIZED in {loss.subject for loss in result.losses}
    assert "CREATE TABLE empty (\n\n);" in _text(api)  # the SQL script is unchanged


# ===========================================================================
# Prisma
# ===========================================================================


def test_prisma_models_map_back_to_their_tables() -> None:
    prisma = _text(_shop(), output="prisma", schema_name="shop")
    assert 'datasource db {\n  provider = "postgresql"\n  schemas  = ["shop"]\n}' in prisma
    assert "model OrderLine {" in prisma and '  @@map("order_line")\n  @@schema("shop")' in prisma
    assert "  id BigInt @id @default(autoincrement())" in prisma  # every model has a key
    assert "  status Status @default(open)" in prisma
    assert "  order_id String @db.Uuid" in prisma
    assert "  total Decimal @db.Decimal(38, 2)" in prisma
    assert "  tags String[]" in prisma


def test_prisma_writes_both_sides_of_every_relation() -> None:
    prisma = _text(_imported(), output="prisma")
    assert ('  customer Customer @relation("fk_orders_2", fields: [customer_id], references: [id])' in prisma)
    assert '  orders_customer Orders[] @relation("fk_orders_2")' in prisma
    # A foreign key that is the table's own primary key is one-to-one.
    assert '  profile Profile? @relation("fk_profile_1")' in prisma
    assert '  created_at DateTime? @default(dbgenerated("now()")) @db.Timestamptz' in prisma


def test_what_prisma_cannot_say_is_reported() -> None:
    result = _emit(_imported(), output="prisma")
    dropped = [loss.detail for loss in result.losses if loss.subject == LOSS_SERIALIZER_DROPPED]
    assert any("checks of column 'total'" in detail for detail in dropped)
    assert any("checks of table 'orders'" in detail for detail in dropped)
    assert any("'fk_orders_3' is kept as plain columns" in detail for detail in dropped)
    assert "fk_orders_3" not in result.files[0].content
    report = compute_lossiness_for_emitter(_imported(), SqlDdlEmitter, options={"output": "prisma"})
    assert LOSS_SERIALIZER_DROPPED in {i.target_mapping for i in report.items if i.kind is LossinessKind.DROP}


def test_prisma_names_avoid_reserved_words_and_map_odd_enum_labels() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="x"),
                       types=[
                           Type(key="String", name="String", kind=TypeKind.RECORD, fields=[
                               _f("String", "id", TypeRef(name="i64", nullable=False)),
                               _f("String", "state", TypeRef(name="State", nullable=False), default="in stock"),
                           ]),
                           Type(key="State", name="State", kind=TypeKind.ENUM, enum_values=[
                               EnumValue(key="State.a", name="a", value="in stock"),
                               EnumValue(key="State.b", name="b", value="9lives"),
                           ]),
                       ])
    prisma = _text(api, output="prisma")
    assert "model String2 {" in prisma and '@@map("string")' in prisma
    assert '  in_stock @map("in stock")\n  v_9lives @map("9lives")' in prisma
    assert "  state State @default(in_stock)" in prisma


def test_prisma_refuses_options_it_cannot_write() -> None:
    with pytest.raises(EmitOptionsError, match="standard-SQL"):
        _emit(_shop(), output="prisma", dialect="ansi")
    with pytest.raises(EmitOptionsError, match="PostgreSQL only"):
        _emit(_shop(), output="prisma", dialect="mysql", schema_name="shop")
    assert SqlDdlEmitOptions().output == "ddl"


# ===========================================================================
# The MySQL key fixes the Prisma output surfaced (shared by every output)
# ===========================================================================


def test_mysql_keys_a_text_column_as_varchar() -> None:
    api = _imported()
    sql = _text(api, dialect="mysql")
    assert "email VARCHAR(200) NOT NULL" in sql  # sized already
    unique_text = CanonicalApi(**{**api.model_dump(), "types": [
        t.model_copy(update={"fields": [f.model_copy(update={"extras": {**(f.extras or {}), "sql_data_type": "TEXT"},
                                                             "constraints": None}) if f.name == "email" else f
                                        for f in t.fields]}) for t in api.types]})
    result = _emit(unique_text, dialect="mysql")
    assert "email VARCHAR(255) NOT NULL" in result.files[0].content
    assert any("cannot key a TEXT column" in loss.detail for loss in result.losses if loss.subject == LOSS_TYPE_APPROX)


def test_a_generated_key_beside_a_composite_primary_key_stays_unique() -> None:
    source = get_import_source("sql-ddl")
    api = source.normalize(source.parse("CREATE TABLE line (order_id BIGINT, n INT, PRIMARY KEY (order_id, n));"))
    sql = _text(api, dialect="mysql", nested="tables")
    assert "id BIGINT AUTO_INCREMENT NOT NULL" in sql
    assert "PRIMARY KEY (order_id, n),\n  UNIQUE (id)" in sql


# ===========================================================================
# The reference tools
# ===========================================================================


@needs_dbml
@needs_prisma
def test_every_corpus_output_passes_its_reference_tool() -> None:
    """The acceptance criterion: DBML parses via @dbml/core; the Prisma schema passes ``prisma validate``."""
    configs = [
        ("dbml", {"dialect": "postgres", "nested": "tables", "schema_name": "app"}),
        ("dbml", {"dialect": "mysql", "nested": "json"}),
        ("prisma", {"dialect": "postgres", "nested": "tables", "schema_name": "app"}),
        ("prisma", {"dialect": "mysql", "nested": "json"}),
    ]
    jobs = [(family, output, options, _text(api, output=output, **options))
            for family, api in _corpus_models() for output, options in configs]
    assert len(jobs) > 200

    async def check_all() -> List[str]:
        gate = asyncio.Semaphore(8)

        async def one(family: str, output: str, options: dict, text: str) -> List[str]:
            async with gate:
                diagnostics = await (validate_dbml if output == "dbml" else validate_prisma)(text)
            return [f"{family} {output} {options}: {d}" for d in diagnostics]

        return [line for lines in await asyncio.gather(*(one(*job) for job in jobs)) for line in lines]

    failures = asyncio.run(check_all())
    assert not failures, "\n".join(failures[:20])


@needs_dbml
async def test_the_dbml_validator_reports_the_line_of_an_error() -> None:
    assert await validate_dbml("Table t {\n  id int [pk]\n}\n") == []
    diagnostics = await validate_dbml("Table t {\n  id int [pk\n}\n")
    assert diagnostics and diagnostics[0].line == 3


@needs_prisma
async def test_the_prisma_validator_reports_prismas_own_error() -> None:
    assert await validate_prisma(_text(_shop(), output="prisma")) == []
    diagnostics = await validate_prisma('datasource db {\n  provider = "postgresql"\n}\nmodel X {\n  id Int\n}\n')
    assert diagnostics and "unique criteria" in diagnostics[0].message and diagnostics[0].line == 4


@needs_dbml
@needs_prisma
@pytest.mark.parametrize("output", ("dbml", "prisma"))
async def test_the_export_gate_runs_the_reference_tool(output: str) -> None:
    api = _shop()
    result = _emit(api, output=output)
    verdict = await validate_emitted_artifact("sql-ddl", result, api=api)
    assert verdict.validated and verdict.valid, verdict.errors
    broken = result.model_copy(update={"files": [result.files[0].model_copy(update={"content": "model {"})]})
    verdict = await validate_emitted_artifact("sql-ddl", broken, api=api)
    assert verdict.validated and not verdict.valid
    assert verdict.findings[0].keyword == ("dbml.parse" if output == "dbml" else "prisma.validate")


async def test_the_gate_says_when_the_toolchain_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.db_schema_validation as validation

    monkeypatch.setattr(validation, "db_schema_validator_available", lambda key: False)
    api = _shop()
    verdict = await validate_emitted_artifact("sql-ddl", _emit(api, output="prisma"), api=api)
    assert verdict.applicable and not verdict.validated
    assert "prisma-validator is not installed" in (verdict.detail or "")
