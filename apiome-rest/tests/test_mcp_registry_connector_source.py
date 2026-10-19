"""The upstream MCP registry connector (CDG-4.4, #5976).

A fake registry (an ``httpx.MockTransport``) serves ``GET /v0.1/servers`` in pages, and the real
:class:`app.mcp_registry_connector_source.McpRegistrySource` runs through
:func:`app.catalog_connector_sync.run_connector_sync` over the in-memory connector store and an
in-memory MCP catalog. Discovery and the remote address rule are injected, so no network is used.

Covers the issue: servers with a reachable remote become MCP servers (``added_via = 'registry'``)
with their sources linked and discovery run; package-only, templated, refused and unreachable
servers stay ``discovered`` with the reason; a re-sync refreshes, retires stale links and retries
only what needs it.
"""

from __future__ import annotations

import base64
import json
import os
import uuid
from typing import Any, Dict, List, Optional

import httpx
import pytest
from catalog_connector_fakes import FakeConnectorStore, FakeDb

from app import mcp_registry_connector_source as reg
from app.catalog_connector_routes import _item_out
from app.catalog_connector_sync import (
    dry_run_connector,
    register_connector_source,
    run_connector_sync,
    source_factory_for,
    syncable_kinds,
    validate_connector_scope,
)
from app.catalog_connectors import CODE_BASE_URL_REFUSED, ConnectorError
from app.config import settings
from app.mcp_credential_crypto import seal_credential_payload

TENANT = "11111111-1111-4111-8111-111111111111"
ACTOR = "33333333-3333-4333-8333-333333333333"
REGISTRY = "https://registry.example.test"


def _server(
    name: str, *, version: str = "1.0.0", remotes=None, packages=None, repository=None, **extra
) -> Dict[str, Any]:
    """A v0.1 ``ServerResponse``."""
    server: Dict[str, Any] = {"name": name, "description": f"{name} server", "version": version}
    if remotes is not None:
        server["remotes"] = remotes
    if packages is not None:
        server["packages"] = packages
    if repository is not None:
        server["repository"] = repository
    official = {
        "status": extra.pop("status", "active"),
        "isLatest": extra.pop("is_latest", True),
        "publishedAt": "2026-09-01T00:00:00Z",
        "updatedAt": extra.pop("updated_at", "2026-10-01T00:00:00Z"),
    }
    server.update(extra)
    return {"server": server, "_meta": {"io.modelcontextprotocol.registry/official": official}}


def _fixture_servers() -> List[Dict[str, Any]]:
    return [
        _server(
            "io.github.acme/weather",
            title="Weather",
            remotes=[
                {"type": "streamable-http", "url": "https://weather.acme.test/mcp", "headers": [{"name": "X-Key"}]}
            ],
            packages=[
                {
                    "registryType": "npm",
                    "identifier": "@acme/weather-mcp",
                    "version": "1.0.0",
                    "transport": {"type": "stdio"},
                }
            ],
            repository={"url": "https://github.com/acme/weather", "source": "github"},
        ),
        _server(
            "io.github.acme/local-files",
            packages=[
                {"registryType": "pypi", "identifier": "acme-files", "version": "0.3.1", "transport": {"type": "stdio"}}
            ],
        ),
        _server("io.github.acme/down", remotes=[{"type": "sse", "url": "https://down.acme.test/sse"}]),
        _server("io.github.acme/internal", remotes=[{"type": "streamable-http", "url": "https://10.0.0.8/mcp"}]),
        _server(
            "io.github.acme/templated", remotes=[{"type": "streamable-http", "url": "https://{tenant}.acme.test/mcp"}]
        ),
    ]


class FakeRegistry:
    """Serves ``/v0.1/servers`` two entries per page and records every request."""

    def __init__(self, servers: List[Dict[str, Any]], *, page_size: int = 2, status: int = 200) -> None:
        self.servers = servers
        self.page_size = page_size
        self.status = status
        self.requests: List[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path != "/v0.1/servers":
            return httpx.Response(404, json={"title": "Not Found"})
        if self.status != 200:
            return httpx.Response(self.status, json={"title": "Unauthorized", "detail": "token revoked"})
        start = int(request.url.params.get("cursor") or 0)
        page = self.servers[start : start + self.page_size]
        metadata: Dict[str, Any] = {"count": len(page)}
        if start + self.page_size < len(self.servers):
            metadata["nextCursor"] = str(start + self.page_size)
        return httpx.Response(200, json={"servers": page, "metadata": metadata})


class McpDb(FakeDb):
    """:class:`FakeDb` plus the MCP catalog calls the source makes (endpoints and their sources)."""

    def __init__(self) -> None:
        super().__init__()
        self.endpoints: Dict[str, Dict[str, Any]] = {}
        self.sources: List[Dict[str, Any]] = []
        self.inserts = 0

    def insert_mcp_endpoint(
        self,
        *,
        tenant_id,
        creator_id,
        name,
        base_slug,
        endpoint_url,
        transport,
        description=None,
        category=None,
        visibility="private",
        discovery_cadence_seconds=None,
        added_via="manual",
    ):
        self.inserts += 1
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "creator_id": creator_id,
            "name": name,
            "slug": base_slug,
            "endpoint_url": endpoint_url,
            "transport": transport,
            "description": description,
            "visibility": visibility,
            "added_via": added_via,
        }
        self.endpoints[row["id"]] = row
        return dict(row)

    def get_mcp_endpoint(self, tenant_id, endpoint_id):
        row = self.endpoints.get(endpoint_id)
        return dict(row) if row and row["tenant_id"] == tenant_id else None

    def update_mcp_endpoint(self, tenant_id, endpoint_id, fields):
        self.endpoints[endpoint_id].update(fields)
        return dict(self.endpoints[endpoint_id])

    def create_mcp_endpoint_source(self, *, tenant_id, endpoint_id, source, linked_by):
        for row in self.sources:
            if (row["endpoint_id"], row["source_kind"], row["locator"]) == (
                endpoint_id,
                source["source_kind"],
                source["locator"],
            ) and row["retired_at"] is None:
                return row
        row = {
            "id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "endpoint_id": endpoint_id,
            "linked_by": linked_by,
            "retired_at": None,
            **source,
        }
        self.sources.append(row)
        return row

    def list_mcp_endpoint_sources(self, endpoint_id, *, include_retired=False):
        return [dict(r) for r in self.sources if r["endpoint_id"] == endpoint_id and r["retired_at"] is None]

    def retire_mcp_endpoint_source(self, endpoint_id, source_id):
        for row in self.sources:
            if row["id"] == source_id and row["endpoint_id"] == endpoint_id:
                row["retired_at"] = "now"
                return True
        return False

    def live_sources(self, endpoint_id) -> List[Dict[str, Any]]:
        return self.list_mcp_endpoint_sources(endpoint_id)


class Discovery:
    """Discovery stand-in: a failure code per endpoint URL (``None`` = the server answered)."""

    def __init__(self, failures: Optional[Dict[str, str]] = None) -> None:
        self.failures = dict(failures or {})
        self.calls: List[str] = []

    def __call__(self, endpoint):
        self.calls.append(endpoint["endpoint_url"])
        return self.failures.get(endpoint["endpoint_url"])


def _address_check(url: str) -> str:
    """The connector address rule, with 10.0.0.0/8 standing in for every private address."""
    if "//10." in url:
        raise ConnectorError(
            CODE_BASE_URL_REFUSED, "Base URL refused: host '10.0.0.8' resolves to a private or reserved address."
        )
    return url


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    key = base64.b64encode(os.urandom(32)).decode()
    monkeypatch.setattr(settings, "mcp_credential_encryption_keys", json.dumps({"1": key}))
    monkeypatch.setattr(settings, "ssrf_allow_private", True)
    yield
    register_connector_source(reg.KIND, reg.McpRegistrySource, scope_validator=reg.validate_mcp_registry_scope)


@pytest.fixture
def store(monkeypatch):
    return FakeConnectorStore().install(monkeypatch)


@pytest.fixture
def shadow_calls(monkeypatch):
    calls: List[Any] = []
    monkeypatch.setattr("app.shadow_api_notifications.notify_new_shadow_apis", lambda *a, **k: calls.append(a))
    return calls


def _use(fake: FakeRegistry, discovery: Discovery) -> None:
    register_connector_source(
        reg.KIND,
        lambda c, creds: reg.McpRegistrySource(
            c, creds, transport=fake.transport(), discover=discovery, address_check=_address_check
        ),
        scope_validator=reg.validate_mcp_registry_scope,
    )


def _connector(store, *, scope=None, token: Optional[str] = "reg-token", created_by: Optional[str] = ACTOR):
    connector = store.add_connector(
        TENANT,
        kind=reg.KIND,
        name="Official registry",
        base_url=f"{REGISTRY}/v0.1/servers",
        scope=scope if scope is not None else {"search": "acme", "updatedSince": "2026-01-01T00:00:00Z"},
        created_by=created_by,
    )
    if token:
        sealed, version = seal_credential_payload({"token": token})
        store.credentials[connector["id"]] = {"encrypted_payload": sealed, "key_version": version}
    return connector


def _sync(store, db, connector, actor_id: Optional[str] = ACTOR):
    return run_connector_sync(db, store.connectors[connector["id"]], actor_id=actor_id)


def _items(store) -> Dict[str, Dict[str, Any]]:
    return {i["remote_id"]: i for i in store.items.values()}


# --- the acceptance criteria -------------------------------------------------------------


def test_sync_turns_reachable_servers_into_mcp_servers_and_keeps_the_rest_discovered(store, shadow_calls):
    fake, discovery, db = (
        FakeRegistry(_fixture_servers()),
        Discovery({"https://down.acme.test/sse": "connect_error"}),
        McpDb(),
    )
    _use(fake, discovery)
    connector = _connector(store)
    result = _sync(store, db, connector)

    assert result.status == "succeeded" and result.connector_status == "active"
    items = _items(store)
    weather = items["io.github.acme/weather"]
    assert weather["status"] == "imported" and weather["discovered_reason"] is None
    endpoint = db.endpoints[weather["mcp_endpoint_id"]]
    assert endpoint["added_via"] == "registry" and endpoint["name"] == "Weather"
    assert endpoint["endpoint_url"] == "https://weather.acme.test/mcp" and endpoint["transport"] == "streamable_http"
    assert endpoint["slug"] == "weather" and endpoint["creator_id"] == ACTOR and endpoint["visibility"] == "private"

    local = items["io.github.acme/local-files"]
    assert local["status"] == "discovered" and local["mcp_endpoint_id"] is None
    assert local["discovered_reason"].startswith("no-remote: the server lists only packages")
    down = items["io.github.acme/down"]
    assert down["status"] == "discovered" and down["mcp_endpoint_id"] in db.endpoints
    assert down["discovered_reason"].startswith("remote-unreachable:") and "connect_error" in down["discovered_reason"]
    assert db.endpoints[down["mcp_endpoint_id"]]["transport"] == "sse"
    internal = items["io.github.acme/internal"]
    assert internal["status"] == "discovered" and internal["discovered_reason"].startswith("remote-refused:")
    assert items["io.github.acme/templated"]["discovered_reason"].startswith("remote-templated:")

    # Only the two servers with a usable remote were created and discovered.
    assert db.inserts == 2
    assert discovery.calls == ["https://weather.acme.test/mcp", "https://down.acme.test/sse"]
    summary = result.summary
    assert (summary["candidates"], summary["imported"], summary["discovered"], summary["failed"]) == (5, 1, 4, 0)
    assert result.pull_count == 2
    assert {d["remoteId"] for d in summary["discoveredItems"]} == {
        "io.github.acme/local-files",
        "io.github.acme/down",
        "io.github.acme/internal",
        "io.github.acme/templated",
    }
    assert shadow_calls == []  # MCP servers never raise shadow-API notifications


def test_sources_are_linked_as_registry_published(store):
    fake, db = FakeRegistry(_fixture_servers()), McpDb()
    _use(fake, Discovery())
    connector = _connector(store)
    _sync(store, db, connector)
    endpoint_id = _items(store)["io.github.acme/weather"]["mcp_endpoint_id"]
    sources = {(s["source_kind"], s["locator"]): s for s in db.live_sources(endpoint_id)}
    assert set(sources) == {
        ("registry", "io.github.acme/weather"),
        ("git", "https://github.com/acme/weather"),
        ("package", "pkg:npm/%40acme/weather-mcp@1.0.0"),
    }
    for source in sources.values():
        assert source["provenance"] == "registry_published"
        assert source["provenance_detail"]["connectorId"] == connector["id"]
        assert source["provenance_detail"]["registryUrl"] == REGISTRY
    assert sources[("package", "pkg:npm/%40acme/weather-mcp@1.0.0")]["verification_state"] == "digest_pinned"
    assert sources[("registry", "io.github.acme/weather")]["revision"] == "1.0.0"


def test_the_registry_is_paged_with_the_scope_filters_and_the_credential(store):
    fake = FakeRegistry(_fixture_servers())
    _use(fake, Discovery())
    _sync(store, McpDb(), _connector(store))
    assert len(fake.requests) == 3  # five servers, two per page
    first = fake.requests[0]
    assert str(first.url).startswith(f"{REGISTRY}/v0.1/servers?")
    assert first.url.params["search"] == "acme" and first.url.params["updated_since"] == "2026-01-01T00:00:00Z"
    assert first.url.params["version"] == "latest" and first.url.params["limit"] == "100"
    assert first.headers["Authorization"] == "Bearer reg-token"
    assert [r.url.params.get("cursor") for r in fake.requests] == [None, "2", "4"]


def test_an_api_key_credential_is_sent_as_x_api_key(store):
    fake = FakeRegistry([_fixture_servers()[0]])
    _use(fake, Discovery())
    connector = _connector(store, token=None, scope={})
    sealed, version = seal_credential_payload({"apiKey": "apk_123"})
    store.credentials[connector["id"]] = {"encrypted_payload": sealed, "key_version": version}
    _sync(store, McpDb(), connector)
    assert fake.requests[0].headers["X-API-Key"] == "apk_123" and "Authorization" not in fake.requests[0].headers
    assert "search" not in fake.requests[0].url.params


def test_resync_retries_only_unreachable_entries_and_reuses_their_server(store):
    fake, discovery, db = (
        FakeRegistry(_fixture_servers()),
        Discovery({"https://down.acme.test/sse": "connect_error"}),
        McpDb(),
    )
    _use(fake, discovery)
    connector = _connector(store)
    _sync(store, db, connector)
    down_id = _items(store)["io.github.acme/down"]["mcp_endpoint_id"]

    discovery.calls.clear()
    discovery.failures.clear()  # the server is back
    result = _sync(store, db, connector)
    assert discovery.calls == ["https://down.acme.test/sse"]  # weather is unchanged: not rediscovered
    down = _items(store)["io.github.acme/down"]
    assert down["status"] == "imported" and down["discovered_reason"] is None and down["mcp_endpoint_id"] == down_id
    assert db.inserts == 2  # no second server for the same entry
    assert _items(store)["io.github.acme/weather"]["status"] == "imported"
    assert result.summary["unchanged"] == 1


def test_resync_refreshes_a_changed_server_and_retires_stale_links(store):
    servers = _fixture_servers()[:1]
    fake, db = FakeRegistry(servers), McpDb()
    _use(fake, Discovery())
    connector = _connector(store)
    _sync(store, db, connector)
    endpoint_id = _items(store)["io.github.acme/weather"]["mcp_endpoint_id"]

    servers[0] = _server(
        "io.github.acme/weather",
        version="1.1.0",
        title="Weather",
        remotes=[{"type": "streamable-http", "url": "https://weather-v2.acme.test/mcp"}],
        packages=[{"registryType": "npm", "identifier": "@acme/weather-mcp", "version": "1.1.0"}],
        updated_at="2026-10-10T00:00:00Z",
    )
    fake.servers = servers
    result = _sync(store, db, connector)
    assert result.summary["imported"] == 1 and db.inserts == 1
    assert db.endpoints[endpoint_id]["endpoint_url"] == "https://weather-v2.acme.test/mcp"
    locators = {s["locator"] for s in db.live_sources(endpoint_id)}
    assert locators == {"io.github.acme/weather", "pkg:npm/%40acme/weather-mcp@1.1.0"}  # old version and repo retired
    assert _items(store)["io.github.acme/weather"]["imported_revision"].startswith("1.1.0+sha256.")


def test_links_an_operator_made_are_never_retired(store):
    servers = _fixture_servers()[:1]
    fake, db = FakeRegistry(servers), McpDb()
    _use(fake, Discovery())
    connector = _connector(store)
    _sync(store, db, connector)
    endpoint_id = _items(store)["io.github.acme/weather"]["mcp_endpoint_id"]
    db.create_mcp_endpoint_source(
        tenant_id=TENANT,
        endpoint_id=endpoint_id,
        linked_by=ACTOR,
        source={
            "source_kind": "image",
            "locator": "ghcr.io/acme/weather:1",
            "provenance": "operator_declared",
            "provenance_detail": {},
        },
    )
    servers[0] = _server(
        "io.github.acme/weather",
        version="2.0.0",
        remotes=[{"type": "streamable-http", "url": "https://weather.acme.test/mcp"}],
    )
    _sync(store, db, connector)
    assert "ghcr.io/acme/weather:1" in {s["locator"] for s in db.live_sources(endpoint_id)}


def test_a_server_deleted_from_the_registry_turns_missing_and_keeps_its_server(store):
    servers = _fixture_servers()[:1]
    fake, db = FakeRegistry(servers), McpDb()
    _use(fake, Discovery())
    connector = _connector(store)
    _sync(store, db, connector)
    servers[0] = _server("io.github.acme/weather", status="deleted")
    result = _sync(store, db, connector)
    item = _items(store)["io.github.acme/weather"]
    assert item["status"] == "missing" and item["mcp_endpoint_id"] in db.endpoints
    assert result.summary["missing"] == 1


def test_a_registry_refusal_fails_the_run_with_its_status(store):
    fake = FakeRegistry(_fixture_servers(), status=401)
    _use(fake, Discovery())
    result = _sync(store, McpDb(), _connector(store))
    assert (result.status, result.error_class, result.http_status) == ("failed", "auth", 401)
    assert "token revoked" in result.error_message and "reg-token" not in result.error_message
    assert result.connector_status == "failing"


def test_a_sweep_run_needs_a_connector_creator_to_own_new_servers(store):
    fake = FakeRegistry(_fixture_servers()[:1])
    _use(fake, Discovery())
    result = _sync(store, McpDb(), _connector(store, created_by=None), actor_id=None)
    assert result.status == "failed" and result.error_class == "invalid-configuration"
    assert "no creator" in result.error_message


def test_dry_run_lists_the_registry_without_creating_anything(store):
    fake, db = FakeRegistry(_fixture_servers()), McpDb()
    _use(fake, Discovery())
    connector = {"id": "dry", "tenant_id": TENANT, "kind": reg.KIND, "base_url": REGISTRY, "scope": {}}
    answer = dry_run_connector(connector, None)
    assert answer["itemCount"] == 5 and answer["items"][0] == {
        "remoteId": "io.github.acme/weather",
        "name": "Weather",
        "environment": None,
        "revision": answer["items"][0]["revision"],
    }
    assert db.endpoints == {} and store.items == {}


def test_the_kind_is_syncable_and_validates_its_scope():
    assert reg.KIND in syncable_kinds() and source_factory_for(reg.KIND) is not None
    validate_connector_scope(reg.KIND, {"search": "weather"}, REGISTRY)
    for scope, base, message in [
        ({}, None, "needs a base URL"),
        ({"region": "us"}, REGISTRY, "Unknown mcp-registry scope key"),
        ({"search": "  "}, REGISTRY, "search must be"),
        ({"updatedSince": "yesterday"}, REGISTRY, "updatedSince must be"),
    ]:
        with pytest.raises(ConnectorError) as info:
            validate_connector_scope(reg.KIND, scope, base)
        assert message in str(info.value) and info.value.code == "connector-invalid"


def test_item_projection_carries_the_mcp_server_and_reason():
    out = _item_out(
        {
            "id": "i1",
            "remote_id": "io.github.acme/down",
            "status": "discovered",
            "mcp_endpoint_id": uuid.UUID(int=7),
            "discovered_reason": "remote-unreachable: …",
        }
    ).model_dump(by_alias=True)
    assert out["mcpEndpointId"] == str(uuid.UUID(int=7)) and out["discoveredReason"] == "remote-unreachable: …"


# --- pure helpers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, root",
    [
        ("https://registry.modelcontextprotocol.io", "https://registry.modelcontextprotocol.io"),
        ("https://registry.modelcontextprotocol.io/", "https://registry.modelcontextprotocol.io"),
        ("https://apiome.test/registry/mcp/acme/v0.1/servers", "https://apiome.test/registry/mcp/acme"),
        ("https://apiome.test/registry/mcp/acme/v0.1/", "https://apiome.test/registry/mcp/acme"),
    ],
)
def test_normalize_registry_base(raw, root):
    assert reg.normalize_registry_base(raw) == root


def test_parse_server_entry_reads_both_shapes_and_drops_deleted_or_nameless():
    v01 = reg.parse_server_entry(_server("a/b"))
    assert v01 is not None and v01.name == "a/b" and v01.official["isLatest"] is True
    flat = reg.parse_server_entry(
        {"name": "a/c", "version": "2", "_meta": {"io.modelcontextprotocol.registry/official": {"status": "active"}}}
    )
    assert flat is not None and flat.version == "2" and flat.official["status"] == "active"
    assert reg.parse_server_entry(_server("a/d", status="deleted")) is None
    assert reg.parse_server_entry({"server": {"version": "1"}}) is None
    assert reg.parse_server_entry("nope") is None


def test_latest_servers_prefers_the_latest_entry_of_each_name():
    old = reg.parse_server_entry(_server("a/b", version="1.0.0", is_latest=False))
    new = reg.parse_server_entry(_server("a/b", version="1.1.0", is_latest=True))
    other = reg.parse_server_entry(_server("a/c"))
    assert [e.version for e in reg.latest_servers([new, old, other])] == ["1.1.0", "1.0.0"]
    assert [e.version for e in reg.latest_servers([old, new])] == ["1.1.0"]


def test_select_remote():
    assert reg.select_remote({"remotes": [{"type": "stdio"}, {"type": "sse", "url": "https://x.test/sse"}]}) == (
        "sse",
        "https://x.test/sse",
    )
    assert reg.select_remote({"remotes": [{"type": "streamable-http", "url": "ftp://x.test"}]}).startswith("no-remote:")
    assert reg.select_remote({}).startswith("no-remote: the server lists no")


def test_package_and_image_references():
    entry = reg.parse_server_entry(
        _server(
            "a/b",
            packages=[
                {"registryType": "oci", "identifier": "docker.io/acme/b", "version": "1.2.3"},
                {"registryType": "oci", "identifier": "ghcr.io/acme/b@sha256:" + "a" * 64},
                {"registryType": "pypi", "identifier": "acme-b"},
                {"registryType": "mcpb", "identifier": "https://example.test/b.mcpb"},
            ],
        )
    )
    links = reg.registry_source_links(entry, connector={"id": "c1", "name": "R"}, registry_url=REGISTRY)
    assert [(link.source_kind, link.locator) for link in links] == [
        ("registry", "a/b"),
        ("image", "docker.io/acme/b:1.2.3"),
        ("image", "ghcr.io/acme/b@sha256:" + "a" * 64),
        ("package", "pkg:pypi/acme-b"),
    ]
    assert links[2].verification_state == "digest_pinned" and links[3].verification_state == "unverified"


def test_candidate_is_credential_free_and_revision_tracks_content():
    entry = reg.parse_server_entry(_fixture_servers()[0])
    candidate = reg.build_candidate(entry, registry_url=REGISTRY)
    assert candidate.remote_id == "io.github.acme/weather" and candidate.name == "Weather"
    assert candidate.hosts == ("weather.acme.test",) and candidate.updated_at.year == 2026
    assert candidate.deployment["remotes"] == [{"type": "streamable-http", "url": "https://weather.acme.test/mcp"}]
    assert candidate.deployment["packages"] == [
        {"registryType": "npm", "identifier": "@acme/weather-mcp", "version": "1.0.0"}
    ]
    assert "headers" not in json.dumps(candidate.deployment)
    changed = dict(entry.server, description="new words")
    assert reg.entry_revision(changed) != candidate.revision and candidate.revision.startswith("1.0.0+sha256.")
