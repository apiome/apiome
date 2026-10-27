"""Tests for the Smithy breaking-change classifier — MFI-17.4 (#3811).

The Smithy CLI is not installed in CI, so the classifier tests replay output recorded from the real
CLI 1.53.0 running ``smithy diff --format csv`` inside the toolchain sandbox on
``tests/fixtures/smithy_breaking/{old,new}.smithy`` (``recordings/diff.json``; the staging path is
stored as ``/__STAGING__``). The models are read from the JSON ASTs the same CLI assembled from those
files (``old.ast.json`` / ``new.ast.json``). :func:`test_live_smithy_diff_matches_the_recording` runs
the real CLI when it is available (``APIOME_SMITHY_BIN``).
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import smithy_ast, smithy_breaking
from app import smithy_import_source as import_source_module
from app.breaking_change import (
    ChangeClassification,
    Severity,
    UnattributedFinding,
    _assemble_result,
    classify,
    get_breaking_change_classifier,
)
from app.diff import ChangeKind, EntityCategory, diff
from app.import_source import ImportSourceError
from app.smithy_ast import read_validation_events, run_smithy_diff
from app.smithy_ast_mapper import document_from_ast
from app.smithy_breaking import SMITHY_SEVERITIES, SmithyBreakingChangeClassifier, model_text, overlay_events
from app.smithy_import_source import SmithyImportSource
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolRunResult

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "smithy_breaking"
_PLACEHOLDER = "/__STAGING__"

#: The recorded findings: (severity, evaluator id, shape).
_RECORDED_EVENTS = [
    ("ERROR", "RemovedOperationBinding.FromService.DeletePet", "example.shelter#Shelter"),
    ("DANGER", "ChangedMemberOrder", "example.shelter#GetPetInput"),
    ("ERROR", "AddedRequiredMember", "example.shelter#GetPetInput$region"),
    ("NOTE", "AddedShape", "example.shelter#GetPetInput$region"),
    ("DANGER", "ChangedMemberOrder", "example.shelter#GetPetOutput"),
    ("NOTE", "AddedShape", "example.shelter#GetPetOutput$extra"),
    ("NOTE", "ChangedEnumTrait.Appended.1", "example.shelter#Status"),
    ("NOTE", "AddedShape", "example.shelter#Status$HELD"),
    ("ERROR", "ChangedMemberTarget", "example.shelter#Pet$size"),
    ("ERROR", "RemovedShape", "example.shelter#GetPetInput$filter"),
    ("ERROR", "RemovedShape", "example.shelter#GetPetOutput$tag"),
    ("ERROR", "RemovedShape", "example.shelter#DeletePet"),
    ("ERROR", "RemovedShape", "example.shelter#DeletePetInput"),
    ("ERROR", "ChangedEnumTrait.Removed.1", "example.shelter#Status"),
    ("ERROR", "RemovedShape", "example.shelter#Status$CLOSED"),
]


def _recording() -> Dict[str, Any]:
    return json.loads((_FIXTURES / "recordings" / "diff.json").read_text(encoding="utf-8"))


def _model(name: str, *, include_raw: bool = True):
    adapter = SmithyImportSource()
    text = (_FIXTURES / f"{name}.ast.json").read_text(encoding="utf-8")
    return adapter.normalize(adapter.parse(text), include_raw=include_raw)


@pytest.fixture(autouse=True)
def _no_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model parsing never runs ``smithy validate`` here (MFI-17.3 has its own tests)."""
    monkeypatch.setattr(import_source_module, "smithy_cli_available", lambda: False)


def _replay(monkeypatch: pytest.MonkeyPatch, stdout: str = None, exit_code: int = None) -> List[Dict[str, Any]]:
    """Make ``smithy diff`` replay the recording (or ``stdout``); return what each call saw."""
    calls: List[Dict[str, Any]] = []
    recorded = _recording()
    stdout = recorded["stdout"] if stdout is None else stdout
    exit_code = recorded["exit_code"] if exit_code is None else exit_code

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        old, new = Path(args[args.index("--old") + 1]), Path(args[args.index("--new") + 1])
        staging = str(old.parent.parent)
        calls.append(
            {
                "key": key,
                "args": [a.replace(staging, _PLACEHOLDER) for a in args],
                "old": old.read_text(encoding="utf-8"),
                "new": new.read_text(encoding="utf-8"),
                **kwargs,
            }
        )
        output = stdout.replace(_PLACEHOLDER, staging)
        if exit_code:
            raise ToolExecutionError(key, exit_code, output, "")
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout=output, stderr="", duration_ms=1)

    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _fake)
    monkeypatch.setattr(smithy_breaking, "smithy_cli_available", lambda: True)
    return calls


def _change(category: EntityCategory, key: str, severity: Severity = Severity.SAFE) -> ChangeClassification:
    return ChangeClassification(
        category=category, kind=ChangeKind.MODIFIED, key=key, severity=severity, rule_id="base", rationale="base"
    )


def _event(severity: str, shape: str, event_id: str = "Rule", message: str = "msg") -> Dict[str, Any]:
    return {"severity": severity, "id": event_id, "shape": shape, "message": message}


# ===========================================================================
# Registration and the severity map
# ===========================================================================


def test_the_classifier_is_registered_for_smithy():
    assert get_breaking_change_classifier("smithy") is SmithyBreakingChangeClassifier


def test_smithy_severities_map_onto_apiome_severities():
    assert SMITHY_SEVERITIES == {
        "ERROR": Severity.BREAKING,
        "DANGER": Severity.DANGEROUS,
        "WARNING": Severity.DANGEROUS,
        "NOTE": Severity.SAFE,
    }


# ===========================================================================
# Running `smithy diff`
# ===========================================================================


def test_the_recorded_diff_reads_into_events():
    staging = Path("/tmp/staged")
    events = read_validation_events(_recording()["stdout"].replace(_PLACEHOLDER, str(staging)), staging)
    assert [(e["severity"], e["id"], e["shape"]) for e in events] == _RECORDED_EVENTS
    assert {e["file"] for e in events} == {"old/model.smithy", "new/model.smithy"}


def test_run_smithy_diff_stages_both_models_and_runs_offline(monkeypatch):
    calls = _replay(monkeypatch)
    old_text = (_FIXTURES / "old.smithy").read_text(encoding="utf-8")
    new_ast = (_FIXTURES / "new.ast.json").read_text(encoding="utf-8")
    events = run_smithy_diff(old_text, new_ast)
    assert [(e["severity"], e["id"], e["shape"]) for e in events] == _RECORDED_EVENTS
    (call,) = calls
    assert call["key"] == "smithy"
    assert call["args"] == [
        "diff",
        "--no-config",
        "--format",
        "csv",
        "--severity",
        "NOTE",
        "--allow-unknown-traits",
        "--old",
        f"{_PLACEHOLDER}/old/model.smithy",
        "--new",
        f"{_PLACEHOLDER}/new/model.json",
    ]
    assert (call["old"], call["new"]) == (old_text, new_ast)
    assert "-Dhttps.proxyPort=9" in call["extra_env"]["JAVA_TOOL_OPTIONS"]
    assert "-Duser.home=" in call["extra_env"]["JAVA_TOOL_OPTIONS"]
    assert call["cwd"] == call["extra_env"]["HOME"]


def test_a_clean_diff_has_no_events(monkeypatch):
    _replay(monkeypatch, stdout="severity,id,shape,file,line,column,message,hint,suppressionReason\n", exit_code=0)
    assert run_smithy_diff("a", "b") == []


def test_run_smithy_diff_is_best_effort(monkeypatch):
    _replay(monkeypatch, stdout="Unable to load the model: syntax error", exit_code=1)
    assert run_smithy_diff("a", "b") is None

    def _missing(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        raise ToolNotAvailableError(key, "smithy")

    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _missing)
    assert run_smithy_diff("a", "b") is None


# ===========================================================================
# Joining findings to changes
# ===========================================================================


def test_the_recorded_diff_grades_the_changes_and_keeps_unjoined_findings(monkeypatch):
    calls = _replay(monkeypatch)
    old, new = _model("old"), _model("new")
    result = classify(diff(old, new), old, new)
    assert len(calls) == 1
    assert result.classifier == "smithy-diff"
    grades = {c.key: (c.severity.value, c.rule_id) for c in result.classifications}
    assert grades == {
        "example.shelter.Shelter": ("breaking", "smithy-diff.RemovedOperationBinding.FromService.DeletePet"),
        "example.shelter.Shelter.DeletePet": ("breaking", "smithy-diff.RemovedShape"),
        # No finding names the operation's request message: the baseline grade stands.
        "example.shelter.Shelter.DeletePet#request": ("breaking", "removed-entity"),
        "example.shelter.DeletePetInput": ("breaking", "smithy-diff.RemovedShape"),
        "example.shelter.DeletePetInput.id": ("breaking", "removed-entity"),
        # The enum lost CLOSED (ERROR) and gained HELD (NOTE): the worst wins.
        "example.shelter.Status": ("breaking", "smithy-diff.ChangedEnumTrait.Removed.1"),
        "example.shelter.GetPetInput.filter": ("breaking", "smithy-diff.RemovedShape"),
        "example.shelter.GetPetInput.region": ("breaking", "smithy-diff.AddedRequiredMember"),
        "example.shelter.GetPetOutput.extra": ("safe", "smithy-diff.AddedShape"),
        "example.shelter.GetPetOutput.tag": ("breaking", "smithy-diff.RemovedShape"),
        "example.shelter.Pet.size": ("breaking", "smithy-diff.ChangedMemberTarget"),
    }
    status = next(c for c in result.classifications if c.key == "example.shelter.Status")
    assert "Enum value `CLOSED` was removed" in status.rationale
    assert "Enum value `HELD` was appended" in status.rationale
    assert [(u.severity, u.rule_id, u.shape) for u in result.unattributed] == [
        (Severity.DANGEROUS, "smithy-diff.ChangedMemberOrder", "example.shelter#GetPetInput"),
        (Severity.DANGEROUS, "smithy-diff.ChangedMemberOrder", "example.shelter#GetPetOutput"),
    ]
    assert result.overall_severity is Severity.BREAKING
    assert result.counts_by_severity == {"breaking": 10, "safe": 1}


def test_a_shape_finding_joins_an_operation_by_name_in_its_namespace():
    classifications = [
        _change(EntityCategory.OPERATION, "ns.Svc.GetPet"),
        _change(EntityCategory.OPERATION, "other.Svc.GetPet"),
    ]
    graded, unattributed = overlay_events(classifications, [_event("WARNING", "ns#GetPet", "OperationChanged")])
    assert [(c.severity, c.rule_id) for c in graded] == [
        (Severity.DANGEROUS, "smithy-diff.OperationChanged"),
        (Severity.SAFE, "base"),
    ]
    assert unattributed == []


def test_a_member_finding_falls_back_to_its_shape():
    graded, _ = overlay_events(
        [_change(EntityCategory.TYPE, "ns.Status")], [_event("ERROR", "ns#Status$GONE", "RemovedShape")]
    )
    assert (graded[0].severity, graded[0].rule_id) == (Severity.BREAKING, "smithy-diff.RemovedShape")


def test_a_note_can_lower_the_baseline_grade():
    graded, _ = overlay_events(
        [_change(EntityCategory.FIELD, "ns.Pet.tag", Severity.DANGEROUS)], [_event("NOTE", "ns#Pet$tag", "AddedShape")]
    )
    assert graded[0].severity is Severity.SAFE


def test_unjoined_notes_and_unknown_severities_are_dropped():
    graded, unattributed = overlay_events(
        [_change(EntityCategory.TYPE, "ns.Pet")],
        [_event("NOTE", "ns#Other"), _event("SUPPRESSED", "ns#Pet"), _event("WARNING", "", "ModelWide")],
    )
    assert graded[0].rule_id == "base"
    assert [(u.severity, u.rule_id, u.shape) for u in unattributed] == [
        (Severity.DANGEROUS, "smithy-diff.ModelWide", "")
    ]


def test_an_unattributed_error_makes_the_whole_result_breaking():
    classifier = SmithyBreakingChangeClassifier()
    finding = UnattributedFinding(severity=Severity.BREAKING, rule_id="smithy-diff.X", rationale="r", shape="ns#A")
    result = _assemble_result(classifier, _model("old", include_raw=False), [], [finding])
    assert result.overall_severity is Severity.BREAKING
    assert result.breaking
    assert result.counts_by_severity == {}
    assert result.model_dump()["unattributed"][0]["rule_id"] == "smithy-diff.X"


def test_identical_models_still_surface_a_tool_finding(monkeypatch):
    output = (
        "severity,id,shape,file,line,column,message,hint,suppressionReason\n"
        '"ERROR","ChangedTrait","example.shelter#Pet","/__STAGING__/new/model.json",1,1,"trait moved","",""\n'
    )
    _replay(monkeypatch, stdout=output, exit_code=1)
    old = _model("old")
    result = classify(diff(old, old), old, old)
    assert result.classifications == []
    assert result.overall_severity is Severity.BREAKING


# ===========================================================================
# Falling back to the baseline
# ===========================================================================


def test_without_the_cli_the_baseline_grades_stand(monkeypatch):
    calls = _replay(monkeypatch)
    monkeypatch.setattr(smithy_breaking, "smithy_cli_available", lambda: False)
    old, new = _model("old"), _model("new")
    result = classify(diff(old, new), old, new)
    assert calls == []
    assert result.classifier == "smithy-diff"
    assert result.unattributed == []
    assert not any(c.rule_id.startswith("smithy-diff.") for c in result.classifications)


def test_without_the_raw_models_the_baseline_grades_stand(monkeypatch):
    calls = _replay(monkeypatch)
    old, new = _model("old", include_raw=False), _model("new", include_raw=False)
    result = classify(diff(old, new), old, new)
    assert calls == []
    assert not any(c.rule_id.startswith("smithy-diff.") for c in result.classifications)


def test_a_diff_that_does_not_run_keeps_the_baseline(monkeypatch):
    _replay(monkeypatch, stdout="Unable to load the model", exit_code=1)
    old, new = _model("old"), _model("new")
    result = classify(diff(old, new), old, new)
    assert not any(c.rule_id.startswith("smithy-diff.") for c in result.classifications)


# ===========================================================================
# The model text kept for the diff
# ===========================================================================


def _assembled_document(source_files):
    ast = json.loads((_FIXTURES / "old.ast.json").read_text(encoding="utf-8"))
    document = document_from_ast(ast, raw="root text", source_files=source_files)
    return replace(document, ast=ast), ast


def test_a_multi_file_set_keeps_its_assembled_ast_for_the_diff():
    document, ast = _assembled_document(("a.smithy", "b.smithy"))
    model = SmithyImportSource().normalize(document)
    assert model.raw["smithy"] == "root text"
    assert json.loads(model.raw["smithy_ast"]) == ast
    assert model_text(model) == model.raw["smithy_ast"]


def test_a_single_file_keeps_only_its_text():
    document, _ = _assembled_document(("model.smithy",))
    model = SmithyImportSource().normalize(document)
    assert set(model.raw) == {"smithy"}
    assert model_text(model) == "root text"
    assert model_text(SmithyImportSource().normalize(document, include_raw=False)) is None


def test_the_ast_does_not_take_part_in_document_equality():
    document, _ = _assembled_document(("a.smithy", "b.smithy"))
    assert document == replace(document, ast=None)


# ===========================================================================
# One `.smithy` file through the CLI
# ===========================================================================


def test_one_idl_file_is_assembled_through_the_cli_when_it_is_available(monkeypatch):
    seen: List[Any] = []
    document, _ = _assembled_document(("model.smithy",))

    def _assemble(members, root, *, source_label=None):
        seen.append((dict(members), root))
        return document

    monkeypatch.setattr(import_source_module, "smithy_cli_available", lambda: True)
    monkeypatch.setattr(import_source_module, "assemble_smithy_set", _assemble)
    monkeypatch.setattr(import_source_module, "validate_smithy_members", lambda members: [])
    text = (_FIXTURES / "old.smithy").read_text(encoding="utf-8")
    assert SmithyImportSource().parse(text) is not None
    assert seen == [({"model.smithy": text}, "model.smithy")]
    model = SmithyImportSource().normalize(SmithyImportSource().parse(text))
    # The CLI reads the inline `:=` input members the built-in reader does not.
    assert any(t.key == "example.shelter.GetPetInput" for t in model.types)


def test_one_idl_file_falls_back_to_the_built_in_reader_when_the_cli_fails(monkeypatch):
    def _fail(members, root, *, source_label=None):
        raise ImportSourceError("The Smithy model does not validate", code="INPUT_SEMANTIC_INVALID")

    monkeypatch.setattr(import_source_module, "smithy_cli_available", lambda: True)
    monkeypatch.setattr(import_source_module, "assemble_smithy_set", _fail)
    monkeypatch.setattr(import_source_module, "validate_smithy_members", lambda members: [])
    document = SmithyImportSource().parse((_FIXTURES / "old.smithy").read_text(encoding="utf-8"))
    assert document.model_sha256 is None  # the built-in reader's document
    assert document.namespace == "example.shelter"


# ===========================================================================
# Live CLI
# ===========================================================================


@pytest.mark.skipif(not smithy_ast.smithy_cli_available(), reason="Smithy CLI (smithy) is not installed")
def test_live_smithy_diff_matches_the_recording():
    events = run_smithy_diff(
        (_FIXTURES / "old.smithy").read_text(encoding="utf-8"),
        (_FIXTURES / "new.smithy").read_text(encoding="utf-8"),
    )
    assert [(e["severity"], e["id"], e["shape"]) for e in events] == _RECORDED_EVENTS
