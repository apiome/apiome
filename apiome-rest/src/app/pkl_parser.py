"""Pkl reader — the Pkl third of FMT-8.5 (#5466).

A Pkl schema is a module of classes and type aliases whose members carry types and
*constraints* (``Int(isBetween(1, 9999))``, ``String(matches(Regex("…")))``). This reader asks
Pkl itself. In the sandboxed toolchain runner the bundled ``pkl eval`` evaluates a small
reflection program (:data:`REFLECTION_PROGRAM`) written next to the upload, which imports every
module of the upload and renders, as JSON, what ``pkl:reflect`` knows about it:

* each class — superclass, doc comment, modifiers, and every property's resolved type (Pkl
  resolves aliases, imports and inheritance), doc comment and evaluated default;
* each type alias and its resolved type;
* each module-level property, and the result of evaluating it — a value that fails its own
  type's constraint (a default of ``80`` on ``Int(isBetween(1024, 65535))``) rejects the import.

Evaluation is network-free, time-bounded and locked down: modules may only come from the upload
and Pkl's standard library (``--root-dir``, ``--allowed-modules``), and resources from nowhere —
``read("env:…")`` is refused and recorded as a declared limit.

``pkl:reflect`` resolves types but does not expose constraints, so the reader parses each
property's type annotation from the source line Pkl located it at (:func:`parse_type`) and lays
the constraints it recognizes onto the resolved type as JSON Schema keywords. A constraint with
no JSON Schema keyword is declared, never guessed. The projection is a JSON Schema document the
shared translator reads (:mod:`app.typed_config_normalizer`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .typed_config_common import (
    MODEL_PARTIAL_SUFFIXES,
    ToolFailure,
    TypedConfigDocument,
    TypedConfigParseError,
    first_lines,
    guard_input,
    model_limit_details,
    pascal_case,
    run_typed_config_tool,
    syntax_error_code,
    workspace,
)

__all__ = [
    "LIMIT_DETAILS",
    "PARTIAL_LIMITS",
    "PKL_FORMAT",
    "PKL_SUFFIXES",
    "PKL_TOOL_KEY",
    "REFLECTION_PROGRAM",
    "is_pkl_source",
    "parse_pkl",
    "parse_pkl_fileset",
    "parse_type",
]

#: The format key the reader, normalizer and adapter share.
PKL_FORMAT = "pkl"

#: Registry key of the bundled ``pkl`` CLI (declared in :mod:`app.toolchain_packaging`).
PKL_TOOL_KEY = "pkl"

#: The file suffixes a Pkl upload uses.
PKL_SUFFIXES: Tuple[str, ...] = (".pkl",)

#: The display name used in messages.
_LABEL = "Pkl"

#: The file the reflection program is written to, beside the upload.
_PROGRAM_FILE = ".apiome-reflect.pkl"

#: Every construct the reader declares rather than models, with the sentence that says what
#: happens to it.
LIMIT_DETAILS: Dict[str, str] = {
    "pkl.type_constraint": (
        "A type constraint is a Pkl boolean expression. Bounds, lengths, emptiness, patterns, "
        "prefixes and suffixes become JSON Schema keywords; any other predicate has no keyword. "
        "The member's type is modelled; that predicate is not."
    ),
    "pkl.late_binding": (
        "A constraint written in terms of another member (`Int(this > minimum)`) is checked "
        "against the object it belongs to, at evaluation. The member's type is modelled; the "
        "relation is not."
    ),
    "pkl.computed_default": (
        "A default that can only be computed from other members, or from the module, has no "
        "single value to record. The member is modelled without a default."
    ),
    "pkl.generator": (
        "A `for` or `when` generator builds a member's value during evaluation. The member's type "
        "is modelled; how its value is generated is not."
    ),
    "pkl.external_read": (
        "`read(…)` reads an environment variable, a file or a URL at evaluation time, and the "
        "evaluation sandbox refuses every resource. The member is modelled without the value it "
        "would have read."
    ),
    "pkl.output": (
        "A module's `output` block decides how the module renders, not what its data is. It is "
        "not modelled."
    ),
    "pkl.method": (
        "A method (`function`) describes behaviour, not data. It is not modelled."
    ),
    "pkl.unit_type": (
        "A `Duration` or `DataSize` is a number with a unit. It is modelled as text (`5.min`, "
        "`512.mb`), so its unit and magnitude are not checked."
    ),
    "pkl.non_string_key": (
        "A `Mapping` or `Map` whose keys are not strings has no JSON object form. The map is "
        "modelled with string keys."
    ),
}
LIMIT_DETAILS.update(model_limit_details(PKL_FORMAT, _LABEL))

#: The limits whose construct is still modelled, with only a detail lost.
PARTIAL_LIMITS = frozenset(
    {
        *(f"{PKL_FORMAT}.{suffix}" for suffix in MODEL_PARTIAL_SUFFIXES),
        "pkl.type_constraint",
        "pkl.late_binding",
        "pkl.computed_default",
        "pkl.generator",
        "pkl.external_read",
        "pkl.unit_type",
        "pkl.non_string_key",
    }
)

#: The reflection program, with ``{imports}`` / ``{modules}`` filled in per upload. It renders
#: one JSON object per imported module (see the module docstring for what it holds).
REFLECTION_PROGRAM = """\
import "pkl:reflect"
import "pkl:test"
{imports}

local renderer_ = new JsonRenderer {{}}

local function ownerOf(declaration: reflect.TypeDeclaration): String =
  declaration.enclosingDeclaration.name

local function typeOf(t: reflect.Type): Dynamic =
  if (t is reflect.DeclaredType) new Dynamic {{
    kind = "declared"
    name = t.referent.name
    owner = ownerOf(t.referent)
    alias = t.referent is reflect.TypeAlias
    arguments = t.typeArguments.map((a) -> typeOf(a))
  }}
  else if (t is reflect.UnionType) new Dynamic {{ kind = "union"; members = t.members.map((a) -> typeOf(a)) }}
  else if (t is reflect.NullableType) new Dynamic {{ kind = "nullable"; member = typeOf(t.member) }}
  else if (t is reflect.StringLiteralType) new Dynamic {{ kind = "string-literal"; value = t.value }}
  else if (t is reflect.FunctionType) new Dynamic {{ kind = "function" }}
  else if (t is reflect.ModuleType) new Dynamic {{ kind = "module" }}
  else if (t is reflect.NothingType) new Dynamic {{ kind = "nothing" }}
  else if (t is reflect.TypeVariable) new Dynamic {{ kind = "type-variable"; name = t.referent.name }}
  else new Dynamic {{ kind = "unknown" }}

local function evaluated(thunk: () -> Any): Dynamic =
  let (failure = test.catchOrNull(() -> renderer_.renderValue(thunk.apply())))
    if (failure != null) new Dynamic {{ error = failure }}
    else new Dynamic {{ rendered = renderer_.renderValue(thunk.apply()) }}

local function property(p: reflect.Property): Dynamic = new Dynamic {{
  line = p.location.line
  doc = p.docComment
  modifiers = p.modifiers.toList().map((x) -> x.toString())
  declared = typeOf(p.type)
  initial = evaluated(() -> p.defaultValue)
}}

local function describe(file: String, r: reflect.Module, instance: Module): Dynamic = new Dynamic {{
  path = file
  name = r.name
  doc = r.docComment
  classes = r.classes.mapValues((_, c) -> new Dynamic {{
    line = c.location.line
    doc = c.docComment
    modifiers = c.modifiers.toList().map((x) -> x.toString())
    superclass =
      if (c.superclass != null && ownerOf(c.superclass!!) != "pkl.base")
        new Dynamic {{ name = c.superclass!!.name; owner = ownerOf(c.superclass!!) }}
      else null
    properties = c.properties.mapValues((_, p) -> property(p)).toMap()
    methods = c.methods.keys.toList()
  }}).toMap()
  typeAliases = r.typeAliases.mapValues((_, a) -> new Dynamic {{
    line = a.location.line
    doc = a.docComment
    declared = typeOf(a.referent)
  }}).toMap()
  properties = r.moduleClass.properties.mapValues((_, p) -> property(p)).toMap()
  values = r.moduleClass.properties.keys.toList().map((k) -> new Dynamic {{
    name = k
    result = evaluated(() -> instance.getProperty(k))
  }})
  methods = r.moduleClass.methods.keys.toList()
}}

output {{
  value = new Dynamic {{ modules = List({modules}) }}
  renderer = new JsonRenderer {{}}
}}
"""

_MODULE_RE = re.compile(r"^\s*module\s+[A-Za-z_][\w.]*\s*$", re.MULTILINE)
#: A ``class`` declaration in Pkl's brace form (``class Order {``, ``open class B extends A {``)
#: — not Python's ``class Order(BaseModel):`` — or a ``typealias``.
_DECLARATION_RE = re.compile(
    r"^\s*(?:(?:open|abstract|external|local)\s+)*"
    r"(?:class\s+[A-Z]\w*(?:<[^>\n]*>)?(?:\s+extends\s+[\w.]+(?:<[^>\n]*>)?)?\s*\{|typealias\s+[A-Z]\w*\b[^\n]*=)",
    re.MULTILINE,
)
_CUE_MARKERS_RE = re.compile(r"^\s*package\s+\w+\s*$|^#\w+\s*:", re.MULTILINE)
_OUTPUT_BLOCK_RE = re.compile(r"^output\s*\{", re.MULTILINE)
_ERROR_LOCATION_RE = re.compile(r"\((?:file://)?(?P<path>[^,()]+\.pkl), line (?P<line>\d+)\)")
_UNDEFINED_RE = re.compile(r"is undefined|Tried to read property .* but its value is undefined", re.S)
_REFUSED_RE = re.compile(r"Refusing to read resource")
_UNRESOLVED_MODULE_RE = re.compile(
    r"Cannot find module|I/O error loading module|Module `.*` does not exist|Refusing to load module"
)

#: Pkl standard-library integer aliases → JSON Schema bounds.
_INT_ALIASES: Dict[str, Tuple[Optional[int], Optional[int]]] = {
    "Int8": (-(2**7), 2**7 - 1),
    "Int16": (-(2**15), 2**15 - 1),
    "Int32": (-(2**31), 2**31 - 1),
    "UInt8": (0, 2**8 - 1),
    "UInt16": (0, 2**16 - 1),
    "UInt32": (0, 2**32 - 1),
    "UInt": (0, None),
}
_LIST_TYPES = frozenset({"Listing", "List", "Collection"})
_MAP_TYPES = frozenset({"Mapping", "Map"})
_STRING_TYPES = frozenset({"String", "Char"})
_NUMBER_TYPES = frozenset({"Int", "Float", "Number", *_INT_ALIASES})


# ===========================================================================
# Detection
# ===========================================================================


def is_pkl_source(text: str) -> bool:
    """Whether ``text`` reads as a Pkl module.

    The evidence is a ``module`` clause or a ``class`` / ``typealias`` declaration, and nothing
    that marks the text as CUE (its ``package`` clause or ``#Definition:``).

    Args:
        text: The candidate source.

    Returns:
        ``True`` when the text is claimable by this reader.
    """
    if _CUE_MARKERS_RE.search(text):
        return False
    return bool(_MODULE_RE.search(text) or _DECLARATION_RE.search(text))


def _mismatch(files: Mapping[str, str], root: str, where: str) -> Optional[str]:
    """A message when the root is not Pkl at all (``FORMAT_MISMATCH``), else ``None``."""
    text = files[root]
    suffix = PurePosixPath(root).suffix.lower()
    if suffix and suffix not in PKL_SUFFIXES and not is_pkl_source(text):
        return (
            f"{PurePosixPath(root).name} is a `{suffix}` file, not Pkl{where}. Pkl import reads "
            "`.pkl` modules of classes and type aliases."
        )
    if _CUE_MARKERS_RE.search(text) and not is_pkl_source(text):
        return f"{root} is CUE, not Pkl{where} (it has a `package` clause or `#Definitions`)."
    return None


# ===========================================================================
# Type annotations (the constraints pkl:reflect does not expose)
# ===========================================================================


@dataclass
class TypeNode:
    """One node of a parsed Pkl type annotation.

    Attributes:
        kind: ``declared``, ``union``, ``nullable``, ``string-literal`` or ``other``.
        name: The declared type's simple name (``Listing``), or the literal's value.
        arguments: Type arguments (``declared``), members (``union``) or the inner type
            (``nullable``, one element).
        constraints: The constraint expressions written on this node (``isBetween(1, 9)``).
    """

    kind: str
    name: str = ""
    arguments: List["TypeNode"] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)

    def has_constraints(self) -> bool:
        """Whether this node or any node below it carries a constraint."""
        return bool(self.constraints) or any(arg.has_constraints() for arg in self.arguments)


class _TypeParser:
    """A small recursive-descent parser for Pkl type annotations."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def _skip(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def _peek(self) -> str:
        self._skip()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def _balanced(self, opener: str, closer: str) -> str:
        """Consume a bracketed span (``opener`` at the cursor) and return its inside."""
        depth = 0
        start = self.pos + 1
        in_string = False
        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "\\" and in_string:
                self.pos += 2
                continue
            if char == '"':
                in_string = not in_string
            elif not in_string and char == opener:
                depth += 1
            elif not in_string and char == closer:
                depth -= 1
                if depth == 0:
                    self.pos += 1
                    return self.text[start : self.pos - 1]
            self.pos += 1
        raise ValueError("unbalanced type annotation")

    def parse_union(self) -> TypeNode:
        members = [self._member()]
        while self._peek() == "|":
            self.pos += 1
            members.append(self._member())
        return members[0] if len(members) == 1 else TypeNode(kind="union", arguments=members)

    def _member(self) -> TypeNode:
        if self._peek() == "*":
            self.pos += 1
        node = self._primary()
        while True:
            char = self._peek()
            if char == "?":
                self.pos += 1
                node = TypeNode(kind="nullable", arguments=[node])
            elif char == "(":
                node.constraints.extend(_split_top_level(self._balanced("(", ")")))
            else:
                return node

    def _primary(self) -> TypeNode:
        char = self._peek()
        if char == '"':
            match = re.compile(r'"((?:\\.|[^"\\])*)"').match(self.text, self.pos)
            if not match:
                raise ValueError("unterminated string literal")
            self.pos = match.end()
            return TypeNode(kind="string-literal", name=match.group(1))
        if char == "(":
            inner = _TypeParser(self._balanced("(", ")")).parse_union()
            if self._peek() == "-":  # a function type `(A) -> B`
                self.pos = len(self.text)
                return TypeNode(kind="other")
            return inner
        match = re.compile(r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*").match(self.text, self.pos)
        if not match:
            raise ValueError(f"unexpected {char!r}")
        self.pos = match.end()
        node = TypeNode(kind="declared", name=match.group(0).rsplit(".", 1)[-1])
        if self.pos < len(self.text) and self.text[self.pos] == "<":
            node.arguments = [
                _TypeParser(part).parse_union() for part in _split_top_level(self._balanced("<", ">"))
            ]
        return node


def _split_top_level(text: str) -> List[str]:
    """Split on commas that are not inside brackets or string literals."""
    parts: List[str] = []
    depth = 0
    in_string = False
    current = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and in_string:
            current += text[index : index + 2]
            index += 2
            continue
        if char == '"':
            in_string = not in_string
        elif not in_string and char in "([<{":
            depth += 1
        elif not in_string and char in ")]>}" and not (char == ">" and index > 0 and text[index - 1] in "=-"):
            depth -= 1
        elif not in_string and char == "," and depth == 0:
            parts.append(current.strip())
            current = ""
            index += 1
            continue
        current += char
        index += 1
    if current.strip():
        parts.append(current.strip())
    return parts


def parse_type(text: str) -> Optional[TypeNode]:
    """Parse a Pkl type annotation, or return ``None`` when it is not one this reader reads.

    Args:
        text: The annotation (``Listing<String(startsWith("/"))>(!isEmpty)``).

    Returns:
        The parsed tree, or ``None``.
    """
    try:
        parser = _TypeParser(text)
        node = parser.parse_union()
        parser._skip()
        return node if parser.pos >= len(text) else None
    except (ValueError, IndexError):
        return None


def _member_annotation(lines: List[str], line_number: int, name: str) -> Tuple[Optional[str], Optional[str]]:
    """The type annotation and default text of the member declared at ``line_number``.

    Args:
        lines: The file's lines.
        line_number: The 1-based line Pkl located the member at.
        name: The member's name (a type alias is located by ``typealias <name> =``).

    Returns:
        ``(annotation, default)`` — each ``None`` when absent.
    """
    if not 0 < line_number <= len(lines):
        return None, None
    text = lines[line_number - 1]
    # A wrapped annotation continues until its brackets balance (a few lines at most).
    follow = line_number
    while _unbalanced(text) and follow < min(len(lines), line_number + 6):
        text += " " + lines[follow].strip()
        follow += 1
    alias = re.match(rf"\s*(?:[a-z]+\s+)*typealias\s+{re.escape(name)}\s*(?:<[^>]*>)?\s*=\s*(.*)$", text)
    if alias:
        return alias.group(1).strip(), None
    member = re.match(rf"\s*(?:[a-z]+\s+)*`?{re.escape(name)}`?\s*(:)?(.*)$", text)
    if not member:
        return None, None
    rest = member.group(2)
    annotation, default = rest, None
    split = _top_level_equals(rest)
    if split is not None:
        annotation, default = rest[:split], rest[split + 1 :].strip()
    annotation = annotation.strip() if member.group(1) else ""
    if annotation.endswith("{"):  # `name: Type {` amends the default in place
        annotation, default = annotation[:-1].strip(), default or "{"
    if not member.group(1) and default is None and rest.strip().startswith("{"):
        default = rest.strip()
    return annotation or None, default


def _unbalanced(text: str) -> bool:
    stripped = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
    return stripped.count("(") > stripped.count(")") or stripped.count("<") > stripped.count(">") + stripped.count("<=")


def _top_level_equals(text: str) -> Optional[int]:
    """Index of the ``=`` that starts a default (not ``==``, ``<=``, ``>=``, ``!=`` or ``->``)."""
    depth = 0
    in_string = False
    for index, char in enumerate(text):
        if char == '"':
            in_string = not in_string
        elif in_string:
            continue
        elif char in "([<{":
            depth += 1
        elif char in ")]>}" and not (char == ">" and index > 0 and text[index - 1] in "=-"):
            depth -= 1
        elif char == "=" and depth <= 0:
            before = text[index - 1] if index else ""
            after = text[index + 1] if index + 1 < len(text) else ""
            if not (before and before in "=<>!") and not (after and after in "=>"):
                return index
    return None


# ===========================================================================
# Constraints → JSON Schema keywords
# ===========================================================================

_NUMBER = r"-?\d[\d_]*(?:\.\d+)?(?:[eE][-+]?\d+)?"
_COMPARE_RE = re.compile(rf"^(length|this)\s*(<=|>=|<|>|==)\s*({_NUMBER})$")
_BETWEEN_RE = re.compile(rf"^(length\.)?isBetween\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)$")
_PATTERN_RE = re.compile(r'^matches\(\s*Regex\(\s*(#*)"(.*)"\1\s*\)\s*\)$', re.S)
_AFFIX_RE = re.compile(r'^(startsWith|endsWith)\(\s*"((?:\\.|[^"\\])*)"\s*\)$')


def _number(text: str) -> Any:
    value = float(text.replace("_", ""))
    return int(value) if value.is_integer() and "." not in text and "e" not in text.lower() else value


def _pkl_string(body: str, raw: bool) -> str:
    """Decode a Pkl string literal's body (``raw`` for a ``#"…"#`` custom-delimited one)."""
    if raw:
        return body
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t", "r": "\r"}.get(m.group(1), m.group(1)), body)


def _apply_constraint(
    expression: str, base: str, keywords: Dict[str, Any]
) -> Optional[str]:
    """Lay one constraint onto JSON Schema keywords.

    Args:
        expression: The constraint (``isBetween(1, 9999)``).
        base: The constrained type's family — ``string``, ``number`` or ``array``.
        keywords: The keywords so far, extended in place.

    Returns:
        ``None`` when the constraint became keywords, else the limit key that declares it.
    """
    expr = expression.strip()
    length = {"string": ("minLength", "maxLength"), "array": ("minItems", "maxItems")}.get(base)

    if expr == "!isEmpty" and length:
        keywords[length[0]] = max(keywords.get(length[0], 0), 1)
        return None
    if base == "array" and expr == "isDistinct":
        keywords["uniqueItems"] = True
        return None
    between = _BETWEEN_RE.match(expr)
    if between:
        low, high = _number(between.group(2)), _number(between.group(3))
        if between.group(1) and length:
            keywords[length[0]], keywords[length[1]] = low, high
            return None
        if not between.group(1) and base == "number":
            keywords["minimum"], keywords["maximum"] = low, high
            return None
    compare = _COMPARE_RE.match(expr)
    if compare:
        subject, operator, value = compare.group(1), compare.group(2), _number(compare.group(3))
        if subject == "length" and length and isinstance(value, int):
            bounds = {"<=": (None, value), "<": (None, value - 1), ">=": (value, None),
                      ">": (value + 1, None), "==": (value, value)}[operator]
        elif subject == "this" and base == "number":
            numeric = {"<=": ("maximum",), "<": ("exclusiveMaximum",), ">=": ("minimum",),
                       ">": ("exclusiveMinimum",), "==": ("minimum", "maximum")}[operator]
            for keyword in numeric:
                keywords[keyword] = value
            return None
        else:
            return "pkl.type_constraint"
        if bounds[0] is not None:
            keywords[length[0]] = bounds[0]
        if bounds[1] is not None:
            keywords[length[1]] = bounds[1]
        return None
    if base == "number":
        simple = {
            "isPositive": ("exclusiveMinimum", 0),
            "isNonNegative": ("minimum", 0),
            "isNegative": ("exclusiveMaximum", 0),
            "isNonPositive": ("maximum", 0),
            "isEven": ("multipleOf", 2),
        }.get(expr)
        if simple:
            keywords[simple[0]] = simple[1]
            return None
    if base == "string":
        pattern = _PATTERN_RE.match(expr)
        affix = _AFFIX_RE.match(expr)
        if pattern and "pattern" not in keywords:
            keywords["pattern"] = _pkl_string(pattern.group(2), raw=bool(pattern.group(1)))
            return None
        if affix and "pattern" not in keywords:
            text = re.escape(_pkl_string(affix.group(2), raw=False))
            keywords["pattern"] = f"^{text}" if affix.group(1) == "startsWith" else f"{text}$"
            return None
    if re.search(r"\bthis\b", expr):
        return "pkl.late_binding"
    return "pkl.type_constraint"


# ===========================================================================
# Projection (reflected modules → JSON Schema)
# ===========================================================================


@dataclass
class _Projection:
    """The state of one upload's projection to JSON Schema."""

    names: Dict[Tuple[str, str], str]
    definitions: Dict[str, Any] = field(default_factory=dict)
    limits: List[Tuple[str, str]] = field(default_factory=list)
    references: Dict[str, Set[str]] = field(default_factory=dict)

    def limit(self, construct: str, location: str) -> None:
        self.limits.append((construct, location))


def _base_family(name: str) -> Optional[str]:
    if name in _STRING_TYPES:
        return "string"
    if name in _NUMBER_TYPES:
        return "number"
    if name in _LIST_TYPES or name == "Set":
        return "array"
    return None


def _type_schema(
    reflected: Mapping[str, Any],
    parsed: Optional[TypeNode],
    projection: _Projection,
    *,
    owner: str,
    location: str,
) -> Optional[Dict[str, Any]]:
    """Project one reflected type (with its parsed annotation, when aligned) to JSON Schema.

    Returns:
        The schema, or ``None`` when the type has no data shape (the limit is recorded).
    """
    kind = reflected.get("kind")
    aligned = parsed if parsed is not None and parsed.kind == kind else None

    if kind == "nullable":
        inner_parsed = aligned.arguments[0] if aligned and aligned.arguments else None
        if inner_parsed is not None and aligned and aligned.constraints:
            inner_parsed.constraints.extend(aligned.constraints)
        inner = _type_schema(reflected.get("member") or {}, inner_parsed, projection, owner=owner, location=location)
        return None if inner is None else {"anyOf": [inner, {"type": "null"}]}

    if kind == "string-literal":
        return {"const": reflected.get("value")}

    if kind == "union":
        members = list(reflected.get("members") or [])
        parsed_members = aligned.arguments if aligned and len(aligned.arguments) == len(members) else []
        if all(member.get("kind") == "string-literal" for member in members):
            return {"enum": [member.get("value") for member in members]}
        schemas = []
        for index, member in enumerate(members):
            schema = _type_schema(
                member,
                parsed_members[index] if parsed_members else None,
                projection,
                owner=owner,
                location=location,
            )
            if schema is not None:
                schemas.append(schema)
        return {"anyOf": schemas} if schemas else None

    if kind != "declared":
        projection.limit(f"{PKL_FORMAT}.unrepresentable", location)
        return None

    name = str(reflected.get("name"))
    declared_owner = str(reflected.get("owner"))
    arguments = list(reflected.get("arguments") or [])
    if aligned is not None and aligned.name != name:
        # `Sku` in the source resolves to `String(…)` only through its alias; a user alias is a
        # reference, so the annotation's own constraints still align with this node.
        aligned = aligned if declared_owner != "pkl.base" else None
    parsed_arguments = aligned.arguments if aligned and len(aligned.arguments) == len(arguments) else []

    if declared_owner != "pkl.base":
        target = projection.names.get((declared_owner, name))
        if target is None:
            projection.limit(f"{PKL_FORMAT}.unmodelled_reference", location)
            return None
        projection.references.setdefault(owner, set()).add(target)
        schema: Dict[str, Any] = {"$ref": f"#/$defs/{target}"}
        if aligned and aligned.constraints:
            for expression in aligned.constraints:
                projection.limit("pkl.type_constraint", location)
        return schema

    family = _base_family(name)
    schema = _base_schema(name, arguments, parsed_arguments, projection, owner=owner, location=location)
    if schema is None:
        return None
    if aligned and aligned.constraints:
        for expression in aligned.constraints:
            construct = _apply_constraint(expression, family or "", schema) if family else "pkl.type_constraint"
            if construct is not None:
                projection.limit(construct, location)
    return schema


def _base_schema(
    name: str,
    arguments: List[Mapping[str, Any]],
    parsed_arguments: List[TypeNode],
    projection: _Projection,
    *,
    owner: str,
    location: str,
) -> Optional[Dict[str, Any]]:
    """A ``pkl.base`` type as JSON Schema."""

    def argument(index: int) -> Dict[str, Any]:
        if index >= len(arguments):
            return {}
        parsed = parsed_arguments[index] if index < len(parsed_arguments) else None
        return _type_schema(arguments[index], parsed, projection, owner=owner, location=location) or {}

    if name in _STRING_TYPES:
        return {"type": "string", **({"minLength": 1, "maxLength": 1} if name == "Char" else {})}
    if name == "Boolean":
        return {"type": "boolean"}
    if name in ("Float", "Number"):
        return {"type": "number"}
    if name == "Int":
        return {"type": "integer"}
    if name in _INT_ALIASES:
        low, high = _INT_ALIASES[name]
        schema: Dict[str, Any] = {"type": "integer"}
        if low is not None:
            schema["minimum"] = low
        if high is not None:
            schema["maximum"] = high
        return schema
    if name == "Null":
        return {"type": "null"}
    if name in ("Any", "Dynamic", "Typed", "Object"):
        return {}
    if name in ("Duration", "DataSize"):
        projection.limit("pkl.unit_type", location)
        return {"type": "string"}
    if name in _LIST_TYPES:
        return {"type": "array", "items": argument(0)}
    if name == "Set":
        return {"type": "array", "items": argument(0), "uniqueItems": True}
    if name in _MAP_TYPES:
        key = arguments[0] if arguments else {}
        if not (key.get("kind") == "declared" and key.get("name") in _STRING_TYPES):
            projection.limit("pkl.non_string_key", location)
        return {"type": "object", "additionalProperties": argument(1)}
    projection.limit(f"{PKL_FORMAT}.unrepresentable", location)
    return None


def _refers_to(expression: str, names: Set[str]) -> bool:
    """Whether a default expression reads another member (``inputs.length``, ``this``, ``module``).

    String literals are ignored, so ``"inputs"`` is not a reference.
    """
    bare = re.sub(r'"(?:\\.|[^"\\])*"', '""', expression)
    if re.search(r"\b(this|module|outer|super)\b", bare):
        return True
    return any(re.search(rf"(?<![\w.]){re.escape(name)}\b", bare) for name in names)


def _declared_default(initial: Mapping[str, Any]) -> Tuple[bool, Any, Optional[str]]:
    """``(has value, value, error)`` from a reflected property's evaluated default."""
    if "rendered" in initial:
        try:
            return True, json.loads(initial["rendered"]), None
        except ValueError:
            return False, None, None
    return False, None, str(initial.get("error") or "")


def _property_schema(
    name: str,
    prop: Mapping[str, Any],
    lines: List[str],
    projection: _Projection,
    *,
    owner: str,
    inherited: Optional[Mapping[str, Any]],
    siblings: Set[str],
) -> Tuple[Optional[Dict[str, Any]], bool]:
    """One property as JSON Schema, and whether it is required.

    Args:
        name: The property's name.
        prop: Its reflection record.
        lines: The source lines of the file it is declared in.
        projection: The projection state.
        owner: The declaring definition's name (for locations and references).
        inherited: The same property's record on a superclass, used when this one only
            overrides the default (``kind = "circle"`` has no type of its own).
        siblings: The names of the other members of the same object, to tell a default computed
            from them from a constant one.

    Returns:
        ``(schema, required)``; the schema is ``None`` when the member has no data shape.
    """
    location = f"{owner}.{name}"
    annotation, default_text = _member_annotation(lines, int(prop.get("line") or 0), name)
    reflected = prop.get("declared") or {}
    if reflected.get("kind") == "unknown" and inherited is not None:
        reflected = inherited.get("declared") or reflected
    parsed = parse_type(annotation) if annotation else None
    if annotation and parsed is None:
        projection.limit("pkl.type_constraint", location)
    schema = _type_schema(reflected, parsed, projection, owner=owner, location=location)
    if schema is None:
        return None, False

    doc = prop.get("doc")
    if isinstance(doc, str) and doc.strip():
        schema = {**schema, "description": doc.strip()}

    has_default = default_text is not None
    if has_default:
        if re.search(r"\bfor\s*\(|\bwhen\s*\(", default_text or ""):
            projection.limit("pkl.generator", location)
        ok, value, error = _declared_default(prop.get("initial") or {})
        if ok and _refers_to(default_text or "", siblings - {name}):
            # Evaluated against a fresh object, `total = inputs.length` is 0 — a value, but not
            # the member's default once `inputs` is set. A default computed from other members
            # is declared rather than recorded as that one value.
            projection.limit("pkl.computed_default", location)
        elif ok:
            schema = {**schema, "default": value}
        elif error and _REFUSED_RE.search(error):
            projection.limit("pkl.external_read", location)
        else:
            projection.limit("pkl.computed_default", location)
    nullable = reflected.get("kind") == "nullable"
    return schema, not (has_default or nullable)


def _class_schema(
    class_name: str,
    record: Mapping[str, Any],
    module: Mapping[str, Any],
    by_name: Mapping[Tuple[str, str], Mapping[str, Any]],
    lines: List[str],
    projection: _Projection,
    *,
    definition: str,
) -> Dict[str, Any]:
    """A class (or a module's own properties) as a closed JSON Schema object."""
    properties: Dict[str, Any] = {}
    required: List[str] = []
    superclass = record.get("superclass")
    for name, prop in (record.get("properties") or {}).items():
        if name == "output":
            continue
        inherited = _inherited_property(superclass, name, by_name)
        schema, is_required = _property_schema(
            name,
            prop,
            lines,
            projection,
            owner=definition,
            inherited=inherited,
            siblings=set(record.get("properties") or {}),
        )
        if schema is None:
            continue
        properties[name] = schema
        if is_required:
            required.append(name)
    for _ in record.get("methods") or []:
        projection.limit("pkl.method", definition)
    shape: Dict[str, Any] = {"type": "object", "properties": properties, "additionalProperties": False}
    if required:
        shape["required"] = required
    doc = record.get("doc")
    if isinstance(superclass, dict):
        target = projection.names.get((str(superclass.get("owner")), str(superclass.get("name"))))
        if target is not None:
            projection.references.setdefault(definition, set()).add(target)
            schema: Dict[str, Any] = {"allOf": [{"$ref": f"#/$defs/{target}"}, shape]}
            if isinstance(doc, str) and doc.strip():
                schema["description"] = doc.strip()
            return schema
    if isinstance(doc, str) and doc.strip():
        shape["description"] = doc.strip()
    return shape


def _inherited_property(
    superclass: Any, name: str, by_name: Mapping[Tuple[str, str], Mapping[str, Any]]
) -> Optional[Mapping[str, Any]]:
    """The nearest superclass's record of property ``name``, walking up the chain."""
    seen: Set[Tuple[str, str]] = set()
    while isinstance(superclass, dict):
        key = (str(superclass.get("owner")), str(superclass.get("name")))
        if key in seen:
            return None
        seen.add(key)
        record = by_name.get(key)
        if record is None:
            return None
        prop = (record.get("properties") or {}).get(name)
        if prop is not None and (prop.get("declared") or {}).get("kind") != "unknown":
            return prop
        superclass = record.get("superclass")
    return None


def _assign_names(modules: List[Mapping[str, Any]]) -> Dict[Tuple[str, str], str]:
    """Give every class and alias a definition name; the root module's keep theirs."""
    names: Dict[Tuple[str, str], str] = {}
    taken: Set[str] = set()
    for index, module in enumerate(modules):
        module_name = str(module.get("name"))
        prefix = pascal_case(module_name)
        own = [*(module.get("classes") or {}), *(module.get("typeAliases") or {})]
        for declaration in own:
            name = declaration if declaration not in taken or index == 0 else f"{prefix}{declaration}"
            taken.add(name)
            names[(module_name, declaration)] = name
    return names


def _module_record_name(module: Mapping[str, Any], taken: Set[str]) -> str:
    """The definition name of a module's own properties (``example.beacon`` → ``Beacon``)."""
    name = pascal_case(str(module.get("name") or "Module"))
    return name if name not in taken else f"{name}Module"


def _project(
    modules: List[Mapping[str, Any]], files: Mapping[str, str]
) -> Tuple[Dict[str, Any], List[str], List[Tuple[str, str]], Optional[str]]:
    """Project the reflected modules (root first) to ``$defs``.

    Returns:
        ``(definitions, root exports, limits, identity)``.
    """
    projection = _Projection(names=_assign_names(modules))
    by_name: Dict[Tuple[str, str], Mapping[str, Any]] = {}
    for module in modules:
        for class_name, record in (module.get("classes") or {}).items():
            by_name[(str(module.get("name")), class_name)] = record

    exports: List[str] = []
    identity: Optional[str] = None
    module_definitions: Dict[str, str] = {}
    for index, module in enumerate(modules):
        module_name = str(module.get("name"))
        lines = files.get(str(module.get("path")), "").splitlines()
        declared: List[Tuple[int, str]] = []
        for class_name, record in (module.get("classes") or {}).items():
            definition = projection.names[(module_name, class_name)]
            projection.definitions[definition] = _class_schema(
                class_name, record, module, by_name, lines, projection, definition=definition
            )
            declared.append((int(record.get("line") or 0), definition))
        for alias_name, record in (module.get("typeAliases") or {}).items():
            definition = projection.names[(module_name, alias_name)]
            annotation, _ = _member_annotation(lines, int(record.get("line") or 0), alias_name)
            parsed = parse_type(annotation) if annotation else None
            schema = _type_schema(
                record.get("declared") or {}, parsed, projection, owner=definition, location=definition
            )
            if schema is not None:
                doc = record.get("doc")
                if isinstance(doc, str) and doc.strip():
                    schema = {**schema, "description": doc.strip()}
                projection.definitions[definition] = schema
                declared.append((int(record.get("line") or 0), definition))
        own = {name: prop for name, prop in (module.get("properties") or {}).items() if name != "output"}
        module_definition = None
        # A module whose every property evaluates to a value is configuration *data* — its
        # values were validated and are listed as instances. One with an unfilled property
        # (`id: String`) is a template, and its properties are a record of their own.
        if own and not set(own) <= _evaluated_values(module):
            module_definition = _module_record_name(module, set(projection.definitions))
            projection.definitions[module_definition] = _class_schema(
                module_definition,
                {"properties": own, "methods": module.get("methods"), "doc": module.get("doc")},
                module,
                by_name,
                lines,
                projection,
                definition=module_definition,
            )
            module_definitions[module_name] = module_definition
        elif module.get("methods"):
            for _ in module.get("methods") or []:
                projection.limit("pkl.method", pascal_case(module_name))
        text = files.get(str(module.get("path")), "")
        if _OUTPUT_BLOCK_RE.search(text):
            projection.limit("pkl.output", module_definition or pascal_case(module_name))
        _record_value_failures(module, projection, module_definition or pascal_case(module_name))
        if index == 0:
            ordered = [definition for _, definition in sorted(declared)]
            exports = ([module_definition] if module_definition else []) + ordered
            records = [name for name in ordered if _is_record(projection.definitions.get(name))]
            identity = module_definition or next(iter(records), ordered[0] if ordered else None)

    reachable = _reachable(exports, projection.references)
    definitions = {name: schema for name, schema in projection.definitions.items() if name in reachable}
    return definitions, [name for name in exports if name in definitions], projection.limits, identity


def _is_record(schema: Any) -> bool:
    """Whether a projected definition is a record (an object shape or an extension of one)."""
    return isinstance(schema, dict) and ("properties" in schema or "allOf" in schema)


def _evaluated_values(module: Mapping[str, Any]) -> Set[str]:
    """The module-level properties that evaluated to a value."""
    return {
        str(value.get("name"))
        for value in module.get("values") or []
        if "rendered" in (value.get("result") or {})
    }


def _reachable(roots: List[str], references: Mapping[str, Set[str]]) -> Set[str]:
    """Every definition reachable from ``roots`` through references."""
    seen: Set[str] = set()
    stack = list(roots)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stack.extend(references.get(name, ()))
    return seen


def _record_value_failures(module: Mapping[str, Any], projection: _Projection, definition: str) -> None:
    """Reject a module whose values fail evaluation; declare the reads the sandbox refused.

    A module-level property that evaluates to an error is either a template slot nobody filled
    (``id: String`` with no value — the normal shape of a Pkl schema module), a resource read
    the sandbox refused (declared), or a real failure — a value that violates its own type's
    constraint — which rejects the import.

    Raises:
        TypedConfigParseError: ``INPUT_SEMANTIC_INVALID`` for a value that fails evaluation.
    """
    for value in module.get("values") or []:
        if value.get("name") == "output":
            continue
        error = (value.get("result") or {}).get("error")
        if not error:
            continue
        if _REFUSED_RE.search(error):
            projection.limit("pkl.external_read", f"{definition}.{value.get('name')}")
        elif _UNRESOLVED_MODULE_RE.search(error):
            raise TypedConfigParseError(
                f"`{value.get('name')}` in module {module.get('name')} imports a module the upload "
                f"does not contain — {first_lines(error, 2)} Modules load only from the upload and "
                "Pkl's standard library.",
                code="INPUT_REFERENCE_UNRESOLVED",
            )
        elif not _UNDEFINED_RE.search(error):
            raise TypedConfigParseError(
                f"Evaluating `{value.get('name')}` in module {module.get('name')} failed — "
                f"{first_lines(error, 3)}",
                code="INPUT_SEMANTIC_INVALID",
            )


# ===========================================================================
# Reading
# ===========================================================================


def _program(module_paths: List[str]) -> str:
    """The reflection program importing every module of the upload (root first)."""
    imports = "\n".join(
        f'import "{json.dumps(path)[1:-1]}" as m{index}' for index, path in enumerate(module_paths)
    )
    modules = ", ".join(
        f'describe("{json.dumps(path)[1:-1]}", reflect.Module(m{index}), m{index})'
        for index, path in enumerate(module_paths)
    )
    return REFLECTION_PROGRAM.format(imports=imports, modules=modules)


def _classify(failure: ToolFailure, files: Mapping[str, str], *, where: str) -> TypedConfigParseError:
    """Turn ``pkl``'s error output into a taxonomy-coded rejection.

    The stack frames that belong to the reflection program, not the upload, are dropped.
    """
    lines = failure.output.replace("–– Pkl Error ––", "").strip().splitlines()
    output = "\n".join(line for line in lines if _PROGRAM_FILE[:-4] not in line and "describe(" not in line)
    detail = first_lines(output, 3)
    location = _ERROR_LOCATION_RE.search(failure.output)
    source = None
    if location:
        tail = PurePosixPath(location.group("path")).name
        source = next((text for name, text in files.items() if PurePosixPath(name).name == tail), None)
    if re.search(r"Evaluation timed out", output):
        return TypedConfigParseError(
            f"Evaluating the Pkl module took longer than its time limit{where} — {detail}",
            code="INPUT_TIME_LIMIT",
        )
    if _UNRESOLVED_MODULE_RE.search(output):
        return TypedConfigParseError(
            f"A Pkl import cannot be resolved{where} — {detail}", code="INPUT_REFERENCE_UNRESOLVED"
        )
    if re.search(r"Unexpected token|Mismatched|Missing|Invalid token|Unterminated|Expected", output):
        code = syntax_error_code(source)
        problem = "ends in the middle of a declaration" if code == "INPUT_TRUNCATED" else "is not valid Pkl"
        return TypedConfigParseError(f"The Pkl source {problem}{where} — {detail}", code=code)
    if re.search(r"Cannot find type", output):
        return TypedConfigParseError(
            f"A Pkl type cannot be resolved{where} — {detail}", code="INPUT_REFERENCE_UNRESOLVED"
        )
    return TypedConfigParseError(f"Pkl evaluation failed{where} — {detail}", code="INPUT_SEMANTIC_INVALID")


def _read(files: Mapping[str, str], root: str, *, source_label: Optional[str]) -> TypedConfigDocument:
    """Guard, reflect and project a Pkl upload."""
    where = f" ({source_label})" if source_label else ""
    guard_input(files, label=_LABEL, where=where)
    message = _mismatch(files, root, where)
    if message is not None:
        raise TypedConfigParseError(message, code="FORMAT_MISMATCH")
    if _PROGRAM_FILE in files:
        raise TypedConfigParseError(
            f"{_PROGRAM_FILE} is a reserved file name{where}.", code="INPUT_SEMANTIC_INVALID"
        )

    modules = [root, *sorted(name for name in files if name != root and name.endswith(PKL_SUFFIXES))]
    laid = {**files, _PROGRAM_FILE: _program(modules)}
    with workspace(laid) as directory:
        result = run_typed_config_tool(
            PKL_TOOL_KEY,
            [
                "eval",
                "--no-cache",
                "--no-project",
                "--color=never",
                "--root-dir",
                ".",
                "--working-dir",
                ".",
                "--allowed-modules",
                "file:,pkl:",
                "--allowed-resources",
                "prop:",
                "--timeout",
                "15",
                _PROGRAM_FILE,
            ],
            cwd=directory,
            label=_LABEL,
            where=where,
        )
    if isinstance(result, ToolFailure):
        raise _classify(result, files, where=where)
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise TypedConfigParseError(
            f"pkl eval returned something other than JSON{where}.", code="INTERNAL_ADAPTER_FAULT"
        ) from exc
    reflected = [module for module in payload.get("modules") or [] if isinstance(module, dict)]
    if not reflected:
        raise TypedConfigParseError(
            f"pkl eval reflected no module{where}.", code="INTERNAL_ADAPTER_FAULT"
        )

    definitions, exports, limits, identity = _project(reflected, files)
    if not exports:
        raise TypedConfigParseError(
            f"{root} declares no class, type alias or typed property{where}, so there is no schema "
            "to import.",
            code="INPUT_SEMANTIC_INVALID",
        )
    instances = tuple(
        str(value.get("name"))
        for value in reflected[0].get("values") or []
        if value.get("name") != "output" and "rendered" in (value.get("result") or {})
    )
    return TypedConfigDocument(
        language=PKL_FORMAT,
        root=root,
        files=tuple(sorted(files)),
        tool_version="",
        schema={"$defs": definitions},
        exports=tuple(exports),
        limits=tuple(limits),
        instances=instances,
        identity=identity,
        sources=dict(files),
    )


def _file_name(source_label: Optional[str]) -> str:
    """The name a pasted or uploaded module is written under (it keeps the ``.pkl`` suffix)."""
    name = PurePosixPath(source_label or "").name
    return name if name else "module.pkl"


def parse_pkl(raw: str, *, source_label: Optional[str] = None) -> TypedConfigDocument:
    """Reflect one Pkl module and project its classes and type aliases.

    Args:
        raw: The module source.
        source_label: The module's name, for the tool and for messages.

    Returns:
        The parsed :class:`~app.typed_config_common.TypedConfigDocument`.

    Raises:
        TypedConfigParseError: With the intake taxonomy code the failure belongs to.
    """
    name = _file_name(source_label)
    return _read({name: raw}, name, source_label=source_label)


def parse_pkl_fileset(
    members: Mapping[str, str], *, root: str, source_label: Optional[str] = None
) -> TypedConfigDocument:
    """Reflect a set of Pkl modules that import one another, rooted at ``root``.

    Args:
        members: Relative path → source.
        root: The root module's path; its classes and aliases are the model.
        source_label: Fallback label for messages.

    Returns:
        The parsed document.

    Raises:
        TypedConfigParseError: With the intake taxonomy code the failure belongs to.
    """
    if root not in members:
        raise TypedConfigParseError(
            f"The Pkl set's root module {root!r} is missing.", code="INPUT_SEMANTIC_INVALID"
        )
    return _read(dict(members), root, source_label=source_label or root)
