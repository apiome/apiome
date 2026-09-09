"""The language-neutral middle of the server stub generators — SDK-2.5 (#4490).

Two server stub generators ship under SDK-2.5: a FastAPI project
(:mod:`app.fastapi_stub_generator`) and an Express/TypeScript project
(:mod:`app.express_stub_generator`). They emit very different source text, but they answer the
*same* questions of the canonical model first — which operations have an HTTP binding, which
router each belongs to, what each path/query/header/cookie parameter is shaped like, what the
request body is, which status a success answers with, and which named types have to exist for any
of that to typecheck.

Asking those questions twice is how two generators drift. This module asks them once and hands
both renderers one plan, so a FastAPI router and an Express route registered for the same
operation validate the same fields, and a pydantic model and a TypeScript interface generated for
the same schema carry the same member names.

**What is deliberately *not* here.** Anything a renderer has to decide while writing source
text: comment syntax, import sets, how a type is spelled, which decorator carries a status code.
Identifier *legality* is the exception and lives here on purpose — this module owns the
allocators, and a keyword-escape applied afterwards could silently collide two members (a field
called ``from`` and a field called ``from_`` both becoming ``from_``) that the allocator would
have kept apart. So :func:`python_identifier` and :func:`typescript_identifier` run inside
allocation, not after it.

The *schema class name* is shared on purpose: :class:`StubSchema` carries a single ``class_name``
used by both languages, because "the ``Pet`` model" being called ``Pet`` in both stubs is a
property a design-first team notices immediately when it stops holding.

**Determinism.** Everything here walks declaration order and allocates names through
:class:`Names`, so a plan is a pure function of the model. Nothing reads the clock, the
environment or the filesystem — which is what lets the client kit keep serving a content-addressed
``ETag`` for a download that now carries two generated projects.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from .canonical_json_schema import CANONICAL_SCALAR_SCHEMAS
from .canonical_model import (
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    Parameter,
    ParameterLocation,
    Type,
    TypeKind,
    TypeRef,
)
from .snippet_render import pick_content_type, request_message, resolve_server_base

__all__ = [
    "DEFAULT_MAX_OPERATIONS",
    "IDENTIFIER_PATTERN",
    "MAX_SCHEMA_DEPTH",
    "Names",
    "SHAPE_ANY",
    "ServerStubPlan",
    "ServerStubSkip",
    "StubBody",
    "StubField",
    "StubFile",
    "StubGroup",
    "StubOperation",
    "StubParameter",
    "StubResponse",
    "StubSchema",
    "ValueShape",
    "build_server_stub_plan",
    "camel_case",
    "constraint_facts",
    "pascal_case",
    "python_identifier",
    "screaming_snake_case",
    "shape_constraints",
    "snake_case",
    "typescript_identifier",
    "words",
    "wrap_text",
]

#: How many HTTP operations a stub project carries before the rest are reported as skipped.
#:
#: Matched to the Go client generator's cap so one kit never carries a Go client for operations
#: its server stubs left out (or the reverse) — a consumer comparing the two would have no way to
#: tell a cap from a bug.
DEFAULT_MAX_OPERATIONS = 250

#: How deep the shape resolver follows an inline structure before it gives up and says ``any``.
#:
#: Named types are resolved by reference, so depth is only spent on anonymous nesting (a list of a
#: list of a map). A model that nests deeper than this is describing something no generated stub
#: could usefully type anyway, and stopping is what keeps a hostile or cyclic inline schema from
#: exhausting the stack on an anonymous request.
MAX_SCHEMA_DEPTH = 12

#: Word boundaries in a source name: separator runs, and the seam between a lower-case (or digit)
#: character and an upper-case one, so ``petId`` splits the same way ``pet_id`` does.
_WORD_SEPARATORS = re.compile(r"[^A-Za-z0-9]+")
_CAMEL_SEAM = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: A ``{name}`` placeholder in an HTTP path template.
_PATH_TOKEN = re.compile(r"\{([^{}]*)\}")

#: The JSON type each canonical scalar family validates as, keyed by the scalar's JSON Schema
#: projection rather than by a second spelling table: a scalar name a new import adapter starts
#: emitting is typed correctly the moment the fleet's shared vocabulary learns it.
_JSON_TYPE_TO_SHAPE: Dict[str, str] = {
    "string": "string",
    "integer": "integer",
    "number": "number",
    "boolean": "boolean",
    "array": "array",
    "object": "object",
}


# ===========================================================================
# Names
# ===========================================================================


def words(name: Optional[str]) -> List[str]:
    """Split a source name into its lower-cased words.

    Args:
        name: The source name, or ``None``.

    Returns:
        The words, without empties. ``pet_id``, ``pet-id`` and ``petId`` all yield
        ``["pet", "id"]``.
    """
    spaced = _CAMEL_SEAM.sub(" ", name or "")
    return [word.lower() for word in _WORD_SEPARATORS.sub(" ", spaced).split(" ") if word]


def pascal_case(name: Optional[str], fallback: str = "Value") -> str:
    """Derive a ``PascalCase`` identifier from a source name.

    Args:
        name: The source name.
        fallback: What to return when nothing usable survives.

    Returns:
        A ``PascalCase`` identifier, prefixed when it would otherwise start with a digit (no
        language this generator targets permits that).
    """
    identifier = "".join(part.capitalize() for part in words(name))
    if not identifier:
        return fallback
    return f"N{identifier}" if identifier[0].isdigit() else identifier


def camel_case(name: Optional[str], fallback: str = "value") -> str:
    """Derive a ``camelCase`` identifier from a source name.

    Args:
        name: The source name.
        fallback: What to return when nothing usable survives.

    Returns:
        A ``camelCase`` identifier, prefixed when it would otherwise start with a digit.
    """
    parts = words(name)
    if not parts:
        return fallback
    identifier = parts[0] + "".join(part.capitalize() for part in parts[1:])
    return f"n{identifier}" if identifier[0].isdigit() else identifier


def snake_case(name: Optional[str], fallback: str = "value") -> str:
    """Derive a ``snake_case`` identifier from a source name.

    Args:
        name: The source name.
        fallback: What to return when nothing usable survives.

    Returns:
        A ``snake_case`` identifier, prefixed when it would otherwise start with a digit.
    """
    parts = words(name)
    if not parts:
        return fallback
    identifier = "_".join(parts)
    return f"n_{identifier}" if identifier[0].isdigit() else identifier


def screaming_snake_case(name: Optional[str], fallback: str = "VALUE") -> str:
    """Derive a ``SCREAMING_SNAKE_CASE`` identifier (an enum member) from a source name."""
    parts = words(name)
    if not parts:
        return fallback
    identifier = "_".join(part.upper() for part in parts)
    return f"N_{identifier}" if identifier[0].isdigit() else identifier


#: Words Python will not accept as a name, plus the soft keywords, which are legal as identifiers
#: but read as syntax errors waiting to happen in generated code a human will edit.
_PYTHON_KEYWORDS = frozenset(keyword.kwlist) | frozenset(getattr(keyword, "softkwlist", ()))

#: The prefix pydantic v2 reserves on a model: a field called ``model_config`` would replace the
#: class's own configuration, and one called ``model_dump`` its serializer. Renaming is the only
#: fix that keeps both the field and the model working — ``protected_namespaces`` only silences
#: the warning for names that do not actually collide.
_PYDANTIC_RESERVED_PREFIX = "model_"

#: Names TypeScript will not accept for a *class member*. Property names in an object type may be
#: any string, and every TypeScript keyword is legal there, so this list is deliberately short:
#: only the two names a class body gives a meaning of its own.
_TYPESCRIPT_MEMBER_RESERVED = frozenset({"constructor", "prototype", "__proto__"})


def python_identifier(name: str, fallback: str = "value") -> str:
    """Make ``name`` legal and safe to declare in generated Python.

    Args:
        name: A ``snake_case`` candidate.
        fallback: What to return when nothing usable survives.

    Returns:
        The name, suffixed with ``_`` when it is a keyword (``from`` → ``from_``) and prefixed
        when it would collide with pydantic's reserved ``model_`` namespace.
    """
    identifier = name or fallback
    if identifier in _PYTHON_KEYWORDS:
        return f"{identifier}_"
    if identifier.startswith(_PYDANTIC_RESERVED_PREFIX):
        return f"field_{identifier}"
    return identifier


def typescript_identifier(name: str, fallback: str = "value") -> str:
    """Make ``name`` legal and safe to declare as a generated TypeScript class member.

    Args:
        name: A ``camelCase`` candidate.
        fallback: What to return when nothing usable survives.

    Returns:
        The name, suffixed with ``_`` when a class body would give it another meaning.
    """
    identifier = name or fallback
    return f"{identifier}_" if identifier in _TYPESCRIPT_MEMBER_RESERVED else identifier


class Names:
    """A deterministic allocator for one namespace of identifiers.

    Every generated model class, handler method, router module and local competes inside some
    namespace, and both target languages reject a redeclaration. Allocating through one object —
    seeded with whatever the fixed files already define — is what stops a schema called
    ``Handlers`` from colliding with the handler interface module's own exports.
    """

    def __init__(self, reserved: Sequence[str] = ()) -> None:
        """Start an allocator that will never hand out one of ``reserved``."""
        self._taken: Set[str] = set(reserved)

    def take(self, preferred: str) -> str:
        """Claim ``preferred``, or the first free ``<preferred>2``, ``<preferred>3``… variant.

        Args:
            preferred: The name the caller would like.

        Returns:
            The claimed name.
        """
        candidate = preferred
        suffix = 2
        while candidate in self._taken:
            candidate = f"{preferred}{suffix}"
            suffix += 1
        self._taken.add(candidate)
        return candidate

    def taken(self, name: str) -> bool:
        """Whether ``name`` has already been claimed."""
        return name in self._taken


# ===========================================================================
# Shapes
# ===========================================================================


@dataclass(frozen=True)
class StubFile:
    """One file of a generated stub project.

    Lives here rather than in either renderer because the facade
    (:mod:`app.server_stub_generator`) and the client kit both stage files from *both* projects
    into one archive, and two structurally identical records with different names would make that
    staging code choose between them for no reason.

    Attributes:
        path: Path relative to the project root (``pyproject.toml``, ``src/routes/pets.ts``).
        text: The file's complete contents, always ending in a newline.
    """

    path: str
    text: str


@dataclass(frozen=True)
class ValueShape:
    """One value's shape, described in terms both target languages can render and validate.

    This is deliberately close to a JSON Schema fragment rather than to either language's type
    system: the Express stub validates against it at runtime, the FastAPI stub hands the same
    facts to pydantic, and a shape that could only be spelled in one of them would put the two
    stubs out of agreement about what a valid request is.

    Attributes:
        kind: ``string`` / ``integer`` / ``number`` / ``boolean`` / ``array`` / ``map`` /
            ``object`` / ``ref`` / ``union`` / ``any``.
        ref: The :attr:`StubSchema.key` this shape names, when ``kind`` is ``ref``.
        item: The element shape of an ``array``, or the value shape of a ``map``.
        members: The alternative shapes of a ``union``.
        format: The JSON Schema ``format`` annotation the canonical scalar projects to.
        enum: The permitted values, when the contract states a closed set inline.
        constraints: The contract's constraints on the value, when it stated any.
        nullable: Whether the value may be ``null``.
    """

    kind: str
    ref: Optional[str] = None
    item: Optional["ValueShape"] = None
    members: Tuple["ValueShape", ...] = ()
    format: Optional[str] = None
    enum: Tuple[Any, ...] = ()
    constraints: Optional[Constraints] = None
    nullable: bool = False


#: The shape of a value the contract says nothing structural about.
SHAPE_ANY = ValueShape(kind="any")


def constraint_facts(constraints: Optional[Constraints]) -> Dict[str, Any]:
    """Reduce a canonical :class:`~app.canonical_model.Constraints` to the keys both stubs honour.

    Only the constraints that *both* pydantic and the generated TypeScript validator can enforce
    are carried through, so a request rejected by one stub is rejected by the other. Everything
    else (``unique_items`` on a non-array, an unrepresentable ``multiple_of``) is dropped rather
    than half-enforced.

    Args:
        constraints: The canonical constraints, or ``None``.

    Returns:
        A dict with any of ``minimum``, ``maximum``, ``exclusive_minimum``, ``exclusive_maximum``,
        ``multiple_of``, ``min_length``, ``max_length``, ``pattern``, ``min_items``, ``max_items``.
        Empty when there is nothing enforceable.
    """
    if constraints is None:
        return {}
    facts: Dict[str, Any] = {}
    for name in (
        "minimum",
        "maximum",
        "exclusive_minimum",
        "exclusive_maximum",
        "multiple_of",
        "min_length",
        "max_length",
        "min_items",
        "max_items",
    ):
        value = getattr(constraints, name, None)
        if value is not None:
            facts[name] = value
    pattern = getattr(constraints, "pattern", None)
    if pattern:
        facts["pattern"] = pattern
    return facts


#: Which constraints apply to which shape family.
#:
#: The split is load-bearing rather than tidy: ``min_length`` means characters on a string and
#: items on an array, and pydantic spells both of them ``min_length`` — so applying the string rule
#: to a list (or the reverse) would reject requests the contract permits. Held here, once, because
#: a rule only one of the two stubs applied would make them disagree about what a valid request is.
_STRING_CONSTRAINTS = frozenset({"min_length", "max_length", "pattern"})
_NUMERIC_CONSTRAINTS = frozenset(
    {"minimum", "maximum", "exclusive_minimum", "exclusive_maximum", "multiple_of"}
)
_ARRAY_CONSTRAINTS = frozenset({"min_items", "max_items"})

#: The constraints whose value is a count of things, and so is never fractional.
_COUNT_CONSTRAINTS = frozenset({"min_length", "max_length", "min_items", "max_items"})


def shape_constraints(shape: ValueShape) -> Dict[str, Any]:
    """Return the constraints that apply to ``shape``, ready for either renderer to spell.

    Two normalizations happen here so neither renderer has to repeat them: a constraint that does
    not apply to the shape's family is dropped, and a bound that
    :class:`~app.canonical_model.Constraints` stores as a float but the contract meant as a whole
    number is returned as an ``int`` — an integer contract's ``maximum: 100`` should not reach a
    generated signature as ``le=100.0``.

    Args:
        shape: The shape whose constraints are wanted.

    Returns:
        Canonical constraint name to value; empty when the shape has none that apply.
    """
    facts = constraint_facts(shape.constraints)
    if not facts:
        return {}
    if shape.kind == "array":
        applicable = _ARRAY_CONSTRAINTS
    elif shape.kind in {"integer", "number"}:
        applicable = _NUMERIC_CONSTRAINTS
    elif shape.kind == "string":
        applicable = _STRING_CONSTRAINTS
    else:
        return {}
    whole = shape.kind != "number"
    resolved: Dict[str, Any] = {}
    for name, value in facts.items():
        if name not in applicable:
            continue
        if isinstance(value, float) and value.is_integer() and (whole or name in _COUNT_CONSTRAINTS):
            value = int(value)
        resolved[name] = value
    return resolved


def wrap_text(text: str, width: int) -> List[str]:
    """Wrap one paragraph to ``width`` columns, never breaking a word.

    Shared by both renderers because a generated doc comment that a reader has to scroll is one
    they will not read, whichever language it is in.

    Args:
        text: The paragraph, already collapsed to a single line.
        width: The column to wrap at.

    Returns:
        The wrapped lines, at least one.
    """
    lines: List[str] = []
    current = ""
    for word in text.split(" "):
        if not current:
            current = word
        elif len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _scalar_shape(name: Optional[str], constraints: Optional[Constraints] = None) -> ValueShape:
    """Resolve a canonical scalar spelling into a :class:`ValueShape`.

    Args:
        name: The canonical scalar name (``string``, ``i64``, ``DateTime``…).
        constraints: The contract's constraints on the value, carried onto the shape.

    Returns:
        The shape. An unrecognized name is ``any`` — the honest answer for a custom scalar the
        model says nothing structural about, and one that neither stub will reject a request over.
    """
    schema = CANONICAL_SCALAR_SCHEMAS.get((name or "").strip().lower())
    if schema is None:
        return ValueShape(kind="any", constraints=constraints)
    kind = _JSON_TYPE_TO_SHAPE.get(str(schema.get("type") or ""), "any")
    return ValueShape(
        kind=kind,
        format=schema.get("format") or (constraints.format if constraints else None),
        constraints=constraints,
    )


# ===========================================================================
# Result shapes
# ===========================================================================


@dataclass(frozen=True)
class StubField:
    """One member of a generated model.

    Attributes:
        wire_name: The name the value travels under on the JSON wire.
        py_name: The pydantic attribute name (``snake_case``), aliased to ``wire_name``.
        ts_name: The TypeScript property name, quoted by the renderer when it is not an
            identifier.
        shape: The member's shape.
        required: Whether the contract requires the member to be present.
        description: The contract's prose for the member.
        default: The declared default, when there is one.
        deprecated: Whether the contract marks the member deprecated.
    """

    wire_name: str
    py_name: str
    ts_name: str
    shape: ValueShape
    required: bool
    description: Optional[str] = None
    default: Any = None
    deprecated: bool = False


@dataclass(frozen=True)
class StubSchema:
    """One named canonical type, resolved for both generators.

    Attributes:
        key: The canonical type key, which every :attr:`ValueShape.ref` names.
        source_name: The type's name in the contract.
        class_name: The identifier *both* stubs declare it under.
        kind: ``record`` / ``enum`` / ``union`` / ``map`` / ``alias`` / ``scalar``.
        fields: The record's members, in declaration order.
        enum_members: ``(member name, wire value)`` for an enum, in declaration order.
        enum_value_kind: ``string`` / ``integer`` / ``mixed`` — what an enum's values all are.
        target: The aliased/mapped/scalar shape, for the non-record kinds.
        members: A union's alternatives.
        description: The contract's prose for the type.
        deprecated: Whether the contract marks the type deprecated.
    """

    key: str
    source_name: str
    class_name: str
    kind: str
    fields: Tuple[StubField, ...] = ()
    enum_members: Tuple[Tuple[str, Any], ...] = ()
    enum_value_kind: str = "string"
    target: Optional[ValueShape] = None
    members: Tuple[ValueShape, ...] = ()
    description: Optional[str] = None
    deprecated: bool = False


@dataclass(frozen=True)
class StubParameter:
    """One path, query, header or cookie input of an operation.

    Attributes:
        wire_name: The name the value travels under (``petId``, ``X-Request-Id``).
        location: ``path`` / ``query`` / ``header`` / ``cookie``.
        py_name: The FastAPI handler's keyword argument name.
        ts_name: The TypeScript request property name.
        shape: The parameter's shape.
        required: Whether the contract requires the value. A path parameter always is — the
            route cannot be matched without it, whatever the contract claims.
        description: The contract's prose for the parameter.
        default: The declared default, when there is one.
        deprecated: Whether the contract marks the parameter deprecated.
    """

    wire_name: str
    location: str
    py_name: str
    ts_name: str
    shape: ValueShape
    required: bool
    description: Optional[str] = None
    default: Any = None
    deprecated: bool = False


@dataclass(frozen=True)
class StubBody:
    """An operation's request body.

    Attributes:
        shape: The body's shape.
        content_type: The media type the body is declared under.
        required: Whether the contract requires a body.
        description: The contract's prose for the body.
        is_json: Whether the declared media type is JSON, and so whether either stub will parse
            and validate it rather than pass the bytes through.
    """

    shape: ValueShape
    content_type: str
    required: bool
    description: Optional[str] = None
    is_json: bool = True


@dataclass(frozen=True)
class StubResponse:
    """One declared response of an operation.

    Attributes:
        status: The numeric HTTP status.
        shape: The response body's shape, or ``None`` when the contract declares no payload.
        description: The contract's prose for the response.
    """

    status: int
    shape: Optional[ValueShape]
    description: Optional[str] = None


@dataclass(frozen=True)
class StubOperation:
    """One HTTP operation, fully resolved before either generator writes a line.

    Attributes:
        key: The canonical operation key.
        operation_id: The id a consumer addresses the operation by.
        group: The router group (an OpenAPI tag, a service) the operation belongs to.
        http_method: The upper-case HTTP verb.
        path_template: The contract's path template, ``{brace}``-spelled and rooted at ``/``.
        express_path: The same path in Express's ``:colon`` spelling.
        py_name: The FastAPI handler method name (``snake_case``).
        ts_name: The TypeScript handler method name (``camelCase``).
        request_type: The generated TypeScript type name for the operation's validated request.
        response_type: The generated TypeScript type name for what the operation answers with.
        path_params: Path parameters, in template order.
        query_params: Query parameters, in declaration order.
        header_params: Header parameters, in declaration order.
        cookie_params: Cookie parameters, in declaration order.
        body: The request body, or ``None``.
        success: The response a successful call answers with.
        errors: The declared error responses, by ascending status.
        summary: The contract's one-line summary.
        description: The contract's prose.
        deprecated: Whether the contract marks the operation deprecated.
        security_schemes: The security schemes the operation itself declares.
    """

    key: str
    operation_id: str
    group: str
    http_method: str
    path_template: str
    express_path: str
    py_name: str
    ts_name: str
    request_type: str
    response_type: str
    path_params: Tuple[StubParameter, ...] = ()
    query_params: Tuple[StubParameter, ...] = ()
    header_params: Tuple[StubParameter, ...] = ()
    cookie_params: Tuple[StubParameter, ...] = ()
    body: Optional[StubBody] = None
    success: StubResponse = field(default_factory=lambda: StubResponse(status=200, shape=None))
    errors: Tuple[StubResponse, ...] = ()
    summary: Optional[str] = None
    description: Optional[str] = None
    deprecated: bool = False
    security_schemes: Tuple[str, ...] = ()

    @property
    def parameters(self) -> Tuple[StubParameter, ...]:
        """Every parameter of the operation, path first, in the order the stubs declare them."""
        return self.path_params + self.query_params + self.header_params + self.cookie_params


@dataclass(frozen=True)
class StubGroup:
    """One router's worth of operations.

    Attributes:
        name: The group's name in the contract (an OpenAPI tag, a service name).
        module: The module/file stem both stubs name the router after.
        class_prefix: The ``PascalCase`` stem the group's generated names are built from.
        handler_class: The typed handler interface's name.
        stub_class: The name of the handler base whose every operation answers 501.
        operations: The group's operations, in declaration order.
        description: The contract's prose for the group, when the source carried any.
    """

    name: str
    module: str
    class_prefix: str
    handler_class: str
    stub_class: str
    operations: Tuple[StubOperation, ...]
    description: Optional[str] = None


@dataclass(frozen=True)
class ServerStubSkip:
    """One operation neither stub generated a route for.

    Attributes:
        operation_id: The id a consumer would address the operation by.
        key: The canonical operation key.
        reason: Why there is no route, in a sentence a consumer can act on.
    """

    operation_id: str
    key: str
    reason: str


@dataclass(frozen=True)
class ServerStubPlan:
    """Everything both generators need, resolved once.

    Attributes:
        title: The API's title, or a fallback derived from its identity.
        version: The API's version, when the contract states one.
        description: The API's prose.
        base_path: The path prefix the declared server mounts the API under (``/v2``), or ``""``.
        schemas: Every named type, in declaration order.
        groups: The router groups, in declaration order. A group with no HTTP operation is
            dropped rather than emitted empty.
        operations: Every planned operation, flat, in declaration order.
        skipped: Operations no route was generated for, with reasons.
        security_schemes: Every security scheme the model mentions, sorted.
        total_operation_count: How many operations the contract declares in total, so a
            truncated plan can say what it left out.
    """

    title: str
    version: Optional[str]
    description: Optional[str]
    base_path: str
    schemas: Tuple[StubSchema, ...]
    groups: Tuple[StubGroup, ...]
    operations: Tuple[StubOperation, ...]
    skipped: Tuple[ServerStubSkip, ...]
    security_schemes: Tuple[str, ...]
    total_operation_count: int

    def schema_by_key(self, key: str) -> Optional[StubSchema]:
        """Return the schema a :attr:`ValueShape.ref` names, or ``None``."""
        for schema in self.schemas:
            if schema.key == key:
                return schema
        return None

    @property
    def truncated(self) -> bool:
        """Whether the operation cap left some of the contract's operations out."""
        return len(self.operations) < self.total_operation_count


# ===========================================================================
# Planning
# ===========================================================================

#: Identifiers no generated class may claim, because a fixed file of one of the two stubs already
#: imports or declares them.
#:
#: One shared reservation list, because a schema gets one ``class_name`` used by both languages,
#: and a name legal in only one of them is a name that cannot be used. The list is exactly what the
#: generated modules import — not every keyword of either language — because a contract is entitled
#: to a schema called ``Error`` or ``Date``, and renaming one it could have kept is a worse outcome
#: than the collision it was avoiding.
_RESERVED_CLASS_NAMES = frozenset(
    {
        # Python: what the generated modules import
        "APIRouter",
        "Annotated",
        "Any",
        "BaseModel",
        "Body",
        "ConfigDict",
        "Cookie",
        "Dict",
        "Enum",
        "FastAPI",
        "Field",
        "Header",
        "JSONResponse",
        "List",
        "Optional",
        "Path",
        "Protocol",
        "Query",
        "Request",
        "RequestValidationError",
        "Response",
        "Union",
        # TypeScript: the one global the generated model file writes
        "Record",
        # Shared error vocabulary both stub projects declare
        "ApiProblem",
        "NotImplementedError",
        "OperationNotImplemented",
        "ValidationIssue",
    }
)


def _status_int(raw: Optional[str]) -> Optional[int]:
    """Return a response status as an int, or ``None`` for a range (``4XX``) or ``default``."""
    text = (raw or "").strip()
    return int(text) if text.isdigit() else None


def _default_success_status(http_method: str, has_payload: bool) -> int:
    """The status a success answers with when the contract does not say.

    ``POST`` defaults to ``201`` only when it declares no payload *and* no explicit status, which
    is the one case where the contract is silent and the verb is the only evidence. Everything
    else answers ``200``, or ``204`` when there is nothing to send.

    Args:
        http_method: The upper-case HTTP verb.
        has_payload: Whether the operation declares a response payload.

    Returns:
        The status code.
    """
    if not has_payload:
        return 201 if http_method == "POST" else 204
    return 200


class _Planner:
    """Resolves one canonical model into a :class:`ServerStubPlan`."""

    def __init__(self, api: CanonicalApi, max_operations: int) -> None:
        """Plan ``api``, generating routes for at most ``max_operations`` HTTP operations."""
        self._api = api
        self._max = max(0, max_operations)
        self._classes = Names(_RESERVED_CLASS_NAMES)
        self._by_key: Dict[str, StubSchema] = {}
        self._by_name: Dict[str, List[Type]] = {}
        self._key_for_type: Dict[str, str] = {}
        self.schemas: List[StubSchema] = []
        self.operations: List[StubOperation] = []
        self.skipped: List[ServerStubSkip] = []
        self.groups: List[StubGroup] = []
        self.total_operations = 0

    # -- named types ------------------------------------------------------

    def plan_schemas(self) -> None:
        """Allocate a class name for every named type, then resolve each one's structure.

        Two passes, because a record's field may reference a type declared after it: allocation
        has to finish before any shape is resolved, or a forward reference would resolve to a
        scalar fallback.
        """
        prepared: List[Tuple[Type, str]] = []
        for type_ in self._api.types:
            if not type_.key or type_.key in self._key_for_type:
                continue
            class_name = self._classes.take(pascal_case(type_.name or type_.key, "Model"))
            self._key_for_type[type_.key] = class_name
            self._by_name.setdefault(type_.name or "", []).append(type_)
            prepared.append((type_, class_name))
        for type_, class_name in prepared:
            schema = self._resolve_type(type_, class_name)
            self._by_key[type_.key] = schema
            self.schemas.append(schema)

    def _lookup_key(self, name: str) -> Optional[str]:
        """Return the canonical key a reference names, or ``None`` when it names no single type.

        Matched by canonical key first and by *unique* source name second — the precedence
        :mod:`app.canonical_json_schema` uses, so a ``$ref`` a validation schema resolves and a
        field a generated model declares always name the same type.
        """
        if not name:
            return None
        if name in self._key_for_type:
            return name
        candidates = self._by_name.get(name, [])
        return candidates[0].key if len(candidates) == 1 else None

    def _resolve_type(self, type_: Type, class_name: str) -> StubSchema:
        """Resolve one named canonical type into a :class:`StubSchema`."""
        common = {
            "key": type_.key,
            "source_name": type_.name or type_.key,
            "class_name": class_name,
            "description": type_.description,
            "deprecated": type_.deprecated,
        }
        if type_.kind is TypeKind.RECORD:
            py_members, ts_members = Names(), Names()
            return StubSchema(
                kind="record",
                fields=tuple(self._resolve_field(member, py_members, ts_members) for member in type_.fields),
                **common,
            )
        if type_.kind is TypeKind.ENUM:
            value_kind, entries = _enum_members(type_)
            return StubSchema(kind="enum", enum_members=entries, enum_value_kind=value_kind, **common)
        if type_.kind is TypeKind.UNION:
            members = tuple(
                self.shape_for_name(member_name) for member_name in type_.union_members if member_name
            )
            return StubSchema(kind="union", members=members, **common)
        if type_.kind is TypeKind.MAP:
            return StubSchema(kind="map", target=self.shape_for_ref(type_.value_type), **common)
        if type_.kind is TypeKind.ALIAS:
            return StubSchema(kind="alias", target=self.shape_for_ref(type_.aliased), **common)
        return StubSchema(kind="scalar", target=_scalar_shape(type_.name or type_.key, type_.constraints), **common)

    def _resolve_field(self, member: CanonicalField, py_names: Names, ts_names: Names) -> StubField:
        """Resolve one record member.

        ``nullable=False`` is the canonical spelling of "required" (see
        :mod:`app.canonical_json_schema`), so a member the contract deliberately marked required
        is the one this reports as required; every other member is optional.
        """
        wire_name = member.name or member.key
        required = member.type is not None and not member.type.nullable
        return StubField(
            wire_name=wire_name,
            py_name=py_names.take(python_identifier(snake_case(wire_name, "field"))),
            # A model member keeps its *wire* name in TypeScript, always: the generated interface
            # describes the JSON that travels, and renaming a property would make the stub's own
            # models disagree with the payloads its routes accept. The renderer quotes the name
            # when it is not a bare identifier.
            ts_name=ts_names.take(wire_name or camel_case(member.key, "field")),
            shape=self.shape_for_ref(member.type, constraints=member.constraints),
            required=required,
            description=member.description,
            default=member.default,
            deprecated=member.deprecated,
        )

    # -- shapes -----------------------------------------------------------

    def shape_for_ref(
        self,
        ref: Optional[TypeRef],
        *,
        constraints: Optional[Constraints] = None,
        depth: int = 0,
    ) -> ValueShape:
        """Express one canonical type reference as a :class:`ValueShape`.

        Args:
            ref: The reference, or ``None``.
            constraints: The contract's constraints at this use site.
            depth: How much anonymous nesting has already been followed.

        Returns:
            The shape. A list wraps its element shape; a named type becomes a ``ref``; anything
            else falls through to the shared scalar vocabulary.
        """
        if ref is None or depth > MAX_SCHEMA_DEPTH:
            return ValueShape(kind="any", constraints=constraints)
        if ref.is_list():
            return ValueShape(
                kind="array",
                item=self.shape_for_ref(ref.item, depth=depth + 1),
                constraints=constraints,
                nullable=False,
            )
        key = self._lookup_key(ref.name or "")
        if key is not None:
            return ValueShape(kind="ref", ref=key, constraints=constraints)
        return _scalar_shape(ref.name or "", constraints)

    def shape_for_name(self, name: str) -> ValueShape:
        """Express a bare type name (a union member) as a :class:`ValueShape`."""
        key = self._lookup_key(name)
        return ValueShape(kind="ref", ref=key) if key is not None else _scalar_shape(name)

    def shape_for_parameter(self, param: Parameter) -> ValueShape:
        """Express a parameter's declared type, folding an inline enum onto the shape."""
        shape = self.shape_for_ref(param.type, constraints=param.constraints)
        enum = tuple(param.constraints.enum) if param.constraints and param.constraints.enum else ()
        if enum and shape.kind in {"string", "integer", "number", "boolean", "any"}:
            kind = shape.kind if shape.kind != "any" else _enum_kind([value for value in enum])
            return ValueShape(
                kind=kind,
                format=shape.format,
                enum=enum,
                constraints=shape.constraints,
            )
        return shape

    # -- operations -------------------------------------------------------

    def plan_operations(self) -> None:
        """Walk every service in declaration order, planning what has an HTTP binding."""
        method_names = Names()
        ts_names = Names()
        group_modules = Names({"index", "__init__", "app", "main", "models", "handlers", "errors"})
        grouped: List[Tuple[str, Optional[str], List[StubOperation]]] = []
        seen_groups: Dict[str, int] = {}

        for service in self._api.services:
            group = service.name or service.key or "api"
            for op in service.operations:
                self.total_operations += 1
                identifier = _operation_identifier(op)
                reason = self._unroutable_reason(op)
                if reason is not None:
                    self.skipped.append(ServerStubSkip(operation_id=identifier, key=op.key, reason=reason))
                    continue
                planned = self._plan_operation(op, group, identifier, method_names, ts_names)
                self.operations.append(planned)
                index = seen_groups.get(group)
                if index is None:
                    seen_groups[group] = len(grouped)
                    grouped.append((group, service.description, [planned]))
                else:
                    grouped[index][2].append(planned)

        for name, description, operations in grouped:
            # The handler interface and its 501 base are allocated out of the *same* namespace as
            # the model classes: both end up imported into one module, and a contract with a
            # schema called ``PetsHandlers`` would otherwise redeclare the interface it names.
            prefix = self._classes.take(pascal_case(name, "Api"))
            self.groups.append(
                StubGroup(
                    name=name,
                    # ``snake_case``, not a bare slug: the module stem is imported as a Python
                    # identifier and as a TypeScript binding, so a group named after a numbered
                    # section ("04 orders") must not start the name with a digit.
                    module=group_modules.take(python_identifier(snake_case(name, "api"), "api")),
                    class_prefix=prefix,
                    handler_class=self._classes.take(f"{prefix}Handlers"),
                    stub_class=self._classes.take(f"NotImplemented{prefix}Handlers"),
                    operations=tuple(operations),
                    description=description,
                )
            )

    def _unroutable_reason(self, op: Operation) -> Optional[str]:
        """Why ``op`` gets no route, or ``None`` when it gets one."""
        if not op.http_method or not op.http_path:
            return (
                f"Operation {op.name or op.key!r} has no HTTP binding; a server stub route is only "
                "generated for HTTP operations"
            )
        if len(self.operations) >= self._max:
            return (
                f"The generated stubs carry the first {self._max} operations; this one is beyond "
                "that limit"
            )
        return None

    def _plan_operation(
        self,
        op: Operation,
        group: str,
        identifier: str,
        method_names: Names,
        ts_names: Names,
    ) -> StubOperation:
        """Resolve one HTTP operation into a :class:`StubOperation`."""
        path = op.http_path or "/"
        if not path.startswith("/"):
            path = "/" + path
        http_method = (op.http_method or "GET").upper()

        declared = {
            param.name: param for param in op.parameters if param.location is ParameterLocation.PATH
        }
        py_args = Names({"self", "request", "response", "body"})
        # ``body`` is claimed up front on both sides: the generated request object carries the
        # request body under that name, so a parameter that happens to be called ``body`` is the
        # one that gets suffixed rather than the member every operation of this shape shares.
        ts_args = Names({"body"})
        path_params: List[StubParameter] = []
        seen_tokens: Set[str] = set()
        for match in _PATH_TOKEN.finditer(path):
            token = match.group(1).strip()
            if not token or token in seen_tokens:
                continue
            seen_tokens.add(token)
            param = declared.get(token)
            path_params.append(
                StubParameter(
                    wire_name=token,
                    location="path",
                    py_name=py_args.take(python_identifier(snake_case(token, "path_value"))),
                    ts_name=ts_args.take(typescript_identifier(camel_case(token, "pathValue"))),
                    # A path parameter is required whatever the contract claims: the route
                    # pattern cannot match without a value in that position.
                    shape=self.shape_for_parameter(param) if param is not None else ValueShape(kind="string"),
                    required=True,
                    description=param.description if param is not None else None,
                    deprecated=param.deprecated if param is not None else False,
                )
            )

        def collect(location: ParameterLocation, label: str) -> Tuple[StubParameter, ...]:
            """Resolve every parameter declared in one location, in declaration order."""
            resolved: List[StubParameter] = []
            for param in op.parameters:
                if param.location is not location:
                    continue
                resolved.append(
                    StubParameter(
                        wire_name=param.name,
                        location=label,
                        py_name=py_args.take(python_identifier(snake_case(param.name, f"{label}_value"))),
                        ts_name=ts_args.take(typescript_identifier(camel_case(param.name, f"{label}Value"))),
                        shape=self.shape_for_parameter(param),
                        required=bool(param.required),
                        description=param.description,
                        default=param.default,
                        deprecated=param.deprecated,
                    )
                )
            return tuple(resolved)

        success, errors = self._plan_responses(op, http_method)
        operation_prefix = pascal_case(identifier or op.key, "Operation")
        return StubOperation(
            key=op.key,
            operation_id=identifier,
            group=group,
            http_method=http_method,
            path_template=path,
            express_path=_express_path(path),
            py_name=method_names.take(python_identifier(snake_case(identifier or op.key, "handle"))),
            ts_name=ts_names.take(typescript_identifier(camel_case(identifier or op.key, "handle"))),
            request_type=self._classes.take(f"{operation_prefix}Request"),
            response_type=self._classes.take(f"{operation_prefix}Response"),
            path_params=tuple(path_params),
            query_params=collect(ParameterLocation.QUERY, "query"),
            header_params=collect(ParameterLocation.HEADER, "header"),
            cookie_params=collect(ParameterLocation.COOKIE, "cookie"),
            body=self._plan_body(op),
            success=success,
            errors=errors,
            summary=op.extras.get("summary") if isinstance(op.extras.get("summary"), str) else None,
            description=op.description,
            deprecated=op.deprecated,
            security_schemes=tuple(_operation_schemes(op)),
        )

    def _plan_body(self, op: Operation) -> Optional[StubBody]:
        """Resolve the operation's request body, if it declares one."""
        message = request_message(op)
        if message is None or (message.payload is None and message.payload_schema is None):
            return None
        content_type = pick_content_type(message)
        is_json = "json" in content_type.lower()
        shape = self.shape_for_ref(message.payload) if message.payload is not None else SHAPE_ANY
        return StubBody(
            shape=shape,
            content_type=content_type,
            required=bool(message.required),
            description=message.description,
            is_json=is_json,
        )

    def _plan_responses(self, op: Operation, http_method: str) -> Tuple[StubResponse, Tuple[StubResponse, ...]]:
        """Split the operation's responses into the success it answers with and its errors."""
        success_message: Optional[Message] = None
        success_status: Optional[int] = None
        fallback: Optional[Message] = None
        errors: List[StubResponse] = []
        seen: Set[int] = set()

        for message in op.messages:
            if message.role not in {MessageRole.RESPONSE, MessageRole.ERROR}:
                continue
            status = _status_int(message.status_code)
            if status is not None and 200 <= status <= 299:
                if success_message is None:
                    success_message, success_status = message, status
                continue
            if status is None:
                if fallback is None and (message.status_code or "").strip().lower() in {"", "default", "2xx"}:
                    fallback = message
                continue
            if status < 400 or status in seen:
                continue
            seen.add(status)
            errors.append(
                StubResponse(
                    status=status,
                    shape=self.shape_for_ref(message.payload) if message.payload is not None else None,
                    description=message.description,
                )
            )

        chosen = success_message or fallback
        shape = (
            self.shape_for_ref(chosen.payload)
            if chosen is not None and chosen.payload is not None
            else (SHAPE_ANY if chosen is not None and chosen.payload_schema is not None else None)
        )
        status = (
            success_status
            if success_status is not None
            else _default_success_status(http_method, shape is not None)
        )
        return (
            StubResponse(status=status, shape=shape, description=chosen.description if chosen else None),
            tuple(sorted(errors, key=lambda item: item.status)),
        )


#: A bare identifier a language accepts as a property name without quoting. Exported because the
#: TypeScript renderer decides quoting from it and a second copy of the rule could disagree with
#: the names this module allocated.
IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")


def _express_path(path: str) -> str:
    """Rewrite an OpenAPI path template into Express's ``:colon`` parameter spelling.

    A token the contract left empty (``/pets/{}``) is dropped rather than turned into a nameless
    Express parameter, which Express would reject at registration time and so would take the whole
    server down at boot.

    Args:
        path: The ``{brace}``-spelled path template.

    Returns:
        The Express path.
    """

    def substitute(match: "re.Match[str]") -> str:
        token = match.group(1).strip()
        return f":{camel_case(token, 'param')}" if token else ""

    return _PATH_TOKEN.sub(substitute, path)


def _enum_kind(values: Sequence[Any]) -> str:
    """Return ``string`` / ``integer`` / ``mixed`` for a set of enum values."""
    if values and all(isinstance(value, str) for value in values):
        return "string"
    if values and all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return "integer"
    return "mixed"


def _enum_members(type_: Type) -> Tuple[str, Tuple[Tuple[str, Any], ...]]:
    """Return an enum's value kind and its ``(member name, wire value)`` pairs.

    A member's declared wire value wins over its name — the rule
    :func:`app.canonical_json_schema.build_type_json_schema` applies, so the constants a generated
    model accepts are the values a validator projected from the same contract would accept.

    Args:
        type_: The ``ENUM`` type.

    Returns:
        ``(value kind, members)``.
    """
    members: List[Tuple[str, Any]] = []
    seen: List[Any] = []
    for member in type_.enum_values:
        value = member.value if member.value is not None else member.name
        if value in seen:
            continue
        seen.append(value)
        members.append((member.name or str(value), value))
    return _enum_kind([value for _name, value in members]), tuple(members)


def _operation_identifier(op: Operation) -> str:
    """The id a consumer addresses this operation by.

    Mirrors :func:`app.snippet_render.find_operation`'s precedence, so an id a generated router
    documents is one the snippet routes actually resolve.
    """
    return op.extras.get("operationId") or op.name or op.key


def _operation_schemes(op: Operation) -> List[str]:
    """The security schemes the operation itself declares, in order, deduplicated.

    Only the operation-scoped requirement is read, never the model-scoped observation:
    :mod:`app.canonical_security` documents why acting on an *inferred* scheme per operation would
    assert a requirement no source stated — and in a server stub that assertion would become a
    generated authentication guard the contract never asked for.
    """
    raw = op.extras.get("security")
    found: List[str] = []
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, (list, tuple)):
        for entry in raw:
            scheme = entry if isinstance(entry, str) else None
            if isinstance(entry, dict) and isinstance(entry.get("scheme"), str):
                scheme = entry["scheme"]
            if scheme and scheme not in found:
                found.append(scheme)
    return found


def _base_path(api: CanonicalApi) -> str:
    """The path prefix the contract's first server mounts the API under.

    A generated server has to answer on the same paths the contract publishes, and an OpenAPI
    server URL routinely carries one (``https://api.example.com/v2``). Only the path is taken —
    the host and scheme are the deployment's business, not the stub's.

    Args:
        api: The canonical model.

    Returns:
        The prefix with no trailing slash (``/v2``), or ``""`` when there is none.
    """
    if not api.servers:
        return ""
    base, _placeholders = resolve_server_base(api)
    without_scheme = base.split("://", 1)[-1]
    slash = without_scheme.find("/")
    if slash < 0:
        return ""
    prefix = without_scheme[slash:].rstrip("/")
    return prefix if prefix and prefix != "/" else ""


def build_server_stub_plan(
    api: CanonicalApi, *, max_operations: int = DEFAULT_MAX_OPERATIONS
) -> ServerStubPlan:
    """Resolve a canonical model into the plan both server stub generators render from.

    Args:
        api: The canonical model to plan.
        max_operations: How many HTTP operations get routes. The rest are reported in
            :attr:`ServerStubPlan.skipped` rather than silently dropped.

    Returns:
        The :class:`ServerStubPlan`. A pure function of ``api``: nothing here reads the clock, the
        environment or the filesystem.
    """
    planner = _Planner(api, max_operations)
    planner.plan_schemas()
    planner.plan_operations()
    schemes: List[str] = []
    for operation in planner.operations:
        for scheme in operation.security_schemes:
            if scheme not in schemes:
                schemes.append(scheme)
    return ServerStubPlan(
        title=api.title or (api.identity.name if api.identity else "API"),
        version=api.version,
        description=api.description,
        base_path=_base_path(api),
        schemas=tuple(planner.schemas),
        groups=tuple(planner.groups),
        operations=tuple(planner.operations),
        skipped=tuple(planner.skipped),
        security_schemes=tuple(sorted(schemes)),
        total_operation_count=planner.total_operations,
    )
