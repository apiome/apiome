"""A single ``.tsp`` file normalizes through its emitted OpenAPI — MFI-14.2 (#3795).

A one-file upload is compiled by ``tsp`` like a one-file project, so its catalog item is built by
the OpenAPI normalizer — the same integration surface (diff, lint, convert) a multi-file project
uses (MFI-14.1). Without the compiler it falls back to the built-in reader, and the item records
which path ran. The compiler is replayed from the MFI-14.1 recordings, as in
:mod:`tests.test_typespec_compile`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.fileset import IntakeFileset
from app.import_source import ImportSourceError
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolTimeoutError
from app.typespec_compile import TSP_NODE_MODULES_ENV, TSP_TOOL_KEY, TypeSpecCompiled
from app.typespec_import_source import (
    COMPILE_SINGLE_FILES_ENV,
    TypeSpecImportSource,
    _single_file_root,
    compile_single_files,
)
from app.typespec_parser import TypeSpecDocument
from tests.test_typespec_compile import _emitted_openapi, _raise, _replay

_SOURCE = TypeSpecImportSource()

PETS = """import "@typespec/http";
using TypeSpec.Http;

@service(#{ title: "Pet Store" })
namespace PetStore;

model Pet { id: int32; name: string; }

@route("/pets")
op listPets(): Pet[];
"""


@pytest.fixture()
def libraries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in for the bundled TypeSpec libraries, as in :mod:`tests.test_typespec_compile`."""
    node_modules = tmp_path / "libs" / "node_modules"
    (node_modules / "@typespec" / "http").mkdir(parents=True)
    monkeypatch.setenv(TSP_NODE_MODULES_ENV, str(node_modules))
    return node_modules


@pytest.fixture()
def compiling(monkeypatch: pytest.MonkeyPatch) -> None:
    """Turn the compiled single-file path on (the suite pins the reader; tests/conftest.py)."""
    monkeypatch.setenv(COMPILE_SINGLE_FILES_ENV, "1")


# --- the switch and the staged name -----------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [("1", True), ("", True), ("yes", True), ("0", False), ("false", False), ("OFF", False), ("no", False)],
)
def test_compile_single_files_reads_the_switch(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv(COMPILE_SINGLE_FILES_ENV, value)
    assert compile_single_files() is expected


def test_compile_single_files_is_on_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(COMPILE_SINGLE_FILES_ENV, raising=False)
    assert compile_single_files() is True


@pytest.mark.parametrize(
    "label, expected",
    [
        ("pets.tsp", "pets.tsp"),
        ("specs/pets.tsp", "pets.tsp"),
        ("C:\\\\specs\\\\pets.tsp", "pets.tsp"),
        ("https://host/api/pets.tsp?raw=1", "pets.tsp"),
        ("pasted", "main.tsp"),
        (".tsp", "main.tsp"),
        (None, "main.tsp"),
    ],
)
def test_a_single_file_is_staged_under_its_own_name(label, expected: str) -> None:
    assert _single_file_root(label) == expected


# --- the compiled path ------------------------------------------------------------------------


def test_a_single_file_compiles_and_normalizes_through_openapi(monkeypatch, libraries, compiling) -> None:
    calls = _replay(monkeypatch, "petstore")
    compiled = _SOURCE.parse(PETS, source_label="specs/pets.tsp")

    assert isinstance(compiled, TypeSpecCompiled)
    assert calls[0]["key"] == TSP_TOOL_KEY
    assert calls[0]["staged"] == ["pets.tsp", "tspconfig.yaml"]
    assert calls[0]["args"][:2] == ["compile", "pets.tsp"]
    assert compiled.openapi == _emitted_openapi()

    api = _SOURCE.normalize(compiled)
    assert api.format == "typespec"
    assert api.extras["typespec_compiled_via"] == "tsp"
    assert api.extras["typespec_source_files"] == ["pets.tsp"]
    # Built by the OpenAPI normalizer: the operations are the emitted OpenAPI's routes.
    routes = {(op.http_method, op.http_path) for service in api.services for op in service.operations}
    emitted = {(method.upper(), path) for path, item in _emitted_openapi()["paths"].items() for method in item}
    assert routes and routes <= emitted | {(m.lower(), p) for m, p in emitted}


def test_a_single_file_and_the_same_compile_as_a_set_give_one_model(monkeypatch, libraries, compiling) -> None:
    _replay(monkeypatch, "petstore")
    alone = _SOURCE.normalize(_SOURCE.parse(PETS, source_label="pets.tsp"), include_raw=False)
    in_a_set = _SOURCE.normalize(
        _SOURCE.parse_fileset(IntakeFileset.from_members({"pets.tsp": PETS}, root="pets.tsp")), include_raw=False
    )
    assert _SOURCE.fingerprint(alone) == _SOURCE.fingerprint(in_a_set)


def test_a_pasted_file_compiles_as_main_tsp(monkeypatch, libraries, compiling) -> None:
    calls = _replay(monkeypatch, "petstore")
    _SOURCE.parse(PETS)
    assert calls[0]["staged"] == ["main.tsp", "tspconfig.yaml"]


# --- the reader fallback ----------------------------------------------------------------------


def test_without_the_compiler_a_single_file_falls_back_to_the_reader(monkeypatch, compiling) -> None:
    _raise(monkeypatch, ToolNotAvailableError(TSP_TOOL_KEY, "missing"))
    document = _SOURCE.parse(PETS, source_label="pets.tsp")
    assert isinstance(document, TypeSpecDocument)
    api = _SOURCE.normalize(document)
    assert api.extras["typespec_compiled_via"] == "reader"
    assert "Pet" in {t.name for t in api.types}


def test_with_the_switch_off_the_compiler_is_not_run(monkeypatch) -> None:
    monkeypatch.setenv(COMPILE_SINGLE_FILES_ENV, "0")
    calls = _replay(monkeypatch, "petstore")
    assert isinstance(_SOURCE.parse(PETS, source_label="pets.tsp"), TypeSpecDocument)
    assert calls == []


def test_text_that_is_not_typespec_fails_before_any_compile(monkeypatch, compiling) -> None:
    calls = _replay(monkeypatch, "petstore")
    with pytest.raises(ImportSourceError):
        _SOURCE.parse("this is not typespec", source_label="notes.tsp")
    assert calls == []


# --- compile refusals surface, as they do for a project --------------------------------------


@pytest.mark.parametrize(
    "error, code",
    [
        (
            ToolExecutionError(TSP_TOOL_KEY, 1, "", "pets.tsp:3:1 - error invalid-ref: Unknown identifier"),
            "INPUT_SEMANTIC_INVALID",
        ),
        (ToolTimeoutError(TSP_TOOL_KEY, 60.0), "INPUT_TIME_LIMIT"),
    ],
)
def test_a_compile_failure_is_reported(monkeypatch, libraries, compiling, error, code: str) -> None:
    _raise(monkeypatch, error)
    with pytest.raises(ImportSourceError) as exc:
        _SOURCE.parse(PETS, source_label="pets.tsp")
    assert exc.value.code == code


def test_a_single_file_that_imports_a_file_it_was_not_uploaded_with_is_refused(monkeypatch, compiling) -> None:
    calls = _replay(monkeypatch, "petstore")
    text = PETS.replace('import "@typespec/http";', 'import "@typespec/http";\nimport "./models.tsp";')
    with pytest.raises(ImportSourceError, match="not in the upload") as exc:
        _SOURCE.parse(text, source_label="main.tsp")
    assert exc.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert calls == []


def test_a_lone_file_in_a_set_compiles_too(monkeypatch, libraries, compiling) -> None:
    calls = _replay(monkeypatch, "petstore")
    members = {"main.tsp": PETS, "package.json": "{}"}
    document = _SOURCE.parse_fileset(IntakeFileset.from_members(members, root="main.tsp"))
    assert isinstance(document, TypeSpecCompiled)
    assert calls[0]["staged"] == ["main.tsp", "tspconfig.yaml"]
