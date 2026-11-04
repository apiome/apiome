"""Liquibase / Flyway changelog mode of the SQL DDL export — MFX-35.3 (#4313).

Covers :mod:`app.sql_changelog`, the ``liquibase`` / ``flyway`` outputs of :mod:`app.sql_ddl_emitter`, the
baseline the export service loads and persists (:mod:`app.export_service`, ``apiome.export_schema_baselines``)
and the export gate (:mod:`app.liquibase_validation`), against the issue's acceptance criteria:

* **the first export emits full changesets; a re-export after a model change emits only the delta** — the
  canonical diff (MFI-3.2) against the stored baseline picks the changed records, and only their tables
  are altered, in PostgreSQL, MySQL and standard SQL;
* **changelogs validate via ``liquibase validate``** — the gate runs it against an offline database (a
  stand-in runner here; the real CLI is installed in the image and smoke-tested at build time), and
  reports the check skipped where the tool is not installed.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app import liquibase_validation
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
from app.emitter import EmitResult, EmittedFile, coerce_emit_options, load_builtin_emitters
from app.export_service import ExportPersistenceContext, emit_canonical
from app.export_validation import validate_emitted_artifact
from app.sql_changelog import (
    BASELINE_VERSION,
    LOSS_CHANGELOG_BASELINE,
    LOSS_CHANGELOG_NOT_ALTERED,
    baseline_variant,
    changelog_statements,
)
from app.sql_ddl_emitter import SqlDdlEmitter
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError

_REPO = Path(__file__).resolve().parents[2]
#: What the runner raises when the liquibase tool is not installed.
_MISSING = ToolNotAvailableError("liquibase", "liquibase")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()


def _enum(*values: str) -> Type:
    return Type(key="Status", name="Status", kind=TypeKind.ENUM,
                enum_values=[EnumValue(key=f"Status.{v}", name=v, value=v) for v in values])


def _shop(*, v2: bool = False, invoice: bool = False) -> CanonicalApi:
    """A small model; ``v2`` adds `email`, drops `fax`, makes `name` required, retypes `total`, adds an enum value."""
    customer = Type(key="Customer", name="Customer", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Customer.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Customer.name", name="name", type=TypeRef(name="string", nullable=not v2)),
        CanonicalField(key="Customer.status", name="status", type=TypeRef(name="Status")),
        CanonicalField(key="Customer.email", name="email", type=TypeRef(name="string")) if v2 else
        CanonicalField(key="Customer.fax", name="fax", type=TypeRef(name="string")),
    ])
    order = Type(key="Order", name="Order", kind=TypeKind.RECORD, fields=[
        CanonicalField(key="Order.id", name="id", type=TypeRef(name="string", nullable=False)),
        CanonicalField(key="Order.customer", name="customer", type=TypeRef(name="Customer")),
        CanonicalField(key="Order.total", name="total", type=TypeRef(name="number" if v2 else "integer")),
    ])
    types = [_enum("active", "blocked", *(["closed"] if v2 else [])), customer, order]
    if invoice:
        types.append(Type(key="Invoice", name="Invoice", kind=TypeKind.RECORD, fields=[
            CanonicalField(key="Invoice.id", name="id", type=TypeRef(name="string", nullable=False)),
            CanonicalField(key="Invoice.order", name="order", type=TypeRef(name="Order")),
        ]))
    return CanonicalApi(paradigm=ApiParadigm.DATA_SCHEMA, format="json-schema", identity=ApiIdentity(name="Shop"),
                        title="Shop", types=types)


def _emit(api: CanonicalApi, baseline: Optional[Dict[str, Any]] = None, **options: Any) -> EmitResult:
    opts = coerce_emit_options(SqlDdlEmitter, {"output": "liquibase", "nested": "tables", **options})
    if baseline is not None:
        opts = opts.model_copy(update={"changelog_baseline": baseline})
    return SqlDdlEmitter().emit(api, opts=opts)


def _text(result: EmitResult) -> str:
    return str(result.files[0].content)


def _statements(result: EmitResult) -> List[str]:
    return changelog_statements(_text(result))


def _subjects(result: EmitResult, subject: str) -> List[str]:
    return [loss.detail for loss in result.losses if loss.subject == subject]


# ===========================================================================
# First export: full changesets
# ===========================================================================


def test_the_first_liquibase_export_creates_everything() -> None:
    result = _emit(_shop())
    text = _text(result)
    assert result.files[0].path == "0001-Shop.changelog.sql"
    assert text.splitlines()[0] == "--liquibase formatted sql"
    assert [line for line in text.splitlines() if line.startswith("--changeset")] == [
        "--changeset apiome:1", "--changeset apiome:2", "--changeset apiome:3", "--changeset apiome:4"]
    statements = _statements(result)
    assert statements[0].startswith('CREATE TYPE "status" AS ENUM')
    assert [s.split("(")[0].strip() for s in statements[1:3]] == ["CREATE TABLE customer", 'CREATE TABLE "order"']
    assert statements[3].startswith('ALTER TABLE "order" ADD CONSTRAINT fk_order_1 FOREIGN KEY')
    baseline = result.changelog_baseline
    assert baseline["version"] == BASELINE_VERSION and baseline["changeset_seq"] == 4
    assert set(baseline["snapshot"]["tables"]) == {"Customer", "Order"}


def test_the_first_flyway_export_is_version_one() -> None:
    result = _emit(_shop(), output="flyway")
    assert result.files[0].path == "V1__initial_schema.sql"
    assert "--changeset" not in _text(result) and len(_statements(result)) == 4
    assert result.changelog_baseline["flyway_version"] == 1


def test_the_changeset_author_option() -> None:
    assert "--changeset platform-team:1" in _text(_emit(_shop(), changeset_author="platform-team"))
    with pytest.raises(Exception):
        coerce_emit_options(SqlDdlEmitter, {"output": "liquibase", "changeset_author": "two words"})


def test_a_schema_name_is_created_first() -> None:
    statements = _statements(_emit(_shop(), schema_name="shop"))
    assert statements[0] == "CREATE SCHEMA shop" and "CREATE TABLE shop.customer" in statements[2]


# ===========================================================================
# Re-export: only the delta
# ===========================================================================


def test_a_re_export_writes_only_the_delta_on_postgres() -> None:
    first = _emit(_shop())
    delta = _emit(_shop(v2=True, invoice=True), first.changelog_baseline)
    assert delta.files[0].path == "0005-Shop.changelog.sql"
    text = _text(delta)
    assert "--changeset apiome:5 runInTransaction:false" in text  # ALTER TYPE … ADD VALUE
    assert _statements(delta) == [
        """ALTER TYPE "status" ADD VALUE 'closed'""",
        "CREATE TABLE invoice (\n  id TEXT NOT NULL,\n  order_id TEXT,\n  PRIMARY KEY (id)\n)",
        "ALTER TABLE customer DROP COLUMN fax",
        "ALTER TABLE customer ADD COLUMN email TEXT",
        'ALTER TABLE customer ALTER COLUMN "name" SET NOT NULL',
        'ALTER TABLE "order" ALTER COLUMN total TYPE DOUBLE PRECISION',
        'ALTER TABLE invoice ADD CONSTRAINT fk_invoice_1 FOREIGN KEY (order_id) REFERENCES "order" (id)',
    ]
    assert any(note.startswith("incremental: 7 change(s)") for note in _subjects(delta, LOSS_CHANGELOG_BASELINE))
    assert delta.changelog_baseline["changeset_seq"] == 11


def test_mysql_modifies_a_changed_column_in_one_statement() -> None:
    first = _emit(_shop(), dialect="mysql", output="flyway")
    delta = _emit(_shop(v2=True), first.changelog_baseline, dialect="mysql", output="flyway")
    assert delta.files[0].path == "V2__update_schema.sql"
    statements = _statements(delta)
    assert "ALTER TABLE customer MODIFY COLUMN `name` TEXT NOT NULL" in statements
    assert "ALTER TABLE customer MODIFY COLUMN `status` ENUM('active', 'blocked', 'closed')" in statements
    assert "ALTER TABLE `order` MODIFY COLUMN total DOUBLE" in statements


def test_standard_sql_sets_the_data_type_and_reports_a_check_it_cannot_alter() -> None:
    first = _emit(_shop(), dialect="ansi", nested="json")
    delta = _emit(_shop(v2=True), first.changelog_baseline, dialect="ansi", nested="json")
    assert 'ALTER TABLE "order" ALTER COLUMN total SET DATA TYPE DOUBLE PRECISION' in _statements(delta)
    assert any("customer.status" in note for note in _subjects(delta, LOSS_CHANGELOG_NOT_ALTERED))


def test_an_unchanged_model_writes_no_statement() -> None:
    first = _emit(_shop())
    again = _emit(_shop(), first.changelog_baseline)
    assert _statements(again) == [] and "--changeset" not in _text(again)
    assert any("nothing changed" in note for note in _subjects(again, LOSS_CHANGELOG_BASELINE))
    assert again.changelog_baseline["changeset_seq"] == 4


def test_a_removed_record_drops_its_foreign_keys_before_its_table() -> None:
    first = _emit(_shop(invoice=True))
    delta = _emit(_shop(), first.changelog_baseline)
    assert _statements(delta) == ["ALTER TABLE invoice DROP CONSTRAINT fk_invoice_1", "DROP TABLE invoice"]
    assert "Invoice" not in delta.changelog_baseline["snapshot"]["tables"]


def test_a_new_foreign_key_gets_a_name_the_table_does_not_use() -> None:
    first = _emit(_shop())
    order_v2 = _shop()
    order_v2.types[2].fields.append(
        CanonicalField(key="Order.billTo", name="billTo", type=TypeRef(name="Customer")))
    delta = _emit(order_v2, first.changelog_baseline)
    assert 'ALTER TABLE "order" ADD COLUMN bill_to_id TEXT' in _statements(delta)
    assert any(s.startswith('ALTER TABLE "order" ADD CONSTRAINT fk_order_2') for s in _statements(delta))
    names = [fk["name"] for fk in delta.changelog_baseline["snapshot"]["tables"]["Order"]["foreign_keys"]]
    assert names == ["fk_order_1", "fk_order_2"]


def test_a_table_the_canonical_diff_does_not_touch_is_left_alone() -> None:
    first = _emit(_shop())
    baseline = first.changelog_baseline
    # What the database holds for `order` (say, written by an older export) differs from today's projection…
    baseline["snapshot"]["tables"]["Order"]["columns"][2]["sql_type"] = "NUMERIC"
    again = _emit(_shop(), baseline)
    # …but the model did not change, so nothing is written and the baseline keeps the database's view.
    assert _statements(again) == []
    assert again.changelog_baseline["snapshot"]["tables"]["Order"]["columns"][2]["sql_type"] == "NUMERIC"


def test_a_changed_primary_key_is_reported_not_rewritten() -> None:
    first = _emit(_shop())
    changed = _shop()
    changed.types[2].fields[0] = CanonicalField(key="Order.id", name="id", type=TypeRef(name="string"),
                                                constraints=Constraints(min_length=3))
    delta = _emit(changed, first.changelog_baseline)
    assert _subjects(delta, LOSS_CHANGELOG_NOT_ALTERED)


# ===========================================================================
# When the baseline is not used
# ===========================================================================


def test_from_scratch_ignores_the_baseline() -> None:
    first = _emit(_shop())
    fresh = _emit(_shop(v2=True), first.changelog_baseline, from_scratch=True)
    assert fresh.files[0].path == "0001-Shop.changelog.sql"
    assert len(_statements(fresh)) == 4


@pytest.mark.parametrize("change", [{"nested": "json"}, {"schema_name": "other"}, {"version": 99}])
def test_a_baseline_written_differently_starts_over_and_says_why(change: Dict[str, Any]) -> None:
    baseline = {**_emit(_shop()).changelog_baseline, **change}
    result = _emit(_shop(v2=True), baseline)
    assert result.files[0].path == "0001-Shop.changelog.sql"
    assert any("full changesets are written" in note for note in _subjects(result, LOSS_CHANGELOG_BASELINE))


def test_the_baseline_option_is_not_a_user_option() -> None:
    schema = SqlDdlEmitter.options_model.model_json_schema()
    assert "changelog_baseline" not in schema["properties"]
    assert {"from_scratch", "changeset_author"} <= set(schema["properties"])
    assert set(schema["properties"]["output"]["enum"]) == {"ddl", "dbml", "prisma", "liquibase", "flyway"}
    assert "changelog_baseline" not in coerce_emit_options(SqlDdlEmitter, {}).model_dump()


def test_other_outputs_leave_no_baseline() -> None:
    result = SqlDdlEmitter().emit(_shop(), opts=coerce_emit_options(SqlDdlEmitter, {}))
    assert result.changelog_baseline is None and result.files[0].path == "Shop.sql"


# ===========================================================================
# The export service: load the baseline, persist the next
# ===========================================================================


def _service(api: CanonicalApi, stored: Optional[Dict[str, Any]], **options: Any) -> Any:
    with patch("app.export_service.db") as db:
        db.get_export_schema_baseline.return_value = stored
        result = emit_canonical(api, "sql-ddl", opts={"output": "liquibase", "nested": "tables", **options},
                                persistence=ExportPersistenceContext(tenant_id="t-1", artifact_id="p-1"))
    return result, db


def test_the_service_persists_the_first_baseline_and_diffs_against_it_next_time() -> None:
    first, db = _service(_shop(), None)
    db.get_export_schema_baseline.assert_called_once_with("t-1", "p-1", "sql-ddl", "postgres:liquibase")
    tenant, project, target, variant, stored = db.upsert_export_schema_baseline.call_args.args
    assert (tenant, project, target, variant) == ("t-1", "p-1", "sql-ddl", "postgres:liquibase")
    second, db2 = _service(_shop(v2=True), stored)
    assert second.files[0].path == "0005-Shop.changelog.sql"
    assert db2.upsert_export_schema_baseline.call_args.args[4]["changeset_seq"] == 9


def test_the_service_keys_the_baseline_by_dialect_and_mode() -> None:
    _result, db = _service(_shop(), None, dialect="mysql", output="flyway")
    assert db.get_export_schema_baseline.call_args.args[3] == baseline_variant("mysql", "flyway") == "mysql:flyway"


def test_from_scratch_does_not_load_but_starts_a_new_baseline() -> None:
    _result, db = _service(_shop(), {"version": BASELINE_VERSION}, from_scratch=True)
    assert not db.get_export_schema_baseline.called and db.upsert_export_schema_baseline.called


def test_a_ddl_export_never_touches_the_baseline_store() -> None:
    with patch("app.export_service.db") as db:
        context = ExportPersistenceContext(tenant_id="t", artifact_id="p")
        emit_canonical(_shop(), "sql-ddl", opts={}, persistence=context)
    assert not db.get_export_schema_baseline.called and not db.upsert_export_schema_baseline.called


def test_without_persistence_a_changelog_is_full_and_nothing_is_stored() -> None:
    with patch("app.export_service.db") as db:
        result = emit_canonical(_shop(), "sql-ddl", opts={"output": "liquibase"})
    assert result.files[0].path == "0001-Shop.changelog.sql" and not db.upsert_export_schema_baseline.called


# ===========================================================================
# The export gate: structure, sqlglot, liquibase validate
# ===========================================================================


def _gate(result: EmitResult) -> Any:
    return asyncio.run(validate_emitted_artifact("sql-ddl", result, api=_shop()))


def _with_text(path: str, text: str) -> EmitResult:
    return EmitResult(files=[EmittedFile(path=path, content=text, media_type="application/sql")],
                      media_type="application/sql")


def test_the_gate_runs_liquibase_validate_offline() -> None:
    result = _emit(_shop(), dialect="mysql")
    with patch.object(liquibase_validation, "run_tool_blocking", return_value=MagicMock()) as run:
        verdict = _gate(result)
    assert verdict.valid and verdict.validated and not verdict.failed
    args = run.call_args.args[1]
    assert "--url=offline:mysql" in args and args[-1] == "validate"
    assert "--changelog-file=0001-Shop.changelog.sql" in args
    assert run.call_args.kwargs["extra_env"]["LIQUIBASE_ANALYTICS_ENABLED"] == "false"


def test_a_changelog_liquibase_rejects_fails_the_gate() -> None:
    error = ToolExecutionError("liquibase", 1, stdout="",
                               stderr="Validation Failed:\n  1 changesets had duplicate identifiers")
    with patch.object(liquibase_validation, "run_tool_blocking", side_effect=error):
        verdict = _gate(_emit(_shop()))
    assert verdict.failed
    assert [f.keyword for f in verdict.findings] == ["liquibase.validate"]
    assert "Validation Failed" in verdict.findings[0].message


def test_without_liquibase_the_check_is_skipped_not_passed() -> None:
    with patch.object(liquibase_validation, "run_tool_blocking", side_effect=_MISSING):
        verdict = _gate(_emit(_shop()))
    assert not verdict.failed and verdict.validated is False
    assert "liquibase is not installed" in (verdict.detail or "")


def test_a_duplicate_changeset_is_caught_before_liquibase() -> None:
    text = "--liquibase formatted sql\n\n--changeset a:1\nCREATE TABLE t (id INTEGER);\n\n--changeset a:1\n" \
           "CREATE TABLE u (id INTEGER);\n"
    with patch.object(liquibase_validation, "run_tool_blocking", side_effect=_MISSING):
        verdict = _gate(_with_text("0001-x.changelog.sql", text))
    assert verdict.failed and any("appears 2 times" in f.message for f in verdict.findings)


def test_a_flyway_migration_that_does_not_parse_fails_the_gate() -> None:
    text = "-- Shop: Flyway migration (postgres, full schema), generated by Apiome.\n\nCREATE TABLE (;\n"
    verdict = _gate(_with_text("V1__initial_schema.sql", text))
    assert verdict.failed and verdict.findings[0].keyword == "changelog.parse"


def test_every_dialect_and_mode_passes_the_gate() -> None:
    for dialect in ("postgres", "mysql", "ansi"):
        for output in ("liquibase", "flyway"):
            first = _emit(_shop(), dialect=dialect, output=output)
            delta = _emit(_shop(v2=True, invoice=True), first.changelog_baseline, dialect=dialect, output=output)
            with patch.object(liquibase_validation, "run_tool_blocking", return_value=MagicMock()):
                for result in (first, delta):
                    assert _gate(result).valid, (dialect, output, result.files[0].path)


def test_the_offline_database_of_each_dialect() -> None:
    assert [liquibase_validation.offline_url(d) for d in ("postgres", "mysql", "ansi")] == [
        "offline:postgresql", "offline:mysql", "offline:postgresql"]


# ===========================================================================
# The store
# ===========================================================================


def test_the_migration_creates_the_baseline_table() -> None:
    text = (_REPO / "apiome-db/scripts/V353__export_schema_baselines_4313.sql").read_text()
    for fragment in ("CREATE TABLE IF NOT EXISTS apiome.export_schema_baselines",
                     "REFERENCES apiome.tenants(id) ON DELETE CASCADE",
                     "REFERENCES apiome.projects(id) ON DELETE CASCADE",
                     "baseline      JSONB        NOT NULL",
                     "UNIQUE (tenant_id, project_id, target, variant)"):
        assert fragment in text, fragment


def test_the_database_methods_round_trip_the_document() -> None:
    from app.database import Database

    database = Database.__new__(Database)
    with patch.object(Database, "execute_query", return_value=[{"baseline": '{"version": 1}'}]) as query:
        assert database.get_export_schema_baseline("t", "p", "sql-ddl", "postgres:liquibase") == {"version": 1}
        assert query.call_args.args[1] == ("t", "p", "sql-ddl", "postgres:liquibase")
    with patch.object(Database, "execute_query", return_value=[]) as query:
        assert database.get_export_schema_baseline("t", "p", "sql-ddl", "postgres:liquibase") is None
        database.upsert_export_schema_baseline("t", "p", "sql-ddl", "postgres:liquibase", {"version": 1})
        assert "ON CONFLICT ON CONSTRAINT uq_export_schema_baselines_scope" in query.call_args.args[0]
        assert query.call_args.args[1][4] == '{"version": 1}'
