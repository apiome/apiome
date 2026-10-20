"""The ``a2a`` import-source adapter, its normalizer, lint pack and live discovery — MFI-18.1 (#3974)."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest

from app import ssrf_guard
from app.a2a_agent_card_discovery import (
    MAX_CARD_BYTES,
    A2aDiscoveryError,
    fetch_agent_card,
    well_known_agent_card_urls,
)
from app.a2a_agent_card_lint import lint_a2a_agent_card
from app.a2a_agent_card_parser import (
    A2aAgentCardParseError,
    is_a2a_agent_card,
    is_a2a_agent_card_document,
    parse_a2a_agent_card,
)
from app.a2a_import_source import A2aImportSource
from app.canonical_model import ApiParadigm, MessageRole, StreamingMode
from app.canonical_security import operation_security_schemes
from app.fileset import IntakeFileset
from app.format_version_coverage import version_coverage_for
from app.import_source import (
    DetectionInput,
    DiffChangeKind,
    ImportSourceError,
    InputKind,
    describe_import_sources,
    detect_import_source,
    get_import_source,
    load_builtin_import_sources,
)
from app.lint_engine import available_lint_formats
from app.normalizer import get_normalizer

load_builtin_import_sources()

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples/a2a"


def _read(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


_MINIMAL = _read("01-minimal-echo-agent.json")
_TYPICAL = _read("02-typical-travel-concierge.json")
_COMPOSITION = _read("03-composition-multi-interface-skill-auth.json")
_STRESS = _read("04-stress-edge-cases.json")
_REAL_WORLD = _read("05-real-world-georoute-planner.json")
_TYPICAL_V3 = _read("06-typical-travel-concierge-v3.json")


@pytest.fixture
def adapter() -> A2aImportSource:
    return A2aImportSource()


def _model(adapter: A2aImportSource, raw: str, **kwargs: Any):
    return adapter.normalize(adapter.parse(raw), **kwargs)


def _ops(model) -> Dict[str, Any]:
    return {op.extras["skill_id"]: op for op in model.services[0].operations}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_adapter_is_registered_under_a2a() -> None:
    source = get_import_source("a2a")
    assert source is not None
    assert source.key == "a2a"


def test_descriptor_advertises_live_discovery_and_agent_paradigm() -> None:
    descriptor = next(d for d in describe_import_sources() if d.key == "a2a")
    assert descriptor.paradigm is ApiParadigm.AGENT
    assert descriptor.supports_live_discovery is True
    assert descriptor.formats == ["a2a"]
    for kind in (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.DISCOVERY):
        assert kind in descriptor.input_kinds


def test_normalizer_and_lint_pack_are_registered() -> None:
    assert get_normalizer("a2a") is not None
    assert "a2a" in available_lint_formats()


def test_version_coverage_is_declared() -> None:
    assert version_coverage_for("a2a").reads


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw", [_MINIMAL, _TYPICAL, _COMPOSITION, _STRESS, _REAL_WORLD, _TYPICAL_V3]
)
def test_detect_claims_every_fixture(adapter: A2aImportSource, raw: str) -> None:
    result = adapter.detect(DetectionInput(text=raw))
    assert result.matched
    assert result.format == "a2a"
    assert result.confidence >= 0.9


def test_detect_reads_a_pre_parsed_document(adapter: A2aImportSource) -> None:
    result = adapter.detect(DetectionInput(document=json.loads(_TYPICAL)))
    assert result.confidence >= 0.9


def test_detect_falls_back_to_the_well_known_filename(adapter: A2aImportSource) -> None:
    for filename in ("agent-card.json", ".well-known/agent.json", "acme.agent-card.json"):
        result = adapter.detect(DetectionInput(text="{}", filename=filename))
        assert result.matched and result.confidence < 0.9


def test_registry_detection_routes_a_card_to_this_adapter() -> None:
    best = detect_import_source(DetectionInput(text=_TYPICAL))
    assert best is not None
    assert best[0].key == "a2a"


@pytest.mark.parametrize(
    "document",
    [
        {"openapi": "3.0.3", "info": {"title": "x", "version": "1"}, "paths": {}},
        {"mcpVersion": "2025-06-18", "name": "x", "skills": [], "capabilities": {}},
        [{"name": "lookup", "parameters": {"type": "object"}}],
        {"name": "Jane", "skills": [{"id": "python"}]},
        {"name": "x", "skills": ["not-an-object"], "capabilities": {}},
    ],
)
def test_detect_declines_look_alikes(adapter: A2aImportSource, document: Any) -> None:
    assert not is_a2a_agent_card_document(document)
    assert not adapter.detect(DetectionInput(text=json.dumps(document))).matched


def test_is_a2a_agent_card_never_raises_on_junk() -> None:
    for junk in ("", "   ", "not json", "\x00\x00", "[1, 2"):
        assert is_a2a_agent_card(junk) is False


def test_mcp_and_llm_tools_adapters_do_not_claim_a_card() -> None:
    for key in ("mcp", "llm-tools"):
        other = get_import_source(key)
        assert other is not None
        assert not other.detect(DetectionInput(text=_TYPICAL)).matched


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "INPUT_EMPTY"),
        ('{"name": "x", "skills": [],}', "INPUT_MALFORMED"),
        ('{"name": "x", "skills": [{"id": "a", "na', "INPUT_TRUNCATED"),
        ("openapi: 3.0.3\ninfo: {title: x, version: '1'}\npaths: {}\n", "FORMAT_MISMATCH"),
        ('{"openapi": "3.0.3", "skills": []}', "FORMAT_MISMATCH"),
        ('{"name": "x", "capabilities": {}}', "FORMAT_MISMATCH"),
        ("[1, 2, 3]", "FORMAT_MISMATCH"),
        ('{"skills": [], "capabilities": {}}', "INPUT_SEMANTIC_INVALID"),
        ('{"name": "x", "skills": {}}', "INPUT_SEMANTIC_INVALID"),
        ('{"name": "x", "skills": ["s"]}', "INPUT_SEMANTIC_INVALID"),
        ('{"name": "x", "skills": [{"id": "a"}]}', "INPUT_SEMANTIC_INVALID"),
        ('{"name": "x", "skills": [{"id": " ", "name": "A"}]}', "INPUT_SEMANTIC_INVALID"),
        ('{"name": "x\u0000", "skills": []}', "INPUT_ENCODING_INVALID"),
    ],
)
def test_parse_classifies_every_failure(raw: str, code: str) -> None:
    with pytest.raises(A2aAgentCardParseError) as excinfo:
        parse_a2a_agent_card(raw)
    assert excinfo.value.code == code


def test_adapter_parse_wraps_errors_with_the_taxonomy_code(adapter: A2aImportSource) -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse('{"name": "x", "skills": [],}', source_label="card.json")
    assert excinfo.value.code == "INPUT_MALFORMED"
    assert "card.json" in str(excinfo.value)


def test_parse_reads_card_fields() -> None:
    card = parse_a2a_agent_card(_COMPOSITION)
    assert card.name == "Ledger Assistant"
    assert card.version == "5.1.2"
    assert card.protocol_version == "0.3.0"
    assert card.provider is not None and card.provider.organization == "Example Bank"
    assert card.supports_authenticated_extended_card is True
    assert sorted(card.security_schemes) == ["bank_oidc", "partner_mtls"]
    assert card.security == (
        {"bank_oidc": ("openid", "accounts:read")},
        {"partner_mtls": ()},
    )
    # The primary url is repeated in additionalInterfaces; it is listed once.
    assert [(i.url.rsplit("/", 1)[-1], i.transport) for i in card.interfaces] == [
        ("jsonrpc", "JSONRPC"),
        ("grpc", "GRPC"),
        ("rest", "HTTP+JSON"),
    ]


def test_parse_tolerates_stress_corners() -> None:
    card = parse_a2a_agent_card(_STRESS)
    assert card.version == "7"  # a numeric version reads as text
    assert card.signature_count == 2
    assert card.default_input_modes == ()
    assert card.default_output_modes == ("text/plain",)  # deduplicated, blanks dropped
    ids = [skill.id for skill in card.skills]
    assert ids == ["restart-service", "restart-service", "42", "explain", "unicode-✓"]
    assert card.skills[0].tags == ("ops", "remediation")
    assert card.skills[3].security == ()  # an explicit empty list, not "inherit"
    assert card.skills[1].security is None


def test_parse_fileset_reads_the_root_member(adapter: A2aImportSource) -> None:
    fileset = IntakeFileset.from_members(
        {"agent-card.json": _MINIMAL, "README.md": "# notes"}, root="agent-card.json"
    )
    card = adapter.parse_fileset(fileset)
    assert card.name == "Echo Agent"


def test_parse_fileset_rejects_a_missing_root(adapter: A2aImportSource) -> None:
    fileset = IntakeFileset(members={"a.json": _MINIMAL}, root="b.json")
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(fileset)


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_rejects_a_foreign_ast(adapter: A2aImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.normalize({"name": "x"})


def test_the_agent_is_one_service_and_each_skill_an_operation(adapter: A2aImportSource) -> None:
    model = _model(adapter, _TYPICAL)
    assert model.paradigm is ApiParadigm.AGENT
    assert model.format == "a2a"
    assert model.protocol == "a2a"
    assert [s.name for s in model.services] == ["Travel Concierge"]
    assert sorted(_ops(model)) == [
        "build-itinerary",
        "search-flights",
        "search-hotels",
        "visa-requirements",
    ]
    assert model.services[0].operations[0].key.startswith("Travel Concierge.")


def test_identity_and_version_come_from_the_card(adapter: A2aImportSource) -> None:
    model = _model(adapter, _TYPICAL)
    assert model.identity.name == "Travel Concierge"
    assert model.identity.namespace == "Example Travel Co."
    assert model.identity.id == "https://travel.agents.example.com/a2a/v1"
    assert model.version == "2.4.0"
    assert model.extras["protocol_version"] == "0.3.0"


def test_skill_tags_become_operation_tags_and_are_rolled_up(adapter: A2aImportSource) -> None:
    model = _model(adapter, _TYPICAL)
    ops = _ops(model)
    assert ops["search-flights"].tags == ["travel", "flights", "search"]
    assert "visa" in model.extras["skill_tags"]
    assert model.extras["skill_count"] == 4


def test_modes_fall_back_to_card_defaults(adapter: A2aImportSource) -> None:
    ops = _ops(_model(adapter, _TYPICAL))
    flights = {m.role: m for m in ops["search-flights"].messages}
    assert flights[MessageRole.REQUEST].content_types == ["text/plain", "application/json"]
    itinerary = {m.role: m for m in ops["build-itinerary"].messages}
    assert itinerary[MessageRole.RESPONSE].content_types == ["application/json", "application/pdf"]
    assert ops["build-itinerary"].extras["input_modes"] == ["text/plain", "application/json"]


def test_streaming_capability_marks_skills_server_streaming(adapter: A2aImportSource) -> None:
    assert all(
        op.streaming is StreamingMode.SERVER for op in _ops(_model(adapter, _TYPICAL)).values()
    )
    assert all(
        op.streaming is StreamingMode.NONE for op in _ops(_model(adapter, _COMPOSITION)).values()
    )


def test_security_is_inherited_unless_the_skill_overrides(adapter: A2aImportSource) -> None:
    model = _model(adapter, _COMPOSITION)
    ops = _ops(model)
    assert ops["account-balance"].extras["security_source"] == "card"
    assert ops["account-balance"].extras["security_requirements"] == [
        {"bank_oidc": ["openid", "accounts:read"]},
        {"partner_mtls": []},
    ]
    assert ops["transfer-funds"].extras["security_source"] == "skill"
    assert ops["transfer-funds"].extras["security_requirements"] == [
        {"bank_oidc": ["openid", "payments:write"]}
    ]
    assert ops["transfer-funds"].extras["security"] == [
        {"scheme": "bank_oidc", "scopes": ["openid", "payments:write"]}
    ]
    # The shared reader every emitter uses sees a per-operation requirement.
    assert operation_security_schemes(model, ops["account-balance"]) == (
        ["bank_oidc", "partner_mtls"],
        "operation",
    )
    assert model.services[0].extras["security_schemes"]["partner_mtls"]["type"] == "mutualTLS"


def test_interfaces_become_servers_with_their_transport(adapter: A2aImportSource) -> None:
    model = _model(adapter, _COMPOSITION)
    assert sorted(server.protocol for server in model.servers) == ["GRPC", "HTTP+JSON", "JSONRPC"]


def test_a_repeated_skill_id_gets_a_distinct_key(adapter: A2aImportSource) -> None:
    ops = _model(adapter, _STRESS).services[0].operations
    repeats = [op for op in ops if op.extras["skill_id"] == "restart-service"]
    assert len(repeats) == 2
    assert len({op.key for op in repeats}) == 2
    second = next(op for op in repeats if "duplicate_of" in op.extras)
    assert second.key.endswith("~2")


def test_examples_are_kept(adapter: A2aImportSource) -> None:
    ops = _ops(_model(adapter, _REAL_WORLD))
    assert len(ops["custom-map-generator"].extras["examples"]) == 2


def test_include_raw_false_drops_the_fidelity_bag(adapter: A2aImportSource) -> None:
    assert _model(adapter, _MINIMAL).raw == {"a2a": json.loads(_MINIMAL)}
    assert _model(adapter, _MINIMAL, include_raw=False).raw is None


# ---------------------------------------------------------------------------
# Fingerprint and diff (versioning across releases)
# ---------------------------------------------------------------------------


def test_fingerprint_is_stable_and_order_invariant(adapter: A2aImportSource) -> None:
    first = adapter.fingerprint(_model(adapter, _TYPICAL))
    assert first == adapter.fingerprint(_model(adapter, _TYPICAL))
    reordered = json.loads(_TYPICAL)
    reordered["skills"] = list(reversed(reordered["skills"]))
    reordered = dict(reversed(list(reordered.items())))
    assert adapter.fingerprint(_model(adapter, json.dumps(reordered))) == first
    assert adapter.fingerprint(_model(adapter, _TYPICAL_V3)) != first


def test_diff_across_releases_surfaces_the_skill_delta(adapter: A2aImportSource) -> None:
    before = _model(adapter, _TYPICAL)
    after = _model(adapter, _TYPICAL_V3)
    diff = adapter.diff(before, after)

    def keys(kind: DiffChangeKind) -> set:
        return {e.key.split(".", 1)[1] for e in diff.of_kind(kind) if e.entity == "operation"}

    assert keys(DiffChangeKind.ADDED) == {"search-rail", "book-trip"}
    assert keys(DiffChangeKind.REMOVED) == {"visa-requirements"}
    # search-flights' description and tags changed; the auth change touches every
    # inherited skill too, so build-itinerary and search-hotels change as well.
    assert "search-flights" in keys(DiffChangeKind.CHANGED)
    services = [e for e in diff.entries if e.entity == "service"]
    assert [e.change for e in services] == [DiffChangeKind.CHANGED]


def test_an_auth_only_change_is_a_changed_service(adapter: A2aImportSource) -> None:
    card = json.loads(_MINIMAL)
    secured = dict(card)
    secured["securitySchemes"] = {"key": {"type": "apiKey", "in": "header", "name": "X-Key"}}
    diff = adapter.diff(
        _model(adapter, json.dumps(card)), _model(adapter, json.dumps(secured))
    )
    assert [(e.entity, e.change) for e in diff.entries] == [
        ("service", DiffChangeKind.CHANGED)
    ]


def test_identical_cards_have_an_empty_diff(adapter: A2aImportSource) -> None:
    assert adapter.diff(_model(adapter, _TYPICAL), _model(adapter, _TYPICAL)).is_empty


# ---------------------------------------------------------------------------
# Lint (capability / auth hygiene)
# ---------------------------------------------------------------------------


def test_clean_cards_raise_no_a2a_findings() -> None:
    for raw in (_TYPICAL, _COMPOSITION, _REAL_WORLD, _TYPICAL_V3):
        result = lint_a2a_agent_card(raw)
        assert not [f for f in result.findings if f.rule.startswith("a2a.")], raw[:40]


def test_the_stress_card_trips_every_hygiene_rule() -> None:
    rules = {f.rule for f in lint_a2a_agent_card(_STRESS).findings}
    assert {
        "a2a.security-undeclared-scheme",
        "a2a.unknown-scheme-type",
        "a2a.apikey-in-query",
        "a2a.insecure-endpoint",
        "a2a.skill-missing-description",
        "a2a.skill-missing-tags",
        "a2a.duplicate-skill-id",
        "a2a.skill-without-modes",
    } <= rules


def test_undeclared_scheme_is_reported_for_card_and_skill() -> None:
    messages = [
        f.message
        for f in lint_a2a_agent_card(_STRESS).findings
        if f.rule == "a2a.security-undeclared-scheme"
    ]
    assert any("'sso'" in m and m.startswith("Card") for m in messages)
    assert any("'break_glass'" in m and m.startswith("Skill") for m in messages)


def test_an_anonymous_card_is_flagged() -> None:
    rules = {f.rule for f in lint_a2a_agent_card(_MINIMAL).findings}
    assert "a2a.no-security" in rules


def test_missing_required_fields_are_flagged() -> None:
    card = {"name": "Bare", "skills": [{"id": "a", "name": "A", "tags": ["x"]}], "capabilities": {}}
    findings = [
        f for f in lint_a2a_agent_card(json.dumps(card)).findings
        if f.rule == "a2a.missing-required-field"
    ]
    assert sorted(f.path for f in findings) == [
        "defaultInputModes",
        "defaultOutputModes",
        "description",
        "url",
        "version",
    ]


def test_loopback_http_is_not_an_insecure_endpoint() -> None:
    card = json.loads(_MINIMAL)
    card["url"] = "http://localhost:9999/a2a"
    rules = {f.rule for f in lint_a2a_agent_card(json.dumps(card)).findings}
    assert "a2a.insecure-endpoint" not in rules


def test_adapter_lint_scores_the_model(adapter: A2aImportSource) -> None:
    report = adapter.lint(_model(adapter, _STRESS))
    assert report.score is not None and report.score < 100
    assert report.grade
    assert report.rule_hits.get("a2a.duplicate-skill-id") == 1


# ---------------------------------------------------------------------------
# Live discovery (well-known fetch)
# ---------------------------------------------------------------------------


#: What the SSRF guard sees a test hostname resolve to (there is no real DNS in CI).
_PUBLIC_IP = "93.184.216.34"


def _resolve_without_dns(host: str) -> list:
    """Resolve IP literals to themselves and every hostname to a public address."""
    try:
        return [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        return [_PUBLIC_IP]


@pytest.fixture(autouse=True)
def _no_dns():
    """Let the guarded client run against mock transports without resolving hostnames."""
    with patch.object(ssrf_guard, "_resolve_host_ips", _resolve_without_dns):
        yield


def _transport(routes: Dict[str, Any]) -> httpx.MockTransport:
    """Mock transport: ``url → body`` (200) or ``url → (status, body)``; anything else 404."""

    def handler(request: httpx.Request) -> httpx.Response:
        route = routes.get(str(request.url))
        if route is None:
            return httpx.Response(404, text="not found")
        status, body = route if isinstance(route, tuple) else (200, route)
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)


def test_well_known_urls_for_an_origin() -> None:
    assert well_known_agent_card_urls("https://Agent.example.com/some/path?q=1") == [
        "https://Agent.example.com/.well-known/agent-card.json",
        "https://Agent.example.com/.well-known/agent.json",
    ]


def test_well_known_urls_keep_a_direct_card_url() -> None:
    url = "https://agent.example.com/cards/v2/agent-card.json"
    assert well_known_agent_card_urls(url) == [url]


@pytest.mark.parametrize("bad", ["", "ftp://agent.example.com", "https://", "agent.example.com"])
def test_well_known_urls_reject_bad_input(bad: str) -> None:
    with pytest.raises(A2aDiscoveryError):
        well_known_agent_card_urls(bad)


def test_fetch_prefers_the_current_well_known_path() -> None:
    routes = {
        "https://agent.example.com/.well-known/agent-card.json": _TYPICAL,
        "https://agent.example.com/.well-known/agent.json": _MINIMAL,
    }
    with httpx.Client(transport=_transport(routes)) as client:
        fetched = fetch_agent_card("https://agent.example.com", client=client)
    assert fetched.url.endswith("/agent-card.json")
    assert fetched.text == _TYPICAL


def test_fetch_falls_back_to_the_legacy_path_on_404() -> None:
    routes = {"https://agent.example.com/.well-known/agent.json": _MINIMAL}
    with httpx.Client(transport=_transport(routes)) as client:
        fetched = fetch_agent_card("https://agent.example.com", client=client)
    assert fetched.url.endswith("/agent.json")


def test_fetch_does_not_fall_back_past_a_server_error() -> None:
    routes = {
        "https://agent.example.com/.well-known/agent-card.json": (401, "nope"),
        "https://agent.example.com/.well-known/agent.json": _MINIMAL,
    }
    with httpx.Client(transport=_transport(routes)) as client:
        with pytest.raises(A2aDiscoveryError, match="HTTP 401"):
            fetch_agent_card("https://agent.example.com", client=client)


def test_fetch_reports_when_no_card_exists() -> None:
    with httpx.Client(transport=_transport({})) as client:
        with pytest.raises(A2aDiscoveryError, match="No Agent Card found"):
            fetch_agent_card("https://agent.example.com", client=client)


def test_fetch_caps_the_body_size() -> None:
    routes = {"https://agent.example.com/.well-known/agent-card.json": "x" * (MAX_CARD_BYTES + 1)}
    with httpx.Client(transport=_transport(routes)) as client:
        with pytest.raises(A2aDiscoveryError, match="byte limit"):
            fetch_agent_card("https://agent.example.com", client=client)


def test_fetch_refuses_internal_addresses() -> None:
    with pytest.raises(A2aDiscoveryError):
        fetch_agent_card("http://127.0.0.1:8080")
    with pytest.raises(A2aDiscoveryError):
        fetch_agent_card("http://169.254.169.254/latest")


def test_introspect_discovers_parses_and_labels_the_card(adapter: A2aImportSource) -> None:
    routes = {"https://agent.example.com/.well-known/agent-card.json": _TYPICAL}
    with httpx.Client(transport=_transport(routes)) as client:
        card = adapter.introspect("https://agent.example.com", client=client)
    assert card.name == "Travel Concierge"
    assert card.source_label == "https://agent.example.com/.well-known/agent-card.json"
    assert len(_ops(adapter.normalize(card))) == 4


def test_introspect_wraps_discovery_and_parse_failures(adapter: A2aImportSource) -> None:
    with httpx.Client(transport=_transport({})) as client:
        with pytest.raises(ImportSourceError, match="No Agent Card found"):
            adapter.introspect("https://agent.example.com", client=client)
    routes = {"https://agent.example.com/.well-known/agent-card.json": "<html>hi</html>"}
    with httpx.Client(transport=_transport(routes)) as client:
        with pytest.raises(ImportSourceError) as excinfo:
            adapter.introspect("https://agent.example.com", client=client)
    assert excinfo.value.code in {"INPUT_MALFORMED", "FORMAT_MISMATCH"}


# ---------------------------------------------------------------------------
# Browse: the catalog item detail "Skills" group
# ---------------------------------------------------------------------------


def test_catalog_detail_lists_skills_with_their_tags(adapter: A2aImportSource) -> None:
    from app.catalog_parsed_model import derive_parsed_model

    groups = derive_parsed_model(_model(adapter, _TYPICAL))
    assert [g["title"] for g in groups] == ["Skills"]
    skills = {e["name"]: e for e in groups[0]["entities"]}
    assert len(skills) == 4
    flights = skills["Search flights"]
    assert flights["tag"] == "SKILL"
    assert flights["meta"] == "tags: travel, flights, search"
    rows = {row["name"]: row["type"] for row in flights["fields"]}
    assert rows["id"] == "search-flights"
    assert rows["input modes"] == "text/plain, application/json"
    assert rows["security"] == "concierge_oauth"
    assert rows["description"].startswith("Finds flights")


def test_catalog_detail_omits_empty_skill_facts(adapter: A2aImportSource) -> None:
    from app.catalog_parsed_model import derive_parsed_model

    groups = derive_parsed_model(_model(adapter, _STRESS))
    explain = next(e for e in groups[0]["entities"] if e["name"] == "Explain")
    assert explain["meta"] is None
    assert {row["name"] for row in explain["fields"]} == {"id", "examples", "output modes"}


def test_other_agent_formats_keep_the_generic_detail_view() -> None:
    from app.catalog_parsed_model import derive_parsed_model

    mcp = get_import_source("mcp")
    manifest = (
        Path(__file__).resolve().parents[2] / "apiome-ui/examples/mcp/01-minimal-echo-tool.json"
    ).read_text(encoding="utf-8")
    groups = derive_parsed_model(mcp.normalize(mcp.parse(manifest)))
    assert "Skills" not in [g["title"] for g in groups]
