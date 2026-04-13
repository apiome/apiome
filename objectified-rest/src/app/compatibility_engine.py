"""
Pluggable compatibility check engine: deterministic classification, findings, and rule hit counts.

Wraps :func:`analyze_schema_compatibility` for use in REST routes and commit/merge pipelines.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .schema_compatibility import (
    CompatibilityFinding,
    CompatibilityRules,
    Overall,
    analyze_schema_compatibility,
)


def compat_report_fingerprint(
    overall: str,
    finding_dicts: List[Dict[str, Any]],
    deprecation_dicts: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Stable hash over sorted findings (and optional deprecation warnings) for audit/API identity.
    """
    payload: Dict[str, Any] = {
        "overall": overall,
        "findings": sorted(
            finding_dicts,
            key=lambda x: (x.get("path", ""), x.get("rule", ""), x.get("id", "")),
        ),
    }
    if deprecation_dicts:
        payload["deprecationWarnings"] = sorted(
            deprecation_dicts,
            key=lambda x: (x.get("revisionId", ""), x.get("role", "")),
        )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def rule_hits_from_findings(findings: List[CompatibilityFinding]) -> Dict[str, int]:
    """Count findings per rule id (deterministic key order when serialized via sorted())."""
    hits: Dict[str, int] = {}
    for f in findings:
        hits[f.rule] = hits.get(f.rule, 0) + 1
    return hits


@dataclass(frozen=True)
class CompatibilityCheckResult:
    """Output of :class:`CompatibilityCheckEngine` — suitable for APIs and audit payloads."""

    overall: Overall
    findings: Tuple[CompatibilityFinding, ...]
    rule_hits: Dict[str, int]
    report_fingerprint: str

    @property
    def finding_dicts(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": f.id,
                "path": f.path,
                "category": f.category,
                "rule": f.rule,
                "message": f.message,
            }
            for f in self.findings
        ]


class CompatibilityCheckEngine:
    """
    Pluggable rules via :class:`CompatibilityRules`; analysis is pure and deterministic
    (findings sorted by path, rule, message).
    """

    @staticmethod
    def run(
        base_spec: Dict[str, Any],
        head_spec: Dict[str, Any],
        rules: Optional[CompatibilityRules] = None,
    ) -> CompatibilityCheckResult:
        r = rules or CompatibilityRules()
        overall, findings_list = analyze_schema_compatibility(base_spec, head_spec, r)
        findings = tuple(findings_list)
        rh = rule_hits_from_findings(list(findings))
        fdicts = [
            {
                "id": f.id,
                "path": f.path,
                "category": f.category,
                "rule": f.rule,
                "message": f.message,
            }
            for f in findings
        ]
        fp = compat_report_fingerprint(overall, fdicts)
        return CompatibilityCheckResult(
            overall=overall,
            findings=findings,
            rule_hits=rh,
            report_fingerprint=fp,
        )


def compat_audit_detail(
    *,
    pipeline: str,
    base_revision_id: str,
    head_revision_id: str,
    result: CompatibilityCheckResult,
) -> Dict[str, Any]:
    """Structured ``workflow_audit.detail`` for persisted compatibility runs (#2589)."""
    return {
        "pipeline": pipeline,
        "baseRevisionId": base_revision_id,
        "headRevisionId": head_revision_id,
        "overall": result.overall,
        "ruleHits": dict(sorted(result.rule_hits.items())),
        "reportFingerprint": result.report_fingerprint,
        "findingCount": len(result.findings),
    }
