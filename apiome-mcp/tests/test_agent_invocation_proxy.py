"""AGX-2.1 invocation proxy (#4533): one call → validate, build, route, inject, send, map, audit.

Runs :class:`~apiome_mcp.agent_invocation_proxy.InvocationProxy` against the in-memory Petstore
upstream and the recording pool. Pins that argument failures never reach the upstream, mock and prod
routing, server-side credential injection (and fail-closed when it cannot open), the distinct error
results, and exactly one audit row per call with the right outcome.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from app.upstream_credential_binding import CredentialInjection

from agent_runtime_fakes import (
    KEY_ID,
    TENANT_ID,
    TOOLSET_ID,
    AgentDb,
    PetstoreUpstream,
    invocation_rows,
    manifest_row,
)
from apiome_mcp.agent_access import AgentKey
from apiome_mcp.agent_invocation_proxy import InvocationConfig, InvocationProxy
from apiome_mcp.agent_toolset_source import ServedToolsetCache, load_served_toolset
from apiome_mcp.agent_upstream_auth import UpstreamCredentialUnavailableError
from apiome_mcp.agent_upstream_client import UpstreamCallPolicy

KEY = AgentKey(key_id=KEY_ID, tenant_id=TENANT_ID, toolset_id=TOOLSET_ID, tool_allowlist=frozenset())
MOCK_ROOT = "http://mock.internal:8775"
CONFIG = InvocationConfig(
    policy=UpstreamCallPolicy(timeout_seconds=0.5, budget_seconds=1.0, backoff_seconds=0.0), mock_base_url=MOCK_ROOT
)


class _Vault:
    """A credential source: an injection, nothing, or 'cannot open'."""

    def __init__(self, injection: CredentialInjection | None = None, *, broken: bool = False) -> None:
        self.injection = injection
        self.broken = broken
        self.urls: list[str] = []

    async def __call__(self, pool: Any, tenant_id: str, toolset_id: str, url: str) -> CredentialInjection | None:
        self.urls.append(url)
        if self.broken:
            raise UpstreamCredentialUnavailableError("cred")
        return self.injection


def _call(
    tool: str,
    arguments: dict[str, Any] | None,
    *,
    db: AgentDb | None = None,
    upstream: PetstoreUpstream | None = None,
    vault: _Vault | None = None,
) -> tuple[Any, PetstoreUpstream, Any]:
    db = db or AgentDb()
    upstream = upstream or PetstoreUpstream()
    pool = db.pool()
    proxy = InvocationProxy(CONFIG, credentials=vault or _Vault())

    async def run() -> Any:
        served = await load_served_toolset(pool, ServedToolsetCache(), TENANT_ID, TOOLSET_ID)  # type: ignore[arg-type]
        assert served is not None
        async with upstream.client() as client:
            return await proxy.invoke(
                pool=pool,  # type: ignore[arg-type]
                client=client,
                key=KEY,
                toolset=served,
                tool=served.tools[tool],
                arguments=arguments,
            )

    return asyncio.run(run()), upstream, pool


def _mcp(result: Any) -> Any:
    return result.to_mcp_result()


# ============================================================================
# Mock target: list and create pets
# ============================================================================


def test_list_pets_goes_to_the_mock_mount_and_returns_the_body() -> None:
    result, upstream, pool = _call("listPets", {"limit": 10, "tags": ["dog", "cat"]})
    (request,) = upstream.requests
    assert str(request.url) == f"{MOCK_ROOT}/acme/petstore/1.0.0/pets?limit=10&tags=dog,cat"
    assert request.headers["accept"] == "application/json"
    assert request.headers["user-agent"].startswith("apiome-mcp-agent/")
    assert result.structured_content["body"] == [{"id": "1", "name": "Rex", "tag": "dog"}]
    (row,) = invocation_rows(pool)
    assert (row["outcome"], row["error_code"], row["http_status"], row["target"]) == ("success", None, 200, "mock")
    assert row["response_bytes"] > 0 and row["request_bytes"] > 0


def test_create_pet_sends_the_flat_body() -> None:
    result, upstream, _ = _call("createPet", {"name": "Tom", "tag": "cat"})
    (request,) = upstream.requests
    assert (request.method, request.url.path) == ("POST", "/acme/petstore/1.0.0/pets")
    assert request.read() == b'{"name":"Tom","tag":"cat"}'
    assert result.structured_content["httpStatus"] == 201
    assert upstream.pets["2"] == {"id": "2", "name": "Tom", "tag": "cat"}


def test_the_mock_target_never_consults_the_vault() -> None:
    vault = _Vault(broken=True)
    result, _, _ = _call("listPets", {}, vault=vault)
    assert vault.urls == []
    assert result.structured_content["httpStatus"] == 200


# ============================================================================
# Validation never reaches the upstream
# ============================================================================


@pytest.mark.parametrize(
    ("tool", "arguments", "argument"),
    [
        ("createPet", {}, "(arguments)"),
        ("createPet", {"name": ""}, "name"),
        ("listPets", {"limit": 0}, "limit"),
        ("listPets", {"limit": "ten"}, "limit"),
        ("listPets", {"colour": "red"}, "colour"),
        ("showPetById", {"petId": ".."}, "petId"),
    ],
)
def test_invalid_arguments_never_reach_the_upstream(tool: str, arguments: dict[str, Any], argument: str) -> None:
    result, upstream, pool = _call(tool, arguments)
    assert upstream.requests == []
    mcp = _mcp(result)
    assert mcp.isError is True
    assert mcp.structuredContent["reason"] == "invalid_arguments"
    assert argument in [issue["argument"] for issue in mcp.structuredContent["invalidArguments"]]
    (row,) = invocation_rows(pool)
    assert (row["outcome"], row["error_code"], row["http_status"]) == ("validation_failure", "invalid_arguments", None)


# ============================================================================
# Upstream failures are distinct, with hints
# ============================================================================


def _failing(status: int, body: Any = None) -> PetstoreUpstream:
    upstream = PetstoreUpstream()
    upstream.override = lambda request: httpx.Response(status, json=body or {"detail": "failed"})
    return upstream


@pytest.mark.parametrize(
    ("status", "reason"),
    [(400, "upstream_bad_request"), (404, "upstream_not_found"), (500, "upstream_server_error")],
)
def test_upstream_errors_become_hint_carrying_results(status: int, reason: str) -> None:
    result, _, pool = _call("showPetById", {"petId": "1"}, upstream=_failing(status))
    mcp = _mcp(result)
    assert mcp.isError is True
    assert mcp.structuredContent["reason"] == reason
    assert mcp.structuredContent["httpStatus"] == status
    assert mcp.structuredContent["hint"]
    assert mcp.content[0].text.startswith(f"{reason}: ")
    (row,) = invocation_rows(pool)
    assert (row["outcome"], row["error_code"], row["http_status"]) == ("upstream_error", reason, status)


def test_a_real_404_from_the_store_names_the_identifier() -> None:
    result, _, _ = _call("showPetById", {"petId": "999"})
    assert "petId='999'" in _mcp(result).structuredContent["hint"]


def test_a_timeout_becomes_its_own_result() -> None:
    upstream = PetstoreUpstream()

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    upstream.override = slow
    result, _, pool = _call("listPets", {}, upstream=upstream)
    mcp = _mcp(result)
    assert (mcp.structuredContent["reason"], mcp.structuredContent["retryable"]) == ("upstream_timeout", True)
    assert len(upstream.requests) == 3
    assert invocation_rows(pool)[0]["error_code"] == "upstream_timeout"


def test_an_unreachable_upstream_becomes_its_own_result() -> None:
    upstream = PetstoreUpstream()

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    upstream.override = refuse
    result, _, _ = _call("createPet", {"name": "Tom"}, upstream=upstream)
    assert _mcp(result).structuredContent["reason"] == "upstream_unreachable"


# ============================================================================
# Prod target: server URL and credential injection
# ============================================================================


def test_prod_calls_the_spec_server_with_the_injected_credential() -> None:
    injection = CredentialInjection(credential_id="c", headers=(("X-Api-Key", "sk_real"),))
    vault = _Vault(injection)
    result, upstream, _ = _call(
        "showPetById",
        {"petId": "1", "X-Request-Id": "r-1"},
        db=AgentDb(manifest=manifest_row(target="prod")),
        vault=vault,
    )
    (request,) = upstream.requests
    assert str(request.url) == "https://api.petstore.example/v1/pets/1"
    assert vault.urls == ["https://api.petstore.example/v1/pets/1"]
    assert request.headers["x-api-key"] == "sk_real"
    assert request.headers["x-request-id"] == "r-1"
    assert "sk_real" not in result.content[0].text
    assert "sk_real" not in str(result.structured_content)


@pytest.mark.parametrize(
    "injection",
    [
        CredentialInjection(credential_id="c", headers=(("Authorization", "Bearer tok_secret_123"),)),
        CredentialInjection(credential_id="c", query=(("api_key", "q/secret+value"),)),
    ],
)
def test_an_echoed_credential_never_reaches_the_agent(injection: CredentialInjection) -> None:
    upstream = PetstoreUpstream()
    upstream.override = lambda request: httpx.Response(
        400,
        json={"echo": {"url": str(request.url), "authorization": request.headers.get("authorization")}},
        headers={"X-Echo": request.headers.get("authorization") or str(request.url)},
    )
    result, _, _ = _call(
        "listPets", {}, db=AgentDb(manifest=manifest_row(target="prod")), upstream=upstream, vault=_Vault(injection)
    )
    text = str(_mcp(result).model_dump())
    for secret in ("tok_secret_123", "q/secret+value", "q%2Fsecret%2Bvalue"):
        assert secret not in text
    assert "[redacted]" in text


def test_prod_without_a_bound_credential_goes_out_bare() -> None:
    result, upstream, _ = _call("listPets", {}, db=AgentDb(manifest=manifest_row(target="prod")), vault=_Vault())
    assert "x-api-key" not in upstream.requests[0].headers
    assert result.structured_content["httpStatus"] == 200


def test_a_credential_that_cannot_open_is_never_sent() -> None:
    result, upstream, pool = _call(
        "listPets", {}, db=AgentDb(manifest=manifest_row(target="prod")), vault=_Vault(broken=True)
    )
    assert upstream.requests == []
    assert _mcp(result).structuredContent["reason"] == "upstream_credential_unavailable"
    assert invocation_rows(pool)[0]["outcome"] == "internal_error"


def test_prod_without_an_absolute_server_is_not_configured() -> None:
    from agent_runtime_fakes import PETSTORE, source_item

    document = {**PETSTORE, "servers": [{"url": "/v1"}]}
    db = AgentDb(manifest=manifest_row(target="prod"), source=source_item(document))
    result, upstream, _ = _call("listPets", {}, db=db)
    assert upstream.requests == []
    assert _mcp(result).structuredContent["reason"] == "upstream_not_configured"


# ============================================================================
# Robustness
# ============================================================================


def test_an_unexpected_error_is_a_result_and_an_internal_error_row() -> None:
    upstream = PetstoreUpstream()

    def explode(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("bug")

    upstream.override = explode
    result, _, pool = _call("listPets", {}, upstream=upstream)
    assert _mcp(result).structuredContent["reason"] == "invocation_failed"
    assert (invocation_rows(pool)[0]["outcome"], invocation_rows(pool)[0]["error_code"]) == (
        "internal_error",
        "invocation_failed",
    )


def test_an_audit_failure_does_not_fail_the_call() -> None:
    db = AgentDb()
    pool = db.pool()
    pool.fail_on = "INSERT INTO apiome.agent_invocations"
    upstream = PetstoreUpstream()
    proxy = InvocationProxy(CONFIG, credentials=_Vault())

    async def run() -> Any:
        served = await load_served_toolset(pool, ServedToolsetCache(), TENANT_ID, TOOLSET_ID)  # type: ignore[arg-type]
        async with upstream.client() as client:
            return await proxy.invoke(
                pool=pool,  # type: ignore[arg-type]
                client=client,
                key=KEY,
                toolset=served,  # type: ignore[arg-type]
                tool=served.tools["listPets"],  # type: ignore[union-attr]
                arguments={},
            )

    assert asyncio.run(run()).structured_content["httpStatus"] == 200


# ============================================================================
# AGX-2.3 safety rails
# ============================================================================


def _proxy_with(config: InvocationConfig, *, db: AgentDb, client: httpx.AsyncClient, tool: str, arguments: Any) -> Any:
    pool = db.pool()
    proxy = InvocationProxy(config, credentials=_Vault())

    async def run() -> Any:
        served = await load_served_toolset(pool, ServedToolsetCache(), TENANT_ID, TOOLSET_ID)  # type: ignore[arg-type]
        assert served is not None
        async with client:
            return await proxy.invoke(
                pool=pool,  # type: ignore[arg-type]
                client=client,
                key=KEY,
                toolset=served,
                tool=served.tools[tool],
                arguments=arguments,
            )

    return asyncio.run(run()), pool


@pytest.mark.parametrize(
    ("tool", "arguments", "method"),
    [
        ("listPets", {}, "GET"),
        ("showPetById", {"petId": "1"}, "GET"),
        ("createPet", {"name": "Tom"}, "POST"),
        ("deletePet", {"petId": "1"}, "DELETE"),
    ],
)
def test_each_tool_sends_only_its_declared_method(tool: str, arguments: dict[str, Any], method: str) -> None:
    _, upstream, _ = _call(tool, arguments)
    assert [request.method for request in upstream.requests] == [method]


def test_a_get_tool_refuses_a_method_override_header() -> None:
    from agent_runtime_fakes import PETSTORE, source_item

    document = json.loads(json.dumps(PETSTORE))
    document["paths"]["/pets"]["get"]["parameters"].append(
        {"name": "X-HTTP-Method-Override", "in": "header", "schema": {"type": "string"}}
    )
    db = AgentDb(source=source_item(document))
    result, upstream, pool = _call("listPets", {"X-HTTP-Method-Override": "DELETE"}, db=db)
    assert upstream.requests == []
    payload = _mcp(result).structuredContent
    assert payload["reason"] == "method_not_allowed"
    assert "only send GET" in payload["error"]["message"] and payload["hint"]
    assert (invocation_rows(pool)[0]["outcome"], invocation_rows(pool)[0]["error_code"]) == (
        "validation_failure",
        "method_not_allowed",
    )


def test_a_matching_method_override_header_is_allowed() -> None:
    from agent_runtime_fakes import PETSTORE, source_item

    document = json.loads(json.dumps(PETSTORE))
    document["paths"]["/pets"]["get"]["parameters"].append(
        {"name": "X-HTTP-Method-Override", "in": "header", "schema": {"type": "string"}}
    )
    result, upstream, _ = _call("listPets", {"X-HTTP-Method-Override": "get"}, db=AgentDb(source=source_item(document)))
    assert [request.method for request in upstream.requests] == ["GET"]
    assert result.structured_content["httpStatus"] == 200


def test_an_oversized_request_body_is_refused_before_sending() -> None:
    upstream = PetstoreUpstream()
    config = InvocationConfig(policy=CONFIG.policy, mock_base_url=MOCK_ROOT, max_request_bytes=64)
    result, pool = _proxy_with(
        config, db=AgentDb(), client=upstream.client(), tool="createPet", arguments={"name": "x" * 200}
    )
    assert upstream.requests == []
    payload = _mcp(result).structuredContent
    assert payload["reason"] == "request_too_large"
    assert "64-byte limit" in payload["error"]["message"] and payload["hint"]
    assert invocation_rows(pool)[0]["error_code"] == "request_too_large"


def test_a_body_at_the_cap_is_sent() -> None:
    upstream = PetstoreUpstream()
    body = b'{"name":"Tom"}'
    config = InvocationConfig(policy=CONFIG.policy, mock_base_url=MOCK_ROOT, max_request_bytes=len(body))
    result, _ = _proxy_with(config, db=AgentDb(), client=upstream.client(), tool="createPet", arguments={"name": "Tom"})
    assert upstream.requests[0].read() == body
    assert result.structured_content["httpStatus"] == 201


@pytest.mark.parametrize("address", ["169.254.169.254", "10.0.0.7", "127.0.0.1", "::ffff:192.168.1.1"])
def test_a_prod_server_resolving_to_a_private_address_is_blocked(address: str) -> None:
    from apiome_mcp.agent_safety_rails import GuardedNetworkBackend, build_upstream_client

    resolved: list[str] = []

    async def resolve(host: str, port: int, timeout: float | None) -> list[str]:
        resolved.append(host)
        return [address]

    client = build_upstream_client(
        mock_base_url=MOCK_ROOT, timeout_seconds=1.0, backend=GuardedNetworkBackend(resolver=resolve)
    )
    result, pool = _proxy_with(
        CONFIG, db=AgentDb(manifest=manifest_row(target="prod")), client=client, tool="listPets", arguments={}
    )
    payload = _mcp(result).structuredContent
    assert payload["reason"] == "upstream_blocked"
    assert "api.petstore.example" in payload["error"]["message"]
    assert address not in str(payload)
    assert payload["retryable"] is False
    # Refused once, not retried.
    assert resolved == ["api.petstore.example"]
    assert (invocation_rows(pool)[0]["outcome"], invocation_rows(pool)[0]["error_code"]) == (
        "internal_error",
        "upstream_blocked",
    )
