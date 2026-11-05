"""MCP ``export.targets`` / ``version.export`` — MFX-40.1 (#4339).

The tools against a mocked apiome-rest (``httpx.MockTransport``): they call the internal export routes with
the key's tenant and the internal service token; any target key passes straight through (no per-format
code); the fidelity report comes back as REST sent it; a running job is collected with ``job_id``; an
artifact outside the key's scope, a missing argument, export not configured and a REST refusal are
``ToolError``s that name the problem. Last, the tools are live on the server and in the shared registry.
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

from apiome_mcp.export_tools import build_export_targets_response, build_version_export_response
from apiome_mcp.mcp_auth import McpAuthContext
from apiome_mcp.scope import Scope
from apiome_mcp.settings import Settings


def _sync(fn: Any) -> Any:
    """Run an async test with ``asyncio.run``, as the rest of this suite does (no pytest async plugin)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return asyncio.run(fn(*args, **kwargs))

    return wrapper


TENANT = str(uuid.uuid4())
PROJECT = str(uuid.uuid4())
OTHER = str(uuid.uuid4())
TOKEN = "internal-token-0123456789"

REPORT = {"summary": {"tier": "lossy", "preserved_percent": 72},
          "report": {"items": [{"construct": "Op.subscribe", "kind": "drop", "severity": "critical"}]},
          "advisory": {"headline": "This export loses fidelity"}}


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = dict(database_url="postgresql://u:p@localhost:5432/apiome",
                                  internal_secret="internal-secret-0123456789",
                                  rest_internal_url="http://rest:8000/", rest_internal_service_token=SecretStr(TOKEN),
                                  export_wait_seconds=5)
    values.update(overrides)
    return Settings(**values)


def _auth(projects: tuple[str, ...] = ()) -> McpAuthContext:
    return McpAuthContext(key_id="k1", tenant_id=TENANT, label="test", scope=Scope(projects=list(projects)))


class _Rest:
    """A recording mock of apiome-rest's internal export routes."""

    def __init__(self, status: int = 200, payload: Any = None) -> None:
        self.requests: list[httpx.Request] = []
        self.status = status
        self.payload = payload

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.payload is not None:
            return httpx.Response(self.status, json=self.payload)
        if request.url.path.endswith("/targets"):
            return httpx.Response(200, json={"artifact": PROJECT, "targets": [
                {"descriptor": {"key": "openapi"}, "fidelity": {"tier": "lossless"}},
                {"descriptor": {"key": "brand-new-format"}, "fidelity": {"tier": "lossy"}}]})
        body = json.loads(request.content)
        return httpx.Response(200, json={"jobId": body.get("jobId") or "job-1", "state": "completed",
                                         "artifact": PROJECT, "target": body.get("target"), "fidelity": REPORT,
                                         "files": [{"path": "a.txt", "sizeBytes": 2, "content": "hi"}],
                                         "contentInline": True})

    def body(self, index: int = -1) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


@_sync
async def test_export_targets_calls_rest_with_the_key_s_tenant_and_token() -> None:
    rest = _Rest()
    result = await build_export_targets_response(auth_ctx=_auth(), artifact=f" {PROJECT} ", version="1.0.0",
                                                 settings=_settings(), transport=httpx.MockTransport(rest))
    assert [t["descriptor"]["key"] for t in result["targets"]] == ["openapi", "brand-new-format"]
    request = rest.requests[0]
    assert str(request.url) == "http://rest:8000/v1/internal/mcp/export/targets"
    assert request.headers["X-Internal-Service-Token"] == TOKEN
    assert rest.body() == {"tenantId": TENANT, "artifact": PROJECT, "version": "1.0.0"}


@_sync
async def test_version_export_passes_any_target_through_and_returns_the_fidelity_report() -> None:
    rest = _Rest()
    result = await build_version_export_response(
        auth_ctx=_auth(), artifact=PROJECT, target="brand-new-format", options={"flavor": "x"}, confirm=True,
        settings=_settings(), transport=httpx.MockTransport(rest))
    assert rest.body() == {"tenantId": TENANT, "artifact": PROJECT, "version": None, "target": "brand-new-format",
                           "options": {"flavor": "x"}, "confirm": True, "waitSeconds": 5}
    assert result["fidelity"]["report"]["items"][0]["severity"] == "critical"
    assert result["files"][0]["content"] == "hi"


@_sync
async def test_a_running_job_is_collected_by_job_id() -> None:
    rest = _Rest()
    result = await build_version_export_response(auth_ctx=_auth(), job_id="job-7", settings=_settings(),
                                                 transport=httpx.MockTransport(rest))
    assert rest.body() == {"tenantId": TENANT, "jobId": "job-7", "waitSeconds": 5}
    assert result["jobId"] == "job-7"


@_sync
async def test_the_key_s_scope_limits_what_it_exports_and_collects() -> None:
    scoped = _auth(projects=(OTHER,))
    rest = _Rest()
    with pytest.raises(ToolError, match="scope does not include that artifact"):
        await build_export_targets_response(auth_ctx=scoped, artifact=PROJECT, settings=_settings(),
                                            transport=httpx.MockTransport(rest))
    with pytest.raises(ToolError, match="scope does not include that artifact"):
        await build_version_export_response(auth_ctx=scoped, artifact=PROJECT, target="openapi",
                                            settings=_settings(), transport=httpx.MockTransport(rest))
    assert rest.requests == []
    with pytest.raises(ToolError, match="scope does not include that export's artifact"):
        await build_version_export_response(auth_ctx=scoped, job_id="job-1", settings=_settings(),
                                            transport=httpx.MockTransport(rest))


@pytest.mark.parametrize("kwargs, message", [
    ({"artifact": "", "target": "openapi"}, "artifact is required"),
    ({"artifact": PROJECT, "target": " "}, "target is required"),
])
@_sync
async def test_missing_arguments_are_named(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ToolError, match=message):
        await build_version_export_response(auth_ctx=_auth(), settings=_settings(),
                                            transport=httpx.MockTransport(_Rest()), **kwargs)


@_sync
async def test_export_without_configuration_is_refused() -> None:
    for settings in (_settings(rest_internal_url=None), _settings(rest_internal_service_token=None)):
        with pytest.raises(ToolError, match="not configured"):
            await build_export_targets_response(auth_ctx=_auth(), artifact=PROJECT, settings=settings,
                                                transport=httpx.MockTransport(_Rest()))


@_sync
async def test_a_rest_refusal_names_its_reason() -> None:
    rest = _Rest(status=400, payload={"detail": {"code": "mcp-export-refused",
                                                 "message": "Unsupported export target 'nope'"}})
    with pytest.raises(ToolError, match=r"Export refused \(400\): Unsupported export target 'nope'"):
        await build_version_export_response(auth_ctx=_auth(), artifact=PROJECT, target="nope", settings=_settings(),
                                            transport=httpx.MockTransport(rest))
    validation = _Rest(status=422, payload={"detail": [{"msg": "bad option"}]})
    with pytest.raises(ToolError, match="bad option"):
        await build_export_targets_response(auth_ctx=_auth(), artifact=PROJECT, settings=_settings(),
                                            transport=httpx.MockTransport(validation))


@_sync
async def test_an_unreachable_rest_is_a_tool_error() -> None:
    def boom(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ToolError, match="could not be reached"):
        await build_export_targets_response(auth_ctx=_auth(), artifact=PROJECT, settings=_settings(),
                                            transport=httpx.MockTransport(boom))


@_sync
async def test_the_tools_are_live_and_registered() -> None:
    from app.mcp_tool_registry import is_registered_mcp_tool

    from apiome_mcp.server import mcp

    names = {tool.name for tool in await mcp.list_tools()}
    assert {"export.targets", "version.export"} <= names
    assert is_registered_mcp_tool("export.targets") and is_registered_mcp_tool("version.export")
