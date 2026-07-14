"""Tests for oasdiff OpenAPI compatibility adapter (CLX-2.3 / #4853)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.external_linter_adapter import (
    AdapterInput,
    InputFormat,
    ScanMode,
    adapters_for_format,
    get_adapter,
    load_builtin_adapters,
    run_adapter,
)
from app.external_linter_runner import RestrictedRunSuccess
from app.openapi_compatibility_adapters import (
    CHANGE_CLASS_BREAKING,
    CHANGE_CLASS_DANGEROUS,
    CHANGE_CLASS_INFORMATIONAL,
    OASDIFF_ADAPTER_ID,
    OasdiffAdapter,
    oasdiff_level_to_change_class,
    parse_oasdiff_changelog_json,
)
from app.toolchain_packaging import probe_tool

_FIXTURES = Path(__file__).parent / "fixtures" / "openapi_compatibility"
_GOLDEN = json.loads((_FIXTURES / "mapping_golden.json").read_text(encoding="utf-8"))


def test_oasdiff_adapter_registers_for_openapi_breaking():
    load_builtin_adapters()
    ids = {a.adapter_id for a in adapters_for_format(InputFormat.OPENAPI)}
    assert OASDIFF_ADAPTER_ID in ids
    adapter = get_adapter(OASDIFF_ADAPTER_ID)
    assert adapter is not None
    decl = adapter.declaration()
    assert ScanMode.BREAKING in decl.scan_modes
    assert decl.tool_key == "oasdiff"


@pytest.mark.parametrize(
    "level,expected",
    [
        (3, CHANGE_CLASS_BREAKING),
        (2, CHANGE_CLASS_DANGEROUS),
        (1, CHANGE_CLASS_INFORMATIONAL),
        ("ERR", CHANGE_CLASS_BREAKING),
        ("warn", CHANGE_CLASS_DANGEROUS),
        ("info", CHANGE_CLASS_INFORMATIONAL),
    ],
)
def test_oasdiff_level_to_change_class(level, expected):
    assert oasdiff_level_to_change_class(level) == expected


def test_parse_info_findings_preserve_rule_id_and_location():
    raw = (_FIXTURES / "changelog_info.json").read_text(encoding="utf-8")
    findings = parse_oasdiff_changelog_json(raw)
    assert len(findings) == 1
    f = findings[0]
    expect = _GOLDEN["info"]
    assert f["rule_id"] == expect["rule_id"]
    assert f["change_class"] == expect["change_class"]
    assert f["severity"] == expect["severity"]
    assert f["path"] == expect["path"]
    assert f["start_line"] == expect["start_line"]


def test_parse_breaking_findings_map_to_error():
    raw = (_FIXTURES / "changelog_breaking.json").read_text(encoding="utf-8")
    findings = parse_oasdiff_changelog_json(raw)
    assert len(findings) == 1
    f = findings[0]
    expect = _GOLDEN["breaking"]
    assert f["rule_id"] == expect["rule_id"]
    assert f["change_class"] == expect["change_class"]
    assert f["severity"] == expect["severity"]
    assert f["path"] == expect["path"]
    assert f["start_line"] == expect["start_line"]


def test_map_envelope_stamps_change_class_and_api_path():
    adapter = OasdiffAdapter()
    raw = parse_oasdiff_changelog_json(
        (_FIXTURES / "changelog_breaking.json").read_text(encoding="utf-8")
    )
    envelopes = adapter.map_envelope(raw)
    assert len(envelopes) == 1
    env = envelopes[0]
    assert env["change_class"] == CHANGE_CLASS_BREAKING
    assert env["category"] == "compatibility"
    assert env["rule_id"] == "api-path-removed-without-deprecation"
    assert env["location"]["apiPath"] == "/pets"
    assert env["location"]["operation"] == "GET"


@pytest.mark.asyncio
async def test_fake_runner_findings_become_evidence():
    stdout = (_FIXTURES / "changelog_breaking.json").read_text(encoding="utf-8")
    mock_runner = MagicMock()
    mock_runner.run_spec = AsyncMock(
        return_value=RestrictedRunSuccess(
            key="oasdiff",
            argv=("oasdiff", "changelog"),
            exit_code=0,
            stdout=stdout,
            stderr="",
            duration_ms=12,
        )
    )
    base_doc = json.loads(
        json.dumps(
            {
                "openapi": "3.0.3",
                "info": {"title": "Pets", "version": "1.0.0"},
                "paths": {},
            }
        )
    )
    head_doc = dict(base_doc)
    head_doc["info"] = {"title": "Pets", "version": "1.1.0"}
    inputs = AdapterInput(
        document=head_doc,
        format=InputFormat.OPENAPI,
        scan_mode=ScanMode.BREAKING,
        metadata={"base_document": base_doc},
    )
    result = await run_adapter(OasdiffAdapter(), inputs, runner=mock_runner)
    assert result.outcome_ready
    assert result.failure_kind is None
    assert len(result.envelope_findings) == 1
    evidence = result.to_evidence_run(subject_id="rev-head-1")
    assert evidence["scanner_id"] == OASDIFF_ADAPTER_ID
    assert evidence["findings"][0]["change_class"] == CHANGE_CLASS_BREAKING


@pytest.mark.asyncio
async def test_real_oasdiff_when_available():
    avail = probe_tool("oasdiff")
    if not getattr(avail, "available", False):
        # Allow override for local/CI when binary is installed outside PATH packaging.
        pytest.importorskip("shutil")
        import shutil

        if shutil.which("oasdiff") is None and not Path("/tmp/oasdiff").is_file():
            pytest.skip("oasdiff not available")
        env_patch = {"APIOME_OASDIFF_BIN": "/tmp/oasdiff"}
    else:
        env_patch = {}

    base_yaml = (_FIXTURES / "base" / "openapi.yaml").read_text(encoding="utf-8")
    rev_yaml = (_FIXTURES / "revision_removed_path.yaml").read_text(encoding="utf-8")
    inputs = AdapterInput(
        files={"openapi.yaml": rev_yaml},
        format=InputFormat.OPENAPI,
        scan_mode=ScanMode.BREAKING,
        metadata={"base_files": {"openapi.yaml": base_yaml}},
    )
    with patch.dict("os.environ", env_patch, clear=False):
        # Re-register so probe picks up override.
        from app.toolchain_packaging import register_bundled_tools

        register_bundled_tools()
        result = await run_adapter(OasdiffAdapter(), inputs)

    if result.failure_kind == "unavailable":
        pytest.skip("oasdiff unavailable in this environment")
    assert result.outcome_ready, result.diagnostics
    assert any(
        f.get("change_class") == CHANGE_CLASS_BREAKING for f in result.envelope_findings
    )
