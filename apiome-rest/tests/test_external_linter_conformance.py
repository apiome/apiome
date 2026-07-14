"""Conformance tests for the external-linter adapter SPI (CLX-2.1, #4851).

Covers a fake tool (all success + failure modes → coverage evidence) and a gated
real-tool path through ``buf`` when the packaged binary is available.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Optional, Sequence, Tuple

import pytest

from app.external_linter_adapter import (
    BUF_LINT_ADAPTER_ID,
    BUF_LINT_SCANNER_ID,
    AdapterInput,
    BufLintAdapter,
    ExternalLinterAdapter,
    InputFormat,
    ScanMode,
    run_adapter,
)
from app.external_linter_parsers import (
    OUTPUT_FORMAT_JSONL,
    OUTPUT_FORMAT_SARIF,
)
from app.external_linter_runner import (
    FAILURE_CRASH,
    FAILURE_MALFORMED,
    FAILURE_TIMEOUT,
    FAILURE_UNAVAILABLE,
    RestrictedRunner,
)
from app.lint_evidence import (
    OUTCOME_FAILED,
    OUTCOME_FINDINGS,
    OUTCOME_PASSED,
    OUTCOME_UNAVAILABLE,
    SUBJECT_CATALOG_REVISION,
    coverage_entries,
)
from app.proto_descriptor import BUF_TOOL_KEY, ProtoFile
from app.proto_lint import run_buf_lint
from app.toolchain_packaging import probe_tool
from app.toolchain_runner import (
    ToolExecutionError,
    ToolNotAvailableError,
    ToolSpec,
    ToolTimeoutError,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "external_linter"
_PROTO_FIXTURES = Path(__file__).parent / "fixtures" / "proto"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# ===========================================================================
# Fake toolchain runner + FakeLinterAdapter (conformance only)
# ===========================================================================


@dataclass
class _FakeRunResult:
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    key: str = "fake-linter"
    argv: Optional[List[str]] = None
    duration_ms: int = 1


class _FakeToolchain:
    """Injectable toolchain double for RestrictedRunner."""

    def __init__(
        self,
        *,
        result: Optional[_FakeRunResult] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self._result = result if result is not None else _FakeRunResult()
        self._error = error
        self.calls: List[Dict[str, Any]] = []
        self.last_extra_env: Optional[Dict[str, str]] = None

    async def run_spec(
        self,
        spec: ToolSpec,
        args: Sequence[str] = (),
        *,
        stdin: Optional[str] = None,
        timeout: Optional[float] = None,
        cwd: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        policy: Any = None,
        **_: Any,
    ) -> _FakeRunResult:
        self.last_extra_env = dict(extra_env or {})
        self.calls.append(
            {
                "key": spec.key,
                "args": list(args),
                "stdin": stdin,
                "timeout": timeout,
                "cwd": cwd,
                "extra_env": dict(extra_env or {}),
            }
        )
        if self._error is not None:
            raise self._error
        return self._result


class FakeLinterAdapter(ExternalLinterAdapter):
    """Conformance-only adapter that echoes fixture corpus as SARIF or JSONL."""

    adapter_id: ClassVar[str] = "fake.linter"
    scanner_id: ClassVar[str] = "fake.linter"
    formats: ClassVar[Tuple[str, ...]] = (InputFormat.GENERIC, InputFormat.OPENAPI)
    scan_modes: ClassVar[Tuple[str, ...]] = (ScanMode.LINT,)
    tool_key: ClassVar[str] = "fake-linter"
    output_format: ClassVar[str] = OUTPUT_FORMAT_SARIF
    adapter_version: ClassVar[str] = "fake-linter/1"
    description: ClassVar[str] = "Conformance fake external linter"
    accept_exit_codes: ClassVar[Tuple[int, ...]] = ()

    def __init__(self, *, output_format: str = OUTPUT_FORMAT_SARIF) -> None:
        self.output_format = output_format  # type: ignore[misc]

    def tool_spec(self) -> ToolSpec:
        return ToolSpec(
            key=self.tool_key,
            executable="fake-linter",
            description=self.description,
            base_args=("lint",),
            parses_json=False,
        )

    def build_args(
        self, inputs: AdapterInput, *, workspace: Optional[str]
    ) -> Sequence[str]:
        _ = workspace
        mode = inputs.metadata.get("fixture", "findings.sarif.json")
        return ["--fixture", str(mode)]

    def stdin_for(self, inputs: AdapterInput) -> Optional[str]:
        return inputs.document


async def _run_fake(
    *,
    stdout: str = "",
    error: Optional[Exception] = None,
    output_format: str = OUTPUT_FORMAT_SARIF,
    document: str = "openapi: '3.0.0'\n",
    fixture_name: str = "findings.sarif.json",
) -> Any:
    inner = _FakeToolchain(
        result=_FakeRunResult(stdout=stdout),
        error=error,
    )
    runner = RestrictedRunner(inner=inner)  # type: ignore[arg-type]
    adapter = FakeLinterAdapter(output_format=output_format)
    return await run_adapter(
        adapter,
        AdapterInput(
            document=document,
            format=InputFormat.OPENAPI,
            scan_mode=ScanMode.LINT,
            metadata={"fixture": fixture_name},
        ),
        runner=runner,
    )


# ===========================================================================
# Fake tool — success paths
# ===========================================================================


async def test_fake_sarif_findings_become_evidence() -> None:
    result = await _run_fake(stdout=_load("findings.sarif.json"))
    assert result.outcome_ready
    assert result.failure_kind is None
    assert [f["rule_id"] for f in result.envelope_findings] == [
        "source-rule-alpha",
        "source-rule-beta",
    ]
    assert result.envelope_findings[0]["location"]["path"] == "openapi.yaml"
    assert result.envelope_findings[0]["location"]["start_line"] == 8

    evidence = result.to_evidence_run(subject_id="rev-1")
    assert evidence["scanner_id"] == "fake.linter"
    assert evidence["outcome"] == OUTCOME_FINDINGS
    assert evidence["coverage"]["state"] == "full"

    coverage = coverage_entries([evidence], ["fake.linter", "apiome.native-lint"])
    by_scanner = {e["scanner_id"]: e for e in coverage}
    assert by_scanner["fake.linter"]["outcome"] == OUTCOME_FINDINGS
    assert by_scanner["apiome.native-lint"]["outcome"] == "not_run"


async def test_fake_sarif_clean_passes() -> None:
    result = await _run_fake(stdout=_load("clean.sarif.json"))
    evidence = result.to_evidence_run(subject_id="rev-clean")
    assert evidence["outcome"] == OUTCOME_PASSED
    assert evidence["findings"] == []


async def test_fake_jsonl_findings_map_to_golden() -> None:
    result = await _run_fake(
        stdout=_load("findings.jsonl"),
        output_format=OUTPUT_FORMAT_JSONL,
        fixture_name="findings.jsonl",
    )
    golden = json.loads(_load("mapping_golden.json"))["jsonl_findings"]
    assert len(result.raw_findings) == len(golden)
    for actual, expected in zip(result.raw_findings, golden):
        assert actual["rule_id"] == expected["rule_id"]
        assert actual["path"] == expected["path"]
        assert actual["start_line"] == expected["start_line"]


# ===========================================================================
# Fake tool — failure modes → coverage evidence
# ===========================================================================


async def test_fake_unavailable_is_coverage_evidence() -> None:
    result = await _run_fake(error=ToolNotAvailableError("fake-linter", "fake-linter"))
    assert result.failure_kind == FAILURE_UNAVAILABLE
    evidence = result.to_evidence_run(subject_id="rev-u")
    assert evidence["outcome"] == OUTCOME_UNAVAILABLE
    assert evidence["coverage"]["state"] == "none"
    assert evidence["findings"] == []
    coverage = coverage_entries([evidence], ["fake.linter"])
    assert coverage[0]["outcome"] == OUTCOME_UNAVAILABLE


async def test_fake_timeout_is_coverage_evidence() -> None:
    result = await _run_fake(error=ToolTimeoutError("fake-linter", 1.0))
    assert result.failure_kind == FAILURE_TIMEOUT
    evidence = result.to_evidence_run(subject_id="rev-t")
    assert evidence["outcome"] == OUTCOME_FAILED
    assert evidence["coverage"]["failure_kind"] == FAILURE_TIMEOUT


async def test_fake_crash_is_coverage_evidence() -> None:
    result = await _run_fake(
        error=ToolExecutionError("fake-linter", 139, "", "Segmentation fault")
    )
    assert result.failure_kind == FAILURE_CRASH
    evidence = result.to_evidence_run(subject_id="rev-c")
    assert evidence["outcome"] == OUTCOME_FAILED
    assert evidence["coverage"]["state"] == "none"


async def test_fake_malformed_output_is_coverage_evidence() -> None:
    result = await _run_fake(stdout=_load("malformed.sarif.json"))
    assert result.failure_kind == FAILURE_MALFORMED
    evidence = result.to_evidence_run(subject_id="rev-m")
    assert evidence["outcome"] == OUTCOME_FAILED
    assert evidence["coverage"]["failure_kind"] == FAILURE_MALFORMED
    assert "diagnostics" in evidence["coverage"]


# ===========================================================================
# Real tool — gated Buf conformance
# ===========================================================================


_BUF_AVAILABLE = bool(getattr(probe_tool(BUF_TOOL_KEY), "available", False))


@pytest.mark.skipif(not _BUF_AVAILABLE, reason="bundled buf not resolvable in this environment")
async def test_real_buf_adapter_conformance() -> None:
    """Run BufLintAdapter against committed proto fixtures when buf is packaged."""
    proto_path = _PROTO_FIXTURES / "grpc" / "user" / "user.proto"
    if not proto_path.is_file():
        # Fallback: any single-file under fixtures/proto
        candidates = sorted(_PROTO_FIXTURES.rglob("*.proto"))
        assert candidates, "no proto fixtures available"
        proto_path = candidates[0]

    content = proto_path.read_text(encoding="utf-8")
    # Keep path module-relative (under a package folder when possible).
    rel = "user/user.proto"
    result = await run_adapter(
        BufLintAdapter(),
        AdapterInput(
            files={rel: content},
            format=InputFormat.PROTOBUF,
            scan_mode=ScanMode.LINT,
        ),
    )
    # Real buf may return findings or a clean pass; operational failure is not OK here.
    assert result.adapter_id == BUF_LINT_ADAPTER_ID
    assert result.scanner_id == BUF_LINT_SCANNER_ID
    assert result.failure_kind is None
    assert result.outcome_ready

    evidence = result.to_evidence_run(
        subject_type=SUBJECT_CATALOG_REVISION,
        subject_id="rev-buf-real",
    )
    assert evidence["scanner_id"] == BUF_LINT_SCANNER_ID
    assert evidence["outcome"] in (OUTCOME_PASSED, OUTCOME_FINDINGS)
    assert evidence["coverage"]["state"] == "full"

    # Bridge API still returns raw dicts.
    findings = await run_buf_lint([ProtoFile(path=rel, content=content)])
    assert isinstance(findings, list)


@pytest.mark.skipif(not _BUF_AVAILABLE, reason="bundled buf not resolvable in this environment")
async def test_real_buf_via_run_buf_lint() -> None:
    candidates = sorted(_PROTO_FIXTURES.rglob("*.proto"))
    assert candidates
    proto_path = candidates[0]
    findings = await run_buf_lint(
        [ProtoFile(path="sample.proto", content=proto_path.read_text(encoding="utf-8"))]
    )
    assert isinstance(findings, list)
