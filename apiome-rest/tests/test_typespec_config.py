"""Tests for a TypeSpec project's ``tspconfig.yaml`` — MFI-14.5 (#3798).

The compile tests replay output recorded from the real ``@typespec/compiler`` 0.65.0
(``tests/fixtures/typespec_compile/recordings``):

* ``petstore-tspconfig`` — the ``petstore`` set with ``petstore-tspconfig.yaml`` beside it (two
  OpenAPI versions, ``omit-unreachable-types``, plus settings Apiome ignores);
* ``single-project`` — ``single/main.tsp`` with its ``tspconfig.yaml`` (a one-file project).

:func:`test_live_compiles_match_the_recordings` runs the real compiler when it is available.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

from app.fileset import IntakeFileset
from app.import_source import ImportSourceError
from app.typespec_compile import OPENAPI_TSPCONFIG, compile_typespec_set
from app.typespec_config import build_tspconfig, find_tspconfig, resolve_tspconfig
from app.typespec_import_source import TypeSpecImportSource
from tests.test_typespec_compile import _live_compiler_ready, _recording, _replay, libraries  # noqa: F401

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "typespec_compile"


def _petstore_with_config() -> Dict[str, str]:
    """The petstore set plus its uploaded ``tspconfig.yaml``."""
    root = _FIXTURES / "petstore"
    members = {str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(root.rglob("*")) if p.is_file()}
    members["tspconfig.yaml"] = (_FIXTURES / "petstore-tspconfig.yaml").read_text(encoding="utf-8")
    return members


def _single_project() -> Dict[str, str]:
    """The one-file project: ``main.tsp`` and its ``tspconfig.yaml``."""
    root = _FIXTURES / "single"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(root.iterdir())}


def _emitted(name: str) -> Dict[str, Any]:
    """The OpenAPI a recording emitted."""
    return json.loads(_recording(name)["emitted"]["@typespec/openapi3/openapi.json"])


# ===========================================================================
# Reading tspconfig.yaml
# ===========================================================================


def test_the_honored_settings_are_applied():
    config = resolve_tspconfig(
        "warn-as-error: true\n"
        "options:\n"
        '  "@typespec/openapi3":\n'
        "    openapi-versions: [3.1.0]\n"
        "    omit-unreachable-types: true\n"
        "    include-x-typespec-name: inline-only\n"
        "    safeint-strategy: double-int\n"
    )
    assert config.applied == {
        "warn-as-error": True,
        "options": {
            "@typespec/openapi3": {
                "openapi-versions": ["3.1.0"],
                "omit-unreachable-types": True,
                "include-x-typespec-name": "inline-only",
                "safeint-strategy": "double-int",
            }
        },
    }
    assert config.ignored == ()


def test_everything_else_is_ignored_and_named():
    config = resolve_tspconfig((_FIXTURES / "petstore-tspconfig.yaml").read_text(encoding="utf-8"))
    assert config.applied == {
        "options": {"@typespec/openapi3": {"openapi-versions": ["3.1.0"], "omit-unreachable-types": True}},
        "warn-as-error": False,
    }
    assert config.ignored == (
        "emit: only @typespec/openapi3 runs on import",
        "output-dir: output stays in Apiome's scratch directory",
        'options."@typespec/openapi3".openapi-versions: only the first version (3.1.0) is emitted',
        'options."@typespec/openapi3".output-file: Apiome reads one openapi.json it names itself',
        'options."@typespec/json-schema": only @typespec/openapi3 runs on import',
        "linter: Apiome runs the bundled libraries' built-in linter rulesets itself",
    )


@pytest.mark.parametrize(
    "text, reason",
    [
        ("warn-as-error: yes-please\n", "warn-as-error: expected true or false"),
        ('options:\n  "@typespec/openapi3":\n    safeint-strategy: float\n', "expected one of double-int, int64"),
        ('options:\n  "@typespec/openapi3":\n    openapi-versions: [2.0]\n', "expected one of 3.0.0, 3.1.0"),
        ('options:\n  "@typespec/openapi3":\n    omit-unreachable-types: "yes"\n', "expected true or false"),
        ('options:\n  "@typespec/openapi3":\n    new-line: crlf\n', "line endings do not change the API"),
        ('options:\n  "@typespec/openapi3":\n    emitter-output-dir: /etc\n', "output stays"),
        ("environment-variables:\n  X: {default: y}\n", "no environment interpolation"),
        ("something-new: 1\n", "something-new: not a setting Apiome applies"),
        ("options: [1]\n", "options: not a mapping"),
    ],
)
def test_invalid_or_unknown_settings_are_ignored(text: str, reason: str):
    config = resolve_tspconfig(text)
    assert config.applied == {}
    assert any(reason in line for line in config.ignored)


@pytest.mark.parametrize("text", ["- a list\n", "key: [unclosed\n"])
def test_a_config_that_is_not_a_yaml_mapping_is_malformed(text: str):
    with pytest.raises(ImportSourceError) as exc:
        resolve_tspconfig(text, path="tspconfig.yaml")
    assert exc.value.code == "INPUT_MALFORMED"


def test_an_empty_config_applies_nothing():
    assert resolve_tspconfig("").applied == {}
    assert resolve_tspconfig("# only a comment\n").applied == {}


def test_the_built_config_always_emits_one_openapi_json():
    built = yaml.safe_load(build_tspconfig({"options": {"@typespec/openapi3": {"output-file": "../x.json"}}}))
    assert built["emit"] == ["@typespec/openapi3"]
    assert built["options"]["@typespec/openapi3"]["output-file"] == "openapi.json"
    assert yaml.safe_load(OPENAPI_TSPCONFIG) == {
        "emit": ["@typespec/openapi3"],
        "options": {"@typespec/openapi3": {"output-file": "openapi.json"}},
        # MFI-14.3: the bundled libraries' built-in linter rulesets run on every compile.
        "linter": {"extends": ["@typespec/http/all"]},
    }


def test_find_tspconfig_looks_beside_the_root():
    assert find_tspconfig({"main.tsp": "", "tspconfig.yaml": ""}, "main.tsp") == "tspconfig.yaml"
    assert find_tspconfig({"api/main.tsp": "", "api/tspconfig.yml": ""}, "api/main.tsp") == "api/tspconfig.yml"
    assert find_tspconfig({"api/main.tsp": "", "tspconfig.yaml": ""}, "api/main.tsp") is None


# ===========================================================================
# Compiling with an uploaded config (recorded)
# ===========================================================================


def test_the_compile_uses_the_merged_config(monkeypatch, libraries):  # noqa: F811
    calls = _replay(monkeypatch, "petstore-tspconfig")
    compiled = compile_typespec_set(_petstore_with_config(), "main.tsp")
    assert yaml.safe_load(calls[0]["tspconfig"]) == yaml.safe_load(_recording("petstore-tspconfig")["tspconfig"])
    # The uploaded file itself is never staged; Apiome's merged config replaces it.
    assert "emit:\n- '@typespec/openapi3'\n" in calls[0]["tspconfig"]
    assert compiled.openapi == _emitted("petstore-tspconfig")
    assert compiled.openapi["openapi"] == "3.1.0"
    assert compiled.config is not None and compiled.config.path == "tspconfig.yaml"


def test_a_single_file_with_a_config_compiles_as_a_project(monkeypatch, libraries):  # noqa: F811
    calls = _replay(monkeypatch, "single-project")
    source = TypeSpecImportSource()
    api = source.normalize(source.parse_fileset(IntakeFileset.from_members(_single_project(), root="main.tsp")))
    assert len(calls) == 1
    assert api.format == "typespec"
    assert api.extras["typespec_openapi_format"] == "openapi-3.1"
    # omit-unreachable-types dropped the model no operation uses.
    assert {t.name for t in api.types} == {"Greeting"}
    assert api.extras["typespec_tspconfig"] == "tspconfig.yaml"
    assert api.extras["typespec_tspconfig_applied"] == {
        "options": {
            "@typespec/openapi3": {
                "openapi-versions": ["3.1.0"],
                "omit-unreachable-types": True,
                "safeint-strategy": "double-int",
            }
        }
    }
    assert api.extras["typespec_tspconfig_ignored"] == []


def test_a_project_without_a_config_records_none(monkeypatch, libraries):  # noqa: F811
    _replay(monkeypatch, "petstore")
    source = TypeSpecImportSource()
    members = _petstore_with_config()
    del members["tspconfig.yaml"]
    api = source.normalize(source.parse_fileset(IntakeFileset.from_members(members, root="main.tsp")))
    assert "typespec_tspconfig" not in api.extras


def test_a_malformed_config_refuses_the_import(monkeypatch, libraries):  # noqa: F811
    _replay(monkeypatch, "single-project")
    members = {**_single_project(), "tspconfig.yaml": "- not a mapping\n"}
    with pytest.raises(ImportSourceError) as exc:
        TypeSpecImportSource().parse_fileset(IntakeFileset.from_members(members, root="main.tsp"))
    assert exc.value.code == "INPUT_MALFORMED"


def test_the_config_never_becomes_the_archive_root():
    from app.archive_intake import rank_root_candidates

    ranked = rank_root_candidates(_petstore_with_config())
    assert ranked[0].path == "main.tsp"
    assert "tspconfig.yaml" not in [candidate.path for candidate in ranked]


# ===========================================================================
# Live compiler
# ===========================================================================


@pytest.mark.skipif(not _live_compiler_ready(), reason="tsp with @typespec/openapi3 is not installed")
def test_live_compiles_match_the_recordings():
    assert compile_typespec_set(_petstore_with_config(), "main.tsp").openapi == _emitted("petstore-tspconfig")
    assert compile_typespec_set(_single_project(), "main.tsp").openapi == _emitted("single-project")
