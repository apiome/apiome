"""CUE, Pkl and Dhall import — FMT-8.5 (#5466).

Two kinds of test live here:

* **pure** tests of everything the readers do in Python — detection, intake guards, the
  truncation heuristic, Dhall import refusal, the CUE module layout and source scan, the Pkl
  annotation parser and constraint mapping, the Dhall normal-form projection, and the shared
  normalizer — which run everywhere;
* **tool** tests that evaluate real uploads with the bundled ``cue`` / ``pkl`` / ``dhall`` in the
  sandbox, which skip when the tool is not installed (``scripts/install_dev_toolchain.sh``).

The corpus suites (``test_corpus_import``, ``test_corpus_negative``, ``test_corpus_golden``) cover
every fixture under ``apiome-ui/examples/{cue,pkl,dhall}`` on top of this.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict

import pytest

from app import typed_config_common as common
from app.canonical_model import CanonicalApi, TypeKind
from app.cue_parser import (
    LIMIT_DETAILS as CUE_LIMITS,
)
from app.cue_parser import (
    PARTIAL_LIMITS as CUE_PARTIAL,
)
from app.cue_parser import (
    _drop_artifact_refs,
    is_cue_source,
    layout_module,
    scan_limits,
    simplify_schema,
    strip_conditionals,
)
from app.dhall_parser import LIMIT_DETAILS as DHALL_LIMITS
from app.dhall_parser import PARTIAL_LIMITS as DHALL_PARTIAL
from app.dhall_parser import _value, is_dhall_source, project, refused_imports
from app.fileset import IntakeFileset
from app.format_capability_registry import capability_for
from app.import_source import DetectionInput, ImportSourceError, get_import_source, load_builtin_import_sources
from app.pkl_parser import LIMIT_DETAILS as PKL_LIMITS
from app.pkl_parser import PARTIAL_LIMITS as PKL_PARTIAL
from app.pkl_parser import _apply_constraint, _member_annotation, _refers_to, is_pkl_source, parse_type
from app.toolchain_packaging import bundled_tool, probe_tool
from app.toolchain_runner import ToolExecutionError, ToolNotAvailableError, ToolTimeoutError
from app.toolchain_sandbox import NETWORK_STRICT
from app.toolchain_selfcheck import REQUIRED_TOOL_KEYS, _parse_version
from app.typed_config_common import (
    ToolFailure,
    TypedConfigDocument,
    TypedConfigParseError,
    guard_input,
    pascal_case,
    syntax_error_code,
)
from app.typed_config_import_source import CUE_CAPABILITIES, DHALL_CAPABILITIES, PKL_CAPABILITIES
from app.typed_config_normalizer import CueNormalizer, dialect_for
from app.zod_normalizer import ZOD_DIALECT, translate_schema

load_builtin_import_sources()

EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"


def _tool(key: str) -> pytest.MarkDecorator:
    return pytest.mark.skipif(
        not getattr(probe_tool(key), "available", False),
        reason=f"`{key}` is not installed here (scripts/install_dev_toolchain.sh)",
    )


needs_cue, needs_pkl, needs_dhall = _tool("cue"), _tool("pkl"), _tool("dhall")


def types_of(api: CanonicalApi):
    return {t.key: t for t in api.types}


def field(type_, name):
    return next(f for f in type_.fields if f.name == name)


def limits_of(api: CanonicalApi) -> Dict[str, list]:
    return {
        limit["construct"]: limit["locations"]
        for limit in api.extras[api.format]["capability_limits"]
    }


def read(language: str, text: str, label: str) -> CanonicalApi:
    adapter = get_import_source(language)
    return adapter.normalize(adapter.parse(text, source_label=label))


def rejection(language: str, text: str, label: str) -> ImportSourceError:
    adapter = get_import_source(language)
    with pytest.raises(ImportSourceError) as caught:
        adapter.parse(text, source_label=label)
    return caught.value


# ===========================================================================
# Adapter surface and the packaging rule
# ===========================================================================


@pytest.mark.parametrize(
    ("key", "tool", "suffix", "capabilities", "details", "partial"),
    [
        ("cue", "cue", ".cue", CUE_CAPABILITIES, CUE_LIMITS, CUE_PARTIAL),
        ("pkl", "pkl", ".pkl", PKL_CAPABILITIES, PKL_LIMITS, PKL_PARTIAL),
        ("dhall", "dhall", ".dhall", DHALL_CAPABILITIES, DHALL_LIMITS, DHALL_PARTIAL),
    ],
)
def test_adapter_surface_matches_the_registry(key, tool, suffix, capabilities, details, partial):
    adapter = get_import_source(key)
    assert adapter.required_tools == (tool,)
    assert suffix in adapter.declared_file_extensions()
    assert adapter.paradigm.value == "data_schema"
    assert set(capabilities.unsupported) == set(details)
    assert set(capability_for(key).canonical_projection.dropped_constructs) == set(details)
    assert partial <= set(details)
    assert all(construct.startswith(f"{key}.") for construct in details)


def test_the_three_tools_are_required_and_pinned():
    # FMT-1.3: a shipped format's tool is a hard dependency, never a runtime `available: false`.
    for key, version in (("cue", "0.17.1"), ("pkl", "0.32.2"), ("dhall", "1.42.2")):
        assert key in REQUIRED_TOOL_KEYS
        assert bundled_tool(key).version == version


def test_dockerfile_installs_the_pinned_tools():
    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG CUE_VERSION=0.17.1" in dockerfile
    assert "ARG PKL_VERSION=0.32.2" in dockerfile
    assert "ARG DHALL_VERSION=1.42.2" in dockerfile


@pytest.mark.parametrize(
    ("banner", "expected"),
    [
        ("cue version v0.17.1", "0.17.1"),
        ("Pkl 0.32.2 (Linux 7.0.0-1017-azure, native)", "0.32.2"),
        ("1.42.2", "1.42.2"),
    ],
)
def test_version_banners_of_the_new_tools_are_read(banner, expected):
    assert _parse_version(banner) == expected


# ===========================================================================
# Detection
# ===========================================================================


def test_cue_detection_needs_a_package_clause_and_a_definition():
    assert is_cue_source('package orders\n\n#Order: {\n\tid: string\n}\n')
    # A `#Name:` line alone is a YAML / shell comment, not CUE.
    assert not is_cue_source("#Note: this is a comment\nkey: value\n")


def test_pkl_detection_declines_cue():
    assert is_pkl_source("module example.orders\n\nclass Order {\n  id: String\n}\n")
    assert is_pkl_source("typealias Sku = String\n")
    assert not is_pkl_source("package orders\n#Order: {\n}\n")
    assert is_pkl_source("open class Base {\n}\nclass Child extends Base {\n}\n")
    # Python and DTD text with the word `class` are not Pkl.
    assert not is_pkl_source("from pydantic import BaseModel\n\nclass Order(BaseModel):\n    id: str\n")
    assert not is_pkl_source('<!ATTLIST item\n    class NMTOKENS #IMPLIED>\n')


def test_dhall_detection_declines_other_languages():
    assert is_dhall_source("let Order = { id : Text } in { Order }\n")
    assert is_dhall_source("{ Type = { id : Text }, default = {=} }\n")
    assert not is_dhall_source('{ OrderLine = { sku | String | doc "x" } }\n')
    assert not is_dhall_source("module example.orders\nclass Order {}\n")
    # YAML prose that happens to read "summary: List widgets" is not a typed Dhall field.
    assert not is_dhall_source("paths:\n  /w:\n    get:\n      summary: List widgets\n      tags: [w\n")


@pytest.mark.parametrize(
    ("key", "text", "filename"),
    [
        ("cue", "package beacon\n\n#Beacon: {\n\tid: string\n}\n", "beacon.cue"),
        ("pkl", "module example.beacon\n\nid: String\n", "beacon.pkl"),
        ("dhall", "let Beacon = { id : Text } in { Beacon }\n", "beacon.dhall"),
    ],
)
def test_detection_is_more_confident_with_the_language_suffix(key, text, filename):
    adapter = get_import_source(key)
    assert adapter.detect(DetectionInput(text=text, filename=filename)).confidence == 0.95
    assert adapter.detect(DetectionInput(text=text, filename="paste.txt")).confidence == 0.85
    assert adapter.detect(DetectionInput(text="openapi: 3.1.0\n")).confidence == 0.0


# ===========================================================================
# Intake guards and error reading
# ===========================================================================


@pytest.mark.parametrize(
    ("files", "code"),
    [
        ({"a.cue": "   \n"}, "INPUT_EMPTY"),
        ({"a.cue": "x" * (common.MAX_TYPED_CONFIG_BYTES + 1)}, "INPUT_TOO_LARGE"),
        ({"a.cue": "\ufeffpackage a"}, "INPUT_ENCODING_INVALID"),
        ({"a.cue": "package a\x00"}, "INPUT_ENCODING_INVALID"),
        ({"../escape.cue": "package a"}, "INPUT_SEMANTIC_INVALID"),
        ({"/etc/a.cue": "package a"}, "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_guard_input_rejects_before_any_tool_runs(files, code):
    with pytest.raises(TypedConfigParseError) as caught:
        guard_input(files, label="CUE", where="")
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("#Thing: {\n\tid: string\n", "INPUT_MALFORMED"),  # complete last line, missing brace
        ("#Thing: {\n\tq: int & <=\n", "INPUT_TRUNCATED"),  # ends on an operator
        ("class A {\n  q: Int(isBetween(1, 99\n", "INPUT_TRUNCATED"),  # open parenthesis
        ("let A = < EUR | GBP\n", "INPUT_TRUNCATED"),  # open Dhall union
        ('x: String = "never closed\n', "INPUT_TRUNCATED"),  # open string literal
        ("let A = 1\n\n{ A }\n", "INPUT_MALFORMED"),
        ("#Thing: {", "INPUT_TRUNCATED"),  # no final newline
        ("x: Int(length <= 5)\n", "INPUT_MALFORMED"),  # a comparison is not an open angle
        (None, "INPUT_MALFORMED"),
    ],
)
def test_syntax_error_code_tells_truncation_from_malformation(text, code):
    assert syntax_error_code(text) == code


@pytest.mark.parametrize(
    ("text", "name"),
    [("example.beacon", "Beacon"), ("01-minimal-schema", "MinimalSchema"), ("123", "Schema123"), ("", "Schema")],
)
def test_pascal_case_names_a_module_or_file(text, name):
    assert pascal_case(text) == name


def test_tool_runs_use_the_strict_untrusted_code_sandbox(monkeypatch, tmp_path):
    seen = {}

    def fake_run(key, args, **kwargs):
        seen.update(kwargs, key=key, args=args)
        return "ok"

    monkeypatch.setattr(common, "run_tool_blocking", fake_run)
    assert common.run_typed_config_tool("cue", ["export"], cwd=tmp_path, label="CUE", where="") == "ok"
    assert seen["policy"].no_network and seen["policy"].network_enforcement == NETWORK_STRICT
    assert seen["cwd"] == str(tmp_path)
    assert seen["extra_env"]["HOME"] == str(tmp_path)
    assert seen["timeout"] == common.TOOL_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (ToolNotAvailableError("cue", "cue"), "ADAPTER_UNAVAILABLE"),
        (ToolTimeoutError("cue", 20.0), "INPUT_TIME_LIMIT"),
    ],
)
def test_runner_failures_map_to_taxonomy_codes(monkeypatch, tmp_path, error, code):
    def fake_run(*args, **kwargs):
        raise error

    monkeypatch.setattr(common, "run_tool_blocking", fake_run)
    with pytest.raises(TypedConfigParseError) as caught:
        common.run_typed_config_tool("cue", [], cwd=tmp_path, label="CUE", where="")
    assert caught.value.code == code


def test_a_non_zero_exit_is_returned_scrubbed_of_the_workspace_path(monkeypatch, tmp_path):
    workspace = tmp_path / "apiome-typed-config-abc"
    workspace.mkdir()

    def fake_run(*args, **kwargs):
        raise ToolExecutionError("pkl", 1, "", f"\x1b[31mError\x1b[0m at file://{workspace}/a.pkl, line 3")

    monkeypatch.setattr(common, "run_tool_blocking", fake_run)
    failure = common.run_typed_config_tool("pkl", [], cwd=workspace, label="Pkl", where="")
    assert isinstance(failure, ToolFailure)
    assert failure.output == "Error at a.pkl, line 3"


# ===========================================================================
# Dhall import refusal
# ===========================================================================


@pytest.mark.parametrize(
    "source",
    [
        "let T = https://prelude.dhall-lang.org/package.dhall in T",
        "let home = env:HOME as Text in home",
        "let secret = /etc/passwd as Text in secret",
        "let p = ~/.config/x.dhall in p",
        "let up = ../../outside.dhall in up",
    ],
)
def test_dhall_imports_outside_the_upload_are_refused(source):
    assert refused_imports(source, path="package.dhall")


@pytest.mark.parametrize(
    "source",
    [
        "let shared = ./shared.dhall in shared",
        "let A = { a : Text } //\\\\ { b : Text } in A",
        "let r = { a = 1 } /\\ { b = 2 } in r",
        '-- https://example.com in a comment\nlet url = "https://example.com" in url',
        "{- /etc/passwd -} let x = 1 in x",
    ],
)
def test_dhall_relative_imports_operators_comments_and_text_are_not_refused(source):
    assert refused_imports(source, path="package.dhall") == []


def test_a_parent_import_inside_the_upload_is_allowed():
    assert refused_imports("let s = ../shared.dhall in s", path="types/order.dhall") == []


# ===========================================================================
# CUE: module layout, the source scan and the JSON Schema clean-up
# ===========================================================================


def test_a_flat_cue_module_is_laid_out_as_cue_expects():
    files = {
        "cue.mod": 'module: "example.com/shipping"\n',
        "schema.cue": 'package shipping\nimport "example.com/shipping/shared"\n',
        "shared.cue": "package shared\n#Money: {value: int}\n",
    }
    laid, root = layout_module(files, "schema.cue")
    assert root == "schema.cue"
    assert set(laid) == {"cue.mod/module.cue", "schema.cue", "shared/shared.cue"}


def test_a_real_cue_module_layout_is_kept():
    files = {"cue.mod/module.cue": 'module: "x.com/a"\n', "schema.cue": "package a\n"}
    assert layout_module(files, "schema.cue") == (files, "schema.cue")


def test_scan_limits_finds_each_construct_and_the_computed_fields():
    source = (
        "package s\n"
        "#S: {\n"
        "\tinputs: [...string]\n"
        "\tupper: [for s in inputs {s}]\n"
        '\ttarget: "\\(host):1"\n'
        '\tmode: "a" | *"b"\n'
        "\t_secret: string\n"
        "\tlet n = 2\n"
        "\tblob: bytes\n"
        "\tprefixed: strings.HasPrefix(\"x\")\n"
        "\tsized: strings.MinRunes(2)\n"
        '\tif mode == "a" {\n\t\textra: int\n\t}\n'
        "}\n"
    )
    limits, dropped, conditional = scan_limits(source)
    constructs = {construct for construct, _ in limits}
    assert constructs == {
        "cue.comprehension",
        "cue.interpolation",
        "cue.default",
        "cue.hidden_field",
        "cue.let_binding",
        "cue.bytes",
        "cue.builtin_validator",
        "cue.conditional_field",
    }
    assert dropped == {"S": {"upper", "target"}}
    assert conditional == {"S"}
    assert ("cue.builtin_validator", "S.prefixed") in limits
    assert not any(location == "S.sized" for _, location in limits)  # MinRunes is expressible


def test_strip_conditionals_keeps_line_numbers_and_unconditional_fields():
    source = '#S: {\n\ttier: "a" | "b"\n\tif tier == "a" {\n\t\tseats: 1\n\t}\n\tname: string\n}\n'
    stripped = strip_conditionals(source)
    assert stripped.count("\n") == source.count("\n")
    assert "seats" not in stripped and "tier:" in stripped and "name: string" in stripped


def test_simplify_merges_scalar_all_of_and_non_empty_lists():
    defs: Dict[str, object] = {}
    assert simplify_schema({"allOf": [{"type": "number"}, {"type": "integer", "minimum": 0}]}, defs) == {
        "type": "integer",
        "minimum": 0,
    }
    merged = simplify_schema(
        {"allOf": [{"prefixItems": [True]}, {"type": "array", "items": {"type": "string"}, "minItems": 1}]}, defs
    )
    assert merged == {"type": "array", "items": {"type": "string"}, "minItems": 1}


def test_simplify_folds_a_default_branch_and_splits_an_embedding():
    defs = {"Status": {"enum": ["new", "paid"]}}
    assert simplify_schema({"anyOf": [{"$ref": "#/$defs/Status"}, {"const": "new"}]}, defs) == {
        "$ref": "#/$defs/Status"
    }
    embedded = simplify_schema({"$ref": "#/$defs/Base", "type": "object", "properties": {"x": True}}, defs)
    assert embedded == {"allOf": [{"$ref": "#/$defs/Base"}, {"type": "object", "properties": {"x": {}}}]}
    assert simplify_schema({"$ref": "#/$defs/Base", "type": "object", "properties": {}}, defs) == {
        "$ref": "#/$defs/Base"
    }


def test_label_reference_pseudo_definitions_are_dropped():
    schema = {
        "type": "object",
        "additionalProperties": {
            "$ref": "#/$defs/Service",
            "type": "object",
            "properties": {"name": {"$ref": "#/$defs/services"}},
            "required": ["name"],
        },
    }
    cleaned = simplify_schema(_drop_artifact_refs(schema, {"services"}), {})
    assert cleaned["additionalProperties"] == {"$ref": "#/$defs/Service"}


# ===========================================================================
# Pkl: annotations and constraints
# ===========================================================================


def test_parse_type_reads_nested_constraints_nullability_and_unions():
    node = parse_type('Listing<String(startsWith("/"))>(!isEmpty)')
    assert node.kind == "declared" and node.name == "Listing" and node.constraints == ["!isEmpty"]
    assert node.arguments[0].constraints == ['startsWith("/")']
    nullable = parse_type("String(length <= 500)?")
    assert nullable.kind == "nullable" and nullable.arguments[0].constraints == ["length <= 500"]
    union = parse_type('"a" | *"b" | shared.Money')
    assert [m.kind for m in union.arguments] == ["string-literal", "string-literal", "declared"]
    assert union.arguments[2].name == "Money"
    assert parse_type("Int(") is None


@pytest.mark.parametrize(
    ("expression", "base", "keywords"),
    [
        ("isBetween(1, 9999)", "number", {"minimum": 1, "maximum": 9999}),
        ("isPositive", "number", {"exclusiveMinimum": 0}),
        ("this >= 10", "number", {"minimum": 10}),
        ("length.isBetween(3, 20)", "string", {"minLength": 3, "maxLength": 20}),
        ("length < 5", "string", {"maxLength": 4}),
        ("length == 2", "string", {"minLength": 2, "maxLength": 2}),
        ("!isEmpty", "string", {"minLength": 1}),
        ("!isEmpty", "array", {"minItems": 1}),
        ("isDistinct", "array", {"uniqueItems": True}),
        ('matches(Regex("^[A-Z]{3}$"))', "string", {"pattern": "^[A-Z]{3}$"}),
        ('matches(Regex(#"^\\d+$"#))', "string", {"pattern": "^\\d+$"}),
        ('startsWith("/")', "string", {"pattern": "^/"}),
        ('endsWith(".io")', "string", {"pattern": "\\.io$"}),
    ],
)
def test_recognized_constraints_become_json_schema_keywords(expression, base, keywords):
    found: Dict[str, object] = {}
    assert _apply_constraint(expression, base, found) is None
    assert found == keywords


@pytest.mark.parametrize(
    ("expression", "construct"),
    [
        ("this > minimum", "pkl.late_binding"),
        ("isOdd", "pkl.type_constraint"),
        ('contains("x")', "pkl.type_constraint"),
    ],
)
def test_other_constraints_are_declared(expression, construct):
    assert _apply_constraint(expression, "number", {}) == construct


def test_member_annotation_splits_type_and_default():
    lines = [
        "  status: OrderStatus = \"new\"",
        '  kind = "circle"',
        "  maximum: Int(this > minimum) = 10",
        'typealias Sku = String(matches(Regex("^A$")))',
        "  readiness: Probe = new { path = \"/readyz\" }",
    ]
    assert _member_annotation(lines, 1, "status") == ("OrderStatus", '"new"')
    assert _member_annotation(lines, 2, "kind") == (None, '"circle"')
    assert _member_annotation(lines, 3, "maximum") == ("Int(this > minimum)", "10")
    assert _member_annotation(lines, 4, "Sku") == ('String(matches(Regex("^A$")))', None)
    assert _member_annotation(lines, 5, "readiness") == ("Probe", 'new { path = "/readyz" }')


def test_a_default_that_reads_another_member_is_computed():
    assert _refers_to("inputs.length", {"inputs", "total"})
    assert _refers_to("this.x + 1", set())
    assert not _refers_to('"inputs"', {"inputs"})
    assert not _refers_to("2 * 21", {"inputs"})


# ===========================================================================
# Dhall: the normal-form projection
# ===========================================================================


def test_dhall_projection_names_types_structurally_and_lists_instances():
    currency = [11, {"EUR": None, "USD": None}]
    money = [7, {"currency": currency, "value": "Natural"}]
    normal_form = [
        8,
        {
            "Currency": currency,
            "Money": money,
            "Order": [
                7,
                {
                    "lines": [0, "List", [7, {"sku": "Text"}]],
                    "note": [0, "Optional", "Text"],
                    "tags": [0, "List", [7, {"mapKey": "Text", "mapValue": "Natural"}]],
                    "total": money,
                },
            ],
            "Page": [1, "a", "Type", [7, {"items": [0, "List", ["a", 0]]}]],
            "Payment": [11, {"Card": [7, {"token": "Text"}], "Cash": None}],
            "defaultTotal": [8, {"currency": [9, currency, "EUR"], "value": [15, 0]}],
        },
    ]
    source = "let Currency = 1 let Money = 1 let Order = 1 let Page = 1 let Payment = 1 in {}"
    definitions, exports, instances, limits = project(normal_form, root_name="Root", source=source)
    assert exports == ["Currency", "Money", "Order", "Payment"]
    assert instances == ["defaultTotal"]
    assert ("dhall.function", "Page") in limits
    order = definitions["Order"]
    assert order["properties"]["total"] == {"$ref": "#/$defs/Money"}
    assert order["properties"]["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert order["properties"]["tags"] == {
        "type": "object",
        "additionalProperties": {"type": "integer", "minimum": 0},
    }
    assert set(order["required"]) == {"lines", "tags", "total"}
    assert definitions["Money"]["properties"]["currency"] == {"$ref": "#/$defs/Currency"}
    assert definitions["Payment"] == {"anyOf": [{"$ref": "#/$defs/PaymentCard"}, {"const": "Cash"}]}
    assert definitions["PaymentCard"]["properties"] == {"token": {"type": "string"}}


def test_dhall_schema_record_defaults_are_field_defaults():
    normal_form = [
        8,
        {"Type": [7, {"id": "Text", "retries": "Natural"}], "default": [8, {"retries": [15, 3]}]},
    ]
    definitions, exports, _, _ = project(normal_form, root_name="Beacon", source="")
    assert exports == ["Beacon"]
    assert definitions["Beacon"]["properties"]["retries"] == {"type": "integer", "minimum": 0, "default": 3}
    assert definitions["Beacon"]["required"] == ["id"]


@pytest.mark.parametrize(
    ("node", "value"),
    [
        ([15, 3], 3),
        ([16, -2], -2),
        (1.5, 1.5),
        (True, True),
        ([18, "hi"], "hi"),
        ([0, "None", "Text"], None),
        ([5, None, [18, "x"]], "x"),
        ([4, "Text"], []),
        ([4, None, [15, 1], [15, 2]], [1, 2]),
        ([9, [11, {"EUR": None}], "EUR"], "EUR"),
    ],
)
def test_dhall_values_decode_as_dhall_to_json_renders_them(node, value):
    assert _value(node) == (True, value)


def test_a_dhall_function_value_does_not_decode():
    assert _value([1, "x", "Natural", ["x", 0]]) == (False, None)


# ===========================================================================
# The shared normalizer
# ===========================================================================


def test_normalizer_models_an_extension_as_a_record_with_its_base_fields():
    document = TypedConfigDocument(
        language="cue",
        root="a.cue",
        files=("a.cue",),
        tool_version="",
        schema={
            "$defs": {
                "Base": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
                "Child": {
                    "allOf": [
                        {"$ref": "#/$defs/Base"},
                        {"type": "object", "properties": {"n": {"type": "integer", "minimum": 1}}},
                    ]
                },
            }
        },
        exports=("Base", "Child"),
        limits=(("cue.default", "Child.n"),),
        instances=("config",),
        identity="Child",
    )
    api = CueNormalizer().normalize(document)
    types = types_of(api)
    assert {f.name for f in types["Child"].fields} == {"id", "n"}
    assert types["Child"].kind is TypeKind.RECORD
    assert field(types["Child"], "n").constraints.minimum == 1
    assert api.identity.name == "Child"
    assert api.extras["cue"]["instances"] == ["config"]
    assert limits_of(api) == {"cue.default": ["Child.n"]}


def test_normalizer_refuses_another_languages_document():
    document = TypedConfigDocument(
        language="pkl", root="a.pkl", files=("a.pkl",), tool_version="", schema={}, exports=()
    )
    with pytest.raises(ValueError):
        CueNormalizer().normalize(document)


def test_the_zod_dialect_is_unchanged_and_typed_config_records_no_unknown_keys():
    closed = {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}}, "additionalProperties": False}
    zod = translate_schema(closed)
    assert zod["extras"] == {"zod_unknown_keys": "strict"}
    assert zod["properties"][0]["type"]["target"] == "zod#A"
    assert translate_schema(closed, ZOD_DIALECT) == zod
    pkl = translate_schema(closed, dialect_for("pkl"))
    assert "extras" not in pkl
    assert pkl["properties"][0]["type"]["target"] == "pkl#A"


# ===========================================================================
# Real evaluations (skipped when the bundled tool is missing)
# ===========================================================================


@needs_cue
def test_cue_definitions_import_with_their_constraints():
    api = read("cue", (EXAMPLES / "cue/02-typical-order-schema.cue").read_text(), "orders.cue")
    types = types_of(api)
    order = types["Order"]
    assert field(order, "orderId").constraints.pattern == "^ORD-[0-9]{8}$"
    assert field(order, "customerId").constraints.min_length == 3
    assert field(order, "lines").constraints.min_items == 1
    assert field(order, "note").type.nullable
    assert types["OrderStatus"].kind is TypeKind.ENUM
    assert field(types["OrderLine"], "quantity").constraints.maximum == 9999
    assert "cue.default" in limits_of(api)


@needs_cue
def test_cue_lattice_constructs_are_declared_not_approximated():
    api = read("cue", (EXAMPLES / "cue/04-stress-lattice.cue").read_text(), "stress.cue")
    types = types_of(api)
    limits = limits_of(api)
    assert "Computed.upper" in limits["cue.comprehension"]
    assert "Interpolated.target" in limits["cue.interpolation"]
    assert "upper" not in {f.name for f in types["Computed"].fields}
    assert "target" not in {f.name for f in types["Interpolated"].fields}
    assert [f.name for f in types["Conditional"].fields] == ["tier"]
    assert len(types["Narrowed"].fields) == len(types["Scalars"].fields)


@needs_cue
def test_cue_module_set_resolves_its_imported_package():
    members = {p.name: p.read_text() for p in (EXAMPLES / "cue/03-imports-set").iterdir()}
    adapter = get_import_source("cue")
    api = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root="schema.cue")))
    assert {"Shipment", "Address", "Money"} <= set(types_of(api))


@needs_cue
def test_cue_without_definitions_and_incomplete_data_are_rejected():
    assert rejection("cue", "package a\n\nx: 1\n", "a.cue").code == "INPUT_SEMANTIC_INVALID"
    assert rejection("cue", "package a\n#A: {x: int}\na: #A\n", "a.cue").code == "INPUT_SEMANTIC_INVALID"
    unresolved = rejection("cue", 'package a\nimport "example.com/nowhere"\n#A: nowhere.#B\n', "a.cue")
    assert unresolved.code == "INPUT_REFERENCE_UNRESOLVED"


@needs_pkl
def test_pkl_classes_import_with_constraints_inheritance_and_defaults():
    api = read("pkl", (EXAMPLES / "pkl/02-typical-order-schema.pkl").read_text(), "orders.pkl")
    types = types_of(api)
    assert api.identity.name == "Orders"  # a template module's own properties
    assert field(types["Order"], "customerId").constraints.max_length == 20
    assert field(types["Order"], "status").default == "new"
    assert field(types["OrderLine"], "discount").type.nullable
    assert field(types["OrderLine"], "discount").constraints.maximum == 1.0
    assert types["Sku"].constraints.pattern == "^[A-Z]{3}-[0-9]{4}$"

    stress = read("pkl", (EXAMPLES / "pkl/04-stress-type-system.pkl").read_text(), "stress.pkl")
    stress_types = types_of(stress)
    assert {f.name for f in stress_types["Derived"].fields} == {"id", "createdAt", "extra"}
    assert field(stress_types["Circle"], "kind").default == "circle"
    assert field(stress_types["Scalars"], "small").constraints.minimum == -128
    limits = limits_of(stress)
    assert limits["pkl.external_read"] == ["FromEnvironment.region"]
    assert "SelfReferential.maximum" in limits["pkl.late_binding"]
    assert "Computed.total" in limits["pkl.computed_default"]
    assert field(stress_types["Computed"], "total").default is None


@needs_pkl
def test_pkl_sandbox_refuses_resources_and_modules_outside_the_upload():
    refused = read("pkl", 'module m\n\nregion: String = read("env:HOME").text\nid: String\n', "m.pkl")
    assert limits_of(refused)["pkl.external_read"] == ["M.region"]
    assert rejection("pkl", 'import "https://example.com/x.pkl"\nv = x.y\n', "m.pkl").code == (
        "INPUT_REFERENCE_UNRESOLVED"
    )
    assert rejection("pkl", 'import "/etc/hostinfo.pkl"\nv = hostinfo.y\n', "m.pkl").code == (
        "INPUT_REFERENCE_UNRESOLVED"
    )


@needs_pkl
def test_pkl_value_that_breaks_its_constraint_is_rejected():
    text = "module m\n\nclass Port {\n  value: Int(isBetween(1024, 65535)) = 80\n}\n\nport: Port = new {}\n"
    error = rejection("pkl", text, "m.pkl")
    assert error.code == "INPUT_SEMANTIC_INVALID"
    assert "isBetween(1024, 65535)" in str(error)


@needs_pkl
def test_pkl_module_set_resolves_imports():
    members = {p.name: p.read_text() for p in (EXAMPLES / "pkl/03-modules-set").iterdir()}
    adapter = get_import_source("pkl")
    api = adapter.normalize(adapter.parse_fileset(IntakeFileset.from_members(members, root="shipping.pkl")))
    types = types_of(api)
    assert field(types["Shipment"], "destination").type.name == "Address"
    assert field(types["Address"], "countryCode").constraints.min_length == 2


@needs_dhall
def test_dhall_types_import_with_defaults_and_unions():
    api = read("dhall", (EXAMPLES / "dhall/06-typical-union-and-defaults.dhall").read_text(), "u.dhall")
    types = types_of(api)
    assert field(types["Product"], "currency").default == "EUR"
    assert types["Payment"].kind is TypeKind.UNION
    assert "PaymentCard" in types
    assert api.extras["dhall"]["instances"] == ["catalogue"]


@needs_dhall
def test_dhall_type_level_functions_and_hashes_are_declared():
    api = read("dhall", (EXAMPLES / "dhall/04-stress-type-system.dhall").read_text(), "s.dhall")
    limits = limits_of(api)
    assert set(limits["dhall.function"]) == {"Page", "withEnvelope"}
    assert "dhall.integrity_check" in limits
    assert {f.name for f in types_of(api)["OrderPage"].fields} == {"cursor", "items", "total"}


@needs_dhall
def test_dhall_refuses_imports_before_running():
    error = rejection("dhall", "let T = env:HOME as Text in { T = Text }\n", "a.dhall")
    assert error.code == "INPUT_REFERENCE_UNRESOLVED"
    assert "env:HOME" in str(error)


@needs_dhall
def test_dhall_type_error_is_semantic():
    error = rejection("dhall", 'let n : Natural = "x" in { T = Text }\n', "a.dhall")
    assert error.code == "INPUT_SEMANTIC_INVALID"
