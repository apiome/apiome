"""Tests for the generated MCP reference pages (DOCS-1.11, #5628).

The first test is the **drift gate**: it renders every page from the catalog server's registry and
compares it byte-for-byte with the committed copy, so adding or re-describing a tool without
regenerating the pages turns CI red. The rest check the renderer on a small server of its own.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Literal

import pytest
from fastmcp import FastMCP
from pydantic import Field

from apiome_mcp.reference_doc import (
    MCP_REFERENCE_DOCS_DIR,
    REGENERATE_COMMAND,
    McpRegistry,
    anchor,
    collect_registry,
    escape_prose,
    load_registry,
    render_pages,
    table_cell,
    type_label,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DOCS_DIR = REPO_ROOT / MCP_REFERENCE_DOCS_DIR


# ---------------------------------------------------------------------------------------------
# The drift gate
# ---------------------------------------------------------------------------------------------


def test_committed_pages_match_the_registry() -> None:
    """Every committed page equals a fresh render, and the folder holds nothing else."""
    pages = render_pages(load_registry())
    committed = {path.name for path in DOCS_DIR.iterdir() if path.is_file()}
    assert committed == set(pages), f"{MCP_REFERENCE_DOCS_DIR} files differ. Regenerate with: {REGENERATE_COMMAND}"
    for name, content in pages.items():
        assert (DOCS_DIR / name).read_text(encoding="utf-8") == content, (
            f"{MCP_REFERENCE_DOCS_DIR}/{name} is out of date. Regenerate with: {REGENERATE_COMMAND}"
        )


def test_every_catalog_tool_is_documented_under_its_anchor() -> None:
    """Each registered tool has a heading on the tools page."""
    registry = load_registry()
    tools_page = render_pages(registry)["tools.md"]
    assert registry.tools, "the catalog server registers tools"
    for tool in registry.tools:
        assert f"## `{tool.name}` {{#{anchor(tool.name)}}}" in tools_page


# ---------------------------------------------------------------------------------------------
# The renderer, on a server of its own
# ---------------------------------------------------------------------------------------------


def _tiny_server() -> FastMCP:
    """Two tools: one with every argument shape the table handles, one with none."""
    server = FastMCP("Tiny")

    @server.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
    def find_widgets(
        query: Annotated[str, Field(description="Text to match | including pipes.")],
        colour: Literal["red", "blue"] = "red",
        limit: int | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Find widgets by name.

        Returns a list. Callers send `Bearer <key>` outside code as Bearer <key>.
        """
        return []

    @server.tool
    def ping() -> dict[str, str]:
        """Say hello."""
        return {}

    return server


@pytest.fixture(scope="module")
def tiny() -> McpRegistry:
    """The tiny server's registry."""
    return asyncio.run(collect_registry(_tiny_server()))


def test_registry_is_sorted_and_carries_annotations(tiny: McpRegistry) -> None:
    assert [tool.name for tool in tiny.tools] == ["find_widgets", "ping"]
    assert tiny.tools[0].annotations == {"readOnlyHint": True, "openWorldHint": False}
    assert tiny.server_name == "Tiny"


def test_tools_page_parameters_table(tiny: McpRegistry) -> None:
    page = render_pages(tiny)["tools.md"]
    assert "| `query` | string | yes |  | Text to match \\| including pipes. |" in page
    assert '| `colour` | one of: "red", "blue" | no | `"red"` |  |' in page
    assert "| `limit` | integer or null | no | `null` |  |" in page
    assert "| `tags` | array of string or null | no | `null` |  |" in page
    assert "**Hints:** Read-only: yes, Open world: no." in page
    assert "**Returns:** `result` — array of object." in page
    assert "## `ping` {#ping}" in page
    assert "Takes no arguments." in page


def test_prose_escapes_angle_brackets_only_outside_code(tiny: McpRegistry) -> None:
    page = render_pages(tiny)["tools.md"]
    assert "`Bearer <key>` outside code as Bearer &lt;key&gt;." in page


def test_empty_resources_and_prompts_say_so(tiny: McpRegistry) -> None:
    pages = render_pages(tiny)
    assert "registers **no resources** and no resource templates" in pages["resources.md"]
    assert "registers **no prompts**" in pages["prompts.md"]


def test_resources_and_prompts_are_listed_when_registered() -> None:
    server = FastMCP("WithExtras")

    @server.resource("memo://readme", name="readme", description="The readme.", mime_type="text/plain")
    def readme() -> str:
        return "hi"

    @server.prompt
    def review(spec_id: str, focus: str = "security") -> str:
        """Review a spec."""
        return spec_id + focus

    pages = render_pages(asyncio.run(collect_registry(server)))
    assert "| `memo://readme` | readme | resource | text/plain | The readme. |" in pages["resources.md"]
    assert "## `review` {#review}" in pages["prompts.md"]
    # FastMCP may fill in its own argument description, so only the name and requiredness are pinned.
    assert "| `spec_id` | yes |" in pages["prompts.md"]
    assert "| `focus` | no |" in pages["prompts.md"]


def test_front_matter_and_index(tiny: McpRegistry) -> None:
    pages = render_pages(tiny)
    for name in ("index.mdx", "tools.md", "resources.md", "prompts.md"):
        head = pages[name].split("---\n")[1]
        assert "generated: apiome-mcp/scripts/generate_mcp_reference_docs.py" in head
        description = next(line for line in head.splitlines() if line.startswith("description:"))
        assert len(description.split()) - 1 <= 14, f"{name}: description over 14 words"
    index = pages["index.mdx"]
    assert "<!--" not in index, "MDX pages cannot hold HTML comments"
    assert "| [Tools](./tools.md) | 2 |" in index


@pytest.mark.parametrize(
    ("schema", "label"),
    [
        ({"type": "string"}, "string"),
        ({"anyOf": [{"type": "null"}, {"type": "integer"}]}, "integer or null"),
        ({"type": ["string", "null"]}, "string or null"),
        ({"type": "array", "items": {"$ref": "#/$defs/Widget"}}, "array of Widget"),
        ({"enum": ["a", 1]}, 'one of: "a", 1'),
        ({"const": "x"}, 'constant "x"'),
        ({"oneOf": [{"type": "string"}, {"type": "string"}]}, "string"),
        ({}, "any"),
        ("nonsense", "any"),
    ],
)
def test_type_label(schema: object, label: str) -> None:
    assert type_label(schema) == label


def test_cell_and_anchor_helpers() -> None:
    assert table_cell("a |\n b <c>") == "a \\| b &lt;c&gt;"
    assert escape_prose("x <y> `<z>` ``<w>``") == "x &lt;y&gt; `<z>` ``<w>``"
    assert anchor("spec.describe_operation") == "spec-describe-operation"
