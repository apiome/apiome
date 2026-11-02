"""API Blueprint 1A parser.

Parses API Blueprint markdown into a typed :class:`ApiblueprintDocument` AST using
a lightweight line-oriented parser so catalog imports do not depend on the
external ``drafter`` CLI.

What it reads: the ``FORMAT`` / ``HOST`` metadata, the API title and description (HTML comments
skipped), resources and actions (an action may override the URI), the URI template's query
expansion (``/books{?limit,offset}`` → query parameters), ``+ Parameters``, request and response
``+ Attributes``, action descriptions, and the ``# Data Structures`` section: named types with their
description and MSON members (``+ name: sample (type, required) - description``, a backtick-escaped
name, an optional nested ``+ Default: value``) or enum members.

MFI-16.2 (#3805) reads the rest of what the canonical model needs from groups, transactions and MSON:

* **Resource groups** — ``# Group Pets`` names the group of every action below it.
* **Transactions** — a named or bare ``+ Request`` (``+ Request Minimal (application/json)``) keeps
  its body; ``+ Headers`` under a request or response are read as ``Name: value`` lines; an inline
  ``+ Attributes`` body (members, no named type) becomes a type of its own, named after the action
  (``Get owner 200 Response``, ``Create pet Request``).
* **MSON** — a type name may contain spaces (``## Owner Summary (object)``); a named base type is
  inheritance (``## Cat (Pet)``) and ``+ Include Problem`` a mixin, both recorded for the normalizer
  to flatten; a member typed ``object`` with deeper-indented members becomes a nested type
  (``Pet.address``); ``+ Members`` under a member or parameter lists its enum values; ``nullable``
  is read beside ``required`` / ``optional``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "ApiblueprintParseError",
    "ApiblueprintField",
    "ApiblueprintType",
    "ApiblueprintParameter",
    "ApiblueprintOperation",
    "ApiblueprintDocument",
    "is_apiblueprint",
    "parse_apiblueprint",
    "split_uri_template",
]

_FORMAT_RE = re.compile(r"^\s*FORMAT\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
#: The *detection* marker, deliberately narrower than :data:`_FORMAT_RE` (FMT-5.1).
#:
#: API Blueprint's ``FORMAT: 1A`` is a metadata line at column zero declaring the
#: blueprint revision. The parser's permissive form matches ``format:`` **anywhere** at
#: **any** indentation with **any** value, which is also how every YAML document in the
#: world spells a JSON-Schema ``format: int32`` or an ODCS server's ``format: parquet`` —
#: so used as a sniff it claimed documents that are not blueprints at all. Detection
#: therefore requires both halves of the real marker: column zero, and a ``1A``-line
#: revision. Reading a parsed document still uses the permissive form, so nothing a
#: blueprint can legally say stops being read.
_FORMAT_MARKER_RE = re.compile(r"^FORMAT\s*:\s*1A[0-9]*\s*$", re.IGNORECASE | re.MULTILINE)
_HOST_RE = re.compile(r"^\s*HOST\s*:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
_RESOURCE_RE = re.compile(r"^##\s+(.+?)\s+\[([^\]]+)\]\s*$")
_ACTION_RE = re.compile(r"^###\s+(.+?)\s+\[([A-Z]+)(?:\s+([^\]]+))?\]\s*$")
#: A named type in ``# Data Structures``: ``## Pet (object)``, ``## Owner Summary (object)``,
#: ``## Cat (Pet)``, or a bare ``## Pet`` (an object).
_TYPE_DEF_RE = re.compile(r"^##\s+(.+?)(?:\s+\(([^)]+)\))?\s*$")
#: ``# Group Pets`` — a resource group (MFI-16.2).
_GROUP_RE = re.compile(r"^#\s+Group\s+(.+?)\s*$")
#: ``+ Include Problem`` — an MSON mixin (MFI-16.2).
_INCLUDE_RE = re.compile(r"^\+\s+Include\s+(.+?)\s*$")
#: ``+ Members`` — the values of an enum member, parameter or type, on the deeper lines.
_MEMBERS_RE = re.compile(r"^\+\s+Members\s*$")
#: MSON section headings that only group members: ``+ Properties``, ``+ Items``.
_SECTION_RE = re.compile(r"^\+\s+(?:Properties|Items)\s*$")
#: ``+ Sample: value`` — an example, not part of the contract.
_SAMPLE_RE = re.compile(r"^\+\s+Samples?\b")
#: An enum member line: ``+ available`` or ``+ `in stock` - description``.
_MEMBER_VALUE_RE = re.compile(r"^\+\s+(?:`([^`]+)`|([^\s`()]+))(?:\s*-\s*.*)?$")
#: A ``Name: value`` line of a ``+ Headers`` block.
_HEADER_LINE_RE = re.compile(r"^([A-Za-z0-9!#$%&'*+.^_`|~-]+)\s*:\s*(.*?)\s*$")
#: MSON base types: a type defined with one of these is that kind of type, not a subtype.
_BASE_TYPES = frozenset({"object", "array", "enum", "string", "number", "boolean"})
#: An MSON property: ``+ name: sample (type, required) - description``. The name may be escaped in
#: backticks (``+ `order-id` (string)``); the ``:`` and sample are optional.
_FIELD_RE = re.compile(
    r"^\s*\+\s+(\w+|`[^`]+`)(?::\s*(?:(?:`([^`]*)`)|([^\s(]\S*))?)?\s*\(([^)]+)\)\s*(?:-\s*(.*))?$"
)
#: A parameter, nested under ``+ Parameters`` (indented, so ``+ Request (…)`` never reads as one).
_PARAM_RE = re.compile(r"^\s+\+\s+([\w.\-]+)\s*\(([^)]+)\)\s*(?:-\s*(.*))?$")
#: A nested ``+ Default: value`` under a property or parameter (indented below it).
_DEFAULT_RE = re.compile(r"^\s+\+\s+Default\s*:\s*(?:`([^`]*)`|(.*?))\s*$")
#: A URI template's query expansion: ``{?limit,offset}`` or ``{&page}``.
_QUERY_EXPANSION_RE = re.compile(r"\{[?&]([^}]*)\}")
#: A one-line HTML comment (``<!-- … -->``): markup, not description.
_HTML_COMMENT_RE = re.compile(r"^<!--.*-->$")
_ATTRIBUTES_RE = re.compile(r"^\s*\+\s+Attributes\s*\(([^)]+)\)\s*$")
#: An ``+ Attributes`` line with no type: the body is the members that follow (MFI-16.2).
_INLINE_ATTRIBUTES_RE = re.compile(r"^\s*\+\s+Attributes\s*$")
#: ``+ Request``, ``+ Request (application/json)`` or ``+ Request Minimal (application/json)``.
_REQUEST_RE = re.compile(r"^\s*\+\s+Request(?:\s+([^(]*?))?\s*(?:\(([^)]+)\))?\s*$")
#: ``+ Headers`` under a request or response (MFI-16.2).
_HEADERS_RE = re.compile(r"^\s*\+\s+Headers\s*$")
_RESPONSE_RE = re.compile(r"^\s*\+\s+Response\s+(\d{3})(?:\s*\(([^)]+)\))?\s*$")
_DATA_STRUCTURES_RE = re.compile(r"^#\s+Data Structures\s*$", re.IGNORECASE)


class ApiblueprintParseError(ValueError):
    """Raised when API Blueprint text cannot be parsed."""


@dataclass(frozen=True)
class ApiblueprintField:
    name: str
    type_expr: str
    required: bool
    sample: Optional[str]
    description: Optional[str]
    #: The nested ``+ Default:`` value, as written.
    default: Optional[str] = None
    #: The values of an inline ``enum[…]`` member, from its nested ``+ Members`` (MFI-16.2).
    enum_values: Tuple[str, ...] = ()
    #: Whether the member is marked ``nullable`` (MFI-16.2).
    nullable: bool = False


@dataclass(frozen=True)
class ApiblueprintType:
    name: str
    kind: str
    fields: Tuple[ApiblueprintField, ...]
    enum_values: Tuple[str, ...]
    description: Optional[str] = None
    #: The named type it inherits from (``## Cat (Pet)`` → ``Pet``), when not a base type (MFI-16.2).
    base: Optional[str] = None
    #: The types it mixes in with ``+ Include``, in order (MFI-16.2).
    includes: Tuple[str, ...] = ()
    #: Whether it was synthesized from an inline body or a nested object member (MFI-16.2).
    inline: bool = False


@dataclass(frozen=True)
class ApiblueprintParameter:
    name: str
    type_expr: str
    required: bool
    description: Optional[str] = None
    #: ``path``, or ``query`` for a name in the URI template's query expansion (``{?limit}``).
    location: str = "path"
    #: The nested ``+ Default:`` value, as written.
    default: Optional[str] = None
    #: The values of an ``enum[…]`` parameter, from its nested ``+ Members`` (MFI-16.2).
    enum_values: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ApiblueprintOperation:
    name: str
    method: str
    path: str
    description: Optional[str]
    parameters: Tuple[ApiblueprintParameter, ...]
    request_media_type: Optional[str]
    request_type: Optional[str]
    #: ``(status, media type, body type, headers)``; headers are ``(name, value)`` pairs (MFI-16.2).
    responses: Tuple[Tuple[str, Optional[str], Optional[str], Tuple[Tuple[str, str], ...]], ...]
    #: The resource group it belongs to (``# Group Pets``), if any (MFI-16.2).
    group: Optional[str] = None
    #: The first request's headers, as ``(name, value)`` pairs (MFI-16.2).
    request_headers: Tuple[Tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ApiblueprintDocument:
    format_version: str
    title: str
    host: Optional[str]
    description: Optional[str]
    types: Tuple[ApiblueprintType, ...]
    operations: Tuple[ApiblueprintOperation, ...]
    raw: str
    #: drafter's annotations of the document (MFI-16.3, :func:`app.apiblueprint_drafter.run_drafter`):
    #: ``{"severity", "code", "message", "line"?, "column"?}``; empty without drafter.
    drafter_annotations: Tuple[Dict[str, Any], ...] = ()
    #: drafter's API Elements parse result — the Refract tree (MFI-16.1,
    #: :func:`app.apiblueprint_drafter.run_drafter_parse`); ``None`` without drafter.
    refract: Optional[Dict[str, Any]] = None


def is_apiblueprint(content: str) -> bool:
    """Return ``True`` when ``content`` looks like an API Blueprint document.

    Claims a document carrying the ``FORMAT: 1A`` metadata marker at column zero — see
    :data:`_FORMAT_MARKER_RE` for why both halves of that marker are required.

    Args:
        content: The candidate document text.

    Returns:
        ``True`` when the API Blueprint reader claims the text.
    """
    if not content or not isinstance(content, str):
        return False
    return bool(_FORMAT_MARKER_RE.search(content.strip()))


#: MSON type attributes — everything in a member's parentheses that is not its type.
_TYPE_ATTRIBUTES = frozenset({"required", "optional", "nullable", "fixed", "fixed-type", "sample", "default"})


def _parse_type_modifiers(modifiers: str) -> Tuple[str, bool, bool]:
    """Split an MSON ``(type, attributes…)`` list.

    Args:
        modifiers: The text inside the parentheses, for example ``array[Pet], required, nullable``.

    Returns:
        ``(type, required, nullable)``; the type is ``string`` when none is named.
    """
    parts = [part.strip() for part in modifiers.split(",") if part.strip()]
    lowered = {part.lower() for part in parts}
    required = "required" in lowered and "optional" not in lowered
    type_parts = [part for part in parts if part.lower() not in _TYPE_ATTRIBUTES]
    return (type_parts[0] if type_parts else "string"), required, "nullable" in lowered


def _indent(line: str) -> int:
    """The number of leading spaces (a tab counts as four, as Markdown reads it)."""
    expanded = line.expandtabs(4)
    return len(expanded) - len(expanded.lstrip(" "))


def _type_heading(name: str, modifiers: Optional[str]) -> Tuple[str, str, Optional[str]]:
    """Read a ``## Name (type)`` data-structure heading.

    Args:
        name: The heading's name, which may contain spaces.
        modifiers: The text in its parentheses, or ``None`` for a bare ``## Name``.

    Returns:
        ``(name, kind, base)``: ``kind`` is the MSON base type (``object``, ``enum``, ``array`` …);
        ``base`` is the named type it inherits from, or ``None``.
    """
    type_expr, _required, _nullable = _parse_type_modifiers(modifiers) if modifiers else ("object", False, False)
    lowered = type_expr.lower()
    if lowered in _BASE_TYPES:
        return name.strip(), lowered, None
    if lowered.startswith("enum["):
        return name.strip(), "enum", None
    if lowered.startswith("array["):
        return name.strip(), "array", None
    return name.strip(), "object", type_expr.strip()


def _skip_deeper(lines: List[str], index: int, indent: int) -> int:
    """The index of the first line after ``index`` that is not blank and not deeper than ``indent``."""
    while index < len(lines) and (not lines[index].strip() or _indent(lines[index]) > indent):
        index += 1
    return index


def _read_member_values(lines: List[str], index: int, indent: int) -> Tuple[List[str], int]:
    """Read the enum values listed under a ``+ Members`` line indented ``indent``.

    Returns:
        The values in order, and the index of the first line not under the ``+ Members`` line.
    """
    values: List[str] = []
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped and _indent(line) <= indent:
            break
        match = _MEMBER_VALUE_RE.match(stripped) if stripped else None
        if match:
            values.append(match.group(1) or match.group(2))
        index += 1
    return values, index


@dataclass
class _MsonBlock:
    """What one MSON block declares: the members of a type, an inline body or a nested object."""

    fields: List[ApiblueprintField]
    enum_values: List[str]
    includes: List[str]
    description: List[str]
    #: Types synthesized for nested object members (``Pet.address``), deepest last.
    nested: List[ApiblueprintType]


def _next_content(lines: List[str], index: int) -> Optional[str]:
    """The next non-blank line at or after ``index``, or ``None``."""
    while index < len(lines):
        if lines[index].strip():
            return lines[index]
        index += 1
    return None


def _read_mson_block(
    lines: List[str],
    index: int,
    *,
    owner: str,
    min_indent: int,
    owner_is_enum: bool = False,
    collect_description: bool = False,
) -> Tuple[_MsonBlock, int]:
    """Read MSON members from ``index`` until a heading or a line indented less than ``min_indent``.

    Args:
        lines: The document's lines.
        index: Where the block's first member line may be.
        owner: The name of the type the members belong to; nested types are named after it.
        min_indent: The least indentation a line of the block can have.
        owner_is_enum: Whether bare ``+ value`` lines at the block's own level are enum values.
        collect_description: Whether prose before the first member is the owner's description.

    Returns:
        The block, and the index of the first line after it.
    """
    block = _MsonBlock([], [], [], [], [])
    last_field_indent: Optional[int] = None
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        indent = _indent(line)
        if stripped.startswith("#") or indent < min_indent:
            break
        under_field = last_field_indent is not None and indent > last_field_indent and bool(block.fields)
        include = _INCLUDE_RE.match(stripped)
        if include and not under_field:
            block.includes.append(include.group(1).strip("`"))
            index += 1
            continue
        if _SECTION_RE.match(stripped):
            index += 1
            continue
        if _SAMPLE_RE.match(stripped):
            index = _skip_deeper(lines, index + 1, indent)
            continue
        if _MEMBERS_RE.match(stripped):
            values, index = _read_member_values(lines, index + 1, indent)
            if under_field:
                block.fields[-1] = replace(block.fields[-1], enum_values=tuple(values))
            else:
                block.enum_values.extend(values)
            continue
        default_match = _DEFAULT_RE.match(line)
        if default_match and under_field:
            value = default_match.group(1) if default_match.group(1) is not None else default_match.group(2)
            block.fields[-1] = replace(block.fields[-1], default=value)
            index += 1
            continue
        field = _parse_field_line(line)
        if field is not None and not under_field:
            index += 1
            following = _next_content(lines, index)
            nests = (
                field.type_expr.lower() == "object"
                and following is not None
                and _indent(following) > indent
                and (_parse_field_line(following) is not None or _INCLUDE_RE.match(following.strip()))
            )
            if nests:
                nested_name = f"{owner}.{field.name}"
                nested, index = _read_mson_block(lines, index, owner=nested_name, min_indent=indent + 1)
                block.nested.append(
                    ApiblueprintType(
                        name=nested_name,
                        kind="object",
                        fields=tuple(nested.fields),
                        enum_values=(),
                        includes=tuple(nested.includes),
                        inline=True,
                    )
                )
                block.nested.extend(nested.nested)
                field = replace(field, type_expr=nested_name)
            block.fields.append(field)
            last_field_indent = indent
            continue
        member = _MEMBER_VALUE_RE.match(stripped)
        if member and owner_is_enum and not block.fields:
            block.enum_values.append(member.group(1) or member.group(2))
            index += 1
            continue
        if (
            collect_description
            and not block.fields
            and not block.enum_values
            and not stripped.startswith("+")
            and not _HTML_COMMENT_RE.match(stripped)
        ):
            block.description.append(stripped)
        index += 1
    return block, index


def _read_headers(lines: List[str], index: int, indent: int) -> Tuple[List[Tuple[str, str]], int]:
    """Read the ``Name: value`` lines of a ``+ Headers`` block indented ``indent``.

    Returns:
        The headers in order, and the index of the first line not under the ``+ Headers`` line.
    """
    headers: List[Tuple[str, str]] = []
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped and (_indent(line) <= indent or stripped.startswith(("+", "#"))):
            break
        match = _HEADER_LINE_RE.match(stripped) if stripped else None
        if match:
            headers.append((match.group(1), match.group(2)))
        index += 1
    return headers, index


def _normalize_path(path: str) -> str:
    cleaned = path.strip()
    if not cleaned.startswith("/"):
        cleaned = "/" + cleaned
    return cleaned


def _join_paths(base: str, suffix: Optional[str]) -> str:
    base_path = _normalize_path(base)
    if not suffix:
        return base_path
    suffix = suffix.strip()
    if suffix.startswith("/"):
        return _normalize_path(suffix)
    if not base_path.endswith("/"):
        base_path += "/"
    return _normalize_path(base_path + suffix)


def split_uri_template(path: str) -> Tuple[str, List[str]]:
    """Split a URI template into its path and the names of its query expansion.

    Args:
        path: The resource or action URI template (``/books{?limit,offset}``).

    Returns:
        The path without the query expansion (``/books``) and the query names (``["limit", "offset"]``),
        explode modifiers (``*``) removed.
    """
    names = [
        name.strip().rstrip("*")
        for group in _QUERY_EXPANSION_RE.findall(path)
        for name in group.split(",")
        if name.strip()
    ]
    return _QUERY_EXPANSION_RE.sub("", path), names


def _path_parameters(path: str) -> List[ApiblueprintParameter]:
    params: List[ApiblueprintParameter] = []
    for name in re.findall(r"\{([^}?&]+)\}", path):
        params.append(
            ApiblueprintParameter(
                name=name,
                type_expr="string",
                required=True,
                description=None,
            )
        )
    return params


def _parse_parameter_line(line: str) -> Optional[ApiblueprintParameter]:
    match = _PARAM_RE.match(line)
    if not match:
        return None
    type_expr, required, _nullable = _parse_type_modifiers(match.group(2))
    return ApiblueprintParameter(
        name=match.group(1),
        type_expr=type_expr,
        required=required,
        description=match.group(3).strip() if match.group(3) else None,
    )


def _parse_field_line(line: str) -> Optional[ApiblueprintField]:
    match = _FIELD_RE.match(line)
    if not match:
        return None
    sample = match.group(2) if match.group(2) is not None else match.group(3)
    type_expr, required, nullable = _parse_type_modifiers(match.group(4))
    return ApiblueprintField(
        name=match.group(1).strip("`"),
        type_expr=type_expr,
        required=required,
        sample=sample,
        description=match.group(5).strip() if match.group(5) else None,
        nullable=nullable,
    )


def _finalize_operation(
    *,
    name: str,
    method: str,
    path: str,
    description: Optional[str],
    resource_params: List[ApiblueprintParameter],
    action_params: List[ApiblueprintParameter],
    request_media_type: Optional[str],
    request_type: Optional[str],
    responses: List[Tuple[str, Optional[str], Optional[str], Tuple[Tuple[str, str], ...]]],
    group: Optional[str] = None,
    request_headers: Tuple[Tuple[str, str], ...] = (),
) -> ApiblueprintOperation:
    path, query_names = split_uri_template(path)
    params_by_name = {param.name: param for param in _path_parameters(path)}
    for name_ in query_names:
        params_by_name[name_] = ApiblueprintParameter(name=name_, type_expr="string", required=False, location="query")
    for param in [*resource_params, *action_params]:
        params_by_name[param.name] = replace(param, location="query") if param.name in query_names else param
    return ApiblueprintOperation(
        name=name,
        method=method,
        path=path,
        description=description,
        parameters=tuple(params_by_name.values()),
        request_media_type=request_media_type,
        request_type=request_type,
        responses=tuple(responses),
        group=group,
        request_headers=request_headers,
    )


def parse_apiblueprint(content: str, *, source_label: Optional[str] = None) -> ApiblueprintDocument:
    """Parse API Blueprint text into an :class:`ApiblueprintDocument`.

    Args:
        content: The blueprint.
        source_label: Its name; the title when the blueprint has no ``# Title`` heading.

    Returns:
        The parsed document.

    Raises:
        ApiblueprintParseError: When the text is empty, is not API Blueprint, or declares neither a
            resource nor a data structure.
    """
    if not content or not content.strip():
        raise ApiblueprintParseError("Invalid or empty API Blueprint document")
    if not is_apiblueprint(content):
        raise ApiblueprintParseError("Content does not appear to be an API Blueprint document")

    lines = content.splitlines()
    format_version = "1A"
    host: Optional[str] = None
    title = source_label or "API Blueprint"
    description_lines: List[str] = []
    types: List[ApiblueprintType] = []
    operations: List[ApiblueprintOperation] = []

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        format_match = _FORMAT_RE.match(stripped)
        if format_match:
            format_version = format_match.group(1)
            index += 1
            continue
        host_match = _HOST_RE.match(stripped)
        if host_match:
            host = host_match.group(1)
            index += 1
            continue
        if stripped.startswith("#"):
            break
        index += 1

    if (
        index < len(lines)
        and lines[index].startswith("# ")
        and not lines[index].startswith("##")
        and not _GROUP_RE.match(lines[index].strip())
        and not _DATA_STRUCTURES_RE.match(lines[index].strip())
    ):
        title = lines[index][2:].strip() or title
        index += 1

    current_group: Optional[str] = None
    current_resource_path: Optional[str] = None
    resource_params: List[ApiblueprintParameter] = []
    in_data_structures = False
    in_parameters_block = False
    action_name: Optional[str] = None
    action_method: Optional[str] = None
    action_path: Optional[str] = None
    action_params: List[ApiblueprintParameter] = []
    request_media_type: Optional[str] = None
    request_type: Optional[str] = None
    request_headers: List[Tuple[str, str]] = []
    #: Whether the action's first ``+ Request`` was seen; later requests are other transactions.
    request_seen = False
    #: Where ``+ Attributes`` / ``+ Headers`` land: ``request`` (the first), ``response``, or ``None``.
    target: Optional[str] = None
    responses: List[Tuple[str, Optional[str], Optional[str], Tuple[Tuple[str, str], ...]]] = []
    pending_response_status: Optional[str] = None
    pending_response_media: Optional[str] = None
    pending_response_type: Optional[str] = None
    pending_response_headers: List[Tuple[str, str]] = []
    #: Description lines of the current action (before its first ``+`` section).
    action_description: List[str] = []
    action_body_started = False
    #: Where a nested ``+ Default:`` line under a parameter lands: ``("param", list, index)``.
    default_target: Optional[Tuple[Any, ...]] = None

    def flush_pending_response() -> None:
        nonlocal pending_response_status, pending_response_media, pending_response_type
        nonlocal pending_response_headers
        if pending_response_status is not None and action_name is not None:
            responses.append(
                (
                    pending_response_status,
                    pending_response_media,
                    pending_response_type,
                    tuple(pending_response_headers),
                )
            )
        pending_response_status = None
        pending_response_media = None
        pending_response_type = None
        pending_response_headers = []

    def apply_default(value: str) -> None:
        """Attach a nested ``+ Default:`` value to the parameter it is indented under."""
        if default_target is None:
            return
        owner, at = default_target[1], default_target[2]
        owner[at] = replace(owner[at], default=value)

    def reset_action() -> None:
        nonlocal action_name, action_method, action_path, action_params
        nonlocal request_media_type, request_type, request_headers, request_seen, target, responses
        nonlocal action_description, action_body_started
        action_name = None
        action_method = None
        action_path = None
        action_params = []
        request_media_type = None
        request_type = None
        request_headers = []
        request_seen = False
        target = None
        responses = []
        action_description = []
        action_body_started = False

    def flush_operation() -> None:
        description = "\n".join(action_description).strip() or None
        flush_pending_response()
        if action_name is not None and action_method is not None and action_path is not None:
            operations.append(
                _finalize_operation(
                    name=action_name,
                    method=action_method,
                    path=action_path,
                    description=description,
                    resource_params=resource_params,
                    action_params=action_params,
                    request_media_type=request_media_type,
                    request_type=request_type,
                    responses=responses,
                    group=current_group,
                    request_headers=tuple(request_headers),
                )
            )
        reset_action()

    def inline_body(at: int, indent: int, name: str) -> Tuple[Optional[str], int]:
        """Read an inline ``+ Attributes`` body into a type named ``name``; return its name and the next index."""
        block, after = _read_mson_block(lines, at, owner=name, min_indent=indent + 1)
        if not block.fields and not block.includes:
            return None, after
        types.append(
            ApiblueprintType(
                name=name,
                kind="object",
                fields=tuple(block.fields),
                enum_values=(),
                includes=tuple(block.includes),
                inline=True,
            )
        )
        types.extend(block.nested)
        return name, after

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if _DATA_STRUCTURES_RE.match(stripped):
            flush_operation()
            in_data_structures = True
            current_group = None
            current_resource_path = None
            resource_params = []
            in_parameters_block = False
            index += 1
            continue

        if in_data_structures:
            type_match = _TYPE_DEF_RE.match(stripped) if stripped.startswith("## ") else None
            if type_match:
                name, kind, base = _type_heading(type_match.group(1), type_match.group(2))
                block, index = _read_mson_block(
                    lines,
                    index + 1,
                    owner=name,
                    min_indent=0,
                    owner_is_enum=kind == "enum",
                    collect_description=True,
                )
                types.append(
                    ApiblueprintType(
                        name=name,
                        kind=kind,
                        fields=tuple(block.fields),
                        enum_values=tuple(block.enum_values),
                        description="\n".join(block.description).strip() or None,
                        base=base,
                        includes=tuple(block.includes),
                    )
                )
                types.extend(block.nested)
                continue
            index += 1
            continue

        group_match = _GROUP_RE.match(stripped)
        if group_match:
            flush_operation()
            current_group = group_match.group(1)
            current_resource_path = None
            resource_params = []
            in_parameters_block = False
            index += 1
            continue

        resource_match = _RESOURCE_RE.match(stripped)
        if resource_match:
            flush_operation()
            current_resource_path = _normalize_path(resource_match.group(2))
            resource_params = []
            in_parameters_block = False
            index += 1
            continue

        action_match = _ACTION_RE.match(stripped)
        if action_match and current_resource_path is not None:
            flush_operation()
            action_name = action_match.group(1).strip()
            action_method = action_match.group(2).upper()
            action_path = _join_paths(current_resource_path, action_match.group(3))
            action_params = []
            in_parameters_block = False
            index += 1
            continue

        if action_name is not None and stripped.startswith("+"):
            action_body_started = True

        if stripped == "+ Parameters":
            in_parameters_block = True
            index += 1
            continue

        if in_parameters_block:
            default_match = _DEFAULT_RE.match(line)
            if default_match:
                apply_default(default_match.group(1) if default_match.group(1) is not None
                              else default_match.group(2))
                index += 1
                continue
            if _MEMBERS_RE.match(stripped):
                # MFI-16.2: the values of the enum parameter it is indented under.
                values, index = _read_member_values(lines, index + 1, _indent(line))
                if default_target is not None:
                    owner, at = default_target[1], default_target[2]
                    owner[at] = replace(owner[at], enum_values=tuple(values))
                continue
            param = _parse_parameter_line(line)
            if param is not None:
                owner = action_params if action_name is not None else resource_params
                owner.append(param)
                default_target = ("param", owner, len(owner) - 1)
                index += 1
                continue
            if stripped.startswith("+") or stripped.startswith("#"):
                in_parameters_block = False
                continue
            index += 1
            continue

        request_match = _REQUEST_RE.match(stripped)
        if request_match and action_name is not None:
            flush_pending_response()
            if request_seen:
                # A further request is another transaction's; its body is not the operation's.
                target = None
            else:
                request_seen = True
                target = "request"
                request_media_type = request_match.group(2).strip() if request_match.group(2) else None
            index += 1
            continue

        response_match = _RESPONSE_RE.match(stripped)
        if response_match and action_name is not None:
            flush_pending_response()
            pending_response_status = response_match.group(1)
            pending_response_media = (
                response_match.group(2).strip() if response_match.group(2) else None
            )
            target = "response"
            index += 1
            continue

        if action_name is not None and _HEADERS_RE.match(line):
            headers, index = _read_headers(lines, index + 1, _indent(line))
            if target == "response":
                pending_response_headers.extend(headers)
            elif target == "request":
                request_headers.extend(headers)
            continue

        attributes_match = _ATTRIBUTES_RE.match(stripped)
        inline_match = _INLINE_ATTRIBUTES_RE.match(stripped)
        if (attributes_match or inline_match) and action_name is not None:
            type_name = attributes_match.group(1).strip() if attributes_match else "object"
            index += 1
            if type_name.lower() == "object":
                label = (
                    f"{action_name} {pending_response_status} Response"
                    if target == "response"
                    else f"{action_name} Request"
                )
                inline_name, index = inline_body(index, _indent(line), label)
                type_name = inline_name or type_name
            if target == "response" and pending_response_status is not None:
                pending_response_type = type_name
            elif target == "request" and request_type is None:
                request_type = type_name
            continue

        if (
            stripped
            and not stripped.startswith("+")
            and not stripped.startswith("#")
            and not _HTML_COMMENT_RE.match(stripped)
        ):
            if action_name is None and current_resource_path is None:
                description_lines.append(stripped)
            elif action_name is not None and not action_body_started:
                action_description.append(stripped)

        index += 1

    flush_operation()

    if not types and not operations:
        label = f" ({source_label})" if source_label else ""
        raise ApiblueprintParseError(f"No API Blueprint resources or data structures found{label}")

    description = "\n".join(description_lines).strip() or None
    return ApiblueprintDocument(
        format_version=format_version,
        title=title,
        host=host,
        description=description,
        types=tuple(types),
        operations=tuple(operations),
        raw=content,
    )
