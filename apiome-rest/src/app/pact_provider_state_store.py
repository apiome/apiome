"""Persistence for the provider-state registry — PFX-3.3 (#6933).

:mod:`app.pact_provider_state` says what a state *is*; this module is the only place one is read
or written (apiome-db V441: ``pact_provider_state`` and ``pact_provider_state_override``).

**Everything starts from the caller's tenant and the provider.** The provider is resolved with
:func:`app.pacticipant_store.get_pacticipant` (tenant-scoped) before this module is called, and
every statement filters on both ``tenant_id`` and ``provider_id``; an override's target is resolved
with :func:`app.verification_target_store.get_target`, which is tenant-scoped too, and V441's
composite references refuse anything that slipped past.

**A state and its overrides are written together.** Registering or replacing a state is one
transaction: the state row, then its overrides replaced wholesale, so a reader never sees a state
with half of its per-target setups.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

import psycopg2
from psycopg2.extras import Json

from .consumer_contract_store import ConsumerActor
from .pact_provider_state import (
    CODE_STATE_INVALID,
    CODE_STATE_NAME_TAKEN,
    CODE_STATE_NOT_FOUND,
    MAX_STATES_PER_PROVIDER,
    ProviderStateInput,
    ProviderStateRecord,
    StateOverrideRecord,
    StateParameter,
    StateSetup,
)
from .pact_publication import PactPublicationError
from .pacticipant import PacticipantRecord
from .revision_deprecation import is_uuid_string

__all__ = [
    "ResolvedOverride",
    "create_state",
    "delete_state",
    "get_state",
    "list_states",
    "replace_state",
]

_NAME_KEY = "pact_provider_state_name_key"

_COLUMNS = """
    id::text AS id, name, description, parameters, setup, created_at, updated_at
"""

_OVERRIDES = """
    SELECT o.state_id::text AS state_id, o.target_id::text AS target_id, t.slug AS target_slug, o.setup
    FROM apiome.pact_provider_state_override o
    JOIN apiome.verification_target t ON t.id = o.target_id AND t.tenant_id = o.tenant_id
    WHERE o.tenant_id = %s::uuid AND o.state_id = ANY(%s::uuid[])
    ORDER BY t.slug, o.target_id
"""


@dataclass(frozen=True)
class ResolvedOverride:
    """An override whose target reference has been resolved in the caller's tenant.

    Attributes:
        target_id: The verification target's id.
        target_slug: Its handle.
        setup: The checked setup.
    """

    target_id: str
    target_slug: str
    setup: StateSetup


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _not_found(state_id: str, provider: PacticipantRecord) -> PactPublicationError:
    """The 404 for a state this provider does not have."""
    return PactPublicationError(
        CODE_STATE_NOT_FOUND, f"the provider '{provider.slug}' has no provider state '{state_id}'"
    )


def _name_taken(name: str, provider: PacticipantRecord) -> PactPublicationError:
    """The 409 for a name another state of the provider has."""
    return PactPublicationError(
        CODE_STATE_NAME_TAKEN,
        f"/name: the provider '{provider.slug}' already has a state named '{name}'",
        pointer="/name",
    )


def _record(row: Dict[str, Any], provider: PacticipantRecord, overrides: List[Dict[str, Any]]) -> ProviderStateRecord:
    """Build a record from a state row and its override rows."""
    return ProviderStateRecord(
        id=row["id"],
        provider=provider.slug,
        name=row["name"],
        description=row.get("description"),
        parameters=[StateParameter.model_validate(item) for item in row.get("parameters") or []],
        setup=StateSetup.model_validate(row["setup"]),
        overrides=[
            StateOverrideRecord(
                target_id=item["target_id"],
                target_slug=item["target_slug"],
                setup=StateSetup.model_validate(item["setup"]),
            )
            for item in overrides
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _with_overrides(
    db: Any, tenant_id: str, provider: PacticipantRecord, rows: Sequence[Dict[str, Any]]
) -> List[ProviderStateRecord]:
    """Attach each state's overrides (one query for all of them)."""
    if not rows:
        return []
    by_state: Dict[str, List[Dict[str, Any]]] = {}
    for item in db.execute_query(_OVERRIDES, (tenant_id, [row["id"] for row in rows])) or []:
        by_state.setdefault(item["state_id"], []).append(dict(item))
    return [_record(dict(row), provider, by_state.get(row["id"], [])) for row in rows]


def list_states(db: Any, tenant_id: str, provider: PacticipantRecord) -> List[ProviderStateRecord]:
    """Read a provider's registered states, by name.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider (already resolved in this tenant).

    Returns:
        The states, each with its overrides; empty when none is registered.
    """
    rows = db.execute_query(
        f"""
        SELECT {_COLUMNS} FROM apiome.pact_provider_state
        WHERE tenant_id = %s::uuid AND provider_id = %s::uuid
        ORDER BY name, id
        """,
        (tenant_id, provider.id),
    )
    return _with_overrides(db, tenant_id, provider, [dict(row) for row in rows or []])


def get_state(db: Any, tenant_id: str, provider: PacticipantRecord, state_id: str) -> ProviderStateRecord:
    """Read one state of a provider by id.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider.
        state_id: The state's id.

    Returns:
        The state.

    Raises:
        PactPublicationError: ``provider-state-not-found``.
    """
    ref = (state_id or "").strip()
    rows = (
        db.execute_query(
            f"""
            SELECT {_COLUMNS} FROM apiome.pact_provider_state
            WHERE tenant_id = %s::uuid AND provider_id = %s::uuid AND id = %s::uuid
            """,
            (tenant_id, provider.id, ref),
        )
        if is_uuid_string(ref)
        else None
    )
    if not rows:
        raise _not_found(ref, provider)
    return _with_overrides(db, tenant_id, provider, [dict(rows[0])])[0]


def _write_overrides(cursor: Any, tenant_id: str, state_id: str, overrides: Sequence[ResolvedOverride]) -> None:
    """Replace a state's overrides with ``overrides``."""
    cursor.execute(
        "DELETE FROM apiome.pact_provider_state_override WHERE tenant_id = %s::uuid AND state_id = %s::uuid",
        (tenant_id, state_id),
    )
    for override in overrides:
        cursor.execute(
            """
            INSERT INTO apiome.pact_provider_state_override (tenant_id, state_id, target_id, setup)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s)
            """,
            (tenant_id, state_id, override.target_id, Json(override.setup.model_dump(mode="json"))),
        )


def _parameters(state: ProviderStateInput) -> Json:
    """The state's parameters as stored."""
    return Json([parameter.model_dump(mode="json") for parameter in state.parameters])


def create_state(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    state: ProviderStateInput,
    overrides: Sequence[ResolvedOverride],
    *,
    actor: ConsumerActor,
) -> ProviderStateRecord:
    """Register a state.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider.
        state: The checked body (:func:`app.pact_provider_state.validate_state`).
        overrides: Its overrides, targets resolved.
        actor: Who is registering it.

    Returns:
        The stored state.

    Raises:
        PactPublicationError: ``provider-state-name-taken``; ``provider-state-invalid`` when the
            provider already has :data:`~app.pact_provider_state.MAX_STATES_PER_PROVIDER` states.
    """
    user_id = _user_id(actor)

    def work(cursor: Any) -> str:
        cursor.execute(
            "SELECT count(*) AS n FROM apiome.pact_provider_state"
            " WHERE tenant_id = %s::uuid AND provider_id = %s::uuid",
            (tenant_id, provider.id),
        )
        count = cursor.fetchone()
        if count and int(dict(count)["n"]) >= MAX_STATES_PER_PROVIDER:
            raise PactPublicationError(
                CODE_STATE_INVALID,
                f"the provider '{provider.slug}' already has {MAX_STATES_PER_PROVIDER} states, "
                "the most one may register",
            )
        cursor.execute(
            """
            INSERT INTO apiome.pact_provider_state
                (tenant_id, provider_id, name, description, parameters, setup, created_by, updated_by)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s::uuid, %s::uuid)
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                provider.id,
                state.name,
                state.description,
                _parameters(state),
                Json(state.setup.model_dump(mode="json")),
                user_id,
                user_id,
            ),
        )
        state_id = dict(cursor.fetchone())["id"]
        _write_overrides(cursor, tenant_id, state_id, overrides)
        return state_id

    try:
        state_id = db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        if getattr(exc.diag, "constraint_name", None) == _NAME_KEY:
            raise _name_taken(state.name, provider) from exc
        raise
    return get_state(db, tenant_id, provider, state_id)


def replace_state(
    db: Any,
    tenant_id: str,
    provider: PacticipantRecord,
    state_id: str,
    state: ProviderStateInput,
    overrides: Sequence[ResolvedOverride],
    *,
    actor: ConsumerActor,
) -> ProviderStateRecord:
    """Replace a state's fields and overrides (renaming is allowed).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider.
        state_id: The state's id.
        state: The checked body.
        overrides: Its overrides, targets resolved; they replace the stored ones.
        actor: Who is changing it.

    Returns:
        The stored state.

    Raises:
        PactPublicationError: ``provider-state-not-found``; ``provider-state-name-taken``.
    """
    current = get_state(db, tenant_id, provider, state_id)
    user_id = _user_id(actor)

    def work(cursor: Any) -> Optional[str]:
        cursor.execute(
            """
            UPDATE apiome.pact_provider_state
            SET name = %s, description = %s, parameters = %s, setup = %s,
                updated_by = %s::uuid, updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s::uuid AND provider_id = %s::uuid AND id = %s::uuid
            RETURNING id::text AS id
            """,
            (
                state.name,
                state.description,
                _parameters(state),
                Json(state.setup.model_dump(mode="json")),
                user_id,
                tenant_id,
                provider.id,
                current.id,
            ),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        _write_overrides(cursor, tenant_id, current.id, overrides)
        return current.id

    try:
        updated = db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        if getattr(exc.diag, "constraint_name", None) == _NAME_KEY:
            raise _name_taken(state.name, provider) from exc
        raise
    if updated is None:
        raise _not_found(state_id, provider)
    return get_state(db, tenant_id, provider, updated)


def delete_state(db: Any, tenant_id: str, provider: PacticipantRecord, state_id: str) -> None:
    """Delete a state and its overrides.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider: The provider.
        state_id: The state's id.

    Raises:
        PactPublicationError: ``provider-state-not-found``.
    """
    current = get_state(db, tenant_id, provider, state_id)

    def work(cursor: Any) -> Optional[bool]:
        cursor.execute(
            """
            DELETE FROM apiome.pact_provider_state
            WHERE tenant_id = %s::uuid AND provider_id = %s::uuid AND id = %s::uuid
            RETURNING id
            """,
            (tenant_id, provider.id, current.id),
        )
        return True if cursor.fetchone() else None

    if db._guarded_tx(work) is None:
        raise _not_found(state_id, provider)
