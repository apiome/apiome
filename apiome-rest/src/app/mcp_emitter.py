"""MCP tool-definition emitter: canonical model → MCP server descriptor — MFX-32.1 (#4295).

Turns a cataloged API into the tools an MCP host lists: the fastest path from "API in the
catalog" to "API usable by an agent". The artifact is a **server descriptor** — server metadata
plus the ``tools`` array — in the static-manifest shape the MCP importer reads
(:mod:`app.mcp_import_source`, FMT-1.7), so an exported descriptor imports straight back.
Generating a *running* server is out of scope (SDK-4.5).

One mapping
-----------
Tools are not derived here. :func:`app.mcp_tool_mapping.compile_mcp_tools` (AGX-1.1) owns the
operation → tool mapping that the managed MCP proxy also uses: the tool ``name`` from the
operationId (sanitized to the MCP grammar and deduplicated — ``_2``, ``_3`` …), the
``description`` from the summary and description plus a "Returns …" sentence, and the
``inputSchema`` from the parameters and the request body through the JSON-Schema mapping. This
module adds the MCP *packaging*:

* ``mcpVersion`` — the protocol revision the descriptor targets (``protocol_version``);
* ``server`` — ``name`` (a slug of the API's name), ``title`` and ``version``;
* ``capabilities.tools`` and the ``tools`` array;
* ``outputSchema`` (2025-06-18) — the 2xx response body's schema when it is an object, as MCP
  requires; an array or scalar response stays in the description (``mcp-output-not-object``).

**Grouping** (``grouping``): ``single`` writes one descriptor; ``per-service`` writes one per
service (a large API split into smaller tool surfaces), named ``<server>-<service>``. Names are
compiled over the whole API either way, so a tool keeps its name whichever grouping you pick.

Every tool is checked against the MCP Tool schema of the chosen revision (vendored in
``data/mcp_tool_schema.json``) and against the compiler's own contract before the descriptor is
returned, so an invalid descriptor cannot ship.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple, Union

from jsonschema import Draft7Validator
from pydantic import Field, ValidationError

from .canonical_model import ApiParadigm, CanonicalApi, Channel, Operation, Type
from .emitter import (
    CapabilityProfile,
    EmitOptions,
    EmitOptionsError,
    EmitPreconditionError,
    EmitResult,
    EmittedFile,
    Emitter,
    LossKind,
    LossTracker,
    Provenance,
    ProvenanceTracker,
)
from .fidelity_rulepack import CapabilityRulePack, FidelityVerdict
from .lossiness import LossinessReport, LossinessSeverity
from .mcp_tool_mapping import McpToolDefinition, McpToolset, compile_mcp_tools, validate_mcp_tool
from .tool_projection import EVENT_OPERATION_KINDS, selectable_operations

__all__ = [
    "MCP_FORMAT_KEY",
    "McpEmitOptions",
    "McpEmitter",
    "McpFidelityRulePack",
    "build_mcp_descriptors",
    "mcp_tool_schema_violations",
]

#: Registry key and format of the emitter — the same key as the MCP importer, so the round-trip
#: matrix pairs ``mcp -> mcp`` without an alias.
MCP_FORMAT_KEY = "mcp"
#: The protocol revisions the emitter writes. 2025-06-18 is the first with ``outputSchema``.
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
#: The revision that introduced ``outputSchema`` (and ``title``) on a Tool.
OUTPUT_SCHEMA_SINCE = "2025-06-18"
OUTPUT_MEDIA_TYPE = "application/json"
#: Suffix of every emitted descriptor file.
DESCRIPTOR_SUFFIX = ".mcp.json"

#: Loss subjects this emitter records (beyond the compiler's).
LOSS_OUTPUT_NOT_OBJECT = "mcp-output-not-object"
LOSS_OUTPUT_UNSUPPORTED = "mcp-output-schema-unsupported"
LOSS_NAME_SYNTHESIZED = "mcp-tool-name-synthesized"
LOSS_NOT_A_TOOL = "mcp-capability-not-a-tool"
#: Services an imported MCP manifest marks as resources or prompts (``extras["mcp_kind"]``): their
#: operations are not tools, and a tool descriptor does not write them.
_NON_TOOL_KINDS = frozenset({"resource", "prompt"})

_SCHEMA_PATH = Path(__file__).parent / "data" / "mcp_tool_schema.json"
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class McpEmitOptions(EmitOptions):
    """Per-target options for :class:`McpEmitter`."""

    protocol_version: Literal["2025-06-18", "2025-03-26"] = Field(
        default="2025-06-18",
        description="MCP protocol revision the descriptor targets. `2025-06-18` (default) adds "
        "`outputSchema`; `2025-03-26` has none, so what a tool returns stays in its description.",
    )
    grouping: Literal["single", "per-service"] = Field(
        default="single",
        description="`single` writes one server descriptor; `per-service` writes one descriptor "
        "per service (`<server>-<service>.mcp.json`), for large APIs.",
    )
    output_schema: bool = Field(
        default=True,
        description="Write a tool's `outputSchema` from its success response when the response is "
        "an object (2025-06-18). A server built from the descriptor must then return matching "
        "`structuredContent`; turn it off to describe the result in the description only.",
    )
    include_deprecated: bool = Field(
        default=False,
        description="Also write a tool for each deprecated operation (its description says so).",
    )


# ===========================================================================
# The MCP Tool schema
# ===========================================================================


@lru_cache(maxsize=None)
def _tool_validator(protocol_version: str) -> Draft7Validator:
    """The vendored MCP Tool schema of one protocol revision."""
    document = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    schema = {"$ref": f"#/definitions/Tool-{protocol_version}", "definitions": document["definitions"]}
    return Draft7Validator(schema)


def mcp_tool_schema_violations(tool: Mapping[str, Any], protocol_version: str) -> List[str]:
    """Check one emitted tool against the MCP Tool schema of ``protocol_version``.

    Args:
        tool: A ``tools`` entry (``name``, ``description``, ``inputSchema``, ``outputSchema`` …).
        protocol_version: One of :data:`PROTOCOL_VERSIONS`.

    Returns:
        Human-readable violations (``/path: message``); empty when the tool is valid.
    """
    validator = _tool_validator(protocol_version)
    problems = []
    for error in sorted(validator.iter_errors(tool), key=lambda e: list(e.absolute_path)):
        pointer = "".join(f"/{part}" for part in error.absolute_path)
        problems.append(f"{pointer or '/'}: {error.message}")
    return problems


# ===========================================================================
# Building the descriptors
# ===========================================================================


def _slug(text: str) -> str:
    """A server-name slug: lower-case letters, digits and hyphens."""
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "api"


def _tool_operations(
    api: CanonicalApi, options: McpEmitOptions, losses: Optional[LossTracker] = None
) -> List[str]:
    """The keys of the operations that become tools.

    Every callable operation, except a deprecated one (unless ``include_deprecated``) and the
    resources and prompts of an imported MCP manifest, which are MCP capabilities but not tools
    (each recorded as ``mcp-capability-not-a-tool``).
    """
    non_tool = {
        op.key: service.extras.get("mcp_kind")
        for service in api.services
        if (service.extras or {}).get("mcp_kind") in _NON_TOOL_KINDS
        for op in service.operations
    }
    keys: List[str] = []
    for _service, operation in selectable_operations(api, include_deprecated=True):
        if operation.key in non_tool:
            if losses is not None:
                losses.record(
                    LossKind.NA,
                    LOSS_NOT_A_TOOL,
                    f"the MCP {non_tool[operation.key]} {operation.name or operation.key!r} is not a tool; "
                    "a tool descriptor lists tools only, so it is not written",
                    pointer=operation.key,
                )
            continue
        if operation.deprecated and not options.include_deprecated:
            continue
        keys.append(operation.key)
    return keys


def _render_tool(tool: McpToolDefinition, options: McpEmitOptions, losses: LossTracker) -> Dict[str, Any]:
    """One ``tools`` entry: the compiled MCP entry, plus ``outputSchema`` where it applies."""
    entry = tool.to_mcp()
    schema = tool.output.schema if tool.output is not None else None
    if schema is None or not options.output_schema:
        return entry
    if options.protocol_version < OUTPUT_SCHEMA_SINCE:
        losses.record(
            LossKind.NA,
            LOSS_OUTPUT_UNSUPPORTED,
            f"MCP {options.protocol_version} has no outputSchema; what {tool.name!r} returns is "
            "described in its description only",
            pointer=tool.operation,
        )
    elif schema.get("type") == "object":
        entry["outputSchema"] = schema
    else:
        losses.record(
            LossKind.NA,
            LOSS_OUTPUT_NOT_OBJECT,
            f"MCP requires an object outputSchema; {tool.name!r} returns "
            f"{tool.output.shape or 'a non-object value'}, so its result is described in its "
            "description only",
            pointer=tool.operation,
        )
    return entry


def build_mcp_descriptors(
    api: CanonicalApi,
    options: McpEmitOptions,
    *,
    losses: LossTracker,
    tracker: Optional[ProvenanceTracker] = None,
) -> Tuple[List[Tuple[str, Dict[str, Any]]], McpToolset]:
    """Compile ``api`` and package its tools as MCP server descriptors.

    Args:
        api: The canonical model to export.
        options: The emit options.
        losses: Loss tracker the compile and the packaging record onto.
        tracker: Provenance tracker for the tool names (``None`` to skip provenance).

    Returns:
        ``([(file name, descriptor), …], toolset)`` — one descriptor for ``single``, one per service
        that has a tool for ``per-service``.

    Raises:
        EmitPreconditionError: When the model has no callable operation to make a tool of.
        ValueError: When a tool fails the MCP Tool schema or the compiler's contract.
    """
    toolset = compile_mcp_tools(api, exposed=_tool_operations(api, options, losses))
    for loss in toolset.losses:
        losses.record(loss.kind, loss.subject, loss.detail, pointer=loss.pointer)
    if not toolset.tools:
        raise EmitPreconditionError(
            "An MCP server descriptor lists tools an agent can call, and this model has no callable "
            "operation (an event, streaming or schema-only model has none)."
        )

    server_name = _slug(api.identity.name or api.title or "api")
    # A per-service descriptor is named and titled after the service's name (its key may be qualified).
    service_of = {op.key: service.name or service.key for service in api.services for op in service.operations}
    groups: Dict[str, List[McpToolDefinition]] = {}
    for tool in toolset.tools:
        group = service_of.get(tool.operation, "") if options.grouping == "per-service" else ""
        groups.setdefault(group, []).append(tool)

    descriptors: List[Tuple[str, Dict[str, Any]]] = []
    problems: List[str] = []
    for group, tools in groups.items():
        name = f"{server_name}-{_slug(group)}" if group else server_name
        rendered = [_render_tool(tool, options, losses) for tool in tools]
        for entry in rendered:
            problems += [f"{entry['name']!r}{p}" for p in validate_mcp_tool(entry)]
            problems += [f"{entry['name']!r}{p}" for p in mcp_tool_schema_violations(entry, options.protocol_version)]
        server: Dict[str, Any] = {"name": name, "version": api.version or "0.0.0"}
        if api.title and options.protocol_version >= OUTPUT_SCHEMA_SINCE:
            server["title"] = api.title if not group else f"{api.title} — {group}"
        descriptor = {
            "mcpVersion": options.protocol_version,
            "server": server,
            "capabilities": {"tools": {}},
            "tools": rendered,
        }
        descriptors.append((f"{name}{DESCRIPTOR_SUFFIX}", descriptor))
        if tracker is not None:
            for index, tool in enumerate(tools):
                tracker.record(
                    f"/{name}/tools/{index}/name",
                    tool.name_provenance,
                    None if tool.name_provenance is Provenance.SOURCE
                    else f"synthesized from {tool.source_name!r} to satisfy the MCP tool-name grammar",
                )
    if problems:
        raise ValueError("The MCP descriptor is not valid: " + "; ".join(problems))
    for tool in toolset.tools:
        if tool.name_provenance is not Provenance.SOURCE:
            losses.record(
                LossKind.INFERRED,
                LOSS_NAME_SYNTHESIZED,
                f"tool name {tool.name!r} was synthesized from {tool.source_name!r}",
                pointer=tool.operation,
            )
    return descriptors, toolset


# ===========================================================================
# Fidelity
# ===========================================================================


class McpFidelityRulePack(CapabilityRulePack):
    """Fidelity rules for MCP tool-definition export.

    A tool carries a callable's name, its documentation and JSON Schemas for its input (and, from
    2025-06-18, an object output). So:

    * an operation is ``OK`` when its tool keeps the operation's own name, and **``SYNTH``** when
      the name was synthesized (sanitized, deduplicated or made from the method and path);
    * an event or streaming operation has no tool and is ``DROP``ped, as is a deprecated one
      unless ``include_deprecated`` and an imported MCP manifest's resources and prompts;
    * a channel is ``DROP``ped; a named type is inlined into each tool that uses it (``APPROX``);
    * the API's servers have no field in a descriptor (``DROP``).
    """

    target_label = "MCP server descriptor"

    def apply_options(self, options: Mapping[str, Any]) -> None:
        """Compute the report for these options (invalid options fall back to the defaults)."""
        try:
            self._options = McpEmitOptions.model_validate(dict(options))
        except ValidationError:
            self._options = McpEmitOptions()

    def evaluate(self, api: CanonicalApi) -> LossinessReport:
        """Compile once to learn each tool's name, then walk the model."""
        options = getattr(self, "_options", None) or McpEmitOptions()
        self._non_tools = {
            op.key for service in api.services
            if (service.extras or {}).get("mcp_kind") in _NON_TOOL_KINDS for op in service.operations
        }
        try:
            toolset = compile_mcp_tools(api, exposed=_tool_operations(api, options))
        except ValueError:
            toolset = McpToolset(tools=())
        self._tools = {tool.operation: tool for tool in toolset.tools}
        return super().evaluate(api)

    def root_verdicts(self, api: CanonicalApi) -> List[FidelityVerdict]:
        """The servers a descriptor has no field for."""
        if not api.servers:
            return []
        return [
            FidelityVerdict.drop(
                message=f"an {self.target_label} lists tools, not the API's servers; the "
                f"{len(api.servers)} declared server(s) are dropped — the MCP server that serves the "
                "tools decides where calls go",
                severity=LossinessSeverity.WARN,
                target_mapping="servers → dropped",
            )
        ]

    def operation_verdict(self, operation: Operation) -> FidelityVerdict:
        """OK or SYNTH by the tool's name; DROP when the operation gets no tool."""
        tool = getattr(self, "_tools", {}).get(operation.key)
        if tool is None:
            if operation.key in getattr(self, "_non_tools", set()):
                reason = "an MCP resource or prompt is not a tool"
            elif operation.kind in EVENT_OPERATION_KINDS or operation.streaming.value != "none":
                reason = "an event or streaming operation has no tool form"
            elif operation.deprecated:
                reason = "a deprecated operation gets a tool only with include_deprecated"
            else:
                reason = "the operation has no callable form"
            return FidelityVerdict.drop(
                message=f"{self.target_label}: {reason}; {operation.key!r} is dropped",
                target_mapping="operation → no tool",
            )
        if tool.name_provenance is not Provenance.SOURCE:
            return FidelityVerdict.synth(
                message=f"tool name {tool.name!r} was synthesized from {tool.source_name!r} to satisfy "
                "the MCP tool-name grammar (and stay unique)",
                severity=LossinessSeverity.INFO,
                target_mapping=f"operation → tool {tool.name}",
            )
        return FidelityVerdict.ok(message=f"operation carried to the MCP tool {tool.name!r}")

    def channel_verdict(self, channel: Channel) -> FidelityVerdict:
        """A channel has no tool representation."""
        return FidelityVerdict.drop(
            message=f"{self.target_label} has no channel vocabulary; channel {channel.key!r} is dropped",
            target_mapping="channel → dropped",
        )

    def type_verdict(self, type_: Type) -> FidelityVerdict:
        """A named type is inlined into every tool schema that uses it."""
        return FidelityVerdict.approx(
            message=f"{self.target_label} has no component section; type {type_.key!r} is inlined "
            "into each tool schema that uses it",
            severity=LossinessSeverity.INFO,
            target_mapping="named type → inlined schema",
        )


# ===========================================================================
# Emitter
# ===========================================================================


class McpEmitter(Emitter, register=True):
    """Emit a :class:`CanonicalApi` as MCP server descriptor(s) with tool definitions."""

    key = MCP_FORMAT_KEY
    #: Offered greyed out with the reason when the source has no operation a tool can call (X1, #6222).
    requires_source = ("tool-operation",)
    format = MCP_FORMAT_KEY
    label = "MCP Tool Definitions"
    description = (
        "Export as an MCP server descriptor: one tool per operation, with a unique name, a "
        "description, an inputSchema from the parameters and body, and an outputSchema where "
        "the protocol revision supports it."
    )
    icon = "bot"
    paradigm = ApiParadigm.AGENT
    multi_file = False
    options_model = McpEmitOptions

    @classmethod
    def capability_profile(cls) -> CapabilityProfile:
        """A tool's schemas are JSON Schema; there is no event vocabulary or field identity."""
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
        """Return the MCP tool-definition rules."""
        return McpFidelityRulePack

    def emit(
        self,
        api: CanonicalApi,
        *,
        opts: Optional[Union[McpEmitOptions, EmitOptions]] = None,
    ) -> EmitResult:
        """Emit ``api`` as one MCP server descriptor (or one per service).

        Args:
            api: The canonical model to export.
            opts: Per-target options; the defaults write one 2025-06-18 descriptor.

        Returns:
            An :class:`~app.emitter.EmitResult` whose files are the descriptors' JSON text.

        Raises:
            EmitOptionsError: When ``opts`` names an unknown option value.
            EmitPreconditionError: When the model has no callable operation.
            ValueError: When a tool fails the MCP Tool schema.
        """
        options = _coerce_options(opts)
        losses = LossTracker()
        tracker = ProvenanceTracker()
        descriptors, _toolset = build_mcp_descriptors(api, options, losses=losses, tracker=tracker)
        files = [
            EmittedFile(
                path=path,
                content=json.dumps(descriptor, indent=2, ensure_ascii=False) + "\n",
                media_type=OUTPUT_MEDIA_TYPE,
            )
            for path, descriptor in descriptors
        ]
        return EmitResult(
            files=files,
            media_type=OUTPUT_MEDIA_TYPE,
            provenance=tracker.records(),
            losses=losses.records(),
        )


def _coerce_options(opts: Optional[Union[McpEmitOptions, EmitOptions]]) -> McpEmitOptions:
    """Validate caller-supplied options into :class:`McpEmitOptions`."""
    if isinstance(opts, McpEmitOptions):
        return opts
    try:
        return McpEmitOptions.model_validate(opts.model_dump() if opts else {})
    except ValueError as exc:
        raise EmitOptionsError(f"Invalid MCP emit options: {exc}") from exc
