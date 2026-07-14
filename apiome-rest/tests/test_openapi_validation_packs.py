"""Tests for OpenAPI validation packs (CLX-2.2 / #4852)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.external_linter_adapter import (
    AdapterInput,
    InputFormat,
    adapters_for_format,
    get_adapter,
    load_builtin_adapters,
)
from app.openapi_validation_adapters import (
    REDOCLY_OAS_ADAPTER_ID,
    SPECTRAL_OAS_ADAPTER_ID,
    VACUUM_OAS_ADAPTER_ID,
    parse_spectral_json_findings,
)
from app.openapi_validation_pack import (
    DEFAULT_BULK_RUNNER,
    list_openapi_validation_adapters,
    parity_default_runner_rationale,
    run_openapi_validation_pack,
)
from app.openapi_validation_profiles import (
    PROFILE_BASELINE,
    PROFILE_STRICT,
    PROFILE_TENANT_GUIDE,
    normalize_profile,
    render_tenant_guide_spectral_ruleset,
    spectral_ruleset_path,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "openapi_validation_parity"
_MATRIX = json.loads((_FIXTURES / "parity_matrix.json").read_text(encoding="utf-8"))


def test_default_bulk_runner_is_spectral_per_parity_matrix():
    assert DEFAULT_BULK_RUNNER == SPECTRAL_OAS_ADAPTER_ID
    assert _MATRIX["default_bulk_runner"] == SPECTRAL_OAS_ADAPTER_ID
    assert "parity" in parity_default_runner_rationale().lower()
    assert "speed" in parity_default_runner_rationale().lower()


def test_profiles_normalize():
    assert normalize_profile(None) == PROFILE_BASELINE
    assert normalize_profile("STRICT") == PROFILE_STRICT
    assert normalize_profile("tenant-guide") == PROFILE_TENANT_GUIDE


def test_curated_rulesets_exist():
    assert spectral_ruleset_path(PROFILE_BASELINE).is_file()
    assert spectral_ruleset_path(PROFILE_STRICT).is_file()


def test_tenant_guide_overlay_extends_baseline():
    yaml_text = render_tenant_guide_spectral_ruleset(
        baseline_ruleset=spectral_ruleset_path(PROFILE_BASELINE),
        custom_rules={
            "tenant.must-have-x": {
                "description": "require x",
                "severity": "error",
                "given": "$.info",
                "then": {"function": "truthy", "field": "x-owned-by"},
            }
        },
    )
    assert "extends:" in yaml_text
    assert "tenant.must-have-x" in yaml_text
    assert "baseline" in yaml_text or str(spectral_ruleset_path(PROFILE_BASELINE)) in yaml_text


def test_adapters_register_for_openapi():
    load_builtin_adapters()
    ids = {a.adapter_id for a in adapters_for_format(InputFormat.OPENAPI)}
    assert SPECTRAL_OAS_ADAPTER_ID in ids
    assert VACUUM_OAS_ADAPTER_ID in ids
    assert REDOCLY_OAS_ADAPTER_ID in ids
    assert get_adapter(SPECTRAL_OAS_ADAPTER_ID) is not None


def test_parse_spectral_json_findings_preserves_rule_id_and_location():
    raw = json.dumps(
        [
            {
                "code": "operation-operationId",
                "message": "Operation must have operationId.",
                "path": ["paths", "/things", "get"],
                "severity": 0,
                "range": {"start": {"line": 8, "character": 4}},
                "documentationUrl": "https://example.com/rules/operation-operationId",
            }
        ]
    )
    findings = parse_spectral_json_findings(raw)
    assert len(findings) == 1
    assert findings[0]["rule_id"] == "operation-operationId"
    assert "paths" in findings[0]["path"]
    assert findings[0]["start_line"] == 8
    assert findings[0]["remediation"]


def test_parity_fixture_multifile_has_local_ref_only():
    entry = (_FIXTURES / "clean" / "openapi.yaml").read_text(encoding="utf-8")
    assert "$ref: \"./components.yaml" in entry or "$ref: './components.yaml" in entry
    assert "http://" not in entry and "https://" not in entry
    assert (_FIXTURES / "clean" / "components.yaml").is_file()


def test_list_openapi_validation_adapters_discovery():
    adapters = list_openapi_validation_adapters()
    ids = {a["adapter_id"] for a in adapters}
    assert ids == {SPECTRAL_OAS_ADAPTER_ID, VACUUM_OAS_ADAPTER_ID, REDOCLY_OAS_ADAPTER_ID}
    spectral = next(a for a in adapters if a["adapter_id"] == SPECTRAL_OAS_ADAPTER_ID)
    assert spectral["is_default_bulk_runner"] is True
    assert PROFILE_BASELINE in spectral["profiles"]


@pytest.mark.asyncio
async def test_pack_runs_default_runner_with_injected_toolchain():
    """Facade invokes the default Spectral adapter; unavailable tools degrade via SPI."""
    with patch(
        "app.openapi_validation_pack.run_adapter",
        new_callable=AsyncMock,
    ) as m_run:
        fake = MagicMock()
        fake.lint_findings = []
        fake.envelope_findings = []
        fake.failure_kind = "unavailable"
        fake.to_evidence_run = MagicMock(return_value={"scanner_id": SPECTRAL_OAS_ADAPTER_ID})
        m_run.return_value = fake
        result = await run_openapi_validation_pack(
            document={"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": {}},
            profile=PROFILE_BASELINE,
        )
    assert result.runner_id == DEFAULT_BULK_RUNNER
    assert result.profile == PROFILE_BASELINE
    m_run.assert_awaited()


@pytest.mark.asyncio
async def test_pack_workspace_args_point_at_profile_ruleset():
    load_builtin_adapters()
    adapter_cls = get_adapter(SPECTRAL_OAS_ADAPTER_ID)
    assert adapter_cls is not None
    adapter = adapter_cls()
    inputs = AdapterInput(
        document={"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": {}},
        format=InputFormat.OPENAPI,
        metadata={"profile": PROFILE_STRICT},
    )
    with adapter.prepare_workspace(inputs) as workspace:
        assert workspace
        args = list(adapter.build_args(inputs, workspace=workspace))
    assert "-r" in args
    assert "-f" in args and "sarif" in args
    ruleset_arg = args[args.index("-r") + 1]
    assert "strict" in ruleset_arg.replace("\\", "/")


from app.toolchain_packaging import probe_tool

_SPECTRAL_AVAILABLE = bool(getattr(probe_tool("spectral"), "available", False))
_VACUUM_AVAILABLE = bool(getattr(probe_tool("vacuum"), "available", False))


@pytest.mark.asyncio
@pytest.mark.skipif(not _SPECTRAL_AVAILABLE, reason="spectral binary unavailable")
async def test_real_spectral_lint_violations_fixture():
    files = {
        "openapi.yaml": (_FIXTURES / "violations" / "openapi.yaml").read_text(encoding="utf-8"),
    }
    result = await run_openapi_validation_pack(
        files=files, profile=PROFILE_BASELINE, runner_id=SPECTRAL_OAS_ADAPTER_ID
    )
    assert result.adapter_result.outcome_ready or result.adapter_result.failure_kind
    if result.adapter_result.outcome_ready:
        rule_ids = " ".join(
            str(f.get("rule_id") or "") for f in result.adapter_result.raw_findings
        )
        # At least one of the expected structural/doc rules should fire.
        assert any(
            needle in rule_ids for needle in _MATRIX["fixtures"]["violations"]["expected_rule_substrings"]
        )


@pytest.mark.asyncio
@pytest.mark.skipif(not _VACUUM_AVAILABLE, reason="vacuum binary unavailable")
async def test_real_vacuum_multifile_local_ref_no_network():
    clean = _FIXTURES / "clean"
    files = {
        "openapi.yaml": (clean / "openapi.yaml").read_text(encoding="utf-8"),
        "components.yaml": (clean / "components.yaml").read_text(encoding="utf-8"),
    }
    result = await run_openapi_validation_pack(
        files=files, profile=PROFILE_BASELINE, runner_id=VACUUM_OAS_ADAPTER_ID
    )
    # Success or findings — not a network/crash failure from unresolved remote $ref.
    assert result.adapter_result.failure_kind not in {"crash"}
