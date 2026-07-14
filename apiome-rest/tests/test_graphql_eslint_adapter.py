"""Tests for the GraphQL ESLint adapter (CLX-2.4, #4854)."""

from __future__ import annotations

import pytest

from app.external_linter_adapter import available_adapters, get_adapter, load_builtin_adapters
from app.external_linter_runner import FAILURE_UNAVAILABLE
from app.graphql_eslint_adapter import (
    GRAPHQL_ESLINT_ADAPTER_ID,
    GraphqlEslintAdapter,
    run_graphql_eslint_via_adapter,
)
from app.lint_evidence import OUTCOME_UNAVAILABLE


@pytest.mark.asyncio
async def test_graphql_eslint_adapter_registered():
    load_builtin_adapters()
    assert GRAPHQL_ESLINT_ADAPTER_ID in available_adapters()
    assert get_adapter(GRAPHQL_ESLINT_ADAPTER_ID) is GraphqlEslintAdapter


@pytest.mark.asyncio
async def test_graphql_eslint_unavailable_without_cli():
    """Honest unavailable coverage when the Node CLI is not on PATH."""
    result = await run_graphql_eslint_via_adapter(
        "type Query { hello: String }",
    )
    assert result.failure_kind == FAILURE_UNAVAILABLE
    evidence = result.to_evidence_run(subject_id="00000000-0000-0000-0000-000000000001")
    assert evidence["scanner_id"] == "graphql.eslint"
    assert evidence["outcome"] == OUTCOME_UNAVAILABLE
    assert evidence["coverage"].get("state") == "none"


def test_map_lint_findings_reuses_eslint_findings():
    adapter = GraphqlEslintAdapter()
    raw = [
        {
            "filePath": "schema.graphql",
            "messages": [
                {
                    "ruleId": "@graphql-eslint/naming-convention",
                    "severity": 2,
                    "message": "bad name",
                    "line": 1,
                    "column": 2,
                }
            ],
        }
    ]
    findings = adapter.map_lint_findings(raw)
    assert len(findings) == 1
    assert findings[0].rule == "graphql.eslint.naming-convention"
    envelopes = adapter.map_envelope(raw)
    assert envelopes[0]["rule_id"] == "graphql.eslint.naming-convention"
