"""API tests for MCP protocol-conformance & agent-readiness (CLX-3.1, #4855).

Covers the two routes the conformance engine is served through:

- ``GET /v1/mcp/conformance/rules`` — the rule catalog and its profiles, every rule citing the
  MCP specification revision it derives from and a resolvable reference.
- ``GET /v1/mcp/{slug}/endpoints/{id}/versions/{vid}/conformance`` — run and gate a profile over
  one stored snapshot, recomputed from the persisted surface plus the snapshot's stored redacted
  protocol transcript.

The route runs the *real* engine (:func:`app.mcp_conformance.run_conformance`) over a surface
reconstructed from mocked capability-item rows, so the score, gate, profile selection, and the
honesty guarantee — a transcript-backed rule with no transcript is reported as **skipped**, never
as a pass — are all verified end-to-end without a database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.auth import validate_authentication, validate_session_credentials
from app.main import app
from app.mcp_conformance import (
    MCP_SPEC_VERSION,
    PROFILE_FULL,
    PROFILE_PROTOCOL,
    PROFILE_READINESS,
    RULE_REGISTRY,
)
from app.mcp_protocol_transcript import TranscriptRecorder

client = TestClient(app)

_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}
_NOW = datetime(2026, 7, 14, 12, 0, 0, tzinfo=timezone.utc)

_EP = "11111111-1111-1111-1111-111111111111"
_V1 = "22222222-2222-2222-2222-222222222222"

_CONFORMANCE_URL = f"/v1/mcp/acme/endpoints/{_EP}/versions/{_V1}/conformance"
_RULES_URL = "/v1/mcp/conformance/rules"

#: The rule ids that can only be evaluated from a captured protocol transcript. Derived from the
#: registry rather than hardcoded, so a new transcript-backed rule is covered automatically.
_TRANSCRIPT_RULES = sorted(r.rule_id for r in RULE_REGISTRY.values() if r.requires_transcript)

_ENDPOINT_ROW = {
    "id": _EP,
    "tenant_id": "t1",
    "name": "Acme Weather",
    "slug": "acme-weather",
    "endpoint_url": "https://mcp.acme.example/mcp",
    "transport": "streamable_http",
    "visibility": "private",
    "published": False,
    "enabled": True,
    "current_version_id": _V1,
}


def _version_row(*, capabilities=None):
    """A row shaped like ``get_mcp_endpoint_version`` returns (identity fields only)."""
    return {
        "id": _V1,
        "endpoint_id": _EP,
        "version_seq": 3,
        "version_tag": "2026-07-14T12:00Z",
        "protocol_version": "2025-06-18",
        "server_name": "acme",
        "server_title": None,
        "server_version": "1.0.0",
        "instructions": None,
        # 'prompts' is declared but no prompt items are listed below, which is exactly the
        # deterministic, surface-derived protocol defect (protocol.declared-capability-empty)
        # the profile tests need — protocol findings that require no transcript.
        "capabilities": (
            {"tools": {"listChanged": True}, "prompts": {}}
            if capabilities is None
            else capabilities
        ),
        "surface_fingerprint": "fp1",
        "discovered_at": _NOW,
        "created_at": _NOW,
    }


def _tool_row(name, description, ordinal=0, *, input_schema=None, annotations=None):
    """A minimal ``mcp_capability_items`` row for a tool."""
    return {
        "version_id": _V1,
        "item_type": "tool",
        "name": name,
        "title": None,
        "description": description,
        "input_schema": input_schema or {"type": "object"},
        "output_schema": None,
        "annotations": annotations,
        "uri": None,
        "uri_template": None,
        "raw": {},
        "ordinal": ordinal,
    }


def _defective_tools():
    """Capability rows for a surface with agent-readiness defects at several severities.

    ``getWeather``'s description is far too brief for a model to select on (warning) and its
    ``q`` parameter is both undocumented (warning) and unconstrained (info); neither tool
    declares an output schema or behavioural annotations (info).
    """
    return [
        _tool_row(
            "getWeather",
            "Weather.",
            input_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        ),
        _tool_row("delete_all_records", "Delete.", ordinal=1),
    ]


def _transcript_dict():
    """A captured, redacted protocol transcript for the snapshot, as its stored dict payload.

    Built through the real :class:`~app.mcp_protocol_transcript.TranscriptRecorder`, so the
    payload the route reconstructs is exactly the shape discovery persists: the ``initialize``
    handshake plus a terminal ``tools/list`` page, both well-formed.
    """
    recorder = TranscriptRecorder()
    recorder.note_versions(requested="2025-06-18", negotiated="2025-06-18")
    recorder.record(
        "initialize",
        request_id=1,
        params={"protocolVersion": "2025-06-18"},
        http_status=200,
        envelope={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "acme", "version": "1.0.0"},
            },
        },
    )
    recorder.record(
        "tools/list",
        request_id=2,
        params={},
        http_status=200,
        envelope={
            "jsonrpc": "2.0",
            "id": 2,
            "result": {"tools": [{"name": "getWeather"}, {"name": "delete_all_records"}]},
        },
    )
    return recorder.transcript().as_dict()


@pytest.fixture(autouse=True)
def _default_auth():
    """Authenticate both dependencies the two routes use.

    The version-scoped conformance route is tenant-scoped (``validate_authentication``); the rules
    catalog is registry-level and takes no tenant, so it authenticates with
    ``validate_session_credentials`` — the same dependency ``GET /v1/lint/rules`` uses.
    """
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    app.dependency_overrides[validate_session_credentials] = lambda: _JWT_T1
    yield
    app.dependency_overrides.pop(validate_authentication, None)
    app.dependency_overrides.pop(validate_session_credentials, None)


def _mock_db(mdb, *, transcript=None, items=None, version=None):
    """Wire a patched ``app.mcp_catalog_routes.db`` for one conformance run."""
    mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
    mdb.get_mcp_endpoint_version.return_value = version or _version_row()
    mdb.get_mcp_capability_items.return_value = (
        _defective_tools() if items is None else items
    )
    mdb.get_mcp_protocol_transcript.return_value = (
        {"transcript": transcript} if transcript is not None else None
    )
    return mdb


# ===========================================================================
# GET /v1/mcp/conformance/rules — the rule catalog
# ===========================================================================


def test_rules_catalog_cites_a_spec_version_and_resolvable_reference_per_rule():
    """Every rule is attributable: it names the spec revision and a resolvable source URL."""
    r = client.get(_RULES_URL)
    assert r.status_code == 200
    body = r.json()
    assert body["specVersion"] == MCP_SPEC_VERSION
    assert len(body["rules"]) == len(RULE_REGISTRY)
    for rule in body["rules"]:
        assert rule["specVersion"], f"{rule['ruleId']} cites no spec version"
        assert rule["specReference"].startswith("https://"), rule["ruleId"]
        assert rule["rationale"].strip()
        assert rule["category"] in {"protocol", "readiness"}
        assert rule["severity"] in {"error", "warning", "info"}
        assert isinstance(rule["requiresTranscript"], bool)


def test_rules_catalog_lists_all_three_profiles():
    """The catalog advertises every gateable profile, with the categories each selects."""
    body = client.get(_RULES_URL).json()
    profiles = {p["profileId"]: p for p in body["profiles"]}
    assert set(profiles) == {PROFILE_FULL, PROFILE_PROTOCOL, PROFILE_READINESS}
    assert profiles[PROFILE_PROTOCOL]["categories"] == ["protocol"]
    assert profiles[PROFILE_READINESS]["categories"] == ["readiness"]
    assert sorted(profiles[PROFILE_FULL]["categories"]) == ["protocol", "readiness"]


def test_rules_catalog_filters_to_the_requested_profile():
    """``?profile=mcp-protocol`` narrows the catalog to that profile's rules only."""
    body = client.get(_RULES_URL, params={"profile": PROFILE_PROTOCOL}).json()
    assert body["rules"], "the protocol profile must select at least one rule"
    assert {rule["category"] for rule in body["rules"]} == {"protocol"}
    # Narrowing the catalog must not narrow the advertised profile list.
    assert len(body["profiles"]) == 3
    full = client.get(_RULES_URL).json()
    assert len(body["rules"]) < len(full["rules"])


def test_rules_catalog_rejects_unknown_profile():
    """A typo'd profile is a 400, never a silent fall back to the default rule set."""
    r = client.get(_RULES_URL, params={"profile": "nope"})
    assert r.status_code == 400
    assert "nope" in r.json()["detail"]


def test_rules_catalog_is_never_served_anonymously():
    """The catalog is authenticated: an anonymous caller gets a clean 401."""
    app.dependency_overrides.pop(validate_session_credentials, None)
    assert client.get(_RULES_URL).status_code == 401


def test_rules_catalog_needs_no_tenant_slug_query_parameter():
    """The registry-level catalog is reachable at its own URL, with no invented tenant.

    Regression guard. The route first authenticated with ``validate_authentication``, whose
    ``tenant_slug`` parameter is resolved from the *path* on tenant-scoped routes. This route has
    no ``{tenant_slug}`` segment, so FastAPI instead demanded it as a **query** parameter: the
    catalog answered 422 unless the caller made up a slug, and then authenticated against whatever
    they made up. Swapping to ``validate_session_credentials`` (what ``GET /v1/lint/rules`` uses)
    fixed it; this pins the plain URL working so it cannot regress.
    """
    r = client.get(_RULES_URL)
    assert r.status_code == 200
    assert r.json()["rules"]


# ===========================================================================
# The honesty guarantee — no transcript means skipped, never passed
# ===========================================================================


def test_conformance_without_transcript_skips_transcript_backed_rules():
    """With no stored transcript the transcript-backed rules are reported skipped, not passing.

    This is the load-bearing honesty guarantee: an unobserved protocol behaviour must never read
    as a clean one. Each skipped rule must therefore be absent from ``evaluatedRules``.
    """
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, transcript=None)
        r = client.get(_CONFORMANCE_URL)
    assert r.status_code == 200
    body = r.json()

    assert body["transcriptCaptured"] is False
    assert body["skippedRules"] == _TRANSCRIPT_RULES
    assert body["skippedRules"], "the engine has transcript-backed rules to skip"
    assert body["evaluatedRules"], "the surface-derived rules still run"
    assert not set(body["skippedRules"]) & set(body["evaluatedRules"])
    # And no finding may be attributed to a rule that was never evaluated.
    assert not {f["rule"] for f in body["findings"]} & set(body["skippedRules"])
    mdb.get_mcp_protocol_transcript.assert_called_once_with(_V1)


def test_conformance_with_transcript_evaluates_every_rule():
    """A stored transcript is loaded, so nothing is skipped and the run is fully evidenced."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb, transcript=_transcript_dict())
        r = client.get(_CONFORMANCE_URL)
    assert r.status_code == 200
    body = r.json()

    assert body["transcriptCaptured"] is True
    assert body["skippedRules"] == []
    # Every transcript-backed rule now moves into the evaluated set.
    assert set(_TRANSCRIPT_RULES) <= set(body["evaluatedRules"])
    assert set(body["evaluatedRules"]) == set(RULE_REGISTRY)


def test_conformance_report_identity_and_shape():
    """The report carries the snapshot's identity, the profile, and a cited spec revision."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        body = client.get(_CONFORMANCE_URL).json()

    assert body["endpointId"] == _EP
    assert body["versionId"] == _V1
    assert body["versionSeq"] == 3
    assert body["versionTag"] == "2026-07-14T12:00Z"
    assert body["profile"] == PROFILE_FULL
    assert body["specVersion"] == MCP_SPEC_VERSION
    assert 0 <= body["score"] <= 100
    assert body["grade"] in {"A", "B", "C", "D", "F"}
    assert body["reportFingerprint"]
    assert body["findings"], "the defective surface must itemize findings"
    assert sum(body["severityCounts"].values()) == len(body["findings"])
    assert sum(body["ruleHits"].values()) == len(body["findings"])


# ===========================================================================
# Gate
# ===========================================================================


def test_gate_fails_on_warning_for_a_defective_surface():
    """``?failOn=warning`` fails a surface whose tool definitions carry warning-level defects."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        body = client.get(_CONFORMANCE_URL, params={"failOn": "warning"}).json()

    warnings = [f for f in body["findings"] if f["severity"] == "warning"]
    assert warnings, "the fixture surface must produce warning-level findings"
    gate = body["gate"]
    assert gate["passed"] is False
    assert gate["failOn"] == "warning"
    assert gate["reasons"]
    assert "warning" in gate["reasons"][0]


def test_gate_none_passes_the_same_defective_surface():
    """``?failOn=none`` reports the same findings but never fails on severity alone."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        body = client.get(_CONFORMANCE_URL, params={"failOn": "none"}).json()

    assert body["findings"], "findings are still reported under failOn=none"
    assert body["gate"]["passed"] is True
    assert body["gate"]["failOn"] == "none"
    assert body["gate"]["reasons"] == []


def test_gate_min_score_floor_fails_with_a_score_reason():
    """``?minScore=100`` fails a defective surface, and says so as a *score* reason."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        body = client.get(
            _CONFORMANCE_URL, params={"failOn": "none", "minScore": 100}
        ).json()

    gate = body["gate"]
    assert body["score"] < 100
    assert gate["passed"] is False
    assert gate["minScore"] == 100
    assert len(gate["reasons"]) == 1
    assert f"score {body['score']} is below the required minimum of 100" in gate["reasons"][0]


def test_gate_rejects_unknown_fail_on():
    """An unrecognized ``failOn`` threshold is a 400, not a silent default."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        r = client.get(_CONFORMANCE_URL, params={"failOn": "bogus"})
    assert r.status_code == 400
    assert "bogus" in r.json()["detail"]


def test_conformance_rejects_unknown_profile():
    """An unknown ``?profile`` is a 400, so a CI typo never quietly changes what is gated."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        r = client.get(_CONFORMANCE_URL, params={"profile": "nope"})
    assert r.status_code == 400
    assert "nope" in r.json()["detail"]


# ===========================================================================
# Profile selection
# ===========================================================================


def test_protocol_profile_returns_only_protocol_findings():
    """``?profile=mcp-protocol`` evaluates and reports the protocol half only."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        body = client.get(_CONFORMANCE_URL, params={"profile": PROFILE_PROTOCOL}).json()

    assert body["profile"] == PROFILE_PROTOCOL
    assert body["findings"], "the fixture declares 'prompts' but lists none"
    assert {f["category"] for f in body["findings"]} == {"protocol"}
    assert all(rule.startswith("protocol.") for rule in body["evaluatedRules"])


def test_readiness_profile_returns_only_readiness_findings():
    """``?profile=mcp-agent-readiness`` evaluates and reports the tool-quality half only."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        body = client.get(_CONFORMANCE_URL, params={"profile": PROFILE_READINESS}).json()

    assert body["profile"] == PROFILE_READINESS
    assert body["findings"]
    assert {f["category"] for f in body["findings"]} == {"readiness"}
    assert all(rule.startswith("readiness.") for rule in body["evaluatedRules"])
    # Readiness rules are all surface-derived, so nothing is ever skipped for want of evidence.
    assert body["skippedRules"] == []


def test_profiles_partition_the_full_run():
    """The two half-profiles together account for exactly the full profile's findings."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        full = client.get(_CONFORMANCE_URL).json()
        protocol = client.get(
            _CONFORMANCE_URL, params={"profile": PROFILE_PROTOCOL}
        ).json()
        readiness = client.get(
            _CONFORMANCE_URL, params={"profile": PROFILE_READINESS}
        ).json()

    ids = lambda body: {f["id"] for f in body["findings"]}  # noqa: E731
    assert ids(protocol) | ids(readiness) == ids(full)
    assert not ids(protocol) & ids(readiness)
    # The same surface under a different profile is a different report.
    assert full["reportFingerprint"] != protocol["reportFingerprint"]


# ===========================================================================
# CI artifact formats
# ===========================================================================


def test_sarif_format_returns_a_sarif_run_not_the_json_model():
    """``?format=sarif`` returns a SARIF 2.1.0 document driven by the conformance scanner id."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        r = client.get(_CONFORMANCE_URL, params={"format": "sarif"})

    assert r.status_code == 200
    assert "sarif+json" in r.headers["content-type"]
    doc = json.loads(r.text)
    assert doc["version"] == "2.1.0"
    driver = doc["runs"][0]["tool"]["driver"]
    assert driver["name"] == "apiome.mcp-conformance"
    assert driver["rules"], "the defective surface must contribute SARIF rules"
    assert doc["runs"][0]["results"]
    # It is a SARIF document, not the JSON report model.
    assert "reportFingerprint" not in doc and "gate" not in doc


def test_junit_format_returns_xml_not_the_json_model():
    """``?format=junit`` returns a JUnit suite with a failure per error/warning finding."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        json_body = client.get(_CONFORMANCE_URL).json()
        r = client.get(_CONFORMANCE_URL, params={"format": "junit"})

    assert r.status_code == 200
    assert "xml" in r.headers["content-type"]
    assert r.text.lstrip().startswith("<?xml")
    assert "<testsuite" in r.text
    failing = sum(
        1 for f in json_body["findings"] if f["severity"] in ("error", "warning")
    )
    assert f'failures="{failing}"' in r.text
    assert f'tests="{len(json_body["findings"])}"' in r.text


# ===========================================================================
# Determinism & read-only contract
# ===========================================================================


def test_two_identical_gets_are_byte_stable():
    """The recompute is deterministic: an unchanged snapshot yields an identical report."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        first = client.get(_CONFORMANCE_URL).json()
        second = client.get(_CONFORMANCE_URL).json()

    assert first["reportFingerprint"] == second["reportFingerprint"]
    assert first == second


def test_conformance_get_is_read_only():
    """The GET recomputes and returns; it must persist nothing."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        assert client.get(_CONFORMANCE_URL).status_code == 200

        called = [call[0] for call in mdb.method_calls]

    assert called, "the route must have read the snapshot"
    written = [
        name
        for name in called
        if name.startswith(("set_", "record_", "create_", "update_", "insert_", "delete_"))
    ]
    assert written == []
    # Only the read accessors the recompute needs.
    assert set(called) == {
        "get_mcp_endpoint",
        "get_mcp_endpoint_version",
        "get_mcp_capability_items",
        "get_mcp_protocol_transcript",
    }


# ===========================================================================
# Tenant scoping and not-found
# ===========================================================================


def test_conformance_scoped_to_token_tenant_not_path_slug():
    """The endpoint is resolved against the caller's tenant, never the slug in the path."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        _mock_db(mdb)
        r = client.get(f"/v1/mcp/other-slug/endpoints/{_EP}/versions/{_V1}/conformance")
    assert r.status_code == 200
    mdb.get_mcp_endpoint.assert_called_once_with("t1", _EP)


def test_conformance_endpoint_404():
    """An endpoint outside the caller's tenant is a 404, and is never even read further."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = None
        r = client.get(_CONFORMANCE_URL)
    assert r.status_code == 404
    mdb.get_mcp_endpoint_version.assert_not_called()
    mdb.get_mcp_protocol_transcript.assert_not_called()


def test_conformance_version_404():
    """A version id that is not under the endpoint is a 404, with no conformance run."""
    with patch("app.mcp_catalog_routes.db") as mdb:
        mdb.get_mcp_endpoint.return_value = _ENDPOINT_ROW
        mdb.get_mcp_endpoint_version.return_value = None
        r = client.get(_CONFORMANCE_URL)
    assert r.status_code == 404
    mdb.get_mcp_capability_items.assert_not_called()
    mdb.get_mcp_protocol_transcript.assert_not_called()


def test_conformance_requires_authentication():
    app.dependency_overrides.pop(validate_authentication, None)
    assert client.get(_CONFORMANCE_URL).status_code == 401
