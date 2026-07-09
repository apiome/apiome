"""CLI entrypoint for the apiome-mock console script and ``python -m`` runs."""

from __future__ import annotations

import argparse
import sys

from apiome_mock import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="apiome-mock",
        description="Apiome mock server (FastAPI).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    serve_parser = subparsers.add_parser(
        "serve",
        help="Validate configuration and run the mock HTTP server.",
    )
    serve_parser.add_argument(
        "--host",
        default=None,
        metavar="ADDR",
        help="Bind address (default: APIOME_MOCK_HTTP_HOST).",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=None,
        metavar="PORT",
        help="TCP port (default: APIOME_MOCK_HTTP_PORT).",
    )

    args = parser.parse_args()

    if args.command == "serve":
        import uvicorn
        from pydantic import ValidationError

        from apiome_mock.logging_config import configure_logging
        from apiome_mock.server import create_app
        from apiome_mock.settings import get_settings

        try:
            settings = get_settings()
        except ValidationError as exc:
            print(f"Configuration error:\n{exc}", file=sys.stderr)
            raise SystemExit(2) from exc

        configure_logging(settings)
        host = (args.host.strip() if args.host else None) or settings.http_host
        if not host:
            print("Bind host must be non-empty.", file=sys.stderr)
            raise SystemExit(2)
        port = args.port if args.port is not None else settings.http_port
        if not (1 <= port <= 65535):
            print("--port must be between 1 and 65535", file=sys.stderr)
            raise SystemExit(2)

        uvicorn.run(create_app(), host=host, port=port, log_level=settings.log_level.lower())
        return

    parser.print_help()
