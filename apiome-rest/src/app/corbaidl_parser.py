"""CORBA / OMG IDL parser — MFI-21.7.

Parses ``.idl`` source text into a typed :class:`CorbaIdlDocument` AST using lightweight
regex and brace matching (no external IDL compiler dependency). Syntax errors surface as
:class:`CorbaIdlParseError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

__all__ = [
    "CorbaIdlParseError",
    "CorbaIdlEnum",
    "CorbaIdlTypedef",
    "CorbaIdlField",
    "CorbaIdlStruct",
    "CorbaIdlParameter",
    "CorbaIdlOperation",
    "CorbaIdlInterface",
    "CorbaIdlDocument",
    "is_corbaidl",
    "parse_corbaidl",
]

_CORBA_BASE_TYPES = frozenset(
    {
        "void",
        "boolean",
        "char",
        "wchar",
        "octet",
        "short",
        "unsigned short",
        "long",
        "unsigned long",
        "float",
        "double",
        "string",
        "wstring",
        "any",
        "Object",
    }
)

_PARAM_DIRECTIONS = frozenset({"in", "out", "inout"})


class CorbaIdlParseError(ValueError):
    """Raised when CORBA IDL cannot be parsed."""


@dataclass(frozen=True)
class CorbaIdlEnum:
    name: str
    values: Tuple[Tuple[str, Optional[int]], ...]


@dataclass(frozen=True)
class CorbaIdlTypedef:
    name: str
    type_expr: str


@dataclass(frozen=True)
class CorbaIdlField:
    name: str
    type_expr: str


@dataclass(frozen=True)
class CorbaIdlStruct:
    name: str
    kind: str  # struct | exception
    fields: Tuple[CorbaIdlField, ...]


@dataclass(frozen=True)
class CorbaIdlParameter:
    name: str
    type_expr: str
    direction: str = "in"


@dataclass(frozen=True)
class CorbaIdlOperation:
    name: str
    return_type: str
    parameters: Tuple[CorbaIdlParameter, ...]
    raises: Tuple[str, ...]


@dataclass(frozen=True)
class CorbaIdlInterface:
    name: str
    operations: Tuple[CorbaIdlOperation, ...]


@dataclass(frozen=True)
class CorbaIdlDocument:
    module: Optional[str]
    typedefs: Tuple[CorbaIdlTypedef, ...]
    enums: Tuple[CorbaIdlEnum, ...]
    structs: Tuple[CorbaIdlStruct, ...]
    interfaces: Tuple[CorbaIdlInterface, ...]
    raw: str


def is_corbaidl(content: str) -> bool:
    """Return ``True`` when ``content`` looks like CORBA / OMG IDL."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if re.search(r"\bnamespace\s+\w+\s+", trimmed) or 'include "' in trimmed:
        return False
    if re.search(r"\bservice\s+\w+\s*\{", trimmed):
        return False
    if re.search(r"\bprogram\s+\w+\s*\{", trimmed):
        return False
    if re.search(r"\bmodule\s+\w+\s*\{", trimmed) and re.search(
        r"\binterface\s+\w+", trimmed
    ):
        return True
    if re.search(r"\binterface\s+\w+\s*\{", trimmed) and re.search(
        r"\b(struct|exception|enum|typedef)\b", trimmed
    ):
        return True
    if re.search(r"\braises\s*\(", trimmed) and re.search(r"\bexception\s+\w+", trimmed):
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


def _collect_typedefs(cleaned: str) -> Dict[str, str]:
    typedefs: Dict[str, str] = {}
    for match in re.finditer(r"\btypedef\s+([\w.<>, \t]+?)\s+(\w+)\s*;", cleaned):
        typedefs[match.group(2).strip()] = re.sub(r"\s+", " ", match.group(1).strip())
    return typedefs


def _resolve_typedef(
    type_expr: str,
    typedefs: Dict[str, str],
    visited: Optional[set[str]] = None,
) -> str:
    visited = visited or set()
    t = re.sub(r"\s+", " ", type_expr.strip())
    seq_match = re.fullmatch(r"sequence\s*<\s*([\w.<>, \t]+)\s*>", t)
    if seq_match:
        inner = _resolve_typedef(seq_match.group(1).strip(), typedefs, visited)
        return f"sequence<{inner}>"
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
    seq_match = re.match(r"^sequence\s*<", s[i:])
    if seq_match:
        i += len(seq_match.group(0)) - 1
        depth = 1
        i += 1
        while i < len(s) and depth > 0:
            if s[i] == "<":
                depth += 1
            elif s[i] == ">":
                depth -= 1
            i += 1
        return re.sub(r"\s+", " ", s[type_start:i].strip()), i
    while i < len(s) and (s[i].isalnum() or s[i] in "._"):
        i += 1
    return s[type_start:i].strip(), i


def _parse_struct_fields(inner: str, typedefs: Dict[str, str]) -> Tuple[CorbaIdlField, ...]:
    fields: List[CorbaIdlField] = []
    i = 0
    while i < len(inner):
        while i < len(inner) and inner[i] in " \t,;\n\r":
            i += 1
        if i >= len(inner):
            break
        raw_type, type_end = _parse_field_type(inner, i)
        i = type_end
        if not raw_type:
            break
        while i < len(inner) and inner[i].isspace():
            i += 1
        name_match = re.match(r"(\w+)\s*[,;\n]", inner[i:])
        if not name_match:
            break
        field_name = name_match.group(1)
        i += name_match.end()
        resolved = _resolve_typedef(raw_type, typedefs)
        fields.append(CorbaIdlField(name=field_name, type_expr=resolved))
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


def _parse_parameters(params_inner: str, typedefs: Dict[str, str]) -> Tuple[CorbaIdlParameter, ...]:
    parameters: List[CorbaIdlParameter] = []
    for chunk in params_inner.split(","):
        decl = chunk.strip()
        if not decl:
            continue
        direction = "in"
        dir_match = re.match(r"^(in|out|inout)\s+", decl)
        if dir_match:
            direction = dir_match.group(1)
            decl = decl[dir_match.end() :].strip()
        raw_type, type_end = _parse_field_type(decl, 0)
        if not raw_type:
            continue
        rest = decl[type_end:].strip()
        name_match = re.match(r"(\w+)\s*$", rest)
        if not name_match:
            continue
        parameters.append(
            CorbaIdlParameter(
                name=name_match.group(1),
                type_expr=_resolve_typedef(raw_type, typedefs),
                direction=direction,
            )
        )
    return tuple(parameters)


def _parse_interface_operations(inner: str, typedefs: Dict[str, str]) -> Tuple[CorbaIdlOperation, ...]:
    operations: List[CorbaIdlOperation] = []
    decls = [part.strip() for part in inner.split(";") if part.strip()]
    for decl in decls:
        if decl.startswith("attribute "):
            continue
        raises: List[str] = []
        raises_match = re.search(r"\braises\s*\(([^)]*)\)\s*$", decl)
        if raises_match:
            raises_inner = raises_match.group(1)
            decl = decl[: raises_match.start()].strip()
            raises = [name.strip() for name in raises_inner.split(",") if name.strip()]
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
        operations.append(
            CorbaIdlOperation(
                name=method_name,
                return_type=_resolve_typedef(return_type, typedefs),
                parameters=_parse_parameters(params_inner, typedefs),
                raises=tuple(raises),
            )
        )
    return tuple(operations)


def _extract_module_body(cleaned: str) -> Tuple[Optional[str], str]:
    match = re.search(r"\bmodule\s+(\w+)\s*\{", cleaned)
    if not match:
        return None, cleaned
    open_brace = cleaned.find("{", match.start())
    close = _find_matching_brace(cleaned, open_brace + 1)
    if close == -1:
        return match.group(1), cleaned
    return match.group(1), cleaned[open_brace + 1 : close]


def _parse_definitions(
    scope: str,
    typedefs: Dict[str, str],
) -> Tuple[
    Tuple[CorbaIdlEnum, ...],
    Tuple[CorbaIdlStruct, ...],
    Tuple[CorbaIdlInterface, ...],
]:
    enums: List[CorbaIdlEnum] = []
    structs: List[CorbaIdlStruct] = []
    interfaces: List[CorbaIdlInterface] = []

    for match in re.finditer(r"\benum\s+(\w+)\s*\{", scope):
        open_brace = scope.find("{", match.start())
        close = _find_matching_brace(scope, open_brace + 1)
        if close == -1:
            continue
        inner = scope[open_brace + 1 : close]
        values = _parse_enum_values(inner)
        if values:
            enums.append(CorbaIdlEnum(name=match.group(1), values=values))

    for match in re.finditer(r"\b(struct|exception)\s+(\w+)\s*\{", scope):
        kind, name = match.group(1), match.group(2)
        open_brace = scope.find("{", match.start())
        close = _find_matching_brace(scope, open_brace + 1)
        if close == -1:
            continue
        inner = scope[open_brace + 1 : close]
        fields = _parse_struct_fields(inner, typedefs)
        structs.append(CorbaIdlStruct(name=name, kind=kind, fields=fields))

    for match in re.finditer(r"\binterface\s+(\w+)\s*\{", scope):
        name = match.group(1)
        open_brace = scope.find("{", match.start())
        close = _find_matching_brace(scope, open_brace + 1)
        if close == -1:
            continue
        inner = scope[open_brace + 1 : close]
        operations = _parse_interface_operations(inner, typedefs)
        interfaces.append(CorbaIdlInterface(name=name, operations=operations))

    return tuple(enums), tuple(structs), tuple(interfaces)


def parse_corbaidl(content: str, *, source_label: Optional[str] = None) -> CorbaIdlDocument:
    """Parse CORBA / OMG IDL text into a :class:`CorbaIdlDocument`."""
    if not content or not content.strip():
        raise CorbaIdlParseError("Invalid or empty CORBA IDL content")
    if not is_corbaidl(content):
        raise CorbaIdlParseError("Content does not appear to be a CORBA IDL definition")

    cleaned = _strip_comments(content)
    module_name, scope = _extract_module_body(cleaned)
    typedef_map = _collect_typedefs(scope)
    enums, structs, interfaces = _parse_definitions(scope, typedef_map)

    if not enums and not structs and not interfaces:
        label = f" ({source_label})" if source_label else ""
        raise CorbaIdlParseError(
            f"No struct, exception, enum, or interface definitions found in the CORBA IDL file{label}"
        )

    typedefs = tuple(CorbaIdlTypedef(name=name, type_expr=expr) for name, expr in typedef_map.items())
    return CorbaIdlDocument(
        module=module_name,
        typedefs=typedefs,
        enums=enums,
        structs=structs,
        interfaces=interfaces,
        raw=content,
    )
