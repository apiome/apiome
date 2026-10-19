"""Agent and model entities — reads and writes — CDG-5.2 (#5980).

Models and agents are plain rows (V297). What makes an agent more than a row is
:func:`sync_agent_consumers`: an agent is a **consumer** of every project its keys reach, so CTG
impact and the blast radius include it. For each such project the agent has one ``consumer`` row
(found by the agent's slug, or created — "creates or links") and a current ``consumer_contract``
with source ``agent`` whose operations are what its live keys may call: the enabled tools of each
key's enabled toolset that are on the key's allowlist. The CDG-3.1 ``consumes`` family derives the
graph edges from that contract, one per operation.

When a key is revoked or unlinked, or the agent is retired or deleted, the next sync records a new
revision without those operations (empty when nothing is left), and the ``consumes`` family marks
the edges it no longer produces stale. A sync whose operations are unchanged records nothing.

Every write runs in one transaction (``db._guarded_tx``) and is audited on the tenant's access
audit as ``catalog.agent.*`` / ``catalog.model.*``.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any, Callable, Dict, List, Optional, Sequence

import psycopg2

from . import consumer_contract_store
from .agent_keys import key_status
from .catalog_agents import (
    AGENT_STATUSES,
    CODE_AGENT_NOT_FOUND,
    CODE_AGENT_SLUG_TAKEN,
    CODE_KEY_INVALID,
    CODE_KEY_NOT_LINKED,
    CODE_KEY_TAKEN,
    CODE_MODEL_NOT_FOUND,
    CODE_MODEL_SLUG_TAKEN,
    MODEL_HOSTINGS,
    AgentConsumerRef,
    AgentInput,
    AgentKeyRef,
    AgentOut,
    AgentPatch,
    AgentRef,
    CatalogAgentError,
    ModelInput,
    ModelOut,
    ModelPatch,
    agent_surface,
    check_choice,
    is_deprecated,
    model_ref,
    normalize_name,
    optional_text,
    resolve_slug,
)
from .consumer_contract import SOURCE_AGENT, UnresolvedInteraction, contract_pointers
from .consumer_contract_store import ConsumerActor, ConsumerValidationError
from .database import db
from .entity_owners import owner_envelope_join, owner_ref_from_value
from .revision_deprecation import is_uuid_string

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------------------------
# Shared SQL
# ---------------------------------------------------------------------------------------------

_MODEL_COLUMNS = """
    m.id::text AS id, m.slug, m.name, m.provider, m.model_name, m.model_version, m.hosting,
    m.data_handling, m.deprecated_at, m.created_at, m.updated_at
"""

_AGENT_COLUMNS = """
    a.id::text AS id, a.slug, a.name, a.description, a.runtime, a.status, a.created_at, a.updated_at,
    m.id::text AS m_id, m.slug AS m_slug, m.name AS m_name, m.provider AS m_provider,
    m.model_version AS m_model_version, m.deprecated_at AS m_deprecated_at
"""

_AGENT_MODEL_JOIN = "LEFT JOIN apiome.catalog_models m ON m.id = a.model_id AND m.deleted_at IS NULL"

#: An agent's keys, with the toolset's project and how many tools each key may call. Never
#: ``key_hash``.
_AGENT_KEYS_SQL = """
    SELECT k.id::text AS id, k.name, k.key_prefix, k.enabled, k.expires_at,
           k.deleted_at AS revoked_at, k.last_used_at, k.toolset_id::text AS toolset_id,
           v.project_id::text AS project_id, p.name AS project_name, v.version_id AS version_label,
           (SELECT count(*) FROM apiome.agent_toolset_tools tt
             WHERE tt.toolset_id = k.toolset_id AND tt.enabled
               AND COALESCE(k.tool_allowlist, '[]'::jsonb) ? tt.tool_name)::int AS enabled_tools
    FROM apiome.catalog_agent_keys cak
    JOIN apiome.api_keys k ON k.id = cak.api_key_id AND k.kind = 'agent'
    LEFT JOIN apiome.agent_toolsets t ON t.id = k.toolset_id
    LEFT JOIN apiome.versions v ON v.id = t.version_id
    LEFT JOIN apiome.projects p ON p.id = v.project_id
    WHERE cak.agent_id = %s::uuid
    ORDER BY lower(k.name), k.id
"""

#: What an agent's live keys may call, per project: live, enabled keys of an active agent; enabled
#: toolsets; enabled tools on the key's allowlist.
_AGENT_OPERATIONS_SQL = """
    SELECT v.project_id::text AS project_id, v.id::text AS version_id, v.version_id AS version_label,
           v.created_at AS version_created_at, tt.operation_key
    FROM apiome.catalog_agents a
    JOIN apiome.catalog_agent_keys cak ON cak.agent_id = a.id
    JOIN apiome.api_keys k ON k.id = cak.api_key_id AND k.kind = 'agent'
         AND k.deleted_at IS NULL AND k.enabled
         AND (k.expires_at IS NULL OR k.expires_at > CURRENT_TIMESTAMP)
    JOIN apiome.agent_toolsets t ON t.id = k.toolset_id AND t.enabled
    JOIN apiome.agent_toolset_tools tt ON tt.toolset_id = t.id AND tt.enabled
         AND COALESCE(k.tool_allowlist, '[]'::jsonb) ? tt.tool_name
    JOIN apiome.versions v ON v.id = t.version_id
    WHERE a.id = %s::uuid AND a.tenant_id = %s::uuid AND a.deleted_at IS NULL AND a.status = 'active'
    ORDER BY v.project_id, v.created_at DESC, tt.operation_key
"""


def _audit(cursor: Any, tenant_id: str, actor: ConsumerActor, action: str, target: str, detail: Dict[str, Any]) -> None:
    """Append a ``catalog.agent.*`` / ``catalog.model.*`` row to the tenant's access audit."""
    db._append_access_audit(
        cursor,
        tenant_id=tenant_id,
        action=action,
        actor_id=actor.user_id,
        actor_label=actor.label,
        target=target,
        source="api_key" if actor.kind == "api_key" else "web",
        detail=detail,
    )


def _run(work: Callable[[Any], Any], taken_code: str, slug: str) -> Any:
    """Run ``work`` in one transaction, translating a live-slug collision into a refusal."""
    try:
        return db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        raise CatalogAgentError(taken_code, f"'{slug}' is already taken") from exc


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a UUID, else ``None`` (an unattributable API-key call)."""
    return actor.user_id if is_uuid_string(actor.user_id or "") else None


# ---------------------------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------------------------


def _model_out(row: Dict[str, Any], agents: Optional[List[AgentRef]] = None) -> ModelOut:
    """Build a :class:`ModelOut` from a ``catalog_models`` row."""
    return ModelOut(
        id=str(row["id"]),
        slug=row["slug"],
        name=row["name"],
        provider=row["provider"],
        model_name=row["model_name"],
        model_version=row.get("model_version"),
        hosting=row["hosting"],
        data_handling=row.get("data_handling"),
        deprecated_at=row.get("deprecated_at"),
        deprecated=is_deprecated(row.get("deprecated_at")),
        owner=owner_ref_from_value(row.get("entity_owner")),
        agents=agents or [],
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def list_models(tenant_id: str) -> List[ModelOut]:
    """The tenant's live models, by name, with their owners.

    Args:
        tenant_id: The tenant.

    Returns:
        The models.
    """
    rows = db.execute_query(
        f"""
        SELECT {_MODEL_COLUMNS}, own.entity_owner
        FROM apiome.catalog_models m
        {owner_envelope_join(("model",), "m.id", "m.tenant_id")}
        WHERE m.tenant_id = %s::uuid AND m.deleted_at IS NULL
        ORDER BY lower(m.name), m.id
        """,
        (tenant_id,),
    )
    return [_model_out(dict(row)) for row in rows or []]


def _model_row(tenant_id: str, slug: str) -> Dict[str, Any]:
    """One live model row with its owner, by slug (or id, as a team page links it), else ``model-not-found``."""
    rows = db.execute_query(
        f"""
        SELECT {_MODEL_COLUMNS}, own.entity_owner
        FROM apiome.catalog_models m
        {owner_envelope_join(("model",), "m.id", "m.tenant_id")}
        WHERE m.tenant_id = %s::uuid AND m.deleted_at IS NULL AND (m.slug = %s OR m.id::text = %s)
        ORDER BY (m.slug = %s) DESC
        LIMIT 1
        """,
        (tenant_id, slug, slug, slug),
    )
    if not rows:
        raise CatalogAgentError(CODE_MODEL_NOT_FOUND, f"model '{slug}' not found")
    return dict(rows[0])


def get_model(tenant_id: str, slug: str) -> ModelOut:
    """One live model with the live agents that run on it.

    Args:
        tenant_id: The tenant.
        slug: The model's slug.

    Returns:
        The model.

    Raises:
        CatalogAgentError: ``model-not-found``.
    """
    row = _model_row(tenant_id, slug)
    agents = db.execute_query(
        """
        SELECT a.id::text AS id, a.slug, a.name, a.status FROM apiome.catalog_agents a
        WHERE a.tenant_id = %s::uuid AND a.model_id = %s::uuid AND a.deleted_at IS NULL
        ORDER BY lower(a.name), a.id
        """,
        (tenant_id, row["id"]),
    )
    return _model_out(row, [AgentRef(**dict(a)) for a in agents or []])


def create_model(tenant_id: str, body: ModelInput, *, actor: ConsumerActor) -> ModelOut:
    """Register a model, audited as ``catalog.model.create``.

    Raises:
        CatalogAgentError: ``agent-invalid`` for a malformed field, ``model-slug-taken``.
    """
    model_name = normalize_name(body.model_name, field="modelName")
    name = normalize_name(body.name or model_name)
    slug = resolve_slug(body.slug, name)
    values = {
        "name": name,
        "provider": normalize_name(body.provider, field="provider"),
        "model_name": model_name,
        "model_version": optional_text(body.model_version),
        "hosting": check_choice(body.hosting, MODEL_HOSTINGS, "hosting"),
        "data_handling": optional_text(body.data_handling),
        "deprecated_at": body.deprecated_at,
    }

    def work(cursor: Any) -> str:
        cursor.execute(
            """
            INSERT INTO apiome.catalog_models
                (tenant_id, slug, name, provider, model_name, model_version, hosting, data_handling,
                 deprecated_at, created_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s::uuid)
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                slug,
                values["name"],
                values["provider"],
                values["model_name"],
                values["model_version"],
                values["hosting"],
                values["data_handling"],
                values["deprecated_at"],
                _user_id(actor),
            ),
        )
        model_id = cursor.fetchone()["id"]
        _audit(
            cursor,
            tenant_id,
            actor,
            "catalog.model.create",
            f"model:{slug}",
            {"model_id": model_id, **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in values.items()}},
        )
        return model_id

    _run(work, CODE_MODEL_SLUG_TAKEN, slug)
    return get_model(tenant_id, slug)


def update_model(tenant_id: str, slug: str, patch: ModelPatch, *, actor: ConsumerActor) -> ModelOut:
    """Change a model, audited as ``catalog.model.update`` with the fields sent.

    Raises:
        CatalogAgentError: ``model-not-found``, ``agent-invalid``.
    """
    sent = patch.model_fields_set
    changes: Dict[str, Any] = {}
    for field in ("name", "provider", "model_name"):
        if field in sent and getattr(patch, field) is not None:
            changes[field] = normalize_name(getattr(patch, field), field=field)
    for field in ("model_version", "data_handling"):
        if field in sent:
            changes[field] = optional_text(getattr(patch, field))
    if "hosting" in sent and patch.hosting is not None:
        changes["hosting"] = check_choice(patch.hosting, MODEL_HOSTINGS, "hosting")
    if "deprecated_at" in sent:
        changes["deprecated_at"] = patch.deprecated_at
    row = _model_row(tenant_id, slug)
    if changes:
        assignments = ", ".join(f"{field} = %s" for field in changes)

        def work(cursor: Any) -> bool:
            cursor.execute(
                f"UPDATE apiome.catalog_models SET {assignments}, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL",
                (*changes.values(), row["id"], tenant_id),
            )
            _audit(
                cursor,
                tenant_id,
                actor,
                "catalog.model.update",
                f"model:{slug}",
                {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in changes.items()},
            )
            return True

        db._guarded_tx(work)
    return get_model(tenant_id, slug)


def delete_model(tenant_id: str, slug: str, *, actor: ConsumerActor) -> None:
    """Soft-delete a model; agents that ran on it keep running, with no model shown.

    Raises:
        CatalogAgentError: ``model-not-found``.
    """
    row = _model_row(tenant_id, slug)

    def work(cursor: Any) -> bool:
        cursor.execute(
            "UPDATE apiome.catalog_models SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE id = %s::uuid AND tenant_id = %s::uuid",
            (row["id"], tenant_id),
        )
        _audit(cursor, tenant_id, actor, "catalog.model.delete", f"model:{slug}", {"model_id": row["id"]})
        return True

    db._guarded_tx(work)


def _model_id(tenant_id: str, slug: Optional[str]) -> Optional[str]:
    """The id of a live model named by slug, or ``None`` for no model."""
    if slug is None or not slug.strip():
        return None
    return str(_model_row(tenant_id, slug.strip().lower())["id"])


# ---------------------------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------------------------


def _agent_row(tenant_id: str, slug: str) -> Dict[str, Any]:
    """One live agent row with model and owner, by slug (or id, as a team page links it), else ``agent-not-found``."""
    rows = db.execute_query(
        f"""
        SELECT {_AGENT_COLUMNS}, own.entity_owner
        FROM apiome.catalog_agents a
        {_AGENT_MODEL_JOIN}
        {owner_envelope_join(("agent",), "a.id", "a.tenant_id")}
        WHERE a.tenant_id = %s::uuid AND a.deleted_at IS NULL AND (a.slug = %s OR a.id::text = %s)
        ORDER BY (a.slug = %s) DESC
        LIMIT 1
        """,
        (tenant_id, slug, slug, slug),
    )
    if not rows:
        raise CatalogAgentError(CODE_AGENT_NOT_FOUND, f"agent '{slug}' not found")
    return dict(rows[0])


def _agent_out(
    row: Dict[str, Any], keys: Sequence[AgentKeyRef] = (), consumers: Sequence[AgentConsumerRef] = ()
) -> AgentOut:
    """Build an :class:`AgentOut` from an agent row."""
    return AgentOut(
        id=str(row["id"]),
        slug=row["slug"],
        name=row["name"],
        description=row.get("description"),
        runtime=row.get("runtime"),
        status=row["status"],
        model=model_ref(row),
        owner=owner_ref_from_value(row.get("entity_owner")),
        keys=list(keys),
        consumers=list(consumers),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def agent_keys(agent_id: str) -> List[AgentKeyRef]:
    """The agent keys an agent uses — prefix and status only, never the secret or its hash."""
    rows = db.execute_query(_AGENT_KEYS_SQL, (agent_id,))
    return [
        AgentKeyRef(
            id=row["id"],
            name=row["name"],
            key_prefix=row["key_prefix"],
            status=key_status(row),
            toolset_id=row.get("toolset_id"),
            project_id=row.get("project_id"),
            project_name=row.get("project_name"),
            version_label=row.get("version_label"),
            enabled_tools=int(row.get("enabled_tools") or 0),
            revoked_at=row.get("revoked_at"),
            last_used_at=row.get("last_used_at"),
        )
        for row in (dict(r) for r in rows or [])
    ]


def agent_consumers(agent_id: str) -> List[AgentConsumerRef]:
    """The consumer the agent is in each project, with its current contract's operation count."""
    rows = db.execute_query(
        """
        SELECT ac.consumer_id::text AS consumer_id, ac.project_id::text AS project_id, p.name AS project_name,
               COALESCE((SELECT cc.operation_count FROM apiome.consumer_contract cc
                          WHERE cc.consumer_id = ac.consumer_id AND cc.is_current), 0)::int AS operation_count
        FROM apiome.catalog_agent_consumers ac
        JOIN apiome.projects p ON p.id = ac.project_id
        WHERE ac.agent_id = %s::uuid
        ORDER BY lower(p.name), ac.project_id
        """,
        (agent_id,),
    )
    return [AgentConsumerRef(**dict(row)) for row in rows or []]


def list_agents(tenant_id: str) -> List[AgentOut]:
    """The tenant's live agents, by name, with model and owner (keys and consumers on the detail read)."""
    rows = db.execute_query(
        f"""
        SELECT {_AGENT_COLUMNS}, own.entity_owner
        FROM apiome.catalog_agents a
        {_AGENT_MODEL_JOIN}
        {owner_envelope_join(("agent",), "a.id", "a.tenant_id")}
        WHERE a.tenant_id = %s::uuid AND a.deleted_at IS NULL
        ORDER BY lower(a.name), a.id
        """,
        (tenant_id,),
    )
    return [_agent_out(dict(row)) for row in rows or []]


def get_agent(tenant_id: str, slug: str) -> AgentOut:
    """One live agent with its model, owner, keys and consumers.

    Raises:
        CatalogAgentError: ``agent-not-found``.
    """
    row = _agent_row(tenant_id, slug)
    return _agent_out(row, agent_keys(row["id"]), agent_consumers(row["id"]))


def _check_key(cursor: Any, tenant_id: str, key_id: str, agent_id: Optional[str]) -> None:
    """Refuse a key that is not a live agent key of the tenant, or that another agent uses."""
    if not is_uuid_string(key_id):
        raise CatalogAgentError(CODE_KEY_INVALID, f"'{key_id}' is not an agent key id")
    cursor.execute(
        """
        SELECT k.id, cak.agent_id::text AS agent_id
        FROM apiome.api_keys k
        LEFT JOIN apiome.catalog_agent_keys cak ON cak.api_key_id = k.id
        WHERE k.id = %s::uuid AND k.tenant_id = %s::uuid AND k.kind = 'agent' AND k.deleted_at IS NULL
        """,
        (key_id, tenant_id),
    )
    row = cursor.fetchone()
    if row is None:
        raise CatalogAgentError(CODE_KEY_INVALID, f"'{key_id}' is not a live agent key of this workspace")
    if row["agent_id"] and row["agent_id"] != agent_id:
        raise CatalogAgentError(CODE_KEY_TAKEN, "that agent key already belongs to another agent")


def create_agent(tenant_id: str, body: AgentInput, *, actor: ConsumerActor) -> AgentOut:
    """Register an agent with its keys, then derive its consumers; audited as ``catalog.agent.create``.

    Raises:
        CatalogAgentError: ``agent-invalid``, ``agent-slug-taken``, ``model-not-found``,
            ``agent-key-invalid``, ``agent-key-taken``.
    """
    name = normalize_name(body.name)
    slug = resolve_slug(body.slug, name)
    model_id = _model_id(tenant_id, body.model)
    key_ids = list(OrderedDict.fromkeys(k.strip() for k in body.key_ids if k.strip()))

    def work(cursor: Any) -> str:
        cursor.execute(
            """
            INSERT INTO apiome.catalog_agents (tenant_id, slug, name, description, runtime, model_id, created_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s::uuid, %s::uuid)
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                slug,
                name,
                optional_text(body.description),
                optional_text(body.runtime),
                model_id,
                _user_id(actor),
            ),
        )
        agent_id = cursor.fetchone()["id"]
        for key_id in key_ids:
            _check_key(cursor, tenant_id, key_id, agent_id)
            cursor.execute(
                "INSERT INTO apiome.catalog_agent_keys (agent_id, api_key_id, tenant_id) "
                "VALUES (%s::uuid, %s::uuid, %s::uuid)",
                (agent_id, key_id, tenant_id),
            )
        _audit(
            cursor,
            tenant_id,
            actor,
            "catalog.agent.create",
            f"agent:{slug}",
            {"agent_id": agent_id, "name": name, "model_id": model_id, "key_ids": key_ids},
        )
        return agent_id

    agent_id = _run(work, CODE_AGENT_SLUG_TAKEN, slug)
    sync_agent_consumers(tenant_id, agent_id, actor=actor)
    return get_agent(tenant_id, slug)


def update_agent(tenant_id: str, slug: str, patch: AgentPatch, *, actor: ConsumerActor) -> AgentOut:
    """Change an agent, audited as ``catalog.agent.update``; retiring it empties its contracts.

    Raises:
        CatalogAgentError: ``agent-not-found``, ``agent-invalid``, ``model-not-found``.
    """
    sent = patch.model_fields_set
    changes: Dict[str, Any] = {}
    if "name" in sent and patch.name is not None:
        changes["name"] = normalize_name(patch.name)
    for field in ("description", "runtime"):
        if field in sent:
            changes[field] = optional_text(getattr(patch, field))
    if "model" in sent:
        changes["model_id"] = _model_id(tenant_id, patch.model)
    if "status" in sent and patch.status is not None:
        changes["status"] = check_choice(patch.status, AGENT_STATUSES, "status")
    row = _agent_row(tenant_id, slug)
    if changes:
        assignments = ", ".join(f"{field} = %s" for field in changes)

        def work(cursor: Any) -> bool:
            cursor.execute(
                f"UPDATE apiome.catalog_agents SET {assignments}, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = %s::uuid AND tenant_id = %s::uuid AND deleted_at IS NULL",
                (*changes.values(), row["id"], tenant_id),
            )
            _audit(cursor, tenant_id, actor, "catalog.agent.update", f"agent:{slug}", changes)
            return True

        db._guarded_tx(work)
        if "status" in changes or "name" in changes:
            sync_agent_consumers(tenant_id, row["id"], actor=actor)
    return get_agent(tenant_id, slug)


def delete_agent(tenant_id: str, slug: str, *, actor: ConsumerActor) -> None:
    """Soft-delete an agent and empty its contracts (its ``consumes`` edges go stale).

    Raises:
        CatalogAgentError: ``agent-not-found``.
    """
    row = _agent_row(tenant_id, slug)

    def work(cursor: Any) -> bool:
        cursor.execute(
            "UPDATE apiome.catalog_agents SET deleted_at = CURRENT_TIMESTAMP "
            "WHERE id = %s::uuid AND tenant_id = %s::uuid",
            (row["id"], tenant_id),
        )
        _audit(cursor, tenant_id, actor, "catalog.agent.delete", f"agent:{slug}", {"agent_id": row["id"]})
        return True

    db._guarded_tx(work)
    sync_agent_consumers(tenant_id, row["id"], actor=actor)


def link_key(tenant_id: str, slug: str, key_id: str, *, actor: ConsumerActor) -> AgentOut:
    """Add an agent key to an agent and re-derive its consumers (idempotent).

    Raises:
        CatalogAgentError: ``agent-not-found``, ``agent-key-invalid``, ``agent-key-taken``.
    """
    row = _agent_row(tenant_id, slug)

    def work(cursor: Any) -> bool:
        _check_key(cursor, tenant_id, key_id, row["id"])
        cursor.execute(
            """
            INSERT INTO apiome.catalog_agent_keys (agent_id, api_key_id, tenant_id)
            VALUES (%s::uuid, %s::uuid, %s::uuid) ON CONFLICT DO NOTHING
            """,
            (row["id"], key_id, tenant_id),
        )
        _audit(cursor, tenant_id, actor, "catalog.agent.key.link", f"agent:{slug}", {"key_id": key_id})
        return True

    db._guarded_tx(work)
    sync_agent_consumers(tenant_id, row["id"], actor=actor)
    return get_agent(tenant_id, slug)


def unlink_key(tenant_id: str, slug: str, key_id: str, *, actor: ConsumerActor) -> AgentOut:
    """Remove an agent key from an agent and re-derive its consumers.

    Raises:
        CatalogAgentError: ``agent-not-found``, ``agent-key-not-linked``.
    """
    row = _agent_row(tenant_id, slug)
    if not is_uuid_string(key_id):
        raise CatalogAgentError(CODE_KEY_NOT_LINKED, "that key is not linked to this agent")

    def work(cursor: Any) -> Optional[bool]:
        cursor.execute(
            "DELETE FROM apiome.catalog_agent_keys "
            "WHERE agent_id = %s::uuid AND api_key_id = %s::uuid RETURNING api_key_id",
            (row["id"], key_id),
        )
        if cursor.fetchone() is None:
            return None
        _audit(cursor, tenant_id, actor, "catalog.agent.key.unlink", f"agent:{slug}", {"key_id": key_id})
        return True

    if db._guarded_tx(work) is None:
        raise CatalogAgentError(CODE_KEY_NOT_LINKED, "that key is not linked to this agent")
    sync_agent_consumers(tenant_id, row["id"], actor=actor)
    return get_agent(tenant_id, slug)


def agent_id_for_key(tenant_id: str, key_id: str) -> Optional[str]:
    """The agent that uses an agent key, or ``None`` (for the AGX-3.1 revoke hook)."""
    if not is_uuid_string(str(key_id or "")):
        return None
    rows = db.execute_query(
        "SELECT agent_id::text AS agent_id FROM apiome.catalog_agent_keys "
        "WHERE api_key_id = %s::uuid AND tenant_id = %s::uuid",
        (key_id, tenant_id),
    )
    return rows[0]["agent_id"] if rows else None


# ---------------------------------------------------------------------------------------------
# The agent as a consumer
# ---------------------------------------------------------------------------------------------


def _agent_identity(tenant_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
    """The agent's slug and name (deleted agents included: a delete still has to empty contracts)."""
    rows = db.execute_query(
        "SELECT id::text AS id, slug, name FROM apiome.catalog_agents WHERE id = %s::uuid AND tenant_id = %s::uuid",
        (agent_id, tenant_id),
    )
    return dict(rows[0]) if rows else None


def operations_by_project(tenant_id: str, agent_id: str) -> "OrderedDict[str, Dict[str, Any]]":
    """What the agent may call, per project: ``{project_id: {version_id, version_label, keys}}``.

    The version recorded is the newest toolset version the agent reaches in that project.
    """
    grouped: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    for row in db.execute_query(_AGENT_OPERATIONS_SQL, (agent_id, tenant_id)) or []:
        entry = grouped.setdefault(
            str(row["project_id"]),
            {"version_id": row["version_id"], "version_label": row.get("version_label"), "keys": []},
        )
        entry["keys"].append(row["operation_key"])
    return grouped


def _unresolved(keys: Sequence[str]) -> List[UnresolvedInteraction]:
    """The tools that are not HTTP operations, kept on the contract rather than dropped."""
    return [
        UnresolvedInteraction(
            reason="method-not-declared",
            message=f"Tool operation '{key}' is not an HTTP operation, so it has no OpenAPI pointer.",
        )
        for key in keys
    ]


def sync_agent_consumers(tenant_id: str, agent_id: str, *, actor: ConsumerActor) -> int:
    """Make the agent's consumer contracts match what its live keys may call.

    For each project the agent reaches: find or create its consumer (by the agent's slug), link it
    in ``catalog_agent_consumers``, and record a ``source = 'agent'`` contract revision with one
    operation per callable tool — unless the current contract already holds exactly those
    pointers. For each linked project it no longer reaches, record an empty revision. Recording a
    revision materializes the ``consumes`` edges (CDG-3.1), and edges no longer produced go stale.

    Args:
        tenant_id: The tenant.
        agent_id: The agent.
        actor: Who triggered the sync (recorded on each revision).

    Returns:
        The number of contract revisions recorded.
    """
    agent = _agent_identity(tenant_id, agent_id)
    if agent is None:
        return 0
    wanted = operations_by_project(tenant_id, agent_id)
    linked = {
        str(row["project_id"]): str(row["consumer_id"])
        for row in db.execute_query(
            "SELECT project_id::text AS project_id, consumer_id::text AS consumer_id "
            "FROM apiome.catalog_agent_consumers WHERE agent_id = %s::uuid",
            (agent_id,),
        )
        or []
    }
    recorded = 0
    for project_id, entry in wanted.items():
        consumer = consumer_contract_store.ensure_consumer(
            tenant_id,
            project_id,
            slug=agent["slug"],
            name=agent["name"],
            actor=actor,
            description="An agent registered in the catalog (CDG-5.2).",
            metadata={"agent_id": agent_id},
        )
        if linked.get(project_id) != consumer.id and not _link_consumer(tenant_id, agent_id, project_id, consumer.id):
            continue
        surface, unplaced = agent_surface(entry["keys"])
        if _record_if_changed(tenant_id, project_id, consumer, surface, unplaced, entry, actor):
            recorded += 1
    for project_id, consumer_id in linked.items():
        if project_id in wanted:
            continue
        try:
            consumer = consumer_contract_store.get_consumer(tenant_id, project_id, consumer_id)
        except ConsumerValidationError:
            continue  # the consumer was deleted; it consumes nothing already
        surface, _ = agent_surface(())
        if _record_if_changed(tenant_id, project_id, consumer, surface, [], {}, actor):
            recorded += 1
    return recorded


def _link_consumer(tenant_id: str, agent_id: str, project_id: str, consumer_id: str) -> bool:
    """Record that the agent is ``consumer_id`` in ``project_id``.

    Returns:
        ``False`` when that consumer already belongs to another agent (the project is skipped).
    """

    def work(cursor: Any) -> bool:
        cursor.execute(
            """
            INSERT INTO apiome.catalog_agent_consumers (agent_id, consumer_id, project_id, tenant_id)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid)
            ON CONFLICT (agent_id, project_id) DO UPDATE SET consumer_id = EXCLUDED.consumer_id
            """,
            (agent_id, consumer_id, project_id, tenant_id),
        )
        return True

    try:
        return bool(db._guarded_tx(work))
    except psycopg2.errors.UniqueViolation:
        logger.warning("consumer %s already belongs to another agent; skipping", consumer_id)
        return False


def _record_if_changed(
    tenant_id: str,
    project_id: str,
    consumer: Any,
    surface: Any,
    unplaced: Sequence[str],
    entry: Dict[str, Any],
    actor: ConsumerActor,
) -> bool:
    """Record the agent's contract revision unless the current one already holds these pointers."""
    current = db.get_current_consumer_contract(consumer.id, tenant_id)
    pointers = sorted(contract_pointers(surface))
    if current is not None and sorted(current.get("surface_pointers") or []) == pointers:
        return False
    if current is None and not pointers:
        return False
    consumer_contract_store.record_contract(
        tenant_id,
        project_id,
        consumer,
        surface,
        actor=actor,
        unresolved=_unresolved(unplaced),
        source=SOURCE_AGENT,
        version_id=entry.get("version_id"),
        version_label=entry.get("version_label"),
        note="Derived from the agent's keys and their toolsets (CDG-5.2).",
    )
    return True
