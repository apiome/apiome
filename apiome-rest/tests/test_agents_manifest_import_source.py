"""The ``agents-manifest`` import-source adapter, its normalizer, lint pack and live discovery —
MFI-18.3 (#3976)."""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import httpx
import pytest

from app import ssrf_guard
from app.agent_descriptor_fetch import AgentDiscoveryError
from app.agents_manifest_discovery import fetch_site_manifest, site_manifest_urls
from app.agents_manifest_import_source import AgentsManifestImportSource
from app.agents_manifest_lint import lint_agents_manifest
from app.agents_manifest_parser import (
    AgentsManifestParseError,
    classify_link,
    detect_dialect,
    discovery_seeds,
    is_agents_json_document,
    is_awp_document,
    parse_agents_manifest,
)
from app.canonical_model import ApiParadigm
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

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui/examples/agents-manifest"


def _read(name: str) -> str:
    return (_EXAMPLES / name).read_text(encoding="utf-8")


_MINIMAL = _read("01-minimal-agents.txt")
_AGENTS_JSON = _read("02-typical-northwind-agents.json")
_AWP = _read("03-composition-contoso-agent.json")
_STRESS = _read("04-stress-edge-cases.agents.txt")
_LLMS = _read("05-real-world-fabrikam-docs.llms.txt")
_AGENTS_JSON_V2 = _read("06-typical-northwind-agents-v2.json")
_A2A_CARD = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/a2a/02-typical-travel-concierge.json"
).read_text(encoding="utf-8")
_ACP_LIST = (
    Path(__file__).resolve().parents[2] / "apiome-ui/examples/acp/03-composition-agent-list.json"
).read_text(encoding="utf-8")

_VALID = {
    "01-minimal-agents.txt": _MINIMAL,
    "02-typical-northwind-agents.json": _AGENTS_JSON,
    "03-composition-contoso-agent.json": _AWP,
    "04-stress-edge-cases.agents.txt": _STRESS,
    "05-real-world-fabrikam-docs.llms.txt": _LLMS,
    "06-typical-northwind-agents-v2.json": _AGENTS_JSON_V2,
}


@pytest.fixture
def adapter() -> AgentsManifestImportSource:
    return AgentsManifestImportSource()


def _model(adapter: AgentsManifestImportSource, raw: str, label: Any = None, **kwargs: Any):
    return adapter.normalize(adapter.parse(raw, source_label=label), **kwargs)


def _services(model) -> Dict[str, Any]:
    return {service.key: service for service in model.services}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_adapter_is_registered_under_agents_manifest() -> None:
    source = get_import_source("agents-manifest")
    assert source is not None and source.key == "agents-manifest"


def test_descriptor_advertises_live_discovery_and_agent_paradigm() -> None:
    descriptor = next(d for d in describe_import_sources() if d.key == "agents-manifest")
    assert descriptor.paradigm is ApiParadigm.AGENT
    assert descriptor.supports_live_discovery is True
    assert descriptor.formats == ["agents-manifest"]
    assert ".json" in descriptor.file_extensions and ".txt" in descriptor.file_extensions
    for kind in (InputKind.FILE, InputKind.URL, InputKind.PASTE, InputKind.DISCOVERY):
        assert kind in descriptor.input_kinds


def test_normalizer_lint_pack_and_coverage_are_registered() -> None:
    assert get_normalizer("agents-manifest") is not None
    assert "agents-manifest" in available_lint_formats()
    assert len(version_coverage_for("agents-manifest").reads) == 3


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(_VALID))
def test_registry_detection_routes_every_fixture_here(name: str) -> None:
    best = detect_import_source(DetectionInput(text=_VALID[name], filename=name))
    assert best is not None and best[0].key == "agents-manifest"
    assert best[1].confidence >= 0.9


@pytest.mark.parametrize(
    ("raw", "dialect"),
    [
        (_MINIMAL, "agents-txt"),
        (_AGENTS_JSON, "agents-json"),
        (_AWP, "awp"),
        (_STRESS, "agents-txt"),
        (_LLMS, "llms-txt"),
    ],
)
def test_detect_dialect_by_shape(raw: str, dialect: str) -> None:
    assert detect_dialect(raw) == dialect


def test_llms_txt_by_shape_is_weaker_than_by_name(adapter: AgentsManifestImportSource) -> None:
    by_shape = adapter.detect(DetectionInput(text=_LLMS))
    by_name = adapter.detect(DetectionInput(text=_LLMS, filename="llms.txt"))
    assert by_shape.matched and by_shape.confidence < 0.9 <= by_name.confidence


def test_a_title_only_markdown_file_is_llms_txt_only_when_named_so() -> None:
    text = "# Notes\n\nJust some prose.\n"
    assert detect_dialect(text) is None
    assert detect_dialect(text, filename="https://example.com/llms.txt") == "llms-txt"


def test_a_plain_readme_is_not_claimed(adapter: AgentsManifestImportSource) -> None:
    readme = "# Project\n\nSome text.\n\n- item one\n- item two\n"
    assert not adapter.detect(DetectionInput(text=readme, filename="README.md")).matched


def test_neighbouring_agent_formats_do_not_claim_each_other() -> None:
    ours = get_import_source("agents-manifest")
    assert not ours.detect(DetectionInput(text=_A2A_CARD)).matched
    assert not ours.detect(DetectionInput(text=_ACP_LIST)).matched
    for other in ("a2a", "acp"):
        for raw in (_AGENTS_JSON, _AWP):
            assert not get_import_source(other).detect(DetectionInput(text=raw)).matched


def test_detect_reads_a_parsed_document(adapter: AgentsManifestImportSource) -> None:
    result = adapter.detect(DetectionInput(document=json.loads(_AWP)))
    assert result.matched and result.confidence >= 0.95


def test_detect_falls_back_to_the_well_known_file_name(adapter: AgentsManifestImportSource) -> None:
    result = adapter.detect(DetectionInput(text="{}", filename="agents.json"))
    assert result.matched and result.confidence < 0.9


@pytest.mark.parametrize(
    "document",
    [
        {"site": {"name": "x"}},
        {"mcp": [{"url": "https://x.example/mcp"}]},
        {"mcp": [{"name": "no url"}], "site": {}},
        {"openapi": "3.1.0", "mcp": [], "site": {}},
        {"name": "card", "protocolVersion": "0.3.0", "a2a": ["https://x"], "site": {}},
        [{"mcp": []}],
    ],
)
def test_agents_json_shape_declines_look_alikes(document: Any) -> None:
    assert not is_agents_json_document(document)


def test_awp_shape() -> None:
    assert is_awp_document({"awp_version": "0.2", "domain": "x.example"})
    assert not is_awp_document({"domain": "x.example"})
    assert not is_awp_document({"awp_version": "0.2", "openapi": "3.0.0"})


@pytest.mark.parametrize(
    "junk",
    ["", "   ", "\x00\x01binary", "{not json", "Just a sentence.", "key: value\nother: 2\n"],
)
def test_detect_dialect_never_raises_on_junk(junk: str) -> None:
    assert detect_dialect(junk) is None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("", "INPUT_EMPTY"),
        ("\x00\x00", "INPUT_ENCODING_INVALID"),
        ('{"version": "1.0", "site": {"name": "x"}, "mcp": [', "INPUT_TRUNCATED"),
        ('{"version": "1.0", "mcp": [1,],}', "INPUT_MALFORMED"),
        ("[1, 2]", "FORMAT_MISMATCH"),
        ('{"openapi": "3.1.0", "info": {}}', "FORMAT_MISMATCH"),
        ('{"hello": "world"}', "FORMAT_MISMATCH"),
        ("Just a sentence of prose.", "FORMAT_MISMATCH"),
        ('{"version": "1.0", "site": {"name": "x"}, "mcp": []}', "INPUT_SEMANTIC_INVALID"),
        ('{"awp_version": "0.2", "domain": "x.example", "actions": {}}', "INPUT_SEMANTIC_INVALID"),
        ('{"awp_version": "0.2", "domain": "x.example", "actions": [{"method": "GET"}]}',
         "INPUT_SEMANTIC_INVALID"),
        ("# Title only\n", "INPUT_SEMANTIC_INVALID"),
    ],
)
def test_parse_classifies_every_failure(raw: str, code: str) -> None:
    with pytest.raises(AgentsManifestParseError) as excinfo:
        parse_agents_manifest(raw)
    assert excinfo.value.code == code


def test_an_a2a_card_is_a_format_mismatch(adapter: AgentsManifestImportSource) -> None:
    with pytest.raises(ImportSourceError) as excinfo:
        adapter.parse(_A2A_CARD)
    assert excinfo.value.code == "FORMAT_MISMATCH"


def test_parse_reads_agents_json() -> None:
    manifest = parse_agents_manifest(_AGENTS_JSON)
    assert manifest.dialect == "agents-json"
    assert manifest.title == "Northwind Store"
    assert manifest.site_url == "https://shop.northwind.example"
    assert manifest.spec_version == "1.0"
    assert [e.protocol for e in manifest.endpoints] == ["a2a", "a2a", "mcp", "skills"]
    assert manifest.endpoints[2].attributes == {"transport": "streamable-http"}
    assert manifest.endpoints[3].title == "northwind-checkout"
    assert [p.protocol for p in manifest.payments] == ["x402", "mpp"]
    assert manifest.payments[0].attributes == {"chains": ["eip155:8453"]}
    assert manifest.authorization == ("agent-auth",)


def test_parse_reads_awp_protocols_actions_and_payments() -> None:
    manifest = parse_agents_manifest(_AWP)
    assert manifest.dialect == "awp"
    assert manifest.title == "travel.contoso.example"
    assert manifest.description == "Book flights and hotels, and manage existing trips"
    assert manifest.site_url == "https://travel.contoso.example"
    assert manifest.spec_version == "0.2"
    assert [e.protocol for e in manifest.endpoints] == ["a2a", "mcp", "acp"]
    # Payment protocols are metadata, never endpoints — even AP2 with an endpoint.
    assert [p.protocol for p in manifest.payments] == ["x402", "ap2"]
    assert manifest.payments[1].attributes["endpoint"] == "https://travel.contoso.example/ap2"
    search, book, cancel = manifest.actions
    assert (search.method, search.resolved_endpoint) == (
        "GET",
        "https://travel.contoso.example/api/flights",
    )
    assert (book.via, book.operation, book.endpoint) == ("a2a", "message/send", None)
    assert cancel.auth_required is True
    assert manifest.authorization == ("oauth2",)


def test_parse_reads_agents_txt_directives() -> None:
    manifest = parse_agents_manifest(_STRESS)
    assert manifest.dialect == "agents-txt"
    assert manifest.spec_version == "1.0"
    assert [p.protocol for p in manifest.payments] == ["x402", "ap2", "x-tipjar"]
    assert manifest.authorization == ("agent-auth", "oauth2")
    assert manifest.policies == {"payments": "required", "identity": "required"}
    protocols = [e.protocol for e in manifest.endpoints]
    assert protocols.count("mcp") == 3 and protocols.count("a2a") == 3
    assert "x-weather" in protocols
    assert manifest.unknown["Crawl-Delay"] == ["10"]
    assert manifest.unknown["Agente"] == ["https://edge.example/ünïcødé"]
    assert manifest.unknown["unparsed_lines"] == [22]


def test_relative_references_resolve_against_a_url_label() -> None:
    from_file = parse_agents_manifest(_STRESS, source_label="agents.txt")
    from_site = parse_agents_manifest(_STRESS, source_label="https://edge.example/agents.txt")
    relative = [e for e in from_file.endpoints if e.url == "/.well-known/agent-card.json"]
    assert relative[0].resolved_url is None
    resolved = [e for e in from_site.endpoints if e.url == "/.well-known/agent-card.json"]
    assert resolved[0].resolved_url == "https://edge.example/.well-known/agent-card.json"
    assert from_site.title == "edge.example"


def test_parse_reads_llms_txt_links() -> None:
    manifest = parse_agents_manifest(_LLMS)
    assert manifest.dialect == "llms-txt"
    assert manifest.title == "Fabrikam Developer Platform"
    assert manifest.description.startswith("Fabrikam's payments API")
    by_title = {e.title: e for e in manifest.endpoints}
    assert by_title["MCP server"].protocol == "mcp"
    assert by_title["Support agent"].protocol == "a2a"
    assert by_title["API reference"].protocol == "openapi"
    assert by_title["Site manifest"].protocol == "manifest"
    assert by_title["Quickstart"].protocol == "docs"
    assert by_title["Quickstart"].description == "Create a key and make a first call"
    assert by_title["Changelog"].attributes == {"section": "Optional", "optional": True}


@pytest.mark.parametrize(
    ("url", "title", "protocol"),
    [
        ("https://x.example/.well-known/agent-card.json", None, "a2a"),
        ("https://x.example/.well-known/agent.json", None, "a2a"),
        ("https://x.example/agents.txt", None, "manifest"),
        ("https://x.example/docs/llms-full.txt", None, "manifest"),
        ("https://x.example/v1/openapi.yaml", None, "openapi"),
        ("https://x.example/skills/a/SKILL.md", None, "skills"),
        ("https://x.example/mcp/", None, "mcp"),
        ("https://tools.x.example/", "Our MCP endpoint", "mcp"),
        ("https://x.example/runs", "ACP agents", "acp"),
        ("https://x.example/guide.md", "Guide", "docs"),
    ],
)
def test_classify_link(url: str, title: Any, protocol: str) -> None:
    assert classify_link(url, title) == protocol


def test_parse_fileset_reads_the_root(adapter: AgentsManifestImportSource) -> None:
    fileset = IntakeFileset(root="agents.json", members={"agents.json": _AGENTS_JSON, "x.md": "#"})
    assert adapter.parse_fileset(fileset).dialect == "agents-json"
    with pytest.raises(ImportSourceError):
        adapter.parse_fileset(IntakeFileset(root="missing.json", members={"a.json": "{}"}))


# ---------------------------------------------------------------------------
# Discovery seeds
# ---------------------------------------------------------------------------


def test_seeds_point_at_a2a_acp_mcp_and_nested_manifests() -> None:
    awp = [s.as_dict() for s in discovery_seeds(parse_agents_manifest(_AWP))]
    assert awp == [
        {
            "protocol": "a2a",
            "url": "https://travel.contoso.example/.well-known/agent-card.json",
            "importer": "a2a",
        },
        {"protocol": "mcp", "url": "https://travel.contoso.example/mcp", "importer": "mcp-probe"},
        {"protocol": "acp", "url": "https://agents.contoso.example/acp", "importer": "acp"},
    ]
    llms = {s.protocol: s.importer for s in discovery_seeds(parse_agents_manifest(_LLMS))}
    assert llms == {"mcp": "mcp-probe", "a2a": "a2a", "manifest": "agents-manifest"}


def test_seeds_skip_unresolvable_and_repeated_endpoints() -> None:
    seeds = discovery_seeds(parse_agents_manifest(_STRESS))
    assert [s.url for s in seeds] == [
        "https://edge.example/mcp",
        "http://legacy.edge.example/mcp",
    ]


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def test_normalize_rejects_a_foreign_ast(adapter: AgentsManifestImportSource) -> None:
    with pytest.raises(ImportSourceError):
        adapter.normalize({"not": "a manifest"})


def test_each_protocol_is_a_service_and_each_endpoint_an_operation(
    adapter: AgentsManifestImportSource,
) -> None:
    model = _model(adapter, _AGENTS_JSON)
    assert model.paradigm is ApiParadigm.AGENT and model.format == "agents-manifest"
    assert model.protocol == "agents-json"
    services = _services(model)
    assert sorted(services) == ["a2a", "mcp", "skills"]
    assert services["a2a"].name == "A2A agents"
    keys = sorted(op.key for op in services["a2a"].operations)
    assert keys == [
        "a2a.https://returns.northwind.example/.well-known/agent-card.json",
        "a2a.https://shop.northwind.example/.well-known/agent-card.json",
    ]
    assert [s.url for s in model.servers] == ["https://shop.northwind.example"]


def test_payments_and_seeds_live_on_the_model_extras(adapter: AgentsManifestImportSource) -> None:
    model = _model(adapter, _AWP)
    assert "x402" not in _services(model) and "ap2" not in _services(model)
    # Sorted by protocol, so a reordered manifest fingerprints the same.
    assert [p["protocol"] for p in model.extras["payments"]] == ["ap2", "x402"]
    assert model.extras["payments"][1]["details"]["wallet"].startswith("0x")
    assert [s["protocol"] for s in model.extras["discovery_seeds"]] == ["a2a", "acp", "mcp"]
    assert model.extras["dialect"] == "awp" and model.extras["spec_version"] == "0.2"
    assert model.extras["authorization"] == ["oauth2"]


def test_awp_actions_route_via_their_protocol(adapter: AgentsManifestImportSource) -> None:
    services = _services(_model(adapter, _AWP))
    assert sorted(op.name for op in services["actions"].operations) == [
        "cancel_trip",
        "search_flights",
    ]
    book = next(op for op in services["a2a"].operations if op.name == "book_trip")
    assert book.extras["via"] == "a2a" and book.extras["via_declared"] is True
    search = next(op for op in services["actions"].operations if op.name == "search_flights")
    assert search.http_method == "GET"


def test_repeated_endpoints_keep_both(adapter: AgentsManifestImportSource) -> None:
    mcp = _services(_model(adapter, _STRESS))["mcp"].operations
    repeat = [op for op in mcp if op.extras.get("duplicate_of")]
    assert [op.key for op in repeat] == ["mcp.https://edge.example/mcp~2"]


# ---------------------------------------------------------------------------
# Fingerprint and diff
# ---------------------------------------------------------------------------


def test_fingerprint_ignores_order(adapter: AgentsManifestImportSource) -> None:
    base = adapter.fingerprint(_model(adapter, _AGENTS_JSON))
    shuffled = json.loads(_AGENTS_JSON)
    shuffled["a2a"].reverse()
    shuffled = dict(reversed(list(shuffled.items())))
    assert adapter.fingerprint(_model(adapter, json.dumps(shuffled))) == base
    assert adapter.fingerprint(_model(adapter, _AGENTS_JSON_V2)) != base


def test_diff_across_crawls_surfaces_the_endpoint_delta(adapter: AgentsManifestImportSource) -> None:
    diff = adapter.diff(_model(adapter, _AGENTS_JSON), _model(adapter, _AGENTS_JSON_V2))

    def ops(kind: DiffChangeKind) -> set:
        return {e.key for e in diff.of_kind(kind) if e.entity == "operation"}

    assert ops(DiffChangeKind.ADDED) == {"mcp.https://inventory.northwind.example/mcp"}
    assert ops(DiffChangeKind.REMOVED) == {
        "a2a.https://returns.northwind.example/.well-known/agent-card.json"
    }
    assert "mcp.https://shop.northwind.example/mcp" in ops(DiffChangeKind.CHANGED)


# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------


def _pack_rules(raw: str, **kwargs: Any) -> set:
    return {
        f.rule for f in lint_agents_manifest(raw, **kwargs).findings
        if f.rule.startswith("agents-manifest.")
    }


@pytest.mark.parametrize("raw", [_MINIMAL, _AGENTS_JSON, _AWP, _LLMS, _AGENTS_JSON_V2])
def test_clean_manifests_raise_no_pack_findings(raw: str) -> None:
    assert _pack_rules(raw) == set()


def test_the_stress_manifest_trips_the_endpoint_rules() -> None:
    assert _pack_rules(_STRESS) == {
        "agents-manifest.broken-endpoint-ref",
        "agents-manifest.duplicate-endpoint",
        "agents-manifest.insecure-endpoint",
    }


def test_broken_refs_name_each_bad_address() -> None:
    findings = [
        f for f in lint_agents_manifest(_STRESS).findings
        if f.rule == "agents-manifest.broken-endpoint-ref"
    ]
    messages = " ".join(f.message for f in findings)
    for bad in ("'/.well-known/agent-card.json'", "'(empty)'", "'not a url'", "ftp://"):
        assert bad in messages
    # Served from the site, the relative card resolves and is no longer broken.
    assert len(
        [
            f for f in lint_agents_manifest(
                _STRESS, source_label="https://edge.example/agents.txt"
            ).findings
            if f.rule == "agents-manifest.broken-endpoint-ref"
        ]
    ) == len(findings) - 1


def test_awp_action_rules() -> None:
    awp = json.loads(_AWP)
    awp["actions"][1]["via"] = "graphql"
    awp["actions"].append({"id": "search_flights", "endpoint": "/api/v2/flights"})
    assert _pack_rules(json.dumps(awp)) == {
        "agents-manifest.undeclared-via",
        "agents-manifest.duplicate-action-id",
    }


def test_a_docs_only_manifest_seeds_nothing() -> None:
    llms = "# Docs\n\n## Docs\n\n- [Guide](http://docs.example/guide.md)\n"
    # Plain-http documentation links are not agent endpoints, so only the seed rule fires.
    assert _pack_rules(llms) == {"agents-manifest.no-agent-endpoints"}


# ---------------------------------------------------------------------------
# Catalog detail
# ---------------------------------------------------------------------------


def test_catalog_detail_groups_endpoints_actions_seeds_and_payments(
    adapter: AgentsManifestImportSource,
) -> None:
    groups = {group["title"]: group for group in derive_parsed_model(_model(adapter, _AWP))}
    assert list(groups) == ["Endpoints", "Actions", "Discovery seeds", "Payments"]
    endpoint = next(e for e in groups["Endpoints"]["entities"] if e["meta"] == "protocol: mcp")
    rows = {row["name"]: row["type"] for row in endpoint["fields"]}
    assert rows["transport"] == "streamable-http" and rows["version"] == "2025-06-18"
    book = next(e for e in groups["Actions"]["entities"] if e["name"] == "book_trip")
    assert book["tag"] == "ACTION" and book["meta"] == "protocol: a2a"
    seeds = {e["meta"]: e["fields"][0]["type"] for e in groups["Discovery seeds"]["entities"]}
    assert seeds == {"protocol: a2a": "a2a", "protocol: mcp": "mcp-probe", "protocol: acp": "acp"}
    x402 = next(e for e in groups["Payments"]["entities"] if e["name"] == "x402")
    assert {row["name"] for row in x402["fields"]} == {"version", "wallet"}


def test_catalog_detail_omits_empty_groups(adapter: AgentsManifestImportSource) -> None:
    groups = derive_parsed_model(_model(adapter, _MINIMAL))
    assert [group["title"] for group in groups] == ["Endpoints", "Discovery seeds"]


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
    ("site", "expected"),
    [
        (
            "https://example.com",
            [
                "https://example.com/agents.json",
                "https://example.com/.well-known/agent.json",
                "https://example.com/agents.txt",
                "https://example.com/llms.txt",
            ],
        ),
        ("https://example.com/docs/?x=1", None),
        ("https://example.com/docs/llms.txt", ["https://example.com/docs/llms.txt"]),
        ("https://example.com/agents.json?v=2", ["https://example.com/agents.json"]),
    ],
)
def test_site_manifest_urls(site: str, expected: Any) -> None:
    urls = site_manifest_urls(site)
    if expected is None:  # A directory path falls back to the origin's well-known paths.
        assert urls[0] == "https://example.com/agents.json" and len(urls) == 4
    else:
        assert urls == expected


@pytest.mark.parametrize("bad", ["", "ftp://example.com", "https://", "example.com"])
def test_site_manifest_urls_reject_bad_input(bad: str) -> None:
    with pytest.raises(AgentDiscoveryError):
        site_manifest_urls(bad)


def test_introspect_takes_the_first_manifest_and_resolves_against_it(
    adapter: AgentsManifestImportSource,
) -> None:
    routes = {"https://edge.example/agents.txt": _STRESS}
    with httpx.Client(transport=_transport(routes)) as client:
        manifest = adapter.introspect("https://edge.example", client=client)
    assert manifest.source_label == "https://edge.example/agents.txt"
    assert manifest.site_url == "https://edge.example"
    model = adapter.normalize(manifest)
    assert [s.url for s in model.servers] == ["https://edge.example"]


def test_introspect_skips_an_a2a_card_and_an_html_shell(adapter: AgentsManifestImportSource) -> None:
    routes = {
        "https://travel.example/agents.json": "<!doctype html><html></html>",
        "https://travel.example/.well-known/agent.json": _A2A_CARD,
        "https://travel.example/llms.txt": _LLMS,
    }
    with httpx.Client(transport=_transport(routes)) as client:
        manifest = adapter.introspect("https://travel.example", client=client)
    assert manifest.dialect == "llms-txt"


def test_introspect_reports_missing_broken_and_failing_sites(
    adapter: AgentsManifestImportSource,
) -> None:
    with httpx.Client(transport=_transport({})) as client:
        with pytest.raises(ImportSourceError, match="No site manifest found"):
            adapter.introspect("https://none.example", client=client)
    routes = {"https://broken.example/agents.json": '{"version": "1.0", "mcp": ['}
    with httpx.Client(transport=_transport(routes)) as client:
        with pytest.raises(ImportSourceError) as excinfo:
            adapter.introspect("https://broken.example", client=client)
    assert excinfo.value.code == "INPUT_TRUNCATED"
    routes = {"https://down.example/agents.json": (500, "boom")}
    with httpx.Client(transport=_transport(routes)) as client:
        with pytest.raises(ImportSourceError, match="HTTP 500"):
            adapter.introspect("https://down.example", client=client)


def test_a_direct_url_to_a_non_manifest_is_a_mismatch(adapter: AgentsManifestImportSource) -> None:
    routes = {"https://travel.example/.well-known/agent.json": _A2A_CARD}
    with httpx.Client(transport=_transport(routes)) as client:
        with pytest.raises(ImportSourceError) as excinfo:
            adapter.introspect("https://travel.example/.well-known/agent.json", client=client)
    assert excinfo.value.code == "FORMAT_MISMATCH"


def test_discovery_refuses_internal_addresses() -> None:
    with pytest.raises(AgentDiscoveryError):
        fetch_site_manifest("http://127.0.0.1:8000")
    with pytest.raises(AgentDiscoveryError):
        fetch_site_manifest("http://169.254.169.254")
