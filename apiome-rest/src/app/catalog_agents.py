"""Agent and model entities — pure rules and wire shapes — CDG-5.2 (#5980).

An **agent** is a named consumer that calls Apiome-hosted tools with agent keys (AGX-3.1); a
**model** is what it runs on. This module holds what needs no database: validation, the wire
models, and how an agent key's toolset operations become a consumer contract surface.

**No secret leaves this module.** :class:`AgentKeyRef` is the only key shape the agent routes
return: id, name, the lookup prefix, status, toolset and timestamps — never ``key_hash`` and never
the plaintext secret (which only the AGX-3.1 create response ever carries).

Reads and writes live in :mod:`app.catalog_agent_store`; routes in :mod:`app.catalog_agent_routes`.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .consumer_contract import ConsumerContractOperation, ConsumerContractSurface
from .consumer_surface import operation_pointer
from .entity_owners import EntityOwnerRef

__all__ = [
    "AGENT_STATUSES",
    "MODEL_HOSTINGS",
    "CatalogAgentError",
    "agent_surface",
    "is_deprecated",
    "normalize_name",
    "operation_parts",
    "resolve_slug",
]

#: Refusal codes.
CODE_AGENT_NOT_FOUND = "agent-not-found"
CODE_MODEL_NOT_FOUND = "model-not-found"
CODE_INVALID = "agent-invalid"
CODE_AGENT_SLUG_TAKEN = "agent-slug-taken"
CODE_MODEL_SLUG_TAKEN = "model-slug-taken"
CODE_KEY_INVALID = "agent-key-invalid"
CODE_KEY_TAKEN = "agent-key-taken"
CODE_KEY_NOT_LINKED = "agent-key-not-linked"

#: An agent is ``active`` or ``retired``; a retired agent consumes nothing.
AGENT_STATUSES = ("active", "retired")

#: Where a model runs.
MODEL_HOSTINGS = ("api", "self_hosted")

#: A slug is a handle, shaped like a team slug (V297 CHECK).
_SLUG = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")

#: The HTTP methods an operation key may start with (AGX-1.1 ``"GET /pets/{id}"``).
_HTTP_METHODS = frozenset({"get", "put", "post", "delete", "options", "head", "patch", "trace"})


class CatalogAgentError(ValueError):
    """A refusal with a stable machine code.

    Attributes:
        code: One of the module's ``CODE_*`` constants.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def resolve_slug(slug: Optional[str], name: str) -> str:
    """Return the handle an agent or model is stored under.

    Args:
        slug: The handle supplied, or ``None`` to derive one from ``name``.
        name: The display name.

    Returns:
        The lowercased handle.

    Raises:
        CatalogAgentError: ``agent-invalid`` when the handle (supplied or derived) has the wrong shape.
    """
    if slug is not None:
        candidate = slug.strip().lower()
    else:
        candidate = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")[:128].strip("-")
    if not candidate or not _SLUG.match(candidate):
        raise CatalogAgentError(
            CODE_INVALID,
            f"'{candidate}' is not a valid slug; use lowercase letters, digits and hyphens "
            "(1-128 characters, not starting or ending with a hyphen)",
        )
    return candidate


def normalize_name(name: Optional[str], *, field: str = "name") -> str:
    """Return a trimmed, non-blank value.

    Args:
        name: The value sent.
        field: Its field name, for the refusal.

    Raises:
        CatalogAgentError: ``agent-invalid`` for a blank value.
    """
    value = (name or "").strip()
    if not value:
        raise CatalogAgentError(CODE_INVALID, f"{field} is required")
    return value


def optional_text(value: Optional[str]) -> Optional[str]:
    """Trim free text, storing a blank as ``None``."""
    text = (value or "").strip()
    return text or None


def is_deprecated(deprecated_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    """Whether a model's deprecation date has arrived.

    Args:
        deprecated_at: The date, or ``None``.
        now: Clock override for tests.

    Returns:
        ``True`` once ``deprecated_at`` is in the past.
    """
    if deprecated_at is None:
        return False
    moment = deprecated_at if deprecated_at.tzinfo else deprecated_at.replace(tzinfo=timezone.utc)
    return moment <= (now or datetime.now(timezone.utc))


def operation_parts(operation_key: str) -> Optional[Tuple[str, str, str]]:
    """Split an AGX-1.1 operation key into ``(method, path, pointer)``.

    Args:
        operation_key: ``"GET /pets/{id}"``; a GraphQL key such as ``"Query.user"`` has no method.

    Returns:
        ``("get", "/pets/{id}", "/paths/~1pets~1{id}/get")``, or ``None`` when the key is not an
        HTTP operation (it cannot be placed on an OpenAPI surface).
    """
    method, _, path = (operation_key or "").strip().partition(" ")
    method = method.lower()
    path = path.strip()
    if method not in _HTTP_METHODS or not path.startswith("/"):
        return None
    return method, path, operation_pointer(path, method)


def agent_surface(operation_keys: Iterable[str]) -> Tuple[ConsumerContractSurface, List[str]]:
    """The contract surface an agent's enabled tools declare in one project.

    Args:
        operation_keys: The enabled, allowlisted tools' operation keys.

    Returns:
        ``(surface, unplaced)``: one operation per distinct HTTP operation, ordered by path then
        method (no fields — an agent declares operations), and the keys that are not HTTP
        operations, sorted.
    """
    operations: Dict[str, ConsumerContractOperation] = {}
    unplaced: List[str] = []
    for key in operation_keys:
        parts = operation_parts(key)
        if parts is None:
            unplaced.append(key)
            continue
        method, path, pointer = parts
        operations[pointer] = ConsumerContractOperation(method=method, path=path, pointer=pointer, fields=[])
    ordered = sorted(operations.values(), key=lambda op: (op.path, op.method))
    return ConsumerContractSurface(operations=ordered), sorted(set(unplaced))


# ---------------------------------------------------------------------------------------------
# Wire shapes
# ---------------------------------------------------------------------------------------------


class _CamelModel(BaseModel):
    """Wire base: snake_case fields, camelCase JSON."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ModelInput(_CamelModel):
    """Register a model."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    slug: Optional[str] = Field(default=None, max_length=128, description="Derived from `name` when omitted.")
    name: Optional[str] = Field(default=None, max_length=200, description="Display name; defaults to `modelName`.")
    provider: str = Field(min_length=1, max_length=120, description="Anthropic, OpenAI, Mistral, an internal team…")
    model_name: str = Field(min_length=1, max_length=200)
    model_version: Optional[str] = Field(default=None, max_length=120)
    hosting: str = Field(default="api", description="`api` (a provider's API) or `self_hosted`.")
    data_handling: Optional[str] = Field(
        default=None, max_length=4000, description="What the provider retains, where data is processed, opt-outs."
    )
    deprecated_at: Optional[datetime] = Field(default=None, description="When the model is (or was) deprecated.")


class ModelPatch(_CamelModel):
    """Change a model; an omitted field is kept, `deprecatedAt: null` clears the date."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    name: Optional[str] = Field(default=None, max_length=200)
    provider: Optional[str] = Field(default=None, max_length=120)
    model_name: Optional[str] = Field(default=None, max_length=200)
    model_version: Optional[str] = Field(default=None, max_length=120)
    hosting: Optional[str] = None
    data_handling: Optional[str] = Field(default=None, max_length=4000)
    deprecated_at: Optional[datetime] = None


class AgentRef(_CamelModel):
    """An agent, as a model lists the agents that run on it."""

    id: str
    slug: str
    name: str
    status: str


class ModelOut(_CamelModel):
    """A model."""

    id: str
    slug: str
    name: str
    provider: str
    model_name: str
    model_version: Optional[str] = None
    hosting: str
    data_handling: Optional[str] = None
    deprecated_at: Optional[datetime] = None
    deprecated: bool = Field(description="Whether `deprecatedAt` has arrived.")
    owner: Optional[EntityOwnerRef] = None
    agents: List[AgentRef] = Field(default_factory=list, description="Live agents that run on this model.")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AgentInput(_CamelModel):
    """Register an agent."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    slug: Optional[str] = Field(default=None, max_length=128, description="Derived from `name` when omitted.")
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    runtime: Optional[str] = Field(
        default=None, max_length=200, description="Framework or host (LangGraph, a Lambda, …)."
    )
    model: Optional[str] = Field(default=None, max_length=128, description="The slug of the model it runs on.")
    key_ids: List[str] = Field(default_factory=list, max_length=50, description="Agent keys (AGX-3.1) the agent uses.")


class AgentPatch(_CamelModel):
    """Change an agent; an omitted field is kept, `model: null` clears the model."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")

    name: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None, max_length=4000)
    runtime: Optional[str] = Field(default=None, max_length=200)
    model: Optional[str] = Field(default=None, max_length=128)
    status: Optional[str] = Field(default=None, description="`active` or `retired`; a retired agent consumes nothing.")


class AgentModelRef(_CamelModel):
    """The model an agent runs on, with its deprecation."""

    id: str
    slug: str
    name: str
    provider: str
    model_version: Optional[str] = None
    deprecated_at: Optional[datetime] = None
    deprecated: bool


class AgentKeyRef(_CamelModel):
    """An agent key the agent uses. Never carries the secret or its hash."""

    id: str
    name: str
    key_prefix: str = Field(description="The lookup prefix (`ak_1a2b3c4d5…`), never the secret.")
    status: str = Field(description="`active`, `disabled`, `expired` or `revoked`.")
    toolset_id: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    version_label: Optional[str] = None
    enabled_tools: int = Field(default=0, description="Enabled toolset tools this key may call.")
    revoked_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class AgentConsumerRef(_CamelModel):
    """The consumer the agent is in one project, and what it consumes there."""

    consumer_id: str
    project_id: str
    project_name: Optional[str] = None
    operation_count: int = Field(default=0, description="Operations in its current contract.")


class AgentOut(_CamelModel):
    """An agent."""

    id: str
    slug: str
    name: str
    description: Optional[str] = None
    runtime: Optional[str] = None
    status: str
    model: Optional[AgentModelRef] = None
    owner: Optional[EntityOwnerRef] = None
    keys: List[AgentKeyRef] = Field(default_factory=list)
    consumers: List[AgentConsumerRef] = Field(default_factory=list)
    usage_href: str = Field(default="/ade/dashboard/mcp/agents?tab=usage", description="The agent usage page.")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AgentList(_CamelModel):
    """The tenant's live agents."""

    agents: List[AgentOut]


class ModelList(_CamelModel):
    """The tenant's live models."""

    models: List[ModelOut]


def model_ref(row: Optional[Dict[str, Any]]) -> Optional[AgentModelRef]:
    """Build an agent's model reference from the ``m_*`` columns of an agent read, or ``None``."""
    if not row or not row.get("m_id"):
        return None
    return AgentModelRef(
        id=str(row["m_id"]),
        slug=row["m_slug"],
        name=row["m_name"],
        provider=row["m_provider"],
        model_version=row.get("m_model_version"),
        deprecated_at=row.get("m_deprecated_at"),
        deprecated=is_deprecated(row.get("m_deprecated_at")),
    )


def check_choice(value: Optional[str], allowed: Sequence[str], field: str) -> Optional[str]:
    """Return ``value`` when it is one of ``allowed`` (or ``None``), else refuse with ``agent-invalid``."""
    if value is None:
        return None
    if value not in allowed:
        raise CatalogAgentError(CODE_INVALID, f"{field} must be one of {', '.join(allowed)}; got {value!r}")
    return value
