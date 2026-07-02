from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from apiome_mcp.http_credential_middleware import (
    HttpCredentialExtractionMiddleware,
    StashHttpBearerInToolContextMiddleware,
    bearer_secret_from_authorization_header,
    get_http_bearer_from_context,
    http_bearer_token_state_key,
)


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("Basic xyz", None),
        ("Bearer", None),
        ("Bearer ", None),
        ("Bearer  ", None),
        ("bEaReR secret-token", "secret-token"),
        ("Bearer  secret-token  ", "secret-token"),
    ],
)
def test_bearer_secret_from_authorization_header(header: str | None, expected: str | None) -> None:
    assert bearer_secret_from_authorization_header(header) == expected


def test_http_bearer_token_state_key_stable() -> None:
    assert http_bearer_token_state_key() == "apiome_mcp_http_bearer_token"


def test_asgi_and_fastmcp_middleware_chain_with_bearer() -> None:
    async def run() -> None:
        fc = MagicMock()
        fc.set_state = AsyncMock()

        async def inner_app(scope: dict, receive: object, send: object) -> None:
            stash = StashHttpBearerInToolContextMiddleware()
            mctx = MagicMock()
            mctx.fastmcp_context = fc

            async def call_next(_ctx: object) -> str:
                return "ok"

            await stash.on_call_tool(mctx, call_next)

        mw = HttpCredentialExtractionMiddleware(inner_app)
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer chained-secret")],
        }
        await mw(scope, None, None)
        fc.set_state.assert_awaited_once_with(
            "apiome_mcp_http_bearer_token",
            "chained-secret",
            serializable=False,
        )

    asyncio.run(run())


def test_asgi_and_fastmcp_middleware_chain_anonymous_without_bearer() -> None:
    async def run() -> None:
        fc = MagicMock()
        fc.set_state = AsyncMock()

        async def inner_app(scope: dict, receive: object, send: object) -> None:
            stash = StashHttpBearerInToolContextMiddleware()
            mctx = MagicMock()
            mctx.fastmcp_context = fc

            async def call_next(_ctx: object) -> str:
                return "ok"

            await stash.on_call_tool(mctx, call_next)

        mw = HttpCredentialExtractionMiddleware(inner_app)
        scope: dict = {"type": "http", "headers": []}
        await mw(scope, None, None)
        fc.set_state.assert_awaited_once_with(
            "apiome_mcp_http_bearer_token",
            None,
            serializable=False,
        )

    asyncio.run(run())


def test_http_credential_extraction_skips_non_http() -> None:
    async def run() -> None:
        called = False

        async def app(scope: dict, receive: object, send: object) -> None:
            nonlocal called
            called = True

        mw = HttpCredentialExtractionMiddleware(app)
        await mw({"type": "lifespan"}, None, None)
        assert called

    asyncio.run(run())


def test_stash_middleware_skips_when_no_fastmcp_context() -> None:
    async def run() -> None:
        mw = StashHttpBearerInToolContextMiddleware()
        mctx = MagicMock()
        mctx.fastmcp_context = None

        async def call_next(_ctx: object) -> str:
            return "ok"

        assert await mw.on_call_tool(mctx, call_next) == "ok"

    asyncio.run(run())


def test_get_http_bearer_from_context_reads_state() -> None:
    async def run() -> None:
        ctx = MagicMock()
        ctx.get_state = AsyncMock(return_value="stored")

        assert await get_http_bearer_from_context(ctx) == "stored"
        ctx.get_state.assert_awaited_once_with("apiome_mcp_http_bearer_token")

    asyncio.run(run())
