"""The generated MCP reference pages of the documentation site (DOCS-1.11, #5628).

``scripts/generate_mcp_reference_docs.py`` writes the pages under
``apiome-docs/docs/reference/mcp/`` from the registry of the catalog server
(:data:`apiome_mcp.server.mcp`): one page for the tools, one for the resources, one for the
prompts, and an index. ``tests/test_mcp_reference_docs.py`` renders them in memory and compares
them with the committed copies, so adding, renaming or re-describing a tool without regenerating
the pages fails CI.

Reading the registry needs no database and no environment: importing ``server`` only builds the
FastMCP instance (its lifespan, which opens the pool, runs when the server starts), and the
``list_*`` calls read the in-memory registry.

Everything rendered here is deterministic — sorted by name, no timestamps, no versions and no
values that come from the environment — so regenerating an unchanged registry is a no-op.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass, field
from typing import Any

from fastmcp import FastMCP

#: Repository-relative folder the pages are written to.
MCP_REFERENCE_DOCS_DIR = "apiome-docs/docs/reference/mcp"

#: Repository-relative path of the generator, recorded in each page's front matter.
GENERATOR_PATH = "apiome-mcp/scripts/generate_mcp_reference_docs.py"

#: The command that regenerates the pages, quoted in the stale-page messages.
REGENERATE_COMMAND = "cd apiome-mcp && uv run python scripts/generate_mcp_reference_docs.py"

#: The streamable-HTTP path of the catalog server (``apiome_mcp.http_app.MCP_PATH``).
CATALOG_HTTP_PATH = "/mcp"

#: The streamable-HTTP path of the agent runtime (AGX-2.1), mounted beside the catalog.
AGENT_HTTP_PATH = "/agent/mcp"

#: ``Settings.http_port``'s default — the port ``apiome-mcp serve --transport http`` binds.
DEFAULT_HTTP_PORT = 8765

#: Tool annotation keys, in the order the MCP specification lists them, with a reader's label.
ANNOTATION_LABELS: tuple[tuple[str, str], ...] = (
    ("title", "Title"),
    ("readOnlyHint", "Read-only"),
    ("destructiveHint", "Destructive"),
    ("idempotentHint", "Idempotent"),
    ("openWorldHint", "Open world"),
)


@dataclass(frozen=True)
class ToolDoc:
    """One tool, as ``tools/list`` describes it.

    Attributes:
        name: The tool name, e.g. ``spec.describe``.
        title: The optional display title.
        description: The description, with its docstring indentation removed.
        annotations: Behaviour hints (``readOnlyHint`` …); empty when the tool declares none.
        input_schema: The JSON Schema of the arguments.
        output_schema: The JSON Schema of the structured result, or ``None``.
    """

    name: str
    title: str | None
    description: str
    annotations: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class ResourceDoc:
    """One resource or resource template.

    Attributes:
        uri: The URI, or the URI template for a template.
        name: The resource name.
        description: What it holds.
        mime_type: Its media type, when declared.
        template: ``True`` for a resource template.
    """

    uri: str
    name: str
    description: str
    mime_type: str | None
    template: bool


@dataclass(frozen=True)
class PromptDoc:
    """One prompt.

    Attributes:
        name: The prompt name.
        description: What it produces.
        arguments: ``(name, required, description)`` for each argument, in declaration order.
    """

    name: str
    description: str
    arguments: tuple[tuple[str, bool, str], ...]


@dataclass(frozen=True)
class McpRegistry:
    """Everything a server registers, sorted by name.

    Attributes:
        server_name: The server's name (``FastMCP(name)``).
        tools: The tools.
        resources: Resources and resource templates.
        prompts: The prompts.
    """

    server_name: str
    tools: tuple[ToolDoc, ...]
    resources: tuple[ResourceDoc, ...]
    prompts: tuple[PromptDoc, ...]


def _clean(text: str | None) -> str:
    """A description with docstring indentation removed and outer blank lines trimmed.

    Args:
        text: The raw description, or ``None``.

    Returns:
        The cleaned text; ``""`` for ``None``.
    """
    return inspect.cleandoc(text or "").strip()


async def collect_registry(server: FastMCP) -> McpRegistry:
    """Read a server's tools, resources and prompts without starting it.

    Args:
        server: The FastMCP instance.

    Returns:
        The registry, each list sorted by name (resources by URI).
    """
    tools = []
    for tool in await server.list_tools():
        wire = tool.to_mcp_tool().model_dump(exclude_none=True)
        annotations = wire.get("annotations") or {}
        tools.append(
            ToolDoc(
                name=wire["name"],
                title=wire.get("title") or annotations.get("title"),
                description=_clean(wire.get("description")),
                annotations={key: value for key, value in annotations.items() if value is not None},
                input_schema=wire.get("inputSchema") or {},
                output_schema=wire.get("outputSchema"),
            )
        )

    resources = [
        ResourceDoc(
            uri=str(resource.uri),
            name=resource.name,
            description=_clean(resource.description),
            mime_type=resource.mime_type,
            template=False,
        )
        for resource in await server.list_resources()
    ]
    resources += [
        ResourceDoc(
            uri=template.uri_template,
            name=template.name,
            description=_clean(template.description),
            mime_type=template.mime_type,
            template=True,
        )
        for template in await server.list_resource_templates()
    ]

    prompts = [
        PromptDoc(
            name=prompt.name,
            description=_clean(prompt.description),
            arguments=tuple(
                (argument.name, bool(argument.required), _clean(argument.description))
                for argument in (prompt.arguments or [])
            ),
        )
        for prompt in await server.list_prompts()
    ]

    return McpRegistry(
        server_name=server.name,
        tools=tuple(sorted(tools, key=lambda tool: tool.name)),
        resources=tuple(sorted(resources, key=lambda resource: resource.uri)),
        prompts=tuple(sorted(prompts, key=lambda prompt: prompt.name)),
    )


def load_registry(server: FastMCP | None = None) -> McpRegistry:
    """Synchronous wrapper around :func:`collect_registry`.

    Args:
        server: The instance to read; defaults to the catalog server, :data:`apiome_mcp.server.mcp`.

    Returns:
        The registry.
    """
    if server is None:
        from apiome_mcp.server import mcp

        server = mcp
    return asyncio.run(collect_registry(server))


# ---------------------------------------------------------------------------------------------
# CommonMark helpers
# ---------------------------------------------------------------------------------------------

#: A code span: a run of backticks, its content, and the same run again.
_CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.DOTALL)


def escape_prose(text: str) -> str:
    """Make text safe as CommonMark prose: ``<`` and ``>`` become entities outside code spans.

    Inside a code span an entity would print literally, so spans are left alone.

    Args:
        text: Prose that may contain ``<…>`` (e.g. ``Bearer <MCP API key>``) and code spans.

    Returns:
        The escaped text.
    """
    out: list[str] = []
    position = 0
    for match in _CODE_SPAN.finditer(text):
        out.append(text[position : match.start()].replace("<", "&lt;").replace(">", "&gt;"))
        out.append(match.group(0))
        position = match.end()
    out.append(text[position:].replace("<", "&lt;").replace(">", "&gt;"))
    return "".join(out)


def table_cell(text: str) -> str:
    """Make text safe inside a Markdown table cell: one line, ``|`` escaped, ``<``/``>`` escaped.

    Args:
        text: Any text.

    Returns:
        The text as a single table cell.
    """
    one_line = " ".join(text.split())
    return escape_prose(one_line).replace("|", "\\|")


def anchor(name: str) -> str:
    """The heading id for a tool or prompt name: lower case, non-alphanumerics to hyphens.

    Args:
        name: e.g. ``spec.describe_operation``.

    Returns:
        e.g. ``spec-describe-operation``.
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _ref_name(ref: str) -> str:
    """The last segment of a ``$ref``, e.g. ``#/$defs/Filter`` → ``Filter``."""
    return ref.rsplit("/", 1)[-1]


def type_label(schema: Any) -> str:
    """A short, readable type for a JSON Schema.

    Handles ``$ref`` (by name), ``const``, ``enum`` (listing the values), arrays (``array of …``),
    ``anyOf`` / ``oneOf`` and type lists (joined with ``or``; ``null`` reads as "or null"), and
    falls back to ``any``.

    Args:
        schema: A JSON Schema (or anything else, which reads as ``any``).

    Returns:
        e.g. ``string``, ``integer or null``, ``array of string``, ``one of: "a", "b"``.
    """
    if not isinstance(schema, dict):
        return "any"
    if "$ref" in schema:
        return _ref_name(schema["$ref"])
    if "const" in schema:
        return f"constant {json.dumps(schema['const'])}"
    if "enum" in schema:
        return "one of: " + ", ".join(json.dumps(value) for value in schema["enum"])
    for combinator in ("anyOf", "oneOf"):
        if combinator in schema:
            return _join_alternatives([type_label(option) for option in schema[combinator]])
    kind = schema.get("type")
    if isinstance(kind, list):
        return _join_alternatives([type_label({**schema, "type": item}) for item in kind])
    if kind == "array":
        items = schema.get("items")
        return f"array of {type_label(items)}" if items else "array"
    if isinstance(kind, str):
        return kind
    return "any"


def _join_alternatives(labels: list[str]) -> str:
    """Join alternative types, putting ``null`` last as "or null".

    Args:
        labels: The alternatives' labels.

    Returns:
        e.g. ``string or null``.
    """
    rest = [label for label in labels if label != "null"]
    joined = " or ".join(dict.fromkeys(rest)) or "null"
    return f"{joined} or null" if "null" in labels and rest else joined


def _front_matter(title: str, description: str, position: int) -> str:
    """The front matter every generated page carries.

    Args:
        title: Page title.
        description: At most 14 words.
        position: ``sidebar_position``.

    Returns:
        The YAML block and a "generated" comment; joining it with ``\n`` leaves one blank line.
    """
    return (
        "---\n"
        f"title: {json.dumps(title)}\n"
        f"description: {json.dumps(description)}\n"
        f"sidebar_position: {position}\n"
        "tags: [mcp, reference]\n"
        f"generated: {GENERATOR_PATH}\n"
        "---\n\n"
        f"<!-- Generated by {GENERATOR_PATH} from the apiome-mcp server registry. "
        "Do not edit by hand. -->\n"
    )


def _generated_note() -> str:
    """The closing note naming the regenerate command."""
    return f"*This page is generated from the server's registry; regenerate it with `{REGENERATE_COMMAND}`.*\n"


# ---------------------------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------------------------


def _parameters_table(schema: dict[str, Any]) -> list[str]:
    """The arguments of a tool as a Markdown table, or a sentence when it takes none.

    Args:
        schema: The tool's input JSON Schema.

    Returns:
        The lines.
    """
    properties: dict[str, Any] = schema.get("properties") or {}
    if not properties:
        return ["Takes no arguments."]
    required = set(schema.get("required") or [])
    lines = ["| Argument | Type | Required | Default | Description |", "| --- | --- | --- | --- | --- |"]
    for name, prop in properties.items():
        prop = prop if isinstance(prop, dict) else {}
        default = f"`{json.dumps(prop['default'])}`" if "default" in prop else ""
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{name}`",
                    table_cell(type_label(prop)),
                    "yes" if name in required else "no",
                    default,
                    table_cell(_clean(prop.get("description"))),
                ]
            )
            + " |"
        )
    return lines


def _returns_lines(schema: dict[str, Any] | None) -> list[str]:
    """What a tool returns, from its output schema.

    FastMCP wraps a non-object result in ``{"result": …}`` and marks the schema with
    ``x-fastmcp-wrap-result``; that reads as the wrapped value.

    Args:
        schema: The output JSON Schema, or ``None``.

    Returns:
        The lines; a sentence when the tool declares no structured output.
    """
    if not schema:
        return ["**Returns:** unstructured content (no output schema)."]
    properties: dict[str, Any] = schema.get("properties") or {}
    if schema.get("x-fastmcp-wrap-result") and "result" in properties:
        return [f"**Returns:** `result` — {table_cell(type_label(properties['result']))}."]
    if not properties:
        return [f"**Returns:** {table_cell(type_label(schema))}."]
    required = set(schema.get("required") or [])
    lines = ["**Returns:**", "", "| Field | Type | Always present |", "| --- | --- | --- |"]
    for name, prop in properties.items():
        lines.append(f"| `{name}` | {table_cell(type_label(prop))} | {'yes' if name in required else 'no'} |")
    return lines


def render_tools_page(registry: McpRegistry) -> str:
    """The ``tools.md`` page: every tool, its arguments and what it returns.

    Args:
        registry: The server's registry.

    Returns:
        The page.
    """
    lines = [
        _front_matter("MCP tools", "Every tool the Apiome MCP server exposes, with its arguments and results.", 2),
        f"The **{escape_prose(registry.server_name)}** catalog server registers "
        f"**{len(registry.tools)}** tools. Call them with `tools/call` over stdio or streamable HTTP "
        f"(`{CATALOG_HTTP_PATH}`); see the [MCP quick-start](../mcp-quickstart.md) to connect a host.",
        "",
    ]
    if registry.tools:
        lines += ["| Tool | Summary |", "| --- | --- |"]
        for tool in registry.tools:
            summary = tool.description.split("\n\n", 1)[0]
            summary = re.split(r"(?<=[.!?])\s", " ".join(summary.split()), maxsplit=1)[0]
            lines.append(f"| [`{tool.name}`](#{anchor(tool.name)}) | {table_cell(summary)} |")
        lines.append("")
    for tool in registry.tools:
        lines += [f"## `{tool.name}` {{#{anchor(tool.name)}}}", ""]
        if tool.title:
            lines += [f"*{escape_prose(tool.title)}*", ""]
        if tool.description:
            lines += [escape_prose(tool.description), ""]
        hints = [
            (label, tool.annotations[key])
            for key, label in ANNOTATION_LABELS
            if key in tool.annotations and key != "title"
        ]
        if hints:
            rendered = ", ".join(f"{label}: {'yes' if value else 'no'}" for label, value in hints)
            lines += [f"**Hints:** {rendered}.", ""]
        lines += ["**Arguments:**", ""] + _parameters_table(tool.input_schema) + [""]
        lines += _returns_lines(tool.output_schema) + [""]
    lines.append(_generated_note())
    return "\n".join(lines)


def render_resources_page(registry: McpRegistry) -> str:
    """The ``resources.md`` page: every resource and resource template, or a note that there are none.

    Args:
        registry: The server's registry.

    Returns:
        The page.
    """
    lines = [_front_matter("MCP resources", "The resources the Apiome MCP server registers for `resources/read`.", 3)]
    if not registry.resources:
        lines += [
            f"The **{escape_prose(registry.server_name)}** catalog server registers **no resources** and no "
            "resource templates. Specifications are read through [tools](./tools.md) such as "
            "`spec.get_openapi` instead.",
            "",
        ]
    else:
        lines += ["| URI | Name | Kind | Media type | Description |", "| --- | --- | --- | --- | --- |"]
        for resource in registry.resources:
            lines.append(
                f"| `{resource.uri}` | {table_cell(resource.name)} | "
                f"{'template' if resource.template else 'resource'} | {table_cell(resource.mime_type or '')} | "
                f"{table_cell(resource.description)} |"
            )
        lines.append("")
    lines.append(_generated_note())
    return "\n".join(lines)


def render_prompts_page(registry: McpRegistry) -> str:
    """The ``prompts.md`` page: every prompt and its arguments, or a note that there are none.

    Args:
        registry: The server's registry.

    Returns:
        The page.
    """
    lines = [_front_matter("MCP prompts", "The prompts the Apiome MCP server registers for `prompts/get`.", 4)]
    if not registry.prompts:
        lines += [
            f"The **{escape_prose(registry.server_name)}** catalog server registers **no prompts**.",
            "",
        ]
    for prompt in registry.prompts:
        lines += [f"## `{prompt.name}` {{#{anchor(prompt.name)}}}", ""]
        if prompt.description:
            lines += [escape_prose(prompt.description), ""]
        if prompt.arguments:
            lines += ["| Argument | Required | Description |", "| --- | --- | --- |"]
            for name, required, description in prompt.arguments:
                lines.append(f"| `{name}` | {'yes' if required else 'no'} | {table_cell(description)} |")
        else:
            lines.append("Takes no arguments.")
        lines.append("")
    lines.append(_generated_note())
    return "\n".join(lines)


def render_index_page(registry: McpRegistry) -> str:
    """The section's ``index.mdx``: how to reach the server, the counts, and where to go next.

    MDX, so nothing here may contain a bare ``{`` or ``<`` — the text is fixed apart from the
    server name and the counts.

    Args:
        registry: The server's registry.

    Returns:
        The page.
    """
    header = _front_matter(
        "MCP reference", "Tools, resources and prompts of the Apiome MCP server, from its registry.", 1
    )
    # MDX does not accept HTML comments; use an MDX comment instead.
    header = header.replace("<!-- ", "{/* ").replace(" -->", " */}")
    name = re.sub(r"[^A-Za-z0-9 ._-]", "", registry.server_name)
    return "\n".join(
        [
            header,
            f"The **{name}** MCP server (`apiome-mcp`) serves the published-spec catalog to MCP hosts. "
            "Run it with `apiome-mcp serve --transport stdio` for a desktop host, or "
            f"`apiome-mcp serve --transport http` for streamable HTTP (port {DEFAULT_HTTP_PORT} by default).",
            "",
            "| Endpoint | Serves |",
            "| --- | --- |",
            f"| `{CATALOG_HTTP_PATH}` | The catalog server documented here |",
            f"| `{AGENT_HTTP_PATH}` | The agent runtime: each agent toolset's compiled tools |",
            "| `/health` | Liveness probe (HTTP 200; does not query Postgres) |",
            "",
            "| Registry | Count |",
            "| --- | --- |",
            f"| [Tools](./tools.md) | {len(registry.tools)} |",
            f"| [Resources](./resources.md) | {len(registry.resources)} |",
            f"| [Prompts](./prompts.md) | {len(registry.prompts)} |",
            "",
            f"Agent toolsets on `{AGENT_HTTP_PATH}` are compiled per toolset from a project's API, so their "
            "tools are not listed here — see [Agent access](../../bring-in/agent-access.mdx).",
            "",
            "## Rule catalogs",
            "",
            "Apiome also lints MCP servers you import:",
            "",
            "- [MCP conformance rules](../../govern/mcp-conformance-rules.md)",
            "- [MCP surface lint rules](../../govern/mcp-surface-lint-rules.md)",
            "- [MCP trust posture rules](../../govern/mcp-trust-posture-rules.md)",
            "",
            "To connect a host step by step, see the [MCP quick-start](../mcp-quickstart.md).",
            "",
            _generated_note(),
        ]
    )


def render_category() -> str:
    """The section's ``_category_.json`` (sidebar label and position)."""
    return json.dumps({"label": "MCP", "position": 7, "collapsible": True, "collapsed": True}, indent=2) + "\n"


def render_pages(registry: McpRegistry) -> dict[str, str]:
    """Every file of the section, by file name.

    Args:
        registry: The server's registry.

    Returns:
        ``{file name: content}`` for ``_category_.json``, ``index.mdx``, ``tools.md``,
        ``resources.md`` and ``prompts.md``.
    """
    return {
        "_category_.json": render_category(),
        "index.mdx": render_index_page(registry),
        "tools.md": render_tools_page(registry),
        "resources.md": render_resources_page(registry),
        "prompts.md": render_prompts_page(registry),
    }
