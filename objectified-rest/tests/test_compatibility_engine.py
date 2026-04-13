"""Compatibility check engine: rule hits, fingerprints, determinism (#2589)."""

import json

from src.app.compatibility_engine import (
    CompatibilityCheckEngine,
    compat_audit_detail,
    compat_report_fingerprint,
    rule_hits_from_findings,
)
from src.app.schema_compatibility import CompatibilityFinding, CompatibilityRules


def test_rule_hits_aggregation():
    f1 = CompatibilityFinding(
        path="p1", category="breaking", rule="schema_removed", message="m1"
    )
    f2 = CompatibilityFinding(
        path="p2", category="breaking", rule="schema_removed", message="m2"
    )
    f3 = CompatibilityFinding(path="p3", category="safe", rule="schema_added", message="m3")
    rh = rule_hits_from_findings([f1, f2, f3])
    assert rh["schema_removed"] == 2
    assert rh["schema_added"] == 1


def test_engine_deterministic_fingerprint():
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {},
        "components": {"schemas": {"A": {"type": "object", "properties": {"x": {"type": "string"}}}}},
    }
    head = json.loads(json.dumps(spec))
    head["components"]["schemas"]["A"]["properties"]["x"] = {"type": "integer"}
    r1 = CompatibilityCheckEngine.run(spec, head, CompatibilityRules())
    r2 = CompatibilityCheckEngine.run(spec, head, CompatibilityRules())
    assert r1.report_fingerprint == r2.report_fingerprint
    assert r1.overall == r2.overall
    assert [f.rule for f in r1.findings] == [f.rule for f in r2.findings]


def test_compat_audit_detail_sorted_rule_hits():
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {},
        "components": {"schemas": {}},
    }
    base = {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "1"},
        "paths": {},
        "components": {"schemas": {"Z": {"type": "string"}}},
    }
    r = CompatibilityCheckEngine.run(base, spec, CompatibilityRules())
    d = compat_audit_detail(
        pipeline="version.push",
        base_revision_id="a",
        head_revision_id="b",
        result=r,
    )
    keys = list(d["ruleHits"].keys())
    assert keys == sorted(keys)
    assert d["pipeline"] == "version.push"
    assert d["findingCount"] == len(r.findings)


def test_compat_report_fingerprint_matches_legacy_shape():
    overall = "safe"
    fds = [{"id": "i", "path": "/p", "category": "safe", "rule": "r", "message": "m"}]
    fp1 = compat_report_fingerprint(overall, fds, None)
    assert len(fp1) == 64
    fp2 = compat_report_fingerprint(overall, fds, None)
    assert fp1 == fp2
