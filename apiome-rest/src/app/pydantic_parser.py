"""Pydantic model reader — FMT-8.4 (#5465).

Pydantic is Python's Zod: a ``BaseModel`` subclass declares a data shape *and* its validation
constraints. A module of models could produce JSON Schema directly through
``model_json_schema()`` — but only by **importing** it, and importing arbitrary user Python is an
unacceptable execution risk in a multi-tenant service. So this reader never imports, executes or
evaluates the upload: it parses the source with :mod:`ast` and reads what is written.

What a static read can resolve, it resolves:

* ``BaseModel`` subclasses (directly, through other models, through imports between the upload's
  modules), their annotated fields, and ``Field(...)`` / ``Annotated[..., StringConstraints(...)]``
  constraints — mapped to JSON Schema keywords the shared model turns into canonical constraints;
* ``Optional`` / ``Union`` / ``X | Y`` / ``Literal`` / containers / nested and self-referencing
  models, ``Enum`` subclasses, module-level ``Annotated`` and union aliases;
* generic models instantiated by subclassing (``class OrderPage(Page[Order])``);
* aliases (``Field(alias=…)``, ``ConfigDict(alias_generator=to_camel)``), defaults, descriptions,
  ``deprecated``, ``extra="forbid"``.

What only running the module could reveal is **declared**, never guessed: ``create_model``,
validators, computed fields, class-creation hooks, an annotation the reader cannot resolve, and a
type it does not know (:data:`LIMIT_DETAILS`). The output is the same neutral AST FMT-8.1's
TypeScript extractor emits, so :mod:`app.pydantic_normalizer` reuses that model builder and a
Pydantic model, a Zod schema and a TypeScript interface of the same shape model identically.
"""

from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .typescript_types_parser import LimitRecorder

__all__ = [
    "LIMIT_DETAILS",
    "MAX_PYDANTIC_BYTES",
    "PARTIAL_LIMITS",
    "PYTHON_SUFFIXES",
    "PydanticDocument",
    "PydanticParseError",
    "imports_pydantic",
    "is_pydantic_module",
    "parse_pydantic",
    "parse_pydantic_fileset",
    "pydantic_limit_recorder",
]

#: File suffixes this reader claims.
PYTHON_SUFFIXES: Tuple[str, ...] = (".py", ".pyi")

#: The largest module set (all members together) the reader will parse, in bytes.
MAX_PYDANTIC_BYTES = 4 * 1024 * 1024

#: Characters that only appear in source decoded from something that was not UTF-8 text.
_ENCODING_FAULT_MARKERS: Tuple[str, ...] = ("\x00", "�")

#: A ``class X(...BaseModel...)`` line — the detection evidence.
_MODEL_CLASS_RE = re.compile(r"^class\s+\w+\s*\([^)]*\b(?:BaseModel|RootModel)\b", re.MULTILINE)
_PYDANTIC_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+pydantic(?:\.\w+)*\s+import|import\s+pydantic)\b", re.M
)

#: Modules whose names a model may import without the upload containing them: the standard
#: library and pydantic itself. Anything else imported and *used in an annotation* is an
#: unresolved reference.
_KNOWN_LIBRARY_ROOTS = frozenset(
    {
        "__future__",
        "typing",
        "typing_extensions",
        "pydantic",
        "pydantic_core",
        "datetime",
        "decimal",
        "uuid",
        "enum",
        "ipaddress",
        "pathlib",
        "collections",
        "dataclasses",
        "annotated_types",
    }
)


# ===========================================================================
# Declared limits
# ===========================================================================

LIMIT_DETAILS: Dict[str, str] = {
    "pydantic.dynamic_model": (
        "A model built at runtime — `create_model(...)`, or a factory that returns one — has a "
        "field set only executing the module would reveal, and this reader never executes the "
        "upload. It is left out of the model rather than guessed."
    ),
    "pydantic.validator": (
        "A `field_validator`, `model_validator` (or v1 `validator` / `root_validator`) is "
        "arbitrary code. The model and its fields are modelled; what the validator accepts, "
        "rejects or rewrites is not."
    ),
    "pydantic.computed_field": (
        "A `@computed_field` is a property whose value is computed by code at serialization time. "
        "It is not modelled as a field."
    ),
    "pydantic.class_hook": (
        "A model that defines `__init_subclass__`, `__get_pydantic_core_schema__` or a custom "
        "metaclass can change its subclasses' fields when the class is created. The fields that "
        "are written down are modelled; what the hook adds is not."
    ),
    "pydantic.unresolved_annotation": (
        "An annotation the reader cannot resolve statically — a call, a computed type, a name "
        "bound at runtime — is left out rather than modelled as `Any`."
    ),
    "pydantic.unknown_type": (
        "A type the reader does not know (a third-party or uncommon pydantic type) has no "
        "canonical mapping. The field is left out rather than modelled as `Any`."
    ),
    "pydantic.alias_generator": (
        "An `alias_generator` other than pydantic's own `to_camel` / `to_pascal` / `to_snake` is "
        "a function; field names are kept as written."
    ),
    "pydantic.decimal_precision": (
        "`max_digits` / `decimal_places` have no canonical constraint. The field keeps the "
        "`decimal` scalar and both are recorded in `pydantic_decimal`."
    ),
    "pydantic.tuple_positions": (
        "A fixed tuple becomes a list bounded by its length whose items are the union of its "
        "element types; which type sits at which position is recorded in `typescript_tuple`."
    ),
    "pydantic.unmodelled_reference": (
        "A field that refers to something declared a limit (a dynamically built model) cannot "
        "point at a modelled type, so the field is left out too."
    ),
    "pydantic.unresolved_generic": (
        "A generic model is modelled where it is instantiated (`class OrderPage(Page[Order])`); "
        "a generic never instantiated with concrete types has no shape to record."
    ),
    "pydantic.unrepresentable": (
        "A construct with no data shape (`Callable`, `Never`, a bare `type`) is left out of the "
        "model."
    ),
}

#: The limits whose construct is still modelled, with a detail lost.
PARTIAL_LIMITS = frozenset(
    {
        "pydantic.validator",
        "pydantic.class_hook",
        "pydantic.alias_generator",
        "pydantic.decimal_precision",
        "pydantic.tuple_positions",
    }
)

#: The shared model's built-in ``typescript.*`` keys, renamed into this reader's vocabulary.
_TYPESCRIPT_ALIASES: Dict[str, str] = {
    "typescript.tuple_positions": "pydantic.tuple_positions",
    "typescript.unmodelled_reference": "pydantic.unmodelled_reference",
    "typescript.unresolved_generic": "pydantic.unresolved_generic",
    "typescript.index_signature": "pydantic.unrepresentable",
    "typescript.intersection": "pydantic.unrepresentable",
    "typescript.type_query": "pydantic.unresolved_annotation",
    "typescript.lib_type": "pydantic.unknown_type",
    "typescript.function_type": "pydantic.unrepresentable",
    "typescript.symbol_key": "pydantic.unrepresentable",
    "typescript.declaration_merging": "pydantic.unrepresentable",
    "typescript.conditional_type": "pydantic.unrepresentable",
    "typescript.mapped_type": "pydantic.unrepresentable",
    "typescript.template_literal_type": "pydantic.unrepresentable",
}


def pydantic_limit_recorder() -> LimitRecorder:
    """A limit recorder over the Pydantic vocabulary (the shared model's keys renamed into it)."""
    return LimitRecorder(details=LIMIT_DETAILS, aliases=_TYPESCRIPT_ALIASES)


# ===========================================================================
# The parsed document
# ===========================================================================


class PydanticParseError(Exception):
    """A Pydantic module could not be read.

    Attributes:
        code: The intake taxonomy code the failure belongs to.
    """

    def __init__(self, message: str, *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PydanticDocument:
    """A module (or module set) of Pydantic models, read statically.

    Attributes:
        root: The root module's name.
        files: Every module name in the set, sorted.
        declarations: The neutral AST declarations (FMT-8.1's shape) for every model, enum and
            named alias in the set; the root's own and re-exported ones are ``exported``.
        module_limits: Limits met outside any declaration (``create_model`` assignments,
            factories), as ``(construct, location)`` pairs.
        sources: Module name → source text, kept for the fidelity bag.
    """

    root: str
    files: Tuple[str, ...]
    declarations: Tuple[Dict[str, Any], ...]
    module_limits: Tuple[Tuple[str, str], ...] = ()
    sources: Dict[str, str] = field(default_factory=dict)

    def exported(self) -> List[Dict[str, Any]]:
        """The declarations the root module defines or re-exports, in source order."""
        return [d for d in self.declarations if d.get("exported")]


# ===========================================================================
# Detection
# ===========================================================================


def imports_pydantic(text: str) -> bool:
    """Whether a module imports pydantic."""
    return bool(_PYDANTIC_IMPORT_RE.search(text))


def is_pydantic_module(text: str) -> bool:
    """Whether ``text`` reads as a module of Pydantic models (an import plus a model class)."""
    return imports_pydantic(text) and bool(_MODEL_CLASS_RE.search(text))


# ===========================================================================
# Type vocabulary
# ===========================================================================

#: Name → (AST primitive, JSON Schema constraints) for the scalar types pydantic understands.
_SCALARS: Dict[str, Tuple[str, Dict[str, Any]]] = {
    "str": ("string", {}),
    "int": ("integer", {}),
    "float": ("number", {}),
    "bool": ("boolean", {}),
    "bytes": ("bytes", {}),
    "bytearray": ("bytes", {}),
    "None": ("null", {}),
    "NoneType": ("null", {}),
    "Any": ("any", {}),
    "object": ("any", {}),
    "datetime": ("string", {"format": "date-time"}),
    "AwareDatetime": ("string", {"format": "date-time"}),
    "NaiveDatetime": ("string", {"format": "date-time"}),
    "PastDatetime": ("string", {"format": "date-time"}),
    "FutureDatetime": ("string", {"format": "date-time"}),
    "date": ("string", {"format": "date"}),
    "PastDate": ("string", {"format": "date"}),
    "FutureDate": ("string", {"format": "date"}),
    "time": ("string", {"format": "time"}),
    "timedelta": ("string", {"format": "duration"}),
    "Decimal": ("decimal", {}),
    "UUID": ("string", {"format": "uuid"}),
    "UUID1": ("string", {"format": "uuid"}),
    "UUID4": ("string", {"format": "uuid"}),
    "UUID5": ("string", {"format": "uuid"}),
    "EmailStr": ("string", {"format": "email"}),
    "NameEmail": ("string", {"format": "name-email"}),
    "AnyUrl": ("string", {"format": "uri"}),
    "AnyHttpUrl": ("string", {"format": "uri"}),
    "HttpUrl": ("string", {"format": "uri"}),
    "FileUrl": ("string", {"format": "uri"}),
    "PostgresDsn": ("string", {"format": "uri"}),
    "RedisDsn": ("string", {"format": "uri"}),
    "IPv4Address": ("string", {"format": "ipv4"}),
    "IPv6Address": ("string", {"format": "ipv6"}),
    "IPvAnyAddress": ("string", {"format": "ipvanyaddress"}),
    "IPv4Network": ("string", {"format": "ipv4network"}),
    "IPv6Network": ("string", {"format": "ipv6network"}),
    "Path": ("string", {"format": "path"}),
    "FilePath": ("string", {"format": "file-path"}),
    "DirectoryPath": ("string", {"format": "directory-path"}),
    "SecretStr": ("string", {"format": "password"}),
    "SecretBytes": ("bytes", {"format": "password"}),
    "StrictStr": ("string", {}),
    "StrictInt": ("integer", {}),
    "StrictFloat": ("number", {}),
    "StrictBool": ("boolean", {}),
    "StrictBytes": ("bytes", {}),
    "PositiveInt": ("integer", {"exclusiveMinimum": 0}),
    "NegativeInt": ("integer", {"exclusiveMaximum": 0}),
    "NonNegativeInt": ("integer", {"minimum": 0}),
    "NonPositiveInt": ("integer", {"maximum": 0}),
    "PositiveFloat": ("number", {"exclusiveMinimum": 0}),
    "NegativeFloat": ("number", {"exclusiveMaximum": 0}),
    "NonNegativeFloat": ("number", {"minimum": 0}),
    "NonPositiveFloat": ("number", {"maximum": 0}),
}

_LIST_NAMES = frozenset(
    {"list", "List", "Sequence", "MutableSequence", "Iterable", "Collection", "deque", "Deque"}
)
_SET_NAMES = frozenset({"set", "Set", "frozenset", "FrozenSet", "AbstractSet", "MutableSet"})
_DICT_NAMES = frozenset(
    {"dict", "Dict", "Mapping", "MutableMapping", "OrderedDict", "DefaultDict", "defaultdict"}
)
_UNREPRESENTABLE = frozenset(
    {"Callable", "Never", "NoReturn", "type", "Type", "Awaitable", "Coroutine"}
)
_WRAPPERS = frozenset({"ClassVar", "Final", "Required", "NotRequired", "ReadOnly", "InitVar"})
_ENUM_BASES = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})
_MODEL_BASES = frozenset({"BaseModel", "RootModel"})
_VALIDATOR_DECORATORS = frozenset(
    {
        "field_validator",
        "model_validator",
        "validator",
        "root_validator",
        "field_serializer",
        "model_serializer",
    }
)
_CLASS_HOOKS = frozenset(
    {"__init_subclass__", "__get_pydantic_core_schema__", "__get_pydantic_json_schema__"}
)

#: ``Field(...)`` / ``StringConstraints(...)`` keyword → JSON Schema keyword.
_FIELD_CONSTRAINTS = {
    "gt": "exclusiveMinimum",
    "ge": "minimum",
    "lt": "exclusiveMaximum",
    "le": "maximum",
    "multiple_of": "multipleOf",
    "pattern": "pattern",
    "regex": "pattern",
    "min_length": "minLength",
    "max_length": "maxLength",
    "min_items": "minItems",
    "max_items": "maxItems",
    "unique_items": "uniqueItems",
}


def _camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])


def _pascal(name: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in name.split("_"))


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


_ALIAS_GENERATORS = {
    "to_camel": _camel,
    "to_lower_camel": _camel,
    "to_pascal": _pascal,
    "to_snake": _snake,
}


# ===========================================================================
# The static reader
# ===========================================================================


def _dotted(node: ast.AST) -> Optional[str]:
    """``pydantic.Field`` → ``"pydantic.Field"``; ``Field`` → ``"Field"``."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _tail(node: ast.AST) -> Optional[str]:
    """The last segment of a (dotted) name: ``pydantic.Field`` → ``"Field"``."""
    name = _dotted(node)
    return name.rsplit(".", 1)[-1] if name else None


def _literal(node: ast.AST) -> Tuple[bool, Any]:
    """Statically evaluate a literal expression (never anything that runs code)."""
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


@dataclass
class _Module:
    """One parsed module: its imports, classes and module-level aliases."""

    name: str
    tree: ast.Module
    stem: str
    imports: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # local → (module, attr)
    classes: Dict[str, ast.ClassDef] = field(default_factory=dict)
    aliases: Dict[str, ast.expr] = field(default_factory=dict)
    type_vars: Set[str] = field(default_factory=set)


class _Reader:
    """Reads a module set into FMT-8.1 neutral declarations, without executing anything."""

    def __init__(self, files: Mapping[str, str], root: str) -> None:
        self.root = root
        #: Limits met outside any declaration (``X = create_model(...)``, factories).
        self.module_limits: List[Tuple[str, str]] = []
        #: Annotation names nothing in the upload or the known libraries defines.
        self.unresolved: List[Tuple[str, str]] = []
        self.modules: Dict[str, _Module] = {}
        self.by_stem: Dict[str, str] = {}
        for name, text in files.items():
            tree = self._parse(name, text)
            stem = PurePosixPath(name).with_suffix("").as_posix().replace("/", ".")
            module = _Module(name=name, tree=tree, stem=stem)
            self.modules[name] = module
            self.by_stem[stem] = name
            self.by_stem.setdefault(stem.rsplit(".", 1)[-1], name)
            if stem.endswith(".__init__"):
                self.by_stem[stem[: -len(".__init__")]] = name
        for module in self.modules.values():
            self._index(module)

    # --- parsing -----------------------------------------------------------------------

    @staticmethod
    def _parse(name: str, text: str) -> ast.Module:
        try:
            return ast.parse(text, filename=name)
        except SyntaxError as exc:
            location = f"{name}:{exc.lineno}:{exc.offset}"
            message = f"{location}: {exc.msg}"
            # The text stopped while a construct was still open: an unclosed bracket, an
            # unexpected end of file, or a block header with nothing after it on the last line.
            msg = exc.msg or ""
            at_last_line = (exc.lineno or 0) >= len(text.rstrip().splitlines())
            truncated = (
                "was never closed" in msg
                or "unexpected EOF" in msg
                or ("expected an indented block" in msg and at_last_line)
            )
            if truncated:
                raise PydanticParseError(
                    f"The module ends in the middle of a declaration — {message}",
                    code="INPUT_TRUNCATED",
                ) from exc
            raise PydanticParseError(
                f"Python syntax error — {message}", code="INPUT_MALFORMED"
            ) from exc

    def _index(self, module: _Module) -> None:
        for statement in module.tree.body:
            if isinstance(statement, ast.ImportFrom):
                source = "." * statement.level + (statement.module or "")
                for alias in statement.names:
                    module.imports[alias.asname or alias.name] = (source, alias.name)
            elif isinstance(statement, ast.Import):
                for alias in statement.names:
                    module.imports[alias.asname or alias.name.split(".")[0]] = (alias.name, "")
            elif isinstance(statement, ast.ClassDef):
                module.classes[statement.name] = statement
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                )
                value = statement.value
                for target in targets:
                    if not isinstance(target, ast.Name) or value is None:
                        continue
                    if isinstance(value, ast.Call) and _tail(value.func) in {
                        "TypeVar",
                        "ParamSpec",
                    }:
                        module.type_vars.add(target.id)
                    elif isinstance(value, ast.Call) and _tail(value.func) == "create_model":
                        self.module_limits.append(("pydantic.dynamic_model", target.id))
                    elif self._is_type_expression(value):
                        module.aliases[target.id] = value
            elif isinstance(
                statement, ast.TypeAlias
            ):  # pragma: no cover - Python 3.12 `type X = …`
                module.aliases[statement.name.id] = statement.value

    @staticmethod
    def _is_type_expression(node: ast.expr) -> bool:
        """Whether a module-level value is a type expression worth treating as an alias."""
        if isinstance(node, ast.Subscript):
            return (
                _tail(node.value)
                in {"Annotated", "Union", "Optional", "Literal"}
                | _LIST_NAMES
                | _DICT_NAMES
                | _SET_NAMES
            )
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return True
        return False

    # --- name resolution --------------------------------------------------------------

    def _module_for(self, source: str, importer: _Module) -> Optional[_Module]:
        """The upload module an ``import`` statement names, or ``None``."""
        if source.startswith("."):
            depth = len(source) - len(source.lstrip("."))
            base = importer.stem.split(".")[:-depth] if depth else []
            target = ".".join([*base, source.lstrip(".")]).strip(".")
        else:
            target = source
        name = self.by_stem.get(target) or self.by_stem.get(target.rsplit(".", 1)[-1])
        return self.modules.get(name) if name else None

    def resolve(
        self, name: str, module: _Module, seen: Optional[Set[Tuple[str, str]]] = None
    ) -> Tuple[str, Any]:
        """Resolve a bare name in ``module``.

        Returns:
            ``("class", (module, ClassDef))``, ``("alias", (module, expr))``, ``("typevar", name)``,
            ``("library", (module, attr))`` for a stdlib/pydantic import, or ``("unresolved",
            source)`` for a name nothing in the upload or the known libraries defines.
        """
        seen = seen or set()
        if (module.name, name) in seen:
            return "unresolved", name
        seen.add((module.name, name))
        if name in module.classes:
            return "class", (module, module.classes[name])
        if name in module.type_vars:
            return "typevar", name
        if name in module.aliases:
            return "alias", (module, module.aliases[name])
        if name in module.imports:
            source, attr = module.imports[name]
            target = self._module_for(source, module)
            if target is not None:
                return self.resolve(attr or name, target, seen)
            root = source.lstrip(".").split(".")[0]
            if root in _KNOWN_LIBRARY_ROOTS:
                return "library", (source, attr or name)
            return "unresolved", source or name
        if name in _SCALARS or hasattr(builtins, name):
            return "library", ("builtins", name)
        return "unresolved", name

    # --- classes -----------------------------------------------------------------------

    def is_model(self, module: _Module, cls: ast.ClassDef, seen: Optional[Set[str]] = None) -> bool:
        """Whether a class is (transitively) a ``BaseModel`` subclass."""
        seen = seen or set()
        key = f"{module.name}#{cls.name}"
        if key in seen:
            return False
        seen.add(key)
        for base in cls.bases:
            node = base.value if isinstance(base, ast.Subscript) else base
            tail = _tail(node)
            if tail in _MODEL_BASES:
                return True
            if isinstance(node, ast.Name):
                kind, value = self.resolve(node.id, module)
                if kind == "class" and self.is_model(value[0], value[1], seen):
                    return True
        return False

    def is_enum(self, module: _Module, cls: ast.ClassDef) -> bool:
        """Whether a class is an ``Enum`` subclass (directly)."""
        return any(_tail(base) in _ENUM_BASES for base in cls.bases)

    def declarations(self) -> List[Dict[str, Any]]:
        """Every model, enum and union alias in the set, as neutral declarations."""
        root = self.modules[self.root]
        exported_ids = {f"{root.name}#{name}" for name in root.classes}
        for local, (source, attr) in root.imports.items():
            target = self._module_for(source, root)
            if target is not None:
                kind, value = self.resolve(attr or local, target)
                if kind == "class":
                    exported_ids.add(f"{value[0].name}#{value[1].name}")
        out: List[Dict[str, Any]] = []
        ordered = [root] + [m for name, m in sorted(self.modules.items()) if name != self.root]
        for module in ordered:
            for cls in module.classes.values():
                declaration_id = f"{module.name}#{cls.name}"
                if self.is_enum(module, cls):
                    out.append(self._enum(module, cls, exported=declaration_id in exported_ids))
                elif self.is_model(module, cls):
                    out.append(self._model(module, cls, exported=declaration_id in exported_ids))
            for name, value in module.aliases.items():
                if not _is_annotated(value):
                    out.append(self._alias(module, name, value))
            for statement in module.tree.body:
                if isinstance(statement, ast.FunctionDef) and any(
                    isinstance(n, ast.Call) and _tail(n.func) == "create_model"
                    for n in ast.walk(statement)
                ):
                    self.module_limits.append(("pydantic.dynamic_model", statement.name))
        return out

    @staticmethod
    def _docstring(node: ast.AST) -> Optional[str]:
        text = (
            ast.get_docstring(node)
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.Module))
            else None
        )
        return text.strip() if text else None

    def _enum(self, module: _Module, cls: ast.ClassDef, *, exported: bool) -> Dict[str, Any]:
        members = []
        for statement in cls.body:
            if (
                isinstance(statement, ast.Assign)
                and len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
            ):
                ok, value = _literal(statement.value)
                if ok and not statement.targets[0].id.startswith("_"):
                    members.append(
                        {
                            "name": statement.targets[0].id,
                            "value": value,
                            "doc": None,
                            "deprecated": False,
                        }
                    )
        return {
            "id": f"{module.name}#{cls.name}",
            "name": cls.name,
            "module": module.name,
            "line": cls.lineno,
            "exported": exported,
            "doc": self._docstring(cls),
            "deprecated": False,
            "typeParameters": [],
            "mergedDeclarations": 1,
            "kind": "enum",
            "const": False,
            "members": members,
        }

    def _alias(self, module: _Module, name: str, value: ast.expr) -> Dict[str, Any]:
        return {
            "id": f"{module.name}#{name}",
            "name": name,
            "module": module.name,
            "line": value.lineno,
            "exported": False,
            "doc": None,
            "deprecated": False,
            "typeParameters": [],
            "mergedDeclarations": 1,
            "kind": "alias",
            "type": self.annotation(value, module, location=name),
        }

    def _config(self, cls: ast.ClassDef) -> Dict[str, Any]:
        """The literal keywords of a class's ``model_config = ConfigDict(...)``."""
        for statement in cls.body:
            target = (
                statement.targets[0]
                if isinstance(statement, ast.Assign) and statement.targets
                else getattr(statement, "target", None)
            )
            if isinstance(target, ast.Name) and target.id == "model_config":
                value = getattr(statement, "value", None)
                if isinstance(value, ast.Call):
                    config: Dict[str, Any] = {}
                    for keyword in value.keywords:
                        ok, literal = _literal(keyword.value)
                        config[keyword.arg or ""] = literal if ok else _dotted(keyword.value)
                    return config
        return {}

    def _model(self, module: _Module, cls: ast.ClassDef, *, exported: bool) -> Dict[str, Any]:
        location = cls.name
        limits: List[str] = []
        config = self._config(cls)
        generator = None
        if config.get("alias_generator"):
            generator = _ALIAS_GENERATORS.get(str(config["alias_generator"]).rsplit(".", 1)[-1])
            if generator is None:
                limits.append("pydantic.alias_generator")

        parents: List[Dict[str, Any]] = []
        type_parameters: List[str] = []
        for base in cls.bases:
            node = base.value if isinstance(base, ast.Subscript) else base
            tail = _tail(node)
            if tail == "Generic" and isinstance(base, ast.Subscript):
                type_parameters = [n.id for n in _subscript_args(base) if isinstance(n, ast.Name)]
                continue
            if tail in _MODEL_BASES or not isinstance(node, ast.Name):
                continue
            kind, value = self.resolve(node.id, module)
            if kind == "class" and self.is_model(value[0], value[1]):
                args = (
                    [self.annotation(a, module, location=location) for a in _subscript_args(base)]
                    if isinstance(base, ast.Subscript)
                    else []
                )
                parents.append(
                    {
                        "kind": "ref",
                        "target": f"{value[0].name}#{value[1].name}",
                        "name": value[1].name,
                        "typeArguments": args,
                    }
                )
        # Pydantic collects fields over the reversed MRO, so an earlier base wins a clash; the
        # shared model lets a *later* parent override, hence the reversal.
        parents.reverse()

        properties: List[Dict[str, Any]] = []
        unsupported: List[Dict[str, Any]] = []
        for statement in cls.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                attr = statement.target.id
                if (
                    attr == "model_config"
                    or attr.startswith("_")
                    or _tail(_unwrap_classvar(statement.annotation)) == "ClassVar"
                ):
                    continue
                prop = self._field(module, cls.name, attr, statement, generator)
                if prop is not None:
                    properties.append(prop)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                decorators = {
                    _tail(d.func if isinstance(d, ast.Call) else d)
                    for d in statement.decorator_list
                }
                if decorators & _VALIDATOR_DECORATORS:
                    limits.append("pydantic.validator")
                if "computed_field" in decorators:
                    unsupported.append(
                        {
                            "name": statement.name,
                            "construct": "pydantic.computed_field",
                            "text": statement.name,
                        }
                    )
                if statement.name in _CLASS_HOOKS:
                    limits.append("pydantic.class_hook")
        if any(k.arg == "metaclass" for k in cls.keywords):
            limits.append("pydantic.class_hook")

        node: Dict[str, Any] = {
            "properties": properties,
            "indexSignatures": [],
            "unsupported": unsupported,
        }
        extra = config.get("extra")
        if extra in {"forbid", "allow", "ignore"}:
            node["extras"] = {"pydantic_extra": extra}
        if limits:
            node["limits"] = sorted(set(limits), key=limits.index)
        return {
            "id": f"{module.name}#{cls.name}",
            "name": cls.name,
            "module": module.name,
            "line": cls.lineno,
            "exported": exported,
            "doc": self._docstring(cls),
            "deprecated": False,
            "typeParameters": [{"name": t, "default": None} for t in type_parameters],
            "mergedDeclarations": 1,
            "kind": "interface",
            "extends": parents,
            **node,
        }

    def _field(
        self, module: _Module, owner: str, attr: str, statement: ast.AnnAssign, generator: Any
    ) -> Optional[Dict[str, Any]]:
        location = f"{owner}.{attr}"
        type_node = self.annotation(statement.annotation, module, location=location)
        info = _FieldInfo()
        value = statement.value
        if isinstance(value, ast.Call) and _tail(value.func) == "Field":
            info.read_field_call(value, module, self)
        elif value is not None:
            info.has_default = True
            info.default = self.default_value(value, module)
        extras: Dict[str, Any] = {}
        name = info.alias or (generator(attr) if generator else attr)
        if name != attr:
            extras["pydantic_name"] = attr
        if info.exclude:
            extras["pydantic_exclude"] = True
        if info.examples is not None:
            extras["pydantic_examples"] = info.examples
        if info.default_factory:
            extras["pydantic_default_factory"] = info.default_factory
        if info.decimal:
            extras["pydantic_decimal"] = info.decimal
            type_node = {
                **type_node,
                "limits": [*type_node.get("limits", []), "pydantic.decimal_precision"],
            }
        if info.constraints:
            type_node = _attach_constraints(type_node, info.constraints)
        prop: Dict[str, Any] = {
            "name": name,
            "optional": info.has_default,
            "readonly": False,
            "type": type_node,
            "doc": info.description,
            "deprecated": info.deprecated,
            "line": statement.lineno,
        }
        if info.has_default and info.default is not _NO_DEFAULT:
            prop["default"] = info.default
        if extras:
            prop["extras"] = extras
        return prop

    def default_value(self, node: ast.AST, module: _Module) -> Any:
        """A field default, when it is a literal or an enum member; otherwise unrecorded."""
        ok, value = _literal(node)
        if ok:
            return value
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            kind, resolved = self.resolve(node.value.id, module)
            if kind == "class" and self.is_enum(*resolved):
                for statement in resolved[1].body:
                    if (
                        isinstance(statement, ast.Assign)
                        and isinstance(statement.targets[0], ast.Name)
                        and statement.targets[0].id == node.attr
                    ):
                        ok, value = _literal(statement.value)
                        if ok:
                            return value
        return _NO_DEFAULT

    # --- annotations -----------------------------------------------------------------

    def annotation(self, node: ast.expr, module: _Module, *, location: str) -> Dict[str, Any]:
        """Translate one annotation expression into a neutral AST node (never executing it)."""
        if isinstance(node, ast.Constant):
            if node.value is None:
                return {"kind": "primitive", "name": "null"}
            if isinstance(node.value, str):
                # A forward reference: parse the string as an expression, still statically.
                try:
                    return self.annotation(
                        ast.parse(node.value, mode="eval").body, module, location=location
                    )
                except SyntaxError:
                    return _unsupported("pydantic.unresolved_annotation", node.value)
            return {"kind": "literal", "value": node.value}
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return {
                "kind": "union",
                "members": [
                    self.annotation(m, module, location=location) for m in _flatten_bitor(node)
                ],
            }
        if isinstance(node, (ast.Name, ast.Attribute)):
            return self._named(node, module, location=location)
        if isinstance(node, ast.Subscript):
            return self._subscript(node, module, location=location)
        return _unsupported("pydantic.unresolved_annotation", ast.unparse(node))

    def _named(self, node: ast.expr, module: _Module, *, location: str) -> Dict[str, Any]:
        dotted = _dotted(node) or ""
        tail = dotted.rsplit(".", 1)[-1]
        if isinstance(node, ast.Attribute):
            # `uuid.UUID`, `datetime.datetime`, `pydantic.EmailStr`: a module attribute.
            if tail in _SCALARS:
                return _scalar(tail)
            return _unsupported("pydantic.unknown_type", dotted)
        kind, value = self.resolve(node.id, module)
        if kind == "class":
            owner, cls = value
            if self.is_model(owner, cls) or self.is_enum(owner, cls):
                return {
                    "kind": "ref",
                    "target": f"{owner.name}#{cls.name}",
                    "name": cls.name,
                    "typeArguments": [],
                }
            return _unsupported("pydantic.unknown_type", cls.name)
        if kind == "alias":
            owner, expr = value
            if isinstance(expr, ast.Subscript) and _tail(expr.value) == "Annotated":
                return self.annotation(expr, owner, location=location)
            return {
                "kind": "ref",
                "target": f"{owner.name}#{node.id}",
                "name": node.id,
                "typeArguments": [],
            }
        if kind == "typevar":
            return {"kind": "typeParameter", "name": value}
        if kind == "library":
            attr = value[1]
            if attr in _SCALARS:
                return _scalar(attr)
            if attr in _UNREPRESENTABLE:
                return _unsupported("pydantic.unrepresentable", attr)
            if attr in _LIST_NAMES:
                return {
                    "kind": "array",
                    "element": {"kind": "primitive", "name": "any"},
                    "readonly": False,
                }
            if attr in _DICT_NAMES:
                return {
                    "kind": "lib",
                    "name": "Record",
                    "typeArguments": [
                        {"kind": "primitive", "name": "string"},
                        {"kind": "primitive", "name": "any"},
                    ],
                }
            return _unsupported("pydantic.unknown_type", attr)
        self.unresolved.append((location, str(value)))
        return {"kind": "unresolved", "name": node.id}

    def _subscript(self, node: ast.Subscript, module: _Module, *, location: str) -> Dict[str, Any]:
        head = _tail(node.value)
        args = _subscript_args(node)
        if head == "Annotated" and args:
            inner = self.annotation(args[0], module, location=location)
            constraints: Dict[str, Any] = {}
            discriminated = False
            for meta in args[1:]:
                if isinstance(meta, ast.Call) and _tail(meta.func) in {
                    "Field",
                    "StringConstraints",
                    "conint",
                    "constr",
                    "confloat",
                }:
                    info = _FieldInfo()
                    info.read_field_call(meta, module, self)
                    constraints.update(info.constraints)
                    discriminated = discriminated or info.discriminator is not None
            return _attach_constraints(inner, constraints) if constraints else inner
        if head in _WRAPPERS and args:
            return self.annotation(args[0], module, location=location)
        if head == "Optional" and args:
            return {
                "kind": "union",
                "members": [
                    self.annotation(args[0], module, location=location),
                    {"kind": "primitive", "name": "null"},
                ],
            }
        if head == "Union":
            return {
                "kind": "union",
                "members": [self.annotation(a, module, location=location) for a in args],
            }
        if head == "Literal":
            members = []
            for arg in args:
                ok, value = _literal(arg)
                members.append(
                    {"kind": "literal", "value": value}
                    if ok
                    else _unsupported("pydantic.unresolved_annotation", ast.unparse(arg))
                )
            return members[0] if len(members) == 1 else {"kind": "union", "members": members}
        if head in _LIST_NAMES:
            return {
                "kind": "array",
                "element": self.annotation(args[0], module, location=location)
                if args
                else {"kind": "primitive", "name": "any"},
                "readonly": False,
            }
        if head in _SET_NAMES:
            return {
                "kind": "lib",
                "name": "Set",
                "typeArguments": [self.annotation(a, module, location=location) for a in args[:1]],
            }
        if head in _DICT_NAMES and len(args) == 2:
            return {
                "kind": "lib",
                "name": "Record",
                "typeArguments": [self.annotation(a, module, location=location) for a in args],
            }
        if head in {"tuple", "Tuple"}:
            if len(args) == 2 and isinstance(args[1], ast.Constant) and args[1].value is Ellipsis:
                return {
                    "kind": "array",
                    "element": self.annotation(args[0], module, location=location),
                    "readonly": False,
                }
            return {
                "kind": "tuple",
                "elements": [
                    {
                        "name": None,
                        "type": self.annotation(a, module, location=location),
                        "optional": False,
                        "rest": False,
                    }
                    for a in args
                ],
            }
        if head in {"Json"} and args:
            return self.annotation(args[0], module, location=location)
        if head in {"Type", "type"} | _UNREPRESENTABLE:
            return _unsupported("pydantic.unrepresentable", ast.unparse(node))
        if isinstance(node.value, ast.Name):
            kind, value = self.resolve(node.value.id, module)
            if kind == "class" and self.is_model(*value):
                return {
                    "kind": "ref",
                    "target": f"{value[0].name}#{value[1].name}",
                    "name": value[1].name,
                    "typeArguments": [self.annotation(a, module, location=location) for a in args],
                }
        return _unsupported("pydantic.unresolved_annotation", ast.unparse(node))


#: Marker for "the field has a default the reader could not evaluate statically".
_NO_DEFAULT = object()


class _FieldInfo:
    """What a ``Field(...)`` / ``StringConstraints(...)`` call states, read literally."""

    def __init__(self) -> None:
        self.has_default = False
        self.default: Any = _NO_DEFAULT
        self.default_factory: Optional[str] = None
        self.alias: Optional[str] = None
        self.description: Optional[str] = None
        self.deprecated = False
        self.exclude = False
        self.examples: Any = None
        self.discriminator: Optional[str] = None
        self.constraints: Dict[str, Any] = {}
        self.decimal: Dict[str, Any] = {}

    def read_field_call(self, call: ast.Call, module: _Module, reader: _Reader) -> None:
        if call.args and _tail(call.func) == "Field":
            first = call.args[0]
            if not (isinstance(first, ast.Constant) and first.value is Ellipsis):
                self.has_default = True
                self.default = reader.default_value(first, module)
        for keyword in call.keywords:
            arg = keyword.arg or ""
            ok, value = _literal(keyword.value)
            if arg == "default":
                if not (ok and value is Ellipsis):
                    self.has_default = True
                    self.default = value if ok else reader.default_value(keyword.value, module)
            elif arg == "default_factory":
                self.has_default = True
                self.default_factory = _dotted(keyword.value) or ast.unparse(keyword.value)
            elif (
                arg in {"alias", "validation_alias", "serialization_alias"}
                and ok
                and isinstance(value, str)
            ):
                if arg == "alias" or self.alias is None:
                    self.alias = value
            elif arg in {"description", "title"} and ok and isinstance(value, str):
                if arg == "description" or self.description is None:
                    self.description = value
            elif arg == "deprecated":
                self.deprecated = bool(value) if ok else True
            elif arg == "exclude" and ok:
                self.exclude = bool(value)
            elif arg == "examples" and ok:
                self.examples = value
            elif arg == "discriminator" and ok:
                self.discriminator = value
            elif arg in {"max_digits", "decimal_places"} and ok:
                self.decimal[arg] = value
            elif arg in _FIELD_CONSTRAINTS and ok:
                self.constraints[_FIELD_CONSTRAINTS[arg]] = value


def _is_annotated(node: ast.expr) -> bool:
    """Whether an alias is ``Annotated[...]`` — expanded inline (with its constraints) at every
    use, as pydantic's own schema does, rather than becoming a named type."""
    return isinstance(node, ast.Subscript) and _tail(node.value) == "Annotated"


def _subscript_args(node: ast.Subscript) -> List[ast.expr]:
    sl = node.slice
    return list(sl.elts) if isinstance(sl, ast.Tuple) else [sl]


def _flatten_bitor(node: ast.expr) -> Iterable[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        yield from _flatten_bitor(node.left)
        yield from _flatten_bitor(node.right)
    else:
        yield node


def _unwrap_classvar(node: ast.expr) -> ast.expr:
    return node.value if isinstance(node, ast.Subscript) else node


def _scalar(name: str) -> Dict[str, Any]:
    primitive, constraints = _SCALARS[name]
    node: Dict[str, Any] = {"kind": "primitive", "name": primitive}
    return _attach_constraints(node, dict(constraints)) if constraints else node


def _unsupported(construct: str, text: str) -> Dict[str, Any]:
    return {"kind": "unsupported", "construct": construct, "text": text[:200]}


#: Length keywords that mean an item count when the annotation is a collection.
_COLLECTION_LENGTHS = {"minLength": "minItems", "maxLength": "maxItems"}


def _attach_constraints(node: Dict[str, Any], constraints: Dict[str, Any]) -> Dict[str, Any]:
    """Attach JSON Schema constraints to an AST node, placing them where they mean something.

    ``Optional[X]`` carries the constraints on ``X``; a ``min_length`` on a list or set is an
    item count, as in pydantic.
    """
    if node.get("kind") == "union":
        members = node["members"]
        non_null = [
            m for m in members if not (m.get("kind") == "primitive" and m.get("name") == "null")
        ]
        if len(non_null) == 1:
            index = members.index(non_null[0])
            return {
                **node,
                "members": [
                    *members[:index],
                    _attach_constraints(non_null[0], constraints),
                    *members[index + 1 :],
                ],
            }
    if node.get("kind") in {"array", "tuple"} or (
        node.get("kind") == "lib" and node.get("name") == "Set"
    ):
        constraints = {_COLLECTION_LENGTHS.get(k, k): v for k, v in constraints.items()}
    merged = {**(node.get("constraints") or {}), **constraints}
    return {**node, "constraints": merged}


# ===========================================================================
# Entry points
# ===========================================================================


def _guard(files: Mapping[str, str], root: str, where: str) -> None:
    if not any(text.strip() for text in files.values()):
        raise PydanticParseError(f"The Python module is empty{where}.", code="INPUT_EMPTY")
    size = sum(len(text.encode("utf-8", "ignore")) for text in files.values())
    if size > MAX_PYDANTIC_BYTES:
        raise PydanticParseError(
            f"The Python source is {size} bytes{where}, above the {MAX_PYDANTIC_BYTES}-byte import limit.",
            code="INPUT_TOO_LARGE",
        )
    for name, text in sorted(files.items()):
        if text.startswith("﻿") or any(marker in text for marker in _ENCODING_FAULT_MARKERS):
            raise PydanticParseError(
                f"{name} is not UTF-8 text (it looks like UTF-16 or binary){where}.",
                code="INPUT_ENCODING_INVALID",
            )
    if not any(imports_pydantic(text) for text in files.values()):
        raise PydanticParseError(
            f"{root} does not import pydantic, so it defines no Pydantic models{where} (standard "
            "dataclasses and plain classes carry no pydantic constraints).",
            code="FORMAT_MISMATCH",
        )


def _read(files: Mapping[str, str], root: str, *, source_label: Optional[str]) -> PydanticDocument:
    where = f" ({source_label})" if source_label else ""
    _guard(files, root, where)
    reader = _Reader(files, root)
    declarations = reader.declarations()
    if not any(d.get("exported") and d["kind"] == "interface" for d in declarations):
        raise PydanticParseError(
            f"The module defines no `BaseModel` subclass{where}, so there is no model to import.",
            code="INPUT_SEMANTIC_INVALID",
        )
    if reader.unresolved:
        location, source = reader.unresolved[0]
        raise PydanticParseError(
            f"{location} refers to `{source}`, which no module in the import defines{where}. Add "
            "that module to the upload, or import the files as a set.",
            code="INPUT_REFERENCE_UNRESOLVED",
        )
    return PydanticDocument(
        root=root,
        files=tuple(sorted(files)),
        declarations=tuple(declarations),
        module_limits=tuple(dict.fromkeys(reader.module_limits)),
        sources=dict(files),
    )


def parse_pydantic(raw: str, *, source_label: Optional[str] = None) -> PydanticDocument:
    """Read one module of Pydantic models statically (it is never imported or executed).

    Raises:
        PydanticParseError: With the intake taxonomy code the failure belongs to.
    """
    name = PurePosixPath(source_label or "").name
    if not name.endswith(PYTHON_SUFFIXES):
        name = "models.py"
    return _read({name: raw}, name, source_label=source_label)


def parse_pydantic_fileset(
    members: Mapping[str, str], *, root: str, source_label: Optional[str] = None
) -> PydanticDocument:
    """Read a package of modules statically, rooted at ``root``.

    Raises:
        PydanticParseError: With the intake taxonomy code the failure belongs to.
    """
    files = {p: t for p, t in members.items() if p.lower().endswith(PYTHON_SUFFIXES)}
    if root not in files:
        raise PydanticParseError(
            f"The Pydantic set's root module {root!r} is missing or is not a Python file.",
            code="INPUT_SEMANTIC_INVALID",
        )
    return _read(files, root, source_label=source_label or root)
