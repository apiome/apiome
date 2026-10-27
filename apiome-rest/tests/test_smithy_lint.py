"""Tests for the Smithy lint pack — MFI-17.3 (#3810).

The Smithy CLI is not installed in CI, so most tests replay output recorded from the real CLI 1.53.0
running ``smithy validate --format csv`` inside the toolchain sandbox, with the ``smithy-linters``
1.53.0 validators resolved from an offline Maven folder
(``tests/fixtures/smithy_lint/recordings``; the staging path is stored as ``/__STAGING__``).
:func:`test_live_smithy_validate_matches_the_recordings` runs the real CLI when it and the linters
repository are available (``APIOME_SMITHY_BIN`` / ``APIOME_SMITHY_LINTERS_REPO``).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import smithy_ast
from app import smithy_import_source as import_source_module
from app.fileset import IntakeFileset
from app.lint_engine import lint_canonical_model
from app.smithy_ast import (
    SMITHY_LINTERS,
    SMITHY_LINTERS_REPO_ENV,
    read_validation_events,
    smithy_linters_repo,
    validate_smithy_members,
)
from app.smithy_import_source import SmithyImportSource
from app.smithy_lint import rule_for_event
from app.smithy_normalizer import MAX_RECORDED_EVENTS
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolRunResult

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "smithy_lint"
_PLACEHOLDER = "/__STAGING__"

_MODEL_EVENTS = [
    ("WARNING", "MissingPaginatedTrait", "example.shelter#ListPets", 13, 1),
    ("WARNING", "CamelCase", "example.shelter#GetPetInput$pet_id", 25, 9),
    ("WARNING", "ShouldHaveUsedTimestamp", "example.shelter#GetPetOutput$adoptedAt", 29, 9),
    ("WARNING", "AbbreviationName", "example.shelter#PetSummary$URLValue", 40, 5),
    ("WARNING", "CamelCase", "example.shelter#PetSummary$URLValue", 40, 5),
    ("WARNING", "MissingSensitiveTrait", "example.shelter#PetSummary$password", 41, 5),
]


def _text(name: str) -> str:
    return (_FIXTURES / f"{name}.smithy").read_text(encoding="utf-8")


def _recording(name: str) -> Dict[str, Any]:
    return json.loads((_FIXTURES / "recordings" / f"{name}.json").read_text(encoding="utf-8"))


def _summary(events: List[Dict[str, Any]]) -> List[tuple]:
    return [(e["severity"], e["id"], e["shape"], e["line"], e["column"]) for e in events]


@pytest.fixture()
def linters_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in local Maven repository holding the smithy-linters jar."""
    jar = tmp_path / "m2" / "software/amazon/smithy/smithy-linters/1.53.0/smithy-linters-1.53.0.jar"
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"jar")
    monkeypatch.setenv(SMITHY_LINTERS_REPO_ENV, str(tmp_path / "m2"))
    return tmp_path / "m2"


def _replay(monkeypatch: pytest.MonkeyPatch, name: str) -> List[Dict[str, Any]]:
    """Make ``run_tool_blocking`` replay a recording; return what each call saw.

    Each call records its arguments, environment and the files staged for it.
    """
    calls: List[Dict[str, Any]] = []
    recorded = _recording(name)

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        staging = str(Path(args[-1]).parent)
        calls.append(
            {
                "key": key,
                "args": list(args),
                "staged": {Path(a).name: Path(a).read_text(encoding="utf-8") for a in args if a.endswith(".smithy")},
                "config": (
                    json.loads(Path(args[args.index("-c") + 1]).read_text(encoding="utf-8")) if "-c" in args else None
                ),
                **kwargs,
            }
        )
        stdout = recorded["stdout"].replace(_PLACEHOLDER, staging)
        if recorded["exit_code"]:
            raise ToolExecutionError(key, recorded["exit_code"], stdout, "")
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout=stdout, stderr="", duration_ms=1)

    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _fake)
    monkeypatch.setattr(import_source_module, "smithy_cli_available", lambda: True)
    return calls


def _findings(model: Any) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for finding in lint_canonical_model(model).findings:
        payload = finding.as_dict()
        if payload["rule"].startswith("smithy."):
            out.setdefault(payload["rule"], []).append(payload)
    return out


# ===========================================================================
# Reading `smithy validate --format csv`
# ===========================================================================


def test_the_recorded_csv_reads_into_located_events():
    staging = Path("/tmp/staged")
    events = read_validation_events(_recording("model")["stdout"].replace(_PLACEHOLDER, str(staging)), staging)
    assert events is not None
    assert _summary(events) == list(_MODEL_EVENTS)
    assert {event["file"] for event in events} == {"model.smithy"}
    assert events[0]["message"].startswith("The verb of this operation, `list`, requires")


def test_suppressed_events_and_the_generated_validators_file_are_left_out():
    output = (
        "severity,id,shape,file,line,column,message,hint,suppressionReason\n"
        '"SUPPRESSED","CamelCase","ns#A$b","/s/model.smithy",1,1,"hidden","","ok"\n'
        '"WARNING","UnknownValidator_X","","/s/__apiome_lint_validators.smithy",4,5,"x","",""\n'
        '"NOTE","UnreferencedShape","ns#Spare","",,,"Spare is unreferenced","",""\n'
    )
    events = read_validation_events(output, Path("/s"))
    assert events == [
        {
            "severity": "NOTE",
            "id": "UnreferencedShape",
            "shape": "ns#Spare",
            "file": None,
            "message": "Spare is unreferenced",
            "line": None,
            "column": None,
        }
    ]


@pytest.mark.parametrize("output", ["", "FAILURE: something broke", None])
def test_output_without_a_csv_header_reads_as_none(output):
    assert read_validation_events(output, Path("/s")) is None


# ===========================================================================
# Running `smithy validate`
# ===========================================================================


def test_validate_enables_the_linters_from_the_offline_repository(monkeypatch, linters_repo):
    calls = _replay(monkeypatch, "model")
    events = validate_smithy_members({"model.smithy": _text("model")})
    assert _summary(events) == list(_MODEL_EVENTS)
    (call,) = calls
    assert call["args"][:6] == ["validate", "--format", "csv", "--severity", "NOTE", "--allow-unknown-traits"]
    assert call["config"] == {
        "version": "1.0",
        "maven": {
            "dependencies": ["software.amazon.smithy:smithy-linters:1.53.0"],
            "repositories": [{"url": linters_repo.resolve().as_uri()}],
        },
    }
    validators = call["staged"]["__apiome_lint_validators.smithy"]
    assert all(f'{{ name: "{name}", severity: "WARNING" }}' in validators for name in SMITHY_LINTERS)
    env = call["extra_env"]
    assert "-Dhttps.proxyHost=127.0.0.1" in env["JAVA_TOOL_OPTIONS"]
    assert f"-Duser.home={call['cwd']}" in env["JAVA_TOOL_OPTIONS"]


def test_without_the_linters_repository_only_core_validators_run(monkeypatch, tmp_path):
    monkeypatch.setenv(SMITHY_LINTERS_REPO_ENV, str(tmp_path / "missing"))
    monkeypatch.setattr("app.toolchain_packaging.probe_tool", lambda key: None)
    calls = _replay(monkeypatch, "error")
    validate_smithy_members({"model.smithy": _text("error")})
    assert "--no-config" in calls[0]["args"]
    assert "__apiome_lint_validators.smithy" not in calls[0]["staged"]


def test_an_error_exit_still_yields_its_events(monkeypatch, linters_repo):
    _replay(monkeypatch, "error")
    (event,) = validate_smithy_members({"model.smithy": _text("error")})
    assert (event["severity"], event["id"], event["line"], event["column"]) == ("ERROR", "Target.UnresolvedShape", 6, 5)


def test_a_cli_that_cannot_run_yields_nothing(monkeypatch, linters_repo):
    def _missing(*_args: Any, **_kwargs: Any) -> ToolRunResult:
        raise ToolNotAvailableError("smithy", "smithy")

    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _missing)
    assert validate_smithy_members({"model.smithy": _text("model")}) == []


def test_no_model_files_means_no_run(monkeypatch):
    calls = _replay(monkeypatch, "model")
    assert validate_smithy_members({"smithy-build.json": "{}"}) == []
    assert calls == []


def test_the_linters_repository_is_found_beside_the_cli(monkeypatch, tmp_path):
    monkeypatch.delenv(SMITHY_LINTERS_REPO_ENV, raising=False)
    prefix = tmp_path / "tools"
    (prefix / "lib" / "smithy" / "bin").mkdir(parents=True)
    jar = prefix / "lib/smithy-m2/software/amazon/smithy/smithy-linters/1.53.0/smithy-linters-1.53.0.jar"
    jar.parent.mkdir(parents=True)
    jar.write_bytes(b"jar")

    class _Probe:
        resolved_path = str(prefix / "lib" / "smithy" / "bin" / "smithy")

    monkeypatch.setattr("app.toolchain_packaging.probe_tool", lambda key: _Probe())
    assert smithy_linters_repo() == prefix / "lib" / "smithy-m2"


def test_the_linters_version_matches_the_bundled_cli():
    from app.toolchain_packaging import BUNDLED_TOOLS

    smithy = next(tool for tool in BUNDLED_TOOLS if tool.key == "smithy")
    assert smithy_ast._LINTERS_COORDINATE.endswith(f":{smithy.version}")
    assert smithy.version in str(smithy_ast._LINTERS_JAR)


# ===========================================================================
# Import → catalog item → lint
# ===========================================================================


def test_a_single_file_import_records_the_events_and_lint_reports_them(monkeypatch, linters_repo):
    _replay(monkeypatch, "model")
    adapter = SmithyImportSource()
    model = adapter.normalize(adapter.parse(_text("model"), source_label="model.smithy"))
    assert model.extras["smithy_validation_event_count"] == 6
    findings = _findings(model)
    assert set(findings) == {"smithy.linter"}
    assert sorted(f["path"] for f in findings["smithy.linter"]) == [
        "smithy:model.smithy:13:1",
        "smithy:model.smithy:25:9",
        "smithy:model.smithy:29:9",
        "smithy:model.smithy:40:5",
        "smithy:model.smithy:40:5",
        "smithy:model.smithy:41:5",
    ]
    assert all(f["severity"] == "warning" for f in findings["smithy.linter"])
    assert any(f["message"].startswith("MissingPaginatedTrait: ") for f in findings["smithy.linter"])


def test_an_invalid_single_file_is_a_blocking_finding(monkeypatch, linters_repo):
    _replay(monkeypatch, "error")
    adapter = SmithyImportSource()
    model = adapter.normalize(adapter.parse(_text("error"), source_label="model.smithy"))
    (finding,) = _findings(model)["smithy.validation-error"]
    assert finding["severity"] == "error"
    assert finding["path"] == "smithy:model.smithy:6:5"
    assert finding["message"].startswith("Target.UnresolvedShape: member shape targets an unresolved shape")


def test_a_multi_file_set_is_validated_after_assembly(monkeypatch, linters_repo):
    assembled = []
    monkeypatch.setattr(
        import_source_module,
        "assemble_smithy_set",
        lambda members, root, source_label=None: (
            assembled.append(sorted(members)) or import_source_module.parse_smithy(members[root])
        ),
    )
    calls = _replay(monkeypatch, "model")
    members = {
        "main.smithy": _text("model"),
        "other.smithy": '$version: "2"\nnamespace example.other\n',
        "README.md": "x",
    }
    document = SmithyImportSource().parse_fileset(IntakeFileset.from_members(members, root="main.smithy"))
    assert assembled == [["README.md", "main.smithy", "other.smithy"]]
    assert sorted(calls[0]["staged"]) == ["__apiome_lint_validators.smithy", "main.smithy", "other.smithy"]
    assert len(document.validation_events) == 6


def test_without_the_cli_nothing_is_recorded(monkeypatch):
    monkeypatch.setattr(import_source_module, "smithy_cli_available", lambda: False)
    adapter = SmithyImportSource()
    model = adapter.normalize(adapter.parse(_text("model")))
    assert "smithy_validation_events" not in model.extras
    assert _findings(model) == {}


@pytest.mark.parametrize(
    ("event", "rule"),
    [
        ({"id": "CamelCase", "severity": "DANGER"}, "smithy.linter"),
        ({"id": "CamelCase.MemberName", "severity": "WARNING"}, "smithy.linter"),
        ({"id": "Target.UnresolvedShape", "severity": "ERROR"}, "smithy.validation-error"),
        ({"id": "DeprecatedShape", "severity": "WARNING"}, "smithy.validation-warning"),
        ({"id": "MyEmitEach", "severity": "DANGER"}, "smithy.validation-warning"),
        ({"id": "UnreferencedShape", "severity": "NOTE"}, "smithy.validation-note"),
    ],
)
def test_events_map_to_rules(event: Dict[str, Any], rule: str):
    assert rule_for_event(event) == rule


def test_events_are_capped_and_the_rest_counted(monkeypatch):
    monkeypatch.setattr(import_source_module, "smithy_cli_available", lambda: False)
    adapter = SmithyImportSource()
    many = tuple(
        {
            "severity": "WARNING",
            "id": "CamelCase",
            "shape": f"ns#S{i}",
            "file": "m.smithy",
            "line": i,
            "column": 1,
            "message": "m",
        }
        for i in range(MAX_RECORDED_EVENTS + 3)
    )
    model = adapter.normalize(replace(adapter.parse(_text("model")), validation_events=many))
    assert len(model.extras["smithy_validation_events"]) == MAX_RECORDED_EVENTS
    assert model.extras["smithy_validation_event_count"] == MAX_RECORDED_EVENTS + 3
    messages = [f["message"] for f in _findings(model)["smithy.linter"]]
    assert "3 more Smithy validation event(s) not listed." in messages


# ===========================================================================
# Live CLI
# ===========================================================================


@pytest.mark.skipif(
    not (smithy_ast.smithy_cli_available() and smithy_linters_repo() is not None),
    reason="the Smithy CLI and the smithy-linters repository are not installed",
)
def test_live_smithy_validate_matches_the_recordings():
    assert _summary(validate_smithy_members({"model.smithy": _text("model")})) == list(_MODEL_EVENTS)
    (event,) = validate_smithy_members({"model.smithy": _text("error")})
    assert (event["severity"], event["id"]) == ("ERROR", "Target.UnresolvedShape")
