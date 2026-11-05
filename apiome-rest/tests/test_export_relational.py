"""The relational projection of a database export — MFX-45.3 (#4376).

The SQL DDL emitter returns the tables it laid the model out as (:attr:`EmitResult.relational`), and the
export preview manifest hands them to the Review step's ERD. Pinned here:

* every table, column, key and foreign key the script writes is in the projection, in written order;
* what the projection **made up** — a generated key, a nested record's foreign key, a junction table for a
  list of records, a child table for a list of values — is marked ``synthesized``, and nothing declared is;
* each table and column names the canonical construct it came from (``entity_key``);
* every output (DDL, DBML, Prisma, Liquibase, Flyway) carries the same projection; other targets carry none;
* the manifest returns it, whole, on every page.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from app.canonical_model import ApiIdentity, ApiParadigm, CanonicalApi, CanonicalField, Type, TypeKind, TypeRef
from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_preview_manifest import build_export_preview_manifest, paginate_export_preview_manifest
from app.export_relational import RelationalSchema
from app.import_source import load_builtin_import_sources
from app.sql_ddl_emitter import SqlDdlEmitter

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _f(owner: str, name: str, ref: TypeRef) -> CanonicalField:
    return CanonicalField(key=f"{owner}.{name}", name=name, type=ref)


def _shop() -> CanonicalApi:
    """An order with a nested address, a list of lines and a list of tags."""
    return CanonicalApi(
        paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="Shop"), title="Shop",
        types=[
            Type(key="Order", name="Order", kind=TypeKind.RECORD, fields=[
                _f("Order", "user", TypeRef(name="string", nullable=False)),
                _f("Order", "shipTo", TypeRef(name="Address")),
                _f("Order", "lines", TypeRef(item=TypeRef(name="OrderLine"), nullable=False)),
                _f("Order", "tags", TypeRef(item=TypeRef(name="string"))),
            ]),
            Type(key="OrderLine", name="OrderLine", kind=TypeKind.RECORD, fields=[
                _f("OrderLine", "sku", TypeRef(name="string", nullable=False)),
            ]),
            Type(key="Address", name="Address", kind=TypeKind.RECORD, fields=[
                _f("Address", "id", TypeRef(name="i64", nullable=False)),
                _f("Address", "city", TypeRef(name="string")),
            ]),
        ],
    )


def _schema(api: CanonicalApi, **options: Any) -> RelationalSchema:
    result = SqlDdlEmitter().emit(api, opts=coerce_emit_options(SqlDdlEmitter, options))
    assert result.relational is not None
    return RelationalSchema.model_validate(result.relational)


def _tables(schema: RelationalSchema) -> Dict[str, Any]:
    return {t.name: t for t in schema.tables}


# ===========================================================================
# The projection
# ===========================================================================


def test_json_mode_writes_one_table_per_record_and_makes_nothing_up() -> None:
    schema = _schema(_shop())
    assert schema.dialect == "postgres" and schema.output == "ddl"
    tables = _tables(schema)
    assert set(tables) == {"order", "order_line", "address"}
    order = tables["order"]
    assert order.kind == "table" and order.entity_key == "Order" and not order.synthesized
    assert [c.name for c in order.columns] == ["user", "ship_to", "lines", "tags"]
    assert not any(c.synthesized for t in schema.tables for c in t.columns)
    assert not any(t.foreign_keys for t in schema.tables)
    user = order.columns[0]
    assert user.type == "TEXT" and user.not_null and user.entity_key == "Order.user"


def test_tables_mode_marks_every_made_up_key_reference_junction_and_child_table() -> None:
    tables = _tables(_schema(_shop(), nested="tables"))

    # A generated key on a record with no `id`.
    order = tables["order"]
    key = order.columns[0]
    assert (key.name, key.type, key.primary_key, key.identity, key.synthesized) == ("id", "BIGINT", True, True, True)
    assert key.entity_key == "Order"
    assert order.primary_key == ["id"]

    # A non-null `id` field is the key, and it is not made up.
    address_id = next(c for c in tables["address"].columns if c.name == "id")
    assert address_id.primary_key and not address_id.synthesized

    # A nested record becomes a made-up foreign key to its table.
    ship_to = next(c for c in order.columns if c.name == "ship_to_id")
    assert ship_to.synthesized and ship_to.entity_key == "Order.shipTo"
    assert ship_to.references is not None and (ship_to.references.table, ship_to.references.column) == ("address", "id")
    [fk] = order.foreign_keys
    assert (fk.columns, fk.table, fk.ref_columns, fk.synthesized) == (["ship_to_id"], "address", ["id"], True)

    # A list of records becomes a made-up junction table.
    junction = tables["order_lines"]
    assert junction.kind == "junction" and junction.synthesized and junction.entity_key == "Order.lines"
    assert {fk.table for fk in junction.foreign_keys} == {"order", "order_line"}
    assert all(fk.synthesized for fk in junction.foreign_keys)
    assert junction.primary_key == ["order_id", "position"]
    assert all(c.synthesized for c in junction.columns)

    # A list of values becomes a made-up child table; its value column carries the data.
    child = tables["order_tags"]
    assert child.kind == "child" and child.synthesized and child.entity_key == "Order.tags"
    value = next(c for c in child.columns if c.name == "value")
    assert not value.synthesized
    assert {c.name for c in child.columns if c.synthesized} == {"order_id", "position"}


def test_a_declared_foreign_key_read_from_sql_is_not_marked_made_up() -> None:
    path = _EXAMPLES / "sql-ddl" / "02-typical-postgres.sql"
    if not path.is_file():
        pytest.skip("corpus file is not checked out")
    api = build_conversion_source({"id": "i", "name": "typical", "source_format": "sql-ddl",
                                   "format_metadata": {"sourceContent": path.read_text(encoding="utf-8")}}).api
    schema = _schema(api)
    fks = [fk for t in schema.tables for fk in t.foreign_keys]
    assert fks and not any(fk.synthesized for fk in fks)
    assert any(c.primary_key for t in schema.tables for c in t.columns)
    referencing = [c for t in schema.tables for c in t.columns if c.references is not None]
    assert referencing and not any(c.synthesized for c in referencing)


def test_unique_keys_are_marked_on_their_columns() -> None:
    schema = _schema(_shop(), nested="tables", output="prisma")
    for table in schema.tables:
        unique = {name for key in table.unique for name in key}
        assert {c.name for c in table.columns if c.unique} == unique


@pytest.mark.parametrize("output", ["ddl", "dbml", "prisma", "liquibase", "flyway"])
def test_every_output_carries_the_same_projection(output: str) -> None:
    reference = _schema(_shop(), nested="tables")
    schema = _schema(_shop(), nested="tables", output=output)
    assert schema.output == output
    assert [t.name for t in schema.tables] == [t.name for t in reference.tables]


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "ansi"])
def test_the_dialect_spells_the_types(dialect: str) -> None:
    schema = _schema(_shop(), dialect=dialect, schema_name="shop")
    assert schema.dialect == dialect and schema.schema_name == "shop"
    assert all(c.type for t in schema.tables for c in t.columns)


def test_a_non_database_target_carries_no_projection() -> None:
    emitter = get_emitter("openapi-3.1")
    assert emitter is not None
    assert emitter().emit(_shop()).relational is None


# ===========================================================================
# The manifest
# ===========================================================================


def test_the_manifest_returns_the_projection_on_every_page() -> None:
    api = _shop()
    options = {"nested": "tables"}
    emit = SqlDdlEmitter().emit(api, opts=coerce_emit_options(SqlDdlEmitter, options))
    full = build_export_preview_manifest(api, SqlDdlEmitter, emit, options=options)
    first = paginate_export_preview_manifest(full, page_size=2)
    assert first.next_cursor is not None
    second = paginate_export_preview_manifest(full, cursor=first.next_cursor, page_size=2)
    assert first.relational is not None and first.relational == second.relational
    assert {t.name for t in first.relational.tables} >= {"order", "order_lines", "order_tags"}
    dumped = first.model_dump(mode="json")
    assert dumped["relational"]["tables"][0]["columns"][0]["synthesized"] is True


def test_a_non_database_manifest_has_no_projection() -> None:
    api = _shop()
    emitter = get_emitter("openapi-3.1")
    full = build_export_preview_manifest(api, emitter, emitter().emit(api))
    assert paginate_export_preview_manifest(full).relational is None


# ===========================================================================
# Locations: a database export's entities are found through the projection
# ===========================================================================


def _located(output: str, **extra: Any) -> Dict[str, Any]:
    api = _shop()
    options = {"nested": "tables", "output": output, **extra}
    emit = SqlDdlEmitter().emit(api, opts=coerce_emit_options(SqlDdlEmitter, options))
    full = build_export_preview_manifest(api, SqlDdlEmitter, emit, options=options)
    lines = emit.files[0].content.split("\n")
    return {e.key: (e.location, lines[e.location.line - 1] if e.location else None) for e in full.entities}


def test_ddl_entities_point_at_their_table_and_column_lines() -> None:
    located = _located("ddl")
    assert located["Order"][1] == 'CREATE TABLE "order" ('
    assert located["Order.user"][1].strip().startswith('"user" TEXT')
    assert located["Order.shipTo"][1].strip().startswith("ship_to_id ")
    # A list field is the junction / child table it became.
    assert located["Order.lines"][1] == "CREATE TABLE order_lines ("
    assert located["Order.tags"][1] == "CREATE TABLE order_tags ("
    assert located["Address.id"][1].strip().startswith("id BIGINT")
    assert all(location is not None for location, _ in located.values())


def test_a_record_the_report_files_as_renamed_is_still_located_with_its_status_untouched() -> None:
    api = _shop()
    options = {"nested": "tables"}
    emit = SqlDdlEmitter().emit(api, opts=coerce_emit_options(SqlDdlEmitter, options))
    order = next(e for e in build_export_preview_manifest(api, SqlDdlEmitter, emit, options=options).entities
                 if e.key == "Order")
    # `Order` is written as `order` and reads back under that name: the report files that as a drop, and
    # the manifest keeps the report's status — but the table is on its line in the script.
    assert order.status.value == "dropped" and order.emitted is False
    assert order.location is not None and order.location.line == 16


def test_a_schema_qualified_mysql_script_is_located_too() -> None:
    located = _located("ddl", dialect="mysql", schema_name="shop")
    assert located["Order"][1].startswith("CREATE TABLE shop.`order`")
    assert located["Order.user"][1].strip().startswith("`user`")


def test_dbml_entities_point_at_their_table_and_column_lines() -> None:
    located = _located("dbml")
    assert located["Order"][1] == "Table order {"
    assert located["Order.lines"][1] == "Table order_lines {"
    assert located["OrderLine.sku"][1].strip().startswith("sku TEXT")


@pytest.mark.parametrize("output", ["prisma", "liquibase"])
def test_outputs_that_are_not_scanned_carry_no_location(output: str) -> None:
    assert all(location is None for location, _ in _located(output).values())
