"""Description enrichment analysis for agent tools — AGX-1.3 (#4531).

A tool compiled by AGX-1.1 (:func:`app.mcp_tool_mapping.compile_mcp_tools`) is only as usable as
the spec it came from. An operation with no description compiles into a valid tool that an agent
cannot choose, and a parameter with no description is one it cannot fill in. This module holds
the pure, database-free half of the enrichment pass:

* **Agent-hostile flags** (:func:`agent_hostile_flags`). For each operation, a list of
  machine-readable reasons (:data:`REASON_CODES`) why an agent will struggle with its tool: no
  description or a thin one, no examples, no documented error responses, and parameters with no
  description or a thin one. The flags describe the *source spec*, so they are what the AGX-4.4
  agent-readiness score reads.
* **Enrichment targets** (:func:`enrichment_targets`). The tool and parameter descriptions too thin
  to keep. A description is thin below the agent-readiness pack's own thresholds
  (:data:`app.mcp_agent_readiness.MIN_TOOL_DESCRIPTION_CHARS` /
  :data:`~app.mcp_agent_readiness.MIN_PARAM_DESCRIPTION_CHARS`), so this pass and the CLX-3.1
  readiness rules agree about what "thin" means.
* **The prompt and its reply** (:func:`build_enrichment_prompt`, :func:`parse_enrichment_reply`).
  The prompt is built only from the spec's own documentation: names, schema names and fields,
  response descriptions, and examples. The reply is parsed defensively. Anything that is not a
  usable string for a requested target is dropped, never guessed.
* **Applying accepted text** (:func:`apply_description_overrides`). Returns a copy of the canonical
  model with accepted descriptions written in, which is then compiled as usual. The compiler is
  untouched, so tool names and schemas cannot change because of enrichment.

Nothing here decides what reaches an agent. Proposals are stored for review by
:mod:`app.agent_toolset_enrichment`, and only accepted ones are passed to
:func:`apply_description_overrides`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .canonical_model import CanonicalApi, Message, MessageRole, Operation, Parameter, TypeRef
from .mcp_agent_readiness import MIN_PARAM_DESCRIPTION_CHARS, MIN_TOOL_DESCRIPTION_CHARS
from .tool_projection import assemble_tool_description, scrub_credentials

__all__ = [
    "MAX_PARAM_DESCRIPTION_CHARS",
    "MAX_TOOL_DESCRIPTION_CHARS",
    "REASON_CODES",
    "REASON_MISSING_DESCRIPTION",
    "REASON_MISSING_EXAMPLES",
    "REASON_MISSING_PARAM_DESCRIPTION",
    "REASON_THIN_DESCRIPTION",
    "REASON_THIN_PARAM_DESCRIPTION",
    "REASON_UNDOCUMENTED_ERRORS",
    "SYSTEM_PROMPT",
    "TARGET_PARAMETER",
    "TARGET_TOOL",
    "EnrichmentTarget",
    "HostileReason",
    "ToolFlags",
    "agent_hostile_flags",
    "apply_description_overrides",
    "build_enrichment_prompt",
    "enrichment_targets",
    "flag_operation",
    "operation_has_examples",
    "parameter_label",
    "parse_enrichment_reply",
    "tool_description_text",
]

# ---------------------------------------------------------------------------
# Reason codes (the contract AGX-4.4 reads)
# ---------------------------------------------------------------------------

#: The operation documents nothing an agent could choose it by.
REASON_MISSING_DESCRIPTION = "missing-description"
#: The operation's description is shorter than ``MIN_TOOL_DESCRIPTION_CHARS``.
REASON_THIN_DESCRIPTION = "thin-description"
#: Neither the operation, its parameters, nor its payloads carry an example.
REASON_MISSING_EXAMPLES = "missing-examples"
#: An HTTP operation declares no error response (no ``4XX``/``5XX`` and no ``default``).
REASON_UNDOCUMENTED_ERRORS = "undocumented-errors"
#: A parameter has no description.
REASON_MISSING_PARAM_DESCRIPTION = "missing-parameter-description"
#: A parameter's description is shorter than ``MIN_PARAM_DESCRIPTION_CHARS``.
REASON_THIN_PARAM_DESCRIPTION = "thin-parameter-description"

#: Every reason code, in the order a flag lists them.
REASON_CODES: Tuple[str, ...] = (
    REASON_MISSING_DESCRIPTION,
    REASON_THIN_DESCRIPTION,
    REASON_MISSING_EXAMPLES,
    REASON_UNDOCUMENTED_ERRORS,
    REASON_MISSING_PARAM_DESCRIPTION,
    REASON_THIN_PARAM_DESCRIPTION,
)

#: Enrichment target kinds: the tool's own description, or one parameter's.
TARGET_TOOL = "tool"
TARGET_PARAMETER = "parameter"

#: Upper bounds on an accepted or proposed description, so a runaway reply cannot bloat a tool.
MAX_TOOL_DESCRIPTION_CHARS = 1000
MAX_PARAM_DESCRIPTION_CHARS = 300

#: Keys that mark an example in an OpenAPI/Swagger document or a JSON Schema.
_EXAMPLE_KEYS = frozenset({"example", "examples", "x-example", "x-examples"})

#: How much of each context section the prompt includes, so a large spec stays a small prompt.
_PROMPT_API_DESCRIPTION_CHARS = 400
_PROMPT_EXAMPLES_CHARS = 1500
_PROMPT_FIELD_LIMIT = 20

SYSTEM_PROMPT = (
    "You write descriptions for AI-agent tools generated from an API specification. Each tool is "
    "one API operation. A good tool description says in one to three sentences what the operation "
    "does, when to use it, and what it returns. A good parameter description says in one sentence "
    "what value to pass and its format. Use only the facts in the specification excerpt you are "
    "given: do not invent behaviour, fields, limits, or error cases it does not state. Do not "
    "mention that you are an AI. Reply with a single JSON object and nothing else."
)


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HostileReason:
    """One reason an operation's tool is hard for an agent to use.

    Attributes:
        code: One of :data:`REASON_CODES`.
        message: A human-readable explanation.
        parameter: For a parameter reason, the parameter as ``location.name`` (``query.limit``).
    """

    code: str
    message: str
    parameter: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return the JSON shape (``parameter`` only when set)."""
        out: Dict[str, Any] = {"code": self.code, "message": self.message}
        if self.parameter is not None:
            out["parameter"] = self.parameter
        return out


@dataclass(frozen=True)
class ToolFlags:
    """The agent-hostile reasons for one operation.

    Attributes:
        operation_key: The canonical operation key (``GET /pets/{id}``).
        reasons: Every reason that applies, in :data:`REASON_CODES` order.
    """

    operation_key: str
    reasons: Tuple[HostileReason, ...] = field(default_factory=tuple)

    @property
    def codes(self) -> Tuple[str, ...]:
        """The distinct reason codes, in order."""
        return tuple(dict.fromkeys(reason.code for reason in self.reasons))


def parameter_label(parameter: Parameter) -> str:
    """Return the ``location.name`` label a parameter is addressed by in flags and prompts."""
    return f"{parameter.location.value}.{parameter.name}"


def tool_description_text(operation: Operation) -> str:
    """Return the description text the compiler would give the operation's tool.

    The summary and description are joined the way :func:`app.tool_projection.assemble_tool_description`
    joins them, without the deprecation marker (a marker is not documentation).

    Args:
        operation: A canonical operation.

    Returns:
        The text, stripped; empty when the operation documents nothing.
    """
    summary = (operation.extras or {}).get("summary")
    text, _ = assemble_tool_description(
        summary=summary if isinstance(summary, str) else None,
        description=operation.description,
    )
    return (text or "").strip()


def _has_example_key(node: Any) -> bool:
    """Return whether any mapping inside ``node`` has a non-empty example key."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                if key in _EXAMPLE_KEYS and value not in (None, "", [], {}):
                    return True
                stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return False


def _raw_operation(api: CanonicalApi, operation: Operation) -> Optional[Mapping[str, Any]]:
    """Return the operation's own object in a retained OpenAPI/Swagger source, when there is one.

    Path-level parameters are included, so an example declared on them counts.
    """
    raw = api.raw
    if not isinstance(raw, Mapping) or not operation.http_path or not operation.http_method:
        return None
    paths = raw.get("paths")
    path_item = paths.get(operation.http_path) if isinstance(paths, Mapping) else None
    if not isinstance(path_item, Mapping):
        return None
    op_obj = path_item.get(operation.http_method.lower())
    if not isinstance(op_obj, Mapping):
        return None
    return {"operation": op_obj, "parameters": path_item.get("parameters")}


def _referenced_types(api: CanonicalApi, operation: Operation) -> List[Any]:
    """Return the named types the operation's messages reference (one level, list items included)."""
    found: List[Any] = []
    for message in operation.messages:
        ref: Optional[TypeRef] = message.payload
        while ref is not None and ref.item is not None:
            ref = ref.item
        if ref is not None and ref.name:
            type_ = api.type_by_key(ref.name)
            if type_ is not None:
                found.append(type_)
    return found


def operation_has_examples(api: CanonicalApi, operation: Operation) -> bool:
    """Return whether the spec gives an example for anything the operation sends or receives.

    Examples are looked for in the retained source document's operation object (OpenAPI
    ``example`` / ``examples`` / ``x-example``), in inline payload schemas, in the ``extras`` of the
    operation, its parameters and messages, and in the named types its messages reference.

    Args:
        api: The canonical model (its ``raw`` source is used when retained).
        operation: The operation.

    Returns:
        ``True`` when at least one non-empty example is declared.
    """
    raw_op = _raw_operation(api, operation)
    if raw_op is not None and _has_example_key(raw_op):
        return True
    candidates: List[Any] = [operation.extras]
    candidates.extend(parameter.extras for parameter in operation.parameters)
    for message in operation.messages:
        candidates.extend([message.extras, message.payload_schema])
    for type_ in _referenced_types(api, operation):
        candidates.append(type_.model_dump(include={"extras", "fields"}))
    return any(_has_example_key(candidate) for candidate in candidates if candidate)


def _documents_errors(operation: Operation) -> bool:
    """Return whether an operation declares an error response (or a catch-all ``default``)."""
    for message in operation.messages:
        if message.role is MessageRole.ERROR:
            return True
        if message.role is MessageRole.RESPONSE and (message.status_code or "") == "default":
            return True
    return False


def flag_operation(api: CanonicalApi, operation: Operation) -> Tuple[HostileReason, ...]:
    """Return every agent-hostile reason that applies to one operation.

    Args:
        api: The canonical model the operation belongs to.
        operation: The operation.

    Returns:
        The reasons, in :data:`REASON_CODES` order; empty when the tool is agent-friendly.
    """
    reasons: List[HostileReason] = []
    text = tool_description_text(operation)
    if not text:
        reasons.append(
            HostileReason(
                REASON_MISSING_DESCRIPTION,
                f"{operation.key} has no summary or description, so an agent cannot tell when to "
                "call its tool.",
            )
        )
    elif len(text) < MIN_TOOL_DESCRIPTION_CHARS:
        reasons.append(
            HostileReason(
                REASON_THIN_DESCRIPTION,
                f"{operation.key} is described in {len(text)} characters; fewer than "
                f"{MIN_TOOL_DESCRIPTION_CHARS} rarely tell an agent when to call it.",
            )
        )
    if not operation_has_examples(api, operation):
        reasons.append(
            HostileReason(
                REASON_MISSING_EXAMPLES,
                f"{operation.key} declares no examples for its parameters, request or responses.",
            )
        )
    if operation.http_method and not _documents_errors(operation):
        reasons.append(
            HostileReason(
                REASON_UNDOCUMENTED_ERRORS,
                f"{operation.key} declares no error responses, so an agent has no recovery "
                "guidance when a call fails.",
            )
        )
    for parameter in operation.parameters:
        label = parameter_label(parameter)
        described = (parameter.description or "").strip()
        if not described:
            reasons.append(
                HostileReason(
                    REASON_MISSING_PARAM_DESCRIPTION,
                    f"Parameter {label} of {operation.key} has no description.",
                    parameter=label,
                )
            )
        elif len(described) < MIN_PARAM_DESCRIPTION_CHARS:
            reasons.append(
                HostileReason(
                    REASON_THIN_PARAM_DESCRIPTION,
                    f"Parameter {label} of {operation.key} is described in {len(described)} "
                    f"characters; fewer than {MIN_PARAM_DESCRIPTION_CHARS} rarely say what to pass.",
                    parameter=label,
                )
            )
    order = {code: index for index, code in enumerate(REASON_CODES)}
    return tuple(sorted(reasons, key=lambda reason: order[reason.code]))


def agent_hostile_flags(
    api: CanonicalApi, operations: Iterable[Operation]
) -> List[ToolFlags]:
    """Flag the agent-hostile operations among ``operations``.

    Args:
        api: The canonical model.
        operations: The operations to examine (for a toolset: its callable operations).

    Returns:
        One :class:`ToolFlags` per operation with at least one reason, ordered by operation key.
    """
    flags = [
        ToolFlags(operation_key=operation.key, reasons=reasons)
        for operation in operations
        if (reasons := flag_operation(api, operation))
    ]
    return sorted(flags, key=lambda flag: flag.operation_key)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnrichmentTarget:
    """One description too thin to keep, which the pass may propose a replacement for.

    Attributes:
        kind: :data:`TARGET_TOOL` or :data:`TARGET_PARAMETER`.
        operation_key: The operation the description belongs to.
        target_key: The stable address of the description: the operation key for a tool, the
            canonical parameter key (``GET /pets#query.limit``) for a parameter.
        parameter: For a parameter target, its ``location.name`` label.
        original: The current description (``None`` when there is none).
    """

    kind: str
    operation_key: str
    target_key: str
    parameter: Optional[str] = None
    original: Optional[str] = None


def enrichment_targets(operation: Operation) -> List[EnrichmentTarget]:
    """Return the operation's descriptions that are missing or thin.

    Args:
        operation: The operation.

    Returns:
        The tool target first (when thin), then one target per thin parameter, in declaration order.
    """
    targets: List[EnrichmentTarget] = []
    text = tool_description_text(operation)
    if len(text) < MIN_TOOL_DESCRIPTION_CHARS:
        targets.append(
            EnrichmentTarget(
                kind=TARGET_TOOL,
                operation_key=operation.key,
                target_key=operation.key,
                original=text or None,
            )
        )
    for parameter in operation.parameters:
        described = (parameter.description or "").strip()
        if len(described) < MIN_PARAM_DESCRIPTION_CHARS:
            targets.append(
                EnrichmentTarget(
                    kind=TARGET_PARAMETER,
                    operation_key=operation.key,
                    target_key=parameter.key,
                    parameter=parameter_label(parameter),
                    original=described or None,
                )
            )
    return targets


# ---------------------------------------------------------------------------
# Prompt and reply
# ---------------------------------------------------------------------------


def _truncate(text: str, limit: int) -> str:
    """Cut ``text`` to ``limit`` characters, marking the cut."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _type_phrase(api: CanonicalApi, ref: Optional[TypeRef]) -> Optional[str]:
    """Describe a payload reference as ``Pet (fields: id, name)`` or ``array of Pet``."""
    if ref is None:
        return None
    if ref.item is not None:
        inner = _type_phrase(api, ref.item)
        return f"array of {inner}" if inner else "array"
    if not ref.name:
        return None
    type_ = api.type_by_key(ref.name)
    if type_ is None:
        return ref.name
    label = type_.name or ref.name
    names = [field_.name for field_ in type_.fields][:_PROMPT_FIELD_LIMIT]
    return f"{label} (fields: {', '.join(names)})" if names else label


def _message_phrase(api: CanonicalApi, message: Message) -> str:
    """Describe a payload: its named type, or the top-level properties of an inline schema."""
    phrase = _type_phrase(api, message.payload)
    if phrase:
        return phrase
    schema = message.payload_schema or {}
    properties = schema.get("properties") if isinstance(schema, Mapping) else None
    if isinstance(properties, Mapping) and properties:
        names = list(properties)[:_PROMPT_FIELD_LIMIT]
        return f"object (fields: {', '.join(str(name) for name in names)})"
    if isinstance(schema, Mapping) and isinstance(schema.get("type"), str):
        return str(schema["type"])
    return "no payload"


def _examples_excerpt(api: CanonicalApi, operation: Operation) -> Optional[str]:
    """Return the operation's examples from the retained source, as truncated JSON."""
    raw_op = _raw_operation(api, operation)
    if raw_op is None:
        return None
    found: List[Any] = []
    stack: List[Any] = [raw_op]
    while stack:
        current = stack.pop()
        if isinstance(current, Mapping):
            for key, value in current.items():
                if key in _EXAMPLE_KEYS and value not in (None, "", [], {}):
                    found.append(value)
                else:
                    stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    if not found:
        return None
    text = json.dumps(found, default=str, sort_keys=True)
    return _truncate(text, _PROMPT_EXAMPLES_CHARS)


def build_enrichment_prompt(
    api: CanonicalApi, operation: Operation, targets: Sequence[EnrichmentTarget]
) -> str:
    """Render the user-turn prompt asking for descriptions of one operation's thin targets.

    The prompt carries only documentation the spec already has: the API's title and description,
    the operation's key, id, tags and current text, its parameters, its request and response
    payload shapes and response descriptions, and any examples. It names exactly the keys the
    reply must use: ``"tool"`` for the tool and the ``location.name`` label of each parameter.

    Args:
        api: The canonical model.
        operation: The operation.
        targets: The operation's targets (from :func:`enrichment_targets`).

    Returns:
        The prompt text. It is the same for the same inputs.
    """
    lines: List[str] = []
    if api.title:
        lines.append(f"API: {api.title}")
    if api.description:
        lines.append(f"API description: {_truncate(api.description.strip(), _PROMPT_API_DESCRIPTION_CHARS)}")
    lines.append(f"Operation: {operation.key}")
    operation_id = (operation.extras or {}).get("operationId")
    if isinstance(operation_id, str) and operation_id:
        lines.append(f"Operation id: {operation_id}")
    elif operation.name and operation.name != operation.key:
        lines.append(f"Operation name: {operation.name}")
    if operation.tags:
        lines.append(f"Tags: {', '.join(operation.tags)}")
    current = tool_description_text(operation)
    lines.append(f"Current description: {current or '(none)'}")

    if operation.parameters:
        lines.append("Parameters:")
        for parameter in operation.parameters:
            type_phrase = _type_phrase(api, parameter.type) or "unspecified type"
            required = "required" if parameter.required else "optional"
            description = (parameter.description or "").strip() or "(none)"
            lines.append(f"- {parameter_label(parameter)} ({type_phrase}, {required}): {description}")

    for message in operation.messages:
        if message.role is MessageRole.REQUEST:
            body = f"Request body: {_message_phrase(api, message)}"
            if message.description:
                body += f" — {message.description.strip()}"
            lines.append(body)
    responses = [m for m in operation.messages if m.role in (MessageRole.RESPONSE, MessageRole.ERROR)]
    if responses:
        lines.append("Responses:")
        for message in responses:
            status = message.status_code or message.role.value
            detail = f"- {status}: {_message_phrase(api, message)}"
            if message.description:
                detail += f" — {message.description.strip()}"
            lines.append(detail)

    examples = _examples_excerpt(api, operation)
    if examples:
        lines.append(f"Examples: {examples}")

    keys: List[str] = []
    for target in targets:
        keys.append('"tool"' if target.kind == TARGET_TOOL else f'"{target.parameter}"')
    lines.append("")
    lines.append(
        "Write descriptions for these keys only: "
        + ", ".join(keys)
        + '. Reply as {"tool": "...", "parameters": {"<key>": "..."}}, omitting any key you '
        "cannot describe from the excerpt."
    )
    return "\n".join(lines)


def _clean(text: Any, limit: int) -> Optional[str]:
    """Normalise one proposed description, or return ``None`` when it is unusable."""
    if not isinstance(text, str):
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    if not collapsed:
        return None
    scrubbed, _ = scrub_credentials(_truncate(collapsed, limit))
    return scrubbed or None


def _json_object(reply: str) -> Optional[Mapping[str, Any]]:
    """Extract the first JSON object from a reply, tolerating code fences or leading prose."""
    try:
        parsed = json.loads(reply)
    except (json.JSONDecodeError, TypeError):
        start, end = reply.find("{"), reply.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(reply[start : end + 1])
        except json.JSONDecodeError:
            return None
    return parsed if isinstance(parsed, Mapping) else None


def parse_enrichment_reply(
    reply: Optional[str], targets: Sequence[EnrichmentTarget]
) -> Dict[str, str]:
    """Pick the proposed descriptions for ``targets`` out of a model reply.

    Only keys that were asked for are read. A missing, non-string, blank, or unchanged value
    yields no proposal. Text is whitespace-collapsed, capped at
    :data:`MAX_TOOL_DESCRIPTION_CHARS` / :data:`MAX_PARAM_DESCRIPTION_CHARS`, and
    credential-scrubbed.

    Args:
        reply: The model's reply text (``None`` when the call failed).
        targets: The targets the prompt asked about.

    Returns:
        ``{target_key: proposed text}``.
    """
    if not reply:
        return {}
    data = _json_object(reply)
    if data is None:
        return {}
    parameters = data.get("parameters")
    parameters = parameters if isinstance(parameters, Mapping) else {}
    proposals: Dict[str, str] = {}
    for target in targets:
        if target.kind == TARGET_TOOL:
            text = _clean(data.get("tool"), MAX_TOOL_DESCRIPTION_CHARS)
        else:
            text = _clean(parameters.get(target.parameter), MAX_PARAM_DESCRIPTION_CHARS)
        if text and text != (target.original or ""):
            proposals[target.target_key] = text
    return proposals


# ---------------------------------------------------------------------------
# Applying accepted descriptions
# ---------------------------------------------------------------------------


def apply_description_overrides(
    api: CanonicalApi, overrides: Mapping[str, str]
) -> CanonicalApi:
    """Return a copy of ``api`` with accepted descriptions written in.

    A key equal to an operation key replaces that operation's ``description``; a key equal to a
    parameter key replaces that parameter's. The operation's ``summary`` is left alone, so the
    compiled description still leads with the spec's own summary when there is one. Keys that
    match nothing are ignored. ``api`` itself is not modified.

    Args:
        api: The canonical model.
        overrides: ``{target_key: accepted text}``.

    Returns:
        The patched copy (or ``api`` itself when there is nothing to apply).
    """
    if not overrides:
        return api
    patched = api.model_copy(deep=True)
    for service in patched.services:
        for operation in service.operations:
            if operation.key in overrides:
                operation.description = overrides[operation.key]
            for parameter in operation.parameters:
                if parameter.key in overrides:
                    parameter.description = overrides[parameter.key]
    return patched
