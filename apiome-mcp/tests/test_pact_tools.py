"""MCP pact tools — PFX-4.5 (#6942).

The tools against a mocked apiome-rest (``httpx.MockTransport``): each calls its internal pact route with the
key's tenant, the key id and the internal service token; selectors and options are translated to the REST
field names (snake_case and the broker's camelCase both accepted); the bounded answer comes back as REST sent
it. Every failure path is a ``ToolError`` that names the problem: a key limited to projects or to another
tenant, unknown selector keys, wrongly typed values, out-of-range limits (never clamped), neither or both
destinations, a missing argument, the route not configured, unreachable, and a REST refusal (with its code).
Last, the tools are live on the server with read-only / write annotations and in the shared registry.
"""

from __future__ import annotations

import asyncio
import functools
import json
import uuid
from typing import Any

import httpx
import pytest
from fastmcp.exceptions import ToolError
from pydantic import SecretStr

from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.pact_tools import (
    build_pact_can_i_deploy_response,
    build_pact_list_response,
    build_pact_matrix_response,
    build_pact_record_deployment_response,
)
from apiome_mcp.scope import Scope
from apiome_mcp.settings import Settings


def _sync(fn: Any) -> Any:
    """Run an async test with ``asyncio.run``, as the rest of this suite does (no pytest async plugin)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


TENANT = str(uuid.uuid4())
OTHER_TENANT = str(uuid.uuid4())
KEY = str(uuid.uuid4())
TOKEN = "internal-token-0123456789"

VERDICT = {
    "summary": {"deployable": None, "reason": "missing", "success": 0, "failed": 0, "unknown": 1},
    "notices": [{"type": "warning", "code": "no-verification-result", "text": "missing"}],
    "noticesTruncated": False,
    "rows": [],
    "rowsTotal": 0,
    "rowsTruncated": False,
    "retryAfterSeconds": 10,
}


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(
        database_url="postgresql://u:p@localhost:5432/apiome",
        internal_secret="internal-secret-0123456789",
        rest_internal_url="http://rest:8000/",
        rest_internal_service_token=SecretStr(TOKEN),
    )
    values.update(overrides)
    return Settings(**values)


def _auth(scope: Scope | None = None) -> McpAuthContext:
    return McpAuthContext(key_id=KEY, tenant_id=TENANT, label="test", scope=scope or Scope())


class _Rest:
    """A recording mock of apiome-rest's internal pact routes."""

    def __init__(self, status: int = 200, payload: Any = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.payload = payload

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json=self.payload if self.payload is not None else VERDICT)

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


# ---------------------------------------------------------------------------------------------
# What each tool sends
# ---------------------------------------------------------------------------------------------


@_sync
async def test_pact_list_sends_the_key_filters_and_page() -> None:
    page = {"items": [{"sha": "abc"}], "hasMore": True, "nextCursor": "c1"}
    rest = _Rest(payload=page)
    result = await build_pact_list_response(
        auth_ctx=_auth(), provider=" Ledger API ", limit=10, cursor="c0", settings=_settings(), transport=rest.transport
    )
    assert result == page
    request = rest.requests[0]
    assert str(request.url) == "http://rest:8000/v1/internal/mcp/pacts/list"
    assert request.headers["X-Internal-Service-Token"] == TOKEN
    assert rest.body() == {
        "tenantId": TENANT,
        "keyId": KEY,
        "provider": "Ledger API",
        "consumer": None,
        "limit": 10,
        "cursor": "c0",
    }


@_sync
async def test_pact_list_defaults_the_page_size() -> None:
    rest = _Rest(payload={"items": [], "hasMore": False})
    await build_pact_list_response(auth_ctx=_auth(), settings=_settings(), transport=rest.transport)
    assert rest.body()["limit"] == 50


@_sync
async def test_pact_matrix_translates_selectors_and_options() -> None:
    rest = _Rest()
    result = await build_pact_matrix_response(
        auth_ctx=_auth(),
        selectors=[
            {"pacticipant": "Billing", "version": "2.0.0"},
            {"pacticipant": "Ledger", "main_branch": True, "latest": True},
            {"pacticipant": "Audit", "mainBranch": False, "branch": "feat", "tag": "prod", "environment": "test"},
        ],
        latestby="cvpv",
        to_environment="production",
        ignore=["Search", {"pacticipant": "Mail", "version": "1"}],
        limit=200,
        max_rows=5,
        settings=_settings(),
        transport=rest.transport,
    )
    assert result["summary"]["deployable"] is None and result["retryAfterSeconds"] == 10
    assert str(rest.requests[0].url).endswith("/v1/internal/mcp/pacts/matrix")
    assert rest.body() == {
        "tenantId": TENANT,
        "keyId": KEY,
        "selectors": [
            {"pacticipant": "Billing", "version": "2.0.0"},
            {"pacticipant": "Ledger", "mainBranch": True, "latest": True},
            {"pacticipant": "Audit", "mainBranch": False, "branch": "feat", "tag": "prod", "environment": "test"},
        ],
        "latestby": "cvpv",
        "toEnvironment": "production",
        "toTag": None,
        "latest": None,
        "mainBranch": None,
        "ignore": [{"pacticipant": "Search"}, {"pacticipant": "Mail", "version": "1"}],
        "limit": 200,
        "maxRows": 5,
    }


@_sync
async def test_pact_can_i_deploy_sends_one_version_and_its_destination() -> None:
    rest = _Rest()
    await build_pact_can_i_deploy_response(
        auth_ctx=_auth(),
        pacticipant="Billing",
        version="2.0.0",
        to_tag="prod",
        ignore=["Search"],
        settings=_settings(),
        transport=rest.transport,
    )
    assert str(rest.requests[0].url).endswith("/v1/internal/mcp/pacts/can-i-deploy")
    assert rest.body() == {
        "tenantId": TENANT,
        "keyId": KEY,
        "pacticipant": "Billing",
        "version": "2.0.0",
        "toEnvironment": None,
        "toTag": "prod",
        "ignore": [{"pacticipant": "Search"}],
        "maxRows": 50,
    }


@_sync
async def test_pact_record_deployment_sends_the_environment_name() -> None:
    answer = {"created": True, "deployment": {"uuid": "d1", "version": "2.0.0"}}
    rest = _Rest(payload=answer)
    result = await build_pact_record_deployment_response(
        auth_ctx=_auth(),
        pacticipant="Billing",
        version="2.0.0",
        environment="production",
        application_instance="eu-1",
        settings=_settings(),
        transport=rest.transport,
    )
    assert result == answer
    assert str(rest.requests[0].url).endswith("/v1/internal/mcp/pacts/record-deployment")
    assert rest.body() == {
        "tenantId": TENANT,
        "keyId": KEY,
        "pacticipant": "Billing",
        "version": "2.0.0",
        "environment": "production",
        "applicationInstance": "eu-1",
    }


# ---------------------------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------------------------


@_sync
async def test_a_project_limited_key_is_refused_before_any_call() -> None:
    rest = _Rest()
    with pytest.raises(ToolError, match="limited to projects"):
        await build_pact_list_response(
            auth_ctx=_auth(Scope(projects=[str(uuid.uuid4())])), settings=_settings(), transport=rest.transport
        )
    assert rest.requests == []


@_sync
async def test_a_key_scoped_to_another_tenant_is_refused() -> None:
    rest = _Rest()
    with pytest.raises(ToolError, match="own workspace"):
        await build_pact_can_i_deploy_response(
            auth_ctx=_auth(Scope(tenants=[OTHER_TENANT])),
            pacticipant="Billing",
            version="1",
            to_environment="production",
            settings=_settings(),
            transport=rest.transport,
        )
    assert rest.requests == []


@_sync
async def test_a_key_scoped_to_its_own_tenant_is_allowed() -> None:
    rest = _Rest(payload={"items": [], "hasMore": False})
    await build_pact_list_response(
        auth_ctx=_auth(Scope(tenants=[TENANT])), settings=_settings(), transport=rest.transport
    )
    assert len(rest.requests) == 1


@pytest.mark.parametrize(
    ("selectors", "message"),
    [
        (None, "selectors is required"),
        ([], "selectors is required"),
        ("Billing", "selectors must be a list"),
        (["Billing"], r"selectors\[0\] must be an object"),
        ([{"version": "1"}], r"selectors\[0\]\.pacticipant is required"),
        ([{"pacticipant": "  "}], r"selectors\[0\]\.pacticipant is required"),
        ([{"pacticipant": "B", "versoin": "1"}], r"unsupported keys \['versoin'\]; supported: branch, environment"),
        ([{"pacticipant": "B", "latest": "yes"}], r"selectors\[0\]\.latest must be true or false"),
        ([{"pacticipant": "B", "version": 2}], r"selectors\[0\]\.version must be a string"),
    ],
)
def test_malformed_selectors_are_refused_with_the_reason(selectors: Any, message: str) -> None:
    rest = _Rest()
    with pytest.raises(ToolError, match=message):
        asyncio.run(
            build_pact_matrix_response(
                auth_ctx=_auth(), selectors=selectors, settings=_settings(), transport=rest.transport
            )
        )
    assert rest.requests == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"latestby": "everything"}, "latestby must be one of cvp, cvpv, cp"),
        ({"latest": "true"}, "latest must be true or false"),
        ({"max_rows": 0}, "max_rows must be from 1 to 100"),
        ({"max_rows": 101}, r"max_rows must be from 1 to 100 \(got 101\)"),
        ({"max_rows": True}, "max_rows must be a whole number"),
        ({"limit": 1001}, "limit must be from 1 to 1000"),
        ({"ignore": [{"pacticipant": "S", "tag": "x"}]}, r"ignore\[0\] has unsupported keys \['tag'\]"),
        ({"ignore": [{"pacticipant": "S"}] * 50}, "at most 50 selectors"),
    ],
)
def test_malformed_matrix_options_are_refused(kwargs: dict[str, Any], message: str) -> None:
    rest = _Rest()
    with pytest.raises(ToolError, match=message):
        asyncio.run(
            build_pact_matrix_response(
                auth_ctx=_auth(),
                selectors=[{"pacticipant": "Billing"}],
                settings=_settings(),
                transport=rest.transport,
                **kwargs,
            )
        )
    assert rest.requests == []


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"to_environment": None, "to_tag": None}, "Give to_environment"),
        ({"to_environment": "production", "to_tag": "prod"}, "not both"),
        ({"to_environment": "production", "pacticipant": ""}, "pacticipant is required"),
        ({"to_environment": "production", "version": None}, "version is required"),
    ],
)
def test_can_i_deploy_needs_exactly_one_destination_and_a_version(kwargs: dict[str, Any], message: str) -> None:
    arguments: dict[str, Any] = {"pacticipant": "Billing", "version": "1"}
    arguments.update(kwargs)
    rest = _Rest()
    with pytest.raises(ToolError, match=message):
        asyncio.run(
            build_pact_can_i_deploy_response(
                auth_ctx=_auth(), settings=_settings(), transport=rest.transport, **arguments
            )
        )
    assert rest.requests == []


@pytest.mark.parametrize("missing", ["pacticipant", "version", "environment"])
def test_record_deployment_needs_every_argument(missing: str) -> None:
    arguments: dict[str, Any] = {"pacticipant": "Billing", "version": "1", "environment": "production"}
    arguments[missing] = "   "
    rest = _Rest()
    with pytest.raises(ToolError, match=f"{missing} is required"):
        asyncio.run(
            build_pact_record_deployment_response(
                auth_ctx=_auth(), settings=_settings(), transport=rest.transport, **arguments
            )
        )
    assert rest.requests == []


@_sync
async def test_list_limits_are_refused_not_clamped() -> None:
    with pytest.raises(ToolError, match="limit must be from 1 to 100"):
        await build_pact_list_response(auth_ctx=_auth(), limit=500, settings=_settings(), transport=_Rest().transport)


@_sync
async def test_a_rest_refusal_carries_its_code_and_message() -> None:
    rest = _Rest(
        status=403,
        payload={"detail": {"code": "mcp-pact-key-has-no-owner", "message": "This MCP API key has no owner"}},
    )
    with pytest.raises(ToolError, match=r"Pact request refused \(403\): \[mcp-pact-key-has-no-owner\] This MCP"):
        await build_pact_list_response(auth_ctx=_auth(), settings=_settings(), transport=rest.transport)


@_sync
async def test_a_plain_permission_refusal_is_reported() -> None:
    rest = _Rest(status=403, payload={"detail": "Permission denied: pacts:create is required"})
    with pytest.raises(ToolError, match=r"refused \(403\): Permission denied: pacts:create is required"):
        await build_pact_record_deployment_response(
            auth_ctx=_auth(),
            pacticipant="Billing",
            version="1",
            environment="production",
            settings=_settings(),
            transport=rest.transport,
        )


@_sync
async def test_pact_tools_without_configuration_are_refused() -> None:
    with pytest.raises(ToolError, match="Pact request over MCP is not configured"):
        await build_pact_list_response(auth_ctx=_auth(), settings=_settings(rest_internal_url=None))


@_sync
async def test_an_unreachable_rest_is_a_tool_error() -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ToolError, match="could not be reached for the pact request"):
        await build_pact_list_response(auth_ctx=_auth(), settings=_settings(), transport=httpx.MockTransport(boom))


@_sync
async def test_a_non_object_answer_is_a_tool_error() -> None:
    with pytest.raises(ToolError, match="unexpected payload"):
        await build_pact_list_response(auth_ctx=_auth(), settings=_settings(), transport=_Rest(payload=[1]).transport)


# ---------------------------------------------------------------------------------------------
# The server
# ---------------------------------------------------------------------------------------------


@_sync
async def test_the_tools_are_live_annotated_and_registered() -> None:
    from app.mcp_tool_registry import is_registered_mcp_tool, mcp_tools_by_toolset

    from apiome_mcp.server import mcp

    tools = {tool.name: tool for tool in await mcp.list_tools()}
    names = {"pact.list", "pact.matrix", "pact.can_i_deploy", "pact.record_deployment"}
    assert names <= set(tools)
    assert all(is_registered_mcp_tool(name) for name in names)
    assert {d.id for d in mcp_tools_by_toolset("pact")} == names
    for name in ("pact.list", "pact.matrix", "pact.can_i_deploy"):
        assert tools[name].annotations is not None and tools[name].annotations.readOnlyHint is True
    write = tools["pact.record_deployment"].annotations
    assert write is not None and write.readOnlyHint is False and write.destructiveHint is False
