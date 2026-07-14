"""oasdiff OpenAPI compatibility adapter (CLX-2.3 / #4853).

Runs ``oasdiff changelog`` under the CLX-2.1 restricted sandbox, normalizes
breaking / dangerous / informational deltas, and preserves source rule IDs plus
file/line locations from ``revisionSource`` / ``baseSource``.
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
    AdapterOutputError,
    NormalizedToolFinding,
    envelope_from_tool_finding,
)
from .openapi_validation_adapters import materialize_openapi_workspace
from .schema_lint import LintFinding, Severity
from .toolchain_runner import ToolSpec

__all__ = [
    "OASDIFF_ADAPTER_ID",
    "OASDIFF_ADAPTER_VERSION",
    "OASDIFF_SCANNER_ID",
    "CHANGE_CLASS_BREAKING",
    "CHANGE_CLASS_DANGEROUS",
    "CHANGE_CLASS_INFORMATIONAL",
    "OasdiffAdapter",
    "parse_oasdiff_changelog_json",
    "oasdiff_level_to_change_class",
    "oasdiff_level_to_severity",
    "render_oasdiff_changelog_markdown",
    "try_openapi_changes_html",
]

OASDIFF_ADAPTER_ID = "oasdiff.breaking"
OASDIFF_SCANNER_ID = OASDIFF_ADAPTER_ID
OASDIFF_ADAPTER_VERSION = "apiome-oasdiff/1"

CHANGE_CLASS_BREAKING = "breaking"
CHANGE_CLASS_DANGEROUS = "dangerous"
CHANGE_CLASS_INFORMATIONAL = "informational"

# oasdiff checker.Level: INFO=1, WARN=2, ERR=3
_LEVEL_INFO = 1
_LEVEL_WARN = 2
_LEVEL_ERR = 3

_FINDINGS_EXIT = (1,)


def oasdiff_level_to_change_class(level: Any) -> str:
    """Map an oasdiff numeric/string level to Apiome change class."""
    if isinstance(level, str):
        lowered = level.strip().lower()
        if lowered in ("err", "error", "3"):
            return CHANGE_CLASS_BREAKING
        if lowered in ("warn", "warning", "2"):
            return CHANGE_CLASS_DANGEROUS
        return CHANGE_CLASS_INFORMATIONAL
    try:
        numeric = int(level)
    except (TypeError, ValueError):
        return CHANGE_CLASS_INFORMATIONAL
    if numeric >= _LEVEL_ERR:
        return CHANGE_CLASS_BREAKING
    if numeric == _LEVEL_WARN:
        return CHANGE_CLASS_DANGEROUS
    return CHANGE_CLASS_INFORMATIONAL


def oasdiff_level_to_severity(level: Any) -> Severity:
    """Map oasdiff level → envelope severity (error/warning/info)."""
    change_class = oasdiff_level_to_change_class(level)
    if change_class == CHANGE_CLASS_BREAKING:
        return "error"
    if change_class == CHANGE_CLASS_DANGEROUS:
        return "warning"
    return "info"


def parse_oasdiff_changelog_json(stdout: str) -> List[NormalizedToolFinding]:
    """Parse ``oasdiff changelog --format json`` into normalized tool findings.

    Args:
        stdout: Raw JSON array (or ``{"changes": [...]}``) from oasdiff.

    Returns:
        Normalized findings with source rule id, severity, path, and line.

    Raises:
        AdapterOutputError: When stdout is not valid JSON of the expected shape.
    """
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
        nested = doc.get("changes") or doc.get("breakingChanges") or doc.get("items")
        if isinstance(nested, list):
            rows = nested
        else:
            raise AdapterOutputError(
                OUTPUT_FORMAT_JSON, "expected a JSON array or object with a changes list"
            )
    else:
        raise AdapterOutputError(
            OUTPUT_FORMAT_JSON, f"expected object or array, got {type(doc).__name__}"
        )

    findings: List[NormalizedToolFinding] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        rule_id = item.get("id") or item.get("ruleId") or item.get("rule")
        message = item.get("text") or item.get("message") or item.get("comment") or ""
        level = item.get("level")
        severity = oasdiff_level_to_severity(level)
        change_class = oasdiff_level_to_change_class(level)

        source = item.get("revisionSource") or item.get("baseSource") or {}
        if not isinstance(source, Mapping):
            source = {}
        file_path = source.get("file")
        api_path = item.get("path")
        operation = item.get("operation")
        section = item.get("section")
        if file_path:
            path = str(file_path)
        elif api_path and operation:
            path = f"{operation.upper()} {api_path}"
        elif api_path:
            path = str(api_path)
        elif section:
            path = str(section)
        else:
            path = "(document)"

        loc_parts: List[str] = []
        if operation and api_path:
            loc_parts.append(f"{str(operation).upper()} {api_path}")
        elif api_path:
            loc_parts.append(str(api_path))
        if loc_parts and message:
            # Keep operation context in the message when the location path is a file.
            pass

        fingerprint = item.get("fingerprint")
        finding: NormalizedToolFinding = {
            "rule_id": str(rule_id) if rule_id is not None else None,
            "message": str(message),
            "severity": severity,
            "path": path,
            "start_line": source.get("line") if isinstance(source.get("line"), int) else None,
            "start_column": source.get("column")
            if isinstance(source.get("column"), int)
            else None,
            "category": "compatibility",
            "change_class": change_class,
            "oasdiff_level": level,
            "operation": operation,
            "api_path": api_path,
            "section": section,
            "source_fingerprint": (
                str(fingerprint)
                if fingerprint
                else None
            ),
        }
        findings.append(finding)
    return findings


def _base_inputs_from_metadata(inputs: AdapterInput) -> AdapterInput:
    """Build an AdapterInput for the baseline revision from head-run metadata."""
    meta = inputs.metadata if isinstance(inputs.metadata, Mapping) else {}
    base_files = meta.get("base_files")
    base_document = meta.get("base_document")
    if isinstance(base_files, Mapping) and base_files:
        return AdapterInput(
            files={str(k): str(v) for k, v in base_files.items()},
            format=InputFormat.OPENAPI,
            scan_mode=ScanMode.BREAKING,
        )
    if base_document is not None:
        return AdapterInput(
            document=base_document,
            format=InputFormat.OPENAPI,
            scan_mode=ScanMode.BREAKING,
        )
    raise ValueError(
        "OasdiffAdapter requires metadata['base_document'] or metadata['base_files']"
    )


class OasdiffAdapter(ExternalLinterAdapter, register=True):
    """``oasdiff changelog`` → JSON under the restricted no-network sandbox."""

    adapter_id = OASDIFF_ADAPTER_ID
    scanner_id = OASDIFF_SCANNER_ID
    formats: ClassVar[Tuple[str, ...]] = (InputFormat.OPENAPI,)
    scan_modes: ClassVar[Tuple[str, ...]] = (ScanMode.BREAKING,)
    tool_key = "oasdiff"
    output_format = OUTPUT_FORMAT_JSON
    adapter_version = OASDIFF_ADAPTER_VERSION
    description = (
        "oasdiff OpenAPI compatibility changelog → JSON "
        "(breaking / dangerous / informational)."
    )
    accept_exit_codes: ClassVar[Tuple[int, ...]] = _FINDINGS_EXIT

    def tool_spec(self) -> ToolSpec:
        from .toolchain_packaging import bundled_tool

        tool = bundled_tool("oasdiff")
        executable = tool.executable if tool is not None else "oasdiff"
        env_override_keys = (tool.env_override_key,) if tool is not None else ()
        default_timeout = tool.default_timeout_seconds if tool is not None else 60.0
        return ToolSpec(
            key="oasdiff",
            executable=executable,
            description=self.description,
            base_args=("changelog",),
            default_timeout_seconds=default_timeout,
            env_override_keys=env_override_keys,
            parses_json=False,
        )

    def prepare_workspace(
        self, inputs: AdapterInput
    ) -> AbstractContextManager[Optional[str]]:
        class _Scratch:
            def __enter__(self_inner) -> str:
                self_inner._tmp = tempfile.TemporaryDirectory(prefix="apiome-oasdiff-")
                root = Path(self_inner._tmp.__enter__())
                base_root = root / "base"
                rev_root = root / "revision"
                base_inputs = _base_inputs_from_metadata(inputs)
                self_inner.base_entry = materialize_openapi_workspace(base_root, base_inputs)
                self_inner.rev_entry = materialize_openapi_workspace(rev_root, inputs)
                self_inner.root = str(root)
                return self_inner.root

            def __exit__(self_inner, *exc: Any) -> None:
                self_inner._tmp.__exit__(*exc)

        return _Scratch()

    def build_args(
        self, inputs: AdapterInput, *, workspace: Optional[str]
    ) -> Sequence[str]:
        if not workspace:
            raise ValueError("OasdiffAdapter requires a materialized workspace")
        root = Path(workspace)
        base_entry = _entry_under(root / "base")
        rev_entry = _entry_under(root / "revision")
        return [
            base_entry,
            rev_entry,
            "--format",
            "json",
            "--allow-external-refs=false",
        ]

    def parse_output(self, stdout: str) -> List[NormalizedToolFinding]:
        return parse_oasdiff_changelog_json(stdout)

    def map_envelope(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[Dict[str, Any]]:
        envelopes: List[Dict[str, Any]] = []
        for finding in raw_findings:
            if not isinstance(finding, dict):
                continue
            env = envelope_from_tool_finding(finding, category="compatibility")
            change_class = finding.get("change_class") or oasdiff_level_to_change_class(
                finding.get("oasdiff_level")
            )
            env["change_class"] = change_class
            # Keep operation+API path discoverable for UI deep links.
            location = dict(env.get("location") or {})
            if finding.get("api_path"):
                location["apiPath"] = finding["api_path"]
            if finding.get("operation"):
                location["operation"] = finding["operation"]
            if location:
                env["location"] = location
            envelopes.append(env)
        return envelopes

    def map_lint_findings(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[LintFinding]:
        findings: List[LintFinding] = []
        for finding in raw_findings:
            if not isinstance(finding, dict):
                continue
            rule = finding.get("rule_id") or "unknown"
            path = finding.get("api_path") or finding.get("path") or "(document)"
            op = finding.get("operation")
            if op and finding.get("api_path"):
                path = f"paths.{finding['api_path']}.{str(op).lower()}"
            findings.append(
                LintFinding(
                    path=str(path),
                    category="compatibility",
                    rule=f"oasdiff.{rule}",
                    severity=oasdiff_level_to_severity(finding.get("oasdiff_level")),
                    message=str(finding.get("message") or ""),
                )
            )
        return findings


def _entry_under(root: Path) -> str:
    for candidate in ("openapi.yaml", "openapi.yml", "openapi.json"):
        path = root / candidate
        if path.is_file():
            return str(path)
    files = sorted(p for p in root.rglob("*") if p.is_file())
    if not files:
        raise ValueError(f"No OpenAPI files under {root}")
    return str(files[0])


def _comparison_inputs(
    *,
    base_document: Any,
    revision_document: Any,
    base_files: Optional[Mapping[str, str]],
    revision_files: Optional[Mapping[str, str]],
) -> AdapterInput:
    meta: Dict[str, Any] = {}
    if base_files:
        meta["base_files"] = dict(base_files)
    else:
        meta["base_document"] = base_document
    return AdapterInput(
        document=None if revision_files else revision_document,
        files=dict(revision_files) if revision_files else {},
        format=InputFormat.OPENAPI,
        scan_mode=ScanMode.BREAKING,
        metadata=meta,
    )


async def _run_oasdiff_format(
    *,
    base_document: Any,
    revision_document: Any,
    base_files: Optional[Mapping[str, str]],
    revision_files: Optional[Mapping[str, str]],
    fmt: str,
) -> Optional[str]:
    """Invoke oasdiff changelog for a non-JSON format under the sandbox."""
    from .external_linter_adapter import run_adapter
    from .toolchain_packaging import probe_tool

    avail = probe_tool("oasdiff")
    if not getattr(avail, "available", False):
        return None

    class _FmtAdapter(OasdiffAdapter, register=False):
        def build_args(
            self, inputs: AdapterInput, *, workspace: Optional[str]
        ) -> Sequence[str]:
            if not workspace:
                raise ValueError("workspace required")
            root = Path(workspace)
            return [
                _entry_under(root / "base"),
                _entry_under(root / "revision"),
                "--format",
                fmt,
                "--allow-external-refs=false",
            ]

        def parse_output(self, stdout: str) -> List[NormalizedToolFinding]:
            _ = stdout
            return []

    inputs = _comparison_inputs(
        base_document=base_document,
        revision_document=revision_document,
        base_files=base_files,
        revision_files=revision_files,
    )
    try:
        result = await run_adapter(_FmtAdapter(), inputs)
    except Exception:  # noqa: BLE001
        return None
    text = (result.stdout or "").strip()
    return text or None


async def render_oasdiff_changelog_markdown(
    *,
    base_document: Any,
    revision_document: Any,
    base_files: Optional[Mapping[str, str]] = None,
    revision_files: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Best-effort markdown changelog from oasdiff for evidence retention."""
    return await _run_oasdiff_format(
        base_document=base_document,
        revision_document=revision_document,
        base_files=base_files,
        revision_files=revision_files,
        fmt="markdown",
    )


async def try_openapi_changes_html(
    *,
    base_document: Any,
    revision_document: Any,
    base_files: Optional[Mapping[str, str]] = None,
    revision_files: Optional[Mapping[str, str]] = None,
) -> Optional[str]:
    """Optional HTML changelog: openapi-changes when present, else oasdiff HTML."""
    from .external_linter_runner import RestrictedRunner
    from .toolchain_packaging import bundled_tool, probe_tool
    from .toolchain_runner import ToolSpec

    avail = probe_tool("openapi-changes")
    if not getattr(avail, "available", False):
        return await _run_oasdiff_format(
            base_document=base_document,
            revision_document=revision_document,
            base_files=base_files,
            revision_files=revision_files,
            fmt="html",
        )

    tool = bundled_tool("openapi-changes")
    executable = tool.executable if tool is not None else "openapi-changes"
    env_override_keys = (tool.env_override_key,) if tool is not None else ()
    head = _comparison_inputs(
        base_document=base_document,
        revision_document=revision_document,
        base_files=base_files,
        revision_files=revision_files,
    )
    adapter = OasdiffAdapter()
    try:
        with adapter.prepare_workspace(head) as workspace:
            if not workspace:
                return None
            root = Path(workspace)
            base_entry = _entry_under(root / "base")
            rev_entry = _entry_under(root / "revision")
            out_html = root / "changelog.html"
            spec = ToolSpec(
                key="openapi-changes",
                executable=executable,
                description="openapi-changes offline HTML changelog",
                base_args=(),
                env_override_keys=env_override_keys,
                parses_json=False,
            )
            runner = RestrictedRunner()
            await runner.run_spec(
                spec,
                [
                    "html",
                    "report",
                    base_entry,
                    rev_entry,
                    "-o",
                    str(out_html),
                ],
                cwd=workspace,
            )
            if out_html.is_file():
                return out_html.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 — optional renderer
        return await _run_oasdiff_format(
            base_document=base_document,
            revision_document=revision_document,
            base_files=base_files,
            revision_files=revision_files,
            fmt="html",
        )
    return None
