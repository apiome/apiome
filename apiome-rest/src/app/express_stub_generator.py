"""The Express/TypeScript server stub generator — SDK-2.5 (#4490).

Turns a :class:`~app.server_stub_plan.ServerStubPlan` into a runnable Express project: TypeScript
types for the contract's schemas, a request-validation middleware generated from those schemas, one
``Router`` per tag, and typed handler interfaces an implementation is compile-checked against.

**Why the validation is hand-rolled rather than delegated.** Express validates nothing — unlike
FastAPI, which validates the moment the signature says something. So this generator emits a
validator: a small schema vocabulary (:file:`src/validation.ts`), a per-operation descriptor table
generated from the contract (:file:`src/schemas.ts`), and one middleware that runs before every
route. The alternative was to generate zod (or ajv) schemas, which would have made the stub's
correctness depend on a dependency's version and its error shape; a hundred lines of validator the
consumer can read is a better trade for a project whose whole purpose is to be edited.

**The dependency-free core is deliberate.** ``models.ts``, ``handlers.ts``, ``schemas.ts``,
``validation.ts`` and ``runtime.ts`` import nothing outside the project. ``runtime.ts`` declares
minimal structural types (``RequestLike``, ``ResponseLike``) that Express's own ``Request`` and
``Response`` satisfy, so only the route, app and server files ever mention Express. That is what
lets the contract's type-checking and its validation be exercised — by the consumer and by this
repository's own gate — without installing a web framework, and what would let a team swap Express
for Hono by rewriting three files instead of the whole project.

**Three properties are load-bearing.**

*It is byte-deterministic.* Every collection is walked in plan order and every name comes from the
plan's allocators, so the client kit can keep serving a content-addressed ``ETag``.

*It emits TypeScript that compiles under ``strict``.* Types are emitted lazily (a TypeScript type
alias may name a type declared later, so there is no ordering problem), every generated request
object is typed, and the one place a validated value crosses from ``unknown`` into a typed request
is :func:`takeValidated` — a single, documented cast the validator has just made true.

*It never refuses over one bad operation.* Operations with no HTTP binding are already reported by
the plan; this module generates nothing for them and the README names them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .server_stub_plan import (
    IDENTIFIER_PATTERN,
    ServerStubPlan,
    StubField,
    StubFile,
    StubGroup,
    StubOperation,
    StubSchema,
    ValueShape,
    camel_case,
    shape_constraints,
    words,
    wrap_text,
)
from .snippet_render import license_comment_block

__all__ = [
    "DEFAULT_PACKAGE_NAME",
    "EXPRESS_STUB_SCHEMA_VERSION",
    "VALIDATION_STATUS",
    "ExpressStubProject",
    "express_package_name",
    "generate_express_stub",
]

#: The addressable shape of the generated project, recorded in the kit manifest.
EXPRESS_STUB_SCHEMA_VERSION = "sdk.express-stub.v1"

#: npm package name used when nothing usable can be derived from the contract.
DEFAULT_PACKAGE_NAME = "api-server"

#: The status a contract violation is answered with. Held equal to the FastAPI stub's on purpose:
#: two stubs generated from one contract that disagreed about the status of "your request is
#: malformed" would be two contracts.
VALIDATION_STATUS = 400

#: The TypeScript type each scalar shape is written as.
_SCALAR_TS: Dict[str, str] = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "object": "Record<string, unknown>",
    "any": "unknown",
}

#: The validator node key each shared constraint fact is emitted under.
_CONSTRAINT_KEYS: Dict[str, str] = {
    "minimum": "minimum",
    "maximum": "maximum",
    "exclusive_minimum": "exclusiveMinimum",
    "exclusive_maximum": "exclusiveMaximum",
    "multiple_of": "multipleOf",
    "min_length": "minLength",
    "max_length": "maxLength",
    "min_items": "minItems",
    "max_items": "maxItems",
    "pattern": "pattern",
}


# ===========================================================================
# Result shape
# ===========================================================================


@dataclass(frozen=True)
class ExpressStubProject:
    """A complete generated Express project.

    Attributes:
        package_name: The npm package name in ``package.json``.
        files: Every generated file, ordered by path.
        routers: The route module stems, in plan order.
        handler_interfaces: The generated handler interface names, in plan order.
        model_types: The generated TypeScript type names, in plan order.
        route_count: How many routes were registered.
    """

    package_name: str
    files: Tuple[StubFile, ...] = ()
    routers: Tuple[str, ...] = ()
    handler_interfaces: Tuple[str, ...] = ()
    model_types: Tuple[str, ...] = ()
    route_count: int = 0

    def file_map(self) -> Dict[str, str]:
        """Return ``path → text`` for every file, for callers that stage an archive."""
        return {item.path: item.text for item in self.files}


def express_package_name(*candidates: Optional[str]) -> str:
    """Derive the npm package name from the first usable candidate.

    Args:
        *candidates: Names to try in order — typically a tenant's configured npm name, then the
            project slug, then the API title.

    Returns:
        A legal npm name, always suffixed ``-server``. The suffix is not optional: a tenant's
        configured ``npm`` name (SDK-3.4) is the name of the *client* library their consumers
        install, and publishing a server skeleton under it would put two different packages at one
        address. A scope the tenant configured is kept, because that part is their namespace and
        second-guessing it would be presumptuous — ``@acme/widgets`` becomes
        ``@acme/widgets-server``.
    """
    for candidate in candidates:
        text = (candidate or "").strip().lower()
        scope = ""
        if text.startswith("@") and "/" in text:
            scope, _, text = text.partition("/")
            scope += "/"
        parts = words(text)
        if parts and not parts[0][0].isdigit():
            stem = "-".join(parts)
            return scope + (stem if stem.endswith("-server") else f"{stem}-server")
    return DEFAULT_PACKAGE_NAME


# ===========================================================================
# Source-text helpers
# ===========================================================================


def _ts_string(value: str) -> str:
    """Render a TypeScript single-quoted string literal."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f"'{escaped}'"


def _ts_value(value: Any) -> str:
    """Render a JSON-ish value as a TypeScript literal expression."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return json.dumps(value)
    if isinstance(value, str):
        return _ts_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_ts_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{_ts_key(str(k))}: {_ts_value(v)}" for k, v in value.items()) + " }"
    return _ts_string(str(value))


def _ts_key(name: str) -> str:
    """Render an object key, quoted only when it is not a bare identifier."""
    return name if IDENTIFIER_PATTERN.match(name) else _ts_string(name)


def _doc_block(lines: Sequence[str], indent: str = "") -> List[str]:
    """Render a JSDoc block, or nothing when there is nothing to say.

    A description containing ``*/`` would close the comment from the inside and turn the rest of
    the file into syntax errors, so the sequence is neutralized rather than escaped.
    """
    cleaned: List[str] = []
    for line in lines:
        text = " ".join((line or "").split()).replace("*/", "*​/")
        if text:
            cleaned.append(text)
    if not cleaned:
        return []
    if len(cleaned) == 1 and len(indent) + len(cleaned[0]) < 100:
        return [f"{indent}/** {cleaned[0]} */"]
    block = [f"{indent}/**"]
    for index, paragraph in enumerate(cleaned):
        if index:
            block.append(f"{indent} *")
        block += [f"{indent} * {piece}" for piece in wrap_text(paragraph, 96 - len(indent))]
    block.append(f"{indent} */")
    return block


def _module(header: Sequence[str], body: Sequence[str], license_block: Optional[str]) -> str:
    """Assemble one TypeScript module: licence comment, generated banner, header doc, body."""
    lines: List[str] = []
    if license_block:
        lines += license_block.split("\n") + [""]
    lines += ["// Code generated by Apiome. DO NOT EDIT — implement the handler interfaces instead.", ""]
    if header:
        lines += list(header) + [""]
    lines += list(body)
    return "\n".join(lines).rstrip("\n") + "\n"


# ===========================================================================
# Types
# ===========================================================================


class _TypeScriptTypes:
    """Renders a :class:`~app.server_stub_plan.ValueShape` as a TypeScript type expression."""

    def __init__(self, plan: ServerStubPlan) -> None:
        """Index the plan's schemas by key."""
        self._names = {schema.key: schema.class_name for schema in plan.schemas}

    def render(self, shape: Optional[ValueShape]) -> str:
        """Return the TypeScript type expression for ``shape`` (``void`` for ``None``)."""
        if shape is None:
            return "void"
        if shape.kind == "ref" and shape.ref:
            return self._names.get(shape.ref, "unknown")
        if shape.kind == "array":
            inner = self.render(shape.item)
            # A union element has to be parenthesized before `[]` binds, or `A | B[]` is a union
            # of A and an array of B rather than an array of the union.
            return f"({inner})[]" if "|" in inner else f"{inner}[]"
        if shape.kind == "map":
            return f"Record<string, {self.render(shape.item)}>"
        if shape.kind == "union":
            members = list(dict.fromkeys(self.render(member) for member in shape.members))
            if not members:
                return "unknown"
            return members[0] if len(members) == 1 else " | ".join(members)
        if shape.enum:
            literals = list(dict.fromkeys(_ts_value(value) for value in shape.enum))
            if literals:
                return " | ".join(literals)
        return _SCALAR_TS.get(shape.kind, "unknown")

    def model_names(self, shape: Optional[ValueShape], into: set) -> None:
        """Record which generated model type names ``shape`` needs, into ``into``."""
        if shape is None:
            return
        if shape.kind == "ref" and shape.ref:
            name = self._names.get(shape.ref)
            if name:
                into.add(name)
            return
        if shape.kind in {"array", "map"}:
            self.model_names(shape.item, into)
            return
        if shape.kind == "union":
            for member in shape.members:
                self.model_names(member, into)


# ===========================================================================
# models.ts
# ===========================================================================


def _member_line(field_: StubField, types: _TypeScriptTypes) -> List[str]:
    """Render one interface member, with its doc comment."""
    prose: List[str] = []
    if field_.description:
        prose.append(field_.description)
    if field_.deprecated:
        prose.append("@deprecated by the contract.")
    lines = _doc_block(prose, "  ")
    optional = "" if field_.required else "?"
    lines.append(f"  {_ts_key(field_.ts_name)}{optional}: {types.render(field_.shape)};")
    return lines


def _render_models(plan: ServerStubPlan, types: _TypeScriptTypes, license_block: Optional[str]) -> StubFile:
    """Render ``src/models.ts``: one TypeScript declaration per named type in the contract."""
    body: List[str] = []
    for schema in plan.schemas:
        prose = [schema.description or f"`{schema.source_name}`, as the contract declares it."]
        if schema.deprecated:
            prose.append("@deprecated by the contract.")
        body += _doc_block(prose)
        if schema.kind == "record":
            body.append(f"export interface {schema.class_name} {{")
            if not schema.fields:
                body.append("  // The contract declares no members for this type.")
                body.append("  [key: string]: unknown;")
            for member in schema.fields:
                body += _member_line(member, types)
            body.append("}")
        elif schema.kind == "enum":
            if not schema.enum_members:
                body.append(f"export type {schema.class_name} = unknown;")
            else:
                literals = [_ts_value(value) for _name, value in schema.enum_members]
                body.append(f"export type {schema.class_name} = {' | '.join(literals)};")
                body.append(
                    f"export const {schema.class_name}Values = "
                    f"[{', '.join(literals)}] as const;"
                )
        elif schema.kind == "union":
            members = list(dict.fromkeys(types.render(member) for member in schema.members))
            rendered = " | ".join(members) if members else "unknown"
            body.append(f"export type {schema.class_name} = {rendered};")
        elif schema.kind == "map":
            # A MAP schema's ``target`` is its *value* type; the record around it is the schema.
            body.append(f"export type {schema.class_name} = Record<string, {types.render(schema.target)}>;")
        else:
            body.append(f"export type {schema.class_name} = {types.render(schema.target)};")
        body.append("")

    if not plan.schemas:
        body.append("// The contract declares no named types.")
        body.append("export {};")

    header = _doc_block(
        [
            "Types generated from the contract's schemas.",
            "Every member keeps its wire name, so a value of one of these types is the JSON that "
            "travels — no mapping layer, and nothing to keep in sync.",
        ]
    )
    return StubFile(path="src/models.ts", text=_module(header, body, license_block))


# ===========================================================================
# schemas.ts
# ===========================================================================


def _constraint_entries(shape: ValueShape) -> Dict[str, Any]:
    """Return the validator-node keys one shape's constraints justify.

    Which constraints apply, and how their values are spelled, is decided once in
    :func:`app.server_stub_plan.shape_constraints`; only the key names are this validator's.
    """
    return {_CONSTRAINT_KEYS[name]: value for name, value in shape_constraints(shape).items()}


def _schema_node(shape: Optional[ValueShape]) -> Dict[str, Any]:
    """Express one shape as the validator's node vocabulary.

    A named reference stays a reference — the registry resolves it at validation time — which is
    what lets a recursive contract be described at all without the emitter looping.
    """
    if shape is None:
        return {"kind": "any"}
    if shape.kind == "ref" and shape.ref:
        return {"kind": "ref", "ref": shape.ref}
    if shape.kind == "array":
        return {"kind": "array", "items": _schema_node(shape.item), **_constraint_entries(shape)}
    if shape.kind == "map":
        return {"kind": "map", "values": _schema_node(shape.item)}
    if shape.kind == "union":
        return {"kind": "union", "anyOf": [_schema_node(member) for member in shape.members]}
    if shape.kind in {"string", "integer", "number", "boolean"}:
        node: Dict[str, Any] = {"kind": shape.kind}
        if shape.enum:
            node["enum"] = list(shape.enum)
        node.update(_constraint_entries(shape))
        return node
    if shape.kind == "object":
        return {"kind": "map", "values": {"kind": "any"}}
    return {"kind": "any"}


def _record_node(schema: StubSchema) -> Dict[str, Any]:
    """Express one record schema as an ``object`` validator node."""
    return {
        "kind": "object",
        "properties": [
            {"name": member.wire_name, "required": member.required, "schema": _schema_node(member.shape)}
            for member in schema.fields
        ],
    }


def _registry_node(schema: StubSchema) -> Dict[str, Any]:
    """Express one named schema as the validator node its key resolves to."""
    if schema.kind == "record":
        return _record_node(schema)
    if schema.kind == "enum":
        if not schema.enum_members:
            return {"kind": "any"}
        kind = "string" if schema.enum_value_kind == "string" else (
            "integer" if schema.enum_value_kind == "integer" else "any"
        )
        if kind == "any":
            return {"kind": "any"}
        return {"kind": kind, "enum": [value for _name, value in schema.enum_members]}
    if schema.kind == "union":
        return {"kind": "union", "anyOf": [_schema_node(member) for member in schema.members]}
    if schema.kind == "map":
        return {"kind": "map", "values": _schema_node(schema.target)}
    return _schema_node(schema.target)


def _operation_node(operation: StubOperation) -> Dict[str, Any]:
    """Express one operation as the descriptor its middleware validates against."""
    parameters: List[Dict[str, Any]] = []
    for param in operation.parameters:
        parameters.append(
            {
                "name": param.wire_name,
                "in": param.location,
                "target": param.ts_name,
                "required": param.required,
                "schema": _schema_node(param.shape),
            }
        )
    node: Dict[str, Any] = {
        "operationId": operation.operation_id,
        "method": operation.http_method,
        "path": operation.path_template,
        "parameters": parameters,
    }
    if operation.body is not None:
        node["body"] = {
            "required": operation.body.required,
            "contentType": operation.body.content_type,
            # A body the contract declares under a non-JSON media type is passed through
            # unvalidated: the stub will not pretend to parse a format it was never told the
            # shape of, and rejecting it would be worse than forwarding it.
            "validate": operation.body.is_json,
            "schema": _schema_node(operation.body.shape) if operation.body.is_json else {"kind": "any"},
        }
    return node


def _render_literal(value: Any, indent: str) -> List[str]:
    """Render a nested dict/list literal across lines, deterministically."""
    if isinstance(value, dict):
        if not value:
            return [f"{indent}{{}}"]
        lines = [f"{indent}{{"]
        for key, item in value.items():
            rendered = _render_literal(item, indent + "  ")
            rendered[0] = f"{indent}  {_ts_key(str(key))}: {rendered[0].lstrip()}"
            rendered[-1] = rendered[-1] + ","
            lines += rendered
        lines.append(f"{indent}}}")
        return lines
    if isinstance(value, (list, tuple)):
        if not value:
            return [f"{indent}[]"]
        lines = [f"{indent}["]
        for item in value:
            rendered = _render_literal(item, indent + "  ")
            rendered[-1] = rendered[-1] + ","
            lines += rendered
        lines.append(f"{indent}]")
        return lines
    return [f"{indent}{_ts_value(value)}"]


def _render_schemas(plan: ServerStubPlan, license_block: Optional[str]) -> StubFile:
    """Render ``src/schemas.ts``: the named-type registry and the per-operation descriptors."""
    body: List[str] = [
        "import type { OperationSchema, SchemaNode } from './validation';",
        "",
    ]
    body += _doc_block(
        [
            "Every named type the contract declares, keyed the way a `ref` node names it.",
            "References are resolved here rather than inlined, so a contract that describes itself "
            "recursively is describable at all.",
        ]
    )
    registry = {schema.key: _registry_node(schema) for schema in plan.schemas}
    registry_lines = _render_literal(registry, "")
    body.append("export const schemaRegistry: Record<string, SchemaNode> = " + registry_lines[0].lstrip())
    body += registry_lines[1:-1]
    body.append(registry_lines[-1] + ";")
    body.append("")

    body += _doc_block(
        [
            "One descriptor per operation, generated from the contract.",
            "The validation middleware reads these — a route registers the descriptor, never a "
            "hand-written rule.",
        ]
    )
    operations = {operation.ts_name: _operation_node(operation) for operation in plan.operations}
    operation_lines = _render_literal(operations, "")
    body.append("export const operations: Record<string, OperationSchema> = " + operation_lines[0].lstrip())
    body += operation_lines[1:-1]
    body.append(operation_lines[-1] + ";")
    body.append("")

    header = _doc_block(["The contract, as data the validator can run."])
    return StubFile(path="src/schemas.ts", text=_module(header, body, license_block))


# ===========================================================================
# handlers.ts
# ===========================================================================


def _request_type(operation: StubOperation, types: _TypeScriptTypes) -> List[str]:
    """Render one operation's validated-request type."""
    members: List[str] = []
    for param in operation.parameters:
        prose = [param.description] if param.description else []
        prose.append(f"The `{param.wire_name}` {param.location} parameter.")
        members += _doc_block(prose, "  ")
        optional = "" if param.required else "?"
        members.append(f"  {_ts_key(param.ts_name)}{optional}: {types.render(param.shape)};")
    if operation.body is not None:
        members += _doc_block(
            [operation.body.description or f"The request body (`{operation.body.content_type}`)."],
            "  ",
        )
        optional = "" if operation.body.required else "?"
        # ``Uint8Array``, not ``Buffer``: a Node ``Buffer`` *is* one, so the annotation is accurate
        # either way, and the standard-library spelling keeps the dependency-free core compilable
        # without ``@types/node``.
        rendered = types.render(operation.body.shape) if operation.body.is_json else "Uint8Array"
        members.append(f"  body{optional}: {rendered};")

    lines = _doc_block(
        [
            f"The validated input of `{operation.operation_id}`.",
            "Every member has already been checked against the contract; a handler never has to "
            "re-validate one.",
        ]
    )
    if not members:
        lines.append(f"export type {operation.request_type} = Record<string, never>;")
        return lines
    lines.append(f"export interface {operation.request_type} {{")
    lines += members
    lines.append("}")
    return lines


def _render_handlers(
    plan: ServerStubPlan, types: _TypeScriptTypes, license_block: Optional[str]
) -> Tuple[StubFile, List[str]]:
    """Render ``src/handlers.ts``: request/response types, interfaces, and the 501 bases.

    Returns:
        ``(file, interface names)``.
    """
    models: set = set()
    for operation in plan.operations:
        for param in operation.parameters:
            types.model_names(param.shape, models)
        if operation.body is not None and operation.body.is_json:
            types.model_names(operation.body.shape, models)
        types.model_names(operation.success.shape, models)

    body: List[str] = ["import { NotImplementedError } from './runtime';"]
    if models:
        body.append("import type { " + ", ".join(sorted(models)) + " } from './models';")
    body.append("")

    interfaces: List[str] = []
    for group in plan.groups:
        for operation in group.operations:
            body += _request_type(operation, types)
            body.append("")
            body += _doc_block([f"What a successful `{operation.operation_id}` answers with."])
            body.append(
                f"export type {operation.response_type} = {types.render(operation.success.shape)};"
            )
            body.append("")

        interfaces.append(group.handler_class)
        body += _doc_block(
            [
                f"Every operation the contract groups under `{group.name}`.",
                group.description or "",
                f"Implement this interface — or extend `{group.stub_class}` — and pass it to "
                "`createApp`.",
            ]
        )
        body.append(f"export interface {group.handler_class} {{")
        for operation in group.operations:
            body += _doc_block(_operation_prose(operation), "  ")
            body.append(
                f"  {_ts_key(operation.ts_name)}(request: {operation.request_type}): "
                f"Promise<{operation.response_type}>;"
            )
        body.append("}")
        body.append("")

        body += _doc_block(
            [
                f"A `{group.handler_class}` whose every operation answers 501 until it is "
                "overridden.",
                "Extend this and override the operations you have implemented; anything you have "
                "not is still routed, still validated, and still answers 501.",
            ]
        )
        body.append(f"export class {group.stub_class} implements {group.handler_class} {{")
        for operation in group.operations:
            body += _doc_block([f"Answer 501 for `{operation.operation_id}`."], "  ")
            body.append(
                f"  async {operation.ts_name}(_request: {operation.request_type}): "
                f"Promise<{operation.response_type}> {{"
            )
            body.append(
                f"    throw new NotImplementedError({_ts_string(operation.operation_id)}, "
                f"{_ts_string(operation.http_method)}, {_ts_string(operation.path_template)});"
            )
            body.append("  }")
        body.append("}")
        body.append("")

    if not plan.groups:
        body.append("// The contract declares no HTTP operations, so there is nothing to implement.")
        body.append("export {};")

    header = _doc_block(
        [
            "The typed handler interfaces this project is built around.",
            "One interface per contract group states the signature of every operation in it; the "
            "matching NotImplemented… class answers 501 for all of them. Implementing an operation "
            "with a signature the contract does not describe is a compile error.",
        ]
    )
    return StubFile(path="src/handlers.ts", text=_module(header, body, license_block)), interfaces


def _operation_prose(operation: StubOperation) -> List[str]:
    """The paragraphs a generated interface or route documents an operation with."""
    summary = (operation.summary or "").strip()
    if summary and summary[-1] not in ".!?":
        summary += "."
    prose = [line for line in (summary, operation.description) if line]
    prose.append(f"`{operation.http_method} {operation.path_template}` ({operation.operation_id}).")
    if operation.deprecated:
        prose.append("@deprecated by the contract.")
    if operation.security_schemes:
        prose.append(
            "The contract requires authentication for this operation ("
            + ", ".join(f"`{scheme}`" for scheme in operation.security_schemes)
            + "); enforcing it is your implementation's responsibility."
        )
    return prose


# ===========================================================================
# routes/
# ===========================================================================


def _render_route(operation: StubOperation) -> List[str]:
    """Render one route registration: validation middleware, then the typed delegation."""
    lines = _doc_block(_operation_prose(operation), "  ")
    lines.append(f"  router.{operation.http_method.lower()}(")
    lines.append(f"    {_ts_string(operation.express_path or '/')},")
    lines.append(f"    validateRequest(operations[{_ts_string(operation.ts_name)}]),")
    lines.append("    asyncRoute(async (req, res) => {")
    call = f"handlers.{operation.ts_name}(takeValidated<{operation.request_type}>(req))"
    if operation.success.shape is not None:
        lines.append(f"      const result = await {call};")
        lines.append(f"      res.status({operation.success.status}).json(result);")
    else:
        # A response with no declared payload sends no body: `json(undefined)` would write the
        # four bytes `null`, which is a body, and a 204 that carries one is not a 204. The call
        # is awaited but not bound, because a binding nothing reads is a lint failure waiting in
        # the consumer's own project.
        lines.append(f"      await {call};")
        lines.append(f"      res.status({operation.success.status}).end();")
    lines.append("    }),")
    lines.append("  );")
    lines.append("")
    return lines


def _render_router(group: StubGroup, license_block: Optional[str]) -> StubFile:
    """Render one ``src/routes/<group>.ts``: a ``Router`` factory over the group's handlers."""
    request_types = sorted({operation.request_type for operation in group.operations})
    body: List[str] = [
        "import { Router } from 'express';",
        "",
        "import type { " + ", ".join(sorted([group.handler_class, *request_types])) + " } from '../handlers';",
        "import { asyncRoute, takeValidated } from '../runtime';",
        "import { operations } from '../schemas';",
        "import { validateRequest } from '../validation';",
        "",
    ]
    body += _doc_block(
        [
            f"Register every `{group.name}` operation against `handlers`.",
            "The registrations below are the contract: each route validates its request against "
            "the generated descriptor before the handler is called, so a handler only ever sees "
            "input the contract permits.",
        ]
    )
    body.append(f"export function {camel_case(group.module, 'api')}Router(handlers: {group.handler_class}): Router {{")
    body.append("  const router = Router();")
    body.append("")
    for operation in group.operations:
        body += _render_route(operation)
    body.append("  return router;")
    body.append("}")

    header = _doc_block([f"Routes for the contract's `{group.name}` operations."])
    return StubFile(path=f"src/routes/{group.module}.ts", text=_module(header, body, license_block))


# ===========================================================================
# app.ts, server.ts, packaging
# ===========================================================================


def _render_app(plan: ServerStubPlan, license_block: Optional[str]) -> StubFile:
    """Render ``src/app.ts``: the application factory that wires routers to handlers."""
    body: List[str] = ["import express, { type Express } from 'express';", ""]
    handler_types = sorted({group.handler_class for group in plan.groups})
    stub_types = sorted({group.stub_class for group in plan.groups})
    if handler_types:
        body.append("import type { " + ", ".join(handler_types) + " } from './handlers';")
        body.append("import { " + ", ".join(stub_types) + " } from './handlers';")
    body.append("import { errorMiddleware, notFoundMiddleware } from './runtime';")
    for group in plan.groups:
        body.append(
            f"import {{ {camel_case(group.module, 'api')}Router }} from './routes/{group.module}';"
        )
    body.append("")
    body += _doc_block(["The path prefix the contract's server publishes the API under."])
    body.append(f"export const BASE_PATH = {_ts_string(plan.base_path)};")
    body.append("")
    body += _doc_block(
        [
            "An implementation per contract group. Anything left out is routed and validated "
            "exactly the same way and answers 501.",
        ]
    )
    body.append("export interface Handlers {")
    for group in plan.groups:
        body.append(f"  {_ts_key(camel_case(group.module, 'api'))}?: {group.handler_class};")
    if not plan.groups:
        body.append("  // The contract declares no HTTP operations.")
        body.append("  [key: string]: never;")
    body.append("}")
    body.append("")
    body += _doc_block(
        [
            f"Build the {plan.title} application.",
            "`createApp()` with no arguments is a complete, runnable server: every route "
            "registered, every request validated, every operation answering 501.",
        ]
    )
    body.append("export function createApp(handlers: Handlers = {}): Express {")
    body.append("  const app = express();")
    body.append("  app.use(express.json({ limit: '1mb' }));")
    body.append("")
    for group in plan.groups:
        key = camel_case(group.module, "api")
        body.append(
            f"  app.use(BASE_PATH, {key}Router(handlers.{key} ?? new {group.stub_class}()));"
        )
    if not plan.groups:
        body.append("  // The contract declares no HTTP operations, so no router is mounted.")
    body.append("")
    body.append("  app.use(notFoundMiddleware);")
    body.append("  app.use(errorMiddleware);")
    body.append("  return app;")
    body.append("}")

    header = _doc_block(
        [
            "The application factory.",
            "This is the only file that knows the project runs on Express — the models, the "
            "handlers, the schemas and the validator do not import it.",
        ]
    )
    return StubFile(path="src/app.ts", text=_module(header, body, license_block))


def _render_server(plan: ServerStubPlan, license_block: Optional[str]) -> StubFile:
    """Render ``src/server.ts``: the listening entry point."""
    body = [
        "import { createApp } from './app';",
        "",
        "const port = Number(process.env.PORT ?? 8000);",
        "",
        "createApp().listen(port, () => {",
        "  // eslint-disable-next-line no-console",
        f"  console.log(`{plan.title} stub listening on http://127.0.0.1:${{port}}`);",
        "});",
    ]
    header = _doc_block([f"Entry point for the generated {plan.title} server."])
    return StubFile(path="src/server.ts", text=_module(header, body, license_block))


def _render_package_json(plan: ServerStubPlan, package: str) -> StubFile:
    """Render ``package.json`` for the generated project."""
    document = {
        "name": package,
        "version": plan.version or "0.1.0",
        "private": True,
        "description": f"Generated Express server stub for {plan.title}.",
        "main": "dist/server.js",
        "scripts": {
            "build": "tsc",
            "start": "node dist/server.js",
            "dev": "tsc --watch",
            "typecheck": "tsc --noEmit",
        },
        "dependencies": {"express": "^5.0.0"},
        "devDependencies": {
            "@types/express": "^5.0.0",
            "@types/node": "^20.0.0",
            "typescript": "^5.4.0",
        },
    }
    return StubFile(path="package.json", text=json.dumps(document, indent=2) + "\n")


def _render_tsconfig() -> StubFile:
    """Render ``tsconfig.json``: strict, because the point of the stub is the type checking."""
    document = {
        "compilerOptions": {
            "target": "ES2022",
            "module": "commonjs",
            "moduleResolution": "node",
            "lib": ["ES2022"],
            "strict": True,
            "noImplicitOverride": True,
            "esModuleInterop": True,
            "forceConsistentCasingInFileNames": True,
            "skipLibCheck": True,
            "declaration": True,
            "outDir": "dist",
            "rootDir": "src",
        },
        "include": ["src"],
    }
    return StubFile(path="tsconfig.json", text=json.dumps(document, indent=2) + "\n")


def _render_readme(plan: ServerStubPlan, package: str, license_header: Optional[str]) -> StubFile:
    """Render the project's ``README.md``: how to run it, and what to implement."""
    lines = [
        f"# {plan.title} — Express server stub",
        "",
        "A runnable Express skeleton generated from the published contract. Every operation is "
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
        "npm install",
        "npm run build && npm start",
        "```",
        "",
        "Every route answers `501 Not Implemented` with a problem document naming the operation.",
        "",
        "## Implement an operation",
        "",
    ]
    if plan.groups:
        group = plan.groups[0]
        operation = group.operations[0]
        key = camel_case(group.module, "api")
        lines += [
            "```ts",
            f"import {{ {group.stub_class} }} from './src/handlers';",
            "import { createApp } from './src/app';",
            "",
            f"class {group.class_prefix}Service extends {group.stub_class} {{",
            f"  override async {operation.ts_name}(request: /* see handlers.ts */ never) {{",
            "    throw new Error('your implementation');",
            "  }",
            "}",
            "",
            f"const app = createApp({{ {key}: new {group.class_prefix}Service() }});",
            "```",
            "",
            "Copy the exact signature from `src/handlers.ts`. Because the base class implements the "
            "interface, an override whose request or response type does not match the contract is a "
            "`tsc` error — not a 500 in production.",
            "",
        ]
    else:
        lines += ["This contract declares no HTTP operations, so there is nothing to implement.", ""]

    lines += [
        "## Request validation",
        "",
        f"`src/validation.ts` runs before every handler. A request that violates the contract is "
        f"rejected with **{VALIDATION_STATUS}** and an RFC 9457 `application/problem+json` body:",
        "",
        "```json",
        "{",
        '  "type": "https://apiome.dev/problems/request-does-not-match-the-contract",',
        '  "title": "Request does not match the contract",',
        f'  "status": {VALIDATION_STATUS},',
        '  "detail": "1 field(s) did not satisfy the published contract.",',
        '  "errors": [',
        '    { "location": "query", "field": "limit", "message": "must be an integer" }',
        "  ]",
        "}",
        "```",
        "",
        "The rules come from `src/schemas.ts`, which is generated from the contract — not from "
        "hand-written middleware.",
        "",
        "## What is generated",
        "",
        f"- `src/models.ts` — {len(plan.schemas)} type(s) from the contract's schemas.",
        "- `src/handlers.ts` — one typed interface per group, plus a 501-answering base class.",
        f"- `src/routes/` — one `Router` factory per group ({len(plan.operations)} route(s)).",
        "- `src/schemas.ts` — the contract as validator data.",
        "- `src/validation.ts` — the validator and its middleware. No dependencies.",
        "- `src/runtime.ts` — problem documents, the 501 signal, and the framework-neutral request "
        "and response types. No dependencies.",
        "- `src/app.ts` — `createApp()`. The only generated file that imports Express.",
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
        "- Undeclared properties on an object are accepted, matching OpenAPI's default. Tighten "
        "`validateObject` in `src/validation.ts` to reject them.",
        "- A request body declared under a non-JSON media type is passed through unvalidated.",
        "- Authentication is documented per operation, never generated: a stub that invented an "
        "auth check would be asserting a policy the contract did not state.",
        "",
        f"Generated by Apiome · `{EXPRESS_STUB_SCHEMA_VERSION}`.",
        "",
    ]
    return StubFile(path="README.md", text="\n".join(lines))


# ===========================================================================
# Entry point
# ===========================================================================


def generate_express_stub(
    plan: ServerStubPlan,
    *,
    package_name: Optional[str] = None,
    license_header: Optional[str] = None,
) -> ExpressStubProject:
    """Generate a complete Express/TypeScript server stub project from a plan.

    The result is a pure function of its arguments: nothing here reads the clock, the environment
    or the filesystem, so two calls with the same plan and the same branding produce byte-identical
    files.

    Args:
        plan: The resolved plan (see :func:`app.server_stub_plan.build_server_stub_plan`).
        package_name: The npm package name. Defaults to the API's title, suffixed ``-server``.
        license_header: A tenant's resolved licence text (SDK-3.4), rendered as a comment block at
            the top of every generated module and quoted in the README.

    Returns:
        The :class:`ExpressStubProject`.
    """
    package = express_package_name(package_name, plan.title)
    license_block = license_comment_block(license_header, "ts")
    types = _TypeScriptTypes(plan)

    files: List[StubFile] = [
        StubFile(path="src/runtime.ts", text=_module(_RUNTIME_HEADER, _RUNTIME_BODY.split("\n"), license_block)),
        StubFile(
            path="src/validation.ts",
            text=_module(_VALIDATION_HEADER, _validation_body(), license_block),
        ),
        _render_models(plan, types, license_block),
        _render_schemas(plan, license_block),
    ]
    handlers_file, interfaces = _render_handlers(plan, types, license_block)
    files.append(handlers_file)
    files.append(_render_app(plan, license_block))
    files.append(_render_server(plan, license_block))

    routers: List[str] = []
    for group in plan.groups:
        files.append(_render_router(group, license_block))
        routers.append(group.module)

    files.append(_render_package_json(plan, package))
    files.append(_render_tsconfig())
    files.append(_render_readme(plan, package, license_header))
    files.sort(key=lambda item: item.path)

    return ExpressStubProject(
        package_name=package,
        files=tuple(files),
        routers=tuple(routers),
        handler_interfaces=tuple(interfaces),
        model_types=tuple(schema.class_name for schema in plan.schemas),
        route_count=len(plan.operations),
    )


def _validation_body() -> List[str]:
    """Return ``src/validation.ts``'s body, with the shared validation status substituted in."""
    return _VALIDATION_BODY.replace("__VALIDATION_STATUS__", str(VALIDATION_STATUS)).split("\n")


# ===========================================================================
# The two fixed runtime modules
# ===========================================================================
#
# These are the same in every generated project — they are a function of the framework, not of the
# contract — so they are written once here rather than composed line by line. Keeping them as text
# is what makes them reviewable as TypeScript rather than as Python that emits TypeScript.

_RUNTIME_HEADER = _doc_block(
    [
        "The framework-neutral runtime: problem documents, the 501 signal, and the minimal request "
        "and response shapes the validator works against.",
        "This file imports nothing. Express's own `Request` and `Response` satisfy `RequestLike` "
        "and `ResponseLike` structurally, which is why the validation layer never has to mention "
        "Express — and why swapping Express for another framework touches the routes, not this.",
    ]
)

_RUNTIME_BODY = '''/** The subset of an HTTP request the generated validation reads. */
export interface RequestLike {
  /** The request's HTTP method. */
  method: string;
  /** Path parameters, as matched by the router. */
  params: Record<string, string>;
  /** Parsed query-string parameters. */
  query: Record<string, unknown>;
  /** Request headers, lower-cased by the server. */
  headers: Record<string, unknown>;
  /** The parsed request body, when a body parser has run. */
  body?: unknown;
}

/** The subset of an HTTP response the generated code writes to. */
export interface ResponseLike {
  status(code: number): ResponseLike;
  json(payload: unknown): unknown;
  end(): unknown;
  setHeader(name: string, value: string): unknown;
}

/** What a middleware calls to pass control on, or to report a failure. */
export type NextFunction = (error?: unknown) => void;

/** A middleware in the shape both this project and Express understand. */
export type Middleware = (req: RequestLike, res: ResponseLike, next: NextFunction) => void;

/** The media type a problem document is served as (RFC 9457). */
export const PROBLEM_MEDIA_TYPE = 'application/problem+json';

/** The `type` URI prefix problem documents are minted under. */
export const PROBLEM_TYPE_PREFIX = 'https://apiome.dev/problems';

/** One field-level failure inside a validation problem document. */
export interface ProblemError {
  /** Where the value came from: `path`, `query`, `header`, `cookie` or `body`. */
  location: string;
  /** Which field failed, as a dotted path. */
  field: string;
  /** What was wrong with it. */
  message: string;
}

/** An RFC 9457 problem document. */
export interface ApiProblem {
  type: string;
  title: string;
  status: number;
  detail: string;
  errors?: ProblemError[];
  operationId?: string;
}

/**
 * Build a problem document.
 *
 * @param status - The HTTP status the response carries.
 * @param title - A short, stable summary of the problem type.
 * @param detail - What went wrong with this request.
 * @param extra - Any further members to include.
 * @returns The problem document, ready to send.
 */
export function problem(
  status: number,
  title: string,
  detail: string,
  extra: Partial<ApiProblem> = {},
): ApiProblem {
  return {
    type: `${PROBLEM_TYPE_PREFIX}/${title.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
    title,
    status,
    detail,
    ...extra,
  };
}

/**
 * Write a problem document to the response.
 *
 * @param res - The response to write to.
 * @param document - The problem document.
 */
export function sendProblem(res: ResponseLike, document: ApiProblem): void {
  res.setHeader('content-type', PROBLEM_MEDIA_TYPE);
  res.status(document.status).json(document);
}

/** Thrown by a generated handler stub that nobody has implemented yet. */
export class NotImplementedError extends Error {
  /** The contract's id for the operation. */
  readonly operationId: string;
  /** The operation's HTTP verb. */
  readonly httpMethod: string;
  /** The operation's path template. */
  readonly path: string;

  /**
   * @param operationId - The contract's id for the operation.
   * @param httpMethod - The operation's HTTP verb.
   * @param path - The operation's path template.
   */
  constructor(operationId: string, httpMethod: string, path: string) {
    super(`${httpMethod} ${path} (${operationId}) is not implemented`);
    this.name = 'NotImplementedError';
    this.operationId = operationId;
    this.httpMethod = httpMethod;
    this.path = path;
  }
}

/**
 * Where a validated request is parked between the middleware and the route.
 *
 * A symbol, not a string: the request object belongs to the framework, and a string property could
 * collide with one the framework — or another middleware — already uses.
 */
export const VALIDATED = Symbol.for('apiome.validatedRequest');

interface ValidatedCarrier {
  [VALIDATED]?: Record<string, unknown>;
}

/**
 * Park a validated request on the request object.
 *
 * @param req - The request being handled.
 * @param value - The validated input.
 */
export function putValidated(req: RequestLike, value: Record<string, unknown>): void {
  (req as RequestLike & ValidatedCarrier)[VALIDATED] = value;
}

/**
 * Read back the validated request the middleware produced.
 *
 * This is the one place a value crosses from `unknown` into a contract type, and the cast is safe
 * exactly because `validateRequest` ran first and refused anything that did not match. A route
 * reached without that middleware throws rather than handing a handler unchecked input.
 *
 * @typeParam T - The operation's generated request type.
 * @param req - The request being handled.
 * @returns The validated input, typed.
 */
export function takeValidated<T>(req: RequestLike): T {
  const value = (req as RequestLike & ValidatedCarrier)[VALIDATED];
  if (value === undefined) {
    throw new Error('takeValidated called on a request that was not validated');
  }
  return value as T;
}

/**
 * Adapt an async route to the callback shape a router expects.
 *
 * Without this, a rejected promise inside a handler is an unhandled rejection rather than a 500 —
 * the single most common way a hand-written Express server loses an error.
 *
 * @param handler - The async route body.
 * @returns A middleware that forwards any failure to the error middleware.
 */
export function asyncRoute(
  handler: (req: RequestLike, res: ResponseLike) => Promise<void>,
): Middleware {
  return (req, res, next) => {
    handler(req, res).catch(next);
  };
}

/**
 * Answer 404 for a path the contract does not declare.
 *
 * @param req - The unmatched request.
 * @param res - The response to write to.
 */
export function notFoundMiddleware(req: RequestLike, res: ResponseLike): void {
  sendProblem(
    res,
    problem(404, 'Not found', `${req.method} is not declared by this contract at that path.`),
  );
}

/**
 * Turn a thrown error into a problem document.
 *
 * A `NotImplementedError` is the expected case — every operation throws one until it is
 * implemented — and answers 501 naming the operation. Anything else is a genuine failure and
 * answers 500 without leaking its message.
 *
 * @param error - Whatever was thrown.
 * @param req - The request being handled.
 * @param res - The response to write to.
 * @param next - Passed on when the response has already started.
 */
export function errorMiddleware(
  error: unknown,
  req: RequestLike,
  res: ResponseLike,
  next: NextFunction,
): void {
  if (error instanceof NotImplementedError) {
    sendProblem(
      res,
      problem(
        501,
        'Not implemented',
        `${error.httpMethod} ${error.path} is declared by the contract but has no implementation yet.`,
        { operationId: error.operationId },
      ),
    );
    return;
  }
  if (error === undefined || error === null) {
    next();
    return;
  }
  sendProblem(res, problem(500, 'Internal server error', 'The server failed to handle the request.'));
}
'''

_VALIDATION_HEADER = _doc_block(
    [
        "The generated request validator.",
        "`schemas.ts` holds the contract as data; this file is the engine that runs it. Every route "
        "mounts `validateRequest(operations.<id>)` ahead of its handler, so a handler is only ever "
        "reached by a request the contract permits.",
        "It has no dependencies on purpose: a validator whose behaviour depended on a package "
        "version would make the stub's own correctness a moving target.",
    ]
)

_VALIDATION_BODY = '''import {
  type Middleware,
  type ProblemError,
  type RequestLike,
  problem,
  putValidated,
  sendProblem,
} from './runtime';
import { schemaRegistry } from './schemas';

/** The status a request that violates the contract is answered with. */
export const VALIDATION_STATUS = __VALIDATION_STATUS__;

/** The keywords a numeric node may carry. Shared so `integer` and `number` cannot drift apart. */
export interface NumericNode {
  enum?: readonly unknown[];
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  exclusiveMaximum?: number;
  multipleOf?: number;
}

/** One member of an object node. */
export interface SchemaProperty {
  name: string;
  required: boolean;
  schema: SchemaNode;
}

/** The vocabulary the generated contract data is written in. */
export type SchemaNode =
  | { kind: 'string'; enum?: readonly unknown[]; minLength?: number; maxLength?: number; pattern?: string }
  | ({ kind: 'integer' } & NumericNode)
  | ({ kind: 'number' } & NumericNode)
  | { kind: 'boolean'; enum?: readonly unknown[] }
  | { kind: 'array'; items: SchemaNode; minItems?: number; maxItems?: number }
  | { kind: 'object'; properties: readonly SchemaProperty[] }
  | { kind: 'map'; values: SchemaNode }
  | { kind: 'union'; anyOf: readonly SchemaNode[] }
  | { kind: 'ref'; ref: string }
  | { kind: 'any' };

/** One declared input of an operation. */
export interface ParameterSchema {
  /** The name the value travels under. */
  name: string;
  /** Where it travels: `path`, `query`, `header` or `cookie`. */
  in: string;
  /** The property the validated request carries it under. */
  target: string;
  /** Whether the contract requires it. */
  required: boolean;
  /** Its shape. */
  schema: SchemaNode;
}

/** An operation's request body, when it declares one. */
export interface BodySchema {
  required: boolean;
  contentType: string;
  validate: boolean;
  schema: SchemaNode;
}

/** One operation, as the validator sees it. */
export interface OperationSchema {
  operationId: string;
  method: string;
  path: string;
  parameters: readonly ParameterSchema[];
  body?: BodySchema;
}

/** What a validation pass produced. */
export type Outcome =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; errors: ProblemError[] };

/**
 * Read a cookie jar out of the `Cookie` header.
 *
 * Parsed here rather than taken from `req.cookies` so the stub works with or without
 * `cookie-parser` installed — a generated server that needed an undeclared dependency to honour
 * its own contract would not be runnable as shipped.
 *
 * @param header - The raw `Cookie` header value.
 * @returns Cookie name to value.
 */
export function parseCookies(header: unknown): Record<string, string> {
  const jar: Record<string, string> = {};
  if (typeof header !== 'string') {
    return jar;
  }
  for (const part of header.split(';')) {
    const equals = part.indexOf('=');
    if (equals < 0) {
      continue;
    }
    const name = part.slice(0, equals).trim();
    if (!name) {
      continue;
    }
    const raw = part.slice(equals + 1).trim();
    try {
      jar[name] = decodeURIComponent(raw);
    } catch {
      // A malformed percent-escape is not a reason to drop the cookie; the raw text is what the
      // client sent, and the schema below decides whether it is acceptable.
      jar[name] = raw;
    }
  }
  return jar;
}

/** Resolve a node, following one `ref` hop at a time so a recursive contract terminates. */
function resolve(node: SchemaNode): SchemaNode {
  let current = node;
  const seen = new Set<string>();
  while (current.kind === 'ref') {
    if (seen.has(current.ref)) {
      return { kind: 'any' };
    }
    seen.add(current.ref);
    const next = schemaRegistry[current.ref];
    if (next === undefined) {
      return { kind: 'any' };
    }
    current = next;
  }
  return current;
}

function fail(location: string, field: string, message: string): ProblemError {
  return { location, field, message };
}

/** Coerce one string-carried value towards the type its node declares. */
function coerce(node: SchemaNode, value: unknown): unknown {
  if (typeof value !== 'string') {
    return value;
  }
  if (node.kind === 'integer' || node.kind === 'number') {
    if (value.trim() === '') {
      return value;
    }
    const parsed = Number(value);
    return Number.isNaN(parsed) ? value : parsed;
  }
  if (node.kind === 'boolean') {
    if (value === 'true' || value === '1') {
      return true;
    }
    if (value === 'false' || value === '0') {
      return false;
    }
    return value;
  }
  if (node.kind === 'array') {
    // A repeated query parameter arrives as an array already; a comma-joined one is the other
    // spelling the same contract permits, so both are accepted.
    return value === '' ? [] : value.split(',');
  }
  return value;
}

/**
 * Validate one value against one node.
 *
 * @param node - The node to check against.
 * @param value - The value as it arrived.
 * @param location - Where the value came from, for the error record.
 * @param field - The dotted path to the value, for the error record.
 * @param coerceStrings - Whether string-carried values should be coerced first. True for path,
 *   query, header and cookie values, which are always text on the wire; false for a JSON body,
 *   whose types are already what the client meant.
 * @param errors - Collected failures, appended to.
 * @returns The validated (and possibly coerced) value.
 */
export function validateValue(
  node: SchemaNode,
  value: unknown,
  location: string,
  field: string,
  coerceStrings: boolean,
  errors: ProblemError[],
): unknown {
  const resolved = resolve(node);
  if (resolved.kind === 'any') {
    return value;
  }
  const candidate = coerceStrings ? coerce(resolved, value) : value;

  if (candidate === null || candidate === undefined) {
    errors.push(fail(location, field, 'must not be null'));
    return candidate;
  }

  switch (resolved.kind) {
    case 'string': {
      if (typeof candidate !== 'string') {
        errors.push(fail(location, field, 'must be a string'));
        return candidate;
      }
      if (resolved.minLength !== undefined && candidate.length < resolved.minLength) {
        errors.push(fail(location, field, `must be at least ${resolved.minLength} character(s)`));
      }
      if (resolved.maxLength !== undefined && candidate.length > resolved.maxLength) {
        errors.push(fail(location, field, `must be at most ${resolved.maxLength} character(s)`));
      }
      if (resolved.pattern !== undefined && !new RegExp(resolved.pattern).test(candidate)) {
        errors.push(fail(location, field, `must match ${resolved.pattern}`));
      }
      checkEnum(resolved.enum, candidate, location, field, errors);
      return candidate;
    }
    case 'integer':
    case 'number': {
      if (typeof candidate !== 'number' || !Number.isFinite(candidate)) {
        errors.push(fail(location, field, `must be ${resolved.kind === 'integer' ? 'an integer' : 'a number'}`));
        return candidate;
      }
      if (resolved.kind === 'integer' && !Number.isInteger(candidate)) {
        errors.push(fail(location, field, 'must be an integer'));
      }
      if (resolved.minimum !== undefined && candidate < resolved.minimum) {
        errors.push(fail(location, field, `must be >= ${resolved.minimum}`));
      }
      if (resolved.maximum !== undefined && candidate > resolved.maximum) {
        errors.push(fail(location, field, `must be <= ${resolved.maximum}`));
      }
      if (resolved.exclusiveMinimum !== undefined && candidate <= resolved.exclusiveMinimum) {
        errors.push(fail(location, field, `must be > ${resolved.exclusiveMinimum}`));
      }
      if (resolved.exclusiveMaximum !== undefined && candidate >= resolved.exclusiveMaximum) {
        errors.push(fail(location, field, `must be < ${resolved.exclusiveMaximum}`));
      }
      if (resolved.multipleOf !== undefined && resolved.multipleOf !== 0) {
        const ratio = candidate / resolved.multipleOf;
        if (!Number.isInteger(ratio)) {
          errors.push(fail(location, field, `must be a multiple of ${resolved.multipleOf}`));
        }
      }
      checkEnum(resolved.enum, candidate, location, field, errors);
      return candidate;
    }
    case 'boolean': {
      if (typeof candidate !== 'boolean') {
        errors.push(fail(location, field, 'must be a boolean'));
      }
      return candidate;
    }
    case 'array': {
      if (!Array.isArray(candidate)) {
        errors.push(fail(location, field, 'must be an array'));
        return candidate;
      }
      if (resolved.minItems !== undefined && candidate.length < resolved.minItems) {
        errors.push(fail(location, field, `must have at least ${resolved.minItems} item(s)`));
      }
      if (resolved.maxItems !== undefined && candidate.length > resolved.maxItems) {
        errors.push(fail(location, field, `must have at most ${resolved.maxItems} item(s)`));
      }
      return candidate.map((item, index) =>
        validateValue(resolved.items, item, location, `${field}[${index}]`, coerceStrings, errors),
      );
    }
    case 'object': {
      return validateObject(resolved.properties, candidate, location, field, coerceStrings, errors);
    }
    case 'map': {
      if (typeof candidate !== 'object' || Array.isArray(candidate)) {
        errors.push(fail(location, field, 'must be an object'));
        return candidate;
      }
      const out: Record<string, unknown> = {};
      for (const [key, item] of Object.entries(candidate as Record<string, unknown>)) {
        out[key] = validateValue(resolved.values, item, location, `${field}.${key}`, coerceStrings, errors);
      }
      return out;
    }
    case 'union': {
      for (const member of resolved.anyOf) {
        const attempt: ProblemError[] = [];
        const result = validateValue(member, candidate, location, field, coerceStrings, attempt);
        if (attempt.length === 0) {
          return result;
        }
      }
      errors.push(fail(location, field, 'does not match any of the declared alternatives'));
      return candidate;
    }
    default:
      return candidate;
  }
}

function checkEnum(
  permitted: readonly unknown[] | undefined,
  value: unknown,
  location: string,
  field: string,
  errors: ProblemError[],
): void {
  if (permitted !== undefined && permitted.length > 0 && !permitted.includes(value)) {
    errors.push(fail(location, field, `must be one of ${permitted.map((item) => String(item)).join(', ')}`));
  }
}

/**
 * Validate an object's declared members.
 *
 * Undeclared properties are kept, not rejected: that is OpenAPI's default, and a stub that
 * tightened it would reject requests the published contract accepts. Delete the spread below to
 * make the generated server reject them.
 *
 * @param properties - The declared members.
 * @param value - The value as it arrived.
 * @param location - Where the value came from.
 * @param field - The dotted path to the value.
 * @param coerceStrings - Whether string-carried values should be coerced.
 * @param errors - Collected failures, appended to.
 * @returns The validated object.
 */
export function validateObject(
  properties: readonly SchemaProperty[],
  value: unknown,
  location: string,
  field: string,
  coerceStrings: boolean,
  errors: ProblemError[],
): unknown {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    errors.push(fail(location, field, 'must be an object'));
    return value;
  }
  const source = value as Record<string, unknown>;
  const out: Record<string, unknown> = { ...source };
  for (const property of properties) {
    const present = Object.prototype.hasOwnProperty.call(source, property.name);
    const path = field ? `${field}.${property.name}` : property.name;
    if (!present || source[property.name] === undefined) {
      if (property.required) {
        errors.push(fail(location, path, 'is required'));
      }
      continue;
    }
    out[property.name] = validateValue(
      property.schema,
      source[property.name],
      location,
      path,
      coerceStrings,
      errors,
    );
  }
  return out;
}

/** Read one parameter's raw value out of the request. */
function rawParameter(
  parameter: ParameterSchema,
  req: RequestLike,
  cookies: Record<string, string>,
): unknown {
  switch (parameter.in) {
    case 'path':
      return req.params[parameter.name];
    case 'query':
      return req.query[parameter.name];
    case 'header':
      return req.headers[parameter.name.toLowerCase()];
    case 'cookie':
      return cookies[parameter.name];
    default:
      return undefined;
  }
}

/**
 * Validate a whole request against one operation's descriptor.
 *
 * @param schema - The operation descriptor, from `schemas.ts`.
 * @param req - The request being handled.
 * @returns The validated request, or the failures that stopped it.
 */
export function validateOperationRequest(schema: OperationSchema, req: RequestLike): Outcome {
  const errors: ProblemError[] = [];
  const value: Record<string, unknown> = {};
  const cookies = parseCookies(req.headers['cookie']);

  for (const parameter of schema.parameters) {
    let raw = rawParameter(parameter, req, cookies);
    if (Array.isArray(raw) && resolve(parameter.schema).kind !== 'array') {
      // A parameter repeated in the query string arrives as an array; the contract asked for one
      // value, so the first is taken rather than the request refused.
      raw = raw.length > 0 ? raw[0] : undefined;
    }
    if (raw === undefined || raw === '') {
      if (parameter.required) {
        errors.push(fail(parameter.in, parameter.name, 'is required'));
      }
      continue;
    }
    value[parameter.target] = validateValue(
      parameter.schema,
      raw,
      parameter.in,
      parameter.name,
      true,
      errors,
    );
  }

  if (schema.body !== undefined) {
    const body = req.body;
    const empty =
      body === undefined ||
      body === null ||
      (typeof body === 'object' && !Array.isArray(body) && Object.keys(body).length === 0);
    if (empty) {
      if (schema.body.required) {
        errors.push(fail('body', 'body', 'is required'));
      }
    } else if (schema.body.validate) {
      value['body'] = validateValue(schema.body.schema, body, 'body', '', false, errors);
    } else {
      value['body'] = body;
    }
  }

  return errors.length > 0 ? { ok: false, errors } : { ok: true, value };
}

/**
 * Build the middleware that validates one operation's requests.
 *
 * @param schema - The operation descriptor, from `schemas.ts`.
 * @returns A middleware that either parks the validated request or answers a problem document.
 */
export function validateRequest(schema: OperationSchema): Middleware {
  return (req, res, next) => {
    const outcome = validateOperationRequest(schema, req);
    if (!outcome.ok) {
      sendProblem(
        res,
        problem(
          VALIDATION_STATUS,
          'Request does not match the contract',
          `${outcome.errors.length} field(s) did not satisfy the published contract.`,
          { errors: outcome.errors },
        ),
      );
      return;
    }
    putValidated(req, outcome.value);
    next();
  };
}
'''
