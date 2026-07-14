"""GraphQL ESLint external-linter adapter (CLX-2.4, #4854).

Migrates the existing ``eslint_findings`` mapping in :mod:`app.graphql_lint` onto the
CLX-2.1 restricted adapter SPI so runs (including tool-unavailable) produce CLX-1.1
evidence. The ``graphql-eslint`` Node CLI is **not** bundled in the toolchain image in
this ticket — honest ``unavailable`` coverage is the default until a tool is provided
via ``APIOME_GRAPHQL_ESLINT_BIN`` or PATH.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import AbstractContextManager
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .external_linter_adapter import (
    AdapterInput,
    AdapterRunResult,
    ExternalLinterAdapter,
    InputFormat,
    ScanMode,
    run_adapter,
)
from .external_linter_parsers import (
    OUTPUT_FORMAT_JSON,
    NormalizedToolFinding,
    envelope_from_tool_finding,
)
from .external_linter_runner import RestrictedRunner, default_restricted_runner
from .graphql_lint import eslint_findings
from .schema_lint import LintFinding
from .toolchain_runner import ToolSpec

__all__ = [
    "GraphqlEslintAdapter",
    "GRAPHQL_ESLINT_ADAPTER_ID",
    "GRAPHQL_ESLINT_SCANNER_ID",
    "GRAPHQL_ESLINT_ADAPTER_VERSION",
    "GRAPHQL_ESLINT_TOOL_KEY",
    "run_graphql_eslint_via_adapter",
]

GRAPHQL_ESLINT_ADAPTER_ID = "graphql.eslint"
GRAPHQL_ESLINT_SCANNER_ID = "graphql.eslint"
GRAPHQL_ESLINT_ADAPTER_VERSION = "apiome-graphql-eslint/1"
GRAPHQL_ESLINT_TOOL_KEY = "graphql-eslint"
_ENV_BIN = "APIOME_GRAPHQL_ESLINT_BIN"


class GraphqlEslintAdapter(ExternalLinterAdapter, register=True):
    """``graphql-eslint`` via the restricted runner — authoritative GraphQL style rules."""

    adapter_id = GRAPHQL_ESLINT_ADAPTER_ID
    scanner_id = GRAPHQL_ESLINT_SCANNER_ID
    formats = (InputFormat.GRAPHQL,)
    scan_modes = (ScanMode.LINT,)
    tool_key = GRAPHQL_ESLINT_TOOL_KEY
    output_format = OUTPUT_FORMAT_JSON
    adapter_version = GRAPHQL_ESLINT_ADAPTER_VERSION
    description = (
        "graphql-eslint → findings over SDL (CLX-2.4); unavailable when the CLI is not installed."
    )

    def tool_spec(self) -> ToolSpec:
        executable = os.environ.get(_ENV_BIN) or "graphql-eslint"
        return ToolSpec(
            key=GRAPHQL_ESLINT_TOOL_KEY,
            executable=executable,
            description=self.description,
            base_args=(),
            default_timeout_seconds=60.0,
            env_override_keys=(_ENV_BIN,),
            parses_json=True,
        )

    def prepare_workspace(
        self, inputs: AdapterInput
    ) -> AbstractContextManager[Optional[str]]:
        sdl = _sdl_from_inputs(inputs)
        if not sdl.strip():
            raise ValueError("GraphqlEslintAdapter requires SDL in inputs.document or files")

        class _Scratch:
            def __enter__(self_inner) -> str:
                self_inner._tmp = tempfile.TemporaryDirectory(prefix="apiome-gql-eslint-")
                root = self_inner._tmp.__enter__()
                path = os.path.join(root, "schema.graphql")
                with open(path, "w", encoding="utf-8") as fh:
                    fh.write(sdl)
                self_inner.schema_path = path
                return root

            def __exit__(self_inner, *exc: Any) -> None:
                self_inner._tmp.__exit__(*exc)

        return _Scratch()

    def build_args(
        self, inputs: AdapterInput, *, workspace: Optional[str]
    ) -> Sequence[str]:
        _ = inputs
        if not workspace:
            raise ValueError("GraphqlEslintAdapter requires a materialized workspace")
        schema = os.path.join(workspace, "schema.graphql")
        # Prefer flat JSON for parsers; configs vary by CLI version.
        return [schema, "-f", "json"]

    def parse_output(self, stdout: str) -> List[NormalizedToolFinding]:
        if not (stdout or "").strip():
            return []
        data = json.loads(stdout)
        # Preserve ESLint file-result shape for eslint_findings.
        if isinstance(data, list):
            return list(data)  # type: ignore[return-value]
        if isinstance(data, dict):
            return [data]  # type: ignore[list-item]
        return []

    def map_lint_findings(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[LintFinding]:
        return eslint_findings(list(raw_findings))

    def map_envelope(
        self, raw_findings: Sequence[NormalizedToolFinding]
    ) -> List[Dict[str, Any]]:
        envelopes: List[Dict[str, Any]] = []
        for finding in eslint_findings(list(raw_findings)):
            envelopes.append(
                envelope_from_tool_finding(
                    {
                        "rule_id": finding.rule,
                        "message": finding.message,
                        "severity": finding.severity,
                        "path": finding.path,
                        "category": finding.category or "graphql-eslint",
                    },
                    default_severity=finding.severity,
                    category=finding.category or "graphql-eslint",
                )
            )
        return envelopes


def _sdl_from_inputs(inputs: AdapterInput) -> str:
    if isinstance(inputs.document, str) and inputs.document.strip():
        return inputs.document
    if inputs.files:
        parts = [inputs.files[k] for k in sorted(inputs.files)]
        return "\n".join(parts)
    return ""


async def run_graphql_eslint_via_adapter(
    sdl: str,
    *,
    runner: Any = None,
    timeout: Optional[float] = None,
    policy: Any = None,
) -> AdapterRunResult:
    """Run GraphQL ESLint through the SPI and return the full adapter result.

    Args:
        sdl: GraphQL SDL document text.
        runner: Optional restricted / toolchain runner.
        timeout: Optional timeout.
        policy: Optional sandbox policy.

    Returns:
        :class:`AdapterRunResult` (may carry ``failure_kind=unavailable``).
    """
    restricted: RestrictedRunner
    if runner is None:
        restricted = default_restricted_runner
    elif isinstance(runner, RestrictedRunner):
        restricted = runner
    else:
        restricted = RestrictedRunner(inner=runner)

    return await run_adapter(
        GraphqlEslintAdapter(),
        AdapterInput(
            document=sdl,
            format=InputFormat.GRAPHQL,
            scan_mode=ScanMode.LINT,
        ),
        runner=restricted,
        timeout=timeout,
        policy=policy,
    )
