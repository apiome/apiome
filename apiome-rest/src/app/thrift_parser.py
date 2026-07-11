"""Apache Thrift IDL parser — MFI-11.1.

Parses ``.thrift`` source text into a typed :class:`ThriftDocument` AST. The parser is
deliberately lightweight (regex + brace matching, mirroring the UI's
``thrift-converter.ts``) so catalog imports do not depend on an external Thrift compiler.
Syntax errors surface as :class:`ThriftParseError` with a human-readable message.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

__all__ = [
    "ThriftParseError",
    "ThriftEnum",
    "ThriftField",
    "ThriftStruct",
    "ThriftServiceMethod",
    "ThriftService",
    "ThriftDocument",
    "is_thrift",
    "parse_thrift",
]

_THRIFT_BASE_TYPES = frozenset(
    {"bool", "byte", "i8", "i16", "i32", "i64", "double", "string", "binary", "uuid"}
)


class ThriftParseError(ValueError):
    """Raised when Thrift IDL cannot be parsed."""


@dataclass(frozen=True)
class ThriftEnum:
    name: str
    values: Tuple[Tuple[str, Optional[int]], ...]


@dataclass(frozen=True)
class ThriftField:
    id: int
    name: str
    required: bool
    type_expr: str
    default: Optional[str] = None


@dataclass(frozen=True)
class ThriftStruct:
    name: str
    kind: str  # struct | union | exception
    fields: Tuple[ThriftField, ...]


@dataclass(frozen=True)
class ThriftServiceMethod:
    name: str
    return_type: str
    parameters: Tuple[ThriftField, ...]
    throws: Tuple[Tuple[int, str, str], ...]  # (field_id, type_name, alias)
    oneway: bool = False


@dataclass(frozen=True)
class ThriftService:
    name: str
    methods: Tuple[ThriftServiceMethod, ...]


@dataclass(frozen=True)
class ThriftDocument:
    namespaces: Dict[str, str]
    includes: Tuple[str, ...]
    typedefs: Dict[str, str]
    enums: Tuple[ThriftEnum, ...]
    structs: Tuple[ThriftStruct, ...]
    services: Tuple[ThriftService, ...]
    raw: str


def is_thrift(content: str) -> bool:
    """Return ``True`` when ``content`` looks like Thrift IDL."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if re.search(r"""^\s*\$version\s*:\s*['"]""", trimmed, re.MULTILINE):
        return False
    if re.search(r'\binclude\s+"', trimmed):
        return True
    if re.search(r"^\s*namespace\s+\w+\s+", trimmed, re.MULTILINE):
        return True
    for pattern in (
        r"\bstruct\s+\w+\s*\{",
        r"\benum\s+\w+\s*\{",
        r"\bunion\s+\w+\s*\{",
        r"\bexception\s+\w+\s*\{",
        r"\bservice\s+\w+\s*\{",
        r"\btypedef\s+",
    ):
        if re.search(pattern, trimmed):
            return True
    return False


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    text = re.sub(r"//[^\n]*", " ", text)
    text = re.sub(r"#[^\n]*", " ", text)
    return text


def _find_matching_brace(s: str, start: int) -> int:
    depth = 1
    i = start
    while i < len(s) and depth > 0:
        c = s[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    return i - 1 if depth == 0 else -1


def _collect_typedefs(cleaned: str) -> Dict[str, str]:
    typedefs: Dict[str, str] = {}
    for match in re.finditer(r"\btypedef\s+([\w.<>, \t]+?)\s+(\w+)\s*[,;]", cleaned):
        typedefs[match.group(2).strip()] = match.group(1).strip()
    return typedefs


def _resolve_typedef(
    type_expr: str,
    typedefs: Dict[str, str],
    visited: Optional[set[str]] = None,
) -> str:
    visited = visited or set()
    t = type_expr.strip()
    list_match = re.fullmatch(r"list\s*<\s*([\w.<>, \t]+)\s*>", t)
    if list_match:
        inner = _resolve_typedef(list_match.group(1).strip(), typedefs, visited)
        return f"list<{inner}>"
    set_match = re.fullmatch(r"set\s*<\s*([\w.<>, \t]+)\s*>", t)
    if set_match:
        inner = _resolve_typedef(set_match.group(1).strip(), typedefs, visited)
        return f"set<{inner}>"
    map_match = re.fullmatch(r"map\s*<\s*([\w.<>, \t]+)\s*,\s*([\w.<>, \t]+)\s*>", t)
    if map_match:
        key = _resolve_typedef(map_match.group(1).strip(), typedefs, visited)
        value = _resolve_typedef(map_match.group(2).strip(), typedefs, visited)
        return f"map<{key},{value}>"
    if t in visited:
        return t
    resolved = typedefs.get(t)
    if not resolved:
        return t
    visited.add(t)
    return _resolve_typedef(resolved, typedefs, visited)


def _parse_field_type(s: str, start: int) -> Tuple[str, int]:
    i = start
    while i < len(s) and s[i].isspace():
        i += 1
    if i >= len(s):
        return "", i
    type_start = i
    kw_match = re.match(r"^(list|set|map)\s*<", s[i:])
    if kw_match:
        kw = kw_match.group(1)
        i += len(kw)
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s) or s[i] != "<":
            return s[type_start:i].strip(), i
        i += 1
        depth = 1
        if kw == "map":
            while i < len(s) and depth > 0:
                if s[i] == "<":
                    depth += 1
                elif s[i] == ">":
                    depth -= 1
                i += 1
        else:
            while i < len(s) and depth > 0:
                if s[i] == "<":
                    depth += 1
                elif s[i] == ">":
                    depth -= 1
                i += 1
        return s[type_start:i].strip(), i
    while i < len(s) and (s[i].isalnum() or s[i] in "._"):
        i += 1
    return s[type_start:i].strip(), i


def _parse_struct_fields(inner: str, typedefs: Dict[str, str]) -> Tuple[ThriftField, ...]:
    fields: List[ThriftField] = []
    i = 0
    while i < len(inner):
        while i < len(inner) and inner[i] in " \t,;\n\r":
            i += 1
        if i >= len(inner):
            break
        id_match = re.match(r"(\d+)\s*:", inner[i:])
        if not id_match:
            break
        i += id_match.end()
        while i < len(inner) and inner[i].isspace():
            i += 1
        req_match = re.match(r"(required|optional)\s+", inner[i:])
        required = bool(req_match and req_match.group(1) == "required")
        if req_match:
            i += req_match.end()
        raw_type, type_end = _parse_field_type(inner, i)
        i = type_end
        if not raw_type:
            break
        while i < len(inner) and inner[i].isspace():
            i += 1
        name_match = re.match(r"(\w+)\s*(=\s*[^,;\n]*)?\s*[,;\n]", inner[i:])
        if not name_match:
            break
        field_name = name_match.group(1)
        default = name_match.group(2).strip() if name_match.group(2) else None
        if default and default.startswith("="):
            default = default[1:].strip()
        i += name_match.end()
        resolved = _resolve_typedef(re.sub(r"\s+", " ", raw_type), typedefs)
        fields.append(
            ThriftField(
                id=int(id_match.group(1)),
                name=field_name,
                required=required,
                type_expr=resolved,
                default=default,
            )
        )
    return tuple(fields)


def _parse_enum_values(inner: str) -> Tuple[Tuple[str, Optional[int]], ...]:
    values: List[Tuple[str, Optional[int]]] = []
    for match in re.finditer(r"(\w+)\s*(?:=\s*(-?[\w.]+))?\s*[,;\n]?", inner):
        name = match.group(1)
        if not name:
            continue
        raw_value = match.group(2)
        numeric: Optional[int] = None
        if raw_value is not None:
            try:
                numeric = int(raw_value, 0)
            except ValueError:
                numeric = None
        values.append((name, numeric))
    return tuple(values)


def _parse_service_methods(inner: str, typedefs: Dict[str, str]) -> Tuple[ThriftServiceMethod, ...]:
    methods: List[ThriftServiceMethod] = []
    # Split on method boundaries at top level (semicolon-terminated declarations).
    chunks = re.split(r"(?<=[,;])\s*", inner)
    buffer = ""
    for chunk in chunks:
        buffer = f"{buffer} {chunk}".strip() if buffer else chunk.strip()
        if not buffer:
            continue
        if not buffer.endswith(",") and not buffer.endswith(";"):
            continue
        decl = buffer.rstrip(",;").strip()
        buffer = ""
        if not decl or decl.startswith("//"):
            continue
        oneway = False
        if decl.startswith("oneway "):
            oneway = True
            decl = decl[7:].strip()
        throws: List[Tuple[int, str, str]] = []
        throws_match = re.search(r"\bthrows\s*\((.*)\)\s*$", decl)
        if throws_match:
            throws_inner = throws_match.group(1)
            decl = decl[: throws_match.start()].strip()
            for tm in re.finditer(r"(\d+)\s*:\s*([\w.]+)\s+(\w+)", throws_inner):
                throws.append((int(tm.group(1)), tm.group(2), tm.group(3)))
        paren = decl.find("(")
        if paren == -1:
            continue
        head = decl[:paren].strip()
        close = decl.rfind(")")
        if close == -1:
            continue
        params_inner = decl[paren + 1 : close]
        head_parts = head.rsplit(None, 1)
        if len(head_parts) != 2:
            continue
        return_type, method_name = head_parts[0], head_parts[1]
        parameters = _parse_struct_fields(params_inner, typedefs)
        methods.append(
            ThriftServiceMethod(
                name=method_name,
                return_type=_resolve_typedef(return_type, typedefs),
                parameters=parameters,
                throws=tuple(throws),
                oneway=oneway,
            )
        )
    return tuple(methods)


def parse_thrift(content: str, *, source_label: Optional[str] = None) -> ThriftDocument:
    """Parse Thrift IDL text into a :class:`ThriftDocument`.

    Raises:
        ThriftParseError: When the content is empty, not Thrift, or has no definitions.
    """
    if not content or not content.strip():
        raise ThriftParseError("Invalid or empty Thrift content")
    if not is_thrift(content):
        raise ThriftParseError("Content does not appear to be a Thrift IDL definition")

    cleaned = _strip_comments(content)
    typedefs = _collect_typedefs(cleaned)

    namespaces: Dict[str, str] = {}
    for match in re.finditer(r"^\s*namespace\s+(\w+)\s+([\w.]+)", cleaned, re.MULTILINE):
        namespaces[match.group(1)] = match.group(2)

    includes: List[str] = []
    for match in re.finditer(r'\binclude\s+"([^"]+)"', cleaned):
        includes.append(match.group(1))

    enums: List[ThriftEnum] = []
    for match in re.finditer(r"\benum\s+(\w+)\s*\{", cleaned):
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        values = _parse_enum_values(inner)
        if values:
            enums.append(ThriftEnum(name=match.group(1), values=values))

    structs: List[ThriftStruct] = []
    for match in re.finditer(r"\b(struct|union|exception)\s+(\w+)\s*(?:xsd_all)?\s*\{", cleaned):
        kind, name = match.group(1), match.group(2)
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        fields = _parse_struct_fields(inner, typedefs)
        structs.append(ThriftStruct(name=name, kind=kind, fields=fields))

    services: List[ThriftService] = []
    for match in re.finditer(r"\bservice\s+(\w+)\s*\{", cleaned):
        name = match.group(1)
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        methods = _parse_service_methods(inner, typedefs)
        services.append(ThriftService(name=name, methods=methods))

    if not enums and not structs and not services:
        label = f" ({source_label})" if source_label else ""
        raise ThriftParseError(
            f"No struct, union, exception, enum, or service definitions found in the Thrift file{label}"
        )

    return ThriftDocument(
        namespaces=namespaces,
        includes=tuple(includes),
        typedefs=typedefs,
        enums=tuple(enums),
        structs=tuple(structs),
        services=tuple(services),
        raw=content,
    )
