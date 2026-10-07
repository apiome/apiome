"""Agent toolset description enrichment — AGX-1.3 (#4531).

The service behind the enrichment pass of an agent toolset (AGX-1.2, :mod:`app.agent_toolsets`).
The analysis itself is pure and lives in :mod:`app.agent_tool_enrichment`; this module loads a
toolset's version, stores and reviews proposals (``db.*agent_toolset_enrichment*``, V273), and
compiles the toolset with the accepted ones applied.

**The pass** (:func:`run_toolset_enrichment`) examines every callable operation of the toolset's
version. It always reports the agent-hostile flags. When the copilot is configured
(``APIOME_AGENT_ENRICHMENT_MODEL``, an Ollama chat model; see :mod:`app.ollama_chat`) it also asks
the model for descriptions of the thin tool and parameter descriptions and stores each answer as a
``proposed`` row. Without the copilot, or when Ollama cannot be reached, the pass is flag-only.

* **Idempotent.** A description that already has a proposal, whatever its status, is not asked
  about again, and the store refuses a duplicate. Re-running continues where the last run stopped:
  each run asks about at most :data:`MAX_OPERATIONS_PER_RUN` operations, and reports how many
  remain. A run can be narrowed to named operations.
* **Human-reviewed.** A proposal is served only after a person accepts it
  (:func:`review_toolset_enrichment`), optionally editing the text first. V273's CHECK makes an
  accepted row without a review unrepresentable.
* **Opt-out.** :func:`compile_agent_toolset` applies accepted text only while the toolset's
  ``description_enrichment`` is on. Off, agents get the spec-derived descriptions.

Routes are in :mod:`app.agent_toolset_routes`; every run and review is audited there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field

from . import agent_toolsets
from .agent_tool_enrichment import (
    MAX_PARAM_DESCRIPTION_CHARS,
    MAX_TOOL_DESCRIPTION_CHARS,
    SYSTEM_PROMPT,
    TARGET_PARAMETER,
    TARGET_TOOL,
    EnrichmentTarget,
    agent_hostile_flags,
    apply_description_overrides,
    build_enrichment_prompt,
    enrichment_targets,
    parse_enrichment_reply,
    served_description_overrides,
)
from .agent_toolsets import (
    CODE_TOOLSET_NOT_FOUND,
    CODE_TOOLSET_SOURCE_UNAVAILABLE,
    AgentToolsetError,
)
from .canonical_model import CanonicalApi, Operation
from .config import settings
from .database import db
from .export_source import ExportSourceError
from .mcp_tool_mapping import McpToolMappingError, compile_mcp_tools
from .normalizer import normalize_ordering
from .ollama_chat import chat_completion
from .tool_projection import selectable_operations

__all__ = [
    "CODE_ENRICHMENT_INVALID",
    "CODE_ENRICHMENT_NOT_FOUND",
    "ENRICHMENT_SCHEMA_VERSION",
    "MAX_OPERATIONS_PER_RUN",
    "MODE_COPILOT",
    "MODE_FLAG_ONLY",
    "CompiledToolsetOut",
    "DescriptionGenerator",
    "EnrichmentFlagOut",
    "EnrichmentProposalOut",
    "EnrichmentReport",
    "EnrichmentReview",
    "EnrichmentRun",
    "EnrichmentRunResult",
    "compile_agent_toolset",
    "configured_model",
    "get_toolset_enrichment",
    "review_toolset_enrichment",
    "run_toolset_enrichment",
]

#: The addressable shape of the enrichment projections.
ENRICHMENT_SCHEMA_VERSION = "agx.toolset-enrichment.v1"

#: The pass asks the copilot about at most this many operations per run. A local model answers one
#: prompt in seconds, so this keeps one request well inside an HTTP timeout; re-running continues.
MAX_OPERATIONS_PER_RUN = 20

#: The pass proposed descriptions with the copilot.
MODE_COPILOT = "copilot"
#: No copilot is configured: the pass only flags.
MODE_FLAG_ONLY = "flag-only"

CODE_ENRICHMENT_NOT_FOUND = "agent-toolset-enrichment-not-found"
CODE_ENRICHMENT_INVALID = "agent-toolset-enrichment-invalid"

#: ``(model, system prompt, user prompt) -> reply text or None``. The default is Ollama.
DescriptionGenerator = Callable[[str, str, str], Optional[str]]

_STATUSES = ("proposed", "accepted", "rejected")


def _ollama_json(model: str, system: str, user: str) -> Optional[str]:
    """The default :data:`DescriptionGenerator`: one JSON-mode Ollama chat call."""
    return chat_completion(model, system, user, json_mode=True)


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


class EnrichmentFlagOut(BaseModel):
    """The agent-hostile reasons for one tool of the toolset.

    Attributes:
        operation: The canonical operation key.
        tool_name: The MCP tool name.
        reasons: ``{code, message, parameter?}`` per reason; ``code`` is one of
            :data:`app.agent_tool_enrichment.REASON_CODES`.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operation: str
    tool_name: Optional[str] = Field(default=None, serialization_alias="toolName")
    reasons: List[Dict[str, Any]]


class EnrichmentProposalOut(BaseModel):
    """One description proposal and its review.

    Attributes:
        id: The proposal id (what the review route addresses).
        operation: The operation the description belongs to.
        target_kind: ``tool`` or ``parameter``.
        target_key: The operation key, or the canonical parameter key.
        parameter: For a parameter, its ``location.name`` label.
        original_description: The spec's description when the proposal was made.
        proposed_description: What the copilot proposed. Never served as is.
        model: The model that proposed it.
        status: ``proposed``, ``accepted`` or ``rejected``.
        accepted_description: The text served once accepted (the proposal or an edit of it).
        reviewed_by: Who accepted or rejected it.
        reviewed_at: When.
        created_at: When it was proposed.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    operation: str
    target_kind: Literal["tool", "parameter"] = Field(serialization_alias="targetKind")
    target_key: str = Field(serialization_alias="targetKey")
    parameter: Optional[str] = None
    original_description: Optional[str] = Field(
        default=None, serialization_alias="originalDescription"
    )
    proposed_description: str = Field(serialization_alias="proposedDescription")
    model: str
    status: Literal["proposed", "accepted", "rejected"]
    accepted_description: Optional[str] = Field(
        default=None, serialization_alias="acceptedDescription"
    )
    reviewed_by: Optional[str] = Field(default=None, serialization_alias="reviewedBy")
    reviewed_at: Optional[datetime] = Field(default=None, serialization_alias="reviewedAt")
    created_at: Optional[datetime] = Field(default=None, serialization_alias="createdAt")


class EnrichmentReport(BaseModel):
    """A toolset's enrichment state: flags, proposals and whether the copilot is on.

    Attributes:
        schema_version: The projection's shape.
        toolset_id: The toolset.
        description_enrichment: Whether accepted proposals are served.
        mode: ``copilot`` when a model is configured, else ``flag-only``.
        model: The configured model, if any.
        flags: The agent-hostile tools, ordered by operation key.
        proposals: Every proposal, ordered by operation.
        counts: ``flagged`` tools and proposals by status.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=ENRICHMENT_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    toolset_id: str = Field(serialization_alias="toolsetId")
    description_enrichment: bool = Field(serialization_alias="descriptionEnrichment")
    mode: Literal["copilot", "flag-only"]
    model: Optional[str] = None
    flags: List[EnrichmentFlagOut]
    proposals: List[EnrichmentProposalOut]
    counts: Dict[str, int]


class EnrichmentRunResult(EnrichmentReport):
    """What one run of the pass did, plus the resulting report.

    Attributes:
        generated: Proposals stored by this run.
        attempted_operations: Operations the copilot was asked about.
        failed_operations: Of those, how many got no usable answer (unreachable model, bad reply).
        remaining_operations: Operations with undescribed targets left for a later run.
    """

    generated: int
    attempted_operations: int = Field(serialization_alias="attemptedOperations")
    failed_operations: int = Field(serialization_alias="failedOperations")
    remaining_operations: int = Field(serialization_alias="remainingOperations")


class EnrichmentRun(BaseModel):
    """Body of ``POST …/agent-toolsets/{id}/enrichment``. Every field is optional.

    Attributes:
        operations: Only ask about these operation keys (``GET /pets``). Default: every operation
            with an undescribed target, in canonical order.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operations: Optional[List[str]] = Field(default=None, max_length=500)


class EnrichmentReview(BaseModel):
    """Body of ``PATCH …/agent-toolsets/{id}/enrichment/{proposalId}``.

    Attributes:
        decision: ``accept`` serves the description; ``reject`` withdraws it.
        description: With ``accept``, an edited text to serve instead of the proposal.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    decision: Literal["accept", "reject"]
    description: Optional[str] = Field(default=None, max_length=MAX_TOOL_DESCRIPTION_CHARS)


class CompiledToolsetOut(BaseModel):
    """The toolset as agents are served it: enabled tools, accepted descriptions applied.

    Attributes:
        schema_version: The projection's shape.
        toolset_id: The toolset.
        version_id: Its published version.
        enabled: Whether the toolset serves agents (a disabled one compiles to no tools).
        description_enrichment: Whether accepted proposals were applied.
        enriched_targets: The target keys whose accepted text was applied.
        fingerprint: The compiled toolset's content hash.
        tools: The MCP ``tools/list`` entries, in canonical order.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=ENRICHMENT_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    toolset_id: str = Field(serialization_alias="toolsetId")
    version_id: str = Field(serialization_alias="versionId")
    enabled: bool
    description_enrichment: bool = Field(serialization_alias="descriptionEnrichment")
    enriched_targets: List[str] = Field(serialization_alias="enrichedTargets")
    fingerprint: str
    tools: List[Dict[str, Any]]


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def configured_model() -> Optional[str]:
    """Return the configured copilot model, or ``None`` when the pass is flag-only."""
    model = (settings.agent_enrichment_model or "").strip()
    return model or None


def _toolset_row(tenant_id: str, toolset_id: str) -> Mapping[str, Any]:
    """Return the toolset row, or refuse with ``agent-toolset-not-found``."""
    row = db.get_agent_toolset(tenant_id, toolset_id)
    if row is None:
        raise AgentToolsetError(CODE_TOOLSET_NOT_FOUND, "no such agent toolset")
    return row


def _load_api(tenant_id: str, row: Mapping[str, Any]) -> CanonicalApi:
    """Rebuild the toolset version's canonical model, the way AGX-1.2 seeded it.

    Goes through :func:`app.agent_toolsets._load_version_api` so operation keys match the tool rows.

    Raises:
        AgentToolsetError: ``agent-toolset-source-unavailable`` when the source cannot be read.
    """
    try:
        return agent_toolsets._load_version_api(
            tenant_id, str(row["project_id"]), str(row["version_id"])
        )
    except ExportSourceError as exc:
        raise AgentToolsetError(
            CODE_TOOLSET_SOURCE_UNAVAILABLE, f"the version's operations could not be read: {exc}"
        ) from exc


def _toolset_operations(api: CanonicalApi, keys: Sequence[str]) -> List[Operation]:
    """The toolset's callable operations, in the compiler's canonical order."""
    wanted = set(keys)
    return [
        operation
        for _service, operation in selectable_operations(
            normalize_ordering(api), include_deprecated=True
        )
        if operation.key in wanted
    ]


def _proposal_out(row: Mapping[str, Any]) -> EnrichmentProposalOut:
    """Project a ``db.*agent_toolset_enrichment*`` row onto :class:`EnrichmentProposalOut`."""
    return EnrichmentProposalOut(
        id=str(row["id"]),
        operation=str(row["operation_key"]),
        target_kind=row["target_kind"],
        target_key=str(row["target_key"]),
        parameter=row.get("parameter_name"),
        original_description=row.get("original_description"),
        proposed_description=str(row["proposed_description"]),
        model=str(row["model"]),
        status=row["status"],
        accepted_description=row.get("accepted_description"),
        reviewed_by=row.get("reviewed_by"),
        reviewed_at=row.get("reviewed_at"),
        created_at=row.get("created_at"),
    )


def _report(
    tenant_id: str,
    toolset_id: str,
    row: Mapping[str, Any],
    api: CanonicalApi,
    tool_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Assemble the fields of an :class:`EnrichmentReport`."""
    names = {str(tool["operation_key"]): str(tool["tool_name"]) for tool in tool_rows}
    operations = _toolset_operations(api, list(names))
    flags = [
        EnrichmentFlagOut(
            operation=flag.operation_key,
            tool_name=names.get(flag.operation_key),
            reasons=[reason.to_dict() for reason in flag.reasons],
        )
        for flag in agent_hostile_flags(api, operations)
    ]
    proposals = [_proposal_out(r) for r in db.list_agent_toolset_enrichments(tenant_id, toolset_id)]
    counts = {"flagged": len(flags)}
    counts.update({status: sum(1 for p in proposals if p.status == status) for status in _STATUSES})
    model = configured_model()
    return {
        "toolset_id": toolset_id,
        "description_enrichment": bool(row.get("description_enrichment", True)),
        "mode": MODE_COPILOT if model else MODE_FLAG_ONLY,
        "model": model,
        "flags": flags,
        "proposals": proposals,
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def get_toolset_enrichment(tenant_id: str, toolset_id: str) -> EnrichmentReport:
    """Describe a toolset's agent-hostile tools and its description proposals.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.

    Returns:
        The report.

    Raises:
        AgentToolsetError: ``agent-toolset-not-found``; ``agent-toolset-source-unavailable``.
    """
    row = _toolset_row(tenant_id, toolset_id)
    api = _load_api(tenant_id, row)
    tool_rows = db.list_agent_toolset_tools(tenant_id, toolset_id)
    return EnrichmentReport(**_report(tenant_id, toolset_id, row, api, tool_rows))


def _proposal_row(target: EnrichmentTarget, text: str, model: str) -> Dict[str, Any]:
    """The insert mapping for one proposal."""
    return {
        "operation_key": target.operation_key,
        "target_kind": target.kind,
        "target_key": target.target_key,
        "parameter_name": target.parameter if target.kind == TARGET_PARAMETER else None,
        "original_description": target.original,
        "proposed_description": text,
        "model": model,
    }


def run_toolset_enrichment(
    tenant_id: str,
    toolset_id: str,
    body: Optional[EnrichmentRun] = None,
    *,
    generate: Optional[DescriptionGenerator] = None,
) -> EnrichmentRunResult:
    """Run the enrichment pass over a toolset: flag, and propose when the copilot is configured.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.
        body: Optionally, the operations to ask about.
        generate: The copilot call (default: Ollama via :func:`app.ollama_chat.chat_completion`).

    Returns:
        What the run did and the report after it.

    Raises:
        AgentToolsetError: ``agent-toolset-not-found``; ``agent-toolset-source-unavailable``;
            ``agent-toolset-enrichment-invalid`` when ``operations`` names an operation the
            toolset does not have.
    """
    row = _toolset_row(tenant_id, toolset_id)
    api = _load_api(tenant_id, row)
    tool_rows = db.list_agent_toolset_tools(tenant_id, toolset_id)
    keys = [str(tool["operation_key"]) for tool in tool_rows]

    requested = body.operations if body and body.operations is not None else None
    if requested is not None:
        unknown = sorted(set(requested) - set(keys))
        if unknown:
            raise AgentToolsetError(
                CODE_ENRICHMENT_INVALID,
                *(f"{key} is not an operation of this toolset" for key in unknown),
            )
        keys = [key for key in keys if key in set(requested)]

    described = {str(r["target_key"]) for r in db.list_agent_toolset_enrichments(tenant_id, toolset_id)}
    pending: List[Tuple[Operation, List[EnrichmentTarget]]] = []
    for operation in _toolset_operations(api, keys):
        targets = [t for t in enrichment_targets(operation) if t.target_key not in described]
        if targets:
            pending.append((operation, targets))

    model = configured_model()
    batch = pending[:MAX_OPERATIONS_PER_RUN] if model else []
    call = generate or _ollama_json
    rows: List[Dict[str, Any]] = []
    failed = 0
    for operation, targets in batch:
        reply = call(model or "", SYSTEM_PROMPT, build_enrichment_prompt(api, operation, targets))
        proposals = parse_enrichment_reply(reply, targets)
        if not proposals:
            failed += 1
        rows.extend(
            _proposal_row(target, proposals[target.target_key], model or "")
            for target in targets
            if target.target_key in proposals
        )
    generated = db.insert_agent_toolset_enrichments(tenant_id, toolset_id, rows) if rows else 0

    return EnrichmentRunResult(
        **_report(tenant_id, toolset_id, row, api, tool_rows),
        generated=generated,
        attempted_operations=len(batch),
        failed_operations=failed,
        remaining_operations=len(pending) - len(batch),
    )


def review_toolset_enrichment(
    tenant_id: str,
    toolset_id: str,
    enrichment_id: str,
    body: EnrichmentReview,
    *,
    actor_id: Optional[str] = None,
) -> Tuple[EnrichmentProposalOut, EnrichmentProposalOut]:
    """Accept (optionally with an edit) or reject one proposal.

    A decision can be changed later: rejecting an accepted proposal stops serving it.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.
        enrichment_id: The proposal.
        body: The decision and an optional edited text.
        actor_id: The reviewer.

    Returns:
        ``(before, after)``, so the caller can audit the change.

    Raises:
        AgentToolsetError: ``agent-toolset-enrichment-not-found`` when the tenant's toolset has no
            such proposal; ``agent-toolset-enrichment-invalid`` for an edit with ``reject``, a
            blank edit, or a parameter edit over :data:`MAX_PARAM_DESCRIPTION_CHARS`.
    """
    current = db.get_agent_toolset_enrichment(tenant_id, toolset_id, enrichment_id)
    if current is None:
        raise AgentToolsetError(CODE_ENRICHMENT_NOT_FOUND, "no such proposal in this agent toolset")
    text: Optional[str] = None
    if body.decision == "reject":
        if body.description is not None:
            raise AgentToolsetError(
                CODE_ENRICHMENT_INVALID, "description can only be given when accepting"
            )
    else:
        text = (body.description if body.description is not None else current["proposed_description"])
        text = (text or "").strip()
        limit = (
            MAX_TOOL_DESCRIPTION_CHARS
            if current["target_kind"] == TARGET_TOOL
            else MAX_PARAM_DESCRIPTION_CHARS
        )
        if not text:
            raise AgentToolsetError(CODE_ENRICHMENT_INVALID, "description must not be blank")
        if len(text) > limit:
            raise AgentToolsetError(
                CODE_ENRICHMENT_INVALID,
                f"a {current['target_kind']} description is at most {limit} characters",
            )
    row = db.review_agent_toolset_enrichment(
        tenant_id,
        toolset_id,
        enrichment_id,
        status="accepted" if body.decision == "accept" else "rejected",
        accepted_description=text,
        actor_id=actor_id,
    )
    if row is None:
        # Deleted between the read and the write.
        raise AgentToolsetError(CODE_ENRICHMENT_NOT_FOUND, "no such proposal in this agent toolset")
    return _proposal_out(current), _proposal_out(row)


def compile_agent_toolset(tenant_id: str, toolset_id: str) -> CompiledToolsetOut:
    """Compile the toolset as agents are served it.

    The enabled tools of the toolset, compiled by :func:`app.mcp_tool_mapping.compile_mcp_tools`
    from the version's model. While ``description_enrichment`` is on, accepted proposals are
    written into the model first (:func:`app.agent_tool_enrichment.apply_description_overrides`);
    proposed and rejected ones never are. A disabled toolset compiles to no tools.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.

    Returns:
        The compiled toolset.

    Raises:
        AgentToolsetError: ``agent-toolset-not-found``; ``agent-toolset-source-unavailable`` when
            the version cannot be read or compiled.
    """
    row = _toolset_row(tenant_id, toolset_id)
    enabled = bool(row.get("enabled"))
    enrichment_on = bool(row.get("description_enrichment", True))
    exposed = (
        [str(t["operation_key"]) for t in db.list_agent_toolset_tools(tenant_id, toolset_id) if t["enabled"]]
        if enabled
        else []
    )
    api = _load_api(tenant_id, row)
    overrides: Dict[str, str] = {}
    if enrichment_on and exposed:
        overrides = served_description_overrides(
            db.list_agent_toolset_enrichments(tenant_id, toolset_id, status="accepted"), exposed
        )
    try:
        compiled = compile_mcp_tools(apply_description_overrides(api, overrides), exposed=exposed)
    except McpToolMappingError as exc:
        raise AgentToolsetError(
            CODE_TOOLSET_SOURCE_UNAVAILABLE, f"the toolset could not be compiled: {exc}"
        ) from exc
    return CompiledToolsetOut(
        toolset_id=toolset_id,
        version_id=str(row["version_id"]),
        enabled=enabled,
        description_enrichment=enrichment_on,
        enriched_targets=sorted(overrides),
        fingerprint=compiled.fingerprint(),
        tools=compiled.mcp_tools(),
    )
