#!/usr/bin/env bash
#
# Run script for MCP server
# Starts in streaming-http mode

source .venv/bin/activate
uv run apiome-mcp serve --transport http

