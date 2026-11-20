"""Tests for ``apiome lint suggest <file>`` and its pure helpers (GVM-3.4, #5872)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli.lint_fix_suggest import (
    MAX_SNIPPET_LINES,
    MAX_SUGGESTED_RULES,
    build_suggestions,
    fence_for,
    first_hunk,
    format_suggestions_markdown,
    single_region,
)
from apiome_cli.main import app

runner = CliRunner()

_PLAN_URL = "http://localhost:8000/v1/lint/fixes/plan"

SPEC = """\
openapi: 3.1.0
info:
  title: Shop  # the shop
  version: 1.0.0
tags:
  - name: orders
  - name: orders
paths:
  /orders:
    get:
      responses:
        '200':
          description: OK
components:
  schemas:
    Order:
      type: object
      required: []
"""


def _entry(fix_id: str, rule_id: str, status: str, ops: list[dict], fix_class: str = "removal") -> dict:
    return {
        "fixId": fix_id,
        "ruleId": rule_id,
        "fixClass": fix_class,
        "path": "x",
        "pointer": "/x",
        "message": f"{rule_id} finding",
        "ops": ops,
        "status": status,
    }


DUP_TAG = _entry("fix-tag", "structure.duplicate-tag", "ready", [{"op": "remove", "path": "/tags/1"}])
EMPTY_REQUIRED = _entry(
    "fix-req", "structure.empty-required", "ready", [{"op": "remove", "path": "/components/schemas/Order/required"}]
)
OPERATION_ID = _entry(
    "fix-opid",
    "structure.operation-id-required",
    "ready",
    [{"op": "add", "path": "/paths/~1orders/get/operationId", "value": "getOrders"}],
    fix_class="fill-in",
)
TWO_REGIONS = _entry(
    "fix-two",
    "structure.two-places",
    "ready",
    [
        {"op": "replace", "path": "/info/title", "value": "Store"},
        {"op": "remove", "path": "/components/schemas/Order/required"},
    ],
)
BREAKING = _entry("fix-brk", "naming.schema-pascal-case", "breaking", [])
CONFLICT = _entry("fix-cfl", "structure.schema-example-keyword", "conflict", [])


def _plan(*entries: dict) -> dict:
    return {"entries": list(entries), "appliedOrder": [e["fixId"] for e in entries if e["status"] == "ready"]}


# ---------------------------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------------------------


def test_single_region_replaces_the_changed_lines():
    region = single_region("a\nb\nc\n", "a\nB\nc\n")
    assert region == {"startLine": 2, "endLine": 2, "replacement": "B\n"}


def test_single_region_deletes_lines_with_an_empty_replacement():
    assert single_region("a\nb\nc\n", "a\nc\n") == {"startLine": 2, "endLine": 2, "replacement": ""}


def test_an_insertion_is_anchored_to_the_line_before_it():
    assert single_region("a\nc\n", "a\nb\nc\n") == {"startLine": 1, "endLine": 1, "replacement": "a\nb\n"}


def test_an_insertion_at_the_top_is_anchored_to_the_first_line():
    assert single_region("b\n", "a\nb\n") == {"startLine": 1, "endLine": 1, "replacement": "a\nb\n"}


def test_several_regions_or_no_change_have_no_single_region():
    assert single_region("a\nb\nc\nd\ne\n", "A\nb\nc\nd\nE\n") is None
    assert single_region("a\n", "a\n") is None
    assert single_region("", "a\n") is None


def test_first_hunk_has_no_file_header_and_is_capped():
    hunk = first_hunk("a\nb\n", "a\nB\n")
    assert hunk.startswith("@@ ") and "-b" in hunk and "+B" in hunk and "---" not in hunk
    long = first_hunk("x\n", "".join(f"{i}\n" for i in range(40)))
    assert len(long.splitlines()) == MAX_SNIPPET_LINES + 1 and long.endswith("…")


def test_suggestions_are_anchored_to_the_real_file_lines():
    summary = build_suggestions(SPEC, _plan(DUP_TAG, EMPTY_REQUIRED, BREAKING, CONFLICT), path="api/openapi.yaml")
    assert summary["path"] == "api/openapi.yaml"
    assert (summary["ready"], summary["breaking"], summary["conflict"]) == (2, 1, 1)
    assert [r["ruleId"] for r in summary["rules"]] == ["structure.duplicate-tag", "structure.empty-required"]
    by_fix = {s["fixId"]: s for s in summary["suggestions"]}
    lines = SPEC.splitlines()
    tag = by_fix["fix-tag"]
    assert lines[tag["startLine"] - 1] == "  - name: orders" and tag["replacement"] == ""
    req = by_fix["fix-req"]
    assert lines[req["startLine"] - 1] == "      required: []" and req["replacement"] == ""
    # The YAML comment survives: the snippet is a hunk of the file, not of reconstructed JSON.
    assert "-  - name: orders" in summary["rules"][0]["snippet"]


def test_an_inserted_operation_id_is_one_region():
    summary = build_suggestions(SPEC, _plan(OPERATION_ID), path="openapi.yaml")
    (suggestion,) = summary["suggestions"]
    # An added key lands at the end of its mapping, so the suggestion re-states the line before it.
    anchor = SPEC.splitlines().index("          description: OK") + 1
    assert suggestion["startLine"] == suggestion["endLine"] == anchor
    assert suggestion["replacement"] == "          description: OK\n      operationId: getOrders\n"


def test_a_fix_spanning_two_regions_gets_a_snippet_but_no_suggestion():
    summary = build_suggestions(SPEC, _plan(TWO_REGIONS), path="openapi.yaml")
    assert summary["rules"][0]["count"] == 1 and summary["rules"][0]["snippet"]
    assert summary["suggestions"] == []


def test_a_fix_the_rewriter_cannot_apply_is_counted_without_a_region():
    bad = _entry("fix-bad", "structure.bad", "ready", [{"op": "remove", "path": "/nope/0"}])
    summary = build_suggestions(SPEC, _plan(bad), path="openapi.yaml")
    assert summary["ready"] == 1 and summary["rules"][0]["snippet"] == ""
    assert summary["suggestions"] == []


def test_the_markdown_lists_rules_classes_snippets_and_the_artefact_link():
    summary = build_suggestions(SPEC, _plan(DUP_TAG, EMPTY_REQUIRED, OPERATION_ID, BREAKING), path="openapi.yaml")
    md = format_suggestions_markdown(summary, artifact_url="https://github.com/o/r/actions/runs/1#artifacts")
    assert md.startswith("### Suggested fixes\n")
    assert "3 mechanical fixes ready for `openapi.yaml`; nothing is pushed to the branch." in md
    assert "- `structure.duplicate-tag` — 1 fix (removal)" in md
    assert "- `structure.operation-id-required` — 1 fix (fill-in)" in md
    assert md.count("```diff") == 3
    assert "1 breaking and 0 conflicting fixes need a person" in md
    assert "[workflow artefacts](https://github.com/o/r/actions/runs/1#artifacts)" in md


def test_the_markdown_says_when_nothing_is_suggested():
    md = format_suggestions_markdown(build_suggestions(SPEC, _plan(), path="openapi.yaml"))
    assert "No mechanical lint fixes for `openapi.yaml`." in md
    assert "artefacts" not in md


def test_the_markdown_caps_the_rules_and_fences_backticks():
    rules = [{"ruleId": f"r{i}", "fixClass": "removal", "count": 1, "snippet": ""} for i in range(12)]
    md = format_suggestions_markdown({"path": "p", "ready": 12, "rules": rules})
    assert "`r9`" in md and "`r10`" not in md
    assert f"… and {12 - MAX_SUGGESTED_RULES} more rules." in md
    assert fence_for("a ``` b") == "````" and fence_for("plain") == "```"


# ---------------------------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------------------------


@pytest.fixture
def api_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_API_KEY", "test-key")
    monkeypatch.setenv("APIOME_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("APIOME_TENANT_ID", "acme-corp")


@pytest.fixture
def spec_file(tmp_path: Path) -> Path:
    path = tmp_path / "openapi.yaml"
    path.write_text(SPEC, encoding="utf-8")
    return path


def _bodies(httpx_mock: object) -> list[dict]:
    return [json.loads(r.content) for r in httpx_mock.get_requests() if r.method == "POST"]


@pytest.mark.usefixtures("api_key_env")
def test_suggest_prints_the_markdown_section(httpx_mock: object, spec_file: Path) -> None:
    httpx_mock.add_response(url=_PLAN_URL, method="POST", json=_plan(DUP_TAG))
    result = runner.invoke(
        app, ["lint", "suggest", str(spec_file), "--path", "api/openapi.yaml", "--only", "structure.duplicate-tag"]
    )
    assert result.exit_code == 0, result.output
    assert "### Suggested fixes" in result.stdout
    assert "`api/openapi.yaml`" in result.stdout
    (body,) = _bodies(httpx_mock)
    assert body["document"] == SPEC and body["format"] == "json"
    assert body["rules"] == ["structure.duplicate-tag"] and body["includeRenames"] is False
    assert spec_file.read_text(encoding="utf-8") == SPEC  # never rewritten


@pytest.mark.usefixtures("api_key_env")
def test_suggest_json_carries_the_suggestion_ranges(httpx_mock: object, spec_file: Path, tmp_path: Path) -> None:
    httpx_mock.add_response(url=_PLAN_URL, method="POST", json=_plan(DUP_TAG))
    out = tmp_path / "fixes.json"
    result = runner.invoke(app, ["lint", "suggest", str(spec_file), "--format", "json", "-o", str(out)])
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["suggestions"][0]["fixId"] == "fix-tag"
    assert payload["path"] == str(spec_file)


@pytest.mark.usefixtures("api_key_env")
def test_suggest_patch_writes_the_plan_endpoint_bytes(httpx_mock: object, spec_file: Path, tmp_path: Path) -> None:
    patch_bytes = b'[\n  {\n    "op": "remove",\n    "path": "/tags/1"\n  }\n]\n'
    httpx_mock.add_response(url=_PLAN_URL, method="POST", content=patch_bytes)
    out = tmp_path / "fixes.patch.json"
    result = runner.invoke(app, ["lint", "suggest", str(spec_file), "--format", "patch", "-o", str(out), "--allow-renames"])
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == patch_bytes
    (body,) = _bodies(httpx_mock)
    assert body["format"] == "patch" and body["includeRenames"] is True


@pytest.mark.usefixtures("api_key_env")
def test_suggest_refuses_an_unknown_format(spec_file: Path) -> None:
    result = runner.invoke(app, ["lint", "suggest", str(spec_file), "--format", "sarif"])
    assert result.exit_code == 2
    assert "must be one of" in result.output


@pytest.mark.usefixtures("api_key_env")
def test_suggest_reports_an_unreadable_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["lint", "suggest", str(tmp_path / "missing.yaml")])
    assert result.exit_code == 2
    assert "Cannot read" in result.output
