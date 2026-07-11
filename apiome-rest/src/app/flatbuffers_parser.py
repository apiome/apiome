"""FlatBuffers schema (``.fbs``) parser — MFI-13.1.

Parses FlatBuffers IDL into a typed :class:`FlatBuffersDocument` AST using lightweight regex
and brace matching (no external ``flatc`` dependency). Syntax errors surface as
:class:`FlatBuffersParseError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "FlatBuffersParseError",
    "FbsEnum",
    "FbsField",
    "FbsTypeDef",
    "FlatBuffersDocument",
    "is_flatbuffers",
    "parse_flatbuffers",
]

_FBS_BASE_TYPES = frozenset(
    {
        "bool",
        "byte",
        "ubyte",
        "short",
        "ushort",
        "int",
        "uint",
        "long",
        "ulong",
        "float",
        "double",
        "string",
    }
)


class FlatBuffersParseError(ValueError):
    """Raised when FlatBuffers schema text cannot be parsed."""


@dataclass(frozen=True)
class FbsEnum:
    name: str
    base_type: Optional[str]
    values: Tuple[Tuple[str, Optional[int]], ...]


@dataclass(frozen=True)
class FbsField:
    name: str
    type_expr: str
    default: Optional[str] = None


@dataclass(frozen=True)
class FbsTypeDef:
    name: str
    kind: str  # table | struct | union
    fields: Tuple[FbsField, ...]


@dataclass(frozen=True)
class FlatBuffersDocument:
    namespace: Optional[str]
    includes: Tuple[str, ...]
    enums: Tuple[FbsEnum, ...]
    types: Tuple[FbsTypeDef, ...]
    root_type: Optional[str]
    raw: str


def is_flatbuffers(content: str) -> bool:
    """Return ``True`` when ``content`` looks like a FlatBuffers ``.fbs`` schema."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if re.search(r"\broot_type\s+\w+", trimmed):
        return True
    if re.search(r"\btable\s+\w+\s*\{", trimmed):
        return True
    if re.search(r"\bstruct\s+\w+\s*\{", trimmed) and not re.search(
        r"\bstruct\s+\w+\s*\{[^}]*\b\d+\s*:", trimmed
    ):
        return True
    if re.search(r"\bunion\s+\w+\s*\{", trimmed):
        return True
    if re.search(r"\benum\s+\w+(?:\s*:\s*\w+)?\s*\{", trimmed) and "table " in trimmed:
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


def _parse_fields(inner: str) -> Tuple[FbsField, ...]:
    fields: List[FbsField] = []
    for part in inner.split(";"):
        chunk = part.strip()
        if not chunk:
            continue
        match = re.match(r"(\w+)\s*:\s*(\[[\w.]+\]|\w+)(?:\s*=\s*(.+))?$", chunk)
        if not match:
            continue
        default = match.group(3).strip() if match.group(3) else None
        fields.append(
            FbsField(
                name=match.group(1),
                type_expr=match.group(2).strip(),
                default=default,
            )
        )
    return tuple(fields)


def _parse_union_members(inner: str) -> Tuple[FbsField, ...]:
    members = [m.strip() for m in inner.replace("\n", " ").split(",") if m.strip()]
    return tuple(FbsField(name=member, type_expr=member) for member in members)


def parse_flatbuffers(content: str, *, source_label: Optional[str] = None) -> FlatBuffersDocument:
    """Parse FlatBuffers schema text into a :class:`FlatBuffersDocument`."""
    if not content or not content.strip():
        raise FlatBuffersParseError("Invalid or empty FlatBuffers schema")
    if not is_flatbuffers(content):
        raise FlatBuffersParseError("Content does not appear to be a FlatBuffers .fbs schema")

    cleaned = _strip_comments(content)

    namespace: Optional[str] = None
    ns_match = re.search(r"^\s*namespace\s+([\w.]+)\s*;", cleaned, re.MULTILINE)
    if ns_match:
        namespace = ns_match.group(1)

    includes: List[str] = []
    for match in re.finditer(r'\binclude\s+"([^"]+)"\s*;', cleaned):
        includes.append(match.group(1))

    root_type: Optional[str] = None
    root_match = re.search(r"\broot_type\s+(\w+)\s*;", cleaned)
    if root_match:
        root_type = root_match.group(1)

    enums: List[FbsEnum] = []
    for match in re.finditer(r"\benum\s+(\w+)(?:\s*:\s*(\w+))?\s*\{", cleaned):
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        values = _parse_enum_values(inner)
        if values:
            enums.append(
                FbsEnum(
                    name=match.group(1),
                    base_type=match.group(2),
                    values=values,
                )
            )

    types: List[FbsTypeDef] = []
    for kind in ("table", "struct", "union"):
        pattern = rf"\b{kind}\s+(\w+)\s*\{{"
        for match in re.finditer(pattern, cleaned):
            name = match.group(1)
            open_brace = cleaned.find("{", match.start())
            close = _find_matching_brace(cleaned, open_brace + 1)
            if close == -1:
                continue
            inner = cleaned[open_brace + 1 : close]
            if kind == "union":
                fields = _parse_union_members(inner)
            else:
                fields = _parse_fields(inner)
            types.append(FbsTypeDef(name=name, kind=kind, fields=fields))

    if not enums and not types:
        label = f" ({source_label})" if source_label else ""
        raise FlatBuffersParseError(
            f"No table, struct, union, or enum definitions found in the FlatBuffers schema{label}"
        )

    return FlatBuffersDocument(
        namespace=namespace,
        includes=tuple(includes),
        enums=tuple(enums),
        types=tuple(types),
        root_type=root_type,
        raw=content,
    )
