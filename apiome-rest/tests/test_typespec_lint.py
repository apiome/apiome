"""Tests for the TypeSpec lint pack — MFI-14.3 (#3796).

The ``diagnostics`` recording (``tests/fixtures/typespec_compile/recordings/diagnostics.json``) is
the real ``@typespec/compiler`` 0.65.0 compiling ``tests/fixtures/typespec_compile/diagnostics``
with Apiome's configuration — the built-in ``@typespec/http/all`` linter ruleset enabled — which
reports one compiler warning (``deprecated``) and one linter warning
(``@typespec/http/op-reference-container-route``). :func:`test_live_compile_reports_the_recorded_diagnostics`
runs the real compiler when it is installed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml

from app.fileset import IntakeFileset
from app.lint_engine import lint_canonical_model
from app.typespec_compile import (
    OPENAPI_TSPCONFIG,
    TypeSpecDiagnostic,
    compile_typespec_set,
    parse_diagnostics,
)
from app.typespec_config import BUILTIN_LINTER_RULESETS
from app.typespec_import_source import MAX_RECORDED_DIAGNOSTICS, TypeSpecImportSource
from tests.test_typespec_compile import _live_compiler_ready, _members, _replay, libraries  # noqa: F401

_SET_DIR = Path(__file__).resolve().parent / "fixtures" / "typespec_compile" / "diagnostics"

_EXPECTED = [
    {
        "severity": "warning",
        "code": "deprecated",
        "message": "Deprecated: Use Pet instead.",
        "file": "ops/legacy.tsp",
        "line": 15,
        "column": 18,
    },
    {
        "severity": "warning",
        "code": "@typespec/http/op-reference-container-route",
        "message": (
            "Operation adoptable references an operation which has a @route prefix on its namespace or interface: "
            '"/pets".  This operation will not carry forward the route prefix so the final route may be different '
            "than the referenced operation."
        ),
        "file": "main.tsp",
        "line": 22,
        "column": 4,
    },
]


def _diagnostic_members() -> Dict[str, str]:
    return {
        str(path.relative_to(_SET_DIR)): path.read_text(encoding="utf-8")
        for path in sorted(_SET_DIR.rglob("*"))
        if path.is_file()
    }


def _findings(model: Any) -> List[Dict[str, Any]]:
    return [
        finding.as_dict()
        for finding in lint_canonical_model(model).findings
        if finding.as_dict()["rule"] == "typespec.compiler-diagnostic"
    ]


# ===========================================================================
# Reading diagnostics
# ===========================================================================


def test_parse_diagnostics_reads_located_and_unlocated_lines_and_skips_code_frames():
    output = """TypeSpec compiler v0.65.0

Diagnostics were reported during compilation:

main.tsp:19:31 - warning deprecated: Deprecated: use Pet
> 19 | @get @route("/old") op old(): OldPet;
     |                               ^^^^^^
models/a b.tsp:3:1 - warning @typespec/http/op-reference-container-route: Operation x references ...
warning @typespec/openapi3/some-emitter-note: An emitter note without a location
main.tsp:19:31 - warning deprecated: Deprecated: use Pet

Found 3 warnings.
"""
    diagnostics = parse_diagnostics(output)
    assert diagnostics == [
        TypeSpecDiagnostic("warning", "deprecated", "Deprecated: use Pet", "main.tsp", 19, 31),
        TypeSpecDiagnostic(
            "warning",
            "@typespec/http/op-reference-container-route",
            "Operation x references ...",
            "models/a b.tsp",
            3,
            1,
        ),
        TypeSpecDiagnostic("warning", "@typespec/openapi3/some-emitter-note", "An emitter note without a location"),
    ]
    assert diagnostics[2].as_dict() == {
        "severity": "warning",
        "code": "@typespec/openapi3/some-emitter-note",
        "message": "An emitter note without a location",
    }


def test_parse_diagnostics_of_a_clean_compile_is_empty():
    assert parse_diagnostics("TypeSpec compiler v0.65.0\n\nCompilation completed successfully.\n") == []


def test_every_compile_enables_the_built_in_linter_rulesets():
    assert BUILTIN_LINTER_RULESETS == ("@typespec/http/all",)
    assert yaml.safe_load(OPENAPI_TSPCONFIG)["linter"] == {"extends": ["@typespec/http/all"]}


# ===========================================================================
# Compile → catalog item → lint (recorded)
# ===========================================================================


def test_a_compile_keeps_its_warnings(monkeypatch, libraries):  # noqa: F811
    calls = _replay(monkeypatch, "diagnostics")
    compiled = compile_typespec_set(_diagnostic_members(), "main.tsp")
    assert "@typespec/http/all" in calls[0]["tspconfig"]
    assert [d.as_dict() for d in compiled.diagnostics] == _EXPECTED


def test_the_catalog_item_records_the_diagnostics_and_lint_reports_them(monkeypatch, libraries):  # noqa: F811
    _replay(monkeypatch, "diagnostics")
    adapter = TypeSpecImportSource()
    model = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(_diagnostic_members(), root="main.tsp")))
    assert model.format == "typespec"
    assert model.extras["typespec_diagnostics"] == _EXPECTED
    assert model.extras["typespec_diagnostic_count"] == 2
    findings = _findings(model)
    assert sorted((f["path"], f["severity"]) for f in findings) == [
        ("tsp:main.tsp:22:4", "warning"),
        ("tsp:ops/legacy.tsp:15:18", "warning"),
    ]
    messages = {f["message"] for f in findings}
    assert "deprecated: Deprecated: Use Pet instead." in messages
    assert any(m.startswith("@typespec/http/op-reference-container-route: Operation adoptable") for m in messages)


def test_a_clean_compile_adds_no_extras_or_findings(monkeypatch, libraries):  # noqa: F811
    _replay(monkeypatch, "petstore")
    adapter = TypeSpecImportSource()
    model = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(_members(), root="main.tsp")))
    assert "typespec_diagnostics" not in model.extras
    assert _findings(model) == []


def test_a_single_file_is_not_compiled_and_has_no_diagnostics():
    adapter = TypeSpecImportSource()
    text = (_SET_DIR / "main.tsp").read_text(encoding="utf-8").replace('import "./ops/legacy.tsp";\n', "")
    model = adapter.normalize(adapter.parse(text, source_label="main.tsp"))
    assert "typespec_diagnostics" not in model.extras
    assert _findings(model) == []


def test_recorded_diagnostics_are_capped_and_the_rest_counted(monkeypatch, libraries):  # noqa: F811
    from app import typespec_compile

    many = "\n".join(
        f"main.tsp:{i}:1 - warning deprecated: Deprecated thing {i}" for i in range(1, MAX_RECORDED_DIAGNOSTICS + 4)
    )
    real_parse = typespec_compile.parse_diagnostics
    monkeypatch.setattr(typespec_compile, "parse_diagnostics", lambda output: real_parse(many))
    _replay(monkeypatch, "diagnostics")
    adapter = TypeSpecImportSource()
    model = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(_diagnostic_members(), root="main.tsp")))
    assert len(model.extras["typespec_diagnostics"]) == MAX_RECORDED_DIAGNOSTICS
    assert model.extras["typespec_diagnostic_count"] == MAX_RECORDED_DIAGNOSTICS + 3
    messages = [f["message"] for f in _findings(model)]
    assert "3 more TypeSpec compiler diagnostic(s) not listed." in messages


def test_error_lines_with_library_codes_are_quoted_when_a_compile_fails(monkeypatch, libraries):  # noqa: F811
    from app import typespec_compile
    from app.import_source import ImportSourceError
    from app.toolchain_runner import ToolExecutionError

    stdout = (
        "main.tsp:3:1 - warning deprecated: old\n"
        'main.tsp:4:2 - error @typespec/http/duplicate-operation: Duplicate operation "x".\n'
    )

    def _fail(key: str, args: List[str], **kwargs: Any) -> None:
        raise ToolExecutionError(key, 1, stdout, "")

    monkeypatch.setattr(typespec_compile, "run_tool_blocking", _fail)
    with pytest.raises(ImportSourceError) as exc:
        compile_typespec_set(_diagnostic_members(), "main.tsp")
    assert "@typespec/http/duplicate-operation" in str(exc.value)
    assert "deprecated" not in str(exc.value)


# ===========================================================================
# Live compiler
# ===========================================================================


@pytest.mark.skipif(not _live_compiler_ready(), reason="tsp with @typespec/openapi3 is not installed")
def test_live_compile_reports_the_recorded_diagnostics():
    compiled = compile_typespec_set(_diagnostic_members(), "main.tsp")
    assert [d.as_dict() for d in compiled.diagnostics] == _EXPECTED
