"""Federated MCP catalog search incl. the MCP registry (V2-MCP-26.4 / MCAT-12.4, #3710).

Covers the acceptance criteria — a search returns local + registry results, labeled, with correct
dedup — at two levels:

* the pure helpers in :mod:`app.mcp_federated_search` (query translation, URL keys, the
  registry → hit projection, and :func:`federate`'s dedupe against tenant-owned endpoints), with a
  fake registry (``httpx.MockTransport``) for :func:`search_registry_servers`;
* the ``GET /v1/mcp/{tenant}/search?include_registry=true`` route, with the DB and the registry
  call mocked: blending, dedupe and labels, first-page-only, a disabled or failing registry.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import mcp_federated_search as fs
from app.auth import validate_authentication
from app.config import settings
from app.main import app
from app.mcp_registry_client import McpRegistryClientError, RegistryServer
from app.models import mcp_search_hit_from_row

client = TestClient(app)

REGISTRY = "https://registry.example.test"
OFFICIAL = "io.modelcontextprotocol.registry/official"
_JWT_T1 = {"tenant_id": "t1", "user_id": "user-1", "auth_method": "jwt"}


@pytest.fixture(autouse=True)
def _default_auth(monkeypatch):
    """Authenticate as tenant ``t1``; let the fake registry host through the SSRF guard."""
    app.dependency_overrides[validate_authentication] = lambda: _JWT_T1
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    monkeypatch.setattr(settings, "mcp_registry_search_url", REGISTRY)
    yield
    app.dependency_overrides.pop(validate_authentication, None)


def _server(name: str, *, url: str | None = None, status: str = "active", **extra: Any) -> RegistryServer:
    """A registry entry with one streamable-http remote (or none when ``url`` is ``None``)."""
    doc: Dict[str, Any] = {"name": name, "description": f"{name} server", "version": "1.2.0", **extra}
    if url:
        doc["remotes"] = [{"type": "streamable-http", "url": url}]
    return RegistryServer(server=doc, official={"status": status})


def _local_row(**overrides: Any) -> Dict[str, Any]:
    """A :meth:`Database.search_mcp_capability_items` row."""
    row = {
        "kind": "tool",
        "item_id": "item-1",
        "item_name": "get_forecast",
        "item_title": None,
        "description": "Weather forecast",
        "endpoint_id": "ep-1",
        "endpoint_name": "Acme Weather",
        "endpoint_slug": "acme-weather",
        "endpoint_url": "https://mcp.acme.example/mcp",
        "category": None,
        "visibility": "private",
        "current_version_id": "ver-1",
        "score": 80,
        "grade": "B",
        "relevance": 0.5,
    }
    row.update(overrides)
    return row


# ===========================================================================
# Helpers
# ===========================================================================


@pytest.mark.parametrize(
    "query,expected",
    [
        ("weather", "weather"),
        ('"weather alerts"', "weather alerts"),
        ("weather -beta", "weather"),
        ("weather OR forecast", "weather forecast"),
        ("-only", ""),
        ("(maps)", "maps"),
    ],
)
def test_registry_query_drops_websearch_syntax(query, expected):
    assert fs.registry_query(query) == expected


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://MCP.Acme.example/mcp/", "https://mcp.acme.example/mcp"),
        ("https://user:secret@mcp.acme.example/mcp?x=1#f", "https://mcp.acme.example/mcp"),
        ("https://mcp.acme.example:8443/sse", "https://mcp.acme.example:8443/sse"),
        ("https://mcp.acme.example", "https://mcp.acme.example"),
        ("stdio://local", None),
        (None, None),
        ("", None),
    ],
)
def test_url_key_normalizes_for_comparison(url, expected):
    assert fs.url_key(url) == expected


def test_remote_url_keys_skip_templated_and_duplicates():
    doc = {
        "remotes": [
            {"type": "streamable-http", "url": "https://a.example/mcp"},
            {"type": "sse", "url": "https://a.example/mcp/"},
            {"type": "sse", "url": "https://{tenant}.a.example/sse"},
            "not-a-remote",
        ]
    }
    assert fs.remote_url_keys(doc) == ["https://a.example/mcp"]


def test_registry_hit_projection_labels_and_strips_credentials():
    server = _server(
        "io.github.acme/weather",
        url="https://tok:secret@mcp.acme.example/mcp?key=1",
        title="Acme Weather",
        websiteUrl="https://acme.example/docs",
        status="deprecated",
    )
    hit = fs.registry_hit_from_server(server, registry_url=REGISTRY + "/v0.1")
    assert hit.source == "registry"
    assert hit.server_name == "io.github.acme/weather"
    assert hit.title == "Acme Weather"
    assert hit.version == "1.2.0"
    assert hit.status == "deprecated"
    assert hit.transport == "streamable_http"
    assert hit.remote_url == "https://mcp.acme.example/mcp"
    assert "secret" not in hit.model_dump_json()
    assert hit.host == "mcp.acme.example"
    assert hit.website_url == "https://acme.example/docs"
    assert hit.registry_url == REGISTRY


def test_registry_hit_projection_package_only_server_has_no_remote():
    server = _server("io.github.acme/local", packages=[{"registryType": "npm", "identifier": "x"}])
    hit = fs.registry_hit_from_server(server, registry_url=REGISTRY)
    assert hit.remote_url is None
    assert hit.transport is None
    assert hit.host == ""


def test_federate_dedupes_by_name_case_insensitively():
    servers = [_server("io.github.Acme/Weather", url="https://other.example/mcp")]
    owned = [
        {
            "id": "ep-1",
            "endpoint_url": "https://mcp.acme.example/mcp",
            "added_via": "registry",
            "registry_server_name": "io.github.acme/weather",
        }
    ]
    result = fs.federate(servers, owned, registry_url=REGISTRY)
    assert result.hits == []
    assert result.duplicates == 1
    assert result.server_name_by_endpoint == {"ep-1": "io.github.acme/weather"}


def test_federate_dedupes_by_remote_url_and_labels_hand_added_endpoint():
    servers = [_server("io.github.acme/weather", url="https://mcp.acme.example/mcp/")]
    owned = [
        {
            "id": "ep-9",
            "endpoint_url": "https://user:pw@MCP.acme.example/mcp",
            "added_via": "manual",
            "registry_server_name": None,
        }
    ]
    result = fs.federate(servers, owned, registry_url=REGISTRY)
    assert result.hits == []
    assert result.duplicates == 1
    assert result.server_name_by_endpoint == {"ep-9": "io.github.acme/weather"}


def test_federate_keeps_unowned_entries_in_registry_order():
    servers = [
        _server("io.github.b/two", url="https://b.example/mcp"),
        _server("io.github.a/one", url="https://a.example/mcp"),
    ]
    owned = [
        # Same host, different path: not the same server.
        {"id": "ep-1", "endpoint_url": "https://b.example/other", "added_via": "manual", "registry_server_name": None}
    ]
    result = fs.federate(servers, owned, registry_url=REGISTRY)
    assert [h.server_name for h in result.hits] == ["io.github.b/two", "io.github.a/one"]
    assert result.duplicates == 0
    assert result.server_name_by_endpoint == {}


def test_federate_labels_registry_import_even_without_its_entry():
    owned = [
        {
            "id": "ep-3",
            "endpoint_url": "https://x.example/mcp",
            "added_via": "registry",
            "registry_server_name": "io.github.x/tool",
        }
    ]
    result = fs.federate([], owned, registry_url=REGISTRY)
    assert result.server_name_by_endpoint == {"ep-3": "io.github.x/tool"}


def test_label_local_hits_sets_registry_name():
    hits = [mcp_search_hit_from_row(_local_row()), mcp_search_hit_from_row(_local_row(endpoint_id="ep-2"))]
    fs.label_local_hits(hits, {"ep-1": "io.github.acme/weather"})
    assert hits[0].registry_server_name == "io.github.acme/weather"
    assert hits[1].registry_server_name is None
    assert all(h.source == "local" for h in hits)


def test_search_registry_servers_sends_search_latest_and_limit():
    seen: List[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        entry = {"server": {"name": "io.github.acme/weather", "version": "1.0.0"}, "_meta": {OFFICIAL: {"status": "active"}}}
        gone = {"server": {"name": "io.github.acme/old"}, "_meta": {OFFICIAL: {"status": "deleted"}}}
        return httpx.Response(200, json={"servers": [entry, gone], "metadata": {"count": 2}})

    servers = fs.search_registry_servers(
        "weather", base_url=REGISTRY, limit=500, timeout=2.0, transport=httpx.MockTransport(handle)
    )
    assert [s.name for s in servers] == ["io.github.acme/weather"]  # deleted entries left out
    params = seen[0].url.params
    assert seen[0].url.path == "/v0.1/servers"
    assert params["search"] == "weather"
    assert params["version"] == "latest"
    assert params["limit"] == str(fs.REGISTRY_SEARCH_MAX)


def test_search_registry_servers_blank_term_skips_the_call():
    def handle(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("registry called for a blank term")

    assert fs.search_registry_servers("  ", base_url=REGISTRY, limit=5, timeout=1.0, transport=httpx.MockTransport(handle)) == []


def test_search_registry_servers_error_raises_client_error():
    transport = httpx.MockTransport(lambda r: httpx.Response(503, json={"title": "Unavailable"}))
    with pytest.raises(McpRegistryClientError):
        fs.search_registry_servers("weather", base_url=REGISTRY, limit=5, timeout=1.0, transport=transport)


# ===========================================================================
# Route
# ===========================================================================


def _search(**params: Any):
    return client.get("/v1/mcp/acme/search", params={"q": "weather", **params})


def test_route_without_include_registry_never_calls_registry():
    with patch("app.mcp_catalog_routes.db") as mock_db, patch.object(fs, "search_registry_servers") as reg:
        mock_db.search_mcp_capability_items.return_value = [_local_row()]
        resp = _search()
    assert resp.status_code == 200
    body = resp.json()
    reg.assert_not_called()
    mock_db.find_mcp_endpoints_for_registry_dedupe.assert_not_called()
    assert body["registry_included"] is False
    assert body["registry_hits"] == []
    assert body["hits"][0]["source"] == "local"
    assert body["hits"][0]["registry_server_name"] is None


def test_route_blends_local_and_registry_hits_with_dedupe():
    servers = [
        _server("io.github.acme/weather", url="https://mcp.acme.example/mcp"),  # owned (by URL)
        _server("io.github.zeta/weather-alerts", url="https://alerts.zeta.example/mcp"),
    ]
    owned = [{"id": "ep-1", "endpoint_url": "https://mcp.acme.example/mcp", "added_via": "manual", "registry_server_name": None}]
    with patch("app.mcp_catalog_routes.db") as mock_db, patch.object(
        fs, "search_registry_servers", return_value=servers
    ) as reg:
        mock_db.search_mcp_capability_items.return_value = [_local_row()]
        mock_db.find_mcp_endpoints_for_registry_dedupe.return_value = owned
        resp = _search(include_registry="true", registry_limit=7, q='"weather" -beta')
    assert resp.status_code == 200
    body = resp.json()

    args, kwargs = reg.call_args
    assert args[0] == "weather"
    assert kwargs["base_url"] == REGISTRY
    assert kwargs["limit"] == 7

    dedupe_kwargs = mock_db.find_mcp_endpoints_for_registry_dedupe.call_args.kwargs
    assert mock_db.find_mcp_endpoints_for_registry_dedupe.call_args.args == ("t1",)
    assert set(dedupe_kwargs["server_names"]) == {"io.github.acme/weather", "io.github.zeta/weather-alerts"}
    assert dedupe_kwargs["hosts"] == ["alerts.zeta.example", "mcp.acme.example"]
    assert dedupe_kwargs["endpoint_ids"] == ["ep-1"]

    assert body["registry_included"] is True
    assert body["registry_url"] == REGISTRY
    assert body["registry_error"] is None
    assert body["registry_duplicates"] == 1
    assert [h["server_name"] for h in body["registry_hits"]] == ["io.github.zeta/weather-alerts"]
    assert body["registry_hits"][0]["source"] == "registry"
    # Local hits are unchanged in count and labeled with the registry entry they matched.
    assert body["count"] == 1
    assert body["hits"][0]["source"] == "local"
    assert body["hits"][0]["registry_server_name"] == "io.github.acme/weather"


def test_route_registry_only_on_first_page():
    with patch("app.mcp_catalog_routes.db") as mock_db, patch.object(fs, "search_registry_servers") as reg:
        mock_db.search_mcp_capability_items.return_value = []
        resp = _search(include_registry="true", offset=50)
    assert resp.status_code == 200
    reg.assert_not_called()
    assert resp.json()["registry_included"] is False


def test_route_registry_failure_keeps_local_hits():
    with patch("app.mcp_catalog_routes.db") as mock_db, patch.object(
        fs, "search_registry_servers", side_effect=McpRegistryClientError("registry timed out")
    ):
        mock_db.search_mcp_capability_items.return_value = [_local_row()]
        resp = _search(include_registry="true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["registry_included"] is False
    assert body["registry_error"] == "registry timed out"
    assert body["registry_hits"] == []
    mock_db.find_mcp_endpoints_for_registry_dedupe.assert_not_called()


def test_route_registry_disabled_by_blank_url(monkeypatch):
    monkeypatch.setattr(settings, "mcp_registry_search_url", "")
    with patch("app.mcp_catalog_routes.db") as mock_db, patch.object(fs, "search_registry_servers") as reg:
        mock_db.search_mcp_capability_items.return_value = []
        resp = _search(include_registry="true")
    assert resp.status_code == 200
    reg.assert_not_called()
    body = resp.json()
    assert body["registry_included"] is False
    assert "turned off" in body["registry_error"]


def test_route_endpoint_scope_also_federates():
    endpoint_row = _local_row(kind="endpoint", item_id=None, item_name=None)
    with patch("app.mcp_catalog_routes.db") as mock_db, patch.object(fs, "search_registry_servers", return_value=[]):
        mock_db.search_mcp_endpoints_fts.return_value = [endpoint_row]
        mock_db.find_mcp_endpoints_for_registry_dedupe.return_value = []
        resp = _search(include_registry="true", scope="endpoint")
    assert resp.status_code == 200
    assert resp.json()["registry_included"] is True


def test_route_registry_limit_validated():
    resp = _search(include_registry="true", registry_limit=0)
    assert resp.status_code == 422
