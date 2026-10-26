"""Tests for RAML parse / resolve through AMF — MFI-15.1 (#3799).

AMF is a JVM tool the CI runtime does not install, so most tests replay AMF output recorded
from the real ``amf`` 5.7.1 CLI on the ``tests/fixtures/raml_amf/petstore`` set
(``tests/fixtures/raml_amf/recordings``; the staging path is stored as ``/__STAGING__`` and
swapped for the real one on replay). :func:`test_live_amf_matches_the_recording` runs the
real tool when it is available (``APIOME_AMF_BIN`` or ``amf`` on ``PATH``) and checks that
the recording still matches it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import raml_amf
from app import raml_import_source as raml_import_source_module
from app.fileset import IntakeFileset
from app.import_source import ImportSourceError
from app.raml_amf import (
    AMF_TOOL_KEY,
    amf_model_sha256,
    check_reference_targets,
    find_reference_targets,
    parse_raml_set_with_amf,
    parse_validation_violations,
    references_other_files,
)
from app.raml_amf_mapper import document_from_amf_model
from app.raml_import_source import RamlImportSource
from app.raml_normalizer import RamlNormalizer
from app.toolchain_runner import ToolNotAvailableError, ToolRunResult, ToolTimeoutError

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "raml_amf"
_SET_DIR = _FIXTURES / "petstore"
_RECORDINGS = _FIXTURES / "recordings"
_PLACEHOLDER = "/__STAGING__"


def _petstore_members() -> Dict[str, str]:
    """The fixture set's members, path → text."""
    return {
        str(path.relative_to(_SET_DIR)): path.read_text(encoding="utf-8")
        for path in sorted(_SET_DIR.rglob("*"))
        if path.is_file()
    }


def _recording(name: str) -> Dict[str, str]:
    """A recorded ``amf parse`` run (``stdout`` / ``stderr``)."""
    return json.loads((_RECORDINGS / f"{name}.json").read_text(encoding="utf-8"))


def _replay(monkeypatch: pytest.MonkeyPatch, name: str) -> List[Dict[str, Any]]:
    """Make ``run_tool_blocking`` replay a recording, and return the calls it receives."""
    calls: List[Dict[str, Any]] = []
    recorded = _recording(name)

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        calls.append({"key": key, "args": list(args), **kwargs})
        staging = kwargs["cwd"]
        return ToolRunResult(
            key=key,
            argv=[key, *args],
            exit_code=0,
            stdout=recorded["stdout"].replace(_PLACEHOLDER, staging),
            stderr=recorded["stderr"].replace(_PLACEHOLDER, staging),
            duration_ms=1,
        )

    monkeypatch.setattr(raml_amf, "run_tool_blocking", _fake)
    return calls


@pytest.fixture()
def with_amf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report AMF as available to the import source."""
    monkeypatch.setattr(raml_import_source_module, "amf_available", lambda: True)


@pytest.fixture()
def without_amf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report AMF as unavailable to the import source."""
    monkeypatch.setattr(raml_import_source_module, "amf_available", lambda: False)


# ===========================================================================
# Reference scanning and the path guard
# ===========================================================================


def test_find_reference_targets_reads_includes_uses_and_json_refs():
    assert find_reference_targets("api.raml", _petstore_members()["api.raml"]) == [
        "types/pet.raml",
        "examples/pet.json",
        "libs/common.raml",
    ]
    assert find_reference_targets("schema.json", '{"$ref": "other.json#/a", "x": {"$ref": "#/local"}}') == [
        "other.json#/a"
    ]
    assert find_reference_targets("overlay.raml", "#%RAML 1.0 Overlay\nextends: api.raml\ntitle: X\n") == ["api.raml"]
    assert find_reference_targets("bad.raml", "key: [unclosed\n!include x.raml") == ["x.raml"]


def test_references_other_files():
    assert references_other_files(_petstore_members()) is True
    assert references_other_files({"api.raml": "#%RAML 1.0\ntitle: X\n/a:\n  get:\n"}) is False


@pytest.mark.parametrize(
    "target",
    ["/etc/hostname", "../../etc/hostname", "https://evil.example/lib.raml", "file:///etc/passwd", "C:\\x.raml"],
)
def test_check_reference_targets_refuses_paths_outside_the_set(target: str):
    members = {"api.raml": f"#%RAML 1.0\ntitle: X\ntypes:\n  A: !include {target}\n"}
    with pytest.raises(ImportSourceError) as excinfo:
        check_reference_targets(members)
    assert excinfo.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert target in str(excinfo.value)


def test_check_reference_targets_allows_relative_paths_inside_the_set():
    check_reference_targets(_petstore_members())
    # `..` that stays inside the set is fine (types/pet.raml uses ../libs/common.raml).
    check_reference_targets({"a/b/api.raml": "!include ../c.raml"})


def test_a_member_path_outside_the_set_is_refused(with_amf, monkeypatch):
    _replay(monkeypatch, "petstore")
    with pytest.raises(ImportSourceError) as excinfo:
        parse_raml_set_with_amf({"../api.raml": "#%RAML 1.0\ntitle: X\n"}, "../api.raml")
    assert excinfo.value.code == "INPUT_ARCHIVE_INVALID"


# ===========================================================================
# AMF runs (replayed)
# ===========================================================================


def test_amf_is_called_on_the_staged_root_with_source_maps(monkeypatch):
    calls = _replay(monkeypatch, "petstore")
    parse_raml_set_with_amf(_petstore_members(), "api.raml")
    (call,) = calls
    assert call["key"] == AMF_TOOL_KEY
    args = call["args"]
    assert args[0] == "parse"
    assert args[1] == Path(call["cwd"], "api.raml").resolve().as_uri()
    assert args[2:] == ["-in", "RAML 1.0", "-mime-in", "application/yaml", "-ctx", "true", "-sm", "true"]
    assert call["extra_env"] == {"HOME": call["cwd"]}
    # The staging directory is removed afterwards.
    assert not Path(call["cwd"]).exists()


def test_included_and_library_types_resolve(monkeypatch):
    _replay(monkeypatch, "petstore")
    doc = parse_raml_set_with_amf(_petstore_members(), "api.raml")
    types = {t.name: t for t in doc.types}
    assert list(types) == ["Pet", "common.Status", "common.Error"]
    pet = types["Pet"]
    assert pet.description == "A pet in the store."
    assert [(f.name, f.type_expr, f.required) for f in pet.fields] == [
        ("id", "integer", True),
        ("name", "string", True),
        ("status", "common.Status", True),
        ("tag", "string", False),
        ("tags", "string[]", False),
    ]
    # A field's own description wins over its type's.
    assert next(f for f in pet.fields if f.name == "status").description == "Where the pet is in the adoption process."
    assert types["common.Status"].enum_values == ("available", "pending", "sold")
    assert [f.name for f in types["common.Error"].fields] == ["code", "message"]


def test_resources_parameters_and_bodies_resolve(monkeypatch):
    _replay(monkeypatch, "petstore")
    doc = parse_raml_set_with_amf(_petstore_members(), "api.raml")
    ops = {(o.method, o.path): o for o in doc.operations}
    assert set(ops) == {("get", "/pets"), ("post", "/pets"), ("get", "/pets/{petId}")}
    list_pets = ops[("get", "/pets")]
    assert list_pets.description == "List pets."
    assert [(p.name, p.location, p.type_expr, p.required) for p in list_pets.parameters] == [
        ("limit", "query", "integer", False)
    ]
    assert list_pets.response_types == (("200", "Pet"),)
    assert ops[("post", "/pets")].request_type == "Pet"
    get_pet = ops[("get", "/pets/{petId}")]
    assert [(p.name, p.location, p.type_expr, p.description) for p in get_pet.parameters] == [
        ("petId", "path", "integer", "The pet's id.")
    ]
    assert get_pet.response_types == (("200", "Pet"), ("404", "common.Error"))


def test_document_metadata_and_provenance(monkeypatch):
    _replay(monkeypatch, "petstore")
    members = _petstore_members()
    doc = parse_raml_set_with_amf(members, "api.raml")
    assert (doc.raml_version, doc.title, doc.version, doc.base_uri, doc.media_type) == (
        "1.0",
        "Pet Store",
        "v1",
        "https://api.example.com/{version}",
        "application/json",
    )
    assert doc.description == "Pets, with their types split across files."
    assert doc.raw == members["api.raml"]
    assert doc.source_files == ("api.raml", "examples/pet.json", "libs/common.raml", "types/pet.raml")
    assert doc.model_sha256 and len(doc.model_sha256) == 64


def test_model_hash_does_not_depend_on_the_staging_directory(monkeypatch):
    _replay(monkeypatch, "petstore")
    first = parse_raml_set_with_amf(_petstore_members(), "api.raml").model_sha256
    second = parse_raml_set_with_amf(_petstore_members(), "api.raml").model_sha256
    assert first == second


def test_model_hash_ignores_source_maps_but_not_content():
    model = json.loads(_recording("petstore")["stdout"])
    baseline = amf_model_sha256(model, Path(_PLACEHOLDER))
    without_maps = {
        **model,
        "@graph": [n for n in model["@graph"] if "/source-map" not in n["@id"]],
    }
    assert amf_model_sha256(without_maps, Path(_PLACEHOLDER)) == baseline
    changed = json.loads(json.dumps(model).replace('"Pet Store"', '"Cat Store"'))
    assert amf_model_sha256(changed, Path(_PLACEHOLDER)) != baseline


def test_a_missing_include_is_an_unresolved_reference(monkeypatch):
    _replay(monkeypatch, "missing-include")
    members = {k: v for k, v in _petstore_members().items() if k != "types/pet.raml"}
    with pytest.raises(ImportSourceError) as excinfo:
        parse_raml_set_with_amf(members, "api.raml")
    assert excinfo.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "Pet" in str(excinfo.value)


def test_a_validation_failure_lists_amf_violations(monkeypatch):
    _replay(monkeypatch, "missing-title")
    with pytest.raises(ImportSourceError) as excinfo:
        parse_raml_set_with_amf(_petstore_members(), "api.raml")
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"
    assert str(excinfo.value) == "AMF found 1 problem in the RAML set: API title is mandatory (api.raml line 3)"


def test_parse_validation_violations_skips_warnings():
    stderr = (
        "Conforms: false\n"
        "- Constraint: a\n  Message: Kept\n  Severity: Violation\n  Range: [(7,2)-(8,0)]\n"
        "  Location: file:////stage/libs/x.raml\n"
        "- Constraint: b\n  Message: Dropped\n  Severity: Warning\n"
    )
    assert parse_validation_violations(stderr, Path("/stage")) == ["Kept (libs/x.raml line 7)"]
    assert parse_validation_violations("", Path("/stage")) == []


def test_output_that_is_not_a_model_is_malformed(monkeypatch):
    def _junk(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        return ToolRunResult(
            key=key,
            argv=[key],
            exit_code=0,
            stdout="",
            stderr=f"Exception in thread \"main\" boom: {kwargs['cwd']}/api.raml\n\tat x.y(Z.scala:1)\n",
            duration_ms=1,
        )

    monkeypatch.setattr(raml_amf, "run_tool_blocking", _junk)
    with pytest.raises(ImportSourceError) as excinfo:
        parse_raml_set_with_amf(_petstore_members(), "api.raml")
    assert excinfo.value.code == "INPUT_MALFORMED"
    assert str(excinfo.value) == 'AMF could not parse the RAML set: Exception in thread "main" boom: api.raml'


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ToolNotAvailableError(AMF_TOOL_KEY, "amf"), "ADAPTER_UNAVAILABLE"),
        (ToolTimeoutError(AMF_TOOL_KEY, 120.0), "INPUT_TIME_LIMIT"),
    ],
)
def test_runner_failures_map_to_intake_codes(monkeypatch, error: Exception, code: str):
    def _fail(*args: Any, **kwargs: Any) -> ToolRunResult:
        raise error

    monkeypatch.setattr(raml_amf, "run_tool_blocking", _fail)
    with pytest.raises(ImportSourceError) as excinfo:
        parse_raml_set_with_amf(_petstore_members(), "api.raml")
    assert excinfo.value.code == code


def test_a_model_that_records_a_file_outside_the_set_is_refused(monkeypatch):
    recorded = _recording("petstore")

    def _leaky(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        stdout = recorded["stdout"].replace(_PLACEHOLDER, kwargs["cwd"])
        stdout = stdout.replace(f'{kwargs["cwd"]}/examples/pet.json', "/etc/hostname", 1)
        return ToolRunResult(key=key, argv=[key], exit_code=0, stdout=stdout, stderr="", duration_ms=1)

    monkeypatch.setattr(raml_amf, "run_tool_blocking", _leaky)
    with pytest.raises(ImportSourceError) as excinfo:
        parse_raml_set_with_amf(_petstore_members(), "api.raml")
    assert excinfo.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "hostname" in str(excinfo.value)


def test_a_raml_08_root_is_parsed_as_raml_08(monkeypatch):
    calls = _replay(monkeypatch, "petstore")
    members = _petstore_members()
    members["api.raml"] = members["api.raml"].replace("#%RAML 1.0", "#%RAML 0.8", 1)
    parse_raml_set_with_amf(members, "api.raml")
    assert calls[0]["args"][3] == "RAML 0.8"


# ===========================================================================
# Mapper edge cases (hand-built graphs)
# ===========================================================================


def _graph(*nodes: Dict[str, Any]) -> Dict[str, Any]:
    """A minimal AMF model: a root document encoding a WebAPI, plus ``nodes``."""
    return {"@graph": list(nodes), "@context": {}}


_ROOT = {"@id": "", "doc:root": True, "doc:encodes": {"@id": "#/web-api"}, "doc:declares": []}


def test_mapper_reports_an_unknown_type_name():
    model = _graph(
        {**_ROOT, "doc:declares": [{"@id": "#/A"}]},
        {"@id": "#/web-api", "core:name": "T"},
        {"@id": "#/A", "@type": ["shacl:NodeShape"], "shacl:name": "A", "shacl:property": [{"@id": "#/A/p"}]},
        {"@id": "#/A/p", "shacl:name": "p", "raml-shapes:range": {"@id": "#/A/p/unresolved"}},
        {"@id": "#/A/p/unresolved", "@type": ["raml-shapes:AnyShape"], "shacl:name": "strin"},
    )
    with pytest.raises(ImportSourceError) as excinfo:
        document_from_amf_model(model, raw="")
    assert excinfo.value.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "strin" in str(excinfo.value)


def test_mapper_requires_a_title_and_some_content():
    no_title = _graph(
        {**_ROOT, "doc:declares": [{"@id": "#/A"}]},
        {"@id": "#/web-api"},
        {"@id": "#/A", "shacl:name": "A"},
    )
    with pytest.raises(ImportSourceError) as excinfo:
        document_from_amf_model(no_title, raw="")
    assert excinfo.value.code == "INPUT_SEMANTIC_INVALID"
    empty = _graph(_ROOT, {"@id": "#/web-api", "core:name": "T"})
    with pytest.raises(ImportSourceError) as excinfo:
        document_from_amf_model(empty, raw="", source_label="x.raml")
    assert str(excinfo.value) == "No RAML types or resources found (x.raml)"
    with pytest.raises(ImportSourceError) as excinfo:
        document_from_amf_model(_graph({"@id": "#/web-api"}), raw="")
    assert excinfo.value.code == "INPUT_MALFORMED"


def test_mapper_types_scalars_arrays_files_and_inline_objects():
    model = _graph(
        {**_ROOT, "doc:declares": [{"@id": "#/A"}]},
        {"@id": "#/web-api", "core:name": "T"},
        {
            "@id": "#/A",
            "shacl:name": "A",
            "shacl:property": [{"@id": f"#/A/{n}"} for n in ("d", "f", "o", "x", "n")],
        },
        {"@id": "#/A/d", "shacl:name": "d", "shacl:minCount": 1, "raml-shapes:range": {"@id": "#/s/d"}},
        {"@id": "#/s/d", "@type": ["raml-shapes:ScalarShape"], "shacl:datatype": [{"@id": "http://www.w3.org/2001/XMLSchema#dateTime"}]},
        {"@id": "#/A/f", "shacl:name": "f", "raml-shapes:range": {"@id": "#/s/f"}},
        {"@id": "#/s/f", "@type": ["raml-shapes:FileShape"]},
        {"@id": "#/A/o", "shacl:name": "o", "raml-shapes:range": {"@id": "#/s/o"}},
        {"@id": "#/s/o", "@type": ["shacl:NodeShape"]},
        {"@id": "#/A/x", "shacl:name": "x", "raml-shapes:range": {"@id": "#/s/x"}},
        {"@id": "#/s/x", "@type": ["raml-shapes:ArrayShape"]},
        {"@id": "#/A/n", "shacl:name": "n", "raml-shapes:range": {"@id": "#/s/n"}},
        {"@id": "#/s/n", "@type": ["raml-shapes:NilShape"]},
    )
    (a,) = document_from_amf_model(model, raw="").types
    assert [(f.name, f.type_expr, f.required) for f in a.fields] == [
        ("d", "datetime", True),
        ("f", "file", False),
        ("o", "object", False),
        ("x", "any[]", False),
        ("n", "nil", False),
    ]


# ===========================================================================
# The import source: AMF when available, the YAML reader otherwise
# ===========================================================================


def test_fileset_import_goes_through_amf(with_amf, monkeypatch):
    _replay(monkeypatch, "petstore")
    fileset = IntakeFileset.from_members(_petstore_members(), root="api.raml")
    doc = RamlImportSource().parse_fileset(fileset)
    assert {t.name for t in doc.types} == {"Pet", "common.Status", "common.Error"}
    api = RamlNormalizer().normalize(doc)
    assert {t.name for t in api.types} >= {"Pet", "common.Status", "common.Error"}
    assert api.extras["raml_amf_model_sha256"] == doc.model_sha256
    assert api.extras["raml_source_files"] == list(doc.source_files)


def test_a_single_document_goes_through_amf_too(with_amf, monkeypatch):
    calls = _replay(monkeypatch, "petstore")
    RamlImportSource().parse(_petstore_members()["api.raml"], source_label="api.raml")
    assert calls and calls[0]["args"][1].endswith("/api.raml")


def test_without_amf_a_self_contained_document_uses_the_yaml_reader(without_amf, monkeypatch):
    def _never(*args: Any, **kwargs: Any) -> ToolRunResult:
        raise AssertionError("AMF must not run")

    monkeypatch.setattr(raml_amf, "run_tool_blocking", _never)
    doc = RamlImportSource().parse("#%RAML 1.0\ntitle: Ping\n/ping:\n  get:\n    description: ok\n")
    assert doc.title == "Ping"
    assert doc.model_sha256 is None
    assert "raml_amf_model_sha256" not in RamlNormalizer().normalize(doc).extras


def test_without_amf_a_set_with_includes_is_refused(without_amf):
    fileset = IntakeFileset.from_members(_petstore_members(), root="api.raml")
    with pytest.raises(ImportSourceError) as excinfo:
        RamlImportSource().parse_fileset(fileset)
    assert excinfo.value.code == "ADAPTER_UNAVAILABLE"
    assert "!include" in str(excinfo.value)


def test_amf_tool_reads_its_own_output():
    from app.toolchain_packaging import bundled_tool

    tool = bundled_tool(AMF_TOOL_KEY)
    assert tool is not None and tool.parses_json is False


# ===========================================================================
# Live AMF (only when the tool is installed)
# ===========================================================================


@pytest.mark.skipif(not raml_amf.amf_available(), reason="AMF (amf) is not installed in this runtime")
def test_live_amf_matches_the_recording(monkeypatch):
    live = parse_raml_set_with_amf(_petstore_members(), "api.raml")
    _replay(monkeypatch, "petstore")
    replayed = parse_raml_set_with_amf(_petstore_members(), "api.raml")
    assert live.types == replayed.types
    assert live.operations == replayed.operations
    assert live.model_sha256 == replayed.model_sha256
