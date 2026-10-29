"""Microsoft TypeSpec parser — MFI-22.3.

Parses TypeSpec ``.tsp`` source text into a typed :class:`TypeSpecDocument` AST using lightweight
regex and brace matching (no external ``tsp`` compiler dependency). Syntax errors surface as
:class:`TypeSpecParseError`.
"""

from __future__ import annotations

import json
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
#: ``@service(#{ title: "…" })`` (TypeSpec 0.66+) or ``@service({ title: "…" })`` (the bundled 0.65).
_SERVICE_RE = re.compile(r'@service\(\s*#?\{\s*title:\s*"((?:[^"\\]|\\.)*)"', re.MULTILINE)
_VERBS = frozenset({"get", "post", "put", "patch", "delete", "head"})
_LOCATIONS = frozenset({"path", "query", "header", "cookie", "body"})
#: One decorator: ``@name`` with optional arguments (string literals may hold parentheses).
_DECORATOR_RE = re.compile(r'@(\w+)(?:\((?P<args>(?:"(?:[^"\\]|\\.)*"|[^()"]|\([^()]*\))*)\))?\s*')
#: One directive: ``#deprecated "reason"``.
_DIRECTIVE_RE = re.compile(r'#\w+(?:\s+"(?:[^"\\]|\\.)*")?\s*')
_STRING_ARG_RE = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"')
_NAME_RE = re.compile(r"^(`[^`]+`|[A-Za-z_$][\w$]*)(\?)?\s*:\s*", re.DOTALL)


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
    optional: bool = False


@dataclass(frozen=True)
class TypeSpecOperation:
    name: str
    verb: str
    parameters: Tuple[TypeSpecParameter, ...]
    return_type: str
    is_array_return: bool
    documentation: Optional[str] = None
    route: Optional[str] = None
    tags: Tuple[str, ...] = ()


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
    """Blank out ``//`` and ``/* */`` comments, keeping every offset (and newline) where it was.

    String literals are skipped, so a ``//`` inside ``"https://…"`` is not a comment.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif text.startswith("/*", i):
            close = text.find("*/", i + 2)
            close = n if close == -1 else close + 2
            for j in range(i, close):
                if out[j] != "\n":
                    out[j] = " "
            i = close
        else:
            i += 1
    return "".join(out)


def _find_matching_brace(s: str, start: int) -> int:
    depth = 1
    i = start
    while i < len(s) and depth > 0:
        if s[i] == '"':
            i += 1
            while i < len(s) and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
        elif s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
        i += 1
    return i - 1 if depth == 0 else -1


def _split_top(text: str, separator: str) -> List[Tuple[int, str]]:
    """Split ``text`` at ``separator`` outside strings and brackets; each part with its offset."""
    parts: List[Tuple[int, str]] = []
    depth, start, i = 0, 0, 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            i += 1
            while i < len(text) and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
        elif ch in "({[<":
            depth += 1
        elif ch in ")}]>":
            depth -= 1
        elif ch == separator and depth == 0:
            parts.append((start, text[start:i]))
            start = i + 1
        i += 1
    parts.append((start, text[start:]))
    return parts


def _leading_doc(raw: str, start: int) -> Optional[str]:
    """The doc comment just before ``start``: a ``/** … */`` block or ``///`` lines.

    Decorator and directive lines between the comment and the declaration (``@route("/x")``,
    ``#deprecated "…"``) are skipped.
    """
    lines = raw[:start].splitlines()
    if lines and lines[-1].strip() == "":
        lines.pop()
    elif lines and raw[:start] and not raw[:start].endswith("\n"):
        # The declaration starts mid-line: decorators before it on its own line are skipped.
        lines.pop()
    while lines and (lines[-1].strip().startswith(("@", "#")) or not lines[-1].strip()):
        lines.pop()
    if lines and lines[-1].strip().endswith("*/"):
        block: List[str] = []
        while lines:
            line = lines.pop().strip()
            block.append(line)
            if line.startswith("/**"):
                break
        else:
            return None
        text = "\n".join(reversed(block))
        text = text[3:-2] if text.startswith("/**") and text.endswith("*/") else text
        cleaned = [re.sub(r"^\s*\*\s?", "", line).rstrip() for line in text.strip().splitlines()]
        return "\n".join(cleaned).strip().replace("*\\/", "*/") or None
    docs: List[str] = []
    for line in reversed(lines[-5:]):
        stripped = line.strip()
        if stripped.startswith("///"):
            docs.append(stripped[3:].strip())
            continue
        break
    if not docs:
        return None
    return " ".join(reversed(docs)).strip() or None


def _decorators(statement: str) -> Tuple[List[Tuple[str, Optional[str], str]], str]:
    """Peel the leading decorators and directives off a statement.

    Returns:
        ``([(name, first string argument, text)], rest of the statement)``.
    """
    found: List[Tuple[str, Optional[str], str]] = []
    rest = statement.lstrip()
    while rest[:1] in ("@", "#"):
        if rest.startswith("#"):
            match = _DIRECTIVE_RE.match(rest)
            if match is None:
                break
            rest = rest[match.end():]
            continue
        match = _DECORATOR_RE.match(rest)
        if match is None:
            break
        args = match.group("args")
        arg = _STRING_ARG_RE.match(args) if args else None
        found.append((match.group(1), arg.group(1) if arg else None, match.group(0).strip()))
        rest = rest[match.end():]
    return found, rest


def _unquote(name: str) -> str:
    return name[1:-1] if name.startswith("`") and name.endswith("`") else name


def _without_default(type_expr: str) -> str:
    """A property's type without its ``= default`` (an ``=`` outside strings and brackets)."""
    return _split_top(type_expr, "=")[0][1].strip()


def _parse_model_fields(inner: str, raw: str, block_start: int) -> Tuple[TypeSpecField, ...]:
    fields: List[TypeSpecField] = []
    for offset, statement in _split_top(inner, ";"):
        decorators, rest = _decorators(statement)
        match = _NAME_RE.match(rest)
        if match is None:
            continue
        type_expr = _without_default(rest[match.end():])
        if not type_expr:
            continue
        lead = len(statement) - len(statement.lstrip())
        fields.append(
            TypeSpecField(
                name=_unquote(match.group(1)),
                type_expr=type_expr,
                optional=bool(match.group(2)),
                decorators=tuple(text for _, _, text in decorators),
                documentation=_leading_doc(raw, block_start + offset + lead),
            )
        )
    return tuple(fields)


def _parse_enum_values(inner: str) -> Tuple[str, ...]:
    values: List[str] = []
    for _, member in _split_top(inner, ","):
        _, rest = _decorators(member)
        name = _split_top(rest, ":")[0][1].strip()
        if name:
            values.append(_unquote(name))
    return tuple(values)


def _parse_parameters(params_inner: str) -> Tuple[TypeSpecParameter, ...]:
    parameters: List[TypeSpecParameter] = []
    for _, chunk in _split_top(params_inner, ","):
        decorators, rest = _decorators(chunk)
        match = _NAME_RE.match(rest.strip())
        if match is None:
            continue
        location, explicit = "query", None
        for name, arg, _ in decorators:
            if name in _LOCATIONS:
                location, explicit = name, arg
                break
        parameters.append(
            TypeSpecParameter(
                name=explicit or _unquote(match.group(1)),
                type_expr=_without_default(rest.strip()[match.end():]),
                location=location,
                optional=bool(match.group(2)),
            )
        )
    return tuple(parameters)


def _parse_operations(inner: str, raw: str, block_start: int) -> Tuple[TypeSpecOperation, ...]:
    operations: List[TypeSpecOperation] = []
    for offset, statement in _split_top(inner, ";"):
        decorators, rest = _decorators(statement)
        verb = next((name for name, _, _ in decorators if name in _VERBS), None)
        route = next((arg for name, arg, _ in decorators if name == "route"), None)
        head = re.match(r"\s*(`[^`]+`|\w+)\s*\(", rest)
        if verb is None or head is None:
            continue
        close = head.end()
        depth = 1
        while close < len(rest) and depth:
            if rest[close] == '"':
                close = rest.find('"', close + 1)
            elif rest[close] == "(":
                depth += 1
            elif rest[close] == ")":
                depth -= 1
            close += 1
        after = rest[close:].strip()
        if depth or not after.startswith(":"):
            continue
        return_type = after[1:].strip()
        is_array = return_type.endswith("[]")
        if is_array:
            return_type = return_type[:-2].strip()
        lead = len(statement) - len(statement.lstrip())
        operations.append(
            TypeSpecOperation(
                name=_unquote(head.group(1)),
                verb=verb,
                parameters=_parse_parameters(rest[head.end():close - 1]),
                return_type=return_type,
                is_array_return=is_array,
                documentation=_leading_doc(raw, block_start + offset + lead),
                route=route,
                tags=tuple(arg for name, arg, _ in decorators if name == "tag" and arg),
            )
        )
    return tuple(operations)


def _route_prefix(cleaned: str, start: int) -> Optional[str]:
    """The ``@route`` among the decorators just before the declaration at ``start``."""
    boundary = max(cleaned.rfind(";", 0, start), cleaned.rfind("}", 0, start))
    decorators, _ = _decorators(cleaned[boundary + 1:start])
    return next((arg for name, arg, _ in decorators if name == "route"), None)


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
    service_title = json.loads(f'"{service_match.group(1)}"') if service_match else None

    imports = tuple(
        match.group(0).strip().rstrip(";")
        for match in re.finditer(r"""import\s+['"][^'"]+['"]\s*;""", cleaned)
    )
    usings = tuple(
        match.group(1).strip()
        for match in re.finditer(r"^\s*using\s+([\w.]+)\s*;", cleaned, re.MULTILINE)
    )

    enums: List[TypeSpecEnum] = []
    for match in re.finditer(r"\benum\s+(`[^`]+`|\w+)\s*\{", cleaned):
        name = _unquote(match.group(1))
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
    for match in re.finditer(r"\bmodel\s+(`[^`]+`|\w+)\s*\{", cleaned):
        name = _unquote(match.group(1))
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
    for match in re.finditer(r"\binterface\s+(`[^`]+`|\w+)\s*\{", cleaned):
        name = _unquote(match.group(1))
        route_prefix = _route_prefix(cleaned, match.start())
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
