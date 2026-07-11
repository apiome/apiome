"""Smithy IDL parser.

Parses Smithy 2.x model text into a typed :class:`SmithyDocument` AST using a
lightweight lexer (comment stripping, brace matching, regex) so catalog imports
do not depend on the external ``smithy`` CLI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "SmithyParseError",
    "SmithyField",
    "SmithyStructure",
    "SmithyEnum",
    "SmithyList",
    "SmithyMap",
    "SmithyOperation",
    "SmithyService",
    "SmithyDocument",
    "is_smithy",
    "parse_smithy",
]

_SMITHY_VERSION_RE = re.compile(r"""^\s*\$version\s*:\s*['"]([^'"]+)['"]""", re.MULTILINE)
_SMITHY_KEYWORD_RE = re.compile(
    r"^\s*(service|structure|operation|resource|enum|list|map|union)\s+\w",
    re.MULTILINE,
)
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([\w.]+)", re.MULTILINE)
_TYPESPEC_IMPORT_RE = re.compile(r"""^\s*import\s+['"]@typespec/""", re.MULTILINE)
_TYPESPEC_DECL_RE = re.compile(r"^\s*(model|op|interface)\s+\w", re.MULTILINE)
_SHAPE_RE = re.compile(
    r"\b(structure|union|enum|list|map|operation|service|resource)\s+(\w+)\s*\{",
    re.MULTILINE,
)


class SmithyParseError(ValueError):
    """Raised when Smithy IDL cannot be parsed."""


@dataclass(frozen=True)
class SmithyField:
    name: str
    type_name: str
    required: bool = False
    traits: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SmithyStructure:
    name: str
    kind: str  # structure | union | resource
    fields: Tuple[SmithyField, ...]
    documentation: Optional[str] = None


@dataclass(frozen=True)
class SmithyEnum:
    name: str
    values: Tuple[str, ...]
    documentation: Optional[str] = None


@dataclass(frozen=True)
class SmithyList:
    name: str
    member: str
    documentation: Optional[str] = None


@dataclass(frozen=True)
class SmithyMap:
    name: str
    key: str
    value: str
    documentation: Optional[str] = None


@dataclass(frozen=True)
class SmithyOperation:
    name: str
    input_type: Optional[str]
    output_type: Optional[str]
    documentation: Optional[str] = None


@dataclass(frozen=True)
class SmithyService:
    name: str
    version: Optional[str]
    operations: Tuple[str, ...]
    documentation: Optional[str] = None


@dataclass(frozen=True)
class SmithyDocument:
    version: Optional[str]
    namespace: Optional[str]
    structures: Tuple[SmithyStructure, ...]
    enums: Tuple[SmithyEnum, ...]
    lists: Tuple[SmithyList, ...]
    maps: Tuple[SmithyMap, ...]
    operations: Tuple[SmithyOperation, ...]
    services: Tuple[SmithyService, ...]
    raw: str


def is_smithy(content: str) -> bool:
    """Return ``True`` when ``content`` looks like Smithy IDL."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if _TYPESPEC_IMPORT_RE.search(trimmed) or _TYPESPEC_DECL_RE.search(trimmed):
        return False
    if _SMITHY_VERSION_RE.search(trimmed):
        return True
    if _SMITHY_KEYWORD_RE.search(trimmed):
        return True
    return False


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r"///[^\n]*", " ", text)
    text = re.sub(r"#[^\n]*", " ", text)
    return text


def _find_matching_brace(s: str, start: int) -> int:
    depth = 1
    i = start
    while i < len(s) and depth > 0:
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
        i += 1
    return i - 1 if depth == 0 else -1


def _leading_doc(raw: str, shape_start: int) -> Optional[str]:
    prefix = raw[:shape_start]
    lines = prefix.splitlines()
    docs: List[str] = []
    for line in reversed(lines[-5:]):
        stripped = line.strip()
        if stripped.startswith("///"):
            docs.append(stripped[3:].strip())
            continue
        if not stripped:
            if docs:
                break
            continue
        break
    if not docs:
        return None
    return " ".join(reversed(docs)).strip() or None


def _parse_fields(inner: str) -> Tuple[SmithyField, ...]:
    reserved = frozenset(
        {"version", "operations", "input", "output", "errors", "member", "key", "value"}
    )
    fields: List[SmithyField] = []
    pending_traits: List[str] = []
    for line in inner.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        trait_only = re.fullmatch(r"@(\w+)(?:\([^)]*\))?", stripped)
        if trait_only:
            pending_traits.append(trait_only.group(1))
            continue
        inline_traits = re.findall(r"@(\w+)", stripped)
        field_match = re.search(r"(?P<name>\w+)\s*:\s*(?P<type>[\w.]+)", stripped)
        if not field_match:
            pending_traits = []
            continue
        name = field_match.group("name")
        if name in reserved:
            pending_traits = []
            continue
        traits = tuple(dict.fromkeys([*pending_traits, *inline_traits]))
        fields.append(
            SmithyField(
                name=name,
                type_name=field_match.group("type"),
                required="required" in traits,
                traits=traits,
            )
        )
        pending_traits = []
    return tuple(fields)


def _parse_enum_values(inner: str) -> Tuple[str, ...]:
    reserved = frozenset(
        {
            "apply",
            "enum",
            "list",
            "map",
            "member",
            "structure",
            "union",
            "service",
            "operation",
            "resource",
            "input",
            "output",
            "errors",
            "version",
            "operations",
            "key",
            "value",
        }
    )
    values: List[str] = []
    for token in re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\b", inner):
        if token in reserved:
            continue
        if token not in values:
            values.append(token)
    return tuple(values)


def _parse_service(inner: str) -> Tuple[Optional[str], Tuple[str, ...]]:
    version_match = re.search(r"""version\s*:\s*["']([^"']+)["']""", inner)
    version = version_match.group(1) if version_match else None
    ops_match = re.search(r"operations\s*:\s*\[([^\]]+)\]", inner)
    operations: Tuple[str, ...] = ()
    if ops_match:
        operations = tuple(
            name
            for name in re.findall(r"[\w.]+", ops_match.group(1))
            if name not in {"operations"}
        )
    return version, operations


def _parse_operation(inner: str) -> Tuple[Optional[str], Optional[str]]:
    input_match = re.search(r"input\s*:\s*([\w.]+)", inner)
    output_match = re.search(r"output\s*:\s*([\w.]+)", inner)
    input_type = input_match.group(1) if input_match else None
    output_type = output_match.group(1) if output_match else None
    return input_type, output_type


def _parse_list_member(inner: str) -> Optional[str]:
    match = re.search(r"member\s*:\s*([\w.]+)", inner)
    return match.group(1) if match else None


def _parse_map_types(inner: str) -> Tuple[Optional[str], Optional[str]]:
    key_match = re.search(r"key\s*:\s*([\w.]+)", inner)
    value_match = re.search(r"value\s*:\s*([\w.]+)", inner)
    key = key_match.group(1) if key_match else None
    value = value_match.group(1) if value_match else None
    return key, value


def parse_smithy(content: str, *, source_label: Optional[str] = None) -> SmithyDocument:
    """Parse Smithy IDL text into a :class:`SmithyDocument`."""
    if not content or not content.strip():
        raise SmithyParseError("Invalid or empty Smithy content")
    if not is_smithy(content):
        raise SmithyParseError("Content does not appear to be a Smithy IDL model")

    version_match = _SMITHY_VERSION_RE.search(content)
    version = version_match.group(1) if version_match else None
    namespace_match = _NAMESPACE_RE.search(content)
    namespace = namespace_match.group(1) if namespace_match else None

    cleaned = _strip_comments(content)
    structures: List[SmithyStructure] = []
    enums: List[SmithyEnum] = []
    lists: List[SmithyList] = []
    maps: List[SmithyMap] = []
    operations: List[SmithyOperation] = []
    services: List[SmithyService] = []

    for match in _SHAPE_RE.finditer(cleaned):
        kind, name = match.group(1), match.group(2)
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        documentation = _leading_doc(content, match.start())

        if kind in {"structure", "union", "resource"}:
            fields = _parse_fields(inner)
            structures.append(
                SmithyStructure(
                    name=name,
                    kind=kind,
                    fields=fields,
                    documentation=documentation,
                )
            )
        elif kind == "enum":
            values = _parse_enum_values(inner)
            if values:
                enums.append(SmithyEnum(name=name, values=values, documentation=documentation))
        elif kind == "list":
            member = _parse_list_member(inner)
            if member:
                lists.append(SmithyList(name=name, member=member, documentation=documentation))
        elif kind == "map":
            key, value = _parse_map_types(inner)
            if key and value:
                maps.append(SmithyMap(name=name, key=key, value=value, documentation=documentation))
        elif kind == "operation":
            input_type, output_type = _parse_operation(inner)
            operations.append(
                SmithyOperation(
                    name=name,
                    input_type=input_type,
                    output_type=output_type,
                    documentation=documentation,
                )
            )
        elif kind == "service":
            svc_version, svc_ops = _parse_service(inner)
            services.append(
                SmithyService(
                    name=name,
                    version=svc_version,
                    operations=svc_ops,
                    documentation=documentation,
                )
            )

    if not structures and not enums and not lists and not maps and not operations and not services:
        label = f" ({source_label})" if source_label else ""
        raise SmithyParseError(f"No Smithy shapes found in model{label}")

    return SmithyDocument(
        version=version,
        namespace=namespace,
        structures=tuple(structures),
        enums=tuple(enums),
        lists=tuple(lists),
        maps=tuple(maps),
        operations=tuple(operations),
        services=tuple(services),
        raw=content,
    )
