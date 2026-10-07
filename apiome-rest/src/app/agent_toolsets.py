"""Agent toolsets: tool selection & curation — AGX-1.2 (#4530).

Switching on Agent Access for a published version must not hand an agent every operation the spec
contains. A ``DELETE /users/{id}`` would otherwise become callable the moment access is switched
on. A **toolset** (``apiome.agent_toolsets``, V270) is a tenant's curated choice of which of one
published version's operations its agents may call. Each callable operation has a **tool row**
(``apiome.agent_toolset_tools``) recording whether it is exposed.

**Safe by default: reads on, writes opt-in.** When a toolset is created, every callable operation
of the version gets a row. Read operations are enabled (:func:`is_write_operation` is ``False``
for HTTP ``GET``/``HEAD`` and GraphQL queries), except deprecated ones, which the AGX-1.1
compiler's own default leaves out too. Every other operation is a **write op**: it starts
disabled, and enabling it needs ``confirmWriteOp: true``. Without that the request is refused
with ``agent-toolset-write-op-unconfirmed``. The confirmation is stamped on the row (who and
when), and V270's CHECK makes an enabled but unconfirmed write op impossible to store.

**Tools are the compiler's tools.** Rows reference operations by canonical key (``GET /pets/{id}``),
the reference :func:`app.mcp_tool_mapping.compile_mcp_tools` resolves, and record the compiled MCP
tool name. The name is derived over every callable operation, so curating one tool never renames
another. The apiome-mcp agent runtime reads the enabled names straight from the table.

Routes are in :mod:`app.agent_toolset_routes` and the SQL in ``db.*agent_toolset*``. Every change
is audited there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from .canonical_model import CanonicalApi, Operation, OperationKind
from .database import db
from .export_source import ExportSourceError, load_export_source
from .mcp_tool_mapping import McpToolMappingError, compile_mcp_tools
from .normalizer import normalize_ordering
from .tool_projection import selectable_operations

__all__ = [
    "AGENT_TOOLSET_SCHEMA_VERSION",
    "CODE_TOOLSET_EXISTS",
    "CODE_TOOLSET_INVALID",
    "CODE_TOOLSET_NOT_FOUND",
    "CODE_TOOLSET_SOURCE_UNAVAILABLE",
    "CODE_TOOL_NOT_FOUND",
    "CODE_VERSION_NOT_FOUND",
    "CODE_VERSION_UNPUBLISHED",
    "CODE_WRITE_OP_UNCONFIRMED",
    "DEFAULT_TARGET",
    "READ_HTTP_METHODS",
    "AgentToolOut",
    "AgentToolUpdate",
    "AgentToolsetCreate",
    "AgentToolsetDetail",
    "AgentToolsetError",
    "AgentToolsetOut",
    "AgentToolsetUpdate",
    "ToolSeed",
    "ToolsetTarget",
    "audit_tool_detail",
    "create_agent_toolset",
    "delete_agent_toolset",
    "get_agent_toolset",
    "is_write_operation",
    "list_agent_toolset_tools",
    "list_agent_toolsets",
    "seed_tools",
    "update_agent_toolset",
    "update_agent_toolset_tool",
]

#: The addressable shape of the toolset projections.
AGENT_TOOLSET_SCHEMA_VERSION = "agx.agent-toolset.v1"

#: HTTP methods that read. Every other method is a write op (opt-in).
READ_HTTP_METHODS = frozenset({"GET", "HEAD"})

#: Where tool calls go (V270 ``agent_toolsets_target_ck``; AGX-2.4 consumes it).
ToolsetTarget = Literal["prod", "mock"]

#: The target a new toolset gets when the request names none.
DEFAULT_TARGET: ToolsetTarget = "prod"

#: Refusal codes. :mod:`app.agent_toolset_routes` maps them to HTTP statuses.
CODE_TOOLSET_INVALID = "agent-toolset-invalid"
CODE_TOOLSET_EXISTS = "agent-toolset-exists"
CODE_TOOLSET_NOT_FOUND = "agent-toolset-not-found"
CODE_TOOLSET_SOURCE_UNAVAILABLE = "agent-toolset-source-unavailable"
CODE_TOOL_NOT_FOUND = "agent-toolset-tool-not-found"
CODE_VERSION_NOT_FOUND = "agent-toolset-version-not-found"
CODE_VERSION_UNPUBLISHED = "agent-toolset-version-unpublished"
CODE_WRITE_OP_UNCONFIRMED = "agent-toolset-write-op-unconfirmed"


class AgentToolsetError(ValueError):
    """A toolset request was refused.

    Attributes:
        code: One of the ``CODE_*`` constants.
        errors: One message per problem.
    """

    def __init__(self, code: str, *errors: str) -> None:
        super().__init__("; ".join(errors) or code)
        self.code = code
        self.errors: Tuple[str, ...] = tuple(errors)


class AgentToolsetCreate(BaseModel):
    """Body of ``POST /v1/tenants/{t}/agent-toolsets``.

    Attributes:
        version_id: The published version (``versions.id``) to give Agent Access.
        enabled: Whether the toolset serves agents straight away (default ``True``).
        target: ``prod`` (default) or ``mock``.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    version_id: UUID = Field(alias="versionId")
    enabled: bool = True
    target: ToolsetTarget = DEFAULT_TARGET


class AgentToolsetUpdate(BaseModel):
    """Body of ``PATCH /v1/tenants/{t}/agent-toolsets/{id}``. At least one field is required.

    Attributes:
        enabled: Switch the whole toolset on or off.
        target: ``prod`` or ``mock``.
        description_enrichment: Serve accepted description-enrichment proposals (AGX-1.3), or
            opt out and serve the spec-derived descriptions unchanged.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enabled: Optional[bool] = None
    target: Optional[ToolsetTarget] = None
    description_enrichment: Optional[bool] = Field(default=None, alias="descriptionEnrichment")


class AgentToolUpdate(BaseModel):
    """Body of ``PATCH /v1/tenants/{t}/agent-toolsets/{id}/tools/{toolId}``.

    Attributes:
        enabled: Expose the operation to agents, or stop exposing it.
        confirm_write_op: Must be ``true`` to enable a write op. It is ignored when disabling,
            and when enabling a read.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    enabled: bool
    confirm_write_op: bool = Field(default=False, alias="confirmWriteOp")


class AgentToolOut(BaseModel):
    """One operation's exposure decision.

    Attributes:
        id: The tool row id (what the update route addresses).
        operation: The canonical operation key (``GET /pets/{id}``).
        tool_name: The MCP tool name agents see.
        write_op: Whether the operation mutates. A write op is opt-in.
        enabled: Whether agents may list and call it.
        write_confirmed_at: When enabling this write op was confirmed (only while enabled).
        write_confirmed_by: Who confirmed it.
        updated_at: When the row last changed.
        updated_by: Who last changed it.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    operation: str
    tool_name: str = Field(serialization_alias="toolName")
    write_op: bool = Field(serialization_alias="writeOp")
    enabled: bool
    write_confirmed_at: Optional[datetime] = Field(
        default=None, serialization_alias="writeConfirmedAt"
    )
    write_confirmed_by: Optional[str] = Field(default=None, serialization_alias="writeConfirmedBy")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    updated_by: Optional[str] = Field(default=None, serialization_alias="updatedBy")


class AgentToolsetOut(BaseModel):
    """A toolset, described with its tool counts.

    Attributes:
        schema_version: The projection's shape.
        id: The toolset id (what agent keys and upstream credentials bind to).
        version_id: The published version it exposes.
        project_id: That version's project.
        version_label: The version's label (``1.0.0``).
        enabled: Whether it serves agents at all.
        target: ``prod`` or ``mock``.
        description_enrichment: Whether accepted description-enrichment proposals are served
            (AGX-1.3). ``False`` serves the spec-derived descriptions unchanged.
        tool_count: Callable operations in the version.
        enabled_tool_count: How many of them are exposed.
        enabled_write_op_count: How many exposed ones are write ops.
        created_at: When it was created.
        updated_at: When its settings last changed.
        created_by: Who created it.
        updated_by: Who last changed its settings.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=AGENT_TOOLSET_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    id: str
    version_id: str = Field(serialization_alias="versionId")
    project_id: str = Field(serialization_alias="projectId")
    version_label: Optional[str] = Field(default=None, serialization_alias="versionLabel")
    enabled: bool
    target: ToolsetTarget
    description_enrichment: bool = Field(
        default=True, serialization_alias="descriptionEnrichment"
    )
    tool_count: int = Field(serialization_alias="toolCount")
    enabled_tool_count: int = Field(serialization_alias="enabledToolCount")
    enabled_write_op_count: int = Field(serialization_alias="enabledWriteOpCount")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")
    updated_by: Optional[str] = Field(default=None, serialization_alias="updatedBy")


class AgentToolsetDetail(AgentToolsetOut):
    """A toolset with every tool row, ordered by operation key."""

    tools: List[AgentToolOut]


class ToolSeed(BaseModel):
    """The initial row for one callable operation of a new toolset.

    Attributes:
        operation_key: The canonical operation key.
        tool_name: The compiled MCP tool name.
        write_op: Whether the operation mutates.
        enabled: The safe default: a non-deprecated read is on, everything else is off.
    """

    model_config = ConfigDict(frozen=True)

    operation_key: str
    tool_name: str
    write_op: bool
    enabled: bool


def is_write_operation(operation: Operation) -> bool:
    """Classify an operation for the safe-by-default policy.

    An operation with an HTTP method is a read only for ``GET`` and ``HEAD``. Without one, only a
    GraphQL ``query`` is a read. Anything that cannot be shown to be a read counts as a write, so
    an unknown verb or an RPC method is opt-in rather than exposed.

    Args:
        operation: A canonical operation.

    Returns:
        ``True`` when the operation must be opted into.
    """
    if operation.http_method:
        return operation.http_method.strip().upper() not in READ_HTTP_METHODS
    return operation.kind != OperationKind.QUERY


def seed_tools(api: CanonicalApi) -> List[ToolSeed]:
    """Work out the initial tool rows for a version's canonical model.

    Every operation the compiler can turn into a tool gets a row, deprecated ones included, and is
    named exactly as :func:`compile_mcp_tools` names it.

    Args:
        api: The version's canonical model.

    Returns:
        One seed per callable operation, in the compiler's canonical order.

    Raises:
        McpToolMappingError: When the compiler cannot produce a valid toolset for the model.
    """
    ordered = normalize_ordering(api)
    operations = {
        operation.key: operation
        for _service, operation in selectable_operations(ordered, include_deprecated=True)
    }
    if not operations:
        return []
    compiled = compile_mcp_tools(ordered, exposed=list(operations))
    seeds: List[ToolSeed] = []
    for tool in compiled.tools:
        operation = operations[tool.operation]
        write_op = is_write_operation(operation)
        seeds.append(
            ToolSeed(
                operation_key=tool.operation,
                tool_name=tool.name,
                write_op=write_op,
                enabled=not write_op and not operation.deprecated,
            )
        )
    return seeds


def _load_version_api(tenant_id: str, project_id: str, version_id: str) -> CanonicalApi:
    """Rebuild a version's canonical model from its captured source.

    Args:
        tenant_id: Owning tenant.
        project_id: The version's project.
        version_id: The version (``versions.id``).

    Returns:
        The canonical model.

    Raises:
        ExportSourceError: When the version has no reconstructable source.
    """
    return load_export_source(tenant_id, project_id, version_id).api


def _count(value: Any) -> int:
    """Read a ``count(*)`` column, which a fake or a NULL may leave unset."""
    return int(value or 0)


def _toolset_out(row: Mapping[str, Any]) -> AgentToolsetOut:
    """Project a ``db.*agent_toolset*`` row onto :class:`AgentToolsetOut`."""
    return AgentToolsetOut(
        id=str(row["id"]),
        version_id=str(row["version_id"]),
        project_id=str(row["project_id"]),
        version_label=row.get("version_label"),
        enabled=bool(row["enabled"]),
        target=row["target"],
        description_enrichment=bool(row.get("description_enrichment", True)),
        tool_count=_count(row.get("tool_count")),
        enabled_tool_count=_count(row.get("enabled_tool_count")),
        enabled_write_op_count=_count(row.get("enabled_write_op_count")),
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
        created_by=row.get("created_by"),
        updated_by=row.get("updated_by"),
    )


def _tool_out(row: Mapping[str, Any]) -> AgentToolOut:
    """Project a ``db.*agent_toolset_tool*`` row onto :class:`AgentToolOut`."""
    return AgentToolOut(
        id=str(row["id"]),
        operation=str(row["operation_key"]),
        tool_name=str(row["tool_name"]),
        write_op=bool(row["write_op"]),
        enabled=bool(row["enabled"]),
        write_confirmed_at=row.get("write_confirmed_at"),
        write_confirmed_by=row.get("write_confirmed_by"),
        updated_at=row.get("updated_at"),
        updated_by=row.get("updated_by"),
    )


def _not_found() -> AgentToolsetError:
    """The refusal for a toolset the tenant does not have."""
    return AgentToolsetError(CODE_TOOLSET_NOT_FOUND, "no such agent toolset")


def create_agent_toolset(
    tenant_id: str,
    body: AgentToolsetCreate,
    *,
    actor_id: Optional[str] = None,
) -> AgentToolsetDetail:
    """Create a toolset for a published version, seeded safe by default.

    Args:
        tenant_id: The caller's tenant.
        body: The version, and optionally ``enabled`` / ``target``.
        actor_id: The user creating it.

    Returns:
        The new toolset with its tool rows.

    Raises:
        AgentToolsetError: ``agent-toolset-version-not-found`` when the tenant has no such
            version; ``agent-toolset-version-unpublished`` when it is not published (or is
            deleted); ``agent-toolset-source-unavailable`` when its operations cannot be read;
            ``agent-toolset-exists`` when the version already has a toolset.
    """
    version_id = str(body.version_id)
    version = db.get_agent_toolset_version(tenant_id, version_id)
    if version is None:
        raise AgentToolsetError(CODE_VERSION_NOT_FOUND, "no such version in this tenant")
    if not version.get("published") or version.get("deleted"):
        raise AgentToolsetError(
            CODE_VERSION_UNPUBLISHED,
            "Agent Access can only be enabled for a published, undeleted version",
        )
    try:
        api = _load_version_api(tenant_id, str(version["project_id"]), version_id)
        seeds = seed_tools(api)
    except (ExportSourceError, McpToolMappingError) as exc:
        raise AgentToolsetError(
            CODE_TOOLSET_SOURCE_UNAVAILABLE, f"the version's operations could not be read: {exc}"
        ) from exc

    row = db.insert_agent_toolset(
        tenant_id=tenant_id,
        version_id=version_id,
        enabled=body.enabled,
        target=body.target,
        tools=[seed.model_dump() for seed in seeds],
        actor_id=actor_id,
    )
    if row is None:
        raise AgentToolsetError(CODE_TOOLSET_EXISTS, "this version already has an agent toolset")
    return AgentToolsetDetail(
        **_toolset_out(row).model_dump(),
        tools=list_agent_toolset_tools(tenant_id, str(row["id"])),
    )


def list_agent_toolsets(
    tenant_id: str, *, version_id: Optional[str] = None
) -> List[AgentToolsetOut]:
    """Describe a tenant's toolsets, newest first.

    Args:
        tenant_id: The caller's tenant.
        version_id: When set, only that version's toolset.

    Returns:
        The toolsets with their tool counts.
    """
    return [_toolset_out(row) for row in db.list_agent_toolsets(tenant_id, version_id=version_id)]


def get_agent_toolset(tenant_id: str, toolset_id: str) -> AgentToolsetDetail:
    """Describe one toolset with every tool row.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.

    Returns:
        The toolset and its tools.

    Raises:
        AgentToolsetError: ``agent-toolset-not-found`` when the tenant has no such toolset.
    """
    row = db.get_agent_toolset(tenant_id, toolset_id)
    if row is None:
        raise _not_found()
    return AgentToolsetDetail(
        **_toolset_out(row).model_dump(), tools=list_agent_toolset_tools(tenant_id, toolset_id)
    )


def list_agent_toolset_tools(tenant_id: str, toolset_id: str) -> List[AgentToolOut]:
    """Describe a toolset's tool rows, ordered by operation key.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.

    Returns:
        The tool rows; empty for a toolset the tenant does not have.
    """
    return [_tool_out(row) for row in db.list_agent_toolset_tools(tenant_id, toolset_id)]


def update_agent_toolset(
    tenant_id: str,
    toolset_id: str,
    body: AgentToolsetUpdate,
    *,
    actor_id: Optional[str] = None,
) -> Tuple[AgentToolsetOut, AgentToolsetOut]:
    """Switch a toolset on or off, change its target, and/or opt in or out of enrichment.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.
        body: The fields to change.
        actor_id: The user changing it.

    Returns:
        ``(before, after)``, so the caller can audit the change.

    Raises:
        AgentToolsetError: ``agent-toolset-invalid`` when the body changes nothing;
            ``agent-toolset-not-found`` when the tenant has no such toolset.
    """
    if body.enabled is None and body.target is None and body.description_enrichment is None:
        raise AgentToolsetError(
            CODE_TOOLSET_INVALID, "set at least one of enabled, target, descriptionEnrichment"
        )
    current = db.get_agent_toolset(tenant_id, toolset_id)
    if current is None:
        raise _not_found()
    row = db.update_agent_toolset(
        tenant_id,
        toolset_id,
        enabled=body.enabled,
        target=body.target,
        description_enrichment=body.description_enrichment,
        actor_id=actor_id,
    )
    if row is None:
        # Deleted between the read and the write.
        raise _not_found()
    return _toolset_out(current), _toolset_out(row)


def delete_agent_toolset(tenant_id: str, toolset_id: str) -> AgentToolsetOut:
    """Delete a toolset, with its tool rows, upstream credentials and agent keys.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.

    Returns:
        The toolset as it was before deletion.

    Raises:
        AgentToolsetError: ``agent-toolset-not-found`` when the tenant has no such toolset.
    """
    row = db.delete_agent_toolset(tenant_id, toolset_id)
    if row is None:
        raise _not_found()
    return _toolset_out(row)


def update_agent_toolset_tool(
    tenant_id: str,
    toolset_id: str,
    tool_id: str,
    body: AgentToolUpdate,
    *,
    actor_id: Optional[str] = None,
) -> Tuple[AgentToolOut, AgentToolOut]:
    """Enable or disable one tool. Enabling a write op requires ``confirmWriteOp``.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: The toolset.
        tool_id: The tool row.
        body: The new state and the write-op confirmation.
        actor_id: The user changing it (also recorded as the confirmer of a write op).

    Returns:
        ``(before, after)``, so the caller can audit the change.

    Raises:
        AgentToolsetError: ``agent-toolset-tool-not-found`` when the tenant's toolset has no such
            tool; ``agent-toolset-write-op-unconfirmed`` when enabling a write op without
            ``confirmWriteOp: true``.
    """
    current = db.get_agent_toolset_tool(tenant_id, toolset_id, tool_id)
    if current is None:
        raise AgentToolsetError(CODE_TOOL_NOT_FOUND, "no such tool in this agent toolset")
    if body.enabled and current.get("write_op") and not body.confirm_write_op:
        raise AgentToolsetError(
            CODE_WRITE_OP_UNCONFIRMED,
            f"{current['operation_key']} is a write operation; enabling it requires "
            "confirmWriteOp: true",
        )
    row = db.set_agent_toolset_tool_enabled(
        tenant_id,
        toolset_id,
        tool_id,
        enabled=body.enabled,
        confirm_write_op=body.confirm_write_op,
        actor_id=actor_id,
    )
    if row is None:
        # Deleted between the read and the write.
        raise AgentToolsetError(CODE_TOOL_NOT_FOUND, "no such tool in this agent toolset")
    return _tool_out(current), _tool_out(row)


def audit_tool_detail(before: AgentToolOut, after: AgentToolOut) -> Dict[str, Any]:
    """The metadata an access-audit row records for one tool change.

    Args:
        before: The row before the change.
        after: The row after it.

    Returns:
        The operation, tool name, write-op flag, enabled before/after and, for an enabled write
        op, when its confirmation was given.
    """
    return {
        "operation": after.operation,
        "toolName": after.tool_name,
        "writeOp": after.write_op,
        "enabledBefore": before.enabled,
        "enabledAfter": after.enabled,
        "writeConfirmedAt": (
            after.write_confirmed_at.isoformat() if after.write_confirmed_at else None
        ),
    }
