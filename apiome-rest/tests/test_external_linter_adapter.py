"""Unit tests for the external-linter adapter SPI (CLX-2.1, #4851)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.external_linter_adapter import (
    BUF_LINT_ADAPTER_ID,
    AdapterDeclaration,
    BufLintAdapter,
    ExternalLinterAdapter,
    InputFormat,
    ScanMode,
    adapters_for_format,
    available_adapters,
    get_adapter,
    register_adapter,
)
from app.external_linter_parsers import (
    OUTPUT_FORMAT_JSON,
    OUTPUT_FORMAT_JSONL,
    OUTPUT_FORMAT_SARIF,
    AdapterOutputError,
    envelope_from_tool_finding,
    parse_json_document,
    parse_jsonl,
    parse_sarif,
    parse_tool_output,
)
from app.external_linter_runner import (
    FAILURE_UNAVAILABLE,
    RestrictedRunner,
    failure_kind_to_outcome,
    redact_env_for_log,
)
from app.lint_evidence import OUTCOME_UNAVAILABLE
from app.toolchain_runner import ToolNotAvailableError, ToolSpec

_FIXTURES = Path(__file__).parent / "fixtures" / "external_linter"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_json_document_findings_array() -> None:
    findings = parse_json_document(_load("findings.json"))
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "example.no-empty-servers"


def test_parse_json_document_clean() -> None:
    assert parse_json_document(_load("clean.json")) == []


def test_parse_jsonl_findings() -> None:
    findings = parse_jsonl(_load("findings.jsonl"))
    assert [f["rule_id"] for f in findings] == [
        "example.unused-component",
        "example.operation-id",
    ]


def test_parse_jsonl_clean() -> None:
    assert parse_jsonl(_load("clean.jsonl")) == []


def test_parse_jsonl_malformed_raises() -> None:
    with pytest.raises(AdapterOutputError, match="jsonl"):
        parse_jsonl(_load("malformed.jsonl"))


def test_parse_sarif_preserves_source_rule_ids_and_locations() -> None:
    findings = parse_sarif(_load("findings.sarif.json"))
    golden = json.loads(_load("mapping_golden.json"))["sarif_findings"]
    assert len(findings) == len(golden)
    for actual, expected in zip(findings, golden):
        assert actual["rule_id"] == expected["rule_id"]
        assert actual["path"] == expected["path"]
        assert actual["start_line"] == expected["start_line"]
        assert actual["start_column"] == expected["start_column"]
        assert actual["severity"] == expected["severity"]


def test_parse_sarif_clean() -> None:
    assert parse_sarif(_load("clean.sarif.json")) == []


def test_parse_sarif_malformed_raises() -> None:
    with pytest.raises(AdapterOutputError, match="SARIF|sarif|runs"):
        parse_sarif(_load("malformed.sarif.json"))


def test_parse_tool_output_dispatch() -> None:
    assert parse_tool_output(_load("findings.json"), OUTPUT_FORMAT_JSON)
    assert parse_tool_output(_load("findings.jsonl"), OUTPUT_FORMAT_JSONL)
    assert parse_tool_output(_load("findings.sarif.json"), OUTPUT_FORMAT_SARIF)


def test_envelope_preserves_rule_id_and_location() -> None:
    env = envelope_from_tool_finding(
        {
            "rule_id": "source-rule-alpha",
            "message": "Alpha violation",
            "severity": "error",
            "path": "openapi.yaml",
            "start_line": 8,
            "start_column": 2,
        }
    )
    assert env["rule_id"] == "source-rule-alpha"
    assert env["location"] == {
        "path": "openapi.yaml",
        "start_line": 8,
        "start_column": 2,
    }
    assert env["severity"] == "error"


# ---------------------------------------------------------------------------
# Restricted runner redaction
# ---------------------------------------------------------------------------


def test_redact_env_for_log_masks_secrets() -> None:
    redacted = redact_env_for_log(
        {
            "PATH": "/usr/bin",
            "API_TOKEN": "super-secret",
            "DB_PASSWORD": "hunter2",
            "NORMAL": "ok",
        }
    )
    assert redacted["PATH"] == "/usr/bin"
    assert redacted["NORMAL"] == "ok"
    assert redacted["API_TOKEN"] == "<redacted>"
    assert redacted["DB_PASSWORD"] == "<redacted>"


def test_failure_kind_to_outcome() -> None:
    assert failure_kind_to_outcome(FAILURE_UNAVAILABLE) == OUTCOME_UNAVAILABLE


async def test_restricted_runner_maps_unavailable() -> None:
    class _Boom:
        async def run_spec(self, *args: object, **kwargs: object) -> object:
            raise ToolNotAvailableError("fake", "fake-bin")

    runner = RestrictedRunner(inner=_Boom())  # type: ignore[arg-type]
    outcome = await runner.run_spec(
        ToolSpec(key="fake", executable="fake-bin", parses_json=False),
        [],
    )
    assert outcome.kind == FAILURE_UNAVAILABLE  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_buf_adapter_is_registered() -> None:
    assert BUF_LINT_ADAPTER_ID in available_adapters()
    assert get_adapter(BUF_LINT_ADAPTER_ID) is BufLintAdapter
    assert BufLintAdapter in adapters_for_format(InputFormat.PROTOBUF)


def test_buf_adapter_declaration() -> None:
    decl = BufLintAdapter.declaration()
    assert isinstance(decl, AdapterDeclaration)
    assert decl.formats == (InputFormat.PROTOBUF,)
    assert decl.scan_modes == (ScanMode.LINT,)
    assert decl.tool_key == "buf"
    assert decl.output_format == OUTPUT_FORMAT_JSONL
    assert decl.availability_tools() == ("buf",)


def test_register_adapter_rejects_duplicate_different_class() -> None:
    class _Dup(ExternalLinterAdapter):
        adapter_id = BUF_LINT_ADAPTER_ID

        def tool_spec(self) -> ToolSpec:
            return ToolSpec(key="x", executable="x", parses_json=False)

        def build_args(self, inputs, *, workspace=None):  # type: ignore[no-untyped-def]
            return []

    with pytest.raises(ValueError, match="already registered"):
        register_adapter(_Dup)
