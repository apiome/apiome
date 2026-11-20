"""Tests for the lint-fix round-trip rewriter (GVM-3.3, #5871)."""

from __future__ import annotations

import json

import pytest

from apiome_cli.lint_fix_file import FixApplyError, is_json_text, rewrite_document_text

_YAML = """\
# Payments API — keep this header comment
openapi: 3.1.0
info:
  title: Payments   # trailing comment
  version: '1.0'
servers:
  - url: https://api.example.com/
paths: {}
components:
  schemas:
    Order:
      # why Order exists
      type: object
      required: []
      properties:
        id: {type: string}
"""


def test_yaml_comments_key_order_and_quotes_survive_a_fix() -> None:
    ops = [
        {"op": "remove", "path": "/components/schemas/Order/required"},
        {"op": "replace", "path": "/servers/0/url", "value": "https://api.example.com"},
    ]

    out = rewrite_document_text(_YAML, ops)

    assert "# Payments API — keep this header comment" in out
    assert "# trailing comment" in out
    assert "# why Order exists" in out
    assert "version: '1.0'" in out
    assert "required: []" not in out
    assert "- url: https://api.example.com\n" in out
    keys = [line.split(":")[0] for line in out.splitlines() if line and line[0].isalpha()]
    assert keys == ["openapi", "info", "servers", "paths", "components"]
    # Every other line is byte-identical.
    assert out.splitlines() == [
        line.replace("https://api.example.com/", "https://api.example.com")
        for line in _YAML.splitlines()
        if "required: []" not in line
    ]


def test_yaml_explicit_document_start_is_kept() -> None:
    text = "---\nopenapi: 3.1.0\ntags:\n  - name: a\n  - name: a\n"

    out = rewrite_document_text(text, [{"op": "remove", "path": "/tags/1"}])

    assert out == "---\nopenapi: 3.1.0\ntags:\n  - name: a\n"


@pytest.mark.parametrize("indent", [2, 4, "\t"])
def test_json_keeps_its_indentation_and_key_order(indent: int | str) -> None:
    doc = {"openapi": "3.1.0", "info": {"title": "T"}, "paths": {}, "tags": ["b", "a"]}
    text = json.dumps(doc, indent=indent) + "\n"

    out = rewrite_document_text(text, [{"op": "add", "path": "/tags/-", "value": "c"}])

    assert out == json.dumps({**doc, "tags": ["b", "a", "c"]}, indent=indent) + "\n"


def test_single_line_json_stays_on_one_line() -> None:
    out = rewrite_document_text('{"a": 1, "b": 2}', [{"op": "remove", "path": "/a"}])

    assert out == '{"b": 2}'


def test_move_and_escaped_pointer_tokens() -> None:
    text = '{"paths": {"/pets": {"get": {"operationId": "List_pets"}}}}'
    ops = [
        {
            "op": "move",
            "from": "/paths/~1pets/get/operationId",
            "path": "/paths/~1pets/get/x-old",
        }
    ]

    out = json.loads(rewrite_document_text(text, ops))

    assert out == {"paths": {"/pets": {"get": {"x-old": "List_pets"}}}}


def test_no_ops_returns_the_text_unchanged() -> None:
    assert rewrite_document_text(_YAML, []) == _YAML


@pytest.mark.parametrize(
    "op",
    [
        {"op": "copy", "from": "/info", "path": "/x"},
        {"op": "remove", "path": "/components/schemas/Missing"},
        {"op": "replace", "path": "/servers/9/url", "value": "x"},
        {"op": "remove", "path": ""},
        {"op": "remove", "path": "no-slash"},
    ],
)
def test_an_unappliable_op_raises(op: dict[str, object]) -> None:
    with pytest.raises(FixApplyError):
        rewrite_document_text(_YAML, [op])


def test_is_json_text() -> None:
    assert is_json_text('  {"openapi": "3.1.0"}')
    assert not is_json_text(_YAML)


@pytest.mark.parametrize(
    "text",
    [
        "openapi: 3.1.0\ntags:\n- name: a\n- name: b\npaths: {}\n",
        "openapi: 3.1.0\ninfo:\n    title: T\ntags:\n    -   name: a\n    -   name: b\n",
    ],
)
def test_yaml_sequence_and_mapping_indentation_are_kept(text: str) -> None:
    out = rewrite_document_text(text, [{"op": "remove", "path": "/tags/1"}])

    assert out == text.replace("- name: b\n", "").replace("    -   name: b\n", "")
