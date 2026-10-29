"""TypeSpec emitter: canonical model → TypeSpec ``.tsp`` — MFX-15.1 (#3893).

The inverse of :class:`app.typespec_normalizer.TypeSpecNormalizer` and an implementation of the
:class:`app.emitter.Emitter` SPI. The writer targets the TypeSpec compiler Apiome bundles (``tsp``
0.65, :mod:`app.typespec_compile`) with the ``@typespec/http`` library, and the export is validated by
compiling it (:func:`app.export_validation._validate_typespec`):

* **Document** — ``@service({ title })`` on the namespace, the description as its doc comment, the
  version as ``@info({ version })`` (``@typespec/openapi``) and each server as ``@server(url, description)``
  with its variables.
* **Types** — ``RECORD`` → ``model``; ``ENUM`` → ``enum`` (a member's value written when it differs from
  its name); ``UNION`` → ``union`` (named variants from fields, or its member types); ``MAP`` →
  ``model X is Record<V>``; a named list → ``model X is T[]``; a named scalar or an alias of a scalar →
  ``scalar X extends <base>``; an alias of a named type → ``alias X = T``.
* **Members** — a nullable field is optional (``name?:``); constraints become decorators
  (``@minLength`` / ``@maxLength`` / ``@pattern`` / ``@format`` on strings, ``@minValue`` / ``@maxValue`` and
  their exclusive forms on numbers, ``@minItems`` / ``@maxItems`` on lists); a default is ``= value``;
  descriptions are ``/** doc */`` comments and ``deprecated`` is ``#deprecated``. A name that is not a
  TypeSpec identifier (or is a keyword) is written in backticks, so every name is kept as is.
* **Operations** — each service is an ``interface``; an HTTP operation is ``@get`` / ``@put`` / ``@post`` /
  ``@patch`` / ``@delete`` / ``@head`` with ``@route`` and its parameters as ``@path`` / ``@query`` /
  ``@header("Name")`` / ``@cookie("name")``, the body as ``@body``; the responses are the return type —
  the payload for a plain 200, else ``{ @statusCode statusCode: 201; @body body: T; @header(...) … }``
  variants (a ``4XX`` range as ``@minValue(400) @maxValue(499)``, a ``default`` error as a synthesized
  ``@error`` model). An operation with no HTTP binding is written ``@post @route("/<Service>/<op>")``.

An item imported from TypeSpec is written back in its own form: its imports, namespace, interface route
prefixes, field type expressions and decorators, so a TypeSpec → TypeSpec export re-imports unchanged.
Whatever cannot be carried is reported as a :class:`~app.emitter.Loss`, and the fidelity pack
(:class:`TypeSpecFidelityRulePack`) predicts exactly those losses.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from pydantic import Field

from .canonical_model import (
    ApiParadigm,
    CanonicalApi,
    CanonicalField,
    Constraints,
    Message,
    MessageRole,
    Operation,
    OperationKind,
    Parameter,
    ParameterLocation,
    Service,
    Type,
    TypeKind,
    TypeRef,
)
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import ROOT_CONSTRUCT_KEY, CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessSeverity
from .scalar_aliases import scalar_kind
from .typespec_parser import parse_typespec
from .writer_loss_rulepack import WriterLossRulePack

__all__ = [
    "TypeSpecEmitOptions",
    "TypeSpecEmitter",
    "TypeSpecFidelityRulePack",
    "typespec_identifier",
    "validate_typespec_document",
]

#: Words TypeSpec reserves; a name spelled like one is written in backticks.
_KEYWORDS = frozenset({
    "import", "model", "scalar", "namespace", "using", "op", "enum", "alias", "is", "interface", "union",
    "projection", "else", "if", "dec", "fn", "const", "init", "extern", "extends", "true", "false", "return",
    "void", "never", "unknown", "valueof", "typeof", "statemachine", "macro", "package", "metadata", "env",
    "arg", "declare", "array", "struct", "record", "module", "mod", "sym", "context", "prop", "property",
    "scenario", "pub", "sub", "typeref", "trait", "this", "self", "super", "keyof", "with", "implements",
    "impl", "satisfies", "flag", "auto", "partial", "private", "public", "protected", "internal", "sealed",
    "local", "async", "null", "lambda",
})
#: Types a declaration may not be named after (a reference would then resolve to the declaration).
_BUILTIN_TYPES = frozenset({
    "string", "boolean", "bytes", "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64",
    "safeint", "integer", "float", "float32", "float64", "numeric", "decimal", "decimal128", "utcDateTime",
    "offsetDateTime", "plainDate", "plainTime", "duration", "url", "unknown", "void", "never", "null",
    "Record", "Array", "object",
})
#: Scalar kind (:func:`app.scalar_aliases.scalar_kind`) → TypeSpec scalar.
_TSP_FOR_KIND: Dict[str, str] = {
    "bool": "boolean", "int8": "int8", "int16": "int16", "int32": "int32", "int64": "int64", "uint8": "uint8",
    "uint16": "uint16", "uint32": "uint32", "uint64": "uint64", "float": "float32", "double": "float64",
    "string": "string", "bytes": "bytes",
}
#: Canonical scalar spellings (lower-cased) the kind table does not cover.
_EXTRA_SCALARS: Dict[str, str] = {
    "datetime": "utcDateTime", "date-time": "utcDateTime", "timestamp": "utcDateTime",
    "utcdatetime": "utcDateTime", "offsetdatetime": "offsetDateTime", "date": "plainDate",
    "plaindate": "plainDate", "time": "plainTime", "plaintime": "plainTime", "duration": "duration",
    "uri": "url", "url": "url", "decimal": "decimal", "bigdecimal": "decimal", "decimal128": "decimal128",
    "biginteger": "integer", "safeint": "safeint", "numeric": "numeric", "object": "Record<unknown>",
    "map": "Record<unknown>", "dict": "Record<unknown>", "any": "unknown", "json": "unknown",
    "document": "unknown", "unknown": "unknown", "void": "void", "null": "null",
}
#: A string ``format`` with a TypeSpec scalar of its own (otherwise it is kept with ``@format``).
_STRING_FORMATS: Dict[str, str] = {
    "date-time": "utcDateTime", "date": "plainDate", "time": "plainTime", "duration": "duration",
    "uri": "url", "url": "url",
}
#: Spellings that are text without loss (a format TypeSpec writes with ``@format``).
_STRING_LIKE = frozenset({"uuid", "email", "hostname", "ipv4", "ipv6", "char", "uri-reference", "password"})

_NUMERIC = frozenset({"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "safeint",
                      "integer", "float", "float32", "float64", "numeric", "decimal", "decimal128"})
_INTEGRAL = frozenset({"int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "safeint",
                       "integer"})
_VERBS = frozenset({"get", "put", "post", "patch", "delete", "head"})
_JSON = "application/json"
_EVENT_OPERATION_KINDS = frozenset({OperationKind.PUBLISH, OperationKind.SUBSCRIBE})
_IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
_TEMPLATE_RE = re.compile(r"\{([^{}]+)\}")


def typespec_identifier(name: Optional[str], fallback: str = "Unnamed") -> str:
    """A TypeSpec identifier for ``name``: as is when it is one, else in backticks.

    Args:
        name: The source name (``Pet``, ``order-id``, ``model``).
        fallback: Used for an empty name.

    Returns:
        ``Pet``, `` `order-id` ``, `` `model` ``.
    """
    text = (name or "").replace("`", "'") or fallback
    if _IDENT_RE.match(text) and text not in _KEYWORDS:
        return text
    return f"`{text}`"


def _string(value: str) -> str:
    """A TypeSpec string literal (``${`` would start an interpolation, so it is escaped)."""
    return json.dumps(value, ensure_ascii=False).replace("${", "\\${")


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


class TypeSpecFidelityRulePack(WriterLossRulePack):
    """Fidelity rules for TypeSpec export — MFX-15.1 (#3893).

    The pack builds the document with the TypeSpec writer and turns each loss the writer records into a
    verdict on the construct it concerns (:class:`~app.writer_loss_rulepack.WriterLossRulePack`), so the
    report predicts exactly what the export writes. A carried type or operation is ``OK`` and its
    ``target_mapping`` names the declaration it became (``model Pet``, ``op getPet @get /pets/{id}``).
    A non-TypeSpec source's root is reported as rewritten into a TypeSpec namespace; agent descriptors are
    dropped; events, channels, operations on a method TypeSpec has no verb for, duplicate routes and
    parameters it cannot place are dropped; constraints without a decorator, defaults that do not fit and
    numeric enum values beside string ones are dropped; RPC operations given an HTTP route, inlined
    aliases, custom scalars, inline schemas, synthesized path parameters and default-response models are
    approximations.
    """

    target_label = "TypeSpec"
    critical_drops = frozenset({"event-operation-dropped", "operation-dropped", "parameter-dropped",
                                "unsupported-type"})
    info_drops = frozenset({"field-number-dropped"})
    cosmetic = frozenset({"renamed-declaration", "renamed-member", "renamed-operation", "renamed-enum-member"})

    def build_writer(self, api: CanonicalApi) -> "_TypeSpecWriter":
        """Build the document (default options: they change no loss)."""
        self._typespec_source = api.format == "typespec"
        writer = _TypeSpecWriter(api, TypeSpecEmitOptions())
        writer.build()
        return writer

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """A non-TypeSpec source's document, agent descriptors, and losses with no construct."""
        verdicts: List[FidelityVerdict] = []
        if not self._typespec_source:
            verdicts.append(FidelityVerdict.approx(
                message=f"The document is written as the TypeSpec namespace {self._writer.namespace!r} with "
                "@service, @info and @server, and read back as a TypeSpec REST API",
                severity=LossinessSeverity.INFO,
                target_mapping=f"document → namespace {self._writer.namespace}",
            ))
        if api.agents:
            verdicts.append(FidelityVerdict.drop(
                message=f"{self.target_label} has no agent descriptors; {len(api.agents)} agent(s) are not written",
                target_mapping="agents → dropped",
            ))
        return verdicts + self.loss_verdicts(ROOT_CONSTRUCT_KEY)


class TypeSpecEmitOptions(EmitOptions):
    """Per-target options for :class:`TypeSpecEmitter`."""

    include_comments: bool = Field(
        default=True,
        description="Emit a header comment in the generated TypeSpec document.",
    )
    include_http_imports: bool = Field(
        default=True,
        description="Emit the `@typespec/http` (and, for a version, `@typespec/openapi`) imports and `using`s. "
        "Without them the document only compiles where they are added.",
    )


class TypeSpecEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as a Microsoft TypeSpec ``.tsp`` document."""

    key = "typespec"
    format = "typespec"
    label = "TypeSpec"
    description = "Export as a Microsoft TypeSpec API definition (.tsp)."
    icon = "file-code"
    paradigm = ApiParadigm.REST
    multi_file = False
    options_model = TypeSpecEmitOptions

    OUTPUT_MEDIA_TYPE = "text/plain"

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        return CapabilityProfile(
            operations=True,
            events=False,
            unions=True,
            nullability=True,
            constraints=True,
            field_identity=False,
        )

    @classmethod
    def fidelity_rule_pack(cls) -> type[CapabilityRulePack]:
        return TypeSpecFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[TypeSpecEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        options = (
            opts
            if isinstance(opts, TypeSpecEmitOptions)
            else TypeSpecEmitOptions.model_validate(opts.model_dump() if opts else {})
        )
        writer = _TypeSpecWriter(api, options)
        writer.build()
        if not writer.has_declarations():
            raise EmitPreconditionError(
                "TypeSpec export needs at least one type or operation to declare; this source has neither."
            )
        return EmitResult(
            files=[EmittedFile(path=writer.output_path, content=writer.render(), media_type=self.OUTPUT_MEDIA_TYPE)],
            media_type=self.OUTPUT_MEDIA_TYPE,
            provenance=writer.tracker.records(),
            losses=writer.losses.records(),
        )


# ===========================================================================
# Writer
# ===========================================================================


class _Scope:
    """Names declared in one TypeSpec scope (the namespace, a model, an interface …)."""

    def __init__(self, reserved: Optional[Set[str]] = None) -> None:
        self._taken: Set[str] = set(reserved or ())

    def claim(self, name: Optional[str], fallback: str = "Unnamed") -> str:
        """The name for ``name`` here, suffixed ``2``, ``3`` … when already taken."""
        base = (name or "").replace("`", "'") or fallback
        candidate, suffix = base, 2
        while candidate in self._taken:
            candidate, suffix = f"{base}{suffix}", suffix + 1
        self._taken.add(candidate)
        return candidate


class _TypeSpecWriter:
    """Build the TypeSpec document (see the module docstring)."""

    def __init__(self, api: CanonicalApi, options: TypeSpecEmitOptions) -> None:
        self._api = api
        self._options = options
        self._typespec_source = api.format == "typespec"
        self.tracker = ProvenanceTracker()
        self.losses = LossTracker()
        self.namespace = _namespace(api)
        self.output_path = f"{_base_name(api)}.tsp"
        self._types_by_key = {t.key: t for t in api.types}
        self._types_by_name: Dict[str, Type] = {}
        for type_ in api.types:
            self._types_by_name.setdefault(type_.name, type_)
        self._scope = _Scope(_BUILTIN_TYPES)
        #: Type key → declared name; declared name → what it is (``model`` / ``enum`` / ``string`` …).
        self._names: Dict[str, str] = {}
        self._kinds: Dict[str, str] = {}
        self._enum_members: Dict[str, Dict[str, str]] = {}
        #: Key → how it is written (``model Pet``, ``op getPet @get /pets``), for the fidelity pack.
        self._written: Dict[str, str] = {}
        self._header: List[str] = []
        self._declarations: List[List[str]] = []
        self._context: Optional[str] = None
        self._needs_openapi = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Claim every declaration name, then write the types, the interfaces and the header."""
        for type_ in self._api.types:
            name = self._scope.claim(type_.name, "Model")
            self._names[type_.key] = name
            self._kinds[name] = self._declared_kind(type_)
            if name != type_.name:
                self.losses.record(
                    LossKind.INFERRED,
                    "renamed-declaration",
                    f"TypeSpec declaration names are unique in the namespace and unlike a built-in type; "
                    f"{type_.name!r} is written as {name!r}.",
                    pointer=type_.key,
                )
        for type_ in self._api.types:
            self._write_type(type_)
        self._routes: Set[Tuple[str, str]] = set()
        for service in self._api.services:
            self._write_service(service)
        if self._api.channels:
            self.losses.record(LossKind.NA, "channels-dropped", "TypeSpec HTTP has no event channels.",
                               pointer="channels")
        self._write_header()

    def has_declarations(self) -> bool:
        """Whether the document declares anything."""
        return bool(self._declarations)

    def written_as(self, key: str) -> Optional[str]:
        """How the type or operation ``key`` is written, or ``None`` when it is not written."""
        return self._written.get(key)

    def render(self) -> str:
        """The ``.tsp`` text."""
        lines = list(self._header)
        for block in self._declarations:
            lines.append("")
            lines.extend(block)
        return "\n".join(lines).rstrip() + "\n"

    # ------------------------------------------------------------------
    # Document
    # ------------------------------------------------------------------

    def _write_header(self) -> None:
        api = self._api
        lines: List[str] = []
        title = (api.extras.get("typespec_service_title") if self._typespec_source else None) or api.title \
            or api.identity.name
        if self._options.include_comments:
            lines.append(f"// Generated by Apiome from {title or self.namespace}.")
        if api.version:
            self._needs_openapi = True
        if self._options.include_http_imports:
            imports = ['"@typespec/http"'] + (['"@typespec/openapi"'] if self._needs_openapi else [])
            usings = ["TypeSpec.Http"] + (["TypeSpec.OpenAPI"] if self._needs_openapi else [])
            if self._typespec_source:
                for line in api.extras.get("typespec_imports") or []:
                    target = str(line).replace("import", "", 1).strip().rstrip(";").replace("'", '"')
                    if target not in imports:
                        imports.append(target)
                for using in api.extras.get("typespec_usings") or []:
                    if using not in usings:
                        usings.append(str(using))
            lines.extend(f"import {target};" for target in imports)
            lines.append("")
            lines.extend(f"using {using};" for using in usings)
            lines.append("")
        lines.extend(_doc(api.description))
        lines.append(f"@service({{ title: {_string(title)} }})" if title else "@service")
        if api.version:
            lines.append(f"@info({{ version: {_string(api.version)} }})")
        for server in api.servers:
            lines.append(self._server(server))
        lines.append(f"namespace {self.namespace};")
        self._header = lines

    def _server(self, server: Any) -> str:
        description = server.description or server.name or "Server"
        parts = [_string(server.url), _string(description)]
        if server.variables:
            fields = []
            for variable in server.variables:
                default = f" = {_string(str(variable.default))}" if variable.default is not None else ""
                fields.append(f"{typespec_identifier(variable.name)}?: string{default}")
            parts.append("{ " + ", ".join(fields) + " }")
        return f"@server({', '.join(parts)})"

    # ------------------------------------------------------------------
    # Type references
    # ------------------------------------------------------------------

    def _lookup(self, name: Optional[str]) -> Optional[Type]:
        if not name:
            return None
        return self._types_by_key.get(name) or self._types_by_name.get(name)

    def _declared_kind(self, type_: Type) -> str:
        """What a declaration is, for the decorators and defaults that may target it."""
        if type_.kind is TypeKind.RECORD:
            return "model"
        if type_.kind is TypeKind.ENUM:
            return "enum"
        if type_.kind is TypeKind.UNION:
            return "union"
        if type_.kind is TypeKind.MAP:
            return "map"
        if type_.kind is TypeKind.ALIAS and type_.aliased is not None:
            if type_.aliased.item is not None:
                return "array"
            target = self._lookup(type_.aliased.name)
            if target is not None:
                return "alias"
            return _value_kind(self._scalar(type_.aliased.name, _format(type_.constraints), record=False)[0])
        return _value_kind(self._scalar(type_.name, _format(type_.constraints), record=False)[0])

    def _ref(self, ref: Optional[TypeRef], fmt: Optional[str] = None) -> Tuple[str, bool]:
        """The TypeSpec expression for a reference, and whether ``fmt`` was written into it.

        Args:
            ref: The canonical reference (a list, a scalar or a named type).
            fmt: The ``format`` constraint (it picks a number's width or a string scalar such as
                ``utcDateTime``).

        Returns:
            ``(expression, format used)``.
        """
        if ref is None:
            return "void", False
        if ref.item is not None:
            inner, used = self._ref(ref.item, fmt)
            return (f"({inner})[]" if "|" in inner else f"{inner}[]"), used
        target = self._lookup(ref.name)
        if target is not None:
            return typespec_identifier(self._names[target.key]), False
        return self._scalar(ref.name, fmt)

    def _scalar(self, name: Optional[str], fmt: Optional[str] = None, *, record: bool = True) -> Tuple[str, bool]:
        """The TypeSpec scalar for a canonical spelling, and whether ``fmt`` chose it.

        A string ``format`` with a scalar of its own (``date-time`` → ``utcDateTime``) is used; ``integer``
        / ``number`` take their width from it. Anything unknown is ``string`` (reported).
        """
        if not name:
            return "string", False
        lowered = name.lower()
        hint = (fmt or "").lower()
        if lowered in ("string", "str", "text") and hint in _STRING_FORMATS:
            return _STRING_FORMATS[hint], True
        kind = scalar_kind(name, fmt)
        if kind is not None:
            return _TSP_FOR_KIND[kind], lowered in ("integer", "int", "number") and bool(hint)
        if lowered in _EXTRA_SCALARS:
            return _EXTRA_SCALARS[lowered], False
        if name in _BUILTIN_TYPES:
            return name, False
        if lowered in _STRING_LIKE:
            return "string", False
        if record:
            self.losses.record(LossKind.INFERRED, "unknown-type",
                               f"The type {name!r} has no TypeSpec equivalent; it is written as a string.",
                               pointer=self._context)
        return "string", False

    def _kind_of(self, expression: str) -> str:
        """What a written type expression is: ``string``, ``numeric``, ``array``, ``model`` …"""
        if expression.endswith("[]"):
            return "array"
        if expression.startswith("Record<"):
            return "map"
        name = expression.strip("`")
        return self._kinds.get(name) or _value_kind(name)

    # ------------------------------------------------------------------
    # Types
    # ------------------------------------------------------------------

    def _write_type(self, type_: Type) -> None:
        self._context = type_.key
        name = self._names[type_.key]
        ident = typespec_identifier(name)
        lines = _doc(type_.description) + _deprecated(type_.deprecated, "")
        if type_.kind is TypeKind.RECORD:
            lines += [f"model {ident} {{", *self._members(type_), "}"]
            written = f"model {name}"
        elif type_.kind is TypeKind.ENUM:
            lines += [f"enum {ident} {{", *self._enum_members_of(type_, name), "}"]
            written = f"enum {name}"
        elif type_.kind is TypeKind.UNION:
            lines += [f"union {ident} {{", *self._variants(type_), "}"]
            written = f"union {name}"
        elif type_.kind is TypeKind.MAP:
            lines += self._type_decorators(type_, "map")
            lines.append(f"model {ident} is Record<{self._map_value(type_)}>;")
            written = f"model {name} is Record"
        elif type_.kind is TypeKind.ALIAS and type_.aliased is not None and type_.aliased.item is not None:
            expression, _ = self._ref(type_.aliased, _format(type_.constraints))
            lines += self._type_decorators(type_, "array")
            lines.append(f"model {ident} is {expression};")
            written = f"model {name} is {expression}"
        elif type_.kind is TypeKind.ALIAS and type_.aliased is not None and self._lookup(type_.aliased.name):
            expression, _ = self._ref(type_.aliased)
            self.losses.record(
                LossKind.INFERRED,
                "alias-inlined",
                f"A TypeSpec alias of a named type is not a type of its own; {type_.key!r} is written as "
                f"`alias {name} = {expression}` and compiles to {expression}.",
                pointer=type_.key,
            )
            if _has_constraints(type_.constraints):
                self.losses.record(LossKind.NA, "constraint-dropped",
                                   f"An alias carries no decorators; the constraints of {type_.key!r} are not "
                                   "written.", pointer=type_.key)
            lines = _doc(type_.description) + [f"alias {ident} = {expression};"]
            written = f"alias {name}"
        elif type_.kind in (TypeKind.SCALAR, TypeKind.ALIAS):
            source = type_.aliased.name if type_.aliased is not None else type_.name
            base, used = self._scalar(source, _format(type_.constraints), record=False)
            if type_.kind is TypeKind.SCALAR and _is_custom_scalar(type_.name):
                self.losses.record(LossKind.INFERRED, "custom-scalar",
                                   f"TypeSpec has no custom scalar semantics; {type_.key!r} extends string.",
                                   pointer=type_.key)
            if base in ("void", "null", "unknown", "Record<unknown>") or base.startswith("Record"):
                lines += [f"alias {ident} = {base};"]
            else:
                lines += self._type_decorators(type_, _value_kind(base), format_used=used)
                lines.append(f"scalar {ident} extends {base};")
            written = f"scalar {name}"
        else:
            self.losses.record(LossKind.NA, "unsupported-type",
                               f"Type {type_.key!r} ({type_.kind.value}) has no TypeSpec form and is not written.",
                               pointer=type_.key)
            return
        self._declarations.append(lines)
        self._written[type_.key] = written
        self.tracker.record(type_.key, Provenance.SOURCE)

    def _type_decorators(self, type_: Type, kind: str, *, format_used: bool = False) -> List[str]:
        decorators = self._constraint_decorators(type_.constraints, kind, type_.key, format_used=format_used)
        return [" ".join(decorators)] if decorators else []

    def _map_value(self, type_: Type) -> str:
        key = type_.key_type
        if key is not None and self._kind_of(self._ref(key)[0]) not in ("string", "enum"):
            self.losses.record(LossKind.INFERRED, "map-key-as-string",
                               f"TypeSpec records have string keys; the key of {type_.key!r} is written as a string.",
                               pointer=type_.key)
        value, _ = self._ref(type_.value_type or TypeRef(name="unknown"))
        return value

    def _ordered_fields(self, type_: Type) -> List[CanonicalField]:
        indexed = list(enumerate(type_.fields))
        indexed.sort(key=lambda pair: (pair[1].field_number is None, pair[1].field_number or 0, pair[0]))
        ordered = [field for _, field in indexed]
        numbers = [field.field_number for field in ordered]
        if any(n is not None for n in numbers) and numbers != list(range(1, len(numbers) + 1)):
            for field in ordered:
                if field.field_number is not None:
                    self.losses.record(LossKind.NA, "field-number-dropped",
                                       f"TypeSpec has no field numbers; {field.key!r} (number {field.field_number}) "
                                       "is written in number order.", pointer=field.key)
        return ordered

    def _members(self, type_: Type) -> List[str]:
        scope = _Scope()
        lines: List[str] = []
        for field in self._ordered_fields(type_):
            self._context = field.key
            name = scope.claim(field.name, "field")
            if name != field.name:
                self.losses.record(LossKind.INFERRED, "renamed-member",
                                   f"TypeSpec property names are unique in their model; {field.name!r} is written "
                                   f"as {name!r}.", pointer=field.key)
            lines += _doc(field.description, "  ") + _deprecated(field.deprecated, "  ")
            lines.append(f"  {self._property(field, name)};")
            self.tracker.record(field.key, Provenance.SOURCE)
        self._context = type_.key
        return lines

    def _property(self, field: CanonicalField, name: str) -> str:
        """``@decorators name?: Type = default`` for one model property."""
        stored = field.extras.get("typespec_type") if self._typespec_source else None
        fmt = _format(field.constraints)
        if isinstance(stored, str) and stored:
            expression, used = stored, False
        else:
            expression, used = self._ref(field.type, fmt)
        if expression == "void":
            expression = "null"
        decorators: List[str] = []
        if self._typespec_source:
            decorators += [str(d) for d in field.extras.get("typespec_decorators") or []]
        decorators += self._constraint_decorators(field.constraints, self._kind_of(expression), field.key,
                                                  format_used=used)
        stored_optional = field.extras.get("typespec_optional") if self._typespec_source else None
        optional = "?" if (stored_optional if isinstance(stored_optional, bool) else field.type.nullable) else ""
        default = self._default(field.default, expression, field.key)
        prefix = " ".join(decorators) + " " if decorators else ""
        return f"{prefix}{typespec_identifier(name)}{optional}: {expression}{default}"

    def _enum_members_of(self, type_: Type, name: str) -> List[str]:
        """Enum members; a value is written when it differs from the name (all strings, or all numbers)."""
        scope = _Scope()
        values = [v.value for v in type_.enum_values]
        numeric = (not self._typespec_source and values
                   and all(isinstance(v, int) and not isinstance(v, bool) for v in values))
        lines: List[str] = []
        members: Dict[str, str] = {}
        for value in type_.enum_values:
            member = scope.claim(value.name, "VALUE")
            if member != value.name:
                self.losses.record(LossKind.INFERRED, "renamed-enum-member",
                                   f"TypeSpec enum members are unique; {value.name!r} of {type_.key!r} is written as "
                                   f"{member!r}.", pointer=value.key)
            wire = value.value if isinstance(value.value, str) else value.name
            if numeric:
                rendered = f"{typespec_identifier(member)}: {value.value}"
            elif wire != member:
                rendered = f"{typespec_identifier(member)}: {_string(wire)}"
            else:
                rendered = typespec_identifier(member)
            if (not numeric and not self._typespec_source and isinstance(value.value, (int, float))
                    and not isinstance(value.value, bool)):
                self.losses.record(LossKind.NA, "enum-value-dropped",
                                   f"TypeSpec enum values are all strings or all numbers; the value {value.value!r} "
                                   f"of {value.key!r} is written as its name.", pointer=value.key)
            members[str(wire)] = member
            members[value.name] = member
            lines += _doc(value.description, "  ") + _deprecated(value.deprecated, "  ")
            lines.append(f"  {rendered},")
        self._enum_members[name] = members
        return lines

    def _variants(self, type_: Type) -> List[str]:
        lines: List[str] = []
        if type_.fields:
            scope = _Scope()
            for field in type_.fields:
                self._context = field.key
                name = scope.claim(field.name, "variant")
                expression, _ = self._ref(field.type, _format(field.constraints))
                lines += _doc(field.description, "  ")
                lines.append(f"  {typespec_identifier(name)}: {'null' if expression == 'void' else expression},")
                if _has_constraints(field.constraints):
                    self.losses.record(LossKind.NA, "constraint-dropped",
                                       f"A union variant carries no decorators; the constraints of {field.key!r} are "
                                       "not written.", pointer=type_.key)
        else:
            for member in type_.union_members:
                expression, _ = self._ref(TypeRef(name=member))
                lines.append(f"  {'null' if expression == 'void' else expression},")
        self._context = type_.key
        return lines

    def _constraint_decorators(self, constraints: Optional[Constraints], kind: str, pointer: str, *,
                               format_used: bool = False) -> List[str]:
        """Constraint decorators for a target of ``kind``; constraints that do not apply are reported."""
        if constraints is None:
            return []
        out: List[str] = []
        dropped: List[str] = []
        if kind in ("array", "map"):
            pairs = (("minItems", constraints.min_items), ("maxItems", constraints.max_items))
            out += [f"@{name}({int(value)})" for name, value in pairs if value is not None]
            if constraints.min_length is not None or constraints.max_length is not None:
                dropped.append("length")
        else:
            if constraints.min_items is not None or constraints.max_items is not None:
                dropped.append("item count")
            for name, value in (("minLength", constraints.min_length), ("maxLength", constraints.max_length)):
                if value is None:
                    continue
                if kind == "string":
                    out.append(f"@{name}({int(value)})")
                else:
                    dropped.append(name)
        bounds = (("minValue", constraints.minimum), ("maxValue", constraints.maximum),
                  ("minValueExclusive", constraints.exclusive_minimum),
                  ("maxValueExclusive", constraints.exclusive_maximum))
        for name, value in bounds:
            if value is None:
                continue
            if kind == "numeric":
                out.append(f"@{name}({_number(value)})")
            else:
                dropped.append(name)
        if constraints.pattern:
            if kind == "string":
                out.append(f"@pattern({_string(constraints.pattern)})")
            else:
                dropped.append("pattern")
        if constraints.format and not format_used:
            if kind == "string":
                out.append(f"@format({_string(constraints.format)})")
            elif kind not in ("numeric", "temporal"):
                dropped.append("format")
        if constraints.unique_items:
            dropped.append("uniqueItems")
        if constraints.multiple_of is not None:
            dropped.append("multipleOf")
        if constraints.enum:
            dropped.append("enum")
        if dropped:
            self.losses.record(LossKind.NA, "constraint-dropped",
                               f"TypeSpec has no decorator for {', '.join(dropped)} on a {kind}; it is not written "
                               f"for {pointer!r}.", pointer=pointer)
        return out

    def _default(self, value: Any, expression: str, pointer: str) -> str:
        """`` = value`` for a default that fits its type, else ``""`` (reported)."""
        if value is None:
            return ""
        literal = self._value(value, expression)
        if literal is not None:
            return f" = {literal}"
        self.losses.record(LossKind.NA, "default-dropped",
                           f"The default {value!r} of {pointer!r} does not fit its TypeSpec type ({expression}); it "
                           "is not written.", pointer=pointer)
        return ""

    def _value(self, value: Any, expression: str) -> Optional[str]:
        """A TypeSpec value of type ``expression`` for ``value``, or ``None`` when it does not fit."""
        kind = self._kind_of(expression)
        name = expression.strip("`")
        if kind == "enum":
            member = self._enum_members.get(name, {}).get(str(value))
            return f"{typespec_identifier(name)}.{typespec_identifier(member)}" if member else None
        if kind == "boolean" and isinstance(value, bool):
            return "true" if value else "false"
        if kind == "numeric" and isinstance(value, (int, float)) and not isinstance(value, bool):
            if name in _INTEGRAL and not float(value).is_integer():
                return None
            return _number(value)
        if kind == "string" and isinstance(value, str):
            return _string(value)
        if kind == "array" and isinstance(value, list):
            inner = expression[:-2].strip("()")
            items = [self._value(item, inner) for item in value]
            return None if any(item is None for item in items) else "#[" + ", ".join(items) + "]"
        return None

    # ------------------------------------------------------------------
    # Services and operations
    # ------------------------------------------------------------------

    def _write_service(self, service: Service) -> None:
        operations = [op for op in service.operations if self._placeable(op)]
        if not operations:
            return
        name = self._scope.claim(service.name, "Service")
        if name != service.name:
            self.losses.record(LossKind.INFERRED, "renamed-declaration",
                               f"TypeSpec declaration names are unique in the namespace; the service {service.name!r} "
                               f"is written as the interface {name!r}.", pointer=service.key)
        prefix = service.extras.get("typespec_route_prefix") if self._typespec_source else None
        if prefix and not all((op.http_path or "").startswith(prefix) for op in operations):
            prefix = None
        scope = _Scope()
        body: List[str] = []
        error_models: List[List[str]] = []
        for operation in operations:
            line = self._operation(operation, service, scope, prefix, error_models)
            if line:
                body.extend(line)
        lines = _doc(service.description)
        if prefix:
            lines.append(f"@route({_string(prefix)})")
        lines += [f"interface {typespec_identifier(name)} {{", *body, "}"]
        self._declarations.append(lines)
        self._declarations.extend(error_models)
        self.tracker.record(service.key, Provenance.SOURCE)

    def _placeable(self, operation: Operation) -> bool:
        """Whether an operation can be written; an event or a method TypeSpec has no verb for is reported."""
        if operation.kind in _EVENT_OPERATION_KINDS:
            self.losses.record(LossKind.NA, "event-operation-dropped",
                               f"TypeSpec HTTP has no events; {operation.kind.value} operation {operation.key!r} is "
                               "not written.", pointer=operation.key)
            return False
        if operation.http_method and operation.http_method.lower() not in _VERBS:
            self.losses.record(LossKind.NA, "operation-dropped",
                               f"TypeSpec has no {operation.http_method.upper()} verb; {operation.key!r} is not "
                               "written.", pointer=operation.key)
            return False
        return True

    def _operation(self, operation: Operation, service: Service, scope: _Scope, prefix: Optional[str],
                   error_models: List[List[str]]) -> Optional[List[str]]:
        """The lines of one interface operation, or ``None`` when its route repeats another's."""
        self._context = operation.key
        verb, path = self._binding(operation, service)
        route = (verb, _TEMPLATE_RE.sub("{}", path))
        if route in self._routes:
            self.losses.record(LossKind.NA, "operation-dropped",
                               f"TypeSpec allows one operation per route; {operation.key!r} repeats "
                               f"{verb.upper()} {path} and is not written.", pointer=operation.key)
            return None
        self._routes.add(route)
        name = scope.claim(operation.name, "operation")
        if name != operation.name:
            self.losses.record(LossKind.INFERRED, "renamed-operation",
                               f"TypeSpec operation names are unique in their interface; {operation.name!r} is "
                               f"written as {name!r}.", pointer=operation.key)
        if operation.streaming.value != "none":
            self.losses.record(LossKind.NA, "streaming-dropped",
                               f"TypeSpec HTTP has no streams here; {operation.key!r} is one request and response.",
                               pointer=operation.key)
        params = self._parameters(operation, path)
        returns = self._responses(operation, name, error_models)
        decorators = f"@{verb}"
        op_route = self._op_route(operation, path, prefix)
        if op_route is not None:
            decorators += f" @route({_string(op_route)})"
        lines = _doc(operation.description, "  ") + _deprecated(operation.deprecated, "  ")
        lines.append(f"  {decorators} {typespec_identifier(name)}({', '.join(params)}): {returns};")
        self._written[operation.key] = f"op {name} @{verb} {path}"
        self.tracker.record(operation.key, Provenance.SOURCE)
        self._context = None
        return lines

    def _binding(self, operation: Operation, service: Service) -> Tuple[str, str]:
        """``(verb, path)``: the HTTP binding, or ``post /<Service>/<operation>`` for an RPC operation."""
        if operation.http_method:
            path = (operation.http_path or "/").split("?", 1)[0] or "/"
            return operation.http_method.lower(), path if path.startswith("/") else f"/{path}"
        path = "/" + "/".join(re.sub(r"[^A-Za-z0-9._~-]+", "_", part) for part in (service.name, operation.name))
        self.losses.record(LossKind.INFERRED, "rpc-as-http",
                           f"TypeSpec operations here are HTTP; the RPC operation {operation.key!r} is written as "
                           f"POST {path}.", pointer=operation.key)
        return "post", path

    @staticmethod
    def _op_route(operation: Operation, path: str, prefix: Optional[str]) -> Optional[str]:
        """The operation's ``@route``, relative to the interface's ``prefix`` (a TypeSpec source's).

        ``None`` when the prefix followed by the path parameters already is the path — TypeSpec appends
        path parameters missing from a route — so a TypeSpec source's operations keep their own form.
        """
        if prefix is None:
            return path
        names = [p.name for p in operation.parameters if p.location is ParameterLocation.PATH]
        derived = prefix.rstrip("/") + "".join(f"/{{{n}}}" for n in names) if names else prefix
        if derived == path:
            return None
        return path[len(prefix.rstrip("/")):] or "/"

    def _parameters(self, operation: Operation, path: str) -> List[str]:
        """``@path`` / ``@query`` / ``@header`` / ``@cookie`` parameters, then the body."""
        templated = _TEMPLATE_RE.findall(path)
        scope = _Scope()
        out: List[str] = []
        bound: Set[str] = set()
        for param in operation.parameters:
            self._context = param.key
            rendered = self._parameter(param, templated, scope)
            if rendered is None:
                continue
            if param.location is ParameterLocation.PATH:
                bound.add(param.name)
            out.append(rendered)
        for name in templated:
            if name not in bound:
                self.losses.record(LossKind.INFERRED, "path-parameter-synthesized",
                                   f"The route of {operation.key!r} names {{{name}}} but the source declares no such "
                                   "parameter; it is written as a string path parameter.", pointer=operation.key)
                out.append(f"@path {typespec_identifier(scope.claim(name))}: string")
        self._context = operation.key
        request = next((m for m in operation.messages if m.role is MessageRole.REQUEST), None)
        if request is not None and (request.payload is not None or request.payload_schema):
            expression = self._payload(request, operation)
            out += self._content_type(request, expression, scope)
            optional = "" if request.required or self._typespec_source else "?"
            out.append(f"@body {scope.claim('body')}{optional}: {expression}")
        return out

    def _parameter(self, param: Parameter, templated: List[str], scope: _Scope) -> Optional[str]:
        stored = param.extras.get("typespec_type") if self._typespec_source else None
        fmt = _format(param.constraints)
        expression, used = (stored, False) if isinstance(stored, str) and stored else self._ref(param.type, fmt)
        location = param.location
        if location is ParameterLocation.PATH and param.name not in templated:
            self.losses.record(LossKind.NA, "parameter-dropped",
                               f"The path parameter {param.key!r} is not in the route; TypeSpec would add it to the "
                               "path, so it is not written.", pointer=param.key)
            return None
        keeps_name = location in (ParameterLocation.PATH, ParameterLocation.QUERY) or self._typespec_source
        member = scope.claim(param.name if keeps_name else _camel(param.name), "param")
        if location is ParameterLocation.PATH:
            decorator = "@path"
        elif location is ParameterLocation.QUERY:
            decorator = "@query" if member == param.name else f"@query({_string(param.name)})"
        elif self._typespec_source and member == param.name:
            # A TypeSpec source's implicit `@header ifNoneMatch` (sent as `if-none-match`) stays implicit.
            decorator = f"@{location.value}"
        else:
            decorator = f"@{location.value}({_string(param.name)})"
        decorators = [decorator] + self._constraint_decorators(param.constraints, self._kind_of(expression), param.key,
                                                               format_used=used)
        optional = "" if param.required or location is ParameterLocation.PATH else "?"
        default = self._default(param.default, expression, param.key) if optional else ""
        lines = " ".join(decorators)
        return f"{lines} {typespec_identifier(member)}{optional}: {expression}{default}"

    def _content_type(self, message: Message, payload: Optional[str], scope: _Scope) -> List[str]:
        """A ``Content-Type`` header when a body is not JSON (one literal per media type).

        A ``multipart/*`` body must be a model in TypeSpec; for any other payload the multipart media
        types are left out (reported).
        """
        types = [t for t in message.content_types if t]
        if payload is not None and self._kind_of(payload) != "model":
            multipart = [t for t in types if t.lower().startswith("multipart/")]
            if multipart:
                self.losses.record(LossKind.NA, "content-type-dropped",
                                   f"A TypeSpec multipart body must be a model; {', '.join(multipart)} of "
                                   f"{message.key!r} is not written.", pointer=message.key)
                types = [t for t in types if t not in multipart]
        if not types or types == [_JSON]:
            return []
        literal = " | ".join(_string(t) for t in types)
        return [f'@header("Content-Type") {typespec_identifier(scope.claim("contentType"))}: {literal}']

    def _payload(self, message: Message, operation: Operation) -> str:
        if message.payload is not None:
            expression, _ = self._ref(message.payload)
            return "null" if expression == "void" else expression
        self.losses.record(LossKind.INFERRED, "inline-schema",
                           f"The inline schema of {message.key!r} has no named type; it is written as unknown.",
                           pointer=operation.key)
        return "unknown"

    def _responses(self, operation: Operation, name: str, error_models: List[List[str]]) -> str:
        """The return type: the payload for a plain 200, else one variant per response."""
        responses = [m for m in operation.messages if m.role in (MessageRole.RESPONSE, MessageRole.ERROR)]
        if not responses:
            return "void"
        if len(responses) == 1 and _plain(responses[0]):
            return self._payload(responses[0], operation)
        variants: List[str] = []
        seen: Set[str] = set()
        for message in sorted(responses, key=lambda m: (m.role is MessageRole.ERROR, str(m.status_code or ""))):
            status = str(message.status_code or ("default" if message.role is MessageRole.ERROR else "200"))
            if status in seen:
                self.losses.record(LossKind.NA, "response-dropped",
                                   f"{operation.key!r} has two {status} responses; {message.key!r} is not written.",
                                   pointer=operation.key)
                continue
            seen.add(status)
            members = self._response_members(message, operation)
            if status == "default":
                model = self._scope.claim(f"{_capitalized(name)}DefaultResponse", "DefaultResponse")
                self.losses.record(LossKind.INFERRED, "default-response-model",
                                   f"TypeSpec writes a default response as an @error model; {message.key!r} is the "
                                   f"model {model!r}.", pointer=operation.key)
                error_models.append(_doc(message.description or None) + [
                    f"@error model {typespec_identifier(model)} {{", *(f"  {m};" for m in members), "}"])
                variants.append(typespec_identifier(model))
                continue
            if re.fullmatch(r"[1-5]XX", status, flags=re.IGNORECASE):
                low = int(status[0]) * 100
                code = f"@minValue({low}) @maxValue({low + 99}) @statusCode statusCode: int32"
            elif status.isdigit():
                code = f"@statusCode statusCode: {int(status)}"
            else:
                self.losses.record(LossKind.NA, "response-dropped",
                                   f"TypeSpec has no status {status!r}; {message.key!r} is not written.",
                                   pointer=operation.key)
                continue
            variants.append("{ " + "; ".join([code, *members]) + "; }")
        return " | ".join(variants) or "void"

    def _response_members(self, message: Message, operation: Operation) -> List[str]:
        scope = _Scope({"statusCode"})
        payload = self._payload(message, operation) if message.payload is not None or message.payload_schema else None
        members = self._content_type(message, payload, scope)
        if payload is not None:
            members.append(f"@body {scope.claim('body')}: {payload}")
        for header in message.headers:
            expression, _ = self._ref(header.type)
            optional = "?" if header.type.nullable else ""
            member = typespec_identifier(scope.claim(_camel(header.name), "header"))
            members.append(f"@header({_string(header.name)}) {member}{optional}: {expression}")
        return members


# ===========================================================================
# Helpers
# ===========================================================================


def _plain(message: Message) -> bool:
    """Whether a response is the operation's plain return value: a JSON 200 (or status-less) body."""
    status = str(message.status_code or "200")
    return (message.role is MessageRole.RESPONSE and status == "200" and not message.headers
            and (message.payload is not None or bool(message.payload_schema))
            and message.content_types in ([], [_JSON]))


def _value_kind(expression: str) -> str:
    """The kind of a built-in TypeSpec type."""
    if expression in _NUMERIC:
        return "numeric"
    if expression in ("string", "url"):
        return "string"
    if expression == "boolean":
        return "boolean"
    if expression in ("utcDateTime", "offsetDateTime", "plainDate", "plainTime", "duration"):
        return "temporal"
    if expression == "bytes":
        return "bytes"
    return "other"


def _format(constraints: Optional[Constraints]) -> Optional[str]:
    return constraints.format if constraints is not None else None


def _has_constraints(constraints: Optional[Constraints]) -> bool:
    return constraints is not None and bool(constraints.model_dump(exclude={"extras"}, exclude_none=True))


def _is_custom_scalar(name: str) -> bool:
    """Whether a named scalar has no TypeSpec scalar of its own (it extends ``string``)."""
    lowered = name.lower()
    return (scalar_kind(name) is None and lowered not in _EXTRA_SCALARS and name not in _BUILTIN_TYPES
            and lowered not in _STRING_LIKE and lowered not in _STRING_FORMATS)


def _doc(text: Optional[str], indent: str = "") -> List[str]:
    """A ``/** … */`` doc comment (``*/`` inside the text is broken up)."""
    if not text or not text.strip():
        return []
    body = text.strip().replace("*/", "*\\/").splitlines()
    if len(body) == 1:
        return [f"{indent}/** {body[0]} */"]
    return [f"{indent}/**", *(f"{indent} * {line}".rstrip() for line in body), f"{indent} */"]


def _deprecated(flag: bool, indent: str) -> List[str]:
    return [f'{indent}#deprecated "Deprecated."'] if flag else []


def _camel(name: str) -> str:
    """A header or cookie name as a property name: ``X-Request-Id`` → ``xRequestId``."""
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", name) if p]
    if not parts:
        return "param"
    head, *rest = parts
    text = head[:1].lower() + head[1:] + "".join(p[:1].upper() + p[1:] for p in rest)
    return f"n{text}" if text[0].isdigit() else text


def _capitalized(name: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "Operation"
    return text[:1].upper() + text[1:]


def _namespace(api: CanonicalApi) -> str:
    """A TypeSpec namespace: identifiers joined by ``.``."""
    raw = api.extras.get("typespec_namespace") if api.format == "typespec" else None
    raw = raw or api.identity.namespace or api.identity.name or api.title or "Exported"
    raw = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", str(raw))
    parts = []
    for part in re.split(r"::|[./:\\#\s]+", raw):
        ident = re.sub(r"[^A-Za-z0-9_]+", "_", part).strip("_")
        if ident:
            parts.append(f"N{ident}" if ident[0].isdigit() else ident)
    return ".".join(f"{p}_" if p in _KEYWORDS else p for p in parts) or "Exported"


def _base_name(api: CanonicalApi) -> str:
    base = api.identity.namespace or api.identity.name or api.title or "api"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", base).strip("_") or "api"


def validate_typespec_document(content: str) -> None:
    """Validate TypeSpec text by re-parsing it with the built-in reader (no compiler needed)."""
    parse_typespec(content)

