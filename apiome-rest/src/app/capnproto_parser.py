"""Cap'n Proto schema (``.capnp``) parser — MFI-14.1.

Parses Cap'n Proto IDL into a typed :class:`CapnpDocument` AST using lightweight regex
and brace matching (no external ``capnp`` compiler dependency). Syntax errors surface as
:class:`CapnpParseError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

__all__ = [
    "CapnpParseError",
    "CapnpEnum",
    "CapnpField",
    "CapnpInterface",
    "CapnpInterfaceMethod",
    "CapnpStruct",
    "CapnpDocument",
    "is_capnproto",
    "parse_capnproto",
]


class CapnpParseError(ValueError):
    """Raised when Cap'n Proto schema text cannot be parsed."""


@dataclass(frozen=True)
class CapnpEnum:
    name: str
    qualified_name: str
    values: Tuple[Tuple[str, int], ...]


@dataclass(frozen=True)
class CapnpField:
    slot: int
    name: str
    type_expr: str


@dataclass(frozen=True)
class CapnpStruct:
    name: str
    qualified_name: str
    fields: Tuple[CapnpField, ...]


@dataclass(frozen=True)
class CapnpInterfaceMethod:
    name: str
    slot: int
    parameters: Tuple[CapnpField, ...]
    results: Tuple[CapnpField, ...]


@dataclass(frozen=True)
class CapnpInterface:
    name: str
    methods: Tuple[CapnpInterfaceMethod, ...]


@dataclass(frozen=True)
class CapnpDocument:
    file_id: Optional[str]
    imports: Tuple[str, ...]
    structs: Tuple[CapnpStruct, ...]
    enums: Tuple[CapnpEnum, ...]
    interfaces: Tuple[CapnpInterface, ...]
    raw: str


def is_capnproto(content: str) -> bool:
    """Return ``True`` when ``content`` looks like a Cap'n Proto ``.capnp`` schema."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if re.search(r"@0x[0-9a-fA-F]+\s*;", trimmed):
        return True
    if re.search(r"\binterface\s+\w+\s*\{", trimmed):
        return True
    if re.search(r"\bstruct\s+\w+\s*\{[^}]*@\d+\s*:", trimmed, re.DOTALL):
        return True
    if re.search(r"\benum\s+\w+\s*\{[^}]*@\d+\s*;", trimmed, re.DOTALL):
        return True
    return False


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*[\s\S]*?\*/", " ", text)
    text = re.sub(r"#[^\n]*", " ", text)
    text = re.sub(r"//[^\n]*", " ", text)
    return text


def _brace_depth_at(text: str, pos: int) -> int:
    depth = 0
    for ch in text[:pos]:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
    return depth


def _find_matching_brace(text: str, start: int) -> int:
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return i - 1 if depth == 0 else -1


def _split_top_level_commas(chunk: str) -> List[str]:
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    for ch in chunk:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(ch)
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return parts


def _parse_named_types(chunk: str) -> Tuple[CapnpField, ...]:
    fields: List[CapnpField] = []
    for part in _split_top_level_commas(chunk):
        match = re.fullmatch(r"(\w+)\s*:\s*(.+)", part.strip())
        if not match:
            continue
        fields.append(CapnpField(slot=len(fields), name=match.group(1), type_expr=match.group(2).strip()))
    return tuple(fields)


def _parse_enum_values(inner: str) -> Tuple[Tuple[str, int], ...]:
    values: List[Tuple[str, int]] = []
    for match in re.finditer(r"(\w+)\s*@(\d+)\s*;", inner):
        values.append((match.group(1), int(match.group(2))))
    return tuple(values)


def _parse_struct_fields(inner: str) -> Tuple[CapnpField, ...]:
    fields: List[CapnpField] = []
    for match in re.finditer(r"(\w+)\s*@(\d+)\s*:\s*([^;]+);", inner):
        fields.append(
            CapnpField(
                slot=int(match.group(2)),
                name=match.group(1),
                type_expr=match.group(3).strip(),
            )
        )
    return tuple(fields)


def _parse_nested_definitions(
    inner: str,
    *,
    parent_qual: str,
) -> Tuple[List[CapnpStruct], List[CapnpEnum], str]:
    structs: List[CapnpStruct] = []
    enums: List[CapnpEnum] = []
    remainder = inner
    while True:
        match = re.search(r"\b(struct|enum)\s+(\w+)\s*\{", remainder)
        if not match:
            break
        kind = match.group(1)
        name = match.group(2)
        open_brace = remainder.find("{", match.start())
        close = _find_matching_brace(remainder, open_brace + 1)
        if close == -1:
            break
        block_inner = remainder[open_brace + 1 : close]
        qual = f"{parent_qual}.{name}" if parent_qual else name
        if kind == "struct":
            child_structs, child_enums, field_body = _parse_nested_definitions(block_inner, parent_qual=qual)
            structs.extend(child_structs)
            enums.extend(child_enums)
            structs.append(
                CapnpStruct(
                    name=name,
                    qualified_name=qual,
                    fields=_parse_struct_fields(field_body),
                )
            )
        else:
            enums.append(
                CapnpEnum(
                    name=name,
                    qualified_name=qual,
                    values=_parse_enum_values(block_inner),
                )
            )
        remainder = remainder[: match.start()] + " " + remainder[close + 1 :]
    return structs, enums, remainder


def _parse_interface_methods(inner: str) -> Tuple[CapnpInterfaceMethod, ...]:
    methods: List[CapnpInterfaceMethod] = []
    pattern = r"(\w+)\s*@(\d+)\s*\(([^)]*)\)\s*->\s*\(([^)]*)\)\s*;"
    for match in re.finditer(pattern, inner):
        methods.append(
            CapnpInterfaceMethod(
                name=match.group(1),
                slot=int(match.group(2)),
                parameters=_parse_named_types(match.group(3)),
                results=_parse_named_types(match.group(4)),
            )
        )
    return tuple(methods)


def _iter_top_level_blocks(cleaned: str):
    i = 0
    length = len(cleaned)
    while i < length:
        match = re.match(r"\s*(struct|enum|interface)\s+(\w+)\s*\{", cleaned[i:])
        if match and _brace_depth_at(cleaned, i + match.start()) == 0:
            kind = match.group(1)
            name = match.group(2)
            open_brace = i + match.end() - 1
            close = _find_matching_brace(cleaned, open_brace + 1)
            if close == -1:
                i += 1
                continue
            inner = cleaned[open_brace + 1 : close]
            yield kind, name, inner
            i = close + 1
            continue
        i += 1


def parse_capnproto(content: str, *, source_label: Optional[str] = None) -> CapnpDocument:
    """Parse Cap'n Proto schema text into a :class:`CapnpDocument`."""
    if not content or not content.strip():
        raise CapnpParseError("Invalid or empty Cap'n Proto schema")
    if not is_capnproto(content):
        raise CapnpParseError("Content does not appear to be a Cap'n Proto .capnp schema")

    cleaned = _strip_comments(content)

    file_id: Optional[str] = None
    file_match = re.search(r"@0x([0-9a-fA-F]+)\s*;", cleaned)
    if file_match:
        file_id = f"0x{file_match.group(1)}"

    imports: List[str] = []
    for match in re.finditer(r'@\s*import\s+"([^"]+)"\s*;', cleaned):
        imports.append(match.group(1))
    for match in re.finditer(r'using\s+(\w+)\s*=\s*import\s+"([^"]+)"\s*;', cleaned):
        imports.append(match.group(2))

    structs: List[CapnpStruct] = []
    enums: List[CapnpEnum] = []
    interfaces: List[CapnpInterface] = []

    for kind, name, inner in _iter_top_level_blocks(cleaned):
        if kind == "struct":
            nested_structs, nested_enums, field_body = _parse_nested_definitions(inner, parent_qual=name)
            structs.extend(nested_structs)
            enums.extend(nested_enums)
            structs.append(
                CapnpStruct(
                    name=name,
                    qualified_name=name,
                    fields=_parse_struct_fields(field_body),
                )
            )
        elif kind == "enum":
            enums.append(
                CapnpEnum(
                    name=name,
                    qualified_name=name,
                    values=_parse_enum_values(inner),
                )
            )
        elif kind == "interface":
            interfaces.append(
                CapnpInterface(
                    name=name,
                    methods=_parse_interface_methods(inner),
                )
            )

    if not structs and not enums and not interfaces:
        label = f" ({source_label})" if source_label else ""
        raise CapnpParseError(
            f"No struct, enum, or interface definitions found in the Cap'n Proto schema{label}"
        )

    return CapnpDocument(
        file_id=file_id,
        imports=tuple(imports),
        structs=tuple(structs),
        enums=tuple(enums),
        interfaces=tuple(interfaces),
        raw=content,
    )
