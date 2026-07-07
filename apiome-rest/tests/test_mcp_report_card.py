"""Tests for the MCP server report-card export (V2-MCP-33.1 / MCAT-19.1, #4650).

Two layers:

* **Renderer unit tests** exercise the pure :mod:`app.mcp_report_card` assembly + Markdown/HTML
  renderers directly — deterministic output, graceful partials, finding/change caps, and the
  invariant that no credential secret is ever emitted.
* **Route tests** drive ``GET …/endpoints/{id}/report`` against a mocked ``db`` (mirroring
  ``test_mcp_insight_routes.py``): format negotiation, ``Content-Disposition`` filenames,
  tenant-scoped ``404``, the graceful never-discovered partial, and end-to-end content assembled
  from the real surface-metrics / trust / lint layers over mocked rows.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication
from app.main import app
from app.mcp_license_signals import detect_license_signals
from app.mcp_report_card import (
    MAX_REPORT_CHANGES,
    MAX_REPORT_FINDINGS,
    build_report_card,
    render_report_html,
    render_report_markdown,
)

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 7, 6, 12, 0, 0, tzinfo=timezone.utc)
_GEN = "2026-07-07T00:00:00+00:00"

_EP = "11111111-1111-1111-1111-111111111111"
_V1 = "22222222-2222-2222-2222-222222222222"
_V2 = "33333333-3333-3333-3333-333333333333"

_ENDPOINT_ROW = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
    "category": "weather",
    "visibility": "private",
    "published": False,
    "description": "Weather tools for agents",
    "last_discovered_at": _NOW,
    "last_discovery_status": "success",
    "current_version_id": _V2,
}


def _version_row(version_id=_V2, seq=2, score=88, grade="B"):
    return {
        "id": version_id,
        "endpoint_id": _EP,
        "version_seq": seq,
        "version_tag": f"2026-07-06T{seq:02d}:00Z",
        "protocol_version": "2025-06-18",
        "server_name": "acme",
        "server_title": None,
        "server_version": "1.2.0",
        "instructions": None,
        "capabilities": {"tools": {"listChanged": True}},
        "surface_fingerprint": f"fp{seq}",
        "discovered_at": _NOW,
        "created_at": _NOW,
        "score": score,
        "grade": grade,
        "scored_at": _NOW,
        "added_count": 0,
        "removed_count": 0,
        "modified_count": 0,
        "total_count": 0,
    }


def _tool_row(name, *, required=None, destructive=False, ordinal=0):
    annotations = {"readOnlyHint": True}
    if destructive:
        annotations = {"destructiveHint": True}
    return {
        "version_id": _V2,
        "item_type": "tool",
        "name": name,
        "title": None,
        "description": "does a thing",
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "city name"},
                "units": {"type": "string", "enum": ["c", "f"]},
            },
            "required": required or [],
        },
        "output_schema": None,
        "annotations": annotations,
        "uri": None,
        "uri_template": None,
        "raw": {},
        "ordinal": ordinal,
    }


# ===========================================================================================
# Renderer unit tests (pure)
# ===========================================================================================


def _full_card():
    surface_metrics = {
        "type_counts": {
            "tools": 2,
            "resources": 1,
            "resource_templates": 0,
            "prompts": 1,
            "total": 4,
        },
        "tool_complexity": [
            {
                "property_count": 3,
                "required_count": 1,
                "max_nesting_depth": 2,
                "uses_enum": True,
                "has_output_schema": True,
            },
            {
                "property_count": 1,
                "max_nesting_depth": 0,
                "uses_enum": False,
                "has_output_schema": False,
            },
        ],
        "output_schema_count": 1,
        "annotation_coverage": {
            "tool_count": 2,
            "annotated_tools": 1,
            "read_only_hint": 1,
            "destructive_hint": 1,
            "idempotent_hint": 0,
            "open_world_hint": 0,
        },
        "documentation_coverage": {
            "item_count": 4,
            "described_items": 3,
            "titled_items": 2,
            "description_pct": 75.0,
            "title_pct": 50.0,
            "tool_param_count": 4,
            "documented_tool_params": 3,
            "tool_param_description_pct": 75.0,
        },
    }
    score_report = {
        "score": 88,
        "grade": "B",
        "severity_counts": {"error": 0, "warning": 2, "info": 1},
        "rule_hits": {"mcp-tool-name": 2},
        "findings": [
            {
                "rule": "mcp-tool-name",
                "severity": "warning",
                "message": "name too long | has pipe",
                "path": "tools/foo",
            }
        ],
    }
    trust = {
        "axes": [
            {"key": "safety", "label": "Safety", "value": None, "available": False, "detail": "n/a"},
            {
                "key": "quality",
                "label": "Quality",
                "value": 88.0,
                "available": True,
                "detail": "Grade B · 88/100",
            },
        ],
        "overall": 88.0,
        "available_count": 1,
        "axis_count": 5,
    }
    change_rows = [
        {"change_type": "added", "item_type": "tool", "item_name": "forecast"},
        {"change_type": "removed", "item_type": "prompt", "item_name": "old_prompt"},
    ]
    license_signals = detect_license_signals(
        instructions="Licensed under Apache-2.0. See https://acme.example/legal/terms.",
    ).as_dict()
    return build_report_card(
        endpoint=_ENDPOINT_ROW,
        version=_version_row(),
        is_current=True,
        score_report=score_report,
        surface_metrics=surface_metrics,
        license_signals=license_signals,
        trust_profile=trust,
        change_rows=change_rows,
        change_severity={"breaking": 1, "additive": 1, "review": 0, "total": 2},
        auth_posture="authenticated",
        auth_type="bearer",
        generated_at=_GEN,
    )


def test_markdown_full_report_has_every_section():
    md = render_report_markdown(_full_card())
    for heading in (
        "# MCP Server Report Card — Acme Weather",
        "## Identity",
        "## Grade & Score",
        "## Capability Surface",
        "## Safety Posture",
        "## Documentation Coverage",
        "## License & Terms",
        "## Trust Profile",
        "## Change Since Previous Version",
    ):
        assert heading in md
    assert "Grade B" in md and "88/100" in md
    # License signals itemize with their human kind labels.
    assert "| SPDX id | instructions | `Apache-2.0` |" in md
    assert "| Terms URL | instructions | `https://acme.example/legal/terms` |" in md
    # Pipes inside a cell are escaped so the table row stays intact.
    assert "name too long \\| has pipe" in md
    # Surface roll-up.
    assert "avg **2.0** properties" in md
    # Trust axes render canonical order (quality before safety) with a gap as n/a.
    q_idx = md.index("| Quality |")
    s_idx = md.index("| Safety |")
    assert q_idx < s_idx
    assert "| Safety | n/a |" in md
    # Change severity roll-up.
    assert "1 breaking · 1 additive · 0 review" in md


def test_html_full_report_is_self_contained_with_print_css():
    html = render_report_html(_full_card())
    assert html.startswith("<!doctype html>")
    assert "@media print" in html  # the PDF pathway
    assert "<style>" in html and "http://" not in html.split("<body")[0].replace(
        "mcp.acme.example", ""
    )
    # Grade badge class derives from the letter grade.
    assert "grade grade-b" in html
    assert "Acme Weather" in html and "forecast" in html
    # HTML-escaped finding message (the raw pipe is fine in HTML; angle brackets would be escaped).
    assert "name too long | has pipe" in html


def test_never_discovered_renders_graceful_partial():
    card = build_report_card(
        endpoint=_ENDPOINT_ROW,
        version=None,
        is_current=False,
        score_report=None,
        surface_metrics=None,
        trust_profile=None,
        change_rows=[],
        change_severity=None,
        auth_posture="anonymous",
        auth_type=None,
        generated_at=_GEN,
    )
    md = render_report_markdown(card)
    html = render_report_html(card)
    assert "never been discovered" in md
    assert "Not yet scored." in md
    assert "No discovered surface." in md
    assert "No trust signals available yet." in md
    assert "Not scanned — no discovered snapshot." in md
    # Still a complete document, every one of the eight H2 sections present.
    assert md.count("\n## ") == 8
    assert html.startswith("<!doctype html>") and "never been discovered" in html


def test_findings_and_changes_are_capped_with_explicit_overflow():
    findings = [
        {"rule": f"rule-{i}", "severity": "info", "message": f"m{i}", "path": f"p{i}"}
        for i in range(MAX_REPORT_FINDINGS + 5)
    ]
    changes = [
        {"change_type": "added", "item_type": "tool", "item_name": f"t{i}"}
        for i in range(MAX_REPORT_CHANGES + 7)
    ]
    card = build_report_card(
        endpoint=_ENDPOINT_ROW,
        version=_version_row(),
        is_current=True,
        score_report={
            "score": 50,
            "grade": "F",
            "severity_counts": {"error": 0, "warning": 0, "info": len(findings)},
            "rule_hits": {},
            "findings": findings,
        },
        surface_metrics=None,
        trust_profile=None,
        change_rows=changes,
        change_severity={"breaking": 0, "additive": len(changes), "review": 0, "total": len(changes)},
        auth_posture="anonymous",
        auth_type=None,
        generated_at=_GEN,
    )
    assert len(card.score.findings) == MAX_REPORT_FINDINGS
    assert card.score.findings_truncated == 5
    assert len(card.change.rows) == MAX_REPORT_CHANGES
    assert card.change.rows_truncated == 7
    md = render_report_markdown(card)
    assert "and 5 more finding(s) not shown" in md
    assert "and 7 more change(s) not shown" in md


def test_license_not_stated_renders_carefully_worded_absence():
    # A discovered snapshot whose text states nothing must render "not stated" — an explicit
    # result with a disclaimer — never a "no license" verdict (AC of V2-MCP-34.3).
    card = build_report_card(
        endpoint=_ENDPOINT_ROW,
        version=_version_row(),
        is_current=True,
        score_report=None,
        surface_metrics=None,
        license_signals=detect_license_signals(
            instructions="Use the forecast tool for weather."
        ).as_dict(),
        trust_profile=None,
        change_rows=[],
        change_severity=None,
        auth_posture="anonymous",
        auth_type=None,
        generated_at=_GEN,
    )
    assert card.license is not None
    assert card.license.status == "not_stated"
    md = render_report_markdown(card)
    html = render_report_html(card)
    for body in (md, html):
        assert "Not stated" in body
        assert "This is not a claim that the server has no license or terms." in body
        assert "not a compliance verdict" in body
    # The "never scanned" wording is reserved for a missing snapshot, not an empty result.
    assert "Not scanned — no discovered snapshot." not in md


def test_license_signals_render_in_html_table():
    html = render_report_html(_full_card())
    assert "<h2>License &amp; Terms</h2>" in html
    assert "<code>Apache-2.0</code>" in html
    assert "<td>SPDX id</td>" in html
    assert "informational" in html


def test_renderers_never_emit_a_credential_secret():
    # The report only ever receives an auth *posture* + auth_type label. Even if a caller passed a
    # secret-shaped auth_type, it is only rendered as a label, never as a secret; and there is no
    # field on the report that carries a secret at all.
    card = _full_card()
    md = render_report_markdown(card)
    html = render_report_html(card)
    # A representative secret string is never present because it never enters the model.
    secret = "sk-super-secret-token-value"
    assert secret not in md and secret not in html


# ===========================================================================================
# Route tests
# ===========================================================================================


@pytest.fixture(autouse=True)
def _default_auth():
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _mock_full_endpoint(mdb, *, score_report=True):
    """Wire a mocked ``db`` for a fully-discovered, scored endpoint on its current version."""
    mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
    mdb.get_mcp_endpoint_version.return_value = _version_row()
    mdb.get_mcp_capability_items.return_value = [
        _tool_row("forecast", required=["city"], ordinal=0),
        _tool_row("wipe", destructive=True, ordinal=1),
    ]
    mdb.get_mcp_version_score.return_value = (
        {
            "score": 88,
            "grade": "B",
            "report": {
                "score": 88,
                "grade": "B",
                "severity_counts": {"error": 0, "warning": 1, "info": 0},
                "rule_hits": {"mcp-tool-name": 1},
                "findings": [
                    {
                        "rule": "mcp-tool-name",
                        "severity": "warning",
                        "message": "tool name is terse",
                        "path": "tools/wipe",
                    }
                ],
            },
        }
        if score_report
        else None
    )
    mdb.get_mcp_endpoint_credentials.return_value = {"auth_type": "bearer"}
    mdb.get_mcp_evolution_series.return_value = [_version_row(_V1, 1), _version_row(_V2, 2)]
    mdb.get_mcp_version_changes_for_endpoint.return_value = []
    mdb.list_mcp_invocation_stats.return_value = []
    mdb.get_mcp_version_changes.return_value = [
        {"change_type": "added", "item_type": "tool", "item_name": "wipe"},
    ]


def test_report_markdown_default_format():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_full_endpoint(mdb)
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'filename="report-card-acme-weather-v2.md"' in r.headers["content-disposition"]
    body = r.text
    assert "# MCP Server Report Card — Acme Weather" in body
    assert "Grade B" in body
    assert "wipe" in body
    # Destructive tool detected via annotation.
    assert "Destructive-hint tools: **1**" in body


def test_report_html_format_and_filename():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_full_endpoint(mdb)
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report?format=html")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert 'filename="report-card-acme-weather-v2.html"' in r.headers["content-disposition"]
    assert r.text.startswith("<!doctype html>")
    assert "@media print" in r.text


def test_report_md_alias_accepted():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_full_endpoint(mdb)
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report?format=md")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")


def test_report_unknown_format_is_400():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report?format=pdf")
    assert r.status_code == 400


def test_report_cross_tenant_endpoint_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report")
    assert r.status_code == 404


def test_report_unknown_explicit_version_is_404():
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report?version_id={_V1}")
    assert r.status_code == 404


def test_report_never_discovered_is_graceful_partial():
    endpoint = dict(_ENDPOINT_ROW, current_version_id=None)
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = endpoint
        mdb.get_mcp_endpoint_credentials.return_value = None
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report")
    assert r.status_code == 200
    body = r.text
    assert "never been discovered" in body
    assert "Not yet scored." in body
    # Filename has no version segment when there is no snapshot.
    assert 'filename="report-card-acme-weather.md"' in r.headers["content-disposition"]


def test_report_discovered_but_unscored_partial():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_full_endpoint(mdb, score_report=False)
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report")
    assert r.status_code == 200
    body = r.text
    # Surface present, but the grade section degrades gracefully.
    assert "## Capability Surface" in body
    assert "Not yet scored." in body


def test_report_flags_seeded_license_hints_end_to_end():
    version = _version_row()
    version["instructions"] = (
        "This server is licensed under the MIT license. "
        "Terms of service: https://acme.example/tos."
    )
    version["server_branding"] = {"website_url": "https://acme.example/legal"}
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_full_endpoint(mdb)
        mdb.get_mcp_endpoint_version.return_value = version
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report")
    assert r.status_code == 200
    body = r.text
    assert "## License & Terms" in body
    assert "`MIT`" in body
    assert "`https://acme.example/tos`" in body
    # The branding website URL is classified too (a /legal page is a terms pointer).
    assert "| Terms URL | website_url | `https://acme.example/legal` |" in body
    assert "not a compliance verdict" in body


def test_report_license_absence_is_not_stated_never_no_license():
    # The default mocked version row advertises no instructions/title/branding at all.
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_full_endpoint(mdb)
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report")
    assert r.status_code == 200
    body = r.text
    assert "## License & Terms" in body
    assert "Not stated" in body
    assert "This is not a claim that the server has no license or terms." in body


def test_report_never_leaks_the_credential_secret():
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_full_endpoint(mdb)
        # Even if the credential row carried a secret, the route only reads auth_type.
        mdb.get_mcp_endpoint_credentials.return_value = {
            "auth_type": "bearer",
            "secret": "sk-super-secret-token-value",
        }
        r = client.get(f"/v1/mcp/acme/endpoints/{_EP}/report?format=html")
    assert r.status_code == 200
    assert "sk-super-secret-token-value" not in r.text
    # The posture/label still surfaces.
    assert "bearer" in r.text
