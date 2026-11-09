"""The MCP Registry API v0.1 client (V2-MCP-26.1 / MCAT-12.1, #3707).

A fake registry (an ``httpx.MockTransport``) serves ``GET /v0.1/servers`` in cursor pages and
``GET /v0.1/servers/{name}/versions/{version}``, so no network is used. Covers the acceptance
criteria: the client pages the registry, respects ``nextCursor`` (and stops on a repeated one),
sends ``search`` / ``updated_since`` / ``version=latest``, and tolerates schema drift (unknown
fields, the flat shape, snake_case drafts, unreadable elements).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

import httpx
import pytest

from app import mcp_registry_client as rc
from app.config import settings
from app.ssrf_guard import SSRFError

REGISTRY = "https://registry.example.test"
OFFICIAL = "io.modelcontextprotocol.registry/official"


@pytest.fixture(autouse=True)
def _allow_test_hosts(monkeypatch):
    """The fake registry's host does not resolve; the guard is checked on its own below."""
    monkeypatch.setattr(settings, "ssrf_allow_private", True)


def _entry(name: str, version: str = "1.0.0", *, status: str = "active", is_latest: bool = True, **extra):
    """A v0.1 ``ServerResponse``."""
    server: Dict[str, Any] = {"name": name, "description": f"{name} server", "version": version, **extra}
    return {"server": server, "_meta": {OFFICIAL: {"status": status, "isLatest": is_latest}}}


class FakeRegistry:
    """Serves ``servers`` ``page_size`` per page (cursor = start offset) and records every request."""

    def __init__(self, servers: List[Any], *, page_size: int = 2) -> None:
        self.servers = servers
        self.page_size = page_size
        self.requests: List[httpx.Request] = []
        self.versions: Dict[tuple, Any] = {}
        self.response: Optional[httpx.Response] = None

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.response is not None:
            return self.response
        path = request.url.raw_path.decode().split("?")[0]
        if path == "/v0.1/servers":
            start = int(request.url.params.get("cursor") or 0)
            page = self.servers[start : start + self.page_size]
            metadata: Dict[str, Any] = {"count": len(page)}
            if start + self.page_size < len(self.servers):
                metadata["nextCursor"] = str(start + self.page_size)
            return httpx.Response(200, json={"servers": page, "metadata": metadata})
        parts = path.split("/")
        if len(parts) == 6 and parts[1:3] == ["v0.1", "servers"] and parts[4] == "versions":
            key = (unquote(parts[3]), unquote(parts[5]))
            if key in self.versions:
                return httpx.Response(200, json=self.versions[key])
            return httpx.Response(404, json={"title": "Not Found", "detail": "Server not found"})
        return httpx.Response(404, json={"title": "Not Found"})


def _client(fake: FakeRegistry, base: str = REGISTRY, **kwargs) -> rc.McpRegistryClient:
    return rc.McpRegistryClient(base, transport=fake.transport(), **kwargs)


# ---------------------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [REGISTRY, f"{REGISTRY}/", f"{REGISTRY}/v0.1", f"{REGISTRY}/v0.1/", f"{REGISTRY}/v0.1/servers", f" {REGISTRY} "],
)
def test_a_base_url_is_reduced_to_the_registry_root(url):
    assert rc.normalize_registry_base(url) == REGISTRY


def test_a_server_version_path_encodes_the_name_and_version():
    assert rc.server_version_path("io.github.acme/weather") == "/v0.1/servers/io.github.acme%2Fweather/versions/latest"
    assert rc.server_version_path("a/b", "1.0.0+build") == "/v0.1/servers/a%2Fb/versions/1.0.0%2Bbuild"


def test_the_official_registry_roots_are_pinned_without_a_version_segment():
    assert rc.OFFICIAL_REGISTRY_URL == "https://registry.modelcontextprotocol.io"
    assert rc.STAGING_REGISTRY_URL == "https://staging.registry.modelcontextprotocol.io"
    assert rc.SERVERS_PATH == "/v0.1/servers"


def test_a_blank_base_url_is_refused():
    with pytest.raises(ValueError, match="needs a base URL"):
        rc.McpRegistryClient("  /v0.1 ")


# ---------------------------------------------------------------------------------------
# Listing and paging
# ---------------------------------------------------------------------------------------


def test_list_servers_follows_next_cursor_until_the_last_page():
    fake = FakeRegistry([_entry(f"io.github.acme/s{i}") for i in range(5)])
    with _client(fake) as client:
        servers = client.list_servers()
    assert [s.name for s in servers] == [f"io.github.acme/s{i}" for i in range(5)]
    assert [r.url.params.get("cursor") for r in fake.requests] == [None, "2", "4"]
    first = fake.requests[0]
    assert str(first.url).startswith(f"{REGISTRY}/v0.1/servers?")
    assert first.url.params["limit"] == "100" and first.url.params["version"] == "latest"
    assert "search" not in first.url.params and "updated_since" not in first.url.params
    assert first.headers["Accept"] == "application/json"


def test_filters_and_headers_are_sent_on_every_page():
    fake = FakeRegistry([_entry(f"io.github.acme/s{i}") for i in range(3)])
    since = datetime(2026, 1, 1, 9, 30, tzinfo=timezone(timedelta(hours=2)))
    with _client(fake, headers={"Authorization": "Bearer t"}) as client:
        client.list_servers(search=" acme ", updated_since=since, limit=2)
    for request in fake.requests:
        assert request.url.params["search"] == "acme"
        assert request.url.params["updated_since"] == "2026-01-01T07:30:00Z"
        assert request.url.params["limit"] == "2"
        assert request.headers["Authorization"] == "Bearer t"


def test_a_string_updated_since_is_sent_as_given_and_version_none_lists_every_version():
    fake = FakeRegistry([_entry("a/b")])
    with _client(fake) as client:
        client.list_servers(updated_since="2026-05-01T00:00:00Z", version=None)
    params = fake.requests[0].url.params
    assert params["updated_since"] == "2026-05-01T00:00:00Z" and "version" not in params


def test_a_naive_datetime_is_read_as_utc():
    fake = FakeRegistry([])
    with _client(fake) as client:
        client.list_servers(updated_since=datetime(2026, 3, 4, 5, 6, 7))
    assert fake.requests[0].url.params["updated_since"] == "2026-03-04T05:06:07Z"


def test_one_page_reports_its_cursor_and_what_it_listed():
    fake = FakeRegistry([_entry("a/one"), {"server": {"description": "no name"}}, _entry("a/three")])
    with _client(fake) as client:
        page = client.list_servers_page()
    assert [s.name for s in page.servers] == ["a/one"] and page.listed == 2 and page.next_cursor == "2"


def test_a_repeated_cursor_stops_paging():
    fake = FakeRegistry([])
    fake.response = httpx.Response(200, json={"servers": [_entry("a/b")], "metadata": {"nextCursor": "same"}})
    with _client(fake) as client:
        servers = client.list_servers()
    assert len(fake.requests) == 2 and [s.name for s in servers] == ["a/b", "a/b"]


def test_more_pages_than_allowed_is_an_error_not_a_truncation():
    fake = FakeRegistry([_entry(f"a/s{i}") for i in range(10)], page_size=2)
    with _client(fake) as client, pytest.raises(rc.McpRegistryClientError, match="narrow it with a search") as info:
        client.list_servers(limit=2, max_pages=3)
    assert info.value.error_class == "unexpected" and len(fake.requests) == 3


def test_iter_servers_is_lazy():
    fake = FakeRegistry([_entry(f"a/s{i}") for i in range(6)])
    with _client(fake) as client:
        first = next(client.iter_servers())
    assert first.name == "a/s0" and len(fake.requests) == 1


# ---------------------------------------------------------------------------------------
# Schema drift
# ---------------------------------------------------------------------------------------


def test_unknown_fields_are_kept_and_deleted_entries_left_out_of_a_listing():
    fake = FakeRegistry(
        [
            _entry("a/new", futureField={"x": 1}),
            _entry("a/gone", status="deleted"),
            "not an object",
            {"server": {"name": "  "}},
        ],
        page_size=10,
    )
    with _client(fake) as client:
        servers = client.list_servers()
    assert [s.name for s in servers] == ["a/new"] and servers[0].server["futureField"] == {"x": 1}


def test_the_flat_shape_and_snake_case_drafts_are_read():
    flat = {
        "name": "a/flat",
        "version_detail": {"version": "0.9.0"},
        "_meta": {OFFICIAL: {"status": "Deprecated", "is_latest": True, "published_at": "2025-01-01T00:00:00Z"}},
    }
    entry = rc.parse_server_entry(flat)
    assert entry is not None and entry.name == "a/flat"
    assert entry.status == "deprecated" and entry.official["isLatest"] is True
    assert entry.official["publishedAt"] == "2025-01-01T00:00:00Z"


def test_an_earlier_drafts_next_cursor_is_followed():
    fake = FakeRegistry([])
    pages = iter(
        [
            {"servers": [_entry("a/one")], "metadata": {"next_cursor": "c2"}},
            {"servers": [_entry("a/two")], "metadata": {}},
        ]
    )
    fake.response = None
    fake._handle = lambda request: (fake.requests.append(request), httpx.Response(200, json=next(pages)))[1]
    with _client(fake) as client:
        names = [s.name for s in client.list_servers()]
    assert names == ["a/one", "a/two"] and fake.requests[1].url.params["cursor"] == "c2"


def test_a_page_without_metadata_is_the_last_page():
    fake = FakeRegistry([])
    fake.response = httpx.Response(200, json={"servers": [_entry("a/b")]})
    with _client(fake) as client:
        assert [s.name for s in client.list_servers()] == ["a/b"]
    assert len(fake.requests) == 1


# ---------------------------------------------------------------------------------------
# One server version
# ---------------------------------------------------------------------------------------


def test_get_server_version_fetches_latest_by_default():
    fake = FakeRegistry([])
    fake.versions[("io.github.acme/weather", "latest")] = _entry("io.github.acme/weather", "2.1.0")
    with _client(fake) as client:
        entry = client.get_server_version("io.github.acme/weather")
    assert entry is not None and entry.version == "2.1.0" and entry.official["isLatest"] is True
    assert fake.requests[0].url.raw_path.decode() == "/v0.1/servers/io.github.acme%2Fweather/versions/latest"


def test_get_server_version_fetches_an_exact_version_and_reports_a_deleted_one():
    fake = FakeRegistry([])
    fake.versions[("a/b", "1.0.0")] = _entry("a/b", "1.0.0", status="deleted", is_latest=False)
    with _client(fake) as client:
        entry = client.get_server_version("a/b", "1.0.0")
    assert entry is not None and entry.status == "deleted"


def test_an_unknown_server_version_is_none():
    with _client(FakeRegistry([])) as client:
        assert client.get_server_version("a/missing", "9.9.9") is None


def test_a_version_lookup_needs_a_name_and_version():
    with _client(FakeRegistry([])) as client:
        for name, version in [("", "latest"), ("a/b", " ")]:
            with pytest.raises(ValueError):
                client.get_server_version(name, version)


def test_a_version_body_without_a_server_is_unexpected():
    fake = FakeRegistry([])
    fake.response = httpx.Response(200, json={"server": {"description": "?"}})
    with _client(fake) as client, pytest.raises(rc.McpRegistryClientError, match="no server") as info:
        client.get_server_version("a/b")
    assert info.value.error_class == "unexpected"


# ---------------------------------------------------------------------------------------
# Failures
# ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response, status, error_class, fragment",
    [
        (httpx.Response(401, json={"title": "Unauthorized", "detail": "token revoked"}), 401, "auth", "token revoked"),
        (httpx.Response(503, text="maintenance"), 503, "unavailable", "maintenance"),
        (httpx.Response(200, text="<html>"), 200, "unexpected", "not JSON"),
        (httpx.Response(200, json={"items": []}), None, "unexpected", "no servers list"),
    ],
)
def test_a_refusal_or_odd_body_is_a_client_error(response, status, error_class, fragment):
    fake = FakeRegistry([])
    fake.response = response
    with _client(fake) as client, pytest.raises(rc.McpRegistryClientError) as info:
        client.list_servers_page()
    assert info.value.http_status == status and info.value.error_class == error_class
    assert fragment in str(info.value)


def test_a_version_lookup_refusal_other_than_404_raises():
    fake = FakeRegistry([])
    fake.response = httpx.Response(500, json={"title": "boom"})
    with _client(fake) as client, pytest.raises(rc.McpRegistryClientError) as info:
        client.get_server_version("a/b")
    assert info.value.http_status == 500 and "/v0.1/servers/a%2Fb/versions/latest" in str(info.value)


def test_no_answer_and_a_refused_address_are_client_errors():
    def unreachable(request):
        raise httpx.ConnectError("down", request=request)

    with rc.McpRegistryClient(REGISTRY, transport=httpx.MockTransport(unreachable)) as client:
        with pytest.raises(rc.McpRegistryClientError, match="did not answer GET /v0.1/servers: ConnectError") as info:
            client.list_servers_page()
    assert info.value.http_status is None

    def refused(request):
        raise SSRFError("private address")

    with rc.McpRegistryClient(REGISTRY, transport=httpx.MockTransport(refused)) as client:
        with pytest.raises(rc.McpRegistryClientError, match="refused") as info:
            client.list_servers_page()
    assert info.value.error_class == rc.ERROR_CLASS_ADDRESS_REFUSED


def test_the_built_client_refuses_a_private_registry_address(monkeypatch):
    monkeypatch.setattr(settings, "ssrf_allow_private", False)
    with rc.McpRegistryClient("http://127.0.0.1:9") as client, pytest.raises(rc.McpRegistryClientError) as info:
        client.list_servers_page()
    assert info.value.error_class == rc.ERROR_CLASS_ADDRESS_REFUSED


def test_an_injected_http_client_is_used_and_left_open():
    fake = FakeRegistry([_entry("a/b")])
    http = httpx.Client(transport=fake.transport())
    with rc.McpRegistryClient(REGISTRY, http_client=http) as client:
        assert [s.name for s in client.list_servers()] == ["a/b"]
    assert not http.is_closed
    http.close()
