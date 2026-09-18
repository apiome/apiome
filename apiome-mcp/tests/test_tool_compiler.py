"""Operation→MCP-tool compiler, MCP side — AGX-1.1 (#4529).

The mapping is ``app.mcp_tool_mapping`` in apiome-rest; these tests pin what the MCP
process relies on:

* the re-export *is* the REST implementation (one mapping, never two);
* Petstore compiles to tools the MCP SDK's own ``Tool`` model and the JSON-Schema 2020-12
  metaschema both accept;
* **round trip**: the compiled tools, registered on a throwaway FastMCP server and listed
  through an MCP client, come back exactly as compiled — and arguments shaped the way an
  agent forms them validate, while malformed ones do not. This is the in-process stand-in
  for "tools listed, schemas accepted, arguments form correctly" in Claude Desktop.

The throwaway server never touches the catalog server (``apiome_mcp.server.mcp``), whose
``tools/list`` stays the unfiltered catalog registry (``docs/AGX_COORDINATION.md``).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import app.mcp_tool_mapping as rest_mapping
import mcp.types as mt
import pytest
import yaml
from app.import_source import ImportSourceError
from fastmcp import Client, FastMCP
from fastmcp.tools import Tool
from fastmcp.tools.tool import ToolResult
from jsonschema import Draft202012Validator

from apiome_mcp import tool_compiler
from apiome_mcp.tool_compiler import (
    McpToolset,
    UnknownOperationError,
    compile_openapi_toolset,
    to_mcp_tool,
    to_mcp_tools,
    validate_mcp_tool,
)

_PETSTORE = Path(__file__).resolve().parents[2] / "apiome-ui" / "examples" / "openapi" / "30-openapi-3.0-petstore.yaml"

_PETSTORE_TOOLS = {"listPets", "createPet", "getPetById", "updatePet", "deletePet"}


def _petstore_document() -> dict[str, Any]:
    loaded = yaml.safe_load(_PETSTORE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _petstore() -> McpToolset:
    return compile_openapi_toolset(_petstore_document())


class _EchoTool(Tool):
    """A compiled tool served as-is: its schema is the compiled ``inputSchema``.

    ``run`` echoes the arguments it received, so a test can see exactly what an MCP
    client delivered to the server for a given call.
    """

    async def run(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(content=[mt.TextContent(type="text", text=json.dumps(arguments, sort_keys=True))])


def _serve(toolset: McpToolset) -> FastMCP:
    server = FastMCP(name="agx-compiled-toolset")
    for tool in toolset.tools:
        server.add_tool(_EchoTool(name=tool.name, description=tool.description, parameters=tool.input_schema))
    return server


# ===========================================================================
# One mapping
# ===========================================================================


@pytest.mark.parametrize("name", rest_mapping.__all__)
def test_the_compiler_re_exports_the_rest_mapping_unchanged(name: str) -> None:
    assert getattr(tool_compiler, name) is getattr(rest_mapping, name)


# ===========================================================================
# Petstore
# ===========================================================================


def test_petstore_compiles_one_tool_per_operation() -> None:
    assert {tool.name for tool in _petstore().tools} == _PETSTORE_TOOLS


def test_petstore_tools_validate_as_mcp_sdk_tools() -> None:
    for sdk_tool, tool in zip(to_mcp_tools(_petstore()), _petstore().tools, strict=True):
        assert isinstance(sdk_tool, mt.Tool)
        assert sdk_tool.name == tool.name
        assert sdk_tool.inputSchema == tool.input_schema
        assert sdk_tool.outputSchema is None, "outputSchema is AGX-2.1's decision, not the compiler's"
        assert validate_mcp_tool(tool.to_mcp()) == []
        Draft202012Validator.check_schema(sdk_tool.inputSchema)


def test_to_mcp_tool_carries_the_output_sentence_in_the_description() -> None:
    listing = next(tool for tool in _petstore().tools if tool.name == "listPets")
    description = to_mcp_tool(listing).description
    assert description is not None
    assert description.endswith("Returns HTTP 200 application/json (array of Pet): Success")


def test_compiling_the_same_document_twice_is_byte_identical() -> None:
    assert _petstore().serialize() == _petstore().serialize()


def test_a_swagger_2_document_compiles_through_the_same_adapter() -> None:
    document = {
        "swagger": "2.0",
        "info": {"title": "Legacy", "version": "1"},
        "paths": {
            "/items/{id}": {
                "get": {
                    "operationId": "getItem",
                    "parameters": [{"name": "id", "in": "path", "required": True, "type": "string"}],
                    "responses": {"200": {"description": "The item", "schema": {"type": "object"}}},
                }
            }
        },
    }
    [tool] = compile_openapi_toolset(document).tools
    assert tool.name == "getItem"
    assert tool.input_schema["required"] == ["id"]


def test_exposure_is_passed_through() -> None:
    toolset = compile_openapi_toolset(_petstore_document(), exposed=["GET /pets"])
    assert [tool.name for tool in toolset.tools] == ["listPets"]
    with pytest.raises(UnknownOperationError):
        compile_openapi_toolset(_petstore_document(), exposed=["GET /nowhere"])


def test_a_non_openapi_document_is_rejected() -> None:
    with pytest.raises(ImportSourceError):
        compile_openapi_toolset({"asyncapi": "3.0.0"})


# ===========================================================================
# Round trip through an MCP client
# ===========================================================================


def _listed(toolset: McpToolset) -> list[mt.Tool]:
    async def run() -> list[mt.Tool]:
        async with Client(_serve(toolset)) as client:
            return await client.list_tools()

    return asyncio.run(run())


def test_tools_list_returns_the_compiled_tools_unchanged() -> None:
    toolset = _petstore()
    listed = {tool.name: tool for tool in _listed(toolset)}
    assert set(listed) == _PETSTORE_TOOLS
    for tool in toolset.tools:
        entry = listed[tool.name]
        assert entry.description == tool.description
        assert entry.inputSchema == tool.input_schema


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("listPets", {"limit": 10, "offset": 0, "tags": ["dog", "cat"]}),
        ("createPet", {"id": 7, "name": "Rex", "tag": "dog", "age": 3}),
        ("getPetById", {"petId": 7}),
        ("deletePet", {"petId": 7}),
    ],
)
def test_arguments_formed_from_the_listed_schema_validate_and_arrive(
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    toolset = _petstore()
    listed = {tool.name: tool for tool in _listed(toolset)}
    Draft202012Validator(listed[tool_name].inputSchema).validate(arguments)

    async def call() -> Any:
        async with Client(_serve(toolset)) as client:
            return await client.call_tool(tool_name, arguments)

    result = asyncio.run(call())
    first = result.content[0]
    assert isinstance(first, mt.TextContent)
    assert json.loads(first.text) == arguments


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        ("listPets", {"limit": 0}),
        ("listPets", {"limit": "ten"}),
        ("createPet", {"name": "Rex"}),
        ("getPetById", {}),
    ],
)
def test_malformed_arguments_are_rejected_by_the_listed_schema(tool_name: str, arguments: dict[str, Any]) -> None:
    listed = {tool.name: tool for tool in _listed(_petstore())}
    assert not Draft202012Validator(listed[tool_name].inputSchema).is_valid(arguments)
