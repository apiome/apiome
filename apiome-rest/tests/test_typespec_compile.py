"""Tests for TypeSpec compile via the toolchain runner — MFI-14.1 (#3794).

The TypeSpec compiler is a Node tool the CI runtime does not install, so most tests replay
output recorded from the real ``@typespec/compiler`` 0.65.0 (with ``@typespec/http``, ``rest``,
``openapi3`` and ``versioning`` 0.65.0) on the ``tests/fixtures/typespec_compile/petstore`` set
(``tests/fixtures/typespec_compile/recordings``: the compiler's stdout/stderr and the files it
emitted). :func:`test_live_compile_matches_the_recording` runs the real compiler when ``tsp`` and
the TypeSpec libraries are available.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import typespec_compile
from app.canonical_model import ApiParadigm
from app.conversion_passthrough import ConversionMode, resolve_passthrough_preview
from app.fileset import IntakeFileset
from app.import_source import ImportSourceError
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolRunResult, ToolTimeoutError
from app.typespec_compile import (
    OPENAPI_TSPCONFIG,
    TSP_NODE_MODULES_ENV,
    TSP_TOOL_KEY,
    TypeSpecCompiled,
    check_import_targets,
    compile_typespec_set,
    find_import_targets,
    openapi_sha256,
    read_typespec_openapi_output,
    typespec_node_modules,
)
from app.typespec_import_source import TypeSpecImportSource

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "typespec_compile"
_SET_DIR = _FIXTURES / "petstore"


def _members() -> Dict[str, str]:
    """The fixture set's members, path → text."""
    return {
        str(path.relative_to(_SET_DIR)): path.read_text(encoding="utf-8")
        for path in sorted(_SET_DIR.rglob("*"))
        if path.is_file()
    }


def _recording(name: str) -> Dict[str, Any]:
    """A recorded ``tsp compile`` run."""
    return json.loads((_FIXTURES / "recordings" / f"{name}.json").read_text(encoding="utf-8"))


def _emitted_openapi() -> Dict[str, Any]:
    """The OpenAPI document the recorded successful compile emitted."""
    return json.loads(_recording("petstore")["emitted"]["@typespec/openapi3/openapi.json"])


@pytest.fixture()
def libraries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the bundled TypeSpec libraries (``node_modules/@typespec``)."""
    node_modules = tmp_path / "libs" / "node_modules"
    (node_modules / "@typespec" / "http").mkdir(parents=True)
    monkeypatch.setenv(TSP_NODE_MODULES_ENV, str(node_modules))
    return node_modules


def _replay(monkeypatch: pytest.MonkeyPatch, name: str) -> List[Dict[str, Any]]:
    """Make ``run_tool_blocking`` replay a recording; return what each call saw.

    A successful recording writes its emitted files into the call's ``--output-dir``; a failed
    one raises :class:`ToolExecutionError` with the recorded streams, as the runner would.
    """
    calls: List[Dict[str, Any]] = []
    recorded = _recording(name)

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        cwd = Path(kwargs["cwd"])
        calls.append(
            {
                "key": key,
                "args": list(args),
                "staged": sorted(
                    str(p.relative_to(cwd)) for p in cwd.rglob("*") if p.is_file() and "node_modules" not in p.parts
                ),
                "tspconfig": (cwd / "tspconfig.yaml").read_text(encoding="utf-8"),
                "node_modules": os.path.realpath(cwd / "node_modules") if (cwd / "node_modules").exists() else None,
                **kwargs,
            }
        )
        if recorded["exit_code"] != 0:
            raise ToolExecutionError(key, recorded["exit_code"], recorded["stdout"], recorded["stderr"])
        out = Path(args[args.index("--output-dir") + 1])
        for relative, text in recorded["emitted"].items():
            (out / relative).parent.mkdir(parents=True, exist_ok=True)
            (out / relative).write_text(text, encoding="utf-8")
        return ToolRunResult(
            key=key, argv=[key, *args], exit_code=0, stdout=recorded["stdout"], stderr=recorded["stderr"], duration_ms=1
        )

    monkeypatch.setattr(typespec_compile, "run_tool_blocking", _fake)
    return calls


def _raise(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """Make ``run_tool_blocking`` raise ``error``."""

    def _fake(*_args: Any, **_kwargs: Any) -> ToolRunResult:
        raise error

    monkeypatch.setattr(typespec_compile, "run_tool_blocking", _fake)


# ===========================================================================
# Imports and staging
# ===========================================================================


def test_find_import_targets():
    assert find_import_targets(_members()["main.tsp"]) == ["@typespec/http", "./models/pets.tsp", "./ops/pets-ops.tsp"]


def test_check_import_targets_accepts_the_fixture_and_libraries():
    check_import_targets(_members())


@pytest.mark.parametrize("target", ["../outside.tsp", "/etc/x.tsp", "https://host/x.tsp"])
def test_an_import_outside_the_set_is_refused(target: str):
    with pytest.raises(ImportSourceError, match="outside them") as exc:
        check_import_targets({"main.tsp": f'import "{target}";\nnamespace A;'})
    assert exc.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_an_import_of_a_missing_file_is_refused():
    with pytest.raises(ImportSourceError, match="not in the upload") as exc:
        check_import_targets({"main.tsp": 'import "./models.tsp";\nnamespace A;'})
    assert exc.value.code == "INPUT_REFERENCE_UNRESOLVED"


def test_the_compiler_runs_on_the_staged_root_with_the_libraries_linked(monkeypatch, libraries: Path):
    calls = _replay(monkeypatch, "petstore")
    members = {
        **_members(),
        "tspconfig.yaml": "emit: ['@typespec/json-schema']",
        "package.json": "{}",
        "node_modules/evil/index.js": "x",
    }
    compile_typespec_set(members, "main.tsp")
    (call,) = calls
    assert call["key"] == TSP_TOOL_KEY
    assert call["args"][:2] == ["compile", "main.tsp"]
    # Only .tsp files are staged; Apiome's own tspconfig replaces any uploaded one.
    assert call["staged"] == ["main.tsp", "models/pets.tsp", "ops/pets-ops.tsp", "tspconfig.yaml"]
    assert call["tspconfig"] == OPENAPI_TSPCONFIG
    assert call["node_modules"] == str(libraries)
    assert call["extra_env"]["HOME"] != call["cwd"]
    # Everything is removed afterwards — but never the linked libraries.
    assert not Path(call["cwd"]).exists()
    assert (libraries / "@typespec" / "http").is_dir()


def test_without_the_libraries_nothing_is_linked(monkeypatch, tmp_path):
    monkeypatch.setenv(TSP_NODE_MODULES_ENV, str(tmp_path / "missing"))
    monkeypatch.setattr(
        "app.toolchain_packaging.probe_tool", lambda key: None
    )
    calls = _replay(monkeypatch, "petstore")
    compile_typespec_set(_members(), "main.tsp")
    assert calls[0]["node_modules"] is None


def test_typespec_node_modules_is_found_beside_the_wrapper(monkeypatch, tmp_path):
    prefix = tmp_path / "tools"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "tsp").write_text("#!/bin/sh\n")
    (prefix / "lib" / "node" / "node_modules" / "@typespec").mkdir(parents=True)
    monkeypatch.delenv(TSP_NODE_MODULES_ENV, raising=False)

    class _Probe:
        resolved_path = str(prefix / "bin" / "tsp")

    monkeypatch.setattr("app.toolchain_packaging.probe_tool", lambda key: _Probe())
    assert typespec_node_modules() == prefix / "lib" / "node" / "node_modules"


def test_a_missing_root_or_a_path_outside_the_set_is_refused():
    with pytest.raises(ImportSourceError) as exc:
        compile_typespec_set({"a.tsp": "namespace A;"}, "main.tsp")
    assert exc.value.code == "INPUT_ARCHIVE_INVALID"
    with pytest.raises(ImportSourceError) as exc:
        compile_typespec_set({"main.tsp": "namespace A;", "../x.tsp": "namespace B;"}, "main.tsp")
    assert exc.value.code == "INPUT_ARCHIVE_INVALID"


# ===========================================================================
# Compile results
# ===========================================================================


def test_the_compiled_set_carries_the_emitted_openapi_and_identity(monkeypatch, libraries):
    _replay(monkeypatch, "petstore")
    compiled = compile_typespec_set(_members(), "main.tsp")
    assert compiled.openapi == _emitted_openapi()
    assert compiled.openapi["info"]["title"] == "Pet Store"
    assert sorted(compiled.openapi["paths"]) == ["/pets", "/pets/{petId}"]
    assert compiled.source_files == ("main.tsp", "models/pets.tsp", "ops/pets-ops.tsp")
    assert compiled.namespaces == ("PetStore", "PetStore.Models")
    assert compiled.openapi_sha256 == openapi_sha256(_emitted_openapi())
    assert compiled.root_text == _members()["main.tsp"]


def test_compile_diagnostics_are_quoted(monkeypatch, libraries):
    _replay(monkeypatch, "invalid-ref")
    with pytest.raises(ImportSourceError) as exc:
        compile_typespec_set(_members(), "main.tsp")
    assert exc.value.code == "INPUT_SEMANTIC_INVALID"
    assert "models/pets.tsp:9:11 - error invalid-ref: Unknown identifier PetState" in str(exc.value)


@pytest.mark.parametrize(
    "error, code",
    [
        (ToolNotAvailableError(TSP_TOOL_KEY, "missing"), "ADAPTER_UNAVAILABLE"),
        (ToolTimeoutError(TSP_TOOL_KEY, 120.0), "INPUT_TIME_LIMIT"),
    ],
)
def test_runner_failures_map_to_intake_codes(monkeypatch, libraries, error: Exception, code: str):
    _raise(monkeypatch, error)
    with pytest.raises(ImportSourceError) as exc:
        compile_typespec_set(_members(), "main.tsp")
    assert exc.value.code == code


def test_a_compile_that_emits_nothing_is_malformed(monkeypatch, libraries):
    def _fake(key: str, args: List[str], **_kwargs: Any) -> ToolRunResult:
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout="", stderr="", duration_ms=1)

    monkeypatch.setattr(typespec_compile, "run_tool_blocking", _fake)
    with pytest.raises(ImportSourceError) as exc:
        compile_typespec_set(_members(), "main.tsp")
    assert exc.value.code == "INPUT_MALFORMED"


def test_read_typespec_openapi_output_skips_non_openapi_files(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "other.json").write_text('{"a": 1}')
    (tmp_path / "x" / "openapi.yaml").write_text("openapi: 3.0.0\ninfo: {title: T, version: '1'}\npaths: {}\n")
    assert read_typespec_openapi_output(tmp_path)["info"]["title"] == "T"
    assert read_typespec_openapi_output(tmp_path / "missing") is None


# ===========================================================================
# Import source
# ===========================================================================


def test_a_multi_file_set_normalizes_through_openapi_as_a_typespec_item(monkeypatch, libraries):
    _replay(monkeypatch, "petstore")
    source = TypeSpecImportSource()
    compiled = source.parse_fileset(IntakeFileset.from_members(_members(), root="main.tsp"))
    assert isinstance(compiled, TypeSpecCompiled)
    api = source.normalize(compiled)
    assert api.format == "typespec"
    assert api.paradigm is ApiParadigm.REST
    assert api.title == "Pet Store"
    assert api.extras["typespec_compiled_via"] == "tsp"
    assert api.extras["typespec_openapi_format"] == "openapi-3.0"
    assert api.extras["typespec_source_files"] == ["main.tsp", "models/pets.tsp", "ops/pets-ops.tsp"]
    assert api.extras["typespec_namespaces"] == ["PetStore", "PetStore.Models"]
    assert api.raw == {"typespec": _members()["main.tsp"], "openapi": _emitted_openapi()}
    routes = {(op.http_method, op.http_path) for s in api.services for op in s.operations}
    assert routes == {("GET", "/pets"), ("POST", "/pets"), ("GET", "/pets/{petId}")}
    # The emitter names schemas relative to the service namespace.
    assert {"Models.Pet", "Models.PetStatus", "Models.Error"} <= {t.key for t in api.types}


def test_the_fingerprint_does_not_depend_on_member_order(monkeypatch, libraries):
    _replay(monkeypatch, "petstore")
    source = TypeSpecImportSource()
    members = _members()
    forward = source.normalize(source.parse_fileset(IntakeFileset.from_members(members, root="main.tsp")))
    backward = source.normalize(
        source.parse_fileset(IntakeFileset.from_members(dict(reversed(list(members.items()))), root="main.tsp"))
    )
    assert source.fingerprint(forward) == source.fingerprint(backward)


def test_a_single_file_keeps_the_built_in_reader(monkeypatch):
    calls = _replay(monkeypatch, "petstore")
    members = {"main.tsp": 'import "@typespec/http";\nnamespace A;\nmodel Pet { id: int32; }\n', "package.json": "{}"}
    doc = TypeSpecImportSource().parse_fileset(IntakeFileset.from_members(members, root="main.tsp"))
    assert calls == []
    assert not isinstance(doc, TypeSpecCompiled)


def test_without_the_compiler_a_multi_file_set_is_refused(monkeypatch, libraries):
    _raise(monkeypatch, ToolNotAvailableError(TSP_TOOL_KEY, "missing"))
    with pytest.raises(ImportSourceError) as exc:
        TypeSpecImportSource().parse_fileset(IntakeFileset.from_members(_members(), root="main.tsp"))
    assert exc.value.code == "ADAPTER_UNAVAILABLE"


def test_convert_to_openapi_uses_the_compiled_document(monkeypatch, libraries):
    _replay(monkeypatch, "petstore")
    source = TypeSpecImportSource()
    api = source.normalize(source.parse_fileset(IntakeFileset.from_members(_members(), root="main.tsp")))

    def _no_recompile(*_args: Any, **_kwargs: Any) -> Dict[str, Any]:
        raise AssertionError("a compiled set must not be recompiled from its root text")

    monkeypatch.setattr("app.conversion_passthrough.emit_typespec_openapi", _no_recompile)
    document, _report = resolve_passthrough_preview(
        mode=ConversionMode.TYPESPEC_NATIVE, api=api, source_text=_members()["main.tsp"]
    )
    assert document == _emitted_openapi()


# ===========================================================================
# Live compiler (only when tsp and the TypeSpec libraries are installed)
# ===========================================================================


def _live_compiler_ready() -> bool:
    from app.toolchain_packaging import probe_tool, register_bundled_tools

    register_bundled_tools()
    probe = probe_tool(TSP_TOOL_KEY)
    libraries = typespec_node_modules()
    return bool(probe and probe.available and libraries and (libraries / "@typespec" / "openapi3").is_dir())


@pytest.mark.skipif(not _live_compiler_ready(), reason="tsp with @typespec/openapi3 is not installed")
def test_live_compile_matches_the_recording():
    compiled = compile_typespec_set(_members(), "main.tsp")
    assert compiled.openapi == _emitted_openapi()
