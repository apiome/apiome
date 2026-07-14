"""Spectral / Vacuum / Redocly OpenAPI adapters (CLX-2.2 / #4852).

Registers three external-linter adapters on the CLX-2.1 SPI. Each preserves
source rule IDs, locations, remediation links, and tool/version metadata in
normalized evidence. Commands run under the restricted no-network sandbox.
"""

from __future__ import annotations

import json
import tempfile
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Mapping, Optional, Sequence, Tuple

from .external_linter_adapter import (
    AdapterInput,
    ExternalLinterAdapter,
    InputFormat,
    ScanMode,
)
from .external_linter_parsers import (
    OUTPUT_FORMAT_JSON,
    OUTPUT_FORMAT_SARIF,
    AdapterOutputError,
    NormalizedToolFinding,
    envelope_from_tool_finding,
    parse_json_document,
    parse_sarif,
    parse_tool_output,
)
from .openapi_validation_profiles import (
    PROFILE_TENANT_GUIDE,
    custom_rules_from_guide_rows,
    normalize_profile,
    redocly_config_path,
    render_tenant_guide_spectral_ruleset,
    spectral_ruleset_path,
)
from .schema_lint import LintFinding, Severity
from .toolchain_runner import ToolSpec

__all__ = [
    "SPECTRAL_OAS_ADAPTER_ID",
    "VACUUM_OAS_ADAPTER_ID",
    "REDOCLY_OAS_ADAPTER_ID",
    "SpectralOasAdapter",
    "VacuumOasAdapter",
    "RedoclyOasAdapter",
    "parse_spectral_json_findings",
    "materialize_openapi_workspace",
]

SPECTRAL_OAS_ADAPTER_ID = "spectral.oas"
VACUUM_OAS_ADAPTER_ID = "vacuum.oas"
REDOCLY_OAS_ADAPTER_ID = "redocly.oas"

SPECTRAL_OAS_ADAPTER_VERSION = "apiome-spectral-oas/1"
VACUUM_OAS_ADAPTER_VERSION = "apiome-vacuum-oas/1"
REDOCLY_OAS_ADAPTER_VERSION = "apiome-redocly-oas/1"

_SPECTRAL_SEVERITY: Dict[int, Severity] = {
    0: "error",
    1: "warning",
    2: "info",
    3: "info",
}
_TEXT_SEVERITY: Dict[str, Severity] = {
    "error": "error",
    "warn": "warning",
    "warning": "warning",
    "info": "info",
    "hint": "info",
    "note": "info",
}

# Tools often exit 1 when emitting findings — still parseable.
_FINDINGS_EXIT = (1,)


def materialize_openapi_workspace(
    root: Path,
    inputs: AdapterInput,
    *,
    entry_name: str = "openapi.yaml",
) -> str:
    """Write OpenAPI inputs into ``root`` and return the entry document path.

    Prefers ``inputs.files`` (multi-file trees for local ``$ref``). Falls back to
    a single ``document`` written as ``entry_name``.
    """
    root.mkdir(parents=True, exist_ok=True)
    if inputs.files:
        for rel, content in inputs.files.items():
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        # Prefer common entry filenames when present.
        for candidate in (entry_name, "openapi.yaml", "openapi.yml", "openapi.json"):
            if (root / candidate).is_file():
                return str(root / candidate)
        # Otherwise first path sorted for determinism.
        first = sorted(inputs.files.keys())[0]
        return str(root / first)

    if inputs.document is None:
        raise ValueError("OpenAPI adapters require inputs.document or inputs.files")
    if isinstance(inputs.document, (dict, list)):
        text = json.dumps(inputs.document, indent=2, sort_keys=True)
        entry = root / "openapi.json"
    else:
        text = str(inputs.document)
        entry = root / entry_name
    entry.write_text(text, encoding="utf-8")
    return str(entry)


def _profile_from_inputs(inputs: AdapterInput) -> str:
    meta = inputs.metadata if isinstance(inputs.metadata, Mapping) else {}
    return normalize_profile(meta.get("profile") if meta else None)


def _severity_from(value: Any) -> Severity:
    if isinstance(value, int):
        return _SPECTRAL_SEVERITY.get(value, "info")
    if isinstance(value, str):
        return _TEXT_SEVERITY.get(value.lower(), "info")
    return "info"


def parse_spectral_json_findings(stdout: str) -> List[NormalizedToolFinding]:
    """Parse Spectral JSON / vacuum spectral-report stdout into normalized findings."""
    text = (stdout or "").strip()
    if not text:
        return []
    try:
        doc = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise AdapterOutputError(OUTPUT_FORMAT_JSON, f"JSON decode failed: {exc}") from exc

    rows: List[Any]
    if isinstance(doc, list):
        rows = doc
    elif isinstance(doc, dict):
        nested = doc.get("results") or doc.get("findings") or doc.get("issues")
        if isinstance(nested, list):
            rows = nested
        else:
            rows = [doc]
    else:
        raise AdapterOutputError(
            OUTPUT_FORMAT_JSON, f"expected object or array, got {type(doc).__name__}"
        )

    findings: List[NormalizedToolFinding] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("code") or item.get("ruleId") or item.get("rule")
        message = item.get("message") or ""
        severity = _severity_from(item.get("severity") if "severity" in item else item.get("level"))
        path_parts = item.get("path")
        if isinstance(path_parts, list):
            path = "/".join(str(p) for p in path_parts) or "(document)"
        else:
            path = str(item.get("source") or "(document)")
        start = (item.get("range") or {}).get("start") if isinstance(item.get("range"), dict) else {}
        finding: NormalizedToolFinding = {
            "rule_id": str(rule_id) if rule_id is not None else None,
            "message": str(message),
            "severity": severity,
            "path": path,
            "start_line": start.get("line") if isinstance(start, dict) else None,
            "start_column": start.get("character") if isinstance(start, dict) else None,
            "remediation": item.get("documentationUrl")
            or item.get("helpUrl")
            or item.get("helpUri"),
            "category": "spectral",
        }
        findings.append(finding)
    return findings


def _map_oas_lint_findings(
    raw_findings: Sequence[NormalizedToolFinding],
    *,
    prefix: str,
    category: str,
) -> List[LintFinding]:
    findings: List[LintFinding] = []
    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        rule = finding.get("rule_id") or finding.get("ruleId") or "unknown"
        path = finding.get("path") or "(document)"
        findings.append(
            LintFinding(
                path=str(path),
                category=category,
                rule=f"{prefix}.{rule}",
                severity=_severity_from(finding.get("severity")),
                message=str(finding.get("message") or ""),
            )
        )
    return findings


def _map_oas_envelope(
    raw_findings: Sequence[NormalizedToolFinding],
    *,
    category: str,
) -> List[Dict[str, Any]]:
    envelopes: List[Dict[str, Any]] = []
    for finding in raw_findings:
        if not isinstance(finding, dict):
            continue
        envelopes.append(envelope_from_tool_finding(finding, category=category))
    return envelopes


class _OasWorkspaceAdapter(ExternalLinterAdapter):
    """Shared workspace materialization for OpenAPI file trees."""

    formats: ClassVar[Tuple[str, ...]] = (InputFormat.OPENAPI,)
    scan_modes: ClassVar[Tuple[str, ...]] = (ScanMode.LINT,)
    accept_exit_codes: ClassVar[Tuple[int, ...]] = _FINDINGS_EXIT

    def prepare_workspace(
        self, inputs: AdapterInput
    ) -> AbstractContextManager[Optional[str]]:
        class _Scratch:
            def __enter__(self_inner) -> str:
                self_inner._tmp = tempfile.TemporaryDirectory(prefix="apiome-oas-lint-")
                root = Path(self_inner._tmp.__enter__())
                self_inner.entry = materialize_openapi_workspace(root, inputs)
                profile = _profile_from_inputs(inputs)
                meta = inputs.metadata if isinstance(inputs.metadata, Mapping) else {}
                if profile == PROFILE_TENANT_GUIDE:
                    custom = meta.get("custom_rules") if isinstance(meta.get("custom_rules"), Mapping) else None
                    if custom is None and isinstance(meta.get("guide_rows"), Sequence):
                        custom = custom_rules_from_guide_rows(meta["guide_rows"])  # type: ignore[arg-type]
                    overlay = render_tenant_guide_spectral_ruleset(
                        baseline_ruleset=spectral_ruleset_path(PROFILE_TENANT_GUIDE),
                        custom_rules=custom,
                        custom_rules_yaml=meta.get("custom_rules_yaml")
                        if isinstance(meta.get("custom_rules_yaml"), str)
                        else None,
                    )
                    (root / ".spectral.yaml").write_text(overlay, encoding="utf-8")
                    self_inner.spectral_ruleset = str(root / ".spectral.yaml")
                else:
                    self_inner.spectral_ruleset = str(spectral_ruleset_path(profile))
                # Copy curated redocly config into workspace so redocly resolves relative paths.
                redocly_src = redocly_config_path(profile)
                redocly_dst = root / "redocly.yaml"
                redocly_dst.write_text(redocly_src.read_text(encoding="utf-8"), encoding="utf-8")
                self_inner.redocly_config = str(redocly_dst)
                self_inner.root = str(root)
                return self_inner.root

            def __exit__(self_inner, *exc: Any) -> None:
                self_inner._tmp.__exit__(*exc)

        return _Scratch()


class SpectralOasAdapter(_OasWorkspaceAdapter, register=True):
    """``@stoplight/spectral-cli`` lint → SARIF (compatibility reference / default bulk)."""

    adapter_id = SPECTRAL_OAS_ADAPTER_ID
    scanner_id = SPECTRAL_OAS_ADAPTER_ID
    tool_key = "spectral"
    output_format = OUTPUT_FORMAT_SARIF
    adapter_version = SPECTRAL_OAS_ADAPTER_VERSION
    description = "Spectral OAS lint → SARIF under Apiome baseline/strict/tenant_guide profiles."
    formats = (InputFormat.OPENAPI, InputFormat.ASYNCAPI)

    def tool_spec(self) -> ToolSpec:
        from .toolchain_packaging import bundled_tool

        tool = bundled_tool("spectral")
        executable = tool.executable if tool is not None else "spectral"
        env_override_keys = (tool.env_override_key,) if tool is not None else ()
        default_timeout = tool.default_timeout_seconds if tool is not None else 60.0
        return ToolSpec(
            key="spectral",
            executable=executable,
            description=self.description,
            base_args=("lint",),
            default_timeout_seconds=default_timeout,
            env_override_keys=env_override_keys,
            parses_json=False,
        )

    def build_args(
        self, inputs: AdapterInput, *, workspace: Optional[str]
    ) -> Sequence[str]:
        if not workspace:
            raise ValueError("SpectralOasAdapter requires a materialized workspace")
        scratch = Path(workspace)
        entry = _entry_in_workspace(scratch, inputs)
        ruleset = scratch / ".spectral.yaml"
        if not ruleset.is_file():
            ruleset = Path(spectral_ruleset_path(_profile_from_inputs(inputs)))
        return [
            "-r",
            str(ruleset),
            "-f",
            "sarif",
            "-q",
            entry,
        ]

    def parse_output(self, stdout: str) -> List[NormalizedToolFinding]:
        return parse_sarif(stdout)

    def map_lint_findings(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[LintFinding]:
        return _map_oas_lint_findings(
            raw_findings, prefix="openapi.spectral", category="spectral"
        )

    def map_envelope(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[Dict[str, Any]]:
        return _map_oas_envelope(raw_findings, category="spectral")


class VacuumOasAdapter(_OasWorkspaceAdapter, register=True):
    """``vacuum spectral-report`` → Spectral JSON (bulk candidate / secondary evidence)."""

    adapter_id = VACUUM_OAS_ADAPTER_ID
    scanner_id = VACUUM_OAS_ADAPTER_ID
    tool_key = "vacuum"
    output_format = OUTPUT_FORMAT_JSON
    adapter_version = VACUUM_OAS_ADAPTER_VERSION
    description = "Vacuum OAS spectral-report → JSON under Apiome profiles."

    def tool_spec(self) -> ToolSpec:
        from .toolchain_packaging import bundled_tool

        tool = bundled_tool("vacuum")
        executable = tool.executable if tool is not None else "vacuum"
        env_override_keys = (tool.env_override_key,) if tool is not None else ()
        default_timeout = tool.default_timeout_seconds if tool is not None else 60.0
        return ToolSpec(
            key="vacuum",
            executable=executable,
            description=self.description,
            base_args=("spectral-report",),
            default_timeout_seconds=default_timeout,
            env_override_keys=env_override_keys,
            parses_json=False,
        )

    def build_args(
        self, inputs: AdapterInput, *, workspace: Optional[str]
    ) -> Sequence[str]:
        if not workspace:
            raise ValueError("VacuumOasAdapter requires a materialized workspace")
        scratch = Path(workspace)
        entry = _entry_in_workspace(scratch, inputs)
        ruleset = scratch / ".spectral.yaml"
        if not ruleset.is_file():
            ruleset = Path(spectral_ruleset_path(_profile_from_inputs(inputs)))
        # --remote=false keeps $ref resolution local; sandbox also blocks network.
        return [
            "-r",
            str(ruleset),
            "--remote=false",
            "--no-update-check",
            "-o",
            "-n",
            entry,
        ]

    def parse_output(self, stdout: str) -> List[NormalizedToolFinding]:
        return parse_spectral_json_findings(stdout)

    def map_lint_findings(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[LintFinding]:
        return _map_oas_lint_findings(
            raw_findings, prefix="openapi.vacuum", category="vacuum"
        )

    def map_envelope(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[Dict[str, Any]]:
        return _map_oas_envelope(raw_findings, category="vacuum")


class RedoclyOasAdapter(_OasWorkspaceAdapter, register=True):
    """``@redocly/cli lint`` → JSON (resolver + lint evidence)."""

    adapter_id = REDOCLY_OAS_ADAPTER_ID
    scanner_id = REDOCLY_OAS_ADAPTER_ID
    tool_key = "redocly"
    output_format = OUTPUT_FORMAT_JSON
    adapter_version = REDOCLY_OAS_ADAPTER_VERSION
    description = "Redocly OAS lint → JSON under Apiome baseline/strict profiles."

    def tool_spec(self) -> ToolSpec:
        from .toolchain_packaging import bundled_tool

        tool = bundled_tool("redocly")
        executable = tool.executable if tool is not None else "redocly"
        env_override_keys = (tool.env_override_key,) if tool is not None else ()
        default_timeout = tool.default_timeout_seconds if tool is not None else 60.0
        return ToolSpec(
            key="redocly",
            executable=executable,
            description=self.description,
            base_args=("lint",),
            default_timeout_seconds=default_timeout,
            env_override_keys=env_override_keys,
            parses_json=False,
        )

    def build_args(
        self, inputs: AdapterInput, *, workspace: Optional[str]
    ) -> Sequence[str]:
        if not workspace:
            raise ValueError("RedoclyOasAdapter requires a materialized workspace")
        scratch = Path(workspace)
        entry = _entry_in_workspace(scratch, inputs)
        config = scratch / "redocly.yaml"
        return [
            "--config",
            str(config),
            "--format=json",
            "--max-problems=500",
            entry,
        ]

    def parse_output(self, stdout: str) -> List[NormalizedToolFinding]:
        # Redocly JSON is typically { "<file>": [ { ruleId, message, severity, location }, … ] }
        text = (stdout or "").strip()
        if not text:
            return []
        try:
            doc = json.loads(text)
        except (ValueError, TypeError) as exc:
            raise AdapterOutputError(OUTPUT_FORMAT_JSON, f"JSON decode failed: {exc}") from exc

        findings: List[NormalizedToolFinding] = []
        if isinstance(doc, dict):
            for _file, issues in doc.items():
                if not isinstance(issues, list):
                    continue
                for item in issues:
                    if not isinstance(item, dict):
                        continue
                    loc = item.get("location") or []
                    path = "(document)"
                    start_line = None
                    start_column = None
                    if isinstance(loc, list) and loc:
                        first = loc[0] if isinstance(loc[0], dict) else {}
                        pointer = first.get("pointer") or first.get("path")
                        if pointer:
                            path = str(pointer)
                        report = first.get("reportOn") or first.get("source") or {}
                        if isinstance(report, dict):
                            start_line = report.get("start", {}).get("line") if isinstance(report.get("start"), dict) else report.get("line")
                            start_column = (
                                report.get("start", {}).get("column")
                                if isinstance(report.get("start"), dict)
                                else report.get("column")
                            )
                    findings.append(
                        {
                            "rule_id": item.get("ruleId") or item.get("rule"),
                            "message": str(item.get("message") or ""),
                            "severity": _severity_from(item.get("severity")),
                            "path": path,
                            "start_line": start_line,
                            "start_column": start_column,
                            "remediation": item.get("suggest")[0]
                            if isinstance(item.get("suggest"), list) and item.get("suggest")
                            else item.get("helpUrl"),
                            "category": "redocly",
                        }
                    )
            return findings
        return parse_tool_output(text, OUTPUT_FORMAT_JSON)

    def map_lint_findings(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[LintFinding]:
        return _map_oas_lint_findings(
            raw_findings, prefix="openapi.redocly", category="redocly"
        )

    def map_envelope(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[Dict[str, Any]]:
        return _map_oas_envelope(raw_findings, category="redocly")


def _entry_in_workspace(workspace: Path, inputs: AdapterInput) -> str:
    """Resolve the entry document path inside an already-materialized workspace."""
    for candidate in ("openapi.yaml", "openapi.yml", "openapi.json"):
        if (workspace / candidate).is_file():
            return str(workspace / candidate)
    if inputs.files:
        return str(workspace / sorted(inputs.files.keys())[0])
    if (workspace / "openapi.yaml").is_file():
        return str(workspace / "openapi.yaml")
    raise ValueError("No OpenAPI entry document in workspace")
