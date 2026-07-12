"""Microsoft TypeSpec parser — MFI-22.3.

Parses TypeSpec ``.tsp`` source text into a typed :class:`TypeSpecDocument` AST using lightweight
regex and brace matching (no external ``tsp`` compiler dependency). Syntax errors surface as
:class:`TypeSpecParseError`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

__all__ = [
    "TypeSpecParseError",
    "TypeSpecField",
    "TypeSpecEnum",
    "TypeSpecModel",
    "TypeSpecParameter",
    "TypeSpecOperation",
    "TypeSpecInterface",
    "TypeSpecDocument",
    "is_typespec",
    "parse_typespec",
]

_TYPESPEC_IMPORT_RE = re.compile(r"""^\s*import\s+['"]@typespec/""", re.MULTILINE)
_TYPESPEC_DECL_RE = re.compile(r"^\s*(model|op|interface)\s+\w", re.MULTILINE)
_SMITHY_VERSION_RE = re.compile(r"""^\s*\$version\s*:\s*['"]""", re.MULTILINE)
_SMITHY_KEYWORD_RE = re.compile(
    r"^\s*(service|structure|operation|resource|enum|list|map|union)\s+\w",
    re.MULTILINE,
)
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([\w.]+)\s*;?", re.MULTILINE)
_SERVICE_RE = re.compile(r'@service\(#\{\s*title:\s*"([^"]+)"', re.MULTILINE)
_ROUTE_RE = re.compile(r'@route\(\s*"([^"]+)"\s*\)')
_HTTP_VERB_RE = re.compile(r"@(get|post|put|patch|delete)\b", re.IGNORECASE)
_OPERATION_RE = re.compile(
    r"@(get|post|put|patch|delete)\s+(\w+)\s*\(([^)]*)\)\s*:\s*([^;]+);",
    re.IGNORECASE,
)
_FIELD_RE = re.compile(
    r"^(?:@\w+(?:\([^)]*\))?\s+)*(?P<name>\w+)(\?)?\s*:\s*(?P<type>[^;]+);",
    re.MULTILINE,
)


class TypeSpecParseError(ValueError):
    """Raised when TypeSpec source cannot be parsed."""


@dataclass(frozen=True)
class TypeSpecField:
    name: str
    type_expr: str
    optional: bool
    decorators: Tuple[str, ...]
    documentation: Optional[str] = None


@dataclass(frozen=True)
class TypeSpecEnum:
    name: str
    values: Tuple[str, ...]
    documentation: Optional[str] = None


@dataclass(frozen=True)
class TypeSpecModel:
    name: str
    fields: Tuple[TypeSpecField, ...]
    documentation: Optional[str] = None


@dataclass(frozen=True)
class TypeSpecParameter:
    name: str
    type_expr: str
    location: str


@dataclass(frozen=True)
class TypeSpecOperation:
    name: str
    verb: str
    parameters: Tuple[TypeSpecParameter, ...]
    return_type: str
    is_array_return: bool
    documentation: Optional[str] = None


@dataclass(frozen=True)
class TypeSpecInterface:
    name: str
    route_prefix: Optional[str]
    operations: Tuple[TypeSpecOperation, ...]
    documentation: Optional[str] = None


@dataclass(frozen=True)
class TypeSpecDocument:
    namespace: Optional[str]
    service_title: Optional[str]
    imports: Tuple[str, ...]
    usings: Tuple[str, ...]
    enums: Tuple[TypeSpecEnum, ...]
    models: Tuple[TypeSpecModel, ...]
    interfaces: Tuple[TypeSpecInterface, ...]
    raw: str


def is_typespec(content: str) -> bool:
    """Return ``True`` when ``content`` looks like TypeSpec source."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    if _TYPESPEC_IMPORT_RE.search(trimmed):
        return True
    if _SMITHY_VERSION_RE.search(trimmed):
        return False
    has_namespace = _NAMESPACE_RE.search(trimmed) is not None
    if has_namespace and re.search(r"\bmodel\s+\w", trimmed):
        return True
    if has_namespace and re.search(r"\binterface\s+\w", trimmed):
        return True
    if _SMITHY_KEYWORD_RE.search(trimmed):
        return False
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


def _leading_doc(raw: str, start: int) -> Optional[str]:
    prefix = raw[:start]
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


def _parse_decorators(line: str) -> Tuple[str, ...]:
    return tuple(match.group(0).strip() for match in re.finditer(r"@\w+(?:\([^)]*\))?", line))


def _parse_model_fields(inner: str, raw: str, block_start: int) -> Tuple[TypeSpecField, ...]:
    fields: List[TypeSpecField] = []
    for match in _FIELD_RE.finditer(inner):
        name = match.group("name")
        if name in {"version", "operations"}:
            continue
        type_expr = match.group("type").strip()
        optional = bool(match.group(2))
        line_start = block_start + match.start()
        decorators = _parse_decorators(match.group(0))
        fields.append(
            TypeSpecField(
                name=name,
                type_expr=type_expr,
                optional=optional,
                decorators=decorators,
                documentation=_leading_doc(raw, line_start),
            )
        )
    return tuple(fields)


def _parse_enum_values(inner: str) -> Tuple[str, ...]:
    values: List[str] = []
    for match in re.finditer(r"(\w+)\s*,?", inner):
        value = match.group(1)
        if value:
            values.append(value)
    return tuple(values)


def _parse_parameters(params_inner: str) -> Tuple[TypeSpecParameter, ...]:
    if not params_inner.strip():
        return ()
    parameters: List[TypeSpecParameter] = []
    for chunk in params_inner.split(","):
        decl = chunk.strip()
        if not decl:
            continue
        location = "query"
        if decl.startswith("@path "):
            location = "path"
            decl = decl[6:].strip()
        elif decl.startswith("@query "):
            location = "query"
            decl = decl[7:].strip()
        elif decl.startswith("@header "):
            location = "header"
            decl = decl[8:].strip()
        elif decl.startswith("@body "):
            location = "body"
            decl = decl[6:].strip()
        name_type = decl.split(":", 1)
        if len(name_type) != 2:
            continue
        parameters.append(
            TypeSpecParameter(
                name=name_type[0].strip(),
                type_expr=name_type[1].strip(),
                location=location,
            )
        )
    return tuple(parameters)


def _parse_operations(inner: str, raw: str, block_start: int) -> Tuple[TypeSpecOperation, ...]:
    operations: List[TypeSpecOperation] = []
    for match in _OPERATION_RE.finditer(inner):
        return_type = match.group(4).strip()
        is_array = return_type.endswith("[]")
        if is_array:
            return_type = return_type[:-2].strip()
        line_start = block_start + match.start()
        operations.append(
            TypeSpecOperation(
                name=match.group(2),
                verb=match.group(1).lower(),
                parameters=_parse_parameters(match.group(3)),
                return_type=return_type,
                is_array_return=is_array,
                documentation=_leading_doc(raw, line_start),
            )
        )
    return tuple(operations)


def parse_typespec(content: str, *, source_label: Optional[str] = None) -> TypeSpecDocument:
    """Parse TypeSpec source into a :class:`TypeSpecDocument`."""
    if not content or not content.strip():
        raise TypeSpecParseError("Invalid or empty TypeSpec content")
    if not is_typespec(content):
        raise TypeSpecParseError("Content does not appear to be a TypeSpec definition")

    cleaned = _strip_comments(content)
    namespace_match = _NAMESPACE_RE.search(cleaned)
    namespace = namespace_match.group(1) if namespace_match else None
    service_match = _SERVICE_RE.search(cleaned)
    service_title = service_match.group(1) if service_match else None

    imports = tuple(
        match.group(0).strip().rstrip(";")
        for match in re.finditer(r"""import\s+['"][^'"]+['"]\s*;""", cleaned)
    )
    usings = tuple(
        match.group(1).strip()
        for match in re.finditer(r"^\s*using\s+([\w.]+)\s*;", cleaned, re.MULTILINE)
    )

    enums: List[TypeSpecEnum] = []
    for match in re.finditer(r"\benum\s+(\w+)\s*\{", cleaned):
        name = match.group(1)
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        values = _parse_enum_values(inner)
        if values:
            enums.append(
                TypeSpecEnum(
                    name=name,
                    values=values,
                    documentation=_leading_doc(content, match.start()),
                )
            )

    models: List[TypeSpecModel] = []
    for match in re.finditer(r"\bmodel\s+(\w+)\s*\{", cleaned):
        name = match.group(1)
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        fields = _parse_model_fields(inner, content, open_brace + 1)
        models.append(
            TypeSpecModel(
                name=name,
                fields=fields,
                documentation=_leading_doc(content, match.start()),
            )
        )

    interfaces: List[TypeSpecInterface] = []
    for match in re.finditer(r"\binterface\s+(\w+)\s*\{", cleaned):
        name = match.group(1)
        prefix = cleaned[: match.start()]
        route_match = _ROUTE_RE.search(prefix[-200:])
        route_prefix = route_match.group(1) if route_match else None
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        operations = _parse_operations(inner, content, open_brace + 1)
        interfaces.append(
            TypeSpecInterface(
                name=name,
                route_prefix=route_prefix,
                operations=operations,
                documentation=_leading_doc(content, match.start()),
            )
        )

    if not enums and not models and not interfaces:
        label = f" ({source_label})" if source_label else ""
        raise TypeSpecParseError(
            f"No enum, model, or interface definitions found in the TypeSpec file{label}"
        )

    return TypeSpecDocument(
        namespace=namespace,
        service_title=service_title,
        imports=imports,
        usings=usings,
        enums=tuple(enums),
        models=tuple(models),
        interfaces=tuple(interfaces),
        raw=content,
    )
