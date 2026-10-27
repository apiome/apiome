"""Tests for the API Blueprint lint pack — MFI-16.3 (#3806).

drafter is a native tool the CI runtime does not build, so most tests replay output recorded from
the real drafter 4.0.0 (``drafter -f json`` with the document on stdin) on
``tests/fixtures/apiblueprint_drafter/{warnings,error}.apib``
(``tests/fixtures/apiblueprint_drafter/recordings``: stdout, stderr, exit code).
:func:`test_live_drafter_matches_the_recordings` runs the real tool when it is available
(``APIOME_DRAFTER_BIN`` or ``drafter`` on ``PATH``).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import apiblueprint_drafter
from app import apiblueprint_import_source as import_source_module
from app.apiblueprint_drafter import drafter_available, read_drafter_annotations, run_drafter
from app.apiblueprint_import_source import ApiblueprintImportSource
from app.apiblueprint_normalizer import MAX_RECORDED_ANNOTATIONS
from app.lint_engine import lint_canonical_model
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolRunResult, ToolTimeoutError

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "apiblueprint_drafter"
_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "api-blueprint"

_WARNINGS = [
    {
        "severity": "warning",
        "code": 8,
        "message": "parameter 'limit' is not found within the URI template '/pets{?status}' for 'Pets'",
        "line": 9,
        "column": 1,
    },
    {"severity": "warning", "code": 6, "message": "empty request message-body", "line": 23, "column": 1},
    {"severity": "warning", "code": 6, "message": "action is missing a response", "line": 29, "column": 1},
    {
        "severity": "warning",
        "code": 2,
        "message": "the resource '/pets/{id}' is already defined",
        "line": 27,
        "column": 1,
    },
]
_ERROR = [
    {
        "severity": "error",
        "code": 4,
        "message": "base type 'Animal' is not defined in the document",
        "line": 7,
        "column": 1,
    }
]


def _text(name: str) -> str:
    return (_FIXTURES / f"{name}.apib").read_text(encoding="utf-8")


def _recording(name: str) -> Dict[str, Any]:
    return json.loads((_FIXTURES / "recordings" / f"{name}.json").read_text(encoding="utf-8"))


def _replay(monkeypatch: pytest.MonkeyPatch, name: str) -> List[Dict[str, Any]]:
    """Make ``run_tool_blocking`` replay a recording (raising for a non-zero exit, as the runner does)."""
    calls: List[Dict[str, Any]] = []
    recorded = _recording(name)

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        calls.append({"key": key, "args": list(args), **kwargs})
        if recorded["exit_code"]:
            raise ToolExecutionError(key, recorded["exit_code"], recorded["stdout"], recorded["stderr"])
        return ToolRunResult(
            key=key, argv=[key, *args], exit_code=0, stdout=recorded["stdout"], stderr=recorded["stderr"], duration_ms=1
        )

    monkeypatch.setattr(apiblueprint_drafter, "run_tool_blocking", _fake)
    monkeypatch.setattr(import_source_module, "drafter_available", lambda: True)
    return calls


def _findings(model: Any) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for finding in lint_canonical_model(model).findings:
        payload = finding.as_dict()
        if payload["rule"].startswith("apiblueprint."):
            out.setdefault(payload["rule"], []).append(payload)
    return out


# ===========================================================================
# Reading drafter's parse result
# ===========================================================================


def test_the_recorded_parse_results_read_into_located_annotations():
    assert read_drafter_annotations(_recording("warnings")["stdout"]) == _WARNINGS
    assert read_drafter_annotations(_recording("error")["stdout"]) == _ERROR


@pytest.mark.parametrize("stdout", ["", "OK.", '{"element": "category"}'])
def test_output_that_is_not_a_parse_result_reads_as_none(stdout: str):
    assert read_drafter_annotations(stdout) is None


def test_an_annotation_without_a_source_map_has_no_location():
    result = {
        "element": "parseResult",
        "content": [
            {
                "element": "annotation",
                "meta": {"classes": {"element": "array", "content": [{"element": "string", "content": "warning"}]}},
                "attributes": {"code": {"element": "number", "content": 3}},
                "content": "something ",
            }
        ],
    }
    assert read_drafter_annotations(json.dumps(result)) == [{"severity": "warning", "code": 3, "message": "something"}]


def test_run_drafter_feeds_the_document_on_stdin(monkeypatch):
    calls = _replay(monkeypatch, "warnings")
    assert run_drafter(_text("warnings")) == _WARNINGS
    assert calls[0]["key"] == "drafter"
    assert calls[0]["args"] == ["-f", "json"]
    assert calls[0]["stdin"] == _text("warnings")


def test_a_drafter_error_exit_still_yields_its_annotations(monkeypatch):
    _replay(monkeypatch, "error")
    assert run_drafter(_text("error")) == _ERROR


@pytest.mark.parametrize(
    "error",
    [ToolNotAvailableError("drafter", "drafter"), ToolTimeoutError("drafter", 30.0)],
    ids=["missing", "timeout"],
)
def test_a_drafter_that_cannot_run_yields_nothing(monkeypatch, error: Exception):
    def _raise(*_args: Any, **_kwargs: Any) -> ToolRunResult:
        raise error

    monkeypatch.setattr(apiblueprint_drafter, "run_tool_blocking", _raise)
    assert run_drafter(_text("warnings")) == []


def test_garbage_output_yields_nothing(monkeypatch):
    def _garbage(key: str, args: List[str], **_kwargs: Any) -> ToolRunResult:
        return ToolRunResult(key=key, argv=[key], exit_code=0, stdout="nope", stderr="", duration_ms=1)

    monkeypatch.setattr(apiblueprint_drafter, "run_tool_blocking", _garbage)
    assert run_drafter(_text("warnings")) == []


# ===========================================================================
# Import → catalog item → lint
# ===========================================================================


def test_an_import_records_the_warnings_and_lint_reports_them(monkeypatch):
    _replay(monkeypatch, "warnings")
    adapter = ApiblueprintImportSource()
    model = adapter.normalize(adapter.parse(_text("warnings"), source_label="warnings.apib"))
    assert model.extras["apib_drafter_annotations"] == _WARNINGS
    assert model.extras["apib_drafter_annotation_count"] == 4
    findings = _findings(model)
    assert set(findings) == {"apiblueprint.drafter-warning"}
    assert sorted((f["path"], f["severity"]) for f in findings["apiblueprint.drafter-warning"]) == [
        ("apib:23:1", "warning"),
        ("apib:27:1", "warning"),
        ("apib:29:1", "warning"),
        ("apib:9:1", "warning"),
    ]
    assert any(f["message"].startswith("(8) parameter 'limit'") for f in findings["apiblueprint.drafter-warning"])


def test_a_drafter_error_is_a_blocking_finding_and_the_import_still_succeeds(monkeypatch):
    _replay(monkeypatch, "error")
    adapter = ApiblueprintImportSource()
    model = adapter.normalize(adapter.parse(_text("error"), source_label="error.apib"))
    (finding,) = _findings(model)["apiblueprint.drafter-error"]
    assert finding["severity"] == "error"
    assert finding["path"] == "apib:7:1"
    assert finding["message"] == "(4) base type 'Animal' is not defined in the document"


def test_without_drafter_nothing_is_recorded(monkeypatch):
    monkeypatch.setattr(import_source_module, "drafter_available", lambda: False)
    adapter = ApiblueprintImportSource()
    model = adapter.normalize(adapter.parse(_text("warnings")))
    assert "apib_drafter_annotations" not in model.extras
    assert _findings(model) == {}


@pytest.mark.parametrize("path", sorted(_EXAMPLES.glob("*.apib")), ids=lambda p: p.name)
def test_the_corpus_imports_unchanged_without_drafter(monkeypatch, path: Path):
    monkeypatch.setattr(import_source_module, "drafter_available", lambda: False)
    adapter = ApiblueprintImportSource()
    assert adapter.parse(path.read_text(encoding="utf-8")).drafter_annotations == ()


def test_annotations_are_capped_and_the_rest_counted(monkeypatch):
    monkeypatch.setattr(import_source_module, "drafter_available", lambda: False)
    adapter = ApiblueprintImportSource()
    many = tuple(
        {"severity": "warning", "code": 8, "message": f"m{i}", "line": i, "column": 1}
        for i in range(MAX_RECORDED_ANNOTATIONS + 2)
    )
    model = adapter.normalize(replace(adapter.parse(_text("warnings")), drafter_annotations=many))
    assert len(model.extras["apib_drafter_annotations"]) == MAX_RECORDED_ANNOTATIONS
    assert model.extras["apib_drafter_annotation_count"] == MAX_RECORDED_ANNOTATIONS + 2
    messages = [f["message"] for f in _findings(model)["apiblueprint.drafter-warning"]]
    assert "2 more drafter annotation(s) not listed." in messages


# ===========================================================================
# Live drafter
# ===========================================================================


@pytest.mark.skipif(not drafter_available(), reason="drafter is not installed in this runtime")
def test_live_drafter_matches_the_recordings():
    assert run_drafter(_text("warnings")) == _WARNINGS
    assert run_drafter(_text("error")) == _ERROR
