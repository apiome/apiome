"""The ``acp`` import-source adapter, its normalizer, lint pack and live discovery — MFI-18.2 (#3975)."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest

from app import ssrf_guard
from app.acp_agent_discovery import acp_agents_urls, fetch_acp_agents
from app.acp_agent_lint import lint_acp
from app.acp_agent_normalizer import acp_server_url
from app.acp_agent_parser import AcpParseError, is_acp_document, is_acp_manifest, parse_acp
from app.acp_import_source import AcpImportSource
from app.agent_descriptor_fetch import AgentDiscoveryError
from app.agent_paradigm_keys import unique_keys
from app.canonical_model import ApiParadigm, MessageRole
from app.catalog_parsed_model import derive_parsed_model
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

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples/acp"


def _read(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


_MINIMAL = _read("01-minimal-echo-agent.json")
_TYPICAL = _read("02-typical-research-agent.json")
_LIST = _read("03-composition-agent-list.json")
_STRESS = _read("04-stress-edge-cases.json")
_REAL_WORLD = _read("05-real-world-beeai-style-listing.json")
_TYPICAL_V2 = _read("06-typical-research-agent-v2.json")
_A2A_CARD = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/a2a/02-typical-travel-concierge.json"
).read_text(encoding="utf-8")


@pytest.fixture
def adapter() -> AcpImportSource:
    return AcpImportSource()


def _model(adapter: AcpImportSource, raw: str, **kwargs: Any):
    return adapter.normalize(adapter.parse(raw, source_label=kwargs.pop("label", None)), **kwargs)


def _services(model) -> Dict[str, Any]:
    return {service.name: service for service in model.services}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_adapter_is_registered_under_acp() -> None:
    source = get_import_source("acp")
    assert source is not None and source.key == "acp"


def test_descriptor_advertises_live_discovery_and_agent_paradigm() -> None:
    descriptor = next(d for d in describe_import_sources() if d.key == "acp")
    assert descriptor.paradigm is ApiParadigm.AGENT
    assert descriptor.supports_live_discovery is True
    assert descriptor.formats == ["acp"]
    for kind in (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.DISCOVERY):
        assert kind in descriptor.input_kinds


def test_normalizer_lint_pack_and_coverage_are_registered() -> None:
    assert get_normalizer("acp") is not None
    assert "acp" in available_lint_formats()
    assert version_coverage_for("acp").reads


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [_MINIMAL, _TYPICAL, _LIST, _STRESS, _REAL_WORLD, _TYPICAL_V2])
def test_detect_claims_every_fixture(adapter: AcpImportSource, raw: str) -> None:
    result = adapter.detect(DetectionInput(text=raw))
    assert result.matched and result.format == "acp" and result.confidence >= 0.9


def test_registry_detection_routes_manifests_and_listings_here() -> None:
    for raw in (_MINIMAL, _LIST):
        best = detect_import_source(DetectionInput(text=raw))
        assert best is not None and best[0].key == "acp"


def test_a2a_and_acp_do_not_claim_each_other() -> None:
    assert not get_import_source("acp").detect(DetectionInput(text=_A2A_CARD)).matched
    assert not get_import_source("a2a").detect(DetectionInput(text=_TYPICAL)).matched
    assert not get_import_source("a2a").detect(DetectionInput(text=_LIST)).matched


def test_detect_falls_back_to_the_acp_json_extension(adapter: AcpImportSource) -> None:
    result = adapter.detect(DetectionInput(text="{}", filename="research.acp.json"))
    assert result.matched and result.confidence < 0.9


@pytest.mark.parametrize(
    "document",
    [
        {"name": "x"},
        {"name": "x", "metadata": {"color": "blue"}},
        {"agents": []},
        {"agents": [{"name": "x"}]},
        {"agents": [{"name": "x", "input_content_types": []}], "next": "cursor"},
        {"openapi": "3.0.3", "name": "x", "input_content_types": []},
        {"name": "x", "skills": [], "input_content_types": []},
        [{"name": "x", "input_content_types": []}],
    ],
)
def test_detect_declines_look_alikes(document: Any) -> None:
    assert not is_acp_document(document)


def test_is_acp_manifest_never_raises_on_junk() -> None:
    for junk in ("", "  ", "not json", "\x00", "[1, 2"):
        assert is_acp_manifest(junk) is False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "INPUT_EMPTY"),
        ('{"name": "x", "input_content_types": [],}', "INPUT_MALFORMED"),
        ('{"name": "x", "description": "cut of', "INPUT_TRUNCATED"),
        ("openapi: 3.0.3\ninfo: {title: x, version: '1'}\npaths: {}\n", "FORMAT_MISMATCH"),
        ('{"title": "nothing here"}', "FORMAT_MISMATCH"),
        ("[1, 2]", "FORMAT_MISMATCH"),
        ('{"agents": []}', "INPUT_SEMANTIC_INVALID"),
        ('{"agents": {}}', "INPUT_SEMANTIC_INVALID"),
        ('{"agents": ["x"]}', "INPUT_SEMANTIC_INVALID"),
        ('{"agents": [{"description": "no name"}]}', "INPUT_SEMANTIC_INVALID"),
        ('{"name": " ", "input_content_types": []}', "INPUT_SEMANTIC_INVALID"),
        ('{"name": "x\u0000"}', "INPUT_ENCODING_INVALID"),
    ],
)
def test_parse_classifies_every_failure(raw: str, code: str) -> None:
    with pytest.raises(AcpParseError) as excinfo:
        parse_acp(raw)
    assert excinfo.value.code == code


def test_an_a2a_card_is_a_format_mismatch(adapter: AcpImportSource) -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(_A2A_CARD)
    assert excinfo.value.code == "FORMAT_MISMATCH"


def test_parse_reads_a_manifest() -> None:
    document = parse_acp(_TYPICAL)
    assert document.shape == "manifest"
    assert document.title == "research-assistant"
    agent = document.agents[0]
    assert [c.name for c in agent.capabilities] == ["Web search", "Summarize", "Cite sources"]
    assert agent.framework == "BeeAI"
    assert agent.natural_languages == ("en", "de")
    assert agent.author == {
        "name": "Example Research Team",
        "email": "research@example.com",
        "url": "https://example.com/research",
    }
    assert agent.dependencies[1] == {"type": "model", "name": "granite-3.3-8b-instruct"}
    assert agent.raw["status"]["success_rate"] == 97.2


def test_parse_reads_an_agent_list() -> None:
    document = parse_acp(_LIST, source_label="https://acp.example.com/agents")
    assert document.shape == "agent-list"
    assert [a.name for a in document.agents] == [
        "invoice-extractor",
        "currency-converter",
        "approval-router",
    ]
    assert document.title == "acp.example.com"
    assert parse_acp(_LIST, source_label="finance-agents.json").title == "finance-agents"


def test_parse_tolerates_stress_corners() -> None:
    agents = parse_acp(_STRESS).agents
    bad = agents[0]
    assert [c.name for c in bad.capabilities] == ["Anything", "Anything"]  # nameless/non-object dropped
    assert bad.tags == ("ops",)
    assert bad.input_content_types == ("*/*",) and bad.content_types_declared is False
    writer = agents[3]
    assert writer.author == {"email": "writer@example.com"}
    assert writer.links == (
        {"type": "homepage"},
        {"type": "container-image", "url": "ghcr.io/example/writer:1.2"},
    )
    assert agents[2].output_content_types == ("*/*",) and agents[2].content_types_declared


def test_parse_fileset_reads_the_root(adapter: AcpImportSource) -> None:
    fileset = IntakeFileset.from_members({"agents.json": _LIST, "README.md": "#"}, root="agents.json")
    assert len(adapter.parse_fileset(fileset).agents) == 3
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(members={"a.json": _LIST}, root="b.json"))


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_rejects_a_foreign_ast(adapter: AcpImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.normalize({"name": "x"})


def test_each_agent_is_a_service_and_each_capability_an_operation(adapter: AcpImportSource) -> None:
    model = _model(adapter, _LIST)
    assert model.paradigm is ApiParadigm.AGENT and model.format == "acp" and model.protocol == "acp"
    services = _services(model)
    assert sorted(services) == ["approval-router", "currency-converter", "invoice-extractor"]
    ops = {op.name: op for op in services["invoice-extractor"].operations}
    assert sorted(ops) == ["Extract fields", "Extract line items"]
    assert ops["Extract fields"].key == "invoice-extractor.Extract fields"
    assert ops["Extract fields"].tags == ["ocr", "extraction"]
    request = next(m for m in ops["Extract fields"].messages if m.role is MessageRole.REQUEST)
    assert request.content_types == ["application/pdf", "image/png", "image/jpeg"]
    assert model.extras["agent_count"] == 3
    assert model.extras["capability_count"] == 5
    assert model.extras["domains"] == ["accounts-payable", "finance", "workflow"]


def test_agent_metadata_lives_on_the_service(adapter: AcpImportSource) -> None:
    service = _model(adapter, _TYPICAL).services[0]
    assert service.description.startswith("Researches")
    assert service.extras["framework"] == "BeeAI"
    assert service.extras["license"] == "Apache-2.0"
    assert service.extras["recommended_models"][0] == "granite-3.3-8b-instruct"


def test_runtime_status_and_timestamps_are_not_normalized(adapter: AcpImportSource) -> None:
    model = _model(adapter, _TYPICAL)
    dumped = json.dumps(model.model_dump(mode="json", exclude={"raw"}))
    assert "avg_run_tokens" not in dumped
    assert "2026-09-14" not in dumped
    assert model.raw["acp"]["status"]["avg_run_tokens"] == 4120


def test_a_live_listing_gives_the_model_its_server(adapter: AcpImportSource) -> None:
    model = _model(adapter, _LIST, label="https://acp.example.com/api/agents")
    assert [s.url for s in model.servers] == ["https://acp.example.com/api"]
    assert _model(adapter, _LIST, label="agents.json").servers == []


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("https://acp.example.com/agents", "https://acp.example.com"),
        ("https://acp.example.com/v1/agents/", "https://acp.example.com/v1"),
        ("https://acp.example.com/agents/chat", "https://acp.example.com"),
        ("https://acp.example.com/other", None),
        ("agents.json", None),
        (None, None),
    ],
)
def test_acp_server_url(label: Any, expected: Any) -> None:
    assert acp_server_url(label) == expected


def test_repeated_agent_and_capability_names_keep_both(adapter: AcpImportSource) -> None:
    model = _model(adapter, _STRESS)
    keys = sorted(service.key for service in model.services)
    assert "wildcard" in keys and "wildcard~2" in keys
    bad = next(s for s in model.services if s.name == "Bad Name_With Spaces")
    assert sorted(op.key for op in bad.operations) == [
        "Bad Name_With Spaces.Anything",
        "Bad Name_With Spaces.Anything~2",
    ]


def test_unique_keys() -> None:
    assert unique_keys(["a", "b", "a", "a"]) == [
        ("a", None),
        ("b", None),
        ("a~2", "a"),
        ("a~3", "a"),
    ]


# ---------------------------------------------------------------------------
# Fingerprint and diff
# ---------------------------------------------------------------------------


def test_fingerprint_ignores_runtime_status_and_order(adapter: AcpImportSource) -> None:
    base = adapter.fingerprint(_model(adapter, _TYPICAL))
    redeployed = json.loads(_TYPICAL)
    redeployed["status"] = {"avg_run_tokens": 9999, "success_rate": 12.0}
    redeployed["metadata"]["updated_at"] = "2027-01-01T00:00:00Z"
    redeployed["metadata"]["capabilities"].reverse()
    redeployed = dict(reversed(list(redeployed.items())))
    assert adapter.fingerprint(_model(adapter, json.dumps(redeployed))) == base
    assert adapter.fingerprint(_model(adapter, _TYPICAL_V2)) != base


def test_diff_across_releases_surfaces_the_capability_delta(adapter: AcpImportSource) -> None:
    diff = adapter.diff(_model(adapter, _TYPICAL), _model(adapter, _TYPICAL_V2))

    def ops(kind: DiffChangeKind) -> set:
        return {e.key.split(".", 1)[1] for e in diff.of_kind(kind) if e.entity == "operation"}

    assert ops(DiffChangeKind.ADDED) == {"Read PDFs"}
    assert ops(DiffChangeKind.REMOVED) == {"Cite sources"}
    assert "Summarize" in ops(DiffChangeKind.CHANGED)
    assert [(e.entity, e.change) for e in diff.entries if e.entity == "service"] == [
        ("service", DiffChangeKind.CHANGED)
    ]


def test_an_agent_added_to_a_listing_is_a_new_service(adapter: AcpImportSource) -> None:
    listing = json.loads(_LIST)
    smaller = {"agents": listing["agents"][:2]}
    diff = adapter.diff(_model(adapter, json.dumps(smaller)), _model(adapter, _LIST))
    added = {(e.entity, e.key) for e in diff.of_kind(DiffChangeKind.ADDED)}
    assert ("service", "approval-router") in added
    assert ("operation", "approval-router.Route for approval") in added


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


def test_clean_documents_raise_no_acp_findings() -> None:
    for raw in (_MINIMAL, _TYPICAL, _LIST, _REAL_WORLD, _TYPICAL_V2):
        assert not [f for f in lint_acp(raw).findings if f.rule.startswith("acp.")], raw[:40]


def test_the_stress_listing_trips_every_rule() -> None:
    rules = {f.rule for f in lint_acp(_STRESS).findings}
    assert {
        "acp.duplicate-agent-name",
        "acp.invalid-agent-name",
        "acp.agent-missing-description",
        "acp.duplicate-capability-name",
        "acp.capability-missing-description",
        "acp.no-capabilities",
        "acp.untyped-content",
        "acp.missing-tags",
        "acp.missing-license",
    } <= rules


def test_untyped_content_names_the_direction() -> None:
    messages = [f.message for f in lint_acp(_STRESS).findings if f.rule == "acp.untyped-content"]
    assert any("'wildcard'" in m and "input and output" in m for m in messages)
    # The second `wildcard` declares only its input, so only its output is untyped.
    assert any("output;" in m and "input and" not in m for m in messages)


def test_a_non_label_name_is_flagged_once() -> None:
    findings = [f for f in lint_acp(_STRESS).findings if f.rule == "acp.invalid-agent-name"]
    assert len(findings) == 2  # "Bad Name_With Spaces" and "résumé-writer"; the repeat is skipped


# ---------------------------------------------------------------------------
# Browse: the catalog item detail "Agents" group
# ---------------------------------------------------------------------------


def test_catalog_detail_lists_agents_with_tags_and_capabilities(adapter: AcpImportSource) -> None:
    groups = derive_parsed_model(_model(adapter, _LIST))
    assert [g["title"] for g in groups] == ["Agents"]
    agents = {e["name"]: e for e in groups[0]["entities"]}
    invoice = agents["invoice-extractor"]
    assert invoice["tag"] == "AGENT"
    assert invoice["meta"] == "tags: ocr, extraction, finance, accounts-payable"
    rows = {row["name"]: row["type"] for row in invoice["fields"]}
    assert rows["capabilities"] == "Extract fields, Extract line items"
    assert rows["framework"] == "LangGraph"
    assert rows["output content types"] == "application/json"


def test_catalog_detail_omits_empty_agent_facts(adapter: AcpImportSource) -> None:
    groups = derive_parsed_model(_model(adapter, _STRESS))
    plain = next(e for e in groups[0]["entities"] if e["name"] == "wildcard")
    assert plain["meta"] is None
    assert "capabilities" not in {row["name"] for row in plain["fields"]}


# ---------------------------------------------------------------------------
# Live discovery
# ---------------------------------------------------------------------------

_PUBLIC_IP = "93.184.216.34"


def _resolve_without_dns(host: str) -> list:
    try:
        return [str(ipaddress.ip_address(host.strip("[]")))]
    except ValueError:
        return [_PUBLIC_IP]


@pytest.fixture(autouse=True)
def _no_dns():
    with patch.object(ssrf_guard, "_resolve_host_ips", _resolve_without_dns):
        yield


def _transport(routes: Dict[str, Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        route = routes.get(str(request.url))
        if route is None:
            return httpx.Response(404, text="not found")
        status, body = route if isinstance(route, tuple) else (200, route)
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        ("https://acp.example.com", "https://acp.example.com/agents"),
        ("https://acp.example.com/", "https://acp.example.com/agents"),
        ("https://example.com/acp?x=1", "https://example.com/acp/agents"),
        ("https://acp.example.com/agents", "https://acp.example.com/agents"),
        ("https://acp.example.com/agents/chat", "https://acp.example.com/agents/chat"),
    ],
)
def test_acp_agents_urls(base: str, expected: str) -> None:
    assert acp_agents_urls(base) == [expected]


@pytest.mark.parametrize("bad", ["", "ftp://acp.example.com", "https://", "acp.example.com"])
def test_acp_agents_urls_reject_bad_input(bad: str) -> None:
    with pytest.raises(AgentDiscoveryError):
        acp_agents_urls(bad)


def test_introspect_fetches_the_listing_and_sets_the_server(adapter: AcpImportSource) -> None:
    routes = {"https://acp.example.com/agents": _LIST}
    with httpx.Client(transport=_transport(routes)) as client:
        document = adapter.introspect("https://acp.example.com", client=client)
    assert document.source_label == "https://acp.example.com/agents"
    model = adapter.normalize(document)
    assert [s.url for s in model.servers] == ["https://acp.example.com"]
    assert len(model.services) == 3


def test_introspect_reads_one_agent_url(adapter: AcpImportSource) -> None:
    routes = {"https://acp.example.com/agents/echo": _MINIMAL}
    with httpx.Client(transport=_transport(routes)) as client:
        document = adapter.introspect("https://acp.example.com/agents/echo", client=client)
    assert document.shape == "manifest" and document.agents[0].name == "echo"


def test_introspect_reports_missing_and_failing_servers(adapter: AcpImportSource) -> None:
    with httpx.Client(transport=_transport({})) as client:
        with pytest.raises(ImportSourceError, match="No ACP agent manifest found"):
            adapter.introspect("https://acp.example.com", client=client)
    routes = {"https://acp.example.com/agents": (500, "boom")}
    with httpx.Client(transport=_transport(routes)) as client:
        with pytest.raises(ImportSourceError, match="HTTP 500"):
            adapter.introspect("https://acp.example.com", client=client)


def test_discovery_refuses_internal_addresses() -> None:
    with pytest.raises(AgentDiscoveryError):
        fetch_acp_agents("http://127.0.0.1:8000")
    with pytest.raises(AgentDiscoveryError):
        fetch_acp_agents("http://169.254.169.254")
