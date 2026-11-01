"""OMG IDL export validation with an IDL compiler — MFX-28.3 (#4170).

``omniidl`` (CORBA) and Cyclone DDS ``idlc`` (DDS) are not installed in CI, so the toolchain runner is stood
in for by a fake that records each call and, for a file containing ``Missing``, fails the way the compilers
do (``ToolExecutionError`` with their error lines on stderr). The live compilers are exercised by the
existing ``test_corbaidl_emitter.py`` compile tests where ``APIOME_OMNIIDL_BIN`` / ``APIOME_IDLC_BIN`` are
set. Covers:

* :func:`app.omg_idl_compile.idl_compiler_for` — the header names the profile; without it an annotation
  line means DDS;
* :func:`app.omg_idl_compile.compile_omg_idl` — runs the profile's compiler in a scratch directory through
  the runner; its error lines become ``diagnostics``; an unavailable compiler is ``unavailable``; unsafe
  paths are refused;
* the gate — compiler errors are ``idl.compile`` findings with the compiler's text, the reader re-parse is
  ``idl.reimport``, no compiler falls back to the reader; and **non-parsing IDL fails the export job with
  compiler detail**;
* **fixtures pass** — every corpus export, in both profiles, passes the gate with the compiler stood in.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from test_corbaidl_emitter import _COMPILE_CORPUS, _EXAMPLES, _corpus_api, _emit, _rest_api

from app import omg_idl_compile
from app.emitter import EmitPreconditionError, EmitResult, EmittedFile
from app.export_job_engine import ExportJobStartRequest, schedule_export_job
from app.export_validation import validate_emitted_artifact
from app.omg_idl_compile import (
    IDLC_TOOL_KEY,
    OMNIIDL_TOOL_KEY,
    OmgIdlCompileError,
    compile_omg_idl,
    idl_compiler_for,
)
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError

_OMNIIDL_ERROR = "Shop.idl:3: Error in look-up of 'Missing': 'Missing' not found"
_IDLC_ERROR = "Shop.idl:3:20: error: Scoped name 'Missing' cannot be resolved"


class _FakeRunner:
    """Stands in for the toolchain runner: records calls, rejects any file that mentions ``Missing``."""

    def __init__(self, *, unavailable: bool = False) -> None:
        self.calls: List[Dict[str, Any]] = []
        self.unavailable = unavailable

    async def run_spec(self, spec, args, *, timeout=None, cwd=None, policy=None):
        import os

        with open(os.path.join(cwd, args[0]), encoding="utf-8") as handle:
            text = handle.read()
        self.calls.append({"key": spec.key, "args": list(args), "cwd": cwd, "text": text})
        if self.unavailable:
            raise ToolNotAvailableError(spec.key, spec.executable)
        if "Missing" in text:
            line = _OMNIIDL_ERROR if spec.key == OMNIIDL_TOOL_KEY else _IDLC_ERROR
            raise ToolExecutionError(spec.key, 1, "", f"{line}\nomniidl: 1 error.\n")
        return None


@pytest.fixture
def runner(monkeypatch: pytest.MonkeyPatch) -> _FakeRunner:
    fake = _FakeRunner()
    monkeypatch.setattr(omg_idl_compile, "default_runner", fake)
    monkeypatch.setattr(omg_idl_compile, "idl_compiler_available", lambda key: True)
    return fake


@pytest.fixture
def no_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(omg_idl_compile, "idl_compiler_available", lambda key: False)


def _export(text: str, path: str = "Shop.idl") -> EmitResult:
    return EmitResult(files=[EmittedFile(path=path, content=text, media_type="text/plain")], media_type="text/plain")


_BROKEN_CORBA = "// Generated OMG IDL 4.2 (CORBA profile) for Shop\nmodule Shop {\n  struct Order { Missing m; };\n};\n"
_BROKEN_DDS = "// Generated OMG IDL 4.2 (DDS profile) for Shop\nmodule Shop {\n  struct Order { Missing m; };\n};\n"


# ===========================================================================
# Choosing the compiler
# ===========================================================================


def test_the_header_names_the_profile() -> None:
    assert idl_compiler_for(_BROKEN_CORBA) == OMNIIDL_TOOL_KEY
    assert idl_compiler_for(_BROKEN_DDS) == IDLC_TOOL_KEY


def test_without_a_header_an_annotation_means_dds() -> None:
    assert idl_compiler_for("module M { struct S { @key long id; }; };\n") == IDLC_TOOL_KEY
    assert idl_compiler_for("module M {\n  @topic\n  struct S { long id; };\n};\n") == IDLC_TOOL_KEY
    assert idl_compiler_for("module M { interface I { void ping(); }; };\n") == OMNIIDL_TOOL_KEY


def test_the_emitter_profiles_pick_their_compilers() -> None:
    api = _rest_api()
    assert idl_compiler_for(_emit(api).files[0].content) == OMNIIDL_TOOL_KEY
    assert idl_compiler_for(_emit(api, profile="dds").files[0].content) == IDLC_TOOL_KEY
    # Without the header, a DDS file is told apart by its annotations; one with none is plain IDL omniidl checks.
    bare = _emit(api, profile="dds", include_comments=False).files[0].content
    assert idl_compiler_for(bare) == (IDLC_TOOL_KEY if "@" in bare else OMNIIDL_TOOL_KEY)


# ===========================================================================
# compile_omg_idl
# ===========================================================================


async def test_a_file_that_compiles_returns_its_compiler(runner: _FakeRunner) -> None:
    text = _emit(_rest_api(), profile="dds").files[0].content
    assert await compile_omg_idl("Shop.idl", text) == IDLC_TOOL_KEY
    call = runner.calls[0]
    assert (call["key"], call["args"], call["text"]) == (IDLC_TOOL_KEY, ["Shop.idl"], text)
    assert "apiome-idl-" in call["cwd"]


@pytest.mark.parametrize(("text", "key", "line"), [(_BROKEN_CORBA, OMNIIDL_TOOL_KEY, _OMNIIDL_ERROR),
                                                   (_BROKEN_DDS, IDLC_TOOL_KEY, _IDLC_ERROR)])
async def test_compiler_error_lines_become_diagnostics(runner: _FakeRunner, text: str, key: str, line: str) -> None:
    with pytest.raises(OmgIdlCompileError) as raised:
        await compile_omg_idl("Shop.idl", text)
    assert raised.value.compiler == key and line in raised.value.diagnostics and not raised.value.unavailable


async def test_an_unavailable_compiler_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(omg_idl_compile, "default_runner", _FakeRunner(unavailable=True))
    with pytest.raises(OmgIdlCompileError) as raised:
        await compile_omg_idl("Shop.idl", _BROKEN_CORBA)
    assert raised.value.unavailable


@pytest.mark.parametrize("path", ["Shop.txt", "-o.idl", ""])
async def test_unsafe_paths_are_refused(runner: _FakeRunner, path: str) -> None:
    with pytest.raises(OmgIdlCompileError):
        await compile_omg_idl(path, _BROKEN_CORBA)
    assert runner.calls == []


async def test_a_directory_path_is_reduced_to_its_base_name(runner: _FakeRunner) -> None:
    text = _emit(_rest_api()).files[0].content
    await compile_omg_idl("../../etc/Shop.idl", text)
    assert runner.calls[0]["args"] == ["Shop.idl"] and "apiome-idl-" in runner.calls[0]["cwd"]


# ===========================================================================
# The gate and the export job
# ===========================================================================


async def test_gate_rejects_compiler_errors_with_the_compiler_text(runner: _FakeRunner) -> None:
    api = _rest_api()
    verdict = await validate_emitted_artifact("corbaidl", _export(_BROKEN_DDS), api=api)
    assert verdict.failed
    compiled = [f for f in verdict.findings if f.keyword == "idl.compile"]
    assert [f.message for f in compiled] == [_IDLC_ERROR] and compiled[0].file == "Shop.idl"


async def test_gate_without_a_compiler_reparses(no_compiler) -> None:
    api = _rest_api()
    assert (await validate_emitted_artifact("corbaidl", _emit(api), api=api)).valid
    verdict = await validate_emitted_artifact("corbaidl", _export("this is not IDL {"), api=api)
    assert verdict.failed and verdict.findings[0].keyword == "idl.reimport"


async def test_a_compiler_that_goes_missing_falls_back_to_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(omg_idl_compile, "default_runner", _FakeRunner(unavailable=True))
    monkeypatch.setattr(omg_idl_compile, "idl_compiler_available", lambda key: True)
    api = _rest_api()
    assert (await validate_emitted_artifact("corbaidl", _emit(api), api=api)).valid


async def test_non_parsing_idl_fails_the_job_with_compiler_detail(runner: _FakeRunner) -> None:
    """MFX-28.3 acceptance: non-parsing IDL fails the export job with the compiler's detail."""
    from test_export_job_engine import TENANT_ID, TENANT_SLUG, _source, _wait_terminal

    def _emit_broken(*args, **kwargs):
        return _export(_BROKEN_CORBA, "widgets.idl")

    request = ExportJobStartRequest(artifact="artifact-1", target="corbaidl", confirm=True)
    with patch("app.export_job_engine.load_export_source", return_value=_source()), patch(
        "app.export_job_engine.emit_canonical", side_effect=_emit_broken
    ):
        accepted = await schedule_export_job(TENANT_SLUG, TENANT_ID, request)
        status = await _wait_terminal(accepted.job_id)

    assert status["state"] == "failed"
    assert status["error"]["code"] == "EMITTED_ARTIFACT_INVALID"
    compiled = [f for f in status["error"]["context"]["findings"] if f["keyword"] == "idl.compile"]
    assert [f["message"] for f in compiled] == [_OMNIIDL_ERROR] and compiled[0]["file"] == "widgets.idl"


# ===========================================================================
# Fixtures pass
# ===========================================================================


@pytest.mark.parametrize("profile", ["corba", "dds"])
@pytest.mark.parametrize(("path", "fmt"), _COMPILE_CORPUS, ids=lambda v: str(v))
async def test_every_corpus_export_passes_the_gate(runner: _FakeRunner, path: str, fmt: str, profile: str) -> None:
    api = _corpus_api(_EXAMPLES / path, fmt)
    try:
        result = _emit(api, profile=profile)
    except EmitPreconditionError:
        assert profile == "dds" and not api.types  # the DDS profile writes data types only
        return
    verdict = await validate_emitted_artifact("corbaidl", result, api=api)
    assert verdict.validated and verdict.valid, verdict.errors
    expected = OMNIIDL_TOOL_KEY if profile == "corba" else IDLC_TOOL_KEY
    assert {call["key"] for call in runner.calls} == {expected}


# ---------------------------------------------------------------------------
# A CORBA export with its comments turned off is still checked by omniidl (MFX-28.4, #4171)
# ---------------------------------------------------------------------------


def test_a_corba_file_with_annotations_but_no_header_goes_to_omniidl() -> None:
    """``include_comments: false`` drops the profile header; ``@optional`` alone must not route to idlc."""
    text = ("module Shop {\n  struct Pet {\n    @optional string tag;\n  };\n"
            "  interface Pets {\n    Pet get();\n  };\n};\n")
    assert idl_compiler_for(text) == OMNIIDL_TOOL_KEY


def test_an_exception_also_marks_a_headerless_file_as_corba() -> None:
    assert idl_compiler_for("module M {\n  exception NotFound { @optional string reason; };\n};\n") == OMNIIDL_TOOL_KEY


def test_a_headerless_dds_file_with_a_key_still_goes_to_idlc() -> None:
    assert idl_compiler_for("module M {\n  struct Pet {\n    @key long long id;\n  };\n};\n") == IDLC_TOOL_KEY


@pytest.mark.parametrize("include_comments", [True, False])
def test_a_corba_export_is_checked_by_omniidl_with_or_without_comments(include_comments: bool) -> None:
    text = str(_emit(_rest_api(), profile="corba", include_comments=include_comments).files[0].content)
    assert "interface " in text and "@" in text
    assert idl_compiler_for(text) == OMNIIDL_TOOL_KEY
