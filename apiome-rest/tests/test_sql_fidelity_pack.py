"""SQL fidelity pack — MFX-35.4 (#4314).

Pins :class:`app.sql_ddl_emitter.SqlDdlFidelityRulePack` against the issue's acceptance criteria:

* **operation-bearing sources warn critically** — every operation, channel and service is ``DROP``ped and
  the report starts with the critical types-only advisory (the MFX-19.2 tier), with counts; the transcoding
  guard classifies the export ``near-empty``;
* **projection SYNTH items are enumerated** — every synthesized key, inferred key, junction and child table,
  renamed identifier and table the script declares under a new key is its own ``SYNTH`` item.

Plus the rest of the rule set: a union is ``APPROX`` (its value is stored whole in a JSON column — JSONB on
PostgreSQL — with no table per variant), and constraints a column keeps (bounds, lengths, enumerations,
patterns as ``CHECK`` clauses, ``maxLength`` as the ``VARCHAR`` size) are ``OK`` — under the key the column
reads back as when its table is renamed — while one SQL cannot hold is ``DROP``ped or ``APPROX``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List

import pytest

from app.canonical_model import (
    ApiIdentity,
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Channel,
    Constraints,
    Operation,
    OperationKind,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from app.catalog_conversion import build_conversion_source
from app.emitter import load_builtin_emitters
from app.fidelity_engine import compute_lossiness_for_emitter
from app.import_source import load_builtin_import_sources
from app.lossiness import LossinessKind, LossinessReport, LossinessSeverity, LossItem
from app.sql_ddl_emitter import SqlDdlEmitter
from app.transcoding_guards import TranscodeVerdict, classify_transcode

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_KEPT = "constraints → SQL column rules"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _report(api: CanonicalApi, **options: Any) -> LossinessReport:
    return compute_lossiness_for_emitter(api, SqlDdlEmitter, options=options or None)


def _items(report: LossinessReport, **match: Any) -> List[LossItem]:
    return [i for i in report.items if all(getattr(i, k) == v for k, v in match.items())]


def _f(owner: str, name: str, type_: str, **constraints: Any) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=TypeRef(name=type_),
                          constraints=Constraints(**constraints) if constraints else None)


def _model(*types: Type, **fields: Any) -> CanonicalApi:
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="m"),
                        types=list(types), **fields)


# ===========================================================================
# Operation-bearing sources warn critically
# ===========================================================================


def test_an_operation_bearing_source_gets_the_critical_types_only_advisory() -> None:
    file = _EXAMPLES / "openapi/30-openapi-3.0-petstore.yaml"
    api = build_conversion_source({"id": "i", "name": "pets", "source_format": "openapi",
                                   "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}).api
    report = _report(api)
    [advisory] = _items(report, construct_key="", target_mapping="types-only")
    assert advisory.kind is LossinessKind.DROP and advisory.severity is LossinessSeverity.CRITICAL
    operations = len(api.operations())
    assert f"{len(api.services)} service(s) with {operations} operation(s)" in advisory.message
    assert "OpenAPI or AsyncAPI" in advisory.message
    for operation in api.operations():
        [item] = _items(report, construct_key=operation.key)
        assert item.kind is LossinessKind.DROP and "types-only" in item.message
    guard = classify_transcode(api, SqlDdlEmitter, report=report)
    assert guard.verdict is TranscodeVerdict.NEAR_EMPTY and guard.dropped_operations == operations


def test_channels_and_services_are_dropped_too() -> None:
    api = _model(
        Type(key="Event", name="Event", kind=TypeKind.RECORD, fields=[_f("Event", "id", "string")]),
        services=[Service(key="events", name="events", operations=[
            Operation(key="events.emitted", name="emitted", kind=OperationKind.PUBLISH, channel_ref="evt")])],
        channels=[Channel(key="evt", address="evt")],
    )
    report = _report(api)
    for key in ("events", "events.emitted", "evt"):
        assert [i.kind for i in _items(report, construct_key=key)] == [LossinessKind.DROP], key
    assert "1 channel(s)" in _items(report, target_mapping="types-only")[0].message


def test_a_types_only_source_gets_no_advisory() -> None:
    report = _report(_model(Type(key="t", name="t", kind=TypeKind.RECORD, fields=[_f("t", "a", "string")])))
    assert not _items(report, target_mapping="types-only")


# ===========================================================================
# Projection SYNTH items are enumerated
# ===========================================================================


def _shop() -> CanonicalApi:
    line = Type(key="OrderLine", name="OrderLine", kind=TypeKind.RECORD, fields=[
        _f("OrderLine", "sku", "string"), _f("OrderLine", "price", "decimal")])
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Order.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Order.lines", name="lines", type=TypeRef(item=TypeRef(name="OrderLine"))),
        CanonicalField(key="Order.tags", name="tags", type=TypeRef(item=TypeRef(name="string"))),
        _f("Order", "placedAt", "timestamp"),
    ])
    return _model(line, order)


def test_every_projection_decision_is_its_own_synth_item() -> None:
    report = _report(_shop(), nested="tables")
    synth = {(i.construct_key, i.target_mapping) for i in _items(report, kind=LossinessKind.SYNTH)}
    mappings = {m for _key, m in synth}
    # The key Order already has (id), the one OrderLine gets, the junction and child tables, the renames…
    assert {"sql-key-inferred", "sql-key-synthesized", "sql-junction-table", "sql-child-table",
            "sql-identifier-renamed"} <= mappings
    # A decimal with no scale: PostgreSQL writes NUMERIC, MySQL has to choose one.
    mysql = {i.target_mapping for i in _items(_report(_shop(), nested="tables", dialect="mysql"),
                                              kind=LossinessKind.SYNTH)}
    assert "sql-precision-synthesized" in mysql and "sql-precision-synthesized" not in mappings
    # …and every table the script declares under a key the source does not have.
    tables = {key for key, mapping in synth if mapping == "sql table"}
    assert {"order", "order_line"} <= tables and any("tags" in key for key in tables)
    assert all(i.message.strip() for i in _items(report, kind=LossinessKind.SYNTH))


def test_json_nesting_writes_no_junction_but_approximates_the_nesting() -> None:
    report = _report(_shop(), nested="json")
    mappings = {i.target_mapping for i in report.items}
    assert "sql-junction-table" not in mappings and "sql-child-table" not in mappings
    assert _items(report, construct_key="Order.lines", kind=LossinessKind.APPROX)


# ===========================================================================
# Unions → a JSON column (APPROX)
# ===========================================================================


@pytest.mark.parametrize(("dialect", "column"), [("postgres", "JSONB"), ("mysql", "JSON"), ("ansi", "JSON")])
def test_a_union_is_a_json_column(dialect: str, column: str) -> None:
    shape = Type(key="Shape", name="Shape", kind=TypeKind.UNION, union_members=["Circle", "Square"])
    circle = Type(key="Circle", name="Circle", kind=TypeKind.RECORD, fields=[_f("Circle", "r", "number")])
    square = Type(key="Square", name="Square", kind=TypeKind.RECORD, fields=[_f("Square", "side", "number")])
    picture = Type(key="Picture", name="Picture", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Picture.shape", name="shape", type=TypeRef(name="Shape"))])
    report = _report(_model(shape, circle, square, picture), dialect=dialect)
    kinds = {i.kind: i for i in _items(report, construct_key="Shape")}
    assert set(kinds) == {LossinessKind.DROP, LossinessKind.APPROX}
    assert f"JSON column ({column})" in kinds[LossinessKind.APPROX].message
    assert "no table per variant" in kinds[LossinessKind.APPROX].message
    assert _items(report, construct_key="Picture.shape", kind=LossinessKind.APPROX)


# ===========================================================================
# Constraints → CHECK (largely OK)
# ===========================================================================


def _constrained(name: str = "item") -> CanonicalApi:
    return _model(Type(key=name, name=name, kind=TypeKind.RECORD, fields=[
        _f(name, "qty", "integer", minimum=1, maximum=99),
        _f(name, "code", "string", pattern="^[A-Z]+$", max_length=8),
        _f(name, "size", "string", enum=["s", "m", "l"]),
        _f(name, "label", "string", min_length=2),
    ]))


def test_kept_constraints_are_ok_on_a_table_that_keeps_its_name() -> None:
    report = _report(_constrained())
    for key, needle in (("item.qty", "CHECK (qty >= 1)"), ("item.code", "VARCHAR(8)"),
                        ("item.size", "IN"), ("item.label", "length")):
        [ok] = _items(report, construct_key=key, target_mapping=_KEPT)
        assert ok.kind is LossinessKind.OK and needle in ok.message, key
    assert "pattern as a CHECK (~ regular expression)" in _items(report, construct_key="item.code")[0].message


def test_kept_constraints_are_filed_where_a_renamed_table_reads_back() -> None:
    report = _report(_constrained("Item"))
    assert not _items(report, construct_key="Item.qty", target_mapping=_KEPT)
    [ok] = _items(report, construct_key="item.qty", target_mapping=_KEPT)
    assert ok.kind is LossinessKind.OK and "'Item.qty'" in ok.message


def test_a_pattern_standard_sql_cannot_check_is_dropped_and_claims_nothing() -> None:
    report = _report(_constrained(), dialect="ansi")
    code = _items(report, construct_key="item.code")
    assert [i.kind for i in code] == [LossinessKind.DROP]
    assert "regular-expression" in code[0].message
    assert _items(report, construct_key="item.qty", target_mapping=_KEPT)  # bounds are still kept


def test_a_constraint_with_no_column_rule_is_approximated_not_silent() -> None:
    api = _model(Type(key="item", name="item", kind=TypeKind.RECORD, fields=[
        _f("item", "note", "string", min_items=1)]))
    [item] = _items(_report(api), construct_key="item.note")
    assert item.kind is LossinessKind.APPROX and item.target_mapping == "constraints → not written"
    assert "min_items" in item.message


def test_a_mysql_pattern_is_kept_with_regexp_like() -> None:
    [ok] = _items(_report(_constrained(), dialect="mysql"), construct_key="item.code", target_mapping=_KEPT)
    assert "REGEXP_LIKE" in ok.message


def test_every_item_has_a_message() -> None:
    for api in (_shop(), _constrained(), _constrained("Item")):
        assert all(i.message.strip() for i in _report(api, nested="tables").items)
