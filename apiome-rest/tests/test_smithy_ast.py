"""Tests for Smithy model assembly → JSON AST — MFI-17.1 (#3808).

The Smithy CLI is a JVM tool the CI runtime does not install, so the CLI tests replay a JSON AST
for the ``tests/fixtures/smithy_ast/weather/model`` set: ``main.smithy`` and ``types.smithy``
share the ``example.weather`` namespace across two files, ``common.smithy`` adds
``example.common``, and a ``smithy-build.json`` sits beside them. ``assembled-ast.json`` is
**hand-authored** from the Smithy 2.0 JSON AST specification
(https://smithy.io/2.0/spec/json-ast.html) to match that set — it is not a recording.
:func:`test_live_smithy_ast_matches_the_fixture` runs the real CLI when it is available
(``APIOME_SMITHY_BIN`` or ``smithy`` on ``PATH``) and checks that the fixture matches it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from app import smithy_ast
from app import smithy_import_source as smithy_import_source_module
from app.fileset import IntakeFileset
from app.import_source import DetectionInput, ImportSourceError
from app.smithy_ast import (
    SMITHY_TOOL_KEY,
    assemble_smithy_set,
    ast_sha256,
    is_smithy_ast_text,
    model_members,
    parse_smithy_ast_text,
)
from app.smithy_ast_mapper import document_from_ast, shape_namespace
from app.smithy_import_source import SmithyImportSource
from app.smithy_normalizer import SmithyNormalizer
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolRunResult, ToolTimeoutError

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "smithy_ast" / "weather"
_MODEL_DIR = _FIXTURES / "model"
_AST_TEXT = (_FIXTURES / "assembled-ast.json").read_text(encoding="utf-8")


def _members() -> Dict[str, str]:
    """The fixture set's members, path → text (``smithy-build.json`` included)."""
    return {
        str(path.relative_to(_MODEL_DIR)): path.read_text(encoding="utf-8")
        for path in sorted(_MODEL_DIR.rglob("*"))
        if path.is_file()
    }


def _replay(monkeypatch: pytest.MonkeyPatch, stdout: str = _AST_TEXT) -> List[Dict[str, Any]]:
    """Make ``run_tool_blocking`` answer with ``stdout``; return the calls it receives.

    Each call records the files that existed when the CLI ran, so staging can be asserted.
    """
    calls: List[Dict[str, Any]] = []

    def _fake(key: str, args: List[str], **kwargs: Any) -> ToolRunResult:
        if args[0] != "ast":
            # MFI-17.3's `smithy validate` (run when the CLI is installed) is not under test here.
            return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout="", stderr="", duration_ms=1)
        files = [Path(a) for a in args[2:]]
        calls.append(
            {
                "key": key,
                "args": list(args),
                "staged": {p.name: p.read_text(encoding="utf-8") for p in files},
                "cwd_listing": sorted(p.name for p in Path(kwargs["cwd"]).iterdir()),
                **kwargs,
            }
        )
        return ToolRunResult(key=key, argv=[key, *args], exit_code=0, stdout=stdout, stderr="", duration_ms=1)

    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _fake)
    return calls


def _raise(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    """Make ``run_tool_blocking`` raise ``error``."""

    def _fake(*_args: Any, **_kwargs: Any) -> ToolRunResult:
        raise error

    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _fake)


# ===========================================================================
# Staging and the CLI call
# ===========================================================================


def test_model_members_keeps_model_files_only():
    members = {
        "a.smithy": "namespace a",
        "ast.json": _AST_TEXT,
        "smithy-build.json": '{"version": "1.0"}',
        "nested/smithy-build.json": '{"version": "1.0"}',
        "other.json": '{"openapi": "3.1.0"}',
        "README.md": "# hi",
    }
    assert sorted(model_members(members)) == ["a.smithy", "ast.json"]


def test_the_cli_assembles_the_staged_model_files(monkeypatch):
    calls = _replay(monkeypatch)
    assemble_smithy_set(_members(), "main.smithy")
    (call,) = calls
    assert call["key"] == SMITHY_TOOL_KEY
    assert call["args"][:2] == ["ast", "--allow-unknown-traits"]
    # Every model file is staged and passed; smithy-build.json never is.
    assert sorted(call["staged"]) == ["common.smithy", "main.smithy", "types.smithy"]
    assert all(Path(a).is_absolute() for a in call["args"][2:])
    # The CLI runs from an empty directory, which is also HOME, apart from the models.
    assert call["cwd_listing"] == []
    assert call["extra_env"] == {"HOME": call["cwd"]}
    assert not any(a.startswith(call["cwd"]) for a in call["args"][2:])
    # Both directories are removed afterwards.
    assert not Path(call["cwd"]).exists()
    assert not Path(call["args"][2]).parent.exists()


def test_a_member_path_outside_the_set_is_refused(monkeypatch):
    _replay(monkeypatch)
    with pytest.raises(ImportSourceError) as exc:
        assemble_smithy_set({"main.smithy": "x", "../evil.smithy": "y"}, "main.smithy")
    assert exc.value.code == "INPUT_ARCHIVE_INVALID"


def test_a_set_without_model_files_or_root_is_refused():
    with pytest.raises(ImportSourceError) as exc:
        assemble_smithy_set({"README.md": "x"}, "README.md")
    assert exc.value.code == "INPUT_ARCHIVE_INVALID"
    with pytest.raises(ImportSourceError) as exc:
        assemble_smithy_set({"a.smithy": "x"}, "main.smithy")
    assert exc.value.code == "INPUT_ARCHIVE_INVALID"


@pytest.mark.parametrize(
    "error, code",
    [
        (ToolNotAvailableError(SMITHY_TOOL_KEY, "missing"), "ADAPTER_UNAVAILABLE"),
        (ToolTimeoutError(SMITHY_TOOL_KEY, 120.0), "INPUT_TIME_LIMIT"),
    ],
)
def test_runner_failures_map_to_intake_codes(monkeypatch, error: Exception, code: str):
    _raise(monkeypatch, error)
    with pytest.raises(ImportSourceError) as exc:
        assemble_smithy_set(_members(), "main.smithy")
    assert exc.value.code == code


def test_a_model_that_does_not_validate_quotes_the_cli_errors_without_the_staging_path(monkeypatch):
    staged: Dict[str, str] = {}

    def _fake(key: str, args: List[str], **_kwargs: Any) -> ToolRunResult:
        main = next(a for a in args if a.endswith("main.smithy"))
        staged["dir"] = str(Path(main).parent)
        stderr = (
            "Building the model...\n"
            f"ERROR: example.weather#GetCity (Target) @ {main}:23:5\n"
            "  Operation input targets an unresolved shape `example.weather#Missing`\n"
        )
        raise ToolExecutionError(key, 1, "", stderr)

    monkeypatch.setattr(smithy_ast, "run_tool_blocking", _fake)
    with pytest.raises(ImportSourceError) as exc:
        assemble_smithy_set(_members(), "main.smithy")
    assert exc.value.code == "INPUT_SEMANTIC_INVALID"
    assert "ERROR: example.weather#GetCity (Target) @ main.smithy:23:5" in str(exc.value)
    assert staged["dir"] not in str(exc.value)


def test_output_that_is_not_an_ast_is_malformed(monkeypatch):
    _replay(monkeypatch, stdout="not json")
    with pytest.raises(ImportSourceError) as exc:
        assemble_smithy_set(_members(), "main.smithy")
    assert exc.value.code == "INPUT_MALFORMED"


# ===========================================================================
# The assembled model
# ===========================================================================


def test_identity_is_captured(monkeypatch):
    _replay(monkeypatch)
    doc = assemble_smithy_set(_members(), "main.smithy")
    assert doc.version == "2.0"
    assert doc.namespace == "example.weather"
    assert doc.namespaces == ("example.common", "example.weather")
    assert doc.source_files == ("common.smithy", "main.smithy", "types.smithy")
    assert doc.model_sha256 == ast_sha256(json.loads(_AST_TEXT))
    assert doc.raw == _members()["main.smithy"]


def test_shapes_from_every_file_are_assembled(monkeypatch):
    _replay(monkeypatch)
    doc = assemble_smithy_set(_members(), "main.smithy")
    structures = {s.name: s for s in doc.structures}
    # types.smithy (same namespace) and common.smithy (another namespace) both contribute.
    assert "NoSuchResource" in structures
    assert "example.common#Money" in structures
    assert [(f.name, f.type_name, f.required) for f in structures["example.common#Money"].fields] == [
        ("amount", "BigDecimal", True),
        ("currency", "String", True),
    ]
    # A simple shape resolves to its base type; a cross-namespace target keeps its absolute id.
    forecast = structures["GetForecastOutput"]
    assert {f.name: f.type_name for f in forecast.fields} == {
        "chanceOfRain": "Float",
        "conditions": "ConditionList",
        "priceOfUmbrella": "example.common#Money",
    }
    assert [(f.name, f.type_name, f.required) for f in structures["City"].fields] == [("cityId", "String", True)]
    assert structures["City"].kind == "resource"
    assert [(e.name, e.values) for e in doc.enums] == [("Condition", ("SUNNY", "CLOUDY", "RAIN"))]
    assert [(m.name, m.key, m.value) for m in doc.maps] == [("example.common#Region", "String", "String")]
    assert [(lst.name, lst.member) for lst in doc.lists] == [("ConditionList", "Condition")]


def test_services_bind_their_resources_operations(monkeypatch):
    _replay(monkeypatch)
    doc = assemble_smithy_set(_members(), "main.smithy")
    (service,) = doc.services
    assert (service.name, service.version, service.documentation) == (
        "Weather",
        "2006-03-01",
        "Provides weather forecasts.",
    )
    # The service's own operations, then each resource's (its `operations`, then lifecycle ones).
    assert service.operations == ("GetCurrentTime", "GetForecast", "GetCity")
    ops = {o.name: o for o in doc.operations}
    assert (ops["GetCurrentTime"].input_type, ops["GetCurrentTime"].output_type) == (None, "GetCurrentTimeOutput")
    assert ops["GetCity"].input_type == "GetCityInput"


def test_the_hash_ignores_key_order_but_not_content():
    ast = json.loads(_AST_TEXT)
    reordered = {"shapes": dict(reversed(list(ast["shapes"].items()))), "smithy": ast["smithy"]}
    assert ast_sha256(reordered) == ast_sha256(ast)
    changed = json.loads(_AST_TEXT)
    changed["shapes"]["example.weather#Weather"]["version"] = "2026-01-01"
    assert ast_sha256(changed) != ast_sha256(ast)


def test_the_canonical_model_carries_the_identity(monkeypatch):
    _replay(monkeypatch)
    api = SmithyNormalizer().normalize(assemble_smithy_set(_members(), "main.smithy"), include_raw=False)
    assert api.identity.namespace == "example.weather"
    assert api.extras["smithy_version"] == "2.0"
    assert api.extras["smithy_namespaces"] == ["example.common", "example.weather"]
    assert api.extras["smithy_ast_sha256"] == ast_sha256(json.loads(_AST_TEXT))
    assert api.extras["smithy_source_files"] == ["common.smithy", "main.smithy", "types.smithy"]
    keys = {t.key for t in api.types}
    # A shape of another namespace is keyed under its own namespace, not the primary one.
    assert {"example.common.Money", "example.weather.GetForecastOutput"} <= keys
    forecast = next(t for t in api.types if t.key == "example.weather.GetForecastOutput")
    assert next(f for f in forecast.fields if f.name == "priceOfUmbrella").type.name == "example.common.Money"
    ops = {o.name for s in api.services for o in s.operations}
    assert ops == {"GetCurrentTime", "GetCity", "GetForecast"}


# ===========================================================================
# JSON AST input (no CLI)
# ===========================================================================


def test_is_smithy_ast_text():
    assert is_smithy_ast_text(_AST_TEXT)
    assert not is_smithy_ast_text('{"openapi": "3.1.0"}')
    assert not is_smithy_ast_text('{"smithy": 2}')
    assert not is_smithy_ast_text("{not json")
    assert not is_smithy_ast_text('$version: "2"\nnamespace a')


def test_a_json_ast_is_read_directly():
    doc = parse_smithy_ast_text(_AST_TEXT, source_label="model.json")
    assert doc.namespaces == ("example.common", "example.weather")
    assert doc.model_sha256 == ast_sha256(json.loads(_AST_TEXT))
    assert doc.source_files == ()


def test_a_json_ast_with_an_undefined_target_is_refused():
    ast = {"smithy": "2.0", "shapes": {"a#S": {"type": "structure", "members": {"x": {"target": "b#Missing"}}}}}
    with pytest.raises(ImportSourceError, match="b#Missing") as exc:
        document_from_ast(ast, raw="")
    assert exc.value.code == "INPUT_REFERENCE_UNRESOLVED"


@pytest.mark.parametrize(
    "ast, code",
    [
        ({"shapes": {}}, "INPUT_MALFORMED"),
        ({"smithy": "2.0", "shapes": {}}, "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_a_json_ast_without_shapes_is_refused(ast: Dict[str, Any], code: str):
    with pytest.raises(ImportSourceError) as exc:
        document_from_ast(ast, raw="")
    assert exc.value.code == code
    with pytest.raises(ImportSourceError):
        parse_smithy_ast_text("{broken", source_label="x.json")


def test_the_primary_namespace_without_a_service_is_the_most_used_one():
    ast = {
        "smithy": "2.0",
        "shapes": {
            "b#One": {"type": "structure", "members": {}},
            "a#Two": {"type": "structure", "members": {}},
            "a#Three": {"type": "structure", "members": {}},
        },
    }
    doc = document_from_ast(ast, raw="")
    assert doc.namespace == "a"
    assert sorted(s.name for s in doc.structures) == ["Three", "Two", "b#One"]


def test_shape_namespace():
    assert shape_namespace("a.b#C$member") == "a.b"


# ===========================================================================
# Import source
# ===========================================================================


def test_detects_a_json_ast():
    result = SmithyImportSource().detect(DetectionInput(text=_AST_TEXT, filename="model.json"))
    assert (result.format, result.confidence) == ("smithy", 0.97)


def test_a_single_idl_file_keeps_the_built_in_reader(monkeypatch):
    calls = _replay(monkeypatch)
    doc = SmithyImportSource().parse(_members()["main.smithy"], source_label="main.smithy")
    assert calls == []
    assert doc.model_sha256 is None
    assert doc.namespace == "example.weather"


def test_a_fileset_with_one_model_file_is_read_without_the_cli(monkeypatch):
    calls = _replay(monkeypatch)
    members = {"main.smithy": _members()["main.smithy"], "smithy-build.json": "{}"}
    SmithyImportSource().parse_fileset(IntakeFileset.from_members(members, root="main.smithy"))
    assert calls == []


def test_a_multi_file_fileset_is_assembled_through_the_cli(monkeypatch):
    calls = _replay(monkeypatch)
    doc = SmithyImportSource().parse_fileset(IntakeFileset.from_members(_members(), root="main.smithy"))
    assert len(calls) == 1
    assert doc.namespaces == ("example.common", "example.weather")


def test_without_the_cli_a_multi_file_fileset_is_refused(monkeypatch):
    _raise(monkeypatch, ToolNotAvailableError(SMITHY_TOOL_KEY, "missing"))
    with pytest.raises(ImportSourceError) as exc:
        SmithyImportSource().parse_fileset(IntakeFileset.from_members(_members(), root="main.smithy"))
    assert exc.value.code == "ADAPTER_UNAVAILABLE"


def test_the_import_source_module_uses_the_seam():
    assert smithy_import_source_module.assemble_smithy_set is assemble_smithy_set


# ===========================================================================
# Live CLI (only when the tool is installed)
# ===========================================================================


@pytest.mark.skipif(not smithy_ast.smithy_cli_available(), reason="Smithy CLI (smithy) is not installed")
def test_live_smithy_ast_matches_the_fixture():
    live = assemble_smithy_set(_members(), "main.smithy")
    fixture = parse_smithy_ast_text(_AST_TEXT)
    assert sorted(live.structures, key=lambda s: s.name) == sorted(fixture.structures, key=lambda s: s.name)
    assert live.operations == fixture.operations
    assert live.services == fixture.services
    assert (live.version, live.namespaces) == (fixture.version, fixture.namespaces)
