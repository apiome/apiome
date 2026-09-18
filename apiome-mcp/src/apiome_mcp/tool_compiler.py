"""Operation→MCP-tool compiler for the agent runtime — AGX-1.1 (#4529).

The mapping itself — tool names, descriptions, input schemas, output descriptions, the
MCP keyword subset, determinism — lives in ``apiome-rest`` as ``app.mcp_tool_mapping`` and
is re-exported here unchanged, the same way :mod:`apiome_mcp.effective_policy` shares the
MTG-1.4 resolver. One implementation is the point: the managed invocation runtime
(AGX-2.1), the REST curation surface (AGX-1.2), the MCP tool-definition emitter (MFX-32.1)
and the generated MCP server artifact (SDK-4.5) must never disagree about what a tool is
called or what it takes.

What this module adds is the MCP-process side of the contract:

* :func:`to_mcp_tool` — a compiled tool as the MCP SDK's own ``tools/list`` entry model,
  validated by that model;
* :func:`compile_openapi_toolset` — compile straight from a published revision's OpenAPI
  document (the one :func:`apiome_mcp.spec_get_openapi_tool.build_spec_get_openapi_response`
  builds), normalizing it through the registered OpenAPI/Swagger import adapter first.

Nothing here touches the catalog server's ``tools/list`` (see ``docs/AGX_COORDINATION.md``):
agent toolsets are served by the AGX runtime, not merged into the catalog registry. The
rules the compiler applies are documented in ``docs/TOOL_COMPILER.md``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import mcp.types as mt
from app.mcp_tool_mapping import (
    JSON_SCHEMA_TYPES,
    LOSS_MCP_KEYWORD_DOWNGRADED,
    LOSS_MCP_KEYWORD_DROPPED,
    LOSS_MCP_ROOT_COMBINATOR,
    LOSS_MCP_UNRESOLVED_REF,
    MCP_SCHEMA_KEYWORDS,
    MCP_TOOL_MAPPING_VERSION,
    McpToolDefinition,
    McpToolMappingError,
    McpToolOutput,
    McpToolset,
    UnknownOperationError,
    compile_mcp_tools,
    mcp_schema_violations,
    sanitize_mcp_schema,
    success_response,
    validate_mcp_tool,
)
from app.openapi_import_source import OpenApiImportSource

__all__ = [
    "JSON_SCHEMA_TYPES",
    "LOSS_MCP_KEYWORD_DOWNGRADED",
    "LOSS_MCP_KEYWORD_DROPPED",
    "LOSS_MCP_ROOT_COMBINATOR",
    "LOSS_MCP_UNRESOLVED_REF",
    "MCP_SCHEMA_KEYWORDS",
    "MCP_TOOL_MAPPING_VERSION",
    "McpToolDefinition",
    "McpToolMappingError",
    "McpToolOutput",
    "McpToolset",
    "UnknownOperationError",
    "compile_mcp_tools",
    "compile_openapi_toolset",
    "mcp_schema_violations",
    "sanitize_mcp_schema",
    "success_response",
    "to_mcp_tool",
    "to_mcp_tools",
    "validate_mcp_tool",
]


def to_mcp_tool(tool: McpToolDefinition) -> mt.Tool:
    """Return ``tool`` as the MCP SDK's ``tools/list`` entry.

    Args:
        tool: A compiled tool.

    Returns:
        The ``mcp.types.Tool`` carrying the tool's name, description and input schema.

    Raises:
        pydantic.ValidationError: If the MCP SDK rejects the entry — which a toolset from
            :func:`compile_mcp_tools` never produces, since every tool is validated before
            the toolset is returned.
    """
    return mt.Tool.model_validate(tool.to_mcp())


def to_mcp_tools(toolset: McpToolset) -> list[mt.Tool]:
    """Return every tool of ``toolset`` as an MCP SDK ``tools/list`` entry, in order."""
    return [to_mcp_tool(tool) for tool in toolset.tools]


def compile_openapi_toolset(
    document: Mapping[str, Any],
    *,
    exposed: Iterable[str] | None = None,
) -> McpToolset:
    """Compile a published revision's OpenAPI (or Swagger) document into its toolset.

    The document is normalized through the same import adapter the import pipeline uses,
    so an OpenAPI 3.x, Swagger 2.0 or Swagger 1.2 description all reach the compiler as
    the canonical model their import would have produced.

    Args:
        document: The parsed document (for example a generated OpenAPI 3.1 revision).
        exposed: Canonical operation keys to expose (``GET /pets/{petId}``); ``None``
            exposes every callable, non-deprecated operation.

    Returns:
        The compiled :class:`McpToolset`.

    Raises:
        app.import_source.ImportSourceError: If ``document`` is not an OpenAPI/Swagger
            description.
        UnknownOperationError: If an exposed key names no callable operation.
    """
    api = OpenApiImportSource().normalize(dict(document), include_raw=False)
    return compile_mcp_tools(api, exposed=exposed)
