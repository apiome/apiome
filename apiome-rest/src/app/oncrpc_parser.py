"""ONC RPC / XDR (RPCL) parser — MFI-21.6.

Parses rpcgen ``.x`` source text into a typed :class:`OncRpcDocument` AST using lightweight
regex and brace matching (no external ``rpcgen`` dependency). Syntax errors surface as
:class:`OncRpcParseError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "OncRpcParseError",
    "OncRpcEnum",
    "OncRpcTypedef",
    "OncRpcField",
    "OncRpcUnionCase",
    "OncRpcStruct",
    "OncRpcProcedure",
    "OncRpcVersion",
    "OncRpcProgram",
    "OncRpcDocument",
    "is_oncrpc",
    "parse_oncrpc",
]

_XDR_BASE_TYPES = frozenset(
    {
        "int",
        "unsigned",
        "short",
        "unsigned short",
        "long",
        "unsigned long",
        "hyper",
        "unsigned hyper",
        "float",
        "double",
        "bool",
        "string",
        "opaque",
        "void",
        "char",
        "wchar",
    }
)


class OncRpcParseError(ValueError):
    """Raised when ONC RPC / XDR RPCL cannot be parsed."""


@dataclass(frozen=True)
class OncRpcEnum:
    name: str
    values: Tuple[Tuple[str, Optional[int]], ...]


@dataclass(frozen=True)
class OncRpcTypedef:
    name: str
    type_expr: str


@dataclass(frozen=True)
class OncRpcField:
    name: str
    type_expr: str


@dataclass(frozen=True)
class OncRpcUnionCase:
    label: str
    fields: Tuple[OncRpcField, ...]


@dataclass(frozen=True)
class OncRpcStruct:
    name: str
    kind: str  # struct | union
    fields: Tuple[OncRpcField, ...] = ()
    switch_type: Optional[str] = None
    switch_field: Optional[str] = None
    cases: Tuple[OncRpcUnionCase, ...] = ()


@dataclass(frozen=True)
class OncRpcProcedure:
    name: str
    number: int
    arg_type: str
    return_type: str


@dataclass(frozen=True)
class OncRpcVersion:
    name: str
    number: int
    procedures: Tuple[OncRpcProcedure, ...]


@dataclass(frozen=True)
class OncRpcProgram:
    name: str
    number: int
    versions: Tuple[OncRpcVersion, ...]


@dataclass(frozen=True)
class OncRpcDocument:
    enums: Tuple[OncRpcEnum, ...]
    typedefs: Tuple[OncRpcTypedef, ...]
    structs: Tuple[OncRpcStruct, ...]
    programs: Tuple[OncRpcProgram, ...]
    raw: str


def is_oncrpc(content: str) -> bool:
    """Return ``True`` when ``content`` looks like ONC RPC / XDR RPCL."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if re.search(r"\bprogram\s+\w+\s*\{", trimmed):
        return True
    if re.search(r"\bunion\s+\w+\s+switch\s*\(", trimmed):
        return True
    if re.search(r"\bstruct\s+\w+\s*\{", trimmed) and re.search(
        r"\b(enum|typedef|program)\b", trimmed
    ):
        return True
    return False


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    text = re.sub(r"//[^\n]*", " ", text)
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


def _parse_enum_values(inner: str) -> Tuple[Tuple[str, Optional[int]], ...]:
    values: List[Tuple[str, Optional[int]]] = []
    for match in re.finditer(r"(\w+)\s*(?:=\s*(-?[\w.]+))?\s*[,;]?", inner):
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


def _parse_struct_fields(inner: str) -> Tuple[OncRpcField, ...]:
    fields: List[OncRpcField] = []
    for part in inner.split(";"):
        chunk = part.strip()
        if not chunk:
            continue
        match = re.match(r"([\w.<>, \t]+?)\s+(\w+)(?:\s*<(\d+)>)?\s*$", chunk)
        if not match:
            continue
        base_type = match.group(1).strip()
        bound = match.group(3)
        type_expr = f"{base_type}<{bound}>" if bound else base_type
        fields.append(OncRpcField(name=match.group(2), type_expr=type_expr))
    return tuple(fields)


def _parse_union_cases(inner: str) -> Tuple[OncRpcUnionCase, ...]:
    cases: List[OncRpcUnionCase] = []
    for match in re.finditer(
        r"(case\s+([\w.]+)|default)\s*:\s*([\s\S]*?)(?=(?:case\s+[\w.]+|default)\s*:|$)",
        inner,
    ):
        label = match.group(2) if match.group(1).startswith("case") else "default"
        body = match.group(3).strip()
        if body == "void" or not body:
            cases.append(OncRpcUnionCase(label=label, fields=()))
            continue
        field_match = re.match(r"([\w.<>, \t]+?)\s+(\w+)\s*;?\s*$", body)
        if field_match:
            cases.append(
                OncRpcUnionCase(
                    label=label,
                    fields=(
                        OncRpcField(
                            name=field_match.group(2),
                            type_expr=field_match.group(1).strip(),
                        ),
                    ),
                )
            )
        else:
            cases.append(OncRpcUnionCase(label=label, fields=_parse_struct_fields(body)))
    return tuple(cases)


def _parse_procedures(inner: str) -> Tuple[OncRpcProcedure, ...]:
    procedures: List[OncRpcProcedure] = []
    for match in re.finditer(
        r"([\w.<>, \t]+?)\s+(\w+)\s*\(\s*([\w.<>, \t]*)\s*\)\s*=\s*(\d+)\s*;",
        inner,
    ):
        procedures.append(
            OncRpcProcedure(
                name=match.group(2),
                number=int(match.group(4)),
                arg_type=match.group(3).strip() or "void",
                return_type=match.group(1).strip(),
            )
        )
    return tuple(procedures)


def _parse_typedefs(cleaned: str) -> Tuple[OncRpcTypedef, ...]:
    typedefs: List[OncRpcTypedef] = []
    for match in re.finditer(
        r"typedef\s+(\w+)\s+(\w+)(?:\s*<(\d+)>)?\s*;",
        cleaned,
    ):
        base = match.group(1)
        name = match.group(2)
        bound = match.group(3)
        type_expr = f"{base}<{bound}>" if bound else base
        typedefs.append(OncRpcTypedef(name=name, type_expr=type_expr))
    return tuple(typedefs)


def _parse_versions(inner: str) -> Tuple[OncRpcVersion, ...]:
    versions: List[OncRpcVersion] = []
    for match in re.finditer(r"version\s+(\w+)\s*\{", inner):
        name = match.group(1)
        start = match.end()
        end = _find_matching_brace(inner, start)
        if end < 0:
            raise OncRpcParseError(f"Unclosed version `{name}`")
        body = inner[start:end]
        tail = inner[end + 1 : end + 32]
        number_match = re.match(r"\s*=\s*(\d+)\s*;", tail)
        if not number_match:
            raise OncRpcParseError(f"Version `{name}` is missing a numeric assignment")
        versions.append(
            OncRpcVersion(
                name=name,
                number=int(number_match.group(1)),
                procedures=_parse_procedures(body),
            )
        )
    return tuple(versions)


def _parse_programs(cleaned: str) -> Tuple[OncRpcProgram, ...]:
    programs: List[OncRpcProgram] = []
    for match in re.finditer(r"program\s+(\w+)\s*\{", cleaned):
        name = match.group(1)
        start = match.end()
        end = _find_matching_brace(cleaned, start)
        if end < 0:
            raise OncRpcParseError(f"Unclosed program `{name}`")
        inner = cleaned[start:end]
        tail = cleaned[end + 1 : end + 32]
        number_match = re.match(r"\s*=\s*(0x[\da-fA-F]+|\d+)\s*;", tail)
        if not number_match:
            raise OncRpcParseError(f"Program `{name}` is missing a numeric assignment")
        programs.append(
            OncRpcProgram(
                name=name,
                number=int(number_match.group(1), 0),
                versions=_parse_versions(inner),
            )
        )
    return tuple(programs)


def parse_oncrpc(content: str, *, source_label: Optional[str] = None) -> OncRpcDocument:
    """Parse ONC RPC / XDR RPCL text into an :class:`OncRpcDocument`."""
    if not content or not content.strip():
        raise OncRpcParseError("Invalid or empty ONC RPC document")
    if not is_oncrpc(content):
        label = f" ({source_label})" if source_label else ""
        raise OncRpcParseError(f"Content does not appear to be ONC RPC / XDR RPCL{label}")

    cleaned = _strip_comments(content)
    enums: List[OncRpcEnum] = []
    for match in re.finditer(r"enum\s+(\w+)\s*\{([^}]*)\}\s*;", cleaned):
        enums.append(OncRpcEnum(name=match.group(1), values=_parse_enum_values(match.group(2))))

    typedefs = _parse_typedefs(cleaned)

    structs: List[OncRpcStruct] = []
    for match in re.finditer(
        r"union\s+(\w+)\s+switch\s*\(\s*([\w.<>, \t]+?)\s+(\w+)\s*\)\s*\{",
        cleaned,
    ):
        name = match.group(1)
        start = match.end()
        end = _find_matching_brace(cleaned, start)
        if end < 0:
            raise OncRpcParseError(f"Unclosed union `{name}`")
        structs.append(
            OncRpcStruct(
                name=name,
                kind="union",
                switch_type=match.group(2).strip(),
                switch_field=match.group(3).strip(),
                cases=_parse_union_cases(cleaned[start:end]),
            )
        )

    for match in re.finditer(r"struct\s+(\w+)\s*\{", cleaned):
        name = match.group(1)
        start = match.end()
        end = _find_matching_brace(cleaned, start)
        if end < 0:
            raise OncRpcParseError(f"Unclosed struct `{name}`")
        structs.append(
            OncRpcStruct(
                name=name,
                kind="struct",
                fields=_parse_struct_fields(cleaned[start:end]),
            )
        )

    programs = _parse_programs(cleaned)
    if not structs and not enums and not programs:
        label = f" ({source_label})" if source_label else ""
        raise OncRpcParseError(f"No ONC RPC types or programs found{label}")

    return OncRpcDocument(
        enums=tuple(enums),
        typedefs=tuple(typedefs),
        structs=tuple(structs),
        programs=tuple(programs),
        raw=content,
    )
