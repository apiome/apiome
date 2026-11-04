"""Agentic-web site manifests over a tenant's published surface — MFX-32.3 (#4297).

Covers :mod:`app.agentic_web_manifest` and :mod:`app.browse_agentic_routes`, against the issue's
acceptance criteria:

* **manifests enumerate only published/public artifacts, tenant-scoped** — the routes read the
  anonymous browse queries for the requested tenant only, never the member ones (even with
  credentials), and each project contributes its latest published public version;
* **the emitted agents.json re-imports via MFI-18.3** — the document is detected and parsed as an
  ``agents-json`` manifest, every artifact comes back as an endpoint, and the agent endpoints are
  the discovery seeds; the ``llms.txt`` re-imports as ``llms-txt`` with its links classified.

Plus the agent endpoints (A2A well-known card, MCP / ACP server), ``site_url`` handling and the
empty tenant.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agentic_web_manifest import (
    APIS_KEY,
    MAX_DESCRIPTION_CHARS,
    PublishedArtifact,
    agent_endpoint,
    browse_page_url,
    build_agents_json,
    build_llms_txt,
    render_agents_json,
)
from app.agents_manifest_parser import detect_dialect, discovery_seeds, parse_agents_manifest
from app.canonical_model import AgentDescriptor, ApiIdentity, ApiParadigm, CanonicalApi, Server
from app.catalog_conversion import build_conversion_source
from app.export_source import ExportSourceError
from app.import_source import get_import_source, load_builtin_import_sources
from app.main import app

_EXAMPLES = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples"
_SITE = "https://browse.example.com"

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def _registries() -> None:
    load_builtin_import_sources()


def _corpus(path: str, fmt: str) -> CanonicalApi:
    file = _EXAMPLES / path
    if not file.is_file():
        pytest.skip(f"corpus file {path} is not checked out")
    return build_conversion_source(
        {"id": "item-1", "name": file.stem, "source_format": fmt,
         "format_metadata": {"sourceContent": file.read_text(encoding="utf-8")}}
    ).api


_PETS = PublishedArtifact(project_slug="pets", name="Pet Store", version="1.2.0", protocol="rest",
                          source_format="openapi-3.1", description="Adopt a pet.\nToday.")
_TRAVEL = PublishedArtifact(project_slug="travel", name="Travel Concierge", version="2.4.0", protocol="agent",
                            source_format="a2a", description="Plans trips.",
                            agent_url="https://travel.agents.example.com/.well-known/agent-card.json")
_TICKETS = PublishedArtifact(project_slug="tickets", name="Tickets", version="1.0.0", protocol="agent",
                             source_format="mcp", agent_url="https://mcp.example.com/tickets")
_ACP = PublishedArtifact(project_slug="research", name="Research", version="0.1.0", protocol="agent",
                         source_format="acp", agent_url="https://acp.example.com")
_ALL = [_PETS, _TRAVEL, _TICKETS, _ACP]


def _agents_json(artifacts: List[PublishedArtifact], site: str = _SITE) -> Dict[str, Any]:
    return build_agents_json(tenant_slug="acme", tenant_name="Acme Corp", site_url=site, artifacts=artifacts)


# ===========================================================================
# The builders
# ===========================================================================


def test_agents_json_lists_every_artifact_and_each_agent_endpoint() -> None:
    document = _agents_json(_ALL)
    assert document["site"] == {"name": "Acme Corp", "url": f"{_SITE}/tenant/acme",
                                "description": "The APIs and agents Acme Corp publishes on Apiome."}
    assert [e["url"] for e in document["a2a"]] == [_TRAVEL.agent_url]
    assert [e["url"] for e in document["mcp"]] == [_TICKETS.agent_url]
    assert [e["url"] for e in document["acp"]] == [_ACP.agent_url]
    apis = document[APIS_KEY]
    assert [a["url"] for a in apis] == [
        f"{_SITE}/tenant/acme/pets/1.2.0", f"{_SITE}/tenant/acme/travel/2.4.0",
        f"{_SITE}/tenant/acme/tickets/1.0.0", f"{_SITE}/tenant/acme/research/0.1.0",
    ]
    assert apis[0] == {"url": f"{_SITE}/tenant/acme/pets/1.2.0", "name": "Pet Store",
                       "description": "Adopt a pet. Today.", "protocol": "rest",
                       "format": "openapi-3.1", "version": "1.2.0"}


def test_agents_json_always_has_the_standard_lists() -> None:
    document = _agents_json([_PETS])
    assert document["a2a"] == document["mcp"] == document["acp"] == []


def test_an_agent_without_an_endpoint_is_listed_by_its_page_only() -> None:
    bare = PublishedArtifact(project_slug="echo", name="Echo", version="1", source_format="mcp")
    document = _agents_json([bare])
    assert document["mcp"] == []
    assert [a["name"] for a in document[APIS_KEY]] == ["Echo"]


def test_urls_are_percent_encoded_and_site_relative_without_a_site() -> None:
    odd = PublishedArtifact(project_slug="a b", name="A", version="1.0.0+build/7")
    assert browse_page_url(_SITE, "t/x", odd) == f"{_SITE}/tenant/t%2Fx/a%20b/1.0.0%2Bbuild%2F7"
    document = _agents_json([_PETS], site="")
    assert "url" not in document["site"]
    assert document[APIS_KEY][0]["url"] == "/tenant/acme/pets/1.2.0"


def test_long_descriptions_are_cut_at_a_word() -> None:
    long = PublishedArtifact(project_slug="p", name="P", version="1", description="word " * 100)
    description = _agents_json([long])[APIS_KEY][0]["description"]
    assert len(description) <= MAX_DESCRIPTION_CHARS + 1 and description.endswith("…")


def test_llms_txt_has_apis_agents_and_the_manifest() -> None:
    text = build_llms_txt(tenant_slug="acme", tenant_name="Acme Corp", site_url=_SITE, artifacts=_ALL,
                          agents_json_url=f"{_SITE}/tenant/acme/agents.json")
    assert text.startswith("# Acme Corp\n\n> The 4 APIs and agents Acme Corp publishes on Apiome")
    pets = f"- [Pet Store]({_SITE}/tenant/acme/pets/1.2.0): Adopt a pet. Today. (rest · openapi-3.1 · version 1.2.0)"
    assert pets in text
    assert "## Agents" in text
    assert f"- [Travel Concierge (A2A agent card)]({_TRAVEL.agent_url}): Plans trips." in text
    assert f"- [Tickets (MCP server)]({_TICKETS.agent_url}): The MCP server of Tickets" in text
    manifest = f"- [Site manifest]({_SITE}/tenant/acme/agents.json): agents.json with the same entries"
    assert text.rstrip().endswith(manifest)


def test_llms_txt_for_an_empty_tenant() -> None:
    text = build_llms_txt(tenant_slug="acme", tenant_name="Acme", site_url=_SITE, artifacts=[])
    assert "Nothing is published yet." in text
    assert "## Agents" not in text


def test_link_text_cannot_break_out_of_the_link() -> None:
    sneaky = PublishedArtifact(project_slug="p", name="A [b](http://evil)\nc", version="1")
    text = build_llms_txt(tenant_slug="t", tenant_name="T", site_url=_SITE, artifacts=[sneaky])
    assert "- [A (b)(http://evil) c](" in text


# ===========================================================================
# Re-import through MFI-18.3
# ===========================================================================


def test_agents_json_reimports_as_an_agents_json_manifest() -> None:
    content = render_agents_json(_agents_json(_ALL))
    assert detect_dialect(content, filename="agents.json") == "agents-json"
    manifest = parse_agents_manifest(content, source_label=f"{_SITE}/tenant/acme/agents.json")
    assert manifest.title == "Acme Corp"
    by_protocol = {(e.protocol, e.url) for e in manifest.endpoints}
    assert ("a2a", _TRAVEL.agent_url) in by_protocol
    assert ("mcp", _TICKETS.agent_url) in by_protocol
    assert (APIS_KEY, f"{_SITE}/tenant/acme/pets/1.2.0") in by_protocol
    seeds = {(seed.protocol, seed.url) for seed in discovery_seeds(manifest)}
    assert seeds == {("a2a", _TRAVEL.agent_url), ("mcp", _TICKETS.agent_url), ("acp", _ACP.agent_url)}

    source = get_import_source("agents-manifest")
    api = source.normalize(source.parse(content, source_label="agents.json"))
    assert api.paradigm is ApiParadigm.AGENT
    assert len(list(api.operations())) == 7


def test_an_agents_json_without_agents_still_reimports() -> None:
    content = render_agents_json(_agents_json([_PETS]))
    assert detect_dialect(content, filename="agents.json") == "agents-json"
    source = get_import_source("agents-manifest")
    api = source.normalize(source.parse(content, source_label="agents.json"))
    assert [op.extras.get("url") or op.key for op in api.operations()]


def test_llms_txt_reimports_with_its_links_classified() -> None:
    text = build_llms_txt(tenant_slug="acme", tenant_name="Acme Corp", site_url=_SITE, artifacts=_ALL,
                          agents_json_url=f"{_SITE}/tenant/acme/agents.json")
    assert detect_dialect(text, filename="llms.txt") == "llms-txt"
    manifest = parse_agents_manifest(text, source_label=f"{_SITE}/tenant/acme/llms.txt")
    protocols = {(e.protocol, e.url) for e in manifest.endpoints}
    assert ("a2a", _TRAVEL.agent_url) in protocols
    assert ("mcp", _TICKETS.agent_url) in protocols
    assert ("acp", _ACP.agent_url) in protocols
    assert ("manifest", f"{_SITE}/tenant/acme/agents.json") in protocols
    assert ("docs", f"{_SITE}/tenant/acme/pets/1.2.0") in protocols


# ===========================================================================
# Agent endpoints from an artifact's own source
# ===========================================================================


def test_an_a2a_artifact_points_at_its_well_known_card() -> None:
    api = _corpus("a2a/02-typical-travel-concierge.json", "a2a")
    assert agent_endpoint("a2a", api) == "https://travel.agents.example.com/.well-known/agent-card.json"


def test_an_mcp_artifact_points_at_its_server() -> None:
    assert agent_endpoint("mcp", _corpus("mcp/02-typical-tickets-server.json", "mcp")) == "https://mcp.example.com/tickets"
    assert agent_endpoint("mcp", _corpus("mcp/01-minimal-echo-tool.json", "mcp")) is None  # stdio only


def test_other_formats_and_non_http_endpoints_have_no_agent_endpoint() -> None:
    api = CanonicalApi(paradigm=ApiParadigm.AGENT, format="acp", identity=ApiIdentity(name="x"),
                       servers=[Server(url="stdio://local")],
                       agents=[AgentDescriptor(key="x", name="x", protocol="acp", url="ftp://x")])
    assert agent_endpoint("acp", api) is None
    api.servers.append(Server(url="https://acp.example.com"))
    assert agent_endpoint("acp", api) == "https://acp.example.com"
    assert agent_endpoint("openapi-3.1", api) is None
    assert agent_endpoint(None, api) is None


# ===========================================================================
# The routes: public, tenant-scoped
# ===========================================================================


_TENANT = {"id": "t-1", "slug": "acme", "name": "Acme Corp"}
_PROJECTS = [
    {"slug": "travel", "name": "Travel Concierge", "latest_version": "2.4.0"},
    {"slug": "pets", "name": "Pet Store", "latest_version": "1.2.0"},
    {"slug": "gone", "name": "Gone", "latest_version": "1.0.0"},
]
_VERSIONS = {
    "pets": [
        {"version_id": "1.1.0", "protocol": "rest", "source_format": "openapi-3.1", "description": "Old."},
        {"version_id": "1.2.0", "protocol": "rest", "source_format": "openapi-3.1", "description": "Adopt a pet."},
    ],
    "travel": [{"version_id": "2.4.0", "protocol": "agent", "source_format": "a2a", "description": "Plans trips."}],
    "gone": [],
}


class _Source:
    def __init__(self, api: CanonicalApi) -> None:
        self.api = api


def _get(path: str, **headers: str) -> Any:
    travel = _corpus("a2a/02-typical-travel-concierge.json", "a2a")
    with patch("app.browse_agentic_routes.db") as db, \
            patch("app.browse_agentic_routes.load_public_export_source", return_value=_Source(travel)) as load:
        db.get_tenant_row_by_slug.side_effect = lambda slug: _TENANT if slug == "acme" else None
        db.list_public_browse_projects_for_tenant.return_value = _PROJECTS
        db.list_public_browse_versions_for_project.side_effect = lambda tenant_id, slug: _VERSIONS[slug]
        response = client.get(path, headers=headers)
    response.db, response.load = db, load  # type: ignore[attr-defined]
    return response


def test_the_agents_json_route_lists_the_public_slice_of_one_tenant() -> None:
    response = _get(f"/v1/browse/tenants/acme/agents.json?site_url={_SITE}/", Authorization="Bearer member-token")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["cache-control"] == "public, max-age=300"
    document = json.loads(response.text)
    assert [a["name"] for a in document[APIS_KEY]] == ["Pet Store", "Travel Concierge"]  # by name; empty skipped
    assert document[APIS_KEY][0]["url"] == f"{_SITE}/tenant/acme/pets/1.2.0"  # the latest, not 1.1.0
    assert document["a2a"] == [{"url": "https://travel.agents.example.com/.well-known/agent-card.json",
                                "name": "Travel Concierge", "description": "Plans trips."}]
    db = response.db
    db.list_public_browse_projects_for_tenant.assert_called_once_with("t-1", require_published=True)
    assert not db.list_member_browse_projects_for_tenant.called
    assert not db.list_member_browse_versions_for_project.called
    response.load.assert_called_once_with("acme", "travel", "2.4.0")  # only the agent artifact is loaded


def test_the_llms_txt_route() -> None:
    response = _get(f"/v1/browse/tenants/acme/llms.txt?site_url={_SITE}")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.text.startswith("# Acme Corp")
    assert f"- [Site manifest]({_SITE}/tenant/acme/agents.json)" in response.text


def test_an_unknown_tenant_is_404() -> None:
    assert _get("/v1/browse/tenants/nope/agents.json").status_code == 404
    assert _get("/v1/browse/tenants/nope/llms.txt").status_code == 404


@pytest.mark.parametrize("site", ["ftp://x.example.com", "not a url", "https://x.example.com/?q=1"])
def test_a_bad_site_url_is_422(site: str) -> None:
    assert _get(f"/v1/browse/tenants/acme/agents.json?site_url={site}").status_code == 422


def test_the_setting_is_the_default_site(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import browse_agentic_routes

    monkeypatch.setattr(browse_agentic_routes.settings, "public_browse_url", "https://pub.example.com/b/")
    document = json.loads(_get("/v1/browse/tenants/acme/agents.json").text)
    assert document["site"]["url"] == "https://pub.example.com/b/tenant/acme"
    monkeypatch.setattr(browse_agentic_routes.settings, "public_browse_url", "")
    document = json.loads(_get("/v1/browse/tenants/acme/agents.json").text)
    assert document[APIS_KEY][0]["url"] == "/tenant/acme/pets/1.2.0"


def test_an_agent_whose_source_cannot_be_loaded_is_listed_by_page_only() -> None:
    with patch("app.browse_agentic_routes.db") as db, \
            patch("app.browse_agentic_routes.load_public_export_source",
                  side_effect=ExportSourceError("no source", status_code=422)):
        db.get_tenant_row_by_slug.return_value = _TENANT
        db.list_public_browse_projects_for_tenant.return_value = _PROJECTS
        db.list_public_browse_versions_for_project.side_effect = lambda tenant_id, slug: _VERSIONS[slug]
        document = json.loads(client.get("/v1/browse/tenants/acme/agents.json").text)
    assert document["a2a"] == []
    assert "Travel Concierge" in [a["name"] for a in document[APIS_KEY]]
