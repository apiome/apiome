"""BigQuery and Spark schema modes of the Arrow export — MFX-36.2 (#4318).

Pins the ``output=bigquery`` / ``output=spark`` modes of :class:`app.arrow_emitter.ArrowEmitter` and
:mod:`app.warehouse_schemas` against the issue's acceptance criteria:

* **``bq`` accepts the schema JSON** — every emitted ``.bigquery.json`` passes BigQuery's documented
  ``TableFieldSchema`` rules (:func:`bigquery_schema_problems`); ``RECORD`` / ``REPEATED`` nesting;
* **Spark parses the DDL via ``DataType.fromDDL``** — every emitted ``.spark.ddl`` line parses under
  Spark's column-type grammar (:func:`parse_spark_ddl`); when pyspark and a Java runtime are installed,
  the real ``DataType.fromDDL`` parses it too.

Plus per-table and bundled output, the checkers' refusals, the gate, and the fidelity report.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app.arrow_emitter import ArrowEmitOptions, ArrowEmitter, check_emitted_arrow
from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import EmitResult, EmittedFile, load_builtin_emitters
from app.export_validation import validate_emitted_artifact
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind
from app.warehouse_schemas import (
    LOSS_BIGQUERY_RENAMED,
    LOSS_WAREHOUSE_APPROX,
    SparkDdlError,
    bigquery_schema_problems,
    parse_spark_ddl,
    spark_ddl_problems,
)

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _f(owner: str, name: str, type_: str, *, nullable: bool = True, item: bool = False,
       description: str | None = None, **constraints: Any) -> CanonicalField:
    ref = TypeRef(item=TypeRef(name=type_), nullable=nullable) if item else TypeRef(name=type_, nullable=nullable)
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref, description=description,
                          constraints=Constraints(**constraints) if constraints else None)


def _model(*types: Type) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="m"),
                        types=list(types))


def _shop() -> CanonicalApi:
    line = Type(key="Line", name="Line", kind=TypeKind.RECORD, fields=[
        _f("Line", "sku", "string", nullable=False), _f("Line", "qty", "int32")])
    tags = Type(key="Tags", name="Tags", kind=TypeKind.MAP, key_type=TypeRef(name="string"),
                value_type=TypeRef(name="int64"))
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, fields=[
        _f("Order", "id", "string", nullable=False, description="The order's id"),
        _f("Order", "placed", "date"),
        _f("Order", "placedAt", "string", format="date-time"),
        _f("Order", "total", "decimal", multiple_of=0.01),
        _f("Order", "count", "uint16"),
        _f("Order", "lines", "Line", item=True),
        _f("Order", "codes", "string", item=True),
        _f("Order", "tags", "Tags"),
        _f("Order", "ref", "string", format="uuid"),
        _f("Order", "extra", "any"),
        _f("Order", "ship-to", "string", description="It's \"quoted\"\nand on two lines"),
    ])
    return _model(line, tags, order)


def _imported(fmt: str, relative: str) -> CanonicalApi:
    text = (_EXAMPLES / relative).read_text(encoding="utf-8")
    return build_conversion_source({"id": "i", "name": "x", "source_format": fmt,
                                    "format_metadata": {"sourceContent": text}}).api


def _emit(api: CanonicalApi, **options: Any) -> EmitResult:
    return ArrowEmitter().emit(api, opts=ArrowEmitOptions(**options))


def _bigquery(api: CanonicalApi, **options: Any) -> List[Dict[str, Any]]:
    return json.loads(_emit(api, output="bigquery", **options).files[0].content)


def _by_name(fields: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {f["name"]: f for f in fields}


# ===========================================================================
# BigQuery
# ===========================================================================


def test_bigquery_writes_one_table_schema_per_table_that_bq_accepts() -> None:
    result = _emit(_shop(), output="bigquery")
    assert [f.path for f in result.files] == ["Order.bigquery.json"]
    fields = json.loads(result.files[0].content)
    assert bigquery_schema_problems(fields) == []
    assert isinstance(fields, list) and fields[0] == {"name": "id", "type": "STRING", "mode": "REQUIRED",
                                                      "description": "The order's id"}


def test_bigquery_nests_records_and_repeats_lists() -> None:
    fields = _by_name(_bigquery(_shop()))
    lines = fields["lines"]
    assert lines["type"] == "RECORD" and lines["mode"] == "REPEATED"
    assert _by_name(lines["fields"])["sku"] == {"name": "sku", "type": "STRING", "mode": "REQUIRED"}
    assert fields["codes"] == {"name": "codes", "type": "STRING", "mode": "REPEATED"}
    tags = fields["tags"]
    assert tags["type"] == "RECORD" and tags["mode"] == "REPEATED"
    assert [(f["name"], f["type"], f["mode"]) for f in tags["fields"]] == [
        ("key", "STRING", "REQUIRED"), ("value", "INTEGER", "NULLABLE")]


def test_bigquery_logical_types() -> None:
    fields = _by_name(_bigquery(_shop()))
    assert fields["placed"]["type"] == "DATE"
    assert fields["placedAt"]["type"] == "TIMESTAMP"
    # decimal128(38, 2) has 36 integer digits; BigQuery's NUMERIC holds at most 29, so it is BIGNUMERIC.
    total = fields["total"]
    assert (total["type"], total["precision"], total["scale"]) == ("BIGNUMERIC", "38", "2")
    assert fields["count"]["type"] == "INTEGER"
    assert fields["ref"]["type"] == "STRING"  # a UUID
    assert fields["extra"]["type"] == "JSON"


def test_bigquery_renames_illegal_column_names_and_reports_it() -> None:
    result = _emit(_shop(), output="bigquery")
    names = [f["name"] for f in json.loads(result.files[0].content)]
    assert "ship_to" in names and "ship-to" not in names
    assert any(loss.subject == LOSS_BIGQUERY_RENAMED and "ship-to" in loss.detail for loss in result.losses)


def test_bigquery_decimals_pick_numeric_or_bignumeric() -> None:
    api = _imported("arrow", "arrow/04-stress-type-coverage.json")
    fields = _by_name(_bigquery(api))
    assert fields["f_decimal128"]["type"] == "NUMERIC"
    assert fields["f_decimal256"]["type"] == "BIGNUMERIC"
    assert fields["f_timestamp_naive"]["type"] == "DATETIME"
    assert fields["f_duration"]["type"] == "INTERVAL"
    assert bigquery_schema_problems(list(fields.values())) == []


@pytest.mark.parametrize(("fields", "rule"), [
    ([], "bigquery.fields"),
    ([{"name": "1a", "type": "STRING"}], "bigquery.name"),
    ([{"name": "_PARTITIONTIME", "type": "STRING"}], "bigquery.name"),
    ([{"name": "a", "type": "STRING"}, {"name": "A", "type": "INT64"}], "bigquery.name"),
    ([{"name": "a", "type": "VARCHAR"}], "bigquery.type"),
    ([{"name": "a", "type": "STRING", "mode": "OPTIONAL"}], "bigquery.mode"),
    ([{"name": "a", "type": "RECORD"}], "bigquery.fields"),
    ([{"name": "a", "type": "STRING", "fields": [{"name": "b", "type": "STRING"}]}], "bigquery.fields"),
    ([{"name": "a", "type": "NUMERIC", "precision": "40", "scale": "2"}], "bigquery.decimal"),
    ([{"name": "a", "type": "STRING", "precision": "4"}], "bigquery.decimal"),
    ([{"name": "a", "type": "STRING", "colour": "red"}], "bigquery.field"),
    ([{"name": "a", "type": "STRING", "description": "x" * 1025}], "bigquery.description"),
])
def test_the_bigquery_checker_refuses_what_bq_refuses(fields: Any, rule: str) -> None:
    assert rule in {p["rule"] for p in bigquery_schema_problems(fields)}


def test_the_bigquery_checker_caps_nesting_at_fifteen_levels() -> None:
    leaf: Dict[str, Any] = {"name": "leaf", "type": "STRING"}
    for level in range(16):
        leaf = {"name": f"l{level}", "type": "RECORD", "fields": [leaf]}
    assert "bigquery.depth" in {p["rule"] for p in bigquery_schema_problems([leaf])}


def test_a_record_deeper_than_bigquery_allows_is_written_as_json() -> None:
    types = [Type(key="T0", name="T0", kind=TypeKind.RECORD, fields=[_f("T0", "v", "string")])]
    for n in range(1, 17):
        types.append(Type(key=f"T{n}", name=f"T{n}", kind=TypeKind.RECORD, fields=[_f(f"T{n}", "c", f"T{n - 1}")]))
    result = _emit(_model(*types), output="bigquery")
    assert check_emitted_arrow(result) == []
    assert "JSON" in result.files[0].content


# ===========================================================================
# Spark
# ===========================================================================


def test_spark_writes_one_struct_type_ddl_per_table_that_parses() -> None:
    result = _emit(_shop(), output="spark")
    assert [f.path for f in result.files] == ["Order.spark.ddl"]
    ddl = result.files[0].content
    assert ddl.count("\n") == 1
    assert parse_spark_ddl(ddl)[:3] == ["id", "placed", "placedAt"]
    assert ddl.startswith("`id` STRING NOT NULL COMMENT 'The order\\'s id', `placed` DATE, ")


def test_spark_nested_and_logical_types() -> None:
    ddl = _emit(_shop(), output="spark").files[0].content
    assert "`lines` ARRAY<STRUCT<`sku`: STRING NOT NULL, `qty`: INT>>" in ddl
    assert "`codes` ARRAY<STRING>" in ddl
    assert "`tags` MAP<STRING, BIGINT>" in ddl
    assert "`placedAt` TIMESTAMP" in ddl and "`total` DECIMAL(38, 2)" in ddl
    assert "`count` INT" in ddl  # uint16 fits a signed INT
    assert "COMMENT 'It\\'s \"quoted\"\\nand on two lines'" in ddl


def test_spark_keeps_an_arrow_source_s_types() -> None:
    api = _imported("arrow", "arrow/04-stress-type-coverage.json")
    result = _emit(api, output="spark")
    ddl = result.files[0].content
    for needle in ("`f_int8` TINYINT", "`f_timestamp_naive` TIMESTAMP_NTZ", "`f_duration` INTERVAL DAY TO SECOND",
                   "`f_decimal256` DECIMAL(38, 12)", "`f_null` VOID",
                   "`f_dense_union` STRUCT<`as_int`: INT, `as_text`: STRING, `as_bytes`: BINARY>"):
        assert needle in ddl, needle
    assert spark_ddl_problems(ddl) == []
    details = " ".join(loss.detail for loss in result.losses if loss.subject == LOSS_WAREHOUSE_APPROX)
    assert "union" in details and "38 digits" in details and "time of day" in details


@pytest.mark.parametrize("ddl", [
    "`a` INT, `b` STRING NOT NULL COMMENT 'x'",
    "a int, b struct<c: string, d array<map<string, decimal(10,2)>>>",
    "`a` STRUCT<`c` STRING>",
    "`a` INTERVAL YEAR TO MONTH, `b` INTERVAL DAY, `c` VARCHAR(10), `d` TIMESTAMP_LTZ",
    "STRUCT<a: INT, b: STRING>",
    "`we``ird` BIGINT",
])
def test_the_spark_parser_accepts_what_from_ddl_accepts(ddl: str) -> None:
    parse_spark_ddl(ddl)


@pytest.mark.parametrize("ddl", [
    "", "`a` INTT", "`a` ARRAY<INT", "`a` INT,", "`a` MAP<STRING>", "`a` DECIMAL(40, 2)",
    "`a` INT, `A` STRING", "`a` STRUCT<`b`: INT, `b`: INT>", "`a` INTERVAL MONTH TO DAY",
    "`a` INT NOT", "`a` INT COMMENT x", "`a` INT `b` INT",
])
def test_the_spark_parser_refuses_what_from_ddl_refuses(ddl: str) -> None:
    with pytest.raises(SparkDdlError):
        parse_spark_ddl(ddl)


def test_pyspark_from_ddl_parses_the_emitted_ddl() -> None:
    """With pyspark and a JVM installed, the real ``DataType.fromDDL`` parses every emitted DDL."""
    pyspark = pytest.importorskip("pyspark")
    if shutil.which("java") is None:
        pytest.skip("no Java runtime for Spark")
    from pyspark.sql import SparkSession  # noqa: PLC0415
    from pyspark.sql.types import DataType  # noqa: PLC0415

    assert pyspark
    spark = SparkSession.builder.master("local[1]").getOrCreate()
    try:
        for api in (_shop(), _imported("arrow", "arrow/04-stress-type-coverage.json")):
            for line in _emit(api, output="spark").files[0].content.splitlines():
                assert DataType.fromDDL(line).fields
    finally:
        spark.stop()


# ===========================================================================
# Per-table or bundled
# ===========================================================================


def _two_tables() -> CanonicalApi:
    a = Type(key="A", name="A", kind=TypeKind.RECORD, fields=[_f("A", "x", "string")])
    b = Type(key="B", name="B", kind=TypeKind.RECORD, fields=[_f("B", "y", "int64")])
    return _model(a, b)


def test_per_table_output_writes_a_file_per_table() -> None:
    assert [f.path for f in _emit(_two_tables(), output="bigquery").files] == ["A.bigquery.json", "B.bigquery.json"]
    assert [f.path for f in _emit(_two_tables(), output="spark").files] == ["A.spark.ddl", "B.spark.ddl"]


def test_bundled_output_writes_one_file() -> None:
    [bigquery] = _emit(_two_tables(), output="bigquery", bundle=True).files
    assert bigquery.path == "schemas.bigquery.json" and set(json.loads(bigquery.content)) == {"A", "B"}
    [spark] = _emit(_two_tables(), output="spark", bundle=True).files
    assert spark.path == "schemas.spark.ddl"
    assert spark.content == "-- A\n`x` STRING\n-- B\n`y` BIGINT\n"
    assert spark_ddl_problems(spark.content) == []


def test_the_table_option_and_the_arrow_default_still_apply() -> None:
    assert [f.path for f in _emit(_two_tables(), output="spark", table="B").files] == ["B.spark.ddl"]
    assert [f.path for f in _emit(_two_tables()).files][0] == "A.arrow.json"


# ===========================================================================
# The export gate
# ===========================================================================


@pytest.mark.parametrize(("output", "bundle"), [("bigquery", False), ("bigquery", True), ("spark", False),
                                                ("spark", True)])
def test_the_gate_passes_every_mode(output: str, bundle: bool) -> None:
    api = _shop()
    verdict = asyncio.run(validate_emitted_artifact("arrow", _emit(api, output=output, bundle=bundle), api=api))
    assert verdict.validated and verdict.valid


def test_the_gate_rejects_a_broken_bigquery_or_spark_file() -> None:
    api = _shop()
    for path, content in (("t.bigquery.json", '[{"name": "a", "type": "VARCHAR"}]'),
                          ("t.bigquery.json", "{not json"), ("t.spark.ddl", "`a` INTT\n")):
        result = EmitResult(files=[EmittedFile(path=path, content=content)])
        assert check_emitted_arrow(result), path
        verdict = asyncio.run(validate_emitted_artifact("arrow", result, api=api))
        assert verdict.validated and not verdict.valid


# ===========================================================================
# Fidelity
# ===========================================================================


def _report(api: CanonicalApi, **options: Any):
    return compute_lossiness_for_emitter(api, ArrowEmitter, options=options)


def test_warehouse_approximations_are_filed_under_their_table() -> None:
    report = _report(_shop(), output="bigquery")
    order = [i for i in report.items if i.construct_key == "Order"]
    assert order and {i.kind for i in order} == {LossinessKind.APPROX}
    assert any("map" in i.message for i in order) and any("ship-to" in i.message for i in order)
    # No round trip is measured: a nested record is not reported as re-keyed.
    assert not [i for i in report.items if i.construct_key == "Line" and i.kind is LossinessKind.DROP]


def test_spark_keeps_more_than_bigquery() -> None:
    spark = {i.message for i in _report(_shop(), output="spark").items if i.construct_key == "Order"}
    bigquery = {i.message for i in _report(_shop(), output="bigquery").items if i.construct_key == "Order"}
    assert not any("map" in m for m in spark) and any("map" in m for m in bigquery)


def test_every_item_has_a_message() -> None:
    for output in ("bigquery", "spark"):
        assert all(i.message.strip() for i in _report(_shop(), output=output).items)
