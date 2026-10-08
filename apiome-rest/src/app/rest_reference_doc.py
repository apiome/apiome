"""Render the REST API reference pages of the documentation site (DOCS-1.11, #5628).

The REST reference used to be only the Swagger UI a running service serves. This module turns the
committed OpenAPI document (``apiome-rest/openapi.yaml``) into one CommonMark page per tag under
``apiome-docs/docs/reference/rest/``, plus an index, so the published site documents every
endpoint and the version AGENTS.md makes every REST change bump.

Everything here is a pure function of the parsed document: no I/O, no clock, stable ordering — so
``scripts/generate_rest_reference_docs.py`` can write the pages and
``tests/test_rest_reference_docs.py`` can regenerate them in memory and fail when the committed
copies drift.

The pages are ``.md``, which the site parses as CommonMark (``markdown.format: detect``), so
descriptions may contain ``{`` freely; ``<`` and ``>`` are escaped outside code spans (raw HTML is
dropped by the site), and ``|`` is escaped inside table cells.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from app.docs_site import DOCS_SITE_PAGES_ROOT

__all__ = [
    "GENERATOR",
    "HASH_FRONT_MATTER_KEY",
    "OPENAPI_PATH",
    "REGENERATE_COMMAND",
    "REST_REFERENCE_DIR",
    "UNTAGGED",
    "collect_operations",
    "render_rest_reference",
    "tag_title",
    "type_label",
]

#: The OpenAPI document the pages are generated from, relative to the monorepo root.
OPENAPI_PATH = "apiome-rest/openapi.yaml"

#: The folder the pages are written to, relative to the monorepo root.
REST_REFERENCE_DIR = f"{DOCS_SITE_PAGES_ROOT}/reference/rest"

#: The generator script, named in every page's ``generated`` front matter.
GENERATOR = "apiome-rest/scripts/generate_rest_reference_docs.py"

#: The one command that regenerates the pages, quoted in the pages and the drift test's message.
REGENERATE_COMMAND = "cd apiome-rest && uv run python scripts/generate_rest_reference_docs.py"

#: Front-matter key of the index page holding the SHA-256 of the OpenAPI document it was built
#: from. ``yarn docs:check`` compares it with the committed document and fails when they differ.
HASH_FRONT_MATTER_KEY = "openapi_sha256"

#: Page slug (and pseudo-tag) for operations that declare no tag.
UNTAGGED = "untagged"

#: HTTP methods an OpenAPI path item may hold, in the order a page lists them.
_METHODS: Tuple[str, ...] = ("get", "put", "post", "patch", "delete", "head", "options", "trace")

#: Words written in capitals (or a fixed spelling) when a tag becomes a page title.
_TITLE_WORDS: Mapping[str, str] = {
    "ai": "AI",
    "api": "API",
    "ci": "CI",
    "csv": "CSV",
    "id": "ID",
    "json": "JSON",
    "mcp": "MCP",
    "openapi": "OpenAPI",
    "sdk": "SDK",
    "url": "URL",
}

#: How many enum values a type cell lists before it trails off.
_ENUM_LIMIT = 6

#: Matches a CommonMark code span (a run of backticks, its content, the same run), so escaping
#: can skip text that is shown literally.
_CODE_SPAN = re.compile(r"(`+)(.+?)\1", re.DOTALL)

#: The index page's front-matter description (at most 14 words, as `yarn docs:check` requires).
_INDEX_DESCRIPTION = "Every Apiome REST endpoint, generated from the OpenAPI document, one page per tag."

#: The not-applicable mark, so an empty cell never reads as a missing fact.
_NONE = "—"


@dataclass(frozen=True)
class Operation:
    """One operation of the document, as a page lists it.

    Attributes:
        path: The path template, e.g. ``/v1/projects/{project_id}``.
        method: Lower-case HTTP method.
        spec: The operation object from the document.
        tags: The operation's tags, or ``(UNTAGGED,)`` when it declares none.
    """

    path: str
    method: str
    spec: Mapping[str, Any]
    tags: Tuple[str, ...]


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _escape_html(text: str) -> str:
    """Escape ``<`` and ``>`` outside code spans, so the site never reads them as raw HTML.

    Args:
        text: Prose from the document.

    Returns:
        The prose with angle brackets outside code spans written as entities.
    """
    parts: List[str] = []
    last = 0
    for match in _CODE_SPAN.finditer(text):
        parts.append(text[last : match.start()].replace("<", "&lt;").replace(">", "&gt;"))
        parts.append(match.group(0))
        last = match.end()
    parts.append(text[last:].replace("<", "&lt;").replace(">", "&gt;"))
    return "".join(parts)


def _cell(text: Optional[str]) -> str:
    """Make ``text`` safe inside a table cell.

    Args:
        text: Raw text, or ``None``.

    Returns:
        One line with pipes escaped and angle brackets escaped, or the not-applicable mark.
    """
    if text is None or not str(text).strip():
        return _NONE
    flat = " ".join(str(text).split())
    return _escape_html(flat).replace("|", "\\|")


def _block(text: Optional[str]) -> str:
    """Make a multi-line description safe as page prose.

    Line breaks are kept (so paragraphs and lists survive), angle brackets are escaped and a line
    that would start a heading is written as plain text.

    Args:
        text: A description from the document, or ``None``.

    Returns:
        The description as Markdown, without trailing blank lines; ``""`` when there is none.
    """
    if not text or not text.strip():
        return ""
    lines = [re.sub(r"^(\s*)#", r"\1\\#", line.rstrip()) for line in text.strip().splitlines()]
    return _escape_html("\n".join(lines))


def slugify(text: str) -> str:
    """Turn a name into an anchor or file slug: lower case, runs of other characters to ``-``.

    Args:
        text: An operation id, schema name or tag.

    Returns:
        The slug, e.g. ``ProjectCreate`` → ``projectcreate``, ``list_projects`` → ``list-projects``.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "x"


def tag_title(tag: str) -> str:
    """The page title for a tag: words split on ``-``/``_``, sentence case, acronyms kept.

    Args:
        tag: The tag, e.g. ``mcp-catalog``.

    Returns:
        The title, e.g. ``MCP catalog``; ``Untagged`` for the pseudo-tag.
    """
    words = [word for word in re.split(r"[-_\s]+", tag) if word]
    rendered = [_TITLE_WORDS.get(word.lower(), word.lower()) for word in words]
    if rendered and rendered[0] == words[0].lower():
        rendered[0] = rendered[0][:1].upper() + rendered[0][1:]
    return " ".join(rendered) or tag


def _yaml_string(text: str) -> str:
    """Quote a front-matter string (JSON strings are valid YAML scalars).

    Args:
        text: The value.

    Returns:
        The quoted value.
    """
    return json.dumps(text, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


def _ref_name(ref: str) -> str:
    """The schema name a ``$ref`` points at.

    Args:
        ref: e.g. ``#/components/schemas/ProjectCreate``.

    Returns:
        ``ProjectCreate``.
    """
    return ref.rsplit("/", 1)[-1]


def type_label(schema: Any, refs: Optional[Set[str]] = None, anchors: Optional[Mapping[str, str]] = None) -> str:
    """Describe a schema as a short, readable type, e.g. ``array of ProjectSummary or null``.

    Component references are named, not expanded. When ``anchors`` maps a name to an anchor on
    the page, the name links there.

    Args:
        schema: A schema object (or anything else, which reads as ``any``).
        refs: When given, every component schema named on the way is added to it.
        anchors: Schema name → anchor id of its section on this page.

    Returns:
        The type, safe inside a table cell.
    """
    if not isinstance(schema, Mapping) or not schema:
        return "any"
    if "$ref" in schema:
        name = _ref_name(str(schema["$ref"]))
        if refs is not None:
            refs.add(name)
        anchor = (anchors or {}).get(name)
        return f"[`{name}`](#{anchor})" if anchor else f"`{name}`"
    for key in ("anyOf", "oneOf"):
        if key in schema:
            options = [s for s in schema[key] if not (isinstance(s, Mapping) and s.get("type") == "null")]
            nullable = len(options) != len(schema[key])
            label = " or ".join(type_label(s, refs, anchors) for s in options) or "null"
            return f"{label} or null" if nullable and options else label
    if "allOf" in schema:
        parts = [type_label(s, refs, anchors) for s in schema["allOf"]]
        return " and ".join(parts) if parts else "object"
    if "const" in schema:
        return f"`{json.dumps(schema['const'], ensure_ascii=False)}`"
    if "enum" in schema:
        values = [json.dumps(v, ensure_ascii=False) for v in schema["enum"]]
        shown = ", ".join(f"`{v}`" for v in values[:_ENUM_LIMIT])
        return f"enum {shown}" + (", …" if len(values) > _ENUM_LIMIT else "")
    kind = schema.get("type")
    if isinstance(kind, list):
        others = [k for k in kind if k != "null"]
        base = " or ".join(type_label({**schema, "type": k}, refs, anchors) for k in others) or "null"
        return f"{base} or null" if "null" in kind and others else base
    if kind == "array":
        return f"array of {type_label(schema.get('items'), refs, anchors)}"
    if kind == "object" or "properties" in schema or "additionalProperties" in schema:
        extra = schema.get("additionalProperties")
        if isinstance(extra, Mapping) and extra and "properties" not in schema:
            return f"map of {type_label(extra, refs, anchors)}"
        return "object"
    if isinstance(kind, str):
        fmt = schema.get("format")
        return f"{kind} ({fmt})" if fmt else kind
    return "any"


def _properties_table(schema: Mapping[str, Any], anchors: Mapping[str, str]) -> List[str]:
    """A table of an object schema's top-level properties.

    Args:
        schema: An object schema with ``properties``.
        anchors: Schema name → anchor id, for linking property types.

    Returns:
        The table's lines, or a single sentence when the schema has no properties.
    """
    properties = schema.get("properties") or {}
    if not properties:
        return ["No declared properties."]
    required = set(schema.get("required") or [])
    lines = ["| Property | Type | Required | Description |", "| --- | --- | --- | --- |"]
    for name, prop in properties.items():
        description = prop.get("description") if isinstance(prop, Mapping) else None
        lines.append(
            f"| `{_cell(name)}` | {_cell(type_label(prop, None, anchors))} | "
            f"{'yes' if name in required else 'no'} | {_cell(description)} |"
        )
    return lines


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def collect_operations(document: Mapping[str, Any]) -> List[Operation]:
    """Every operation in the document, sorted by path then method.

    Args:
        document: The parsed OpenAPI document.

    Returns:
        The operations; one that declares no tag carries the pseudo-tag :data:`UNTAGGED`.
    """
    operations: List[Operation] = []
    for path in sorted(document.get("paths") or {}):
        item = document["paths"][path] or {}
        for method in _METHODS:
            spec = item.get(method)
            if not isinstance(spec, Mapping):
                continue
            tags = tuple(dict.fromkeys(spec.get("tags") or [])) or (UNTAGGED,)
            operations.append(Operation(path=path, method=method, spec=spec, tags=tags))
    return operations


def _operations_by_tag(operations: Iterable[Operation]) -> Dict[str, List[Operation]]:
    """Group operations under each of their tags (an operation with two tags is on both pages).

    Args:
        operations: Sorted operations.

    Returns:
        Tag → its operations, in path/method order; tags in alphabetical order.
    """
    grouped: Dict[str, List[Operation]] = {}
    for op in operations:
        for tag in op.tags:
            grouped.setdefault(tag, []).append(op)
    return {tag: grouped[tag] for tag in sorted(grouped)}


def _operation_anchor(op: Operation) -> str:
    """The stable anchor id of an operation's heading.

    Args:
        op: The operation.

    Returns:
        The slug of its ``operationId``, or of ``method path`` when it has none.
    """
    return slugify(str(op.spec.get("operationId") or f"{op.method} {op.path}"))


def _direct_refs(op: Operation) -> Set[str]:
    """The component schemas an operation names directly (parameters, body, responses).

    Args:
        op: The operation.

    Returns:
        The schema names, without following them into their own properties.
    """
    refs: Set[str] = set()
    for param in op.spec.get("parameters") or []:
        type_label(param.get("schema"), refs)
    for content in ((op.spec.get("requestBody") or {}).get("content") or {}).values():
        type_label(content.get("schema"), refs)
    for response in (op.spec.get("responses") or {}).values():
        for content in (response.get("content") or {}).values():
            type_label(content.get("schema"), refs)
    return refs


def _schema_anchors(names: Iterable[str]) -> Dict[str, str]:
    """Unique anchor ids for a page's schema sections.

    Args:
        names: Schema names.

    Returns:
        Name → ``schema-<slug>``, with a numeric suffix when two names slug alike.
    """
    anchors: Dict[str, str] = {}
    used: Set[str] = set()
    for name in sorted(names):
        anchor = base = f"schema-{slugify(name)}"
        n = 2
        while anchor in used:
            anchor, n = f"{base}-{n}", n + 1
        used.add(anchor)
        anchors[name] = anchor
    return anchors


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _header_comment() -> List[str]:
    """The generated-file comment every page carries."""
    return [
        "<!-- GENERATED FILE — do not edit by hand.",
        f"     Regenerate with: {REGENERATE_COMMAND} -->",
    ]


def _render_operation(op: Operation, anchors: Mapping[str, str], anchor: str) -> List[str]:
    """One operation's section.

    Args:
        op: The operation.
        anchors: Schema name → anchor on this page.
        anchor: The heading's id.

    Returns:
        The section's lines.
    """
    spec = op.spec
    lines = [f"## `{op.method.upper()} {op.path}` {{#{anchor}}}", ""]
    summary = spec.get("summary")
    if summary:
        lines += [f"**{_cell(summary)}**", ""]
    if spec.get("deprecated"):
        lines += ["**Deprecated.**", ""]
    description = _block(spec.get("description"))
    if description:
        lines += [description, ""]
    lines += [f"Operation id: `{spec.get('operationId', _NONE)}`", ""]

    params = spec.get("parameters") or []
    if params:
        lines += [
            "**Parameters**",
            "",
            "| Name | In | Type | Required | Description |",
            "| --- | --- | --- | --- | --- |",
        ]
        for param in params:
            lines.append(
                f"| `{_cell(param.get('name'))}` | {param.get('in', _NONE)} | "
                f"{_cell(type_label(param.get('schema'), None, anchors))} | "
                f"{'yes' if param.get('required') else 'no'} | {_cell(param.get('description'))} |"
            )
        lines.append("")

    body = spec.get("requestBody")
    if isinstance(body, Mapping) and body.get("content"):
        required = "required" if body.get("required") else "optional"
        lines += [f"**Request body** ({required})", ""]
        if body.get("description"):
            lines += [_block(body["description"]), ""]
        for media, content in body["content"].items():
            schema = content.get("schema") or {}
            lines.append(f"- `{media}` — {_cell(type_label(schema, None, anchors))}")
        lines.append("")
        for content in body["content"].values():
            schema = content.get("schema") or {}
            if isinstance(schema, Mapping) and "$ref" not in schema and schema.get("properties"):
                lines += _properties_table(schema, anchors) + [""]

    responses = spec.get("responses") or {}
    if responses:
        lines += ["**Responses**", "", "| Status | Description | Body |", "| --- | --- | --- |"]
        for status in sorted(responses, key=str):
            response = responses[status] or {}
            bodies = [
                f"`{media}` {type_label(content.get('schema'), None, anchors)}"
                for media, content in (response.get("content") or {}).items()
            ]
            lines.append(
                f"| {_cell(str(status))} | {_cell(response.get('description'))} | "
                f"{_cell('; '.join(bodies)) if bodies else _NONE} |"
            )
        lines.append("")

    security = spec.get("security")
    if security:
        schemes = sorted({name for requirement in security for name in requirement})
        lines += [f"Security: {', '.join(f'`{s}`' for s in schemes) or 'none'}", ""]
    return lines


def render_tag_page(
    tag: str,
    operations: Sequence[Operation],
    schemas: Mapping[str, Any],
    version: str,
    position: int,
) -> str:
    """The page for one tag.

    Args:
        tag: The tag (or :data:`UNTAGGED`).
        operations: Its operations, sorted.
        schemas: ``components.schemas`` of the document.
        version: ``info.version``.
        position: The page's ``sidebar_position``.

    Returns:
        The page, ending with a newline.
    """
    count = len(operations)
    noun = "operation" if count == 1 else "operations"
    if tag == UNTAGGED:
        title, description = "Untagged", f"REST endpoints that declare no tag: {count} {noun}."
    else:
        title, description = tag_title(tag), f"REST endpoints tagged {tag}: {count} {noun}."

    referenced: Set[str] = set()
    for op in operations:
        referenced |= _direct_refs(op)
    referenced = {name for name in referenced if name in schemas}
    anchors = _schema_anchors(referenced)

    lines = [
        "---",
        f"title: {_yaml_string(title)}",
        f"description: {_yaml_string(description)}",
        f"sidebar_position: {position}",
        "tags: [rest, reference]",
        f"generated: {GENERATOR}",
        "---",
        "",
        *_header_comment(),
        "",
        f"Generated from `{OPENAPI_PATH}` (API version **{version}**) — do not edit by hand. "
        f"How to authenticate is on the [REST API reference](./index.mdx#authentication).",
        "",
    ]
    if tag != UNTAGGED:
        lines += [f"Tag: `{tag}` · {count} {noun}", ""]

    used: Set[str] = set()
    for op in operations:
        anchor = base = _operation_anchor(op)
        n = 2
        while anchor in used or anchor in anchors.values():
            anchor, n = f"{base}-{n}", n + 1
        used.add(anchor)
        lines += _render_operation(op, anchors, anchor)

    if referenced:
        lines += ["## Schemas used {#schemas-used}", ""]
        for name in sorted(referenced):
            schema = schemas[name] or {}
            lines += [f"### `{name}` {{#{anchors[name]}}}", ""]
            description = _block(schema.get("description"))
            if description:
                lines += [description, ""]
            if schema.get("properties") or schema.get("type") == "object":
                lines += _properties_table(schema, anchors)
            else:
                lines.append(f"Type: {_cell(type_label({k: v for k, v in schema.items() if k != 'description'}))}")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _scheme_line(name: str, scheme: Mapping[str, Any]) -> str:
    """One security scheme as a table row, safe for MDX.

    Args:
        name: The scheme's name.
        scheme: The scheme object.

    Returns:
        The row.
    """
    kind = scheme.get("type", _NONE)
    if kind == "http":
        how = f"`Authorization: {str(scheme.get('scheme', '')).capitalize()} …`"
    elif kind == "apiKey":
        how = f"`{scheme.get('name', '')}` {scheme.get('in', '')}"
    else:
        how = _NONE
    description = _cell(scheme.get("description")).replace("{", "\\{").replace("}", "\\}")
    return f"| `{name}` | {kind} | {how} | {description} |"


def render_index_page(
    document: Mapping[str, Any],
    by_tag: Mapping[str, Sequence[Operation]],
    total: int,
    sha256: str,
) -> str:
    """The reference's landing page: version, authentication and every tag.

    Args:
        document: The parsed OpenAPI document.
        by_tag: Tag → its operations.
        total: Number of distinct operations.
        sha256: SHA-256 (hex) of the document's bytes, recorded for ``yarn docs:check``.

    Returns:
        The page (MDX), ending with a newline. Its headings carry no ``{#id}`` (MDX would read the
        braces as an expression); the automatic ids — ``authentication``, ``tags`` — are linked to.
    """
    info = document.get("info") or {}
    version = str(info.get("version", _NONE))
    schemes = (document.get("components") or {}).get("securitySchemes") or {}
    tag_count = len([tag for tag in by_tag if tag != UNTAGGED])
    untagged = len(by_tag.get(UNTAGGED, ()))
    untagged_note = f" (and {untagged} untagged)" if untagged else ""
    lines = [
        "---",
        f"title: {_yaml_string('REST API reference')}",
        f"description: {_yaml_string(_INDEX_DESCRIPTION)}",
        "sidebar_label: REST API",
        "sidebar_position: 1",
        "tags: [rest, reference]",
        f"generated: {GENERATOR}",
        f"{HASH_FRONT_MATTER_KEY}: {sha256}",
        "---",
        "",
        "{/* GENERATED FILE — do not edit by hand.",
        f"    Regenerate with: {REGENERATE_COMMAND} */}}",
        "",
        f"The Apiome REST API, version **{version}** — {total} operations under {tag_count} tags"
        f"{untagged_note}, "
        f"generated from [`{OPENAPI_PATH}`](https://github.com/apiome/apiome/blob/main/{OPENAPI_PATH}). "
        "Each tag has a page listing its endpoints with their parameters, request bodies, responses "
        "and the schemas they use. A running service also serves the same document interactively — "
        "see [API reference](../api-reference.md) for Swagger UI and ReDoc.",
        "",
        "## Authentication",
        "",
        "Endpoints that need a caller accept either of these schemes:",
        "",
        "| Scheme | Type | Sent as | Description |",
        "| --- | --- | --- | --- |",
        *[_scheme_line(name, schemes[name]) for name in sorted(schemes)],
        "",
        "## Tags",
        "",
        "| Tag | Operations |",
        "| --- | --- |",
    ]
    for tag, ops in by_tag.items():
        label = "Untagged" if tag == UNTAGGED else tag_title(tag)
        lines.append(f"| [{label}](./{tag}.md) | {len(ops)} |")
    return "\n".join(lines) + "\n"


def _category_json() -> str:
    """The folder's ``_category_.json``."""
    return (
        json.dumps(
            {"label": "REST API", "position": 3, "collapsible": True, "collapsed": True},
            indent=2,
        )
        + "\n"
    )


def render_rest_reference(document: Mapping[str, Any], source: bytes) -> Dict[str, str]:
    """Every file of the REST reference folder.

    Args:
        document: The parsed OpenAPI document.
        source: The document's bytes, hashed into the index's front matter.

    Returns:
        File name (inside :data:`REST_REFERENCE_DIR`) → contents.
    """
    operations = collect_operations(document)
    by_tag = _operations_by_tag(operations)
    schemas = (document.get("components") or {}).get("schemas") or {}
    version = str((document.get("info") or {}).get("version", _NONE))
    files: Dict[str, str] = {
        "_category_.json": _category_json(),
        "index.mdx": render_index_page(document, by_tag, len(operations), hashlib.sha256(source).hexdigest()),
    }
    for position, (tag, ops) in enumerate(by_tag.items(), start=2):
        files[f"{tag}.md"] = render_tag_page(tag, ops, schemas, version, position)
    return files
