"""Agent keys — AGX-3.1 (#4537).

An agent that calls a tenant's API through a managed MCP toolset holds an **agent key**: an
``apiome.api_keys`` row with ``kind = 'agent'`` (V269). Unlike a workspace key it is

* **bound to one toolset** (``toolset_id``, an AGX-1.2 ``agent_toolsets`` id);
* **restricted to an explicit tool allowlist** (``tool_allowlist``, MCP tool names in the AGX-1.1
  grammar). The tools the key may list and call are the toolset's enabled tools intersected with
  this list, worked out per request by the apiome-mcp agent-access middleware
  (``apiome_mcp.agent_access``). There is no wildcard: an empty list permits nothing;
* **expirable** (``expires_at``) and **revocable** (the existing soft delete). The middleware reads
  the key on every request, so revocation and expiry take effect on the agent's next request.

This module is that key's life in the REST API: how a request is validated, how the secret is
minted and hashed, and how the stored row is described. The routes are
:mod:`app.agent_key_routes`; the SQL is ``db.*agent_key*``.

**The secret is shown once.** :func:`create_agent_key` returns the plaintext beside the metadata
and nothing else ever does: the row holds a bcrypt hash (the same scheme as workspace keys) and
the usual 12-character lookup prefix.

**An agent key is not a REST credential.** ``db.validate_api_key`` accepts workspace keys only, and
an agent key carries exactly the ``agent:invoke`` scope, which no REST route allowlists
(:data:`app.auth.API_KEY_SCOPE_AGENT_INVOKE`).

**The toolset is not checked yet.** ``agent_toolsets`` is AGX-1.2 (#4530), still open when agent
keys shipped, so ``toolset_id`` is a well-formed UUID with no foreign key. AGX-1.2 adds the key
and a route-level existence check; until then the MCP middleware fails closed on a toolset it
cannot resolve.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Iterable, List, Literal, Mapping, Optional, Tuple
from uuid import UUID

import bcrypt
from pydantic import BaseModel, ConfigDict, Field

from .auth import API_KEY_SCOPE_AGENT_INVOKE
from .database import db
from .tool_projection import TOOL_NAME_PATTERN

__all__ = [
    "AGENT_KEY_KIND",
    "AGENT_KEY_SCHEMA_VERSION",
    "AGENT_KEY_SCOPE",
    "AGENT_KEY_SECRET_PREFIX",
    "CODE_AGENT_KEY_EXISTS",
    "CODE_AGENT_KEY_INVALID",
    "CODE_AGENT_KEY_NOT_FOUND",
    "CODE_AGENT_KEY_REVOKED",
    "TOOL_ALLOWLIST_MAX_ENTRIES",
    "AgentKeyAllowlistUpdate",
    "AgentKeyCreate",
    "AgentKeyCreated",
    "AgentKeyError",
    "AgentKeyOut",
    "AgentKeyStatus",
    "create_agent_key",
    "get_agent_key",
    "key_status",
    "list_agent_keys",
    "mint_agent_key_secret",
    "normalize_tool_allowlist",
    "revoke_agent_key",
    "update_agent_key_allowlist",
]

#: The addressable shape of an agent key's metadata projection.
AGENT_KEY_SCHEMA_VERSION = "agx.agent-key.v1"

#: ``api_keys.kind`` for agent keys (V269).
AGENT_KEY_KIND = "agent"

#: The one scope every agent key carries (V269 ``api_keys_kind_scopes_ck``).
AGENT_KEY_SCOPE = API_KEY_SCOPE_AGENT_INVOKE

#: Agent-key secrets start with this, so a leaked one is recognisable (workspace keys use ``sk_``).
AGENT_KEY_SECRET_PREFIX = "ak_"

#: Most tools one allowlist may name (V269 ``api_keys_agent_allowlist_ck``).
TOOL_ALLOWLIST_MAX_ENTRIES = 1024

#: Refusal codes (the routes map them to 422 / 409 / 404 / 409).
CODE_AGENT_KEY_INVALID = "agent-key-invalid"
CODE_AGENT_KEY_EXISTS = "agent-key-exists"
CODE_AGENT_KEY_NOT_FOUND = "agent-key-not-found"
CODE_AGENT_KEY_REVOKED = "agent-key-revoked"

#: Characters in the stored lookup prefix, matching workspace keys (``first 12 + '...'``).
_PREFIX_CHARS = 12

#: bcrypt cost, matching the Control Panel's workspace keys. The MCP middleware verifies the hash
#: on every agent request, so this is also a per-request latency cost.
_BCRYPT_ROUNDS = 10

#: Longest accepted name (``api_keys.name VARCHAR(255)``) and description.
_NAME_MAX_CHARS = 255
_DESCRIPTION_MAX_CHARS = 1_000

AgentKeyStatus = Literal["active", "disabled", "expired", "revoked"]


class AgentKeyError(ValueError):
    """An agent-key request was refused.

    Attributes:
        code: One of the ``CODE_*`` constants.
        errors: One message per problem, so a form can mark every bad field at once.
    """

    def __init__(self, code: str, *errors: str) -> None:
        super().__init__("; ".join(errors) or code)
        self.code = code
        self.errors: Tuple[str, ...] = tuple(errors)


class AgentKeyCreate(BaseModel):
    """Body of ``POST /v1/tenants/{t}/agent-keys``.

    Attributes:
        name: Human name, unique in the tenant (across workspace and agent keys, revoked included).
        description: Optional purpose note.
        toolset_id: The agent toolset the key is bound to.
        tool_allowlist: MCP tool names the key may list and call.
        expires_at: Optional expiry; must be in the future. A naive value is read as UTC.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = Field(min_length=1, max_length=_NAME_MAX_CHARS)
    description: Optional[str] = Field(default=None, max_length=_DESCRIPTION_MAX_CHARS)
    toolset_id: UUID = Field(alias="toolsetId")
    tool_allowlist: List[str] = Field(
        alias="toolAllowlist", max_length=TOOL_ALLOWLIST_MAX_ENTRIES
    )
    expires_at: Optional[datetime] = Field(default=None, alias="expiresAt")


class AgentKeyAllowlistUpdate(BaseModel):
    """Body of ``PUT /v1/tenants/{t}/agent-keys/{id}/allowlist``: the whole new list."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    tool_allowlist: List[str] = Field(
        alias="toolAllowlist", max_length=TOOL_ALLOWLIST_MAX_ENTRIES
    )


class AgentKeyOut(BaseModel):
    """An agent key, described. Never carries the secret or its hash.

    Attributes:
        schema_version: The projection's shape.
        id: The key id.
        kind: Always ``agent``.
        name: Human name.
        description: Purpose note, if any.
        key_prefix: The first 12 characters of the secret plus ``...``, for recognising it.
        toolset_id: The toolset the key is bound to.
        tool_allowlist: The tool names it may use, sorted.
        status: ``active``, ``disabled``, ``expired`` or ``revoked`` (see :func:`key_status`).
        enabled: The key's enabled flag.
        expires_at: When it stops working, if ever.
        revoked_at: When it was revoked, if it was.
        last_used_at: When it last authenticated, if ever.
        created_at: When it was created.
        updated_at: When its row last changed.
        created_by: The user who created it, if known.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: str = Field(
        default=AGENT_KEY_SCHEMA_VERSION, serialization_alias="schemaVersion"
    )
    id: str
    kind: Literal["agent"] = AGENT_KEY_KIND
    name: str
    description: Optional[str] = None
    key_prefix: str = Field(serialization_alias="keyPrefix")
    toolset_id: str = Field(serialization_alias="toolsetId")
    tool_allowlist: List[str] = Field(serialization_alias="toolAllowlist")
    status: AgentKeyStatus
    enabled: bool
    expires_at: Optional[datetime] = Field(default=None, serialization_alias="expiresAt")
    revoked_at: Optional[datetime] = Field(default=None, serialization_alias="revokedAt")
    last_used_at: Optional[datetime] = Field(default=None, serialization_alias="lastUsedAt")
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: Optional[datetime] = Field(default=None, serialization_alias="updatedAt")
    created_by: Optional[str] = Field(default=None, serialization_alias="createdBy")


class AgentKeyCreated(AgentKeyOut):
    """The create response: the key's metadata plus its plaintext secret, shown this once."""

    secret: str = Field(
        description="The agent key. Shown only in this response; store it now.",
    )


def _utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime (a naive value is read as UTC)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_tool_allowlist(raw: Iterable[Any]) -> List[str]:
    """Validate an allowlist and return it deduplicated and sorted.

    Each entry must be an MCP tool name in the AGX-1.1 grammar (``^[A-Za-z0-9_-]{1,64}$``), the
    only names the compiler emits. Sorting makes the stored list, and the audit rows that quote
    it, independent of the order a caller sent.

    Args:
        raw: The submitted entries.

    Returns:
        The distinct names, sorted.

    Raises:
        AgentKeyError: ``agent-key-invalid``, one message per bad entry, when an entry is not a
            tool name or the list is longer than :data:`TOOL_ALLOWLIST_MAX_ENTRIES`.
    """
    entries = list(raw)
    problems: List[str] = []
    names = set()
    for index, entry in enumerate(entries):
        if not isinstance(entry, str) or not TOOL_NAME_PATTERN.fullmatch(entry):
            problems.append(
                f"toolAllowlist[{index}]: {entry!r} is not an MCP tool name "
                f"({TOOL_NAME_PATTERN.pattern})"
            )
            continue
        names.add(entry)
    if len(entries) > TOOL_ALLOWLIST_MAX_ENTRIES:
        problems.append(
            f"toolAllowlist: at most {TOOL_ALLOWLIST_MAX_ENTRIES} entries, got {len(entries)}"
        )
    if problems:
        raise AgentKeyError(CODE_AGENT_KEY_INVALID, *problems)
    return sorted(names)


def mint_agent_key_secret() -> Tuple[str, str, str]:
    """Mint a new agent-key secret.

    Returns:
        ``(secret, key_prefix, key_hash)``: the plaintext (``ak_`` + 64 hex characters, returned
        to the caller once), its lookup prefix, and the bcrypt hash that is stored.
    """
    secret = AGENT_KEY_SECRET_PREFIX + secrets.token_hex(32)
    prefix = secret[:_PREFIX_CHARS] + "..."
    key_hash = bcrypt.hashpw(secret.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return secret, prefix, key_hash.decode("ascii")


def key_status(row: Mapping[str, Any], *, now: Optional[datetime] = None) -> AgentKeyStatus:
    """Work out whether a stored key would authenticate.

    Precedence matches the MCP middleware's refusal order: revoked, then disabled, then expired.

    Args:
        row: A ``db.*agent_key*`` row.
        now: The reference instant; defaults to the current UTC time.

    Returns:
        ``revoked`` when soft-deleted, ``disabled`` when its ``enabled`` flag is off, ``expired``
        when ``expires_at`` has passed, else ``active``.
    """
    if row.get("revoked_at") is not None:
        return "revoked"
    if not row.get("enabled", True):
        return "disabled"
    expires_at = row.get("expires_at")
    reference = _utc(now) if now is not None else datetime.now(timezone.utc)
    if isinstance(expires_at, datetime) and _utc(expires_at) <= reference:
        return "expired"
    return "active"


def _allowlist(raw: Any) -> List[str]:
    """Read a stored ``tool_allowlist`` (JSONB, already decoded by the driver) as a sorted list."""
    if isinstance(raw, list):
        return sorted({str(item) for item in raw if isinstance(item, str)})
    return []


def _out(row: Mapping[str, Any]) -> AgentKeyOut:
    """Project a stored row onto :class:`AgentKeyOut`."""
    return AgentKeyOut(
        id=str(row["id"]),
        name=str(row["name"]),
        description=row.get("description"),
        key_prefix=str(row["key_prefix"]),
        toolset_id=str(row["toolset_id"]),
        tool_allowlist=_allowlist(row.get("tool_allowlist")),
        status=key_status(row),
        enabled=bool(row.get("enabled", True)),
        expires_at=row.get("expires_at"),
        revoked_at=row.get("revoked_at"),
        last_used_at=row.get("last_used_at"),
        created_at=row["created_at"],
        updated_at=row.get("updated_at"),
        created_by=row.get("created_by"),
    )


def _clean_text(value: Optional[str]) -> Optional[str]:
    """Strip ``value``; blank becomes ``None``."""
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def create_agent_key(
    tenant_id: str,
    body: AgentKeyCreate,
    *,
    actor_id: Optional[str] = None,
    now: Optional[datetime] = None,
) -> AgentKeyCreated:
    """Validate, mint and store a new agent key.

    Args:
        tenant_id: The caller's tenant.
        body: The request.
        actor_id: The user creating it (recorded as ``created_by``).
        now: The reference instant for the expiry check; defaults to now.

    Returns:
        The stored key's metadata and its plaintext secret.

    Raises:
        AgentKeyError: ``agent-key-invalid`` (every problem listed) for a blank name, an allowlist
            entry that is not a tool name, or an expiry that is not in the future;
            ``agent-key-exists`` when the tenant already has a key with that name.
    """
    problems: List[str] = []
    name = _clean_text(body.name)
    if name is None:
        problems.append("name: must not be blank")
    try:
        allowlist = normalize_tool_allowlist(body.tool_allowlist)
    except AgentKeyError as exc:
        problems.extend(exc.errors)
        allowlist = []
    expires_at = _utc(body.expires_at) if body.expires_at is not None else None
    reference = _utc(now) if now is not None else datetime.now(timezone.utc)
    if expires_at is not None and expires_at <= reference:
        problems.append("expiresAt: must be in the future")
    if problems:
        raise AgentKeyError(CODE_AGENT_KEY_INVALID, *problems)

    secret, prefix, key_hash = mint_agent_key_secret()
    row = db.insert_agent_key(
        tenant_id=tenant_id,
        name=name,
        description=_clean_text(body.description),
        key_hash=key_hash,
        key_prefix=prefix,
        toolset_id=str(body.toolset_id),
        tool_allowlist=allowlist,
        expires_at=expires_at,
        actor_id=actor_id,
    )
    if row is None:
        raise AgentKeyError(
            CODE_AGENT_KEY_EXISTS, f"an API key named {name!r} already exists in this tenant"
        )
    return AgentKeyCreated(**_out(row).model_dump(), secret=secret)


def list_agent_keys(
    tenant_id: str,
    *,
    toolset_id: Optional[str] = None,
    include_revoked: bool = False,
) -> List[AgentKeyOut]:
    """Describe a tenant's agent keys, newest first.

    Args:
        tenant_id: The caller's tenant.
        toolset_id: When set, only keys bound to this toolset.
        include_revoked: When ``True``, revoked keys are included.

    Returns:
        The keys' metadata.
    """
    rows = db.list_agent_keys(
        tenant_id, toolset_id=toolset_id, include_revoked=include_revoked
    )
    return [_out(row) for row in rows]


def get_agent_key(tenant_id: str, key_id: str) -> AgentKeyOut:
    """Describe one agent key, revoked or not.

    Args:
        tenant_id: The caller's tenant.
        key_id: The key.

    Returns:
        Its metadata.

    Raises:
        AgentKeyError: ``agent-key-not-found`` when the tenant has no agent key with that id.
    """
    row = db.get_agent_key(tenant_id, key_id)
    if row is None:
        raise AgentKeyError(CODE_AGENT_KEY_NOT_FOUND, "no such agent key")
    return _out(row)


def update_agent_key_allowlist(
    tenant_id: str, key_id: str, body: AgentKeyAllowlistUpdate
) -> Tuple[List[str], AgentKeyOut]:
    """Replace an unrevoked agent key's allowlist.

    The MCP middleware reads the allowlist on every request, so the change applies to the agent's
    next request; there is nothing to restart.

    Args:
        tenant_id: The caller's tenant.
        key_id: The key.
        body: The new list.

    Returns:
        ``(previous allowlist, key after the update)``, so the caller can audit the change.

    Raises:
        AgentKeyError: ``agent-key-invalid`` for a bad entry; ``agent-key-not-found`` for an
            unknown id; ``agent-key-revoked`` when the key is revoked (a revoked key never
            authenticates again, so its allowlist is frozen as the audit left it).
    """
    allowlist = normalize_tool_allowlist(body.tool_allowlist)
    current = db.get_agent_key(tenant_id, key_id)
    if current is None:
        raise AgentKeyError(CODE_AGENT_KEY_NOT_FOUND, "no such agent key")
    if current.get("revoked_at") is not None:
        raise AgentKeyError(CODE_AGENT_KEY_REVOKED, "this agent key has been revoked")
    row = db.update_agent_key_allowlist(tenant_id, key_id, allowlist)
    if row is None:
        # Revoked between the read and the write.
        raise AgentKeyError(CODE_AGENT_KEY_REVOKED, "this agent key has been revoked")
    return _allowlist(current.get("tool_allowlist")), _out(row)


def revoke_agent_key(tenant_id: str, key_id: str) -> Tuple[AgentKeyOut, bool]:
    """Revoke an agent key. Idempotent.

    Args:
        tenant_id: The caller's tenant.
        key_id: The key.

    Returns:
        ``(key, revoked_now)``: the key's metadata, and whether this call revoked it (``False``
        when it was already revoked, so the caller audits a revocation once).

    Raises:
        AgentKeyError: ``agent-key-not-found`` when the tenant has no agent key with that id.
    """
    row = db.revoke_agent_key(tenant_id, key_id)
    if row is not None:
        return _out(row), True
    existing = db.get_agent_key(tenant_id, key_id)
    if existing is None:
        raise AgentKeyError(CODE_AGENT_KEY_NOT_FOUND, "no such agent key")
    return _out(existing), False
