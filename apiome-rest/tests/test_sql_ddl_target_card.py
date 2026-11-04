"""SQL DDL target card + CLI + fixtures — MFX-35.5 (#4315).

What the ``sql-ddl`` export target (MFX-35.1 DDL, MFX-35.2 DBML / Prisma, MFX-35.3 Liquibase / Flyway, MFX-35.4
fidelity pack) shows and writes on every export surface, pinned in ``fixtures/sql_ddl_target/outcomes.json``
(regenerate with ``APIOME_REGEN_SQL_DDL_TARGET=1``):

* **the card** — per source kind (a REST API, a GraphQL schema, a JSON Schema item, an imported SQL script and
  a gateway configuration): offered with its fidelity tier and preserved share — an API with operations badges
  **types-only** — or greyed out with the reason (a gateway configuration has no record type);
* **every output** — ``ddl`` in each dialect (``postgres``, ``mysql``, ``ansi``), ``nested=tables``, ``dbml``,
  ``prisma``, ``liquibase`` and ``flyway``: each writes its file, parses in its dialect (sqlglot — the MFX-5.1
  alternate-validator seam) and passes the export gate;
* **browse** — the public ``…/document`` route delivers the script;
* **the CLI and UI fixtures** — ``apiome-cli/tests/fixtures/export-targets-sql-ddl.json`` and
  ``apiome-ui/tests/fixtures/export-targets-sql-ddl-{rest,sql,gateway}.json`` carry the live descriptor, options
  schema, defaults and card badge; ``apiome-cli/tests/fixtures/export-job-completed-sql-ddl-types-only.json``
  carries the Petstore export's live fidelity envelope (summary, **report**, advisory) and file name.

The pinned outcomes use only sources that import without an external toolchain, so they reproduce anywhere.
A DBML, Prisma or Liquibase check whose tool is not installed reports *skipped*, which is still not a failure.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict

import pytest

from app.catalog_conversion import build_conversion_source
from app.emitter import coerce_emit_options, get_emitter, load_builtin_emitters
from app.export_fidelity import build_export_fidelity
from app.export_routes import build_target_fidelity_entries, render_emitted_document
from app.export_validation import validate_emitted_artifact
from app.import_source import load_builtin_import_sources
from app.sql_changelog import changelog_statements
from app.sql_ddl_emitter import parse_sql_script

_TESTS = Path(__file__).resolve().parent
_EXAMPLES = _TESTS.parents[1] / "apiome-ui" / "examples"
_GOLDEN = _TESTS / "fixtures" / "sql_ddl_target" / "outcomes.json"
_CLI_FIXTURES = _TESTS.parents[1] / "apiome-cli" / "tests" / "fixtures"
_UI_FIXTURES = _TESTS.parents[1] / "apiome-ui" / "tests" / "fixtures"
_REGEN = bool(os.environ.get("APIOME_REGEN_SQL_DDL_TARGET"))
_TARGET = "sql-ddl"
_ARTIFACT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
_JOB_ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"

#: One corpus source per kind: the file and the format it is imported as.
SOURCES: Dict[str, tuple[str, str]] = {
    "rest": ("openapi/30-openapi-3.0-petstore.yaml", "openapi"),
    "graphql": ("graphql/06-union-types.graphql", "graphql"),
    "json-schema": ("json-schema/03-multiple-defs.json", "json-schema"),
    "sql": ("sql-ddl/02-typical-postgres.sql", "sql-ddl"),
    "gateway": ("kong/01-minimal-single-service.yaml", "kong"),
}
#: Sources with operations: the types-only badge and the critical advisory (MFX-35.4).
OPERATION_KINDS = ("rest", "graphql")
#: Every output the card offers, and the options that pick it.
PICKS: Dict[str, Dict[str, Any]] = {
    "ddl-postgres": {},
    "ddl-mysql": {"dialect": "mysql"},
    "ddl-ansi": {"dialect": "ansi"},
    "ddl-tables": {"nested": "tables"},
    "dbml": {"output": "dbml"},
    "prisma": {"output": "prisma"},
    "liquibase": {"output": "liquibase"},
    "flyway": {"output": "flyway", "dialect": "mysql"},
}
#: The sources whose exports are pinned for every output.
PICK_SOURCES = ("rest", "sql")
#: The UI fixtures: a REST API, an imported SQL script, and a source the target cannot export.
UI_SOURCES = ("rest", "sql", "gateway")


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_emitters()
    load_builtin_import_sources()


def _source(kind: str) -> Any:
    path, fmt = SOURCES[kind]
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


def _card(api: Any) -> Any:
    return next(entry for entry in build_target_fidelity_entries(api) if entry.descriptor.key == _TARGET)


def _emit(api: Any, options: Dict[str, Any]) -> Any:
    emitter = get_emitter(_TARGET)
    return emitter().emit(api, opts=coerce_emit_options(emitter, options))


def _outcome(api: Any, options: Dict[str, Any]) -> Dict[str, Any]:
    """The pinned facts of one export: its file, tier, preserved share and gate verdict."""
    result = _emit(api, options)
    summary = build_export_fidelity(api, get_emitter(_TARGET), options=options or None).summary
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, result, api=api, options=options))
    return {
        "files": [emitted.path for emitted in result.files],
        "media_type": result.media_type,
        "tier": summary.tier.value,
        "preserved_percent": summary.preserved_percent,
        "valid": bool(verdict.valid),
        "failed": bool(verdict.failed),
    }


def _measure() -> Dict[str, Any]:
    cards = {}
    for kind in SOURCES:
        card = _card(_source(kind))
        cards[kind] = {"available": card.descriptor.available, "tier": card.fidelity.tier.value,
                       "preserved_percent": card.fidelity.preserved_percent}
    picks = {kind: {pick: _outcome(_source(kind), options) for pick, options in PICKS.items()}
             for kind in PICK_SOURCES}
    return {"cards": cards, "picks": picks}


def _targets_body(kind: str) -> Dict[str, Any]:
    """The ``GET …/export/targets`` body for the ``kind`` source, cut to the SQL DDL target."""
    card = _card(_source(kind)).model_dump(mode="json")
    return {"artifact": _ARTIFACT, "version": "1.0.0", "targets": [card]}


def _job_body() -> Dict[str, Any]:
    """The completed export-job envelope for the Petstore export (what the CLI replays)."""
    api = _source("rest")
    result = _emit(api, {})
    return {
        "job_id": _JOB_ID,
        "state": "completed",
        "percent": 100,
        "events": [],
        "result": {
            "artifact": _ARTIFACT,
            "version_record_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "version_label": "1.0.0",
            "target": _TARGET,
            "dry_run": False,
            "fidelity": build_export_fidelity(api, get_emitter(_TARGET)).model_dump(mode="json"),
            "files": [{"path": emitted.path, "media_type": emitted.media_type,
                       "size_bytes": len(str(emitted.content).encode("utf-8"))} for emitted in result.files],
            "media_type": result.media_type,
            "download_path": f"/v1/export/acme-corp/jobs/{_JOB_ID}/download",
        },
        "error": None,
    }


def _check_recorded(path: Path, live: Dict[str, Any]) -> None:
    """``path`` holds ``live`` (written first under regen); skipped when that package is not checked out."""
    if _REGEN and path.parent.is_dir():
        path.write_text(json.dumps(live, indent=2) + "\n", encoding="utf-8")
    if not path.is_file():
        pytest.skip(f"{path.parent} is not checked out")
    assert json.loads(path.read_text(encoding="utf-8")) == live


def test_the_outcomes_match_the_fixture() -> None:
    measured = _measure()
    if _REGEN:
        _GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        _GOLDEN.write_text(json.dumps(measured, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    assert measured == json.loads(_GOLDEN.read_text(encoding="utf-8"))


def test_the_cli_targets_fixture_is_the_live_registry() -> None:
    _check_recorded(_CLI_FIXTURES / "export-targets-sql-ddl.json", _targets_body("rest"))


def test_the_cli_job_fixture_carries_the_live_report_and_file() -> None:
    _check_recorded(_CLI_FIXTURES / "export-job-completed-sql-ddl-types-only.json", _job_body())


@pytest.mark.parametrize("kind", UI_SOURCES)
def test_the_ui_targets_fixtures_are_the_live_registry(kind: str) -> None:
    _check_recorded(_UI_FIXTURES / f"export-targets-sql-ddl-{kind}.json", _targets_body(kind))


# ===========================================================================
# The card
# ===========================================================================


@pytest.mark.parametrize("kind", OPERATION_KINDS)
def test_an_api_with_operations_badges_types_only(kind: str) -> None:
    card = _card(_source(kind))
    assert card.descriptor.available and card.fidelity.tier.value == "types-only"
    assert card.descriptor.paradigm == "data_schema" and card.descriptor.multi_file is False


def test_a_source_with_no_record_type_is_greyed_out() -> None:
    card = _card(_source("gateway"))
    assert card.descriptor.available is False
    assert "at least one record type" in (card.descriptor.unavailable_reason or "")


def test_the_options_offer_every_output_and_dialect() -> None:
    schema = _card(_source("rest")).options_schema
    assert set(schema["properties"]["output"]["enum"]) == {"ddl", "dbml", "prisma", "liquibase", "flyway"}
    assert set(schema["properties"]["dialect"]["enum"]) == {"postgres", "mysql", "ansi"}
    assert {"nested", "schema_name", "from_scratch", "changeset_author"} <= set(schema["properties"])
    assert "changelog_baseline" not in schema["properties"]


# ===========================================================================
# Every output: written, parsed per dialect, through the gate
# ===========================================================================


@pytest.mark.parametrize("pick", PICKS)
@pytest.mark.parametrize("kind", PICK_SOURCES)
def test_each_output_writes_one_file_the_gate_accepts(kind: str, pick: str) -> None:
    outcome = _outcome(_source(kind), PICKS[pick])
    assert outcome["valid"] and not outcome["failed"], outcome
    assert len(outcome["files"]) == 1


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "ansi"])
@pytest.mark.parametrize("output", ["ddl", "liquibase", "flyway"])
def test_every_script_parses_in_its_dialect(output: str, dialect: str) -> None:
    text = str(_emit(_source("rest"), {"output": output, "dialect": dialect}).files[0].content)
    script = text if output == "ddl" else ";\n".join(changelog_statements(text)) + ";"
    assert parse_sql_script(script, dialect)


def test_the_file_names_of_each_output() -> None:
    names = {pick: _outcome(_source("rest"), options)["files"][0] for pick, options in PICKS.items()}
    assert names["ddl-postgres"].endswith(".sql") and names["dbml"].endswith(".dbml")
    assert names["prisma"] == "schema.prisma" and names["liquibase"].endswith(".changelog.sql")
    assert names["flyway"] == "V1__initial_schema.sql"


def test_browse_delivers_the_script() -> None:
    response = render_emitted_document(_source("rest"), _TARGET, {}, None, bundle_multi_file=True)
    assert response.media_type.startswith("application/sql")
    assert b"CREATE TABLE" in response.body


@pytest.mark.parametrize("dialect", ["postgres", "mysql", "ansi"])
def test_the_gate_parses_a_script_in_the_dialect_its_header_names(dialect: str) -> None:
    from app.emitter import EmitResult, EmittedFile

    api = _source("rest")
    good = _emit(api, {"dialect": dialect})
    assert asyncio.run(validate_emitted_artifact(_TARGET, good, api=api)).valid
    text = f"-- x: SQL DDL ({dialect}), generated by Apiome.\nCREATE TABLE (;\n"
    broken = EmitResult(files=[EmittedFile(path="x.sql", media_type="application/sql", content=text)],
                        media_type="application/sql")
    verdict = asyncio.run(validate_emitted_artifact(_TARGET, broken, api=api))
    assert verdict.failed and verdict.findings[0].keyword == "sql.parse"
