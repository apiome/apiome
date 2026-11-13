"""``apiome primitives import <file>`` (CLI 5.6, #3222).

The rules (:mod:`apiome_cli.primitive_import`) and the command against a mocked REST API: the
file shapes, the local checks, the review (``POST …/import/review``) and the plan it prints, the
commit gate (``--dry-run``, the question, ``--yes``, no terminal), ``--update`` /
``--skip-conflicts``, row failures (exit 7, or ``--continue-on-error``), stdin and the round trip
from ``types list --json``, ``--report`` and ``--json``.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager

import pytest
from typer.testing import CliRunner

from apiome_cli.exit_codes import (
    EXIT_ERROR,
    EXIT_PRIMITIVE_IMPORT_FAILED,
    EXIT_SUCCESS,
    EXIT_USAGE,
)
from apiome_cli.main import app
from apiome_cli.progress import row_progress
from apiome_cli.primitive_import import (
    PROGRESS_THRESHOLD,
    STATUS_ABORTED,
    STATUS_CONFLICT,
    STATUS_FAILED,
    STATUS_IMPORTED,
    STATUS_INVALID,
    STATUS_NEW,
    STATUS_OVERWRITE,
    STATUS_SKIPPED,
    STATUS_SYSTEM,
    STATUS_UNCHANGED,
    STATUS_UPDATED,
    ImportFileError,
    ImportRow,
    RowOutcome,
    abort_outcomes,
    build_report,
    bundle_payload,
    commit_outcomes,
    convert_rows,
    describe_schema,
    has_failures,
    parse_rows,
    provenance_warning,
    render_plan,
    render_summary,
    review_outcomes,
)

runner = CliRunner()

_ENV = {
    "APIOME_API_KEY": "obj_test_key",
    "APIOME_BASE_URL": "http://localhost:8000",
    "APIOME_TENANT_ID": "acme",
}
_REVIEW = "http://localhost:8000/v1/primitives/acme/import/review"
_IMPORT = "http://localhost:8000/v1/primitives/acme/import"

_YAML = """\
- name: acme-loyalty-id
  base: string
  pattern: ^LM-[0-9]{8}$
  examples: [LM-00000001, LM-12345678]
- name: acme-region-code
  base: string
  pattern: ^(EU|US|APAC)$
- name: acme-internal-sku
  base: string
  description: Warehouse stock unit.
"""
_NAMES = ["acme-loyalty-id", "acme-region-code", "acme-internal-sku"]


@pytest.fixture(autouse=True)
def _cache_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "acme-primitives.yaml"
    path.write_text(_YAML, encoding="utf-8")
    return path


def _row(index, name, **schema):
    return ImportRow(index, name, schema or {"type": "string"})


def _review(**statuses):
    """A review response classifying each named row (``name="conflict"`` …)."""
    types = []
    for name, status in statuses.items():
        entry = {"name": name.replace("_", "-"), "status": status, "error": None}
        if status == "invalid":
            entry["error"] = {"error": "invalid_schema", "details": [{"path": "pattern", "message": "bad regex"}]}
        types.append(entry)
    return {"status": "review", "warnings": [], "types": types}


def _result(**lists):
    return {"message": "Import completed", "import_id": "imp-1", "errors": [], **lists}


def _posts(httpx_mock, url):
    return [json.loads(r.content) for r in httpx_mock.get_requests() if str(r.url) == url]


def _run(*args, json_mode=False, input=None):
    argv = (["--json"] if json_mode else []) + ["primitives", "import", *[str(arg) for arg in args]]
    return runner.invoke(app, argv, env=_ENV, input=input)


def _all_new():
    return _review(acme_loyalty_id="new", acme_region_code="new", acme_internal_sku="new")


# ---- rules: file shapes ---------------------------------------------------------------------------


def test_parse_rows_accepts_an_array_one_row_and_the_list_envelope() -> None:
    assert parse_rows([{"name": "a"}]) == [{"name": "a"}]
    assert parse_rows({"name": "a", "base": "string"}) == [{"name": "a", "base": "string"}]
    assert parse_rows({"total": 1, "items": [{"name": "a"}]}) == [{"name": "a"}]


@pytest.mark.parametrize(
    ("document", "message"),
    [
        ("text", "must hold one primitive"),
        ({"types": {}}, "must hold one primitive"),
        ({"items": "x"}, "must hold one primitive"),
        ([], "holds no primitives"),
        ({"items": []}, "holds no primitives"),
    ],
)
def test_parse_rows_refuses_other_shapes(document, message) -> None:
    with pytest.raises(ImportFileError, match=message):
        parse_rows(document)


# ---- rules: rows ----------------------------------------------------------------------------------


def test_a_shorthand_row_becomes_a_schema_with_base_as_type() -> None:
    rows, outcomes = convert_rows(
        [{"name": " acme-id ", "base": "string", "pattern": "^A$", "examples": ["A"], "description": "An id."}]
    )
    assert outcomes == []
    assert rows == [
        ImportRow(1, "acme-id", {"type": "string", "pattern": "^A$", "examples": ["A"], "description": "An id."})
    ]


def test_type_is_accepted_in_place_of_base() -> None:
    rows, outcomes = convert_rows([{"name": "n", "type": "integer", "minimum": 0}])
    assert outcomes == [] and rows[0].schema == {"type": "integer", "minimum": 0}


def test_a_rest_row_keeps_its_schema_and_gains_the_row_description_and_tags() -> None:
    schema = {"$id": "https://api.apiome.dev/types/tenant/acme/acme-id", "type": "string"}
    rows, outcomes = convert_rows(
        [{"id": "p1", "name": "acme-id", "schema": schema, "description": "An id.", "tags": ["acme"], "category": "x"}]
    )
    assert outcomes == []
    assert rows[0].schema == {**schema, "description": "An id.", "tags": ["acme"]}
    assert "description" not in schema  # the caller's row is not changed


def test_a_rest_rows_own_schema_description_wins() -> None:
    rows, _ = convert_rows([{"name": "n", "schema": {"type": "string", "description": "Kept."}, "description": "Row."}])
    assert rows[0].schema["description"] == "Kept."


def test_system_rows_are_set_aside_not_failed() -> None:
    rows, outcomes = convert_rows([{"name": "string", "schema": {"type": "string"}, "is_system": True}])
    assert rows == []
    assert outcomes == [RowOutcome(1, "string", STATUS_SYSTEM, "System primitives are read-only.")]
    assert not has_failures(outcomes)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ("text", "must be an object"),
        ({"base": "string"}, "name: is required"),
        ({"name": " ", "base": "string"}, "name: is required"),
        ({"name": 7, "base": "string"}, "name: is required"),
        ({"name": "n"}, "base: is required"),
        ({"name": "n", "base": "strng"}, "'strng' is not one of"),
        ({"name": "n", "base": "string", "type": "integer"}, "differs from type"),
        ({"name": "n", "schema": "string"}, "schema: must be an object"),
        ({"name": "n", "base": "string", "pattern": "^(a$"}, "pattern: not a regular expression"),
        ({"name": "n", "base": "string", "minLength": "long"}, "schema.minLength"),
        ({"name": "n", "base": "string", "pattern": "^LM-[0-9]{8}$", "examples": ["LM-1"]}, r"examples\[0\]"),
    ],
)
def test_invalid_rows_say_what_is_wrong(row, message) -> None:
    rows, outcomes = convert_rows([row])
    assert rows == []
    assert [outcome.status for outcome in outcomes] == [STATUS_INVALID]
    assert outcomes[0].index == 1
    assert re.search(message, outcomes[0].message), outcomes[0].message


def test_a_row_reports_every_problem_it_has() -> None:
    _, outcomes = convert_rows([{"base": "strng"}])
    assert outcomes[0].message.startswith("name: is required; base: 'strng'")


def test_a_repeated_name_is_invalid_and_names_the_first_row() -> None:
    rows, outcomes = convert_rows([{"name": "n", "base": "string"}, {"name": "n", "base": "integer"}])
    assert [row.index for row in rows] == [1]
    assert outcomes == [RowOutcome(2, "n", STATUS_INVALID, "name: 'n' is already used by row 1")]
    assert outcomes[0].label == "row 2 (n)"


def test_convert_rows_calls_back_once_per_row() -> None:
    calls = []
    convert_rows([{"name": "a", "base": "string"}, "bad"], on_row=lambda: calls.append(1))
    assert len(calls) == 2


# ---- rules: payload and outcomes ------------------------------------------------------------------


def test_bundle_payload_sends_the_rows_as_a_type_def_bundle() -> None:
    rows = [_row(1, "a"), _row(2, "b", type="integer")]
    assert bundle_payload(rows, source_label="f.yaml") == {
        "schema": {"types": {"a": {"type": "string"}, "b": {"type": "integer"}}},
        "source_kind": "type-def-bundle",
        "source_label": "f.yaml",
        "import_all": True,
    }
    assert bundle_payload(rows, source_label="f.yaml", overwrite=["b"])["resolutions"] == {
        "b": {"action": "overwrite"}
    }


def test_review_outcomes_classify_each_row() -> None:
    rows = [_row(1, "a"), _row(2, "b"), _row(3, "c"), _row(4, "d"), _row(5, "e")]
    review = _review(a="new", b="identical", c="conflict", d="invalid")
    kept = review_outcomes(rows, review, update=False)
    assert [outcome.status for outcome in kept] == [
        STATUS_NEW, STATUS_UNCHANGED, STATUS_CONFLICT, STATUS_INVALID, STATUS_INVALID
    ]
    assert kept[3].message == "pattern: bad regex"
    assert kept[4].message == "not accepted as a type by the server"
    assert review_outcomes(rows, review, update=True)[2].status == STATUS_OVERWRITE


def test_review_outcomes_read_a_scope_violation() -> None:
    review = {"types": [{"name": "a", "status": "invalid", "error": {"error": "scope_violation", "details": ["x → y"]}}]}
    assert review_outcomes([_row(1, "a")], review, update=False)[0].message == "x → y"


def test_commit_outcomes_read_the_import_response() -> None:
    rows = [_row(1, "a"), _row(2, "b"), _row(3, "c"), _row(4, "d"), _row(5, "e"), _row(6, "f")]
    result = _result(
        imported=["a"],
        overwritten=["b"],
        identical=["c"],
        skipped=["d"],
        errors=[{"name": "e", "error": "cannot_overwrite_system", "details": "A system-core type cannot be overwritten"}],
    )
    done = commit_outcomes(rows, result)
    assert [outcome.status for outcome in done] == [
        STATUS_IMPORTED, STATUS_UPDATED, STATUS_UNCHANGED, STATUS_SKIPPED, STATUS_FAILED, STATUS_FAILED
    ]
    assert done[4].message == "A system-core type cannot be overwritten"
    assert done[5].message == "not reported by the server"
    assert has_failures(done)


def test_a_provenance_failure_is_a_warning_not_a_row() -> None:
    result = _result(imported=["a"], errors=[{"name": "_provenance", "error": "Failed to record import provenance: x"}])
    assert provenance_warning(result) == "Failed to record import provenance: x"
    assert not has_failures(commit_outcomes([_row(1, "a")], result))
    assert provenance_warning(_result(imported=["a"])) is None


def test_abort_outcomes() -> None:
    assert [outcome.status for outcome in abort_outcomes([_row(1, "a")])] == [STATUS_ABORTED]


# ---- rules: text and report -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("schema", "text"),
    [
        ({"type": "string", "pattern": "^LM-[0-9]{8}$"}, "string, pattern ^LM-[0-9]{8}$"),
        ({"type": "string", "format": "uuid"}, "string, format uuid"),
        ({"type": ["string", "null"], "enum": ["a", "b", None]}, "string | null, 3 values"),
        ({"$ref": "./money"}, "$ref"),
        ({}, "any"),
    ],
)
def test_describe_schema(schema, text) -> None:
    assert describe_schema(schema) == text


def test_render_plan_lists_new_rows_conflicts_and_the_rest() -> None:
    rows = [_row(1, "acme-id", type="string", pattern="^A$"), _row(2, "sku"), _row(3, "old"), _row(4, "same")]
    outcomes = [
        RowOutcome(1, "acme-id", STATUS_NEW),
        RowOutcome(2, "sku", STATUS_NEW),
        RowOutcome(3, "old", STATUS_CONFLICT),
        RowOutcome(4, "same", STATUS_UNCHANGED),
        RowOutcome(5, "string", STATUS_SYSTEM),
        RowOutcome(6, None, STATUS_INVALID, "name: is required"),
    ]
    assert render_plan(outcomes, rows) == (
        "  Would import 2 primitives:\n"
        "    + acme-id  (string, pattern ^A$)\n"
        "    + sku      (string)\n"
        "  Conflicts (skipped without --update):\n"
        "    ~ old  (already exists, would be overwritten with --update)\n"
        "  Unchanged: 1 primitive already identical.\n"
        "  Skipped: 1 system primitive (read-only).\n"
        "  Invalid:\n"
        "    ! row 6: name: is required"
    )


def test_render_plan_with_update_and_nothing_new() -> None:
    text = render_plan([RowOutcome(1, "old", STATUS_OVERWRITE)], [_row(1, "old")])
    assert text == (
        "  No new primitives to import.\n"
        "  Would overwrite 1 existing primitive:\n"
        "    ~ old  (already exists, overwritten by --update)"
    )


def test_render_summary() -> None:
    done = [
        *[RowOutcome(i, f"n{i}", STATUS_IMPORTED) for i in range(1, 14)],
        RowOutcome(14, "old", STATUS_UPDATED),
    ]
    assert render_summary(done) == "  ✔ Imported 13 new, updated 1 existing primitive."
    assert render_summary([RowOutcome(1, "a", STATUS_IMPORTED)]) == "  ✔ Imported 1 new, updated 0 existing primitives."
    mixed = [
        RowOutcome(1, "a", STATUS_SKIPPED),
        RowOutcome(2, "b", STATUS_UNCHANGED),
        RowOutcome(3, "c", STATUS_FAILED, "boom"),
    ]
    assert render_summary(mixed) == (
        "  No primitives were imported or updated.\n"
        "  Skipped 1 conflict (pass --update to overwrite).\n"
        "  Unchanged: 1 primitive already identical.\n"
        "  Failed: 1 row.\n"
        "    ! row 3 (c): boom"
    )


def test_build_report_counts_rows_by_status_in_file_order() -> None:
    report = build_report(
        [RowOutcome(2, "b", STATUS_FAILED, "boom"), RowOutcome(1, "a", STATUS_IMPORTED)],
        source="f.yaml",
        tenant="acme",
        committed=True,
        import_id="imp-1",
    )
    assert report == {
        "source": "f.yaml",
        "tenant": "acme",
        "dryRun": False,
        "importId": "imp-1",
        "summary": {"total": 2, "imported": 1, "failed": 1},
        "rows": [
            {"row": 1, "name": "a", "status": "imported", "message": ""},
            {"row": 2, "name": "b", "status": "failed", "message": "boom"},
        ],
    }


# ---- command: dry run and the commit gate ---------------------------------------------------------


def test_dry_run_reviews_and_writes_nothing(httpx_mock, source) -> None:
    httpx_mock.add_response(
        url=_REVIEW,
        method="POST",
        json=_review(acme_loyalty_id="conflict", acme_region_code="new", acme_internal_sku="new"),
    )
    result = _run(source, "--dry-run")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.output == (
        "  Would import 2 primitives:\n"
        "    + acme-region-code   (string, pattern ^(EU|US|APAC)$)\n"
        "    + acme-internal-sku  (string)\n"
        "  Conflicts (skipped without --update):\n"
        "    ~ acme-loyalty-id  (already exists, would be overwritten with --update)\n"
    )
    [body] = _posts(httpx_mock, _REVIEW)
    assert body["source_kind"] == "type-def-bundle" and body["source_label"] == "acme-primitives.yaml"
    assert list(body["schema"]["types"]) == _NAMES
    assert body["schema"]["types"]["acme-loyalty-id"] == {
        "type": "string",
        "pattern": "^LM-[0-9]{8}$",
        "examples": ["LM-00000001", "LM-12345678"],
    }
    assert not _posts(httpx_mock, _IMPORT)


def test_without_a_terminal_and_without_yes_nothing_is_written(httpx_mock, source) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    result = _run(source)
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Would import 3 primitives:" in result.output
    assert "Nothing was written. Pass --yes to import." in result.output
    assert not _posts(httpx_mock, _IMPORT)


def test_yes_imports_without_asking(httpx_mock, source) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    httpx_mock.add_response(url=_IMPORT, method="POST", json=_result(imported=_NAMES))
    result = _run(source, "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.output.endswith("  ✔ Imported 3 new, updated 0 existing primitives.\n")
    [body] = _posts(httpx_mock, _IMPORT)
    assert list(body["schema"]["types"]) == _NAMES and body["import_all"] is True
    assert "resolutions" not in body


def test_a_terminal_is_asked_and_yes_imports(httpx_mock, source, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    httpx_mock.add_response(url=_IMPORT, method="POST", json=_result(imported=_NAMES))
    result = _run(source, input="y\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Import 3 new and overwrite 0 existing primitive(s) in acme?" in result.output
    assert "✔ Imported 3 new" in result.output


def test_declining_writes_nothing_but_leaves_the_plan_in_the_report(httpx_mock, source, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.terminal.interactive_enabled", lambda: True)
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    report = tmp_path / "report.json"
    result = _run(source, "--report", report, input="n\n")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert not _posts(httpx_mock, _IMPORT)
    written = json.loads(report.read_text())
    assert written["dryRun"] is True and written["summary"] == {"total": 3, "new": 3}


def test_nothing_to_write_sends_no_import(httpx_mock, source) -> None:
    httpx_mock.add_response(
        url=_REVIEW,
        method="POST",
        json=_review(acme_loyalty_id="identical", acme_region_code="identical", acme_internal_sku="conflict"),
    )
    result = _run(source, "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "No new primitives to import." in result.output and "Nothing to import." in result.output
    assert not _posts(httpx_mock, _IMPORT)


# ---- command: conflicts ---------------------------------------------------------------------------


def test_update_overwrites_conflicts(httpx_mock, source) -> None:
    httpx_mock.add_response(
        url=_REVIEW,
        method="POST",
        json=_review(acme_loyalty_id="conflict", acme_region_code="new", acme_internal_sku="identical"),
    )
    httpx_mock.add_response(
        url=_IMPORT,
        method="POST",
        json=_result(imported=["acme-region-code"], overwritten=["acme-loyalty-id"], identical=["acme-internal-sku"]),
    )
    result = _run(source, "--update", "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Would overwrite 1 existing primitive:" in result.output
    assert "✔ Imported 1 new, updated 1 existing primitive." in result.output
    assert "Unchanged: 1 primitive already identical." in result.output
    [body] = _posts(httpx_mock, _IMPORT)
    assert body["resolutions"] == {"acme-loyalty-id": {"action": "overwrite"}}


def test_conflicts_are_skipped_by_default(httpx_mock, source) -> None:
    httpx_mock.add_response(
        url=_REVIEW,
        method="POST",
        json=_review(acme_loyalty_id="conflict", acme_region_code="new", acme_internal_sku="new"),
    )
    httpx_mock.add_response(
        url=_IMPORT,
        method="POST",
        json=_result(imported=["acme-region-code", "acme-internal-sku"], skipped=["acme-loyalty-id"]),
    )
    result = _run(source, "--skip-conflicts", "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Skipped 1 conflict (pass --update to overwrite)." in result.output
    assert "resolutions" not in _posts(httpx_mock, _IMPORT)[0]


def test_update_and_skip_conflicts_together_are_refused(httpx_mock, source) -> None:
    result = _run(source, "--update", "--skip-conflicts")
    assert result.exit_code == EXIT_USAGE
    assert "cannot be used together" in result.output
    assert not httpx_mock.get_requests()


# ---- command: row failures ------------------------------------------------------------------------


def _with_bad_row(tmp_path):
    path = tmp_path / "mixed.yaml"
    path.write_text(_YAML + "- name: acme-bad\n  base: strng\n", encoding="utf-8")
    return path


def test_a_locally_invalid_row_stops_before_any_request(httpx_mock, tmp_path) -> None:
    report = tmp_path / "report.json"
    result = _run(_with_bad_row(tmp_path), "--yes", "--report", report)
    assert result.exit_code == EXIT_PRIMITIVE_IMPORT_FAILED
    assert "row 4 (acme-bad): base: 'strng' is not one of" in result.output
    assert "Nothing was imported." in result.output
    assert not httpx_mock.get_requests()
    written = json.loads(report.read_text())
    assert written["tenant"] is None
    assert written["summary"] == {"total": 4, "invalid": 1, "aborted": 3}


def test_continue_on_error_imports_the_good_rows_and_exits_zero(httpx_mock, tmp_path) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    httpx_mock.add_response(url=_IMPORT, method="POST", json=_result(imported=_NAMES))
    result = _run(_with_bad_row(tmp_path), "--yes", "--continue-on-error")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "! row 4 (acme-bad): base: 'strng'" in result.output
    assert "✔ Imported 3 new" in result.output and "Failed: 1 row." in result.output
    assert list(_posts(httpx_mock, _IMPORT)[0]["schema"]["types"]) == _NAMES


def test_a_row_the_review_rejects_stops_the_import(httpx_mock, source) -> None:
    httpx_mock.add_response(
        url=_REVIEW,
        method="POST",
        json=_review(acme_loyalty_id="invalid", acme_region_code="new", acme_internal_sku="new"),
    )
    result = _run(source, "--yes", json_mode=True)
    assert result.exit_code == EXIT_PRIMITIVE_IMPORT_FAILED
    assert not _posts(httpx_mock, _IMPORT)
    report = json.loads(result.stdout)
    assert report["summary"] == {"total": 3, "invalid": 1, "aborted": 2}
    assert report["rows"][0] == {"row": 1, "name": "acme-loyalty-id", "status": "invalid", "message": "pattern: bad regex"}


def test_continue_on_error_leaves_a_rejected_row_out_of_the_import(httpx_mock, source) -> None:
    httpx_mock.add_response(
        url=_REVIEW,
        method="POST",
        json=_review(acme_loyalty_id="invalid", acme_region_code="new", acme_internal_sku="new"),
    )
    httpx_mock.add_response(url=_IMPORT, method="POST", json=_result(imported=_NAMES[1:]))
    result = _run(source, "--yes", "--continue-on-error")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert list(_posts(httpx_mock, _IMPORT)[0]["schema"]["types"]) == _NAMES[1:]
    assert "! row 1 (acme-loyalty-id): pattern: bad regex" in result.output


def test_a_row_that_fails_during_the_import_exits_7(httpx_mock, source, tmp_path) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    httpx_mock.add_response(
        url=_IMPORT,
        method="POST",
        json=_result(imported=_NAMES[:2], errors=[{"name": "acme-internal-sku", "error": "deadlock detected"}]),
    )
    report = tmp_path / "report.json"
    result = _run(source, "--yes", "--report", report)
    assert result.exit_code == EXIT_PRIMITIVE_IMPORT_FAILED
    assert "✔ Imported 2 new" in result.output
    assert "! row 3 (acme-internal-sku): deadlock detected" in result.output
    written = json.loads(report.read_text())
    assert written["dryRun"] is False and written["importId"] == "imp-1"
    assert written["summary"] == {"total": 3, "imported": 2, "failed": 1}


def test_a_provenance_failure_warns_and_exits_zero(httpx_mock, source) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    httpx_mock.add_response(
        url=_IMPORT,
        method="POST",
        json={**_result(imported=_NAMES, errors=[{"name": "_provenance", "error": "no audit"}]), "import_id": None},
    )
    result = _run(source, "--yes")
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "was not recorded in the import history (no audit)" in result.output


# ---- command: input -------------------------------------------------------------------------------


def test_round_trip_from_types_list_json_on_stdin(httpx_mock) -> None:
    listing = {
        "total": 3,
        "items": [
            {"id": "s1", "name": "string", "schema": {"type": "string"}, "is_system": True},
            {
                "id": "p1",
                "name": "acme-loyalty-id",
                "description": "Loyalty member id.",
                "tags": ["acme"],
                "is_system": False,
                "schema": {"$id": "https://api.apiome.dev/types/tenant/acme/acme-loyalty-id", "type": "string"},
            },
            {"id": "p2", "name": "acme-sku", "is_system": False, "schema": {"type": "string", "description": "SKU."}},
        ],
    }
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_review(acme_loyalty_id="conflict", acme_sku="identical"))
    httpx_mock.add_response(
        url=_IMPORT, method="POST", json=_result(overwritten=["acme-loyalty-id"], identical=["acme-sku"])
    )
    result = _run("--update", "--yes", input=json.dumps(listing))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Skipped: 1 system primitive (read-only)." in result.output
    assert "✔ Imported 0 new, updated 1 existing primitive." in result.output
    [body] = _posts(httpx_mock, _IMPORT)
    assert body["source_label"] == "stdin"
    assert body["schema"]["types"] == {
        "acme-loyalty-id": {
            "$id": "https://api.apiome.dev/types/tenant/acme/acme-loyalty-id",
            "type": "string",
            "description": "Loyalty member id.",
            "tags": ["acme"],
        },
        "acme-sku": {"type": "string", "description": "SKU."},
    }


def test_a_dash_reads_stdin_and_one_json_object_is_one_row(httpx_mock) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_review(acme_id="new"))
    result = _run("-", "--dry-run", input='{"name": "acme-id", "base": "string"}')
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "Would import 1 primitive:" in result.output


def test_no_file_on_a_terminal_is_a_usage_error(httpx_mock, monkeypatch) -> None:
    monkeypatch.setattr("apiome_cli.terminal.stdin_is_tty", lambda: True)
    result = _run()
    assert result.exit_code == EXIT_USAGE
    assert "Give a file to import, or pipe primitives in on stdin." in result.output


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("- name: [unclosed", "is not valid JSON or YAML"),
        ("just text", "must hold one primitive"),
        ("[]", "holds no primitives"),
    ],
)
def test_a_file_that_is_not_an_import_file_is_a_usage_error(httpx_mock, tmp_path, content, message) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(content, encoding="utf-8")
    result = _run(path)
    assert result.exit_code == EXIT_USAGE
    assert f"bad.yaml {message}" in result.output
    assert not httpx_mock.get_requests()


def test_a_missing_file_is_a_usage_error(httpx_mock, tmp_path) -> None:
    result = _run(tmp_path / "nope.yaml")
    assert result.exit_code == EXIT_USAGE
    assert "Cannot read" in result.output and "nope.yaml" in result.output


def test_only_system_rows_is_nothing_to_import(httpx_mock) -> None:
    result = _run(input=json.dumps([{"name": "string", "schema": {"type": "string"}, "is_system": True}]))
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert "No primitives to import." in result.output
    assert not httpx_mock.get_requests()


# ---- command: output and errors -------------------------------------------------------------------


def test_json_prints_the_report_on_stdout_and_the_text_on_stderr(httpx_mock, source) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    httpx_mock.add_response(url=_IMPORT, method="POST", json=_result(imported=_NAMES))
    result = _run(source, "--yes", json_mode=True)
    assert result.exit_code == EXIT_SUCCESS, result.output
    report = json.loads(result.stdout)
    assert report["source"] == "acme-primitives.yaml" and report["tenant"] == "acme"
    assert report["dryRun"] is False and report["importId"] == "imp-1"
    assert report["summary"] == {"total": 3, "imported": 3}
    assert [row["name"] for row in report["rows"]] == _NAMES
    assert "Would import 3 primitives:" in result.stderr


def test_dry_run_report_file_matches_the_plan(httpx_mock, source, tmp_path) -> None:
    httpx_mock.add_response(
        url=_REVIEW,
        method="POST",
        json=_review(acme_loyalty_id="conflict", acme_region_code="new", acme_internal_sku="identical"),
    )
    report = tmp_path / "report.json"
    result = _run(source, "--dry-run", "--update", "--report", report)
    assert result.exit_code == EXIT_SUCCESS, result.output
    written = json.loads(report.read_text())
    assert written["dryRun"] is True and written["importId"] is None
    assert written["summary"] == {"total": 3, "new": 1, "overwrite": 1, "unchanged": 1}


def test_an_unwritable_report_path_is_a_usage_error(httpx_mock, source, tmp_path) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json=_all_new())
    result = _run(source, "--dry-run", "--report", tmp_path / "missing-dir" / "report.json")
    assert result.exit_code == EXIT_USAGE
    assert "Cannot write the report" in result.output


def test_review_warnings_are_shown(httpx_mock, source) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", json={**_all_new(), "warnings": ["Type 'x' references './y'"]})
    result = _run(source, "--dry-run")
    assert "Warning: Type 'x' references './y'" in result.output


@pytest.mark.parametrize(("status", "code"), [(403, EXIT_USAGE), (400, EXIT_USAGE), (500, EXIT_ERROR)])
def test_api_errors_map_to_exit_codes(httpx_mock, source, status, code) -> None:
    httpx_mock.add_response(url=_REVIEW, method="POST", status_code=status, json={"detail": "refused"})
    result = _run(source, "--yes")
    assert result.exit_code == code
    assert "refused" in result.output


def test_a_file_over_the_threshold_asks_for_a_progress_bar(httpx_mock, tmp_path, monkeypatch) -> None:
    seen = []

    @contextmanager
    def fake_progress(total, *, description, enabled=True):
        seen.append((total, description, enabled))
        yield lambda: None

    monkeypatch.setattr("apiome_cli.commands.primitives.row_progress", fake_progress)
    count = PROGRESS_THRESHOLD + 1
    rows = [{"name": f"acme-{index}", "base": "string"} for index in range(count)]
    path = tmp_path / "many.json"
    path.write_text(json.dumps(rows), encoding="utf-8")
    httpx_mock.add_response(
        url=_REVIEW, method="POST", json=_review(**{f"acme_{index}": "new" for index in range(count)})
    )
    assert _run(path, "--dry-run").exit_code == EXIT_SUCCESS
    assert seen == [(count, "Checking primitives", True)]

    seen.clear()
    path.write_text(json.dumps(rows[:PROGRESS_THRESHOLD]), encoding="utf-8")
    httpx_mock.add_response(
        url=_REVIEW, method="POST", json=_review(**{f"acme_{index}": "new" for index in range(PROGRESS_THRESHOLD)})
    )
    assert _run(path, "--dry-run").exit_code == EXIT_SUCCESS
    assert seen == [(PROGRESS_THRESHOLD, "Checking primitives", False)]


def test_row_progress_draws_nothing_off_a_terminal() -> None:
    with row_progress(3, description="Checking primitives") as advance:
        assert advance() is None
