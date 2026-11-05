"""Tests for the toolchain check console engine — MFX-44.6 (#4372).

Pins what :mod:`app.export_tool_checks` promises the REST binding:

* every toolchain check an emitter declares (MFX-44.1) has a command here — a new declaration
  without one fails this suite rather than shipping a Run button that cannot run;
* an artifact is staged safely (no path escapes the scratch directory, size caps hold) from a
  re-emit or from a completed job's single document / zip bundle;
* a run streams ``start`` then ``output`` events, hides the scratch directory's path, and ends in
  a result whose status is the tool's outcome (passed / failed + exit code / timed out /
  unavailable / error) — never an exception;
* with ``buf`` installed, ``buf lint`` on a real emitted proto bundle streams its findings.

A fake runner stands in for the toolchain (the runner itself is covered by
``test_toolchain_runner.py``); the ``buf`` test runs only where the binary is present.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from app.emitter import EmitResult, EmittedFile, describe_emit_targets
from app.export_test_tools import ExportTestToolKind
from app.export_tool_checks import (
    MAX_ARTIFACT_FILES,
    ToolCheckArtifactError,
    ToolCheckStatus,
    files_from_download_body,
    files_from_emit,
    result_event,
    run_tool_check,
    tool_check_command,
)
from app.toolchain_runner import (
    ToolExecutionError,
    ToolNotAvailableError,
    ToolRunResult,
    ToolTimeoutError,
)

PROTO = 'syntax = "proto3";\npackage acme.v1;\nmessage widget { string Name = 1; }\n'


class FakeRunner:
    """Records the call, writes ``chunks`` through ``on_output``, then returns or raises ``outcome``."""

    def __init__(self, chunks: Optional[List[tuple]] = None, outcome: Optional[BaseException] = None) -> None:
        self.chunks = chunks or []
        self.outcome = outcome
        self.calls: List[Dict[str, Any]] = []
        self.staged: Dict[str, str] = {}

    async def run_spec(self, spec, args, *, timeout=None, cwd=None, extra_env=None, on_output=None):
        scratch = Path(cwd)
        self.staged = {str(p.relative_to(scratch)): p.read_text() for p in scratch.rglob("*") if p.is_file()}
        self.calls.append({"spec": spec, "args": list(args), "cwd": cwd, "extra_env": extra_env})
        for stream, chunk in self.chunks:
            on_output(stream, chunk(cwd) if callable(chunk) else chunk)
        if self.outcome is not None:
            raise self.outcome
        return ToolRunResult(key=spec.key, argv=[spec.executable, *args], exit_code=0, stdout="", stderr="",
                             duration_ms=12)


async def _run(tool: str, check: str, files: Dict[str, str], runner: FakeRunner):
    events: List[Dict[str, Any]] = []
    result = await run_tool_check(tool_check_command(tool, check), files, label=f"{tool} {check}",
                                  on_event=events.append, runner=runner)
    return result, events


# --- the command registry ----------------------------------------------------


def test_every_declared_toolchain_check_has_a_command():
    """A Run button never appears for a check this server cannot run."""
    declared = {
        (tool.params["tool"], tool.params["check"])
        for entry in describe_emit_targets()
        for tool in entry.descriptor.test_tools
        if tool.kind == ExportTestToolKind.TOOLCHAIN
    }
    assert declared, "emitters declare toolchain checks (MFX-44.1)"
    missing = sorted(pair for pair in declared if tool_check_command(*pair) is None)
    assert missing == []


def test_unknown_check_has_no_command():
    assert tool_check_command("buf", "breaking") is None
    assert tool_check_command("nope", "lint") is None


def test_commands_read_only_their_own_files():
    smithy = tool_check_command("smithy", "build")
    # The emitter writes the model as IDL and as a JSON AST; only the IDL is built.
    assert smithy.matching(["Shop.json", "Shop.smithy"]) == ["Shop.smithy"]
    assert tool_check_command("buf", "lint").matching(["b.proto", "a/a.proto", "manifest.json"]) == [
        "a/a.proto", "b.proto",
    ]


def test_entry_files_prefer_the_conventional_name():
    tsp = tool_check_command("tsp", "compile")
    assert tsp.args(["lib.tsp", "main.tsp"]) == ["compile", "main.tsp", "--no-emit"]
    redocly = tool_check_command("redocly", "lint")
    assert redocly.args(["extra.json", "openapi.json"]) == ["lint", "openapi.json"]


# --- staging the artifact ----------------------------------------------------


def test_files_from_emit_serializes_like_the_download():
    emit = EmitResult(files=[EmittedFile(path="openapi.json", content={"openapi": "3.1.0"}),
                             EmittedFile(path="acme/v1/shop.proto", content=PROTO)])
    files = files_from_emit(emit)
    assert files["acme/v1/shop.proto"] == PROTO
    assert files["openapi.json"].startswith('{\n  "openapi": "3.1.0"')


@pytest.mark.parametrize("path", ["../escape.proto", "/etc/passwd", "a/../../x.proto", "C:evil.proto", ".."])
def test_unsafe_paths_are_refused(path):
    # (An emitted file's path is already sanitized by ``EmittedFile``; a job's download name is not.)
    with pytest.raises(ToolCheckArtifactError):
        files_from_download_body(path, "x")


def test_download_single_document_is_one_file():
    assert files_from_download_body("shop.proto", PROTO) == {"shop.proto": PROTO}


def _zip(members: Dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return buffer.getvalue()


def test_download_bundle_unpacks_text_members_and_skips_binary():
    body = _zip({"acme/v1/shop.proto": PROTO.encode(), "manifest.json": b"{}", "logo.bin": b"\xff\xfe\x00"})
    files = files_from_download_body("protobuf.zip", body)
    assert files == {"acme/v1/shop.proto": PROTO, "manifest.json": "{}"}


def test_download_bundle_refuses_traversal_and_corruption():
    with pytest.raises(ToolCheckArtifactError):
        files_from_download_body("x.zip", _zip({"../evil.proto": b"x"}))
    with pytest.raises(ToolCheckArtifactError):
        files_from_download_body("x.zip", b"not a zip")


def test_download_bundle_refuses_too_many_files():
    body = _zip({f"f{i}.proto": b"x" for i in range(MAX_ARTIFACT_FILES + 1)})
    with pytest.raises(ToolCheckArtifactError):
        files_from_download_body("x.zip", body)


# --- running a check -----------------------------------------------------------


async def test_passing_run_streams_start_then_output_with_scratch_paths_hidden():
    runner = FakeRunner(chunks=[("stdout", lambda cwd: f"{cwd}/acme/v1/shop.proto: ok\n".encode())])
    result, events = await _run("buf", "lint", {"acme/v1/shop.proto": PROTO}, runner)

    assert result.status == ToolCheckStatus.PASSED and result.exit_code == 0 and result.duration_ms == 12
    assert result.command == "buf lint" and result.files == ["acme/v1/shop.proto"]
    assert events[0] == {"event": "start", "tool": "buf", "check": "lint", "label": "buf lint",
                         "command": "buf lint", "files": ["acme/v1/shop.proto"]}
    assert events[1] == {"event": "output", "stream": "stdout", "text": "acme/v1/shop.proto: ok\n"}
    # The bundle is staged under its own paths, with buf's documented defaults beside it.
    assert runner.staged["acme/v1/shop.proto"] == PROTO
    assert "STANDARD" in runner.staged["buf.yaml"]


async def test_a_bundled_config_is_not_overwritten():
    runner = FakeRunner()
    await _run("buf", "lint", {"a.proto": PROTO, "buf.yaml": "version: v2\n"}, runner)
    assert runner.staged["buf.yaml"] == "version: v2\n"


async def test_split_multibyte_characters_are_decoded_across_chunks():
    snowman = "☃\n".encode()
    runner = FakeRunner(chunks=[("stderr", snowman[:1]), ("stderr", snowman[1:])])
    _, events = await _run("buf", "lint", {"a.proto": PROTO}, runner)
    assert "".join(e["text"] for e in events if e["event"] == "output") == "☃\n"


async def test_non_zero_exit_is_a_failed_result_with_its_exit_code():
    runner = FakeRunner(chunks=[("stdout", b"a.proto:3:9:Message name should be PascalCase\n")],
                        outcome=ToolExecutionError("buf", 100, "", ""))
    result, events = await _run("buf", "lint", {"a.proto": PROTO}, runner)
    assert result.status == ToolCheckStatus.FAILED and result.exit_code == 100
    assert result.message == "buf lint exited 100."
    assert [e["event"] for e in events] == ["start", "output"]


async def test_missing_binary_is_unavailable_not_an_error():
    runner = FakeRunner(outcome=ToolNotAvailableError("buf", "buf"))
    result, _ = await _run("buf", "lint", {"a.proto": PROTO}, runner)
    assert result.status == ToolCheckStatus.UNAVAILABLE
    assert result.message == "The buf toolchain is not installed on this server."


async def test_timeout_is_reported_in_words():
    runner = FakeRunner(outcome=ToolTimeoutError("tsp", 60.0))
    result, _ = await _run("tsp", "compile", {"main.tsp": "model A {}"}, runner)
    assert result.status == ToolCheckStatus.TIMED_OUT
    assert "60s timeout" in result.message


async def test_an_artifact_without_matching_files_does_not_run():
    runner = FakeRunner()
    result, events = await _run("buf", "lint", {"openapi.json": "{}"}, runner)
    assert result.status == ToolCheckStatus.ERROR and "no .proto file" in result.message
    assert runner.calls == [] and events == []


async def test_binary_stdout_is_not_streamed():
    runner = FakeRunner(chunks=[("stdout", b"\x00\x01\x02\x03"), ("stderr", b"warning\n")])
    result, events = await _run("capnp", "compile", {"shop.capnp": "@0xbf5147cbbecf40c1;"}, runner)
    texts = [(e["stream"], e["text"]) for e in events if e["event"] == "output"]
    assert texts == [("stderr", "warning\n"), ("stdout", "(4 bytes of binary compiler output not shown)\n")]
    assert result.status == ToolCheckStatus.PASSED


async def test_typespec_runs_with_an_isolated_home():
    runner = FakeRunner()
    await _run("tsp", "compile", {"main.tsp": "model A {}"}, runner)
    call = runner.calls[0]
    assert call["args"] == ["compile", "main.tsp", "--no-emit"]
    assert call["extra_env"]["HOME"] == call["cwd"]


def test_result_event_carries_the_whole_result():
    from app.export_tool_checks import ExportToolCheckResult

    result = ExportToolCheckResult(tool="buf", check="lint", label="buf lint", status=ToolCheckStatus.FAILED,
                                   exit_code=100, duration_ms=5, command="buf lint", files=["a.proto"],
                                   message="buf lint exited 100.")
    assert result_event(result) == {"event": "result", "tool": "buf", "check": "lint", "label": "buf lint",
                                    "status": "failed", "exit_code": 100, "duration_ms": 5,
                                    "command": "buf lint", "files": ["a.proto"],
                                    "message": "buf lint exited 100."}


# --- the real toolchain ----------------------------------------------------------


def _buf_installed() -> bool:
    from app.toolchain_packaging import register_bundled_tools
    from app.toolchain_runner import is_tool_available

    register_bundled_tools()
    return is_tool_available("buf")


@pytest.mark.skipif(not _buf_installed(), reason="buf is not installed in this runtime")
async def test_buf_lint_streams_findings_and_exit_status():
    """The acceptance case: ``buf lint`` on a proto bundle streams its output and reports its exit."""
    events: List[Dict[str, Any]] = []
    result = await run_tool_check(tool_check_command("buf", "lint"), {"acme/v1/shop.proto": PROTO},
                                  label="buf lint", on_event=events.append)
    output = "".join(e["text"] for e in events if e["event"] == "output")
    assert result.status == ToolCheckStatus.FAILED and result.exit_code == 100
    assert 'Message name "widget" should be PascalCase' in output
    assert "acme/v1/shop.proto:3:9" in output  # relative: the scratch path is hidden
