"""Canonical model → MCP tool definitions — AGX-1.1 (#4529).

The compiler behind "a published API as governed MCP tools". Given the canonical model of
one published version, it produces the **toolset** an agent sees: one MCP tool per exposed
operation, each with a name, a description (including what a successful call returns), and
an ``inputSchema`` that every MCP host accepts.

Pipeline::

    CanonicalApi ──normalize_ordering──▶ project_tools (app.tool_projection)
        ──▶ keep the exposed operations
        ──▶ per tool: MCP validity pass on the input schema
                      + output description from the 2xx response
        ──▶ validate every tool ──▶ McpToolset (deterministic)

One mapping, several packagings
-------------------------------

Name derivation, description assembly and argument flattening are **not** decided here:
they come from :mod:`app.tool_projection`, the shared middle the LLM tool-array emitter
(FMT-2.5) also renders. This module adds only what is specific to MCP — the portable
JSON-Schema keyword subset, the tool's output description, exposure, and the deterministic
toolset envelope. The managed invocation runtime (``apiome_mcp.tool_compiler``, AGX-2.1),
the MCP tool-definition emitter (MFX-32.1, #4295) and the generated MCP server artifact
(SDK-4.5, #4499) all compile through :func:`compile_mcp_tools`, so they cannot disagree
about what a tool is called or what it takes.

Guarantees
----------

* **Deterministic.** The model is order-normalized first, every walk is over lists or
  insertion-ordered dicts built here, and :meth:`McpToolset.serialize` sorts keys — the
  same spec always produces a byte-identical toolset (the AGX-1.4 golden contract).
* **Collision-stable names.** Names are derived over *every* callable operation of the
  version, and only then filtered to the exposed ones, so turning one operation on or off
  (AGX-1.2 curation) never renames another tool.
* **MCP-valid.** Every emitted schema holds only :data:`MCP_SCHEMA_KEYWORDS`; every
  keyword outside it is downgraded to a portable equivalent or dropped, and each change is
  reported as a loss. :func:`validate_mcp_tool` re-checks every tool before the toolset is
  returned, so an invalid toolset cannot ship.
* **Operations only.** A model with no callable operation compiles to an empty toolset —
  the schema-only fallback :func:`app.tool_projection.project_tools` offers a tool-array
  export does not apply, because an agent tool must invoke something.

The output schema is carried on :class:`McpToolOutput` but deliberately **not** rendered as
MCP ``outputSchema``: a server that advertises one must return conforming
``structuredContent`` on every call, which only the invocation proxy (AGX-2.1) can promise.
What a successful call returns reaches the agent through the tool description instead.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from .canonical_model import CanonicalApi, Message, MessageRole, Operation, TypeRef
from .emitter import Loss, LossKind, LossTracker, ProvenanceTracker
from .normalizer import normalize_ordering
from .tool_projection import (
    DEPRECATION_PREFIX,
    LOSS_CREDENTIAL_REDACTED,
    LOSS_REQUIRED_WITHOUT_PROPERTY,
    LOSS_RESPONSE_SCHEMA,
    LOSS_SCHEMA_CYCLE,
    TOOL_NAME_PATTERN,
    ToolDefinition,
    ToolSchemaBuilder,
    project_tools,
    scrub_credentials,
    selectable_operations,
)

__all__ = [
    "JSON_SCHEMA_TYPES",
    "LOSS_MCP_KEYWORD_DOWNGRADED",
    "LOSS_MCP_KEYWORD_DROPPED",
    "LOSS_MCP_ROOT_COMBINATOR",
    "LOSS_MCP_UNRESOLVED_REF",
    "MCP_SCHEMA_KEYWORDS",
    "MCP_TOOL_MAPPING_VERSION",
    "McpToolDefinition",
    "McpToolMappingError",
    "McpToolOutput",
    "McpToolset",
    "UnknownOperationError",
    "compile_mcp_tools",
    "mcp_schema_violations",
    "sanitize_mcp_schema",
    "success_response",
    "validate_mcp_tool",
]


# ===========================================================================
# Contract constants
# ===========================================================================

#: Version of the operation→tool mapping. Bump it whenever a change to this module or to
#: :mod:`app.tool_projection` alters compiled output for an unchanged spec, so a stored or
#: golden toolset (AGX-1.2, AGX-1.4) can tell "the spec changed" from "the compiler did".
MCP_TOOL_MAPPING_VERSION = 1

#: The JSON-Schema keywords an emitted MCP schema may carry: the portable core that MCP
#: hosts (Claude Desktop, IDE clients, and the model APIs behind them) accept in a tool's
#: ``inputSchema``. Composition is limited to ``anyOf``; references, definitions,
#: conditionals, tuple forms and vendor extensions are not in it.
MCP_SCHEMA_KEYWORDS: frozenset = frozenset(
    {
        "additionalProperties",
        "anyOf",
        "default",
        "description",
        "enum",
        "examples",
        "exclusiveMaximum",
        "exclusiveMinimum",
        "format",
        "items",
        "maxItems",
        "maxLength",
        "maxProperties",
        "maximum",
        "minItems",
        "minLength",
        "minProperties",
        "minimum",
        "multipleOf",
        "pattern",
        "properties",
        "required",
        "title",
        "type",
        "uniqueItems",
    }
)

#: The JSON-Schema simple type names; any other ``type`` value (``file``, ``binary``) is
#: not a JSON-Schema type at all.
JSON_SCHEMA_TYPES: frozenset = frozenset(
    {"array", "boolean", "integer", "null", "number", "object", "string"}
)

#: Keywords whose value must be a non-negative integer.
_NON_NEGATIVE_INT_KEYWORDS = frozenset(
    {"maxItems", "maxLength", "maxProperties", "minItems", "minLength", "minProperties"}
)

#: Keywords whose value must be a number.
_NUMBER_KEYWORDS = frozenset({"exclusiveMaximum", "exclusiveMinimum", "maximum", "minimum"})

#: Keywords whose value must be a string.
_STRING_KEYWORDS = frozenset({"description", "format", "pattern", "title"})

#: Keywords whose value must be an array.
_ARRAY_KEYWORDS = frozenset({"enum", "examples"})

#: An explicit 2xx status code (``200``, ``201``, …).
_EXPLICIT_SUCCESS = re.compile(r"^2\d\d$")

#: The OpenAPI wildcard for the whole success range.
_SUCCESS_RANGE = "2XX"


# ===========================================================================
# Loss subjects
# ===========================================================================

LOSS_MCP_KEYWORD_DROPPED = "mcp-keyword-dropped"
LOSS_MCP_KEYWORD_DOWNGRADED = "mcp-keyword-downgraded"
LOSS_MCP_UNRESOLVED_REF = "mcp-unresolved-ref"
LOSS_MCP_ROOT_COMBINATOR = "mcp-root-combinator-dropped"


# ===========================================================================
# Errors
# ===========================================================================


class McpToolMappingError(ValueError):
    """Raised when a model cannot be compiled into a valid MCP toolset."""


class UnknownOperationError(McpToolMappingError):
    """Raised when an exposed operation key names no callable operation of the model.

    Attributes:
        keys: The offending keys, sorted.
    """

    def __init__(self, keys: Iterable[str]) -> None:
        self.keys: Tuple[str, ...] = tuple(sorted(keys))
        super().__init__(
            "Exposed operation(s) are not callable operations of this version: "
            + ", ".join(repr(key) for key in self.keys)
        )


# ===========================================================================
# Compiled toolset
# ===========================================================================


@dataclass(frozen=True)
class McpToolOutput:
    """What a successful call of a tool returns, derived from its 2xx response.

    Attributes:
        status: The success status code (``200``, ``2XX``), or ``None`` for a paradigm
            without HTTP status codes.
        description: The response's own description, credential-scrubbed, or ``None``.
        media_type: The preferred media type of the body (JSON first), or ``None``.
        schema: The body's schema — self-contained and MCP-valid — or ``None`` when the
            response has no body.
        shape: A short phrase for the body's shape (``array of Pet``), or ``None``.
    """

    status: Optional[str]
    description: Optional[str]
    media_type: Optional[str]
    schema: Optional[Dict[str, Any]]
    shape: Optional[str]

    def summary(self) -> str:
        """Render the one-line "Returns …" sentence appended to the tool description.

        Returns:
            For example ``Returns HTTP 200 application/json (array of Pet): Success`` or
            ``Returns HTTP 204 with no body: Deleted``.
        """
        parts: List[str] = []
        if self.status:
            parts.append(f"HTTP {self.status}")
        if self.media_type:
            parts.append(self.media_type)
        elif self.schema is None:
            parts.append("with no body")
        if self.shape:
            parts.append(f"({self.shape})" if parts else self.shape)
        head = " ".join(["Returns", *parts])
        return f"{head}: {self.description}" if self.description else f"{head}."

    def to_dict(self) -> Dict[str, Any]:
        """Return the JSON form (``None`` fields omitted)."""
        fields = {
            "status": self.status,
            "description": self.description,
            "mediaType": self.media_type,
            "schema": self.schema,
            "shape": self.shape,
        }
        return {key: value for key, value in fields.items() if value is not None}


@dataclass(frozen=True)
class McpToolDefinition:
    """One compiled MCP tool.

    Attributes:
        name: The tool name — charset-legal, unique in the toolset, stable across runs.
        description: What the model reads when choosing the tool (summary, description,
            and the output sentence), or ``None`` when the source documents nothing.
        input_schema: The MCP-valid argument object.
        output: What a successful call returns, or ``None`` without a success response.
        operation: Canonical key of the operation the tool invokes (``GET /pets/{id}``) —
            the reference curation (AGX-1.2) and invocation (AGX-2.1) resolve it by.
    """

    name: str
    description: Optional[str]
    input_schema: Dict[str, Any]
    output: Optional[McpToolOutput]
    operation: str

    def to_mcp(self) -> Dict[str, Any]:
        """Return the MCP ``tools/list`` entry: ``{name, description?, inputSchema}``."""
        entry: Dict[str, Any] = {"name": self.name}
        if self.description:
            entry["description"] = self.description
        entry["inputSchema"] = self.input_schema
        return entry

    def to_dict(self) -> Dict[str, Any]:
        """Return the full compiled form: the MCP entry plus output and operation."""
        data = self.to_mcp()
        data["operation"] = self.operation
        if self.output is not None:
            data["output"] = self.output.to_dict()
        return data


@dataclass(frozen=True)
class McpToolset:
    """The compiled toolset of one version.

    Attributes:
        tools: The tools, in canonical order (services, then operations, by key).
        losses: Every construct the compile could not carry faithfully, restricted to the
            exposed operations plus document-level notes (why an operation is not callable
            at all, for instance). Not part of :meth:`serialize`, so rewording a loss never
            changes a golden.
    """

    tools: Tuple[McpToolDefinition, ...]
    losses: Tuple[Loss, ...] = ()

    def mcp_tools(self) -> List[Dict[str, Any]]:
        """Return the MCP ``tools/list`` entries, in order."""
        return [tool.to_mcp() for tool in self.tools]

    def to_dict(self) -> Dict[str, Any]:
        """Return the JSON form: mapping version plus every compiled tool."""
        return {
            "mappingVersion": MCP_TOOL_MAPPING_VERSION,
            "tools": [tool.to_dict() for tool in self.tools],
        }

    def serialize(self) -> str:
        """Return the canonical JSON text — byte-identical for the same spec.

        Keys are sorted, indentation is fixed and the text ends with a newline, so the
        output is independent of dict construction order and diffs cleanly as a golden.
        """
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    def fingerprint(self) -> str:
        """Return the SHA-256 hex digest of :meth:`serialize`."""
        return hashlib.sha256(self.serialize().encode("utf-8")).hexdigest()


# ===========================================================================
# MCP validity pass
# ===========================================================================


class _McpSchemaSanitizer:
    """Rewrite one schema into the MCP keyword subset, collecting what it changed.

    Walks schema *positions* only — a ``properties`` map holds property names, not
    keywords, so a property called ``type`` or ``items`` is never mistaken for one.
    Changes are aggregated and recorded once per schema by :meth:`record`, which keeps a
    large toolset's loss list readable.

    Args:
        subject: Canonical coordinate the recorded losses point at.
    """

    def __init__(self, *, subject: str) -> None:
        self._subject = subject
        self._dropped: Set[str] = set()
        self._downgraded: Set[str] = set()
        self._refs: Set[str] = set()
        self._orphaned: Set[str] = set()
        self._root_combinator = False

    # --- entry points -------------------------------------------------------

    def arguments(self, schema: Any) -> Dict[str, Any]:
        """Sanitize a tool's argument object and enforce the root rules.

        MCP hosts require the argument schema to *be* an object with ``properties``, and
        the model APIs behind them reject a composition at the root, so a root ``anyOf``
        (which is also where a root ``oneOf`` lands) is dropped.
        """
        result = self.schema(schema)
        if "anyOf" in result:
            del result["anyOf"]
            self._root_combinator = True
        result["type"] = "object"
        if not isinstance(result.get("properties"), dict):
            result["properties"] = {}
        return result

    def schema(self, node: Any) -> Dict[str, Any]:
        """Sanitize a schema of any shape (a boolean ``false`` becomes ``{}``)."""
        result = self._node(node)
        return {} if result is None else result

    def record(self, losses: LossTracker) -> None:
        """Record every change this sanitizer made as losses on ``losses``."""
        subject = self._subject
        if self._dropped:
            losses.record(
                LossKind.NA,
                LOSS_MCP_KEYWORD_DROPPED,
                f"Keyword(s) {_quoted(self._dropped)} under {subject!r} are outside the "
                "JSON-Schema subset MCP hosts accept and were dropped.",
                pointer=subject,
            )
        if self._downgraded:
            losses.record(
                LossKind.INFERRED,
                LOSS_MCP_KEYWORD_DOWNGRADED,
                f"Keyword(s) {_quoted(self._downgraded)} under {subject!r} were rewritten "
                "into their portable MCP equivalents.",
                pointer=subject,
            )
        if self._refs:
            losses.record(
                LossKind.NA,
                LOSS_MCP_UNRESOLVED_REF,
                f"Reference(s) {_quoted(self._refs)} under {subject!r} point at no type "
                "the model defines; an MCP schema is self-contained, so each became a "
                "free-form node.",
                pointer=subject,
            )
        if self._orphaned:
            losses.record(
                LossKind.NA,
                LOSS_REQUIRED_WITHOUT_PROPERTY,
                f"Required name(s) {_quoted(self._orphaned)} under {subject!r} have no "
                "declared property behind them, so the requirement was dropped.",
                pointer=subject,
            )
        if self._root_combinator:
            losses.record(
                LossKind.NA,
                LOSS_MCP_ROOT_COMBINATOR,
                f"The argument object of {subject!r} is a composition of alternatives; "
                "MCP hosts reject a composition at the root, so it was dropped and the "
                "arguments are described by their properties alone.",
                pointer=subject,
            )

    # --- the walk -----------------------------------------------------------

    def _node(self, node: Any) -> Optional[Dict[str, Any]]:
        """Sanitize one schema node; ``None`` means "matches nothing" (``false``)."""
        if node is True:
            return {}
        if node is False:
            return None
        if not isinstance(node, dict):
            self._dropped.add(f"non-schema value {type(node).__name__}")
            return {}

        work = self._downgrade(dict(node))
        out: Dict[str, Any] = {}
        for key, value in work.items():
            if key not in MCP_SCHEMA_KEYWORDS:
                self._dropped.add(key)
                continue
            kept = self._keyword(key, value)
            if kept is not _DROP:
                out[key] = kept
        self._reconcile_required(out)
        return out

    def _downgrade(self, work: Dict[str, Any]) -> Dict[str, Any]:
        """Rewrite non-portable keywords into portable ones, in place, and return ``work``."""
        ref = work.pop("$ref", None)
        if ref is not None:
            self._refs.add(str(ref))

        while "allOf" in work:
            branches = work.pop("allOf")
            self._downgraded.add("allOf (merged)")
            if isinstance(branches, list):
                for branch in branches:
                    if isinstance(branch, dict) and "$ref" in branch:
                        # Anything still a ref here resolved nowhere upstream.
                        self._refs.add(str(branch["$ref"]))
                        branch = {key: value for key, value in branch.items() if key != "$ref"}
                    _merge_branch(work, branch)

        if "oneOf" in work:
            alternatives = work.pop("oneOf")
            if "anyOf" in work:
                self._dropped.add("oneOf")
            else:
                work["anyOf"] = alternatives
                self._downgraded.add("oneOf (as anyOf)")

        if "const" in work:
            value = work.pop("const")
            if "enum" in work:
                self._dropped.add("const")
            else:
                work["enum"] = [value]
                self._downgraded.add("const (as enum)")

        if work.pop("nullable", False) is True:
            _widen_to_null(work)
            self._downgraded.add("nullable (as a null type)")

        if "example" in work:
            value = work.pop("example")
            if "examples" in work:
                self._dropped.add("example")
            else:
                work["examples"] = [value]
                self._downgraded.add("example (as examples)")

        for exclusive, bound in (("exclusiveMinimum", "minimum"), ("exclusiveMaximum", "maximum")):
            flag = work.get(exclusive)
            if isinstance(flag, bool):
                del work[exclusive]
                if flag and _is_number(work.get(bound)):
                    work[exclusive] = work.pop(bound)
                    self._downgraded.add(f"{exclusive} (boolean form)")

        if work.pop("deprecated", False) is True:
            existing = work.get("description")
            text = existing.strip() if isinstance(existing, str) else ""
            # The marker :func:`app.tool_projection.assemble_tool_description` puts on a tool.
            work["description"] = f"{DEPRECATION_PREFIX} {text}" if text else DEPRECATION_PREFIX
            self._downgraded.add("deprecated (as a description marker)")

        return work

    def _keyword(self, key: str, value: Any) -> Any:
        """Sanitize one allowed keyword's value, or return :data:`_DROP`."""
        if key == "properties":
            if not isinstance(value, dict):
                return self._drop(key)
            properties: Dict[str, Any] = {}
            for name, child in value.items():
                sanitized = self._node(child)
                if sanitized is None:
                    # ``false``: the property may never be present, so it is not an argument.
                    self._dropped.add(f"false schema for property {name!r}")
                    continue
                properties[name] = sanitized
            return properties
        if key == "items":
            if isinstance(value, dict) or value is True:
                return self.schema(value)
            return self._drop("items (tuple or false form)")
        if key == "additionalProperties":
            if isinstance(value, bool):
                return value
            if isinstance(value, dict):
                return self.schema(value)
            return self._drop(key)
        if key == "anyOf":
            if not isinstance(value, list):
                return self._drop(key)
            branches = [branch for branch in map(self._node, value) if branch is not None]
            return branches if branches else self._drop(key)
        if key == "type":
            return self._type(value)
        if key == "required":
            if not isinstance(value, list):
                return self._drop(key)
            return list(dict.fromkeys(name for name in value if isinstance(name, str)))
        if key in _STRING_KEYWORDS:
            return value if isinstance(value, str) else self._drop(key)
        if key in _ARRAY_KEYWORDS:
            return copy.deepcopy(value) if isinstance(value, list) else self._drop(key)
        if key in _NON_NEGATIVE_INT_KEYWORDS:
            if _is_number(value) and float(value).is_integer() and value >= 0:
                return int(value)
            return self._drop(key)
        if key in _NUMBER_KEYWORDS:
            return value if _is_number(value) else self._drop(key)
        if key == "multipleOf":
            return value if _is_number(value) and value > 0 else self._drop(key)
        if key == "uniqueItems":
            return value if isinstance(value, bool) else self._drop(key)
        return copy.deepcopy(value)  # default: any JSON value

    def _type(self, value: Any) -> Any:
        """Keep only JSON-Schema type names; drop the keyword when none survive."""
        if isinstance(value, str):
            if _is_type_name(value):
                return value
            return self._drop(f"type {value!r}")
        if isinstance(value, list):
            kept = list(dict.fromkeys(item for item in value if _is_type_name(item)))
            rejected = [item for item in value if not _is_type_name(item)]
            if rejected:
                self._dropped.add(f"type {rejected!r}")
            return kept if kept else _DROP
        return self._drop("type")

    def _reconcile_required(self, out: Dict[str, Any]) -> None:
        """Drop ``required`` names with no property behind them (hosts reject them)."""
        required = out.get("required")
        if not isinstance(required, list):
            return
        properties = out.get("properties")
        declared = set(properties) if isinstance(properties, dict) else set()
        kept = [name for name in required if name in declared]
        self._orphaned.update(name for name in required if name not in declared)
        if kept:
            out["required"] = kept
        else:
            del out["required"]

    def _drop(self, label: str) -> Any:
        """Note that ``label`` was dropped and return the drop sentinel."""
        self._dropped.add(label)
        return _DROP


#: Sentinel a keyword handler returns to drop the keyword.
_DROP: Any = object()


def _merge_branch(target: Dict[str, Any], branch: Any) -> None:
    """Merge one ``allOf`` branch into ``target`` (the node that carried the ``allOf``).

    ``properties`` are unioned (the first declaration of a name wins) and ``required`` is
    unioned in order; every other keyword is taken from the branch only when ``target``
    does not already set it. A nested ``allOf`` lands back on ``target`` and is merged by
    the caller's loop. The result is never *stricter* than the conjunction it replaces,
    which is the safe direction for an argument schema: the upstream still validates.

    ``target`` is the walk's own shallow copy of a node; every merged container is a new
    object assigned onto it, so the caller's input is never mutated.
    """
    if not isinstance(branch, dict):
        return
    for key, value in branch.items():
        existing = target.get(key)
        if key == "properties" and isinstance(value, dict):
            merged = dict(existing) if isinstance(existing, dict) else {}
            for name, schema in value.items():
                merged.setdefault(name, schema)
            target["properties"] = merged
        elif key == "required" and isinstance(value, list):
            names = [*(existing if isinstance(existing, list) else []), *value]
            target["required"] = list(dict.fromkeys(n for n in names if isinstance(n, str)))
        elif key == "allOf" and isinstance(value, list):
            pending = list(existing) if isinstance(existing, list) else []
            target["allOf"] = [*pending, *value]
        else:
            target.setdefault(key, value)


def _widen_to_null(work: Dict[str, Any]) -> None:
    """Let a schema accept ``null`` (the OpenAPI 3.0 ``nullable: true`` meaning)."""
    declared = work.get("type")
    if isinstance(declared, str) and declared != "null":
        work["type"] = [declared, "null"]
    elif isinstance(declared, list) and "null" not in declared:
        work["type"] = [*declared, "null"]
    # An untyped schema already accepts null; nothing to widen.


def _is_type_name(value: Any) -> bool:
    """Whether ``value`` is one of the JSON-Schema simple type names."""
    return isinstance(value, str) and value in JSON_SCHEMA_TYPES


def _is_number(value: Any) -> bool:
    """Whether ``value`` is a JSON number (``bool`` is not, despite being an ``int``)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _quoted(names: Iterable[str]) -> str:
    """Render a set of names as a sorted, quoted, comma-separated list."""
    return ", ".join(repr(name) for name in sorted(names))


#: Where a self-contained JSON Schema document keeps the definitions its refs point at.
_LOCAL_DEFINITION_KEYWORDS: Tuple[str, ...] = ("$defs", "definitions")


def _resolve_local_refs(schema: Any, losses: LossTracker, subject: str) -> Any:
    """Inline refs into the schema's *own* ``$defs`` / ``definitions`` sections.

    A schema that arrived verbatim — an imported tool bundle's argument object, which the
    shared projection deliberately passes through untouched — may be a small JSON Schema
    document with definitions of its own. MCP hosts do not reliably resolve ``$ref``, so the
    definitions are inlined here (the target merged under any sibling keywords) and the
    definition sections removed. A ref that revisits a definition already being inlined is
    a cycle a self-contained schema cannot express; it becomes a free-form node, reported
    as :data:`app.tool_projection.LOSS_SCHEMA_CYCLE`. A ref this document does not define
    is left for the validity pass to report.

    Args:
        schema: The schema document (not mutated).
        losses: Sink for cycle reports.
        subject: Canonical coordinate the losses point at.

    Returns:
        A new document with every local ref inlined, or ``schema`` itself when it has no
        definition section.
    """
    if not isinstance(schema, dict):
        return schema
    definitions: Dict[str, Any] = {}
    for keyword in _LOCAL_DEFINITION_KEYWORDS:
        section = schema.get(keyword)
        if isinstance(section, dict):
            for name, target in section.items():
                definitions[f"#/{keyword}/{name}"] = target
    if not definitions:
        return schema

    cycles: Set[str] = set()

    def resolve(node: Any, stack: Tuple[str, ...]) -> Any:
        if isinstance(node, list):
            return [resolve(item, stack) for item in node]
        if not isinstance(node, dict):
            return node
        ref = node.get("$ref")
        if isinstance(ref, str) and ref in definitions:
            if ref in stack:
                cycles.add(ref)
                return {}
            target = definitions[ref]
            merged = dict(target) if isinstance(target, dict) else {}
            merged.update({key: value for key, value in node.items() if key != "$ref"})
            return resolve(merged, stack + (ref,))
        return {key: resolve(value, stack) for key, value in node.items()}

    body = {key: value for key, value in schema.items() if key not in _LOCAL_DEFINITION_KEYWORDS}
    resolved = resolve(body, ())
    if cycles:
        losses.record(
            LossKind.NA,
            LOSS_SCHEMA_CYCLE,
            f"Definition(s) {_quoted(cycles)} under {subject!r} refer back to themselves; an "
            "MCP schema is self-contained and cannot express the cycle, so each recursion "
            "point became a free-form node.",
            pointer=subject,
        )
    return resolved


def sanitize_mcp_schema(
    schema: Any,
    *,
    losses: LossTracker,
    subject: str,
    arguments: bool = False,
) -> Dict[str, Any]:
    """Rewrite ``schema`` into the MCP keyword subset (:data:`MCP_SCHEMA_KEYWORDS`).

    Refs into the schema's own ``$defs`` / ``definitions`` are inlined first (see
    :func:`_resolve_local_refs`), so a self-contained document keeps its structure.

    Downgrades keep a construct's meaning in a portable spelling — ``oneOf`` → ``anyOf``,
    ``allOf`` merged into its parent, ``const`` → a one-value ``enum``, OpenAPI 3.0
    ``nullable: true`` → a ``null`` type, ``example`` → ``examples``, boolean
    ``exclusiveMinimum``/``exclusiveMaximum`` → the numeric form, ``deprecated`` → a
    description marker. Everything else outside the subset (``$ref``, ``$defs``, ``not``,
    conditionals, tuple forms, ``readOnly``, ``discriminator``, ``xml``, ``x-*`` …) is
    dropped, which only ever *widens* what the schema accepts. The input is not mutated.

    Args:
        schema: The schema to sanitize.
        losses: Sink the changes are recorded on.
        subject: Canonical coordinate the losses point at.
        arguments: Whether ``schema`` is a tool's argument object, which additionally must
            be a ``type: object`` root with ``properties`` and no root composition.

    Returns:
        A new, MCP-valid schema.
    """
    sanitizer = _McpSchemaSanitizer(subject=subject)
    document = _resolve_local_refs(schema, losses, subject)
    result = sanitizer.arguments(document) if arguments else sanitizer.schema(document)
    sanitizer.record(losses)
    return result


# ===========================================================================
# Validation
# ===========================================================================


def mcp_schema_violations(schema: Any, *, pointer: str = "") -> List[str]:
    """List every way ``schema`` falls outside the MCP keyword subset.

    Args:
        schema: The schema to check.
        pointer: JSON Pointer prefix for the messages (the schema's location).

    Returns:
        ``"<pointer>: <problem>"`` strings; empty when the schema is valid.
    """
    problems: List[str] = []
    _check_schema(schema, pointer, problems)
    return problems


def _check_schema(node: Any, pointer: str, problems: List[str]) -> None:
    """Append the violations of one schema node (and its children) to ``problems``."""
    if not isinstance(node, dict):
        problems.append(f"{pointer or '/'}: a schema must be an object")
        return
    properties = node.get("properties")
    for key, value in node.items():
        here = ProvenanceTracker.child(pointer, key)
        if key not in MCP_SCHEMA_KEYWORDS:
            problems.append(f"{here}: keyword {key!r} is outside the MCP schema subset")
        elif key == "properties":
            if not isinstance(value, dict):
                problems.append(f"{here}: must be an object")
                continue
            for name, child in value.items():
                _check_schema(child, ProvenanceTracker.child(here, name), problems)
        elif key == "items":
            _check_schema(value, here, problems)
        elif key == "additionalProperties" and not isinstance(value, bool):
            _check_schema(value, here, problems)
        elif key == "anyOf":
            if not isinstance(value, list) or not value:
                problems.append(f"{here}: must be a non-empty array")
                continue
            for index, branch in enumerate(value):
                _check_schema(branch, ProvenanceTracker.child(here, str(index)), problems)
        elif key == "type":
            names = value if isinstance(value, list) else [value]
            if not names or not all(_is_type_name(name) for name in names):
                problems.append(f"{here}: {value!r} is not a JSON-Schema type")
        elif key == "required":
            if not isinstance(value, list) or not all(isinstance(name, str) for name in value):
                problems.append(f"{here}: must be an array of strings")
                continue
            declared = set(properties) if isinstance(properties, dict) else set()
            missing = [name for name in value if name not in declared]
            if missing:
                problems.append(f"{here}: {missing!r} name no declared property")


def validate_mcp_tool(entry: Mapping[str, Any]) -> List[str]:
    """Check one MCP ``tools/list`` entry against the compiler's contract.

    Args:
        entry: A ``{name, description?, inputSchema}`` mapping (:meth:`McpToolDefinition.to_mcp`).

    Returns:
        Human-readable violations; empty when the entry is valid.
    """
    problems: List[str] = []
    name = entry.get("name")
    if not isinstance(name, str) or not TOOL_NAME_PATTERN.fullmatch(name):
        problems.append(f"/name: {name!r} does not match {TOOL_NAME_PATTERN.pattern}")
    if "description" in entry:
        description = entry["description"]
        if not isinstance(description, str) or not description.strip():
            problems.append("/description: must be a non-empty string when present")
    schema = entry.get("inputSchema")
    if not isinstance(schema, dict):
        problems.append("/inputSchema: must be an object")
        return problems
    if schema.get("type") != "object":
        problems.append("/inputSchema/type: the argument schema must be type 'object'")
    if not isinstance(schema.get("properties"), dict):
        problems.append("/inputSchema/properties: must be an object")
    for combinator in ("anyOf", "oneOf", "allOf"):
        if combinator in schema:
            problems.append(f"/inputSchema/{combinator}: a composition is not allowed at the root")
    problems.extend(mcp_schema_violations(schema, pointer="/inputSchema"))
    return problems


# ===========================================================================
# Output description
# ===========================================================================


def success_response(operation: Operation) -> Optional[Message]:
    """Return the response message that describes a successful call, if any.

    The lowest explicit 2xx code wins (``200`` over ``201``), then the ``2XX`` range. A
    paradigm without HTTP status codes (gRPC, GraphQL, JSON-RPC …) declares its result as
    a response message with no status, which is used when nothing HTTP-shaped exists.
    ``default`` is never chosen: it describes "anything else", usually an error.

    Args:
        operation: The operation whose success response to find.

    Returns:
        The success message, or ``None``.
    """
    responses = [message for message in operation.messages if message.role is MessageRole.RESPONSE]
    explicit = sorted(
        (m for m in responses if m.status_code and _EXPLICIT_SUCCESS.match(m.status_code)),
        key=lambda m: int(m.status_code or "0"),
    )
    if explicit:
        return explicit[0]
    for message in responses:
        if (message.status_code or "").upper() == _SUCCESS_RANGE:
            return message
    for message in responses:
        if message.status_code is None:
            return message
    return None


def _preferred_media_type(message: Message) -> Optional[str]:
    """The media type a body is described in: JSON first, else the first declared."""
    content_types = sorted(message.content_types)
    for content_type in content_types:
        if "json" in content_type.lower():
            return content_type
    return content_types[0] if content_types else None


def _shape_phrase(message: Message, schema: Optional[Dict[str, Any]]) -> Optional[str]:
    """A short phrase for the body's shape (``array of Pet``, ``Pet``, ``object``)."""
    if message.payload is not None:
        phrase = _type_ref_phrase(message.payload)
        if phrase:
            return phrase
    if schema is not None and isinstance(schema.get("type"), str):
        return str(schema["type"])
    return None


def _type_ref_phrase(ref: TypeRef) -> Optional[str]:
    """Describe a use-site type reference in words."""
    if ref.is_list():
        inner = _type_ref_phrase(ref.item) if ref.item is not None else None
        return f"array of {inner}" if inner else "array"
    return ref.name


def _compile_output(
    operation: Operation,
    *,
    builder: ToolSchemaBuilder,
    losses: LossTracker,
) -> Optional[McpToolOutput]:
    """Derive the tool's output description from the operation's success response."""
    message = success_response(operation)
    if message is None:
        return None
    raw = builder.for_message(message)
    schema = (
        sanitize_mcp_schema(raw, losses=losses, subject=message.key) if raw is not None else None
    )
    description, redacted = scrub_credentials((message.description or "").strip())
    if redacted:
        losses.record(
            LossKind.INFERRED,
            LOSS_CREDENTIAL_REDACTED,
            f"{redacted} credential literal(s) were redacted from the description of "
            f"{message.key!r} before it was published to a tool definition.",
            pointer=message.key,
        )
    return McpToolOutput(
        status=message.status_code,
        description=description or None,
        media_type=_preferred_media_type(message),
        schema=schema,
        shape=_shape_phrase(message, schema),
    )


def _compose_description(base: Optional[str], output: Optional[McpToolOutput]) -> Optional[str]:
    """Join the operation's description and the output sentence into one text."""
    parts = [text for text in (base, output.summary() if output else None) if text]
    return "\n\n".join(parts) if parts else None


# ===========================================================================
# The compiler
# ===========================================================================


def compile_mcp_tools(
    api: CanonicalApi,
    *,
    exposed: Optional[Iterable[str]] = None,
) -> McpToolset:
    """Compile a published version's canonical model into its MCP toolset.

    Args:
        api: The canonical model of the version.
        exposed: Canonical keys of the operations to expose (``GET /pets/{id}``). ``None``
            exposes every callable operation that is not deprecated; an explicit
            collection exposes exactly those operations, deprecated or not (a deprecated
            tool's description says so).

    Returns:
        The toolset, in canonical order.

    Raises:
        TypeError: When ``exposed`` is a bare string rather than a collection of keys.
        UnknownOperationError: When an exposed key names no callable operation (unknown,
            or an event/streaming operation that has no tool form).
        McpToolMappingError: When a compiled tool fails :func:`validate_mcp_tool` — an
            internal invariant, raised rather than shipping an invalid toolset.
    """
    if isinstance(exposed, str):
        raise TypeError("exposed must be a collection of operation keys, not a string")

    ordered = normalize_ordering(api)
    precheck = LossTracker()
    callable_ops = {
        operation.key: operation
        for _service, operation in selectable_operations(
            ordered, include_deprecated=True, losses=precheck
        )
    }
    wanted = _resolve_exposure(callable_ops, exposed)
    if not callable_ops:
        # No schema-only fallback: an agent tool must invoke an operation.
        return McpToolset(tools=(), losses=tuple(precheck.records()))

    losses = LossTracker()
    # Names over *every* callable operation, so exposure never renames a tool.
    projected = project_tools(ordered, losses=losses, include_deprecated=True)
    builder = ToolSchemaBuilder(ordered, losses=losses)

    tools: List[McpToolDefinition] = []
    for definition in projected:
        if definition.source_key in wanted:
            tools.append(
                _compile_tool(definition, callable_ops[definition.source_key], builder, losses)
            )

    _validate_toolset(tools)
    with_output = {tool.operation for tool in tools if tool.output is not None}
    kept = tuple(
        loss for loss in losses.records() if _loss_applies(loss, callable_ops, wanted, with_output)
    )
    return McpToolset(tools=tuple(tools), losses=kept)


def _resolve_exposure(
    callable_ops: Mapping[str, Operation],
    exposed: Optional[Iterable[str]],
) -> Set[str]:
    """Return the set of operation keys to expose, validating an explicit selection."""
    if exposed is None:
        return {key for key, operation in callable_ops.items() if not operation.deprecated}
    keys = set(exposed)
    unknown = keys - set(callable_ops)
    if unknown:
        raise UnknownOperationError(unknown)
    return keys


def _compile_tool(
    definition: ToolDefinition,
    operation: Operation,
    builder: ToolSchemaBuilder,
    losses: LossTracker,
) -> McpToolDefinition:
    """Turn one projected tool definition into its MCP form."""
    input_schema = sanitize_mcp_schema(
        definition.input_schema, losses=losses, subject=operation.key, arguments=True
    )
    output = _compile_output(operation, builder=builder, losses=losses)
    return McpToolDefinition(
        name=definition.name,
        description=_compose_description(definition.description, output),
        input_schema=input_schema,
        output=output,
        operation=operation.key,
    )


def _validate_toolset(tools: List[McpToolDefinition]) -> None:
    """Raise :class:`McpToolMappingError` if any tool breaks the compiler's contract."""
    problems: List[str] = []
    seen: Set[str] = set()
    for tool in tools:
        found = validate_mcp_tool(tool.to_mcp())
        if tool.output is not None and tool.output.schema is not None:
            found.extend(mcp_schema_violations(tool.output.schema, pointer="/output/schema"))
        if tool.name in seen:
            found.append("/name: duplicated within the toolset")
        seen.add(tool.name)
        problems.extend(f"{tool.name!r}{problem}" for problem in found)
    if problems:
        raise McpToolMappingError("Compiled toolset is not MCP-valid: " + "; ".join(problems))


def _loss_applies(
    loss: Loss,
    callable_ops: Mapping[str, Operation],
    wanted: Set[str],
    with_output: Set[str],
) -> bool:
    """Whether a projection loss describes the compiled (exposed) toolset.

    A loss about a callable operation that is not exposed describes a tool that does not
    exist, so it is dropped; a loss about an operation that has no tool form at all (an
    event or streaming operation) is kept, because it explains the absence. The shared
    projection's "responses are not carried" note is dropped for a tool whose output this
    compiler *does* carry.
    """
    if loss.pointer is None:
        return True
    operation_key = loss.pointer.split("#", 1)[0]
    if operation_key in callable_ops and operation_key not in wanted:
        return False
    return not (loss.subject == LOSS_RESPONSE_SCHEMA and operation_key in with_output)
