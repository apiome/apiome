"""CLI entrypoint for the apiome-mcp console script and ``python -m`` runs."""

from __future__ import annotations

import argparse
import asyncio
import sys

from apiome_mcp import __version__


async def _run_stdio_transport() -> None:
    from apiome_mcp.server import mcp

    await mcp.run_stdio_async()


async def _run_keys_revoke(prefix: str) -> int:
    import structlog

    from apiome_mcp.database_pool import create_async_pool, ping_pool
    from apiome_mcp.key_admin import revoke_mcp_keys_by_prefix
    from apiome_mcp.logging_config import configure_logging
    from apiome_mcp.mcp_auth import normalize_stored_prefix
    from apiome_mcp.settings import get_settings

    settings = get_settings()
    configure_logging(settings)
    log = structlog.get_logger(__name__)
    canonical = normalize_stored_prefix(prefix)
    pool = create_async_pool(settings, open=False)
    await pool.open()
    try:
        await ping_pool(pool)
        revoked = await revoke_mcp_keys_by_prefix(pool, canonical)
        log.info("mcp_keys_revoked", prefix=canonical, count=revoked)
    finally:
        await pool.close()
    print(f"Revoked {revoked} active key(s) matching prefix {canonical}.")
    return 0 if revoked else 1


async def _run_http_transport(host: str, port: int, *, log_level: str) -> None:
    """Streamable HTTP via FastMCP (``http_app`` → ``create_streamable_http_app``); serves MCP at ``/mcp``."""
    from starlette.middleware import Middleware as StarletteMiddleware

    from apiome_mcp.http_credential_middleware import HttpCredentialExtractionMiddleware
    from apiome_mcp.server import mcp

    await mcp.run_http_async(
        transport="streamable-http",
        host=host,
        port=port,
        path="/mcp",
        log_level=log_level.lower(),
        middleware=[StarletteMiddleware(HttpCredentialExtractionMiddleware)],
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="apiome-mcp",
        description="Apiome Model Context Protocol server (FastMCP).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser(
        "serve",
        help="Validate configuration and optionally run the MCP server.",
    )
    serve_parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default=None,
        metavar="NAME",
        help=(
            "Run with this transport (omit to validate env and exit). "
            "Use stdio for Claude Desktop; use http for streamable HTTP (MCP at /mcp)."
        ),
    )
    serve_parser.add_argument(
        "--host",
        default=None,
        metavar="ADDR",
        help="Bind address for HTTP transport (default: APIOME_MCP_HTTP_HOST).",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="TCP port for HTTP transport (default: APIOME_MCP_HTTP_PORT).",
    )

    keys_parser = subparsers.add_parser(
        "keys",
        help="MCP API key administration (same commands as ``mcp keys`` when using the mcp entrypoint).",
    )
    keys_sub = keys_parser.add_subparsers(dest="keys_command", required=True)
    revoke_parser = keys_sub.add_parser(
        "revoke",
        help="Revoke all active keys whose stored prefix matches (see key issuance / dashboard prefix).",
    )
    revoke_parser.add_argument(
        "prefix",
        help="Key prefix: first 12 characters, with or without a trailing '...'.",
    )

    args = parser.parse_args()

    if args.command == "serve":
        import structlog
        from pydantic import ValidationError
        from structlog.contextvars import bound_contextvars

        from apiome_mcp.logging_config import configure_logging
        from apiome_mcp.settings import get_settings

        try:
            settings = get_settings()
        except ValidationError as exc:
            print(f"Configuration error:\n{exc}", file=sys.stderr)
            raise SystemExit(2)
        configure_logging(settings)
        log = structlog.get_logger(__name__)
        if args.transport == "stdio":
            with bound_contextvars(request_id="cli-serve-stdio", tool_name=None):
                log.info("mcp_stdio_starting")
            asyncio.run(_run_stdio_transport())
            return
        if args.transport == "http":
            if args.port is not None and not (1 <= args.port <= 65535):
                print("--port must be between 1 and 65535", file=sys.stderr)
                raise SystemExit(2)
            host = (args.host.strip() if args.host else None) or settings.http_host
            if not host:
                print("Bind host must be non-empty.", file=sys.stderr)
                raise SystemExit(2)
            port = args.port if args.port is not None else settings.http_port
            with bound_contextvars(request_id="cli-serve-http", tool_name=None):
                log.info("mcp_http_starting", host=host, port=port, path="/mcp")
            asyncio.run(_run_http_transport(host, port, log_level=settings.log_level))
            return
        with bound_contextvars(request_id="cli-serve", tool_name=None):
            log.info(
                "mcp_configuration_validated",
                detail="Pass --transport stdio or --transport http to run the server.",
            )
        raise SystemExit(0)

    if args.command == "keys":
        from pydantic import ValidationError

        from apiome_mcp.mcp_auth import normalize_stored_prefix
        from apiome_mcp.settings import get_settings

        get_settings.cache_clear()
        try:
            get_settings()
        except ValidationError as exc:
            print(f"Configuration error:\n{exc}", file=sys.stderr)
            raise SystemExit(2)
        if args.keys_command == "revoke":
            try:
                normalize_stored_prefix(args.prefix)
            except ValueError as exc:
                print(str(exc), file=sys.stderr)
                raise SystemExit(2)
            code = asyncio.run(_run_keys_revoke(args.prefix))
            get_settings.cache_clear()
            raise SystemExit(code)

    parser.print_help()
