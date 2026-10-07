"""AGX-2.1 agent runtime assembly (#4533): middleware order, the SDK cache switched off, settings."""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest

from apiome_mcp.agent_access import AgentAccessMiddleware
from apiome_mcp.agent_invocation_proxy import InvocationConfig
from apiome_mcp.agent_quotas import AgentQuotaMiddleware
from apiome_mcp.agent_server import AgentToolsetProvider, build_agent_server
from apiome_mcp.http_credential_middleware import StashHttpBearerInToolContextMiddleware
from apiome_mcp.settings import Settings, get_settings


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("APIOME_MCP_DATABASE_URL", "postgresql://localhost/db")
    monkeypatch.setenv("APIOME_MCP_INTERNAL_SECRET", "x" * 16)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_the_middleware_runs_stash_then_access_then_quota(env: None) -> None:
    app = build_agent_server()
    assert [type(mw) for mw in app.middleware] == [
        StashHttpBearerInToolContextMiddleware,
        AgentAccessMiddleware,
        AgentQuotaMiddleware,
    ]
    assert any(isinstance(provider, AgentToolsetProvider) for provider in app.providers)
    assert app.strict_input_validation is False


def test_the_sdk_tool_cache_is_switched_off(env: None) -> None:
    low_level = build_agent_server()._mcp_server
    low_level._tool_cache["x"] = object()  # type: ignore[assignment]
    assert dict(low_level._tool_cache) == {}
    assert asyncio.run(low_level._get_cached_tool_definition("x")) is None


def test_the_provider_serves_nothing_outside_an_agent_request(env: None) -> None:
    provider = next(p for p in build_agent_server().providers if isinstance(p, AgentToolsetProvider))
    assert asyncio.run(provider.list_tools()) == []
    assert asyncio.run(provider.get_tool("listPets")) is None


def test_the_catalog_server_never_mounts_the_agent_toolsets() -> None:
    from apiome_mcp.server import mcp

    assert not any(isinstance(provider, AgentToolsetProvider) for provider in mcp.providers)


def test_invocation_config_reads_the_upstream_settings(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MCP_AGENT_UPSTREAM_TIMEOUT_SECONDS", "7")
    monkeypatch.setenv("APIOME_MCP_AGENT_UPSTREAM_MAX_RETRIES", "0")
    monkeypatch.setenv("APIOME_MCP_AGENT_RESPONSE_MAX_BYTES", "2048")
    monkeypatch.setenv("APIOME_MCP_MOCK_INVOCATION_BASE_URL", "http://mock:8775/")
    config = InvocationConfig.from_settings(Settings())  # type: ignore[call-arg]
    assert (config.policy.timeout_seconds, config.policy.max_retries, config.policy.max_response_bytes) == (7, 0, 2048)
    assert config.mock_base_url == "http://mock:8775"


def test_the_mock_root_defaults_to_the_public_one(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MCP_MOCK_PUBLIC_BASE_URL", "https://mock.example.com")
    monkeypatch.setenv("APIOME_MCP_MOCK_INVOCATION_BASE_URL", " ")
    assert InvocationConfig.from_settings(Settings()).mock_base_url == "https://mock.example.com"  # type: ignore[call-arg]


def test_a_bad_mock_invocation_root_fails_fast(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MCP_MOCK_INVOCATION_BASE_URL", "file:///etc")
    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]


def test_invocation_config_reads_the_request_cap(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APIOME_MCP_AGENT_REQUEST_MAX_BYTES", "4096")
    assert InvocationConfig.from_settings(Settings()).max_request_bytes == 4096  # type: ignore[call-arg]
    monkeypatch.setenv("APIOME_MCP_AGENT_REQUEST_MAX_BYTES", "10")
    with pytest.raises(ValueError):
        Settings()  # type: ignore[call-arg]


def test_the_rails_default_to_fail_closed(env: None) -> None:
    settings = Settings()  # type: ignore[call-arg]
    assert settings.agent_upstream_allow_private is False
    assert settings.agent_request_max_bytes == 1_048_576


def test_the_lifespan_client_is_guarded_with_the_mock_root_exempt(env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from apiome_mcp.agent_safety_rails import UpstreamBlockedError
    from apiome_mcp.agent_server import _http_client

    monkeypatch.setenv("APIOME_MCP_MOCK_INVOCATION_BASE_URL", "http://mock.internal:8775")
    client = _http_client(Settings())  # type: ignore[call-arg]
    transport = client._transport
    assert transport._origin == ("http", "mock.internal", 8775)  # type: ignore[attr-defined]
    assert client.follow_redirects is False and client.trust_env is False

    async def run() -> None:
        async with client:
            await client.get("http://127.0.0.1:9/")

    with pytest.raises(UpstreamBlockedError):
        asyncio.run(run())
