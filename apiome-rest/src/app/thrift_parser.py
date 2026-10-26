"""Apache Thrift IDL parser — MFI-11.1.

Parses ``.thrift`` source text into a typed :class:`ThriftDocument` AST. The parser is
deliberately lightweight (regex + brace matching, mirroring the UI's
``thrift-converter.ts``) so catalog imports do not depend on an external Thrift compiler.
Syntax errors surface as :class:`ThriftParseError` with a human-readable message.

A multi-file set (a root that ``include``s other files) is parsed by
:func:`app.thrift_fileset.parse_thrift_set`, which fills :attr:`ThriftDocument.included`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .document_markers import looks_like_structured_document

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
    #: The service this one ``extends``, as written (``Base`` or ``shared.Base``), MFI-19.3.
    extends: Optional[str] = None


@dataclass(frozen=True)
class ThriftDocument:
    namespaces: Dict[str, str]
    includes: Tuple[str, ...]
    typedefs: Dict[str, str]
    enums: Tuple[ThriftEnum, ...]
    structs: Tuple[ThriftStruct, ...]
    services: Tuple[ThriftService, ...]
    raw: str
    #: The document's path inside its file set (``None`` for a single pasted document).
    path: Optional[str] = None
    #: The documents this one includes, keyed by the prefix its types are referenced with
    #: (``include "common/shared.thrift"`` → ``shared``). Filled by
    #: :func:`app.thrift_fileset.parse_thrift_set`; empty for a single document.
    included: Dict[str, "ThriftDocument"] = field(default_factory=dict)


def is_thrift(content: str) -> bool:
    """Return ``True`` when ``content`` looks like Thrift IDL."""
    if not content or not isinstance(content, str):
        return False
    trimmed = content.strip()
    if not trimmed:
        return False
    # A JSON or YAML document is never Thrift, whatever words its descriptions use.
    if looks_like_structured_document(trimmed):
        return False
    if re.search(r"""^\s*\$version\s*:\s*['"]""", trimmed, re.MULTILINE):
        return False
    if re.search(r'^[ \t]*include\s+"', trimmed, re.MULTILINE):
        return True
    # `namespace <scope> <identifier>` is the whole line in Thrift (bar a trailing `;` or
    # comment); prose that merely starts with "namespace" — "namespace to its primitives" —
    # carries more words.
    if re.search(
        r"^[ \t]*namespace[ \t]+(?:\*|[A-Za-z_][\w.]*)[ \t]+[A-Za-z_][\w.]*[ \t]*;?[ \t]*(?://.*|#.*)?$",
        trimmed,
        re.MULTILINE,
    ):
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


#: A quoted string (kept) or a comment (blanked), matched left to right so a ``//`` or ``#``
#: inside a string — ``include "http://..."``, a default ``"#fff"`` — is not a comment.
_STRING_OR_COMMENT_RE = re.compile(
    r'("(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\')|/\*[\s\S]*?\*/|//[^\n]*|#[^\n]*'
)


def _strip_comments(text: str) -> str:
    return _STRING_OR_COMMENT_RE.sub(lambda m: m.group(1) or " ", text)


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
    # The trailing `,` / `;` is optional in Thrift; a typedef may also end its line.
    for match in re.finditer(r"\btypedef\s+([\w.<>, \t]+?)\s+(\w+)\s*(?:[,;]|$)", cleaned, re.MULTILINE):
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
        # The separator after the last field / parameter is optional.
        name_match = re.match(r"(\w+)\s*(=\s*[^,;\n]*)?\s*(?:[,;\n]|$)", inner[i:])
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


#: One service method: ``[oneway] <return type> name(<params>) [throws (<fields>)]``. The
#: return type is an identifier, optionally with generic arguments (``map<string, i32>``).
_METHOD_RE = re.compile(
    r"(?:\b(oneway)\s+)?"
    r"([A-Za-z_][\w.]*(?:\s*<[\w.<>,\s]*>)?)\s+"
    r"(\w+)\s*\(([^)]*)\)"
    r"(?:\s*throws\s*\(([^)]*)\))?"
)


def _parse_service_methods(inner: str, typedefs: Dict[str, str]) -> Tuple[ThriftServiceMethod, ...]:
    """Parse a service body's methods.

    Matches each signature as a whole, so a method whose parameters are separated by commas,
    that spans several lines, or that has no trailing separator is read intact (MFI-19.3).
    """
    methods: List[ThriftServiceMethod] = []
    for match in _METHOD_RE.finditer(inner):
        oneway, return_type, method_name, params_inner, throws_inner = match.groups()
        throws: List[Tuple[int, str, str]] = []
        for tm in re.finditer(r"(\d+)\s*:\s*([\w.]+)\s+(\w+)", throws_inner or ""):
            throws.append((int(tm.group(1)), tm.group(2), tm.group(3)))
        methods.append(
            ThriftServiceMethod(
                name=method_name,
                return_type=_resolve_typedef(re.sub(r"\s+", " ", return_type), typedefs),
                parameters=_parse_struct_fields(params_inner, typedefs),
                throws=tuple(throws),
                oneway=bool(oneway),
            )
        )
    return tuple(methods)


def parse_thrift(
    content: str,
    *,
    source_label: Optional[str] = None,
    require_definitions: bool = True,
) -> ThriftDocument:
    """Parse Thrift IDL text into a :class:`ThriftDocument`.

    Args:
        content: The ``.thrift`` text.
        source_label: Label used in error messages.
        require_definitions: When ``False`` (an included file, MFI-19.3), a file that holds
            only typedefs, constants or namespaces is accepted.

    Raises:
        ThriftParseError: When the content is empty, not Thrift, or has no definitions.
    """
    if not content or not content.strip():
        raise ThriftParseError("Invalid or empty Thrift content")
    if require_definitions and not is_thrift(content):
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
    for match in re.finditer(r"\bservice\s+(\w+)(?:\s+extends\s+([\w.]+))?\s*\{", cleaned):
        name, extends = match.group(1), match.group(2)
        open_brace = cleaned.find("{", match.start())
        close = _find_matching_brace(cleaned, open_brace + 1)
        if close == -1:
            continue
        inner = cleaned[open_brace + 1 : close]
        methods = _parse_service_methods(inner, typedefs)
        services.append(ThriftService(name=name, methods=methods, extends=extends))

    if require_definitions and not enums and not structs and not services:
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
