"""The FastAPI server stub generator — SDK-2.5 (#4490).

Turns a :class:`~app.server_stub_plan.ServerStubPlan` into a runnable FastAPI project: pydantic v2
models for the contract's schemas, one ``APIRouter`` per tag, typed handler protocols a team
implements, and an application factory that wires the two together.

**What "stub" means here.** The generated project boots and serves on its own. Every route is
registered, every request is validated against the contract *before* any user code runs, and every
operation answers ``501 Not Implemented`` until somebody implements it. A design-first team clones
it, subclasses one ``NotImplemented…Handlers`` per tag, and fills in bodies — they never write a
route, a parameter declaration or a validation rule.

**Where the validation comes from.** FastAPI already validates a typed signature, so the
generator's job is to make the signature say exactly what the contract said: every path, query,
header and cookie parameter declared with its resolved type, its ``alias`` when the wire name is
not a Python identifier, and its optionality; every JSON request body typed as its pydantic model.
The one thing FastAPI does not do the way a contract-first team wants is *report* the failure —
its default is a ``422`` with its own envelope — so the project installs one exception handler
that answers RFC 9457 ``application/problem+json`` with a ``400`` and a per-field ``errors`` array,
and puts the status in a single module constant so a team that prefers ``422`` changes one line.

**Three properties are load-bearing.**

*It is byte-deterministic.* Every collection is walked in plan order and every name comes from the
plan's allocators. Nothing reads the clock, the environment or the filesystem, so the client kit
can keep serving a content-addressed ``ETag``.

*It emits Python that imports.* A generated module's import list is computed from what it actually
uses, model declarations are ordered so a bare type alias never forward-references, and every
model is rebuilt at the end of ``models.py`` so a recursive contract (a comment whose replies are
comments) resolves rather than leaving a half-built model to fail on first request.

*It never refuses over one bad operation.* Operations with no HTTP binding are already reported by
the plan; this module simply generates nothing for them, and the README names them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from .server_stub_plan import (
    Names,
    ServerStubPlan,
    StubField,
    StubFile,
    StubGroup,
    StubOperation,
    StubParameter,
    StubSchema,
    ValueShape,
    python_identifier,
    screaming_snake_case,
    shape_constraints,
    snake_case,
    wrap_text,
)
from .snippet_render import license_comment_block

__all__ = [
    "DEFAULT_PACKAGE_NAME",
    "FASTAPI_STUB_SCHEMA_VERSION",
    "VALIDATION_STATUS",
    "FastApiStubProject",
    "fastapi_package_name",
    "generate_fastapi_stub",
]

#: The addressable shape of the generated project, recorded in the kit manifest.
FASTAPI_STUB_SCHEMA_VERSION = "sdk.fastapi-stub.v1"

#: Package name used when nothing usable can be derived from the contract.
DEFAULT_PACKAGE_NAME = "api_server"

#: The status a contract violation is answered with.
#:
#: FastAPI's own default is ``422``. A design-first team almost always publishes ``400`` for "your
#: request did not match the contract" — that is what their own spec's error responses say — so the
#: generated project overrides it, and does so through a constant its README points at, because the
#: only thing worse than the wrong default is one a team cannot find.
VALIDATION_STATUS = 400

#: The scalar shapes and the Python type each is written as.
_SCALAR_PYTHON: Dict[str, str] = {
    "string": "str",
    "integer": "int",
    "number": "float",
    "boolean": "bool",
    "object": "Dict[str, Any]",
    "any": "Any",
}

#: pydantic ``Field`` keyword per shared constraint fact. A constraint with no keyword here is
#: dropped rather than approximated — the Express stub enforces the same set, and a rule only one
#: of the two stubs applied would make them disagree about what a valid request is.
_CONSTRAINT_KEYWORDS: Dict[str, str] = {
    "minimum": "ge",
    "maximum": "le",
    "exclusive_minimum": "gt",
    "exclusive_maximum": "lt",
    "multiple_of": "multiple_of",
    "min_length": "min_length",
    "max_length": "max_length",
    "min_items": "min_length",
    "max_items": "max_length",
    "pattern": "pattern",
}

#: The FastAPI parameter class per location.
_PARAM_CLASSES: Dict[str, str] = {
    "path": "Path",
    "query": "Query",
    "header": "Header",
    "cookie": "Cookie",
}


# ===========================================================================
# Result shape
# ===========================================================================


@dataclass(frozen=True)
class FastApiStubProject:
    """A complete generated FastAPI project.

    Attributes:
        package_name: The importable package the project's modules live in.
        files: Every generated file, ordered by path.
        routers: The router module stems, in plan order.
        handler_classes: The ``…Handlers`` protocol names, in plan order.
        model_classes: The generated model class names, in plan order.
        route_count: How many routes were registered.
    """

    package_name: str
    files: Tuple[StubFile, ...] = ()
    routers: Tuple[str, ...] = ()
    handler_classes: Tuple[str, ...] = ()
    model_classes: Tuple[str, ...] = ()
    route_count: int = 0

    def file_map(self) -> Dict[str, str]:
        """Return ``path → text`` for every file, for callers that stage an archive."""
        return {item.path: item.text for item in self.files}


def fastapi_package_name(*candidates: Optional[str]) -> str:
    """Derive the generated project's Python package name from the first usable candidate.

    Args:
        *candidates: Names to try in order — typically the project slug, then the API title.

    Returns:
        A legal, lower-case package name ending in ``_server``, so an unpacked stub never shadows
        the client package a consumer may also have installed.
    """
    for candidate in candidates:
        stem = snake_case(candidate or "", "")
        if stem and not stem[0].isdigit():
            base = python_identifier(stem, DEFAULT_PACKAGE_NAME)
            return base if base.endswith("_server") else f"{base}_server"
    return DEFAULT_PACKAGE_NAME


# ===========================================================================
# Source-text helpers
# ===========================================================================


def _py_string(value: str) -> str:
    """Render a Python string literal, escaping what Python requires escaped."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _py_literal(value: object) -> str:
    """Render a JSON-ish default as a Python literal.

    Args:
        value: The declared default.

    Returns:
        The literal. Anything the four JSON scalar families cannot express is rendered as its
        string form rather than guessed at, which keeps the generated module parseable whatever a
        contract put in a ``default``.
    """
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return _py_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_py_literal(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{_py_string(str(k))}: {_py_literal(v)}" for k, v in value.items()) + "}"
    return _py_string(str(value))


def _docstring(lines: Sequence[str], indent: str) -> List[str]:
    """Render a docstring, or nothing when there is nothing to say.

    A description that itself contains a triple quote would otherwise close the docstring from the
    inside and turn the rest of the module into syntax errors, so the sequence is neutralized
    rather than escaped — the text stays readable and the module stays parseable.

    Args:
        lines: The paragraphs, already split.
        indent: The indentation each rendered line carries.

    Returns:
        The rendered lines.
    """
    cleaned = [line.replace('"""', "'''").replace("\\", "\\\\").rstrip() for line in lines if line.strip()]
    if not cleaned:
        return []
    if len(cleaned) == 1 and len(indent) + len(cleaned[0]) < 96:
        return [f'{indent}"""{cleaned[0]}"""']
    wrapped: List[List[str]] = [wrap_text(paragraph, 100 - len(indent)) for paragraph in cleaned]
    body = [f'{indent}"""{wrapped[0][0]}']
    body += [f"{indent}{line}" for line in wrapped[0][1:]]
    for paragraph in wrapped[1:]:
        body.append(f"{indent}")
        body += [f"{indent}{line}" for line in paragraph]
    body.append(f'{indent}"""')
    return [line.rstrip() for line in body]


def _paragraphs(*values: Optional[str]) -> List[str]:
    """Flatten prose values into non-empty, single-line paragraphs, in order, without repeats."""
    found: List[str] = []
    for value in values:
        for chunk in (value or "").replace("\r\n", "\n").split("\n\n"):
            text = " ".join(chunk.split())
            if text and text not in found:
                found.append(text)
    return found


def _module(header: Sequence[str], imports: Sequence[str], body: Sequence[str], license_block: Optional[str]) -> str:
    """Assemble one Python module: licence comment, docstring, imports, body."""
    lines: List[str] = []
    if license_block:
        lines += license_block.split("\n") + [""]
    lines += ["# Code generated by Apiome. DO NOT EDIT — implement the handler classes instead.", ""]
    lines += list(header)
    if header:
        lines.append("")
    lines.append("from __future__ import annotations")
    lines.append("")
    if imports:
        lines += list(imports)
        # Two blank lines, because what follows an import block in this generator is always a
        # top-level declaration and PEP 8 wants the gap a reader expects to see there.
        lines += ["", ""]
    lines += list(body)
    text = "\n".join(lines).rstrip("\n")
    return text + "\n"


# ===========================================================================
# Types
# ===========================================================================


class _PythonTypes:
    """Renders a :class:`~app.server_stub_plan.ValueShape` as a Python type expression.

    Named types are rendered by class name, which is why this needs the plan: a ``ref`` shape
    carries a canonical key, not a spelling.
    """

    def __init__(self, plan: ServerStubPlan) -> None:
        """Index the plan's schemas by key."""
        self._classes = {schema.key: schema.class_name for schema in plan.schemas}
        self._kinds = {schema.key: schema.kind for schema in plan.schemas}

    def render(self, shape: Optional[ValueShape], *, quote_refs: bool = False) -> str:
        """Return the Python type expression for ``shape``.

        Args:
            shape: The shape, or ``None`` (which is ``None`` the type).
            quote_refs: Whether a named reference is written as a forward reference. Module-level
                type aliases are evaluated eagerly, so an alias that names a class declared later
                has to quote it; an annotation never needs to, because
                ``from __future__ import annotations`` makes every annotation a string already.

        Returns:
            The type expression.
        """
        if shape is None:
            return "None"
        if shape.kind == "ref" and shape.ref:
            name = self._classes.get(shape.ref)
            if name is None:
                return "Any"
            return f'"{name}"' if quote_refs else name
        if shape.kind == "array":
            return f"List[{self.render(shape.item, quote_refs=quote_refs)}]"
        if shape.kind == "map":
            return f"Dict[str, {self.render(shape.item, quote_refs=quote_refs)}]"
        if shape.kind == "union":
            members = [self.render(member, quote_refs=quote_refs) for member in shape.members]
            unique = list(dict.fromkeys(members))
            if not unique:
                return "Any"
            return unique[0] if len(unique) == 1 else "Union[" + ", ".join(unique) + "]"
        return _SCALAR_PYTHON.get(shape.kind, "Any")

    def annotation(self, shape: Optional[ValueShape], *, optional: bool) -> str:
        """Return the annotation for a member or argument, wrapped in ``Optional`` when it may be absent."""
        rendered = self.render(shape)
        if not optional or rendered == "Any":
            return rendered
        return f"Optional[{rendered}]"

    def imports_for(self, shape: Optional[ValueShape], into: Set[str]) -> None:
        """Record which ``typing`` names and model classes ``shape`` needs, into ``into``."""
        if shape is None:
            return
        if shape.kind == "ref" and shape.ref:
            name = self._classes.get(shape.ref)
            if name:
                into.add(name)
            else:
                into.add("Any")
            return
        if shape.kind == "array":
            into.add("List")
            self.imports_for(shape.item, into)
            return
        if shape.kind == "map":
            into.update({"Dict", "str"})
            self.imports_for(shape.item, into)
            return
        if shape.kind == "union":
            into.add("Union")
            for member in shape.members:
                self.imports_for(member, into)
            return
        rendered = _SCALAR_PYTHON.get(shape.kind, "Any")
        if rendered.startswith("Dict"):
            into.update({"Dict", "Any"})
        elif rendered == "Any":
            into.add("Any")

    def is_model(self, shape: Optional[ValueShape]) -> bool:
        """Whether ``shape`` names a generated record class (and so can be a ``response_model``)."""
        return bool(shape and shape.kind == "ref" and self._kinds.get(shape.ref or "") == "record")


def _field_constraints(shape: ValueShape) -> Dict[str, object]:
    """Return the pydantic ``Field`` keywords one shape's constraints justify.

    Which constraints apply, and how their values are spelled, is decided once in
    :func:`app.server_stub_plan.shape_constraints`; only the keyword names are pydantic's.
    """
    return {
        _CONSTRAINT_KEYWORDS[name]: value for name, value in shape_constraints(shape).items()
    }


# ===========================================================================
# models.py
# ===========================================================================


def _render_enum(schema: StubSchema) -> List[str]:
    """Render an ``ENUM`` schema as a Python enum, or as an alias when its values are mixed."""
    if schema.enum_value_kind == "mixed" or not schema.enum_members:
        return [
            f"#: {schema.source_name} — the contract's members have no single underlying type, so "
            "the generated",
            "#: model accepts any value rather than rejecting members it could not represent.",
            f"{schema.class_name} = Any",
            "",
        ]
    base = "str" if schema.enum_value_kind == "string" else "int"
    lines = [f"class {schema.class_name}({base}, Enum):"]
    lines += _docstring(_paragraphs(schema.description) or [f"``{schema.source_name}``."], "    ")
    members = Names({"name", "value"})
    for member_name, value in schema.enum_members:
        constant = members.take(screaming_snake_case(member_name, "MEMBER"))
        lines.append(f"    {constant} = {_py_literal(value)}")
    lines.append("")
    lines.append("")
    return lines


def _render_field(field_: StubField, types: _PythonTypes) -> List[str]:
    """Render one pydantic model field."""
    annotation = types.annotation(field_.shape, optional=not field_.required)
    keywords: List[str] = []
    if field_.wire_name != field_.py_name:
        keywords.append(f"alias={_py_string(field_.wire_name)}")
    for keyword_name, value in _field_constraints(field_.shape).items():
        keywords.append(f"{keyword_name}={_py_literal(value)}")
    if field_.description:
        keywords.append(f"description={_py_string(' '.join(field_.description.split()))}")
    if field_.deprecated:
        keywords.append("deprecated=True")

    if field_.required:
        default = "..."
    elif field_.default is not None:
        default = _py_literal(field_.default)
    else:
        default = "None"

    if not keywords:
        # A required field is declared with no default at all rather than with ``= ...``: both mean
        # "required" to pydantic, but only one of them reads as Python.
        return [f"    {field_.py_name}: {annotation}"] if field_.required else [
            f"    {field_.py_name}: {annotation} = {default}"
        ]
    joined = ", ".join([f"default={default}" if default != "..." else "...", *keywords])
    rendered = f"    {field_.py_name}: {annotation} = Field({joined})"
    if len(rendered) <= 120:
        return [rendered]
    lines = [f"    {field_.py_name}: {annotation} = Field("]
    lines.append(f"        {'...' if default == '...' else f'default={default}'},")
    lines += [f"        {keyword}," for keyword in keywords]
    lines.append("    )")
    return lines


def _render_record(schema: StubSchema, types: _PythonTypes) -> List[str]:
    """Render a ``RECORD`` schema as a pydantic model."""
    lines = [f"class {schema.class_name}(BaseModel):"]
    prose = _paragraphs(schema.description) or [f"``{schema.source_name}``, as the contract declares it."]
    if schema.deprecated:
        prose.append("Deprecated by the contract.")
    lines += _docstring(prose, "    ")
    lines.append("")
    # ``populate_by_name`` lets a handler construct the model with the Python attribute names it
    # sees in its own signature; ``protected_namespaces`` is emptied because a contract is entitled
    # to a field called ``model_version`` and pydantic's warning about it is not actionable here.
    lines.append("    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())")
    lines.append("")
    if not schema.fields:
        lines.append("    # The contract declares no members for this type.")
    for member in schema.fields:
        lines += _render_field(member, types)
    lines.append("")
    lines.append("")
    return lines


def _alias_dependencies(schema: StubSchema) -> Set[str]:
    """Return the schema keys ``schema`` names *eagerly*, and so has to be declared after.

    Only a bare-reference alias (``Second = First``) and a union of bare references constrain
    ordering. A map or a list alias writes its reference as a quoted forward reference, which the
    model rebuild resolves whatever the order.
    """
    if schema.kind == "union":
        return {member.ref for member in schema.members if member.kind == "ref" and member.ref}
    target = schema.target
    if schema.kind == "alias" and target is not None and target.kind == "ref" and target.ref:
        return {target.ref}
    return set()


def _order_aliases(aliases: Sequence[StubSchema]) -> List[StubSchema]:
    """Order bare-reference aliases so none is evaluated before what it names.

    A module-level assignment is evaluated eagerly, so ``Pet = Animal`` needs ``Animal`` to exist
    already — unlike ``Pets = List["Animal"]``, whose reference is a forward reference the model
    rebuild resolves later. Only the bare-reference case constrains ordering, and it forms a
    simple chain graph; a cycle (``A = B`` beside ``B = A``) has no Python spelling at all, so the
    members of one keep declaration order and resolve to whatever the earlier name held.

    Args:
        aliases: The alias-like schemas, in declaration order.

    Returns:
        The same schemas, reordered.
    """
    by_key = {schema.key: schema for schema in aliases}
    ordered: List[StubSchema] = []
    placed: Set[str] = set()
    visiting: Set[str] = set()

    def place(schema: StubSchema) -> None:
        if schema.key in placed or schema.key in visiting:
            return
        visiting.add(schema.key)
        for dependency in sorted(_alias_dependencies(schema)):
            target = by_key.get(dependency)
            if target is not None:
                place(target)
        visiting.discard(schema.key)
        placed.add(schema.key)
        ordered.append(schema)

    for schema in aliases:
        place(schema)
    return ordered


def _render_alias(schema: StubSchema, types: _PythonTypes) -> List[str]:
    """Render a non-record, non-enum schema as a module-level type alias."""
    if schema.kind == "union":
        members = [types.render(member, quote_refs=True) for member in schema.members]
        unique = list(dict.fromkeys(members))
        if not unique:
            rendered = "Any"
        elif len(unique) == 1:
            rendered = unique[0]
        else:
            rendered = "Union[" + ", ".join(unique) + "]"
    elif schema.kind == "map":
        # A MAP schema's ``target`` is its *value* shape; the dictionary around it is the schema.
        rendered = f"Dict[str, {types.render(schema.target, quote_refs=True)}]"
    else:
        rendered = types.render(schema.target, quote_refs=True)
    lines: List[str] = []
    for line in _paragraphs(schema.description) or [f"``{schema.source_name}``."]:
        lines.append(f"#: {line}")
    # A bare forward reference is a string, not a type, so an alias that would be nothing but a
    # quoted name is written unquoted — `_order_aliases` has already guaranteed it resolves.
    if rendered.startswith('"') and rendered.endswith('"'):
        rendered = rendered[1:-1]
    lines.append(f"{schema.class_name} = {rendered}")
    lines.append("")
    return lines


def _render_models(plan: ServerStubPlan, types: _PythonTypes, license_block: Optional[str]) -> StubFile:
    """Render ``models.py``: every named type the contract declares."""
    records = [schema for schema in plan.schemas if schema.kind == "record"]
    enums = [schema for schema in plan.schemas if schema.kind == "enum"]
    aliases = _order_aliases([schema for schema in plan.schemas if schema.kind not in {"record", "enum"}])

    needed: Set[str] = set()
    for schema in plan.schemas:
        if schema.kind == "record":
            for member in schema.fields:
                types.imports_for(member.shape, needed)
                if not member.required:
                    needed.add("Optional")
        elif schema.kind == "union":
            for member in schema.members:
                types.imports_for(member, needed)
            if len(schema.members) > 1:
                needed.add("Union")
        elif schema.kind == "map":
            needed.add("Dict")
            types.imports_for(schema.target, needed)
        elif schema.kind != "enum":
            types.imports_for(schema.target, needed)
        elif schema.enum_value_kind == "mixed" or not schema.enum_members:
            needed.add("Any")

    typing_names = sorted(needed & {"Any", "Dict", "List", "Optional", "Union"})
    imports: List[str] = []
    if enums:
        imports.append("from enum import Enum")
    if typing_names:
        imports.append("from typing import " + ", ".join(typing_names))
    imports.append("")
    imports.append("from pydantic import BaseModel, ConfigDict, Field")

    body: List[str] = []
    for schema in enums:
        body += _render_enum(schema)
    for schema in records:
        body += _render_record(schema, types)
    for schema in aliases:
        body += _render_alias(schema, types)

    if records:
        body += [
            "",
            "# A contract may describe itself recursively (a comment whose replies are comments), and",
            "# every annotation in this module is a string. Rebuilding once, here, is what resolves",
            "# those references before the first request rather than failing on it.",
            "for _model in (",
        ]
        body += [f"    {schema.class_name}," for schema in records]
        body += [
            "):",
            "    _model.model_rebuild(raise_errors=False)",
            "",
        ]

    header = _docstring(
        [
            "Models generated from the contract's schemas.",
            "Every model accepts both its wire name and its Python attribute name, so a handler "
            "can construct one the way its own signature reads.",
        ],
        "",
    )
    return StubFile(path="models.py", text=_module(header, imports, body, license_block))


# ===========================================================================
# errors.py
# ===========================================================================


_ERRORS_BODY = '''class OperationNotImplemented(Exception):
    """Raised by a generated handler stub that nobody has implemented yet.

    Attributes:
        operation_id: The contract's id for the operation.
        method: The operation's HTTP verb.
        path: The operation's path template.
    """

    def __init__(self, operation_id: str, method: str, path: str) -> None:
        """Record which operation is missing, for the 501 body."""
        super().__init__(f"{method} {path} ({operation_id}) is not implemented")
        self.operation_id = operation_id
        self.method = method
        self.path = path


def problem(
    status: int,
    title: str,
    detail: str,
    *,
    errors: Optional[List[Dict[str, Any]]] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build an RFC 9457 problem document.

    Args:
        status: The HTTP status the response carries.
        title: A short, stable summary of the problem type.
        detail: What went wrong with *this* request.
        errors: Per-field failures, when the problem is a validation failure.
        extra: Any further members to include.

    Returns:
        The problem document, ready to serialize.
    """
    document: Dict[str, Any] = {
        "type": f"{PROBLEM_TYPE_PREFIX}/{title.lower().replace(' ', '-')}",
        "title": title,
        "status": status,
        "detail": detail,
    }
    if errors:
        document["errors"] = errors
    if extra:
        document.update(extra)
    return document


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Answer a contract violation with a structured problem document.

    FastAPI's own handler answers 422 with its own envelope. This one answers
    :data:`VALIDATION_STATUS` with ``application/problem+json`` and one ``errors`` entry per
    failure, naming the location (``path``/``query``/``header``/``cookie``/``body``) and the
    field, so a client can correct the request without reading the spec.

    Args:
        request: The offending request.
        exc: The validation error FastAPI raised.

    Returns:
        The problem response.
    """
    raw = exc.errors() if isinstance(exc, RequestValidationError) else []
    errors: List[Dict[str, Any]] = []
    for entry in raw:
        location = list(entry.get("loc") or ())
        where = str(location[0]) if location else "body"
        pointer = ".".join(str(part) for part in location[1:]) or where
        errors.append(
            {
                "location": where,
                "field": pointer,
                "message": str(entry.get("msg") or "is invalid"),
                "type": str(entry.get("type") or "invalid"),
            }
        )
    document = problem(
        VALIDATION_STATUS,
        "Request does not match the contract",
        f"{len(errors)} field(s) did not satisfy the published contract."
        if errors
        else "The request did not satisfy the published contract.",
        errors=errors,
    )
    return JSONResponse(
        status_code=VALIDATION_STATUS, content=document, media_type=PROBLEM_MEDIA_TYPE
    )


async def not_implemented_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Answer 501 for an operation whose handler is still the generated stub.

    Args:
        request: The request that reached an unimplemented operation.
        exc: The :class:`OperationNotImplemented` that was raised.

    Returns:
        The problem response, naming the operation so the reader knows what to implement.
    """
    operation_id = getattr(exc, "operation_id", "unknown")
    method = getattr(exc, "method", request.method)
    path = getattr(exc, "path", request.url.path)
    document = problem(
        501,
        "Not implemented",
        f"{method} {path} is declared by the contract but has no implementation yet.",
        extra={"operationId": operation_id},
    )
    return JSONResponse(status_code=501, content=document, media_type=PROBLEM_MEDIA_TYPE)
'''


def _render_errors(plan: ServerStubPlan, license_block: Optional[str]) -> StubFile:
    """Render ``errors.py``: the 501 signal and the two problem-document handlers."""
    header = _docstring(
        [
            "The project's error vocabulary: one exception for an unimplemented operation, and the "
            "two handlers that turn it and a contract violation into RFC 9457 problem documents.",
            "Change VALIDATION_STATUS if your contract publishes 422 rather than 400 for a "
            "malformed request.",
        ],
        "",
    )
    imports = [
        "from typing import Any, Dict, List, Optional",
        "",
        "from fastapi import Request",
        "from fastapi.exceptions import RequestValidationError",
        "from fastapi.responses import JSONResponse",
    ]
    body = [
        "#: The media type a problem document is served as (RFC 9457).",
        'PROBLEM_MEDIA_TYPE = "application/problem+json"',
        "",
        "#: The ``type`` URI prefix problem documents are minted under.",
        f"PROBLEM_TYPE_PREFIX = {_py_string('https://apiome.dev/problems')}",
        "",
        "#: The status a request that violates the contract is answered with. FastAPI defaults to",
        "#: 422; most published contracts say 400. One line to change it.",
        f"VALIDATION_STATUS = {VALIDATION_STATUS}",
        "",
        "",
    ]
    body += _ERRORS_BODY.split("\n")
    return StubFile(path="errors.py", text=_module(header, imports, body, license_block))


# ===========================================================================
# handlers.py
# ===========================================================================


def _handler_signature(operation: StubOperation, types: _PythonTypes, indent: str) -> List[str]:
    """Render one handler method's ``async def`` line(s), keyword-only throughout.

    Every input is keyword-only so a later contract change that adds a parameter can never
    silently rebind an existing implementation's positional argument.
    """
    arguments: List[str] = []
    for param in operation.parameters:
        annotation = types.annotation(param.shape, optional=not param.required)
        if param.required:
            arguments.append(f"{param.py_name}: {annotation}")
        else:
            default = _py_literal(param.default) if param.default is not None else "None"
            arguments.append(f"{param.py_name}: {annotation} = {default}")
    if operation.body is not None:
        annotation = _body_annotation(operation, types)
        arguments.append(
            f"body: {annotation}" if operation.body.required else f"body: Optional[{annotation}] = None"
        )
    returns = types.render(operation.success.shape) if operation.success.shape is not None else "None"

    if not arguments:
        return [f"{indent}async def {operation.py_name}(self) -> {returns}:"]
    single = f"{indent}async def {operation.py_name}(self, *, " + ", ".join(arguments) + f") -> {returns}:"
    if len(single) <= 120:
        return [single]
    lines = [f"{indent}async def {operation.py_name}(", f"{indent}    self,", f"{indent}    *,"]
    lines += [f"{indent}    {argument}," for argument in arguments]
    lines.append(f"{indent}) -> {returns}:")
    return lines


def _body_annotation(operation: StubOperation, types: _PythonTypes) -> str:
    """The annotation a request body is declared with.

    A non-JSON body is ``bytes``: the contract declared a media type this generator will not
    pretend to parse, and handing a handler the raw bytes is the only honest typing for it.
    """
    if operation.body is None:
        return "None"
    if not operation.body.is_json:
        return "bytes"
    return types.render(operation.body.shape)


def _operation_prose(operation: StubOperation) -> List[str]:
    """The paragraphs a generated handler or route documents an operation with."""
    summary = (operation.summary or "").strip()
    if summary and summary[-1] not in ".!?":
        summary += "."
    prose = _paragraphs(summary, operation.description)
    if not prose:
        prose = [f"``{operation.http_method} {operation.path_template}``."]
    else:
        prose.insert(1, f"``{operation.http_method} {operation.path_template}`` ({operation.operation_id}).")
    if operation.deprecated:
        prose.append("Deprecated by the contract.")
    if operation.security_schemes:
        prose.append(
            "The contract requires authentication for this operation ("
            + ", ".join(f"``{scheme}``" for scheme in operation.security_schemes)
            + "); enforcing it is your implementation's responsibility."
        )
    return prose


def _render_handlers(
    plan: ServerStubPlan, types: _PythonTypes, license_block: Optional[str]
) -> Tuple[StubFile, List[str]]:
    """Render ``handlers.py``: one typed protocol per group plus its 501-answering base.

    Returns:
        ``(file, protocol names)``.
    """
    needed: Set[str] = set()
    models: Set[str] = set()
    for operation in plan.operations:
        for param in operation.parameters:
            types.imports_for(param.shape, models)
            if not param.required:
                needed.add("Optional")
        if operation.body is not None:
            if operation.body.is_json:
                types.imports_for(operation.body.shape, models)
            if not operation.body.required:
                needed.add("Optional")
        types.imports_for(operation.success.shape, models)
    needed |= models & {"Any", "Dict", "List", "Optional", "Union"}
    model_names = sorted(models - {"Any", "Dict", "List", "Optional", "Union", "str"})

    imports = ["from typing import " + ", ".join(sorted(needed | {"Protocol"}))]
    imports.append("")
    imports.append("from .errors import OperationNotImplemented")
    if model_names:
        imports.append("from .models import " + ", ".join(model_names))

    body: List[str] = []
    protocols: List[str] = []
    for group in plan.groups:
        protocol = group.handler_class
        protocols.append(protocol)
        body.append(f"class {protocol}(Protocol):")
        body += _docstring(
            _paragraphs(
                f"Every operation the contract groups under ``{group.name}``.",
                group.description,
                f"Implement this protocol — or subclass ``{group.stub_class}`` — and pass it to "
                "``create_app``.",
            ),
            "    ",
        )
        body.append("")
        for operation in group.operations:
            body += _handler_signature(operation, types, "    ")
            body += _docstring(_operation_prose(operation), "        ")
            body.append("        ...")
            body.append("")
        body.append("")

        body.append(f"class {group.stub_class}:")
        body += _docstring(
            [
                f"A ``{protocol}`` whose every operation answers 501 until it is overridden.",
                "Subclass this and override the methods you have implemented; anything you have "
                "not is still routed, still validated, and still answers 501.",
            ],
            "    ",
        )
        body.append("")
        for operation in group.operations:
            body += _handler_signature(operation, types, "    ")
            body += _docstring([f"Answer 501 for ``{operation.operation_id}``."], "        ")
            body.append(
                f"        raise OperationNotImplemented("
                f"{_py_string(operation.operation_id)}, "
                f"{_py_string(operation.http_method)}, "
                f"{_py_string(operation.path_template)})"
            )
            body.append("")
        body.append("")

    if not plan.groups:
        body += [
            "# The contract declares no HTTP operations, so there is nothing to implement.",
            "",
        ]

    header = _docstring(
        [
            "The typed handler interfaces this project is built around.",
            "One Protocol per contract group states the signature of every operation in it; the "
            "matching NotImplemented… class answers 501 for all of them. Implementing an operation "
            "with a signature the contract does not describe is a type error.",
        ],
        "",
    )
    return StubFile(path="handlers.py", text=_module(header, imports, body, license_block)), protocols


# ===========================================================================
# routers/
# ===========================================================================


def _param_declaration(param: StubParameter, types: _PythonTypes) -> str:
    """Render one FastAPI route parameter, with its location class and metadata."""
    annotation = types.annotation(param.shape, optional=not param.required)
    klass = _PARAM_CLASSES.get(param.location, "Query")
    keywords: List[str] = []
    if param.wire_name != param.py_name:
        keywords.append(f"alias={_py_string(param.wire_name)}")
    for keyword_name, value in _field_constraints(param.shape).items():
        keywords.append(f"{keyword_name}={_py_literal(value)}")
    if param.shape.enum:
        # An enum the contract stated inline is documented rather than enforced: pydantic would
        # need a Literal type for that, and a Literal built from a contract's values is a type the
        # handler signature would also have to carry. The Express stub reports the same limitation.
        keywords.append(
            "description="
            + _py_string(
                (" ".join((param.description or "").split()) + " " if param.description else "")
                + "One of: "
                + ", ".join(str(value) for value in param.shape.enum)
            )
        )
    elif param.description:
        keywords.append(f"description={_py_string(' '.join(param.description.split()))}")
    if param.deprecated:
        keywords.append("deprecated=True")

    metadata = f"{klass}({', '.join(keywords)})"
    if param.required:
        return f"{param.py_name}: Annotated[{annotation}, {metadata}]"
    default = _py_literal(param.default) if param.default is not None else "None"
    return f"{param.py_name}: Annotated[{annotation}, {metadata}] = {default}"


def _render_route(operation: StubOperation, types: _PythonTypes) -> List[str]:
    """Render one route: its decorator, its validated signature, and its delegation."""
    decorator_args: List[str] = [f"        {_py_string(operation.path_template)},"]
    returns_body = operation.success.shape is not None
    if returns_body:
        decorator_args.append(f"        response_model={types.render(operation.success.shape)},")
    else:
        decorator_args.append("        response_class=Response,")
    decorator_args.append(f"        status_code={operation.success.status},")
    decorator_args.append(f"        operation_id={_py_string(operation.operation_id)},")
    if operation.summary:
        decorator_args.append(f"        summary={_py_string(' '.join(operation.summary.split()))},")
    if operation.deprecated:
        decorator_args.append("        deprecated=True,")
    if operation.errors:
        entries = ", ".join(
            f'{response.status}: {{"description": '
            f"{_py_string(' '.join((response.description or 'Error response.').split()))}}}"
            for response in operation.errors
        )
        decorator_args.append(f"        responses={{{entries}}},")

    lines = [f"    @router.{operation.http_method.lower()}("]
    lines += decorator_args
    lines.append("    )")

    arguments = [_param_declaration(param, types) for param in operation.parameters]
    if operation.body is not None:
        annotation = _body_annotation(operation, types)
        if operation.body.required:
            arguments.append(f"body: Annotated[{annotation}, Body()]")
        else:
            arguments.append(f"body: Annotated[Optional[{annotation}], Body()] = None")

    returns = types.render(operation.success.shape) if returns_body else "Response"
    if arguments:
        lines.append(f"    async def {operation.py_name}(")
        # Keyword-only, for the same reason the handler protocol is — and for one more: Python
        # rejects a parameter without a default after one with a default, so a contract that
        # declares an optional query parameter before a required header would otherwise emit a
        # route that will not parse. FastAPI resolves a route's arguments by name, so making them
        # keyword-only costs nothing and lets declaration order be preserved exactly.
        lines.append("        *,")
        lines += [f"        {argument}," for argument in arguments]
        lines.append(f"    ) -> {returns}:")
    else:
        lines.append(f"    async def {operation.py_name}() -> {returns}:")
    lines += _docstring(_operation_prose(operation), "        ")

    call_args = [f"{param.py_name}={param.py_name}" for param in operation.parameters]
    if operation.body is not None:
        call_args.append("body=body")
    call = f"handlers.{operation.py_name}(" + (", ".join(call_args) if call_args else "") + ")"
    if returns_body:
        statement = f"        return await {call}"
    else:
        statement = f"        await {call}"
    if len(statement) <= 120:
        lines.append(statement)
    else:
        prefix = "        return await handlers." if returns_body else "        await handlers."
        lines.append(f"{prefix}{operation.py_name}(")
        lines += [f"            {argument}," for argument in call_args]
        lines.append("        )")
    if not returns_body:
        lines.append(f"        return Response(status_code={operation.success.status})")
    lines.append("")
    return lines


def _render_router(group: StubGroup, types: _PythonTypes, license_block: Optional[str]) -> StubFile:
    """Render one ``routers/<group>.py``: an ``APIRouter`` factory over the group's handlers."""
    needed: Set[str] = {"Annotated"}
    models: Set[str] = set()
    uses_body = False
    param_classes: Set[str] = set()
    optional_seen = False
    for operation in group.operations:
        for param in operation.parameters:
            types.imports_for(param.shape, models)
            param_classes.add(_PARAM_CLASSES.get(param.location, "Query"))
            if not param.required:
                optional_seen = True
        if operation.body is not None:
            uses_body = True
            if operation.body.is_json:
                types.imports_for(operation.body.shape, models)
            if not operation.body.required:
                optional_seen = True
        types.imports_for(operation.success.shape, models)
    if optional_seen:
        needed.add("Optional")
    needed |= models & {"Any", "Dict", "List", "Optional", "Union"}
    model_names = sorted(models - {"Any", "Dict", "List", "Optional", "Union", "str"})

    fastapi_names = sorted({"APIRouter", "Response", *param_classes} | ({"Body"} if uses_body else set()))
    imports = ["from typing import " + ", ".join(sorted(needed))]
    imports.append("")
    imports.append("from fastapi import " + ", ".join(fastapi_names))
    imports.append("")
    imports.append(f"from ..handlers import {group.handler_class}")
    if model_names:
        imports.append("from ..models import " + ", ".join(model_names))

    body = [f"def build_router(handlers: {group.handler_class}) -> APIRouter:"]
    body += _docstring(
        [
            f"Register every ``{group.name}`` operation against ``handlers``.",
            "The routes below are the contract: FastAPI validates each request against these "
            "signatures before your handler is called, so a handler only ever sees input the "
            "contract permits.",
        ],
        "    ",
    )
    body.append("")
    body.append(f"    router = APIRouter(tags=[{_py_string(group.name)}])")
    body.append("")
    for operation in group.operations:
        body += _render_route(operation, types)
    body.append("    return router")

    header = _docstring([f"Routes for the contract's ``{group.name}`` operations."], "")
    return StubFile(path=f"routers/{group.module}.py", text=_module(header, imports, body, license_block))


# ===========================================================================
# app.py, main.py, packaging
# ===========================================================================


def _render_app(plan: ServerStubPlan, license_block: Optional[str]) -> StubFile:
    """Render ``app.py``: the application factory that wires routers to handlers."""
    imports = [
        "from typing import Optional",
        "",
        "from fastapi import FastAPI",
        "from fastapi.exceptions import RequestValidationError",
        "",
    ]
    imports.append(
        "from .errors import ("
        "\n    OperationNotImplemented,"
        "\n    not_implemented_exception_handler,"
        "\n    validation_exception_handler,"
        "\n)"
    )
    handler_imports: List[str] = []
    for group in plan.groups:
        handler_imports.append(group.handler_class)
        handler_imports.append(group.stub_class)
    if handler_imports:
        imports.append("from .handlers import " + ", ".join(sorted(handler_imports)))
    for group in plan.groups:
        imports.append(f"from .routers import {group.module} as {group.module}_routes")

    arguments = [
        f"    {group.module}: Optional[{group.handler_class}] = None," for group in plan.groups
    ]
    body: List[str] = [
        "#: The path prefix the contract's server publishes the API under.",
        f"BASE_PATH = {_py_string(plan.base_path)}",
        "",
        "",
        "def create_app(",
    ]
    if arguments:
        body.append("    *,")
        body += arguments
    body.append(") -> FastAPI:")
    prose = [
        f"Build the {plan.title} application.",
        "Pass an implementation per group to serve it; anything left unset is routed and validated "
        "exactly the same way and answers 501, so the server is runnable from the first minute.",
    ]
    if plan.base_path:
        prose.append(f"Every route is mounted under ``{plan.base_path}``, as the contract's server declares.")
    body += _docstring(prose, "    ")
    body.append("")
    body.append("    app = FastAPI(")
    body.append(f"        title={_py_string(plan.title)},")
    if plan.version:
        body.append(f"        version={_py_string(plan.version)},")
    if plan.description:
        body.append(f"        description={_py_string(' '.join(plan.description.split()))},")
    body.append("    )")
    body.append("    app.add_exception_handler(RequestValidationError, validation_exception_handler)")
    body.append("    app.add_exception_handler(OperationNotImplemented, not_implemented_exception_handler)")
    body.append("")
    for group in plan.groups:
        body.append(
            f"    app.include_router("
            f"{group.module}_routes.build_router({group.module} or {group.stub_class}()), "
            f"prefix=BASE_PATH)"
        )
    if not plan.groups:
        body.append("    # The contract declares no HTTP operations, so no router is mounted.")
    body.append("    return app")

    header = _docstring(
        [
            "The application factory.",
            "``create_app()`` with no arguments is a complete, runnable server: every route "
            "registered, every request validated, every operation answering 501.",
        ],
        "",
    )
    return StubFile(path="app.py", text=_module(header, imports, body, license_block))


def _render_main(plan: ServerStubPlan, package: str, license_block: Optional[str]) -> StubFile:
    """Render ``main.py``: the ASGI entry point and a ``python -m`` runner."""
    imports = ["from .app import create_app"]
    body = [
        "#: The ASGI application. ``uvicorn " + package + ".main:app`` serves it.",
        "app = create_app()",
        "",
        "",
        'if __name__ == "__main__":',
        "    import uvicorn",
        "",
        '    uvicorn.run(app, host="127.0.0.1", port=8000)',
    ]
    header = _docstring(
        [f"Entry point for the generated {plan.title} server.", f"Run it with ``python -m {package}.main``."],
        "",
    )
    return StubFile(path="main.py", text=_module(header, imports, body, license_block))


def _render_init(plan: ServerStubPlan, license_block: Optional[str]) -> StubFile:
    """Render the package ``__init__.py``, re-exporting the factory and the handler bases."""
    exports = ["create_app"]
    imports = ["from .app import create_app"]
    if plan.groups:
        names = []
        for group in plan.groups:
            names += [group.handler_class, group.stub_class]
        imports.append("from .handlers import " + ", ".join(sorted(names)))
        exports += sorted(names)
    body = ["__all__ = ["]
    body += [f"    {_py_string(name)}," for name in exports]
    body.append("]")
    header = _docstring([f"{plan.title} — a generated FastAPI server stub."], "")
    return StubFile(path="__init__.py", text=_module(header, imports, body, license_block))


def _render_pyproject(plan: ServerStubPlan, package: str) -> StubFile:
    """Render ``pyproject.toml`` for the generated project."""
    lines = [
        "[build-system]",
        'requires = ["setuptools>=68"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[project]",
        f'name = "{package.replace("_", "-")}"',
        f'version = "{plan.version or "0.1.0"}"',
        f'description = "Generated FastAPI server stub for {plan.title}."',
        'requires-python = ">=3.9"',
        "dependencies = [",
        '    "fastapi>=0.110",',
        '    "pydantic>=2.6",',
        '    "uvicorn[standard]>=0.27",',
        "]",
        "",
        "[tool.setuptools.packages.find]",
        'include = ["' + package + '*"]',
        "",
    ]
    return StubFile(path="pyproject.toml", text="\n".join(lines))


def _render_readme(plan: ServerStubPlan, package: str, license_header: Optional[str]) -> StubFile:
    """Render the project's ``README.md``: how to run it, and what to implement."""
    lines = [
        f"# {plan.title} — FastAPI server stub",
        "",
        "A runnable FastAPI skeleton generated from the published contract. Every operation is "
        "routed and validated; none is implemented.",
        "",
    ]
    if plan.description:
        lines += [" ".join(plan.description.split()), ""]
    if license_header:
        lines += ["## Licence", "", "```", license_header.strip(), "```", ""]
    lines += [
        "## Run it",
        "",
        "```bash",
        "python -m venv .venv && . .venv/bin/activate",
        "pip install -e .",
        f"uvicorn {package}.main:app --reload",
        "```",
        "",
        "Every route answers `501 Not Implemented` with a problem document naming the operation. "
        "Interactive docs are at `/docs`.",
        "",
        "## Implement an operation",
        "",
    ]
    if plan.groups:
        group = plan.groups[0]
        operation = group.operations[0]
        lines += [
            "```python",
            f"from {package} import {group.stub_class}, create_app",
            "",
            "",
            f"class {group.class_prefix}Service({group.stub_class}):",
            f"    async def {operation.py_name}(self, *args, **kwargs):",
            "        ...  # your implementation",
            "",
            "",
            f"app = create_app({group.module}={group.class_prefix}Service())",
            "```",
            "",
            f"Copy the exact signature from `{package}/handlers.py` — the arguments are keyword-only "
            "and typed from the contract, so an implementation that does not match is a type error "
            "under `mypy`, not a 500 in production.",
            "",
        ]
    else:
        lines += ["This contract declares no HTTP operations, so there is nothing to implement.", ""]

    lines += [
        "## Request validation",
        "",
        f"A request that violates the contract is rejected with **{VALIDATION_STATUS}** and an RFC 9457 "
        "`application/problem+json` body before any handler runs:",
        "",
        "```json",
        "{",
        '  "type": "https://apiome.dev/problems/request-does-not-match-the-contract",',
        '  "title": "Request does not match the contract",',
        f'  "status": {VALIDATION_STATUS},',
        '  "detail": "1 field(s) did not satisfy the published contract.",',
        '  "errors": [',
        '    { "location": "query", "field": "limit", "message": "Input should be a valid integer", '
        '"type": "int_parsing" }',
        "  ]",
        "}",
        "```",
        "",
        f"Change `VALIDATION_STATUS` in `{package}/errors.py` if your contract publishes 422 instead.",
        "",
        "## What is generated",
        "",
        f"- `{package}/models.py` — {len(plan.schemas)} pydantic model(s) from the contract's schemas.",
        f"- `{package}/handlers.py` — one typed `Protocol` per group, plus a 501-answering base.",
        f"- `{package}/routers/` — one `APIRouter` factory per group ({len(plan.operations)} route(s)).",
        f"- `{package}/errors.py` — the problem-document handlers.",
        f"- `{package}/app.py` — `create_app()`, wiring routers to handlers.",
        "",
    ]
    if plan.skipped:
        lines += [
            "## Not generated",
            "",
            "These operations have no HTTP binding, so no route exists for them:",
            "",
        ]
        lines += [f"- `{item.key}` — {item.reason}" for item in plan.skipped]
        lines.append("")
    lines += [
        "## Known limits",
        "",
        "- Undeclared properties are accepted, matching OpenAPI's default. Add "
        "`extra=\"forbid\"` to a model's `model_config` to reject them.",
        "- An enum a contract states inline on a parameter is documented in the OpenAPI docs but not "
        "enforced; an enum declared as a named schema is a real Python enum and is enforced.",
        "- Authentication is documented per operation, never generated: a stub that invented an auth "
        "check would be asserting a policy the contract did not state.",
        "",
        f"Generated by Apiome · `{FASTAPI_STUB_SCHEMA_VERSION}`.",
        "",
    ]
    return StubFile(path="README.md", text="\n".join(lines))


# ===========================================================================
# Entry point
# ===========================================================================


def generate_fastapi_stub(
    plan: ServerStubPlan,
    *,
    package_name: Optional[str] = None,
    license_header: Optional[str] = None,
) -> FastApiStubProject:
    """Generate a complete FastAPI server stub project from a plan.

    The result is a pure function of its arguments: nothing here reads the clock, the environment
    or the filesystem, so two calls with the same plan and the same branding produce byte-identical
    files.

    Args:
        plan: The resolved plan (see :func:`app.server_stub_plan.build_server_stub_plan`).
        package_name: The Python package the generated modules live in. Defaults to the API's
            title, suffixed ``_server``.
        license_header: A tenant's resolved licence text (SDK-3.4), rendered as a comment block at
            the top of every generated module and quoted in the README.

    Returns:
        The :class:`FastApiStubProject`.
    """
    package = fastapi_package_name(package_name, plan.title)
    license_block = license_comment_block(license_header, "python")
    types = _PythonTypes(plan)

    files: List[StubFile] = [
        _render_init(plan, license_block),
        _render_models(plan, types, license_block),
        _render_errors(plan, license_block),
    ]
    handlers_file, protocols = _render_handlers(plan, types, license_block)
    files.append(handlers_file)
    files.append(_render_app(plan, license_block))
    files.append(_render_main(plan, package, license_block))

    routers: List[str] = []
    for group in plan.groups:
        files.append(_render_router(group, types, license_block))
        routers.append(group.module)
    if plan.groups:
        router_init = _module(
            _docstring(["One router module per contract group."], ""),
            [],
            ["__all__ = ["] + [f"    {_py_string(name)}," for name in routers] + ["]"],
            license_block,
        )
        files.append(StubFile(path="routers/__init__.py", text=router_init))

    # Every module above is a member of the package, so its path is rewritten once here rather
    # than spelled into each renderer — which is what keeps the package name a single decision.
    packaged = [StubFile(path=f"{package}/{item.path}", text=item.text) for item in files]
    packaged.append(_render_pyproject(plan, package))
    packaged.append(_render_readme(plan, package, license_header))
    packaged.sort(key=lambda item: item.path)

    return FastApiStubProject(
        package_name=package,
        files=tuple(packaged),
        routers=tuple(routers),
        handler_classes=tuple(protocols),
        model_classes=tuple(schema.class_name for schema in plan.schemas),
        route_count=len(plan.operations),
    )
