"""Engine tests for MCP trust-manifest drift, shadowing, and regression detection (CLX-3.4, #4858).

The acceptance criteria, made executable:

* **AC1/AC4** — a baseline→current diff classifies every material change as exactly one of normal /
  quality-regression / security-regression / coverage-loss, and each change carries old→new evidence.
* **AC3** — a tool name exposed by two enabled endpoints is detected as shadowing (same-host strongest).
* **AC5** — the manifest reuses the existing ``surface_fingerprint``; the fingerprint is stable across
  re-observations that only move volatile transport timing.
* The gate blocks on the *configured* risk deltas and is stable/deterministic.
"""

from __future__ import annotations

from app.mcp_client.handshake import ServerInfo
from app.mcp_client.normalize import CapabilityItem, DiscoverySurface
from app.mcp_trust_manifest import (
    DRIFT_COVERAGE_LOSS,
    DRIFT_NORMAL,
    DRIFT_QUALITY_REGRESSION,
    DRIFT_SECURITY_REGRESSION,
    GATE_BLOCKED,
    GATE_PASS,
    GATE_WARN,
    build_trust_manifest,
    detect_shadowed_names,
    diff_trust_manifests,
    shadow_report,
)


# --- Fixtures ------------------------------------------------------------------------------------


def _tool(name, *, annotations=None, input_schema=None, description="d", ordinal=0):
    return CapabilityItem(
        item_type="tool",
        name=name,
        ordinal=ordinal,
        description=description,
        input_schema=input_schema or {"type": "object", "properties": {}},
        annotations=annotations,
    )


def _tool_row(name, *, annotations=None):
    return {"item_type": "tool", "name": name, "annotations": annotations, "ordinal": 0}


def _surface(tools):
    return DiscoverySurface(
        protocol_version="2025-06-18",
        server_info=ServerInfo(name="acme", version="1.0.0"),
        tools=tuple(tools),
    )


def _endpoint(transport="streamable_http", metadata=None):
    return {"id": "ep1", "transport": transport, "transport_metadata": metadata}


def _version(fp="fp1"):
    return {
        "server_name": "acme",
        "server_title": None,
        "server_version": "1.0.0",
        "protocol_version": "2025-06-18",
        "surface_fingerprint": fp,
    }


def _ref(tag):
    return {"version_tag": tag}


# --- Manifest composition & fingerprint ----------------------------------------------------------


def test_manifest_reuses_surface_fingerprint_and_projects_authority():
    manifest = build_trust_manifest(
        endpoint_row=_endpoint(),
        version_row=_version("surface-abc"),
        capability_rows=[_tool_row("search", annotations={"readOnlyHint": True, "title": "S"})],
    )
    assert manifest.surface_fingerprint == "surface-abc"
    # Only authority annotations are projected — cosmetic 'title' is dropped.
    assert manifest.permissions == ({"name": "search", "annotations": {"readOnlyHint": True}},)
    assert manifest.fingerprint()  # deterministic, non-empty


def test_manifest_fingerprint_ignores_volatile_transport_timing():
    stable = build_trust_manifest(
        endpoint_row=_endpoint(metadata={"tls_issuer": "R3", "connect_latency_ms": 12}),
        version_row=_version(),
        capability_rows=[],
    )
    jittered = build_trust_manifest(
        endpoint_row=_endpoint(metadata={"tls_issuer": "R3", "connect_latency_ms": 900}),
        version_row=_version(),
        capability_rows=[],
    )
    assert stable.fingerprint() == jittered.fingerprint()
    # But a real TLS-issuer change does move it.
    changed = build_trust_manifest(
        endpoint_row=_endpoint(metadata={"tls_issuer": "EVIL", "connect_latency_ms": 12}),
        version_row=_version(),
        capability_rows=[],
    )
    assert changed.fingerprint() != stable.fingerprint()


# --- Drift classification (AC1/AC4) --------------------------------------------------------------


def _drift(baseline_tools, current_tools, *, baseline_ann=None, current_ann=None,
           baseline_sources=(), current_sources=(), gating=None):
    base_surface = _surface(
        [_tool(t, annotations=(baseline_ann or {}).get(t)) for t in baseline_tools]
    )
    cur_surface = _surface(
        [_tool(t, annotations=(current_ann or {}).get(t)) for t in current_tools]
    )
    # Use each surface's real fingerprint so identical surfaces compose identical manifests.
    baseline_manifest = build_trust_manifest(
        endpoint_row=_endpoint(),
        version_row=_version(base_surface.fingerprint()),
        capability_rows=[_tool_row(t, annotations=(baseline_ann or {}).get(t)) for t in baseline_tools],
        source_rows=baseline_sources,
    ).as_dict()
    current_manifest = build_trust_manifest(
        endpoint_row=_endpoint(),
        version_row=_version(cur_surface.fingerprint()),
        capability_rows=[_tool_row(t, annotations=(current_ann or {}).get(t)) for t in current_tools],
        source_rows=current_sources,
    )
    kwargs = dict(
        baseline_manifest=baseline_manifest,
        baseline_surface=base_surface,
        baseline_ref=_ref("v1"),
        current_manifest=current_manifest,
        current_surface=cur_surface,
        current_ref=_ref("v2"),
    )
    if gating is not None:
        kwargs["gating_categories"] = gating
    return diff_trust_manifests(**kwargs)


def test_removed_capability_is_coverage_loss():
    drift = _drift(["search", "delete_all"], ["search"])
    cats = {c.path: c.category for c in drift.changes}
    assert cats["tool:delete_all"] == DRIFT_COVERAGE_LOSS
    assert drift.category_counts[DRIFT_COVERAGE_LOSS] == 1


def test_added_capability_is_normal():
    drift = _drift(["search"], ["search", "list"])
    cats = {c.path: c.category for c in drift.changes}
    assert cats["tool:list"] == DRIFT_NORMAL


def test_permission_escalation_is_security_regression():
    drift = _drift(
        ["search"], ["search"],
        baseline_ann={"search": {"readOnlyHint": True}},
        current_ann={"search": {}},
    )
    change = next(c for c in drift.changes if c.path == "tool:search")
    assert change.category == DRIFT_SECURITY_REGRESSION
    assert "readOnlyHint" in change.summary


def test_becoming_destructive_is_security_regression():
    drift = _drift(
        ["run"], ["run"],
        baseline_ann={"run": {}},
        current_ann={"run": {"destructiveHint": True}},
    )
    change = next(c for c in drift.changes if c.path == "tool:run")
    assert change.category == DRIFT_SECURITY_REGRESSION


def test_breaking_schema_change_is_quality_regression():
    # A tool whose input schema tightens (a new required field) is a breaking, quality regression.
    base = build_trust_manifest(endpoint_row=_endpoint(), version_row=_version("b"),
                                capability_rows=[_tool_row("q")]).as_dict()
    cur = build_trust_manifest(endpoint_row=_endpoint(), version_row=_version("c"),
                               capability_rows=[_tool_row("q")])
    base_surface = _surface([_tool("q", input_schema={"type": "object", "properties": {}})])
    cur_surface = _surface([_tool(
        "q",
        input_schema={"type": "object", "properties": {"x": {"type": "string"}}, "required": ["x"]},
    )])
    drift = diff_trust_manifests(
        baseline_manifest=base, baseline_surface=base_surface, baseline_ref=_ref("v1"),
        current_manifest=cur, current_surface=cur_surface, current_ref=_ref("v2"),
    )
    change = next(c for c in drift.changes if c.path == "tool:q")
    assert change.category == DRIFT_QUALITY_REGRESSION


def test_every_change_carries_old_and_new_evidence():
    drift = _drift(["search", "delete_all"], ["search"])
    report = drift.as_dict()
    for change in report["changes"]:
        assert change["evidence"]["baseline"]["version_tag"] == "v1"
        assert change["evidence"]["current"]["version_tag"] == "v2"


# --- Source drift --------------------------------------------------------------------------------


def _source(locator, *, digest="d1", state="digest_pinned", sbom=None):
    return {
        "id": f"src-{locator}",
        "source_kind": "git",
        "locator": locator,
        "digest": digest,
        "digest_algorithm": "sha1",
        "verification_state": state,
        "provenance": "operator_declared",
    }


def test_source_verification_regression_is_security_regression():
    drift = _drift(
        ["s"], ["s"],
        baseline_sources=[_source("github.com/x")],
        current_sources=[_source("github.com/x", state="unverified")],
    )
    change = next(c for c in drift.changes if c.component == "source")
    assert change.category == DRIFT_SECURITY_REGRESSION


def test_retired_source_is_coverage_loss():
    drift = _drift(
        ["s"], ["s"],
        baseline_sources=[_source("github.com/x")],
        current_sources=[],
    )
    change = next(c for c in drift.changes if c.component == "source")
    assert change.category == DRIFT_COVERAGE_LOSS


def test_pinned_new_release_is_normal():
    drift = _drift(
        ["s"], ["s"],
        baseline_sources=[_source("github.com/x", digest="old")],
        current_sources=[_source("github.com/x", digest="new")],
    )
    change = next(c for c in drift.changes if c.component == "source")
    assert change.category == DRIFT_NORMAL


# --- Gate over configured risk deltas ------------------------------------------------------------


def test_gate_blocks_on_configured_category_and_passes_when_clean():
    blocked = _drift(["search", "delete_all"], ["search"])  # coverage loss (a default gating cat)
    assert blocked.gate.status == GATE_BLOCKED
    assert DRIFT_COVERAGE_LOSS in blocked.gate.blocking_categories

    clean = _drift(["search"], ["search", "list"])  # only an addition
    assert clean.gate.status == GATE_PASS


def test_gate_warns_when_regression_not_in_gating_set():
    # Restrict gating to security only; a coverage loss then warns rather than blocks.
    drift = _drift(["search", "delete_all"], ["search"], gating=[DRIFT_SECURITY_REGRESSION])
    assert drift.gate.status == GATE_WARN
    assert drift.has_regression


def test_identical_manifests_report_unchanged():
    drift = _drift(["search"], ["search"])
    assert drift.unchanged is True
    assert drift.gate.status == GATE_PASS


# --- Shadowing (AC3) -----------------------------------------------------------------------------


def _cap(endpoint_id, name, *, url, item_type="tool", ep_name=None):
    return {
        "endpoint_id": endpoint_id,
        "endpoint_name": ep_name or endpoint_id,
        "endpoint_slug": endpoint_id,
        "endpoint_url": url,
        "item_type": item_type,
        "name": name,
    }


def test_shadowed_tool_name_across_two_endpoints_is_detected():
    rows = [
        _cap("ep1", "search", url="https://a.example/mcp"),
        _cap("ep2", "search", url="https://b.example/mcp"),
        _cap("ep1", "only-here", url="https://a.example/mcp"),
    ]
    groups = detect_shadowed_names(rows)
    assert len(groups) == 1
    assert groups[0].name == "search"
    assert groups[0].host_scope == "cross_host"
    assert {e["id"] for e in groups[0].endpoints} == {"ep1", "ep2"}


def test_same_host_shadowing_is_flagged_stronger():
    rows = [
        _cap("ep1", "run", url="https://same.example/a"),
        _cap("ep2", "run", url="https://same.example/b"),
    ]
    report = shadow_report(rows)
    assert report["group_count"] == 1
    assert report["same_host_count"] == 1
    assert report["groups"][0]["host_scope"] == "same_host"


def test_single_endpoint_name_is_not_shadowing():
    rows = [
        _cap("ep1", "search", url="https://a.example/mcp"),
        _cap("ep1", "search", url="https://a.example/mcp"),  # same endpoint, counts once
    ]
    assert detect_shadowed_names(rows) == []
