"""CLI entrypoint for the objectified-mcp console script and ``python -m`` runs."""

from __future__ import annotations

import argparse

from objectified_mcp import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="objectified-mcp",
        description="Objectified Model Context Protocol server (FastMCP).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args()
    parser.print_help()
