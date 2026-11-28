"""Persistence for Pact environments, deployments and releases — PFX-1.5 (#6918).

:mod:`app.pact_environment` says what these *are*; this module is the only place one is read or
written (apiome-db V435).

**Recording a deployment is one transaction.** :func:`record_deployment` locks the environment
row, so two deployments to one environment take turns, then:

1. returns the current deployment unchanged when this version is already deployed to that
   environment and application instance (the broker's ``find_or_create``);
2. otherwise marks the deployment it replaces — the pacticipant's current one in that environment
   and instance — undeployed, and inserts the new one.

The replaced row stays (``currently_deployed = false``, ``undeployed_at`` set): history is never
deleted, and V435's trigger refuses any other change to it.

**A release is recorded once per version and environment.** Recording it again starts supporting
it again, as the Pact Broker does.

**Everything starts from the caller's tenant.** Environments are looked up with ``tenant_id``,
pacticipants through :func:`app.pacticipant_store.get_pacticipant`, and every read of a deployment
or release filters on ``tenant_id``; nothing reaches another tenant's rows.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional, Sequence, Tuple

import psycopg2
from psycopg2.extras import Json

from .consumer_contract_store import ConsumerActor
from .pact_environment import (
    CODE_DEPLOYED_VERSION_NOT_FOUND,
    CODE_DEPLOYMENT_CONFLICT,
    CODE_ENVIRONMENT_NAME_TAKEN,
    CODE_ENVIRONMENT_NOT_FOUND,
    CODE_RELEASED_VERSION_NOT_FOUND,
    DeployedVersionRecord,
    EnvironmentInput,
    EnvironmentRecord,
    ReleasedVersionRecord,
    deployed_version_from_row,
    environment_from_row,
    released_version_from_row,
)
from .pact_publication import PactPublicationError
from .pacticipant import CODE_NOT_FOUND, PacticipantValidationError
from .pacticipant_store import get_pacticipant, get_version
from .revision_deprecation import is_uuid_string

__all__ = [
    "UNSPECIFIED",
    "create_environment",
    "delete_environment",
    "get_deployed_version",
    "get_environment",
    "get_released_version",
    "list_currently_deployed",
    "list_currently_supported",
    "list_deployments_of_version",
    "list_environments",
    "list_releases_of_version",
    "record_deployment",
    "record_release",
    "record_support_ended",
    "record_undeployment",
    "replace_environment",
]

#: "No application-instance filter" — distinct from ``None``, which means the unnamed instance.
UNSPECIFIED: Any = object()

_ENVIRONMENT_COLUMNS = """
    id::text AS id, name, display_name, production, contract_required, contacts, created_at, updated_at
"""

#: The environment's columns in a deployment or release read, prefixed ``environment_``.
_JOINED_ENVIRONMENT = """
    e.id::text AS environment_id, e.name AS environment_name, e.display_name AS environment_display_name,
    e.production AS environment_production, e.contract_required AS environment_contract_required,
    e.contacts AS environment_contacts, e.created_at AS environment_created_at,
    e.updated_at AS environment_updated_at
"""

_DEPLOYED_SELECT = f"""
    SELECT d.id::text AS id, d.application_instance, d.currently_deployed, d.undeployed_at, d.created_at,
           p.slug AS pacticipant_slug, p.name AS pacticipant_name, v.number AS version_number,
           {_JOINED_ENVIRONMENT}
    FROM apiome.deployed_version d
    JOIN apiome.pacticipant p ON p.id = d.pacticipant_id AND p.tenant_id = d.tenant_id AND p.deleted_at IS NULL
    -- PFX-1.11: a deleted version's deployments are hidden with it.
    JOIN apiome.pacticipant_version v
      ON v.id = d.version_id AND v.pacticipant_id = d.pacticipant_id AND v.deleted_at IS NULL
    JOIN apiome.pact_environment e ON e.id = d.environment_id AND e.tenant_id = d.tenant_id
"""

_RELEASED_SELECT = f"""
    SELECT r.id::text AS id, r.currently_supported, r.support_ended_at, r.created_at, r.updated_at,
           p.slug AS pacticipant_slug, p.name AS pacticipant_name, v.number AS version_number,
           {_JOINED_ENVIRONMENT}
    FROM apiome.released_version r
    JOIN apiome.pacticipant p ON p.id = r.pacticipant_id AND p.tenant_id = r.tenant_id AND p.deleted_at IS NULL
    JOIN apiome.pacticipant_version v
      ON v.id = r.version_id AND v.pacticipant_id = r.pacticipant_id AND v.deleted_at IS NULL
    JOIN apiome.pact_environment e ON e.id = r.environment_id AND e.tenant_id = r.tenant_id
"""

_NAME_KEY = "pact_environment_tenant_name_key"


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _name_taken(name: str) -> PactPublicationError:
    """The 409 for a name another environment of the workspace has."""
    return PactPublicationError(
        CODE_ENVIRONMENT_NAME_TAKEN,
        f"/name: this workspace already has an environment named '{name}'",
        pointer="/name",
    )


def _fetch_one(cursor: Any, query: str, params: Sequence[Any]) -> Optional[dict]:
    """Run ``query`` on an open cursor and return its first row, or ``None``."""
    cursor.execute(query, tuple(params))
    row = cursor.fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------------------------


def list_environments(db: Any, tenant_id: str, *, name: Optional[str] = None) -> List[EnvironmentRecord]:
    """Read the workspace's environments, by name.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        name: Only the environment with exactly this name (the broker's ``?name=``).

    Returns:
        The environments, ordered by name.
    """
    where, params = "tenant_id = %s::uuid", [tenant_id]
    if name is not None:
        where += " AND name = %s"
        params.append(name)
    rows = db.execute_query(
        f"SELECT {_ENVIRONMENT_COLUMNS} FROM apiome.pact_environment WHERE {where} ORDER BY name, id",
        tuple(params),
    )
    return [environment_from_row(dict(row)) for row in rows or []]


def get_environment(db: Any, tenant_id: str, environment_id: str) -> EnvironmentRecord:
    """Read one environment of the workspace by its id (the broker's ``uuid``).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment_id: The environment's id.

    Returns:
        The environment.

    Raises:
        PactPublicationError: ``pact-environment-not-found``.
    """
    ref = (environment_id or "").strip()
    rows = (
        db.execute_query(
            f"SELECT {_ENVIRONMENT_COLUMNS} FROM apiome.pact_environment WHERE tenant_id = %s::uuid AND id = %s::uuid",
            (tenant_id, ref),
        )
        if is_uuid_string(ref)
        else None
    )
    if not rows:
        raise PactPublicationError(CODE_ENVIRONMENT_NOT_FOUND, f"no environment '{ref}' in this workspace")
    return environment_from_row(dict(rows[0]))


def create_environment(
    db: Any,
    tenant_id: str,
    environment: EnvironmentInput,
    *,
    actor: ConsumerActor,
    created_at: Optional[datetime] = None,
) -> EnvironmentRecord:
    """Create an environment.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment: The checked body.
        actor: Who is creating it.
        created_at: When the source broker created it, for an import (PFX-6.7, #6959); ``None`` is now.

    Returns:
        The stored environment.

    Raises:
        PactPublicationError: ``pact-environment-name-taken`` when the name is in use.
    """
    user_id = _user_id(actor)

    def work(cursor: Any) -> EnvironmentRecord:
        row = _fetch_one(
            cursor,
            f"""
            INSERT INTO apiome.pact_environment
                (tenant_id, name, display_name, production, contract_required, contacts, created_by, updated_by,
                 created_at, updated_at)
            VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::uuid, %s::uuid,
                    COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), COALESCE(%s::timestamptz, CURRENT_TIMESTAMP))
            RETURNING {_ENVIRONMENT_COLUMNS}
            """,
            (
                tenant_id,
                environment.name,
                environment.display_name,
                environment.production,
                environment.contract_required,
                Json(environment.contacts),
                user_id,
                user_id,
                created_at,
                created_at,
            ),
        )
        assert row is not None
        return environment_from_row(row)

    try:
        return db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        if getattr(exc.diag, "constraint_name", None) == _NAME_KEY:
            raise _name_taken(environment.name) from exc
        raise


def replace_environment(
    db: Any, tenant_id: str, environment_id: str, environment: EnvironmentInput, *, actor: ConsumerActor
) -> EnvironmentRecord:
    """Replace an environment's fields (the broker's ``PUT``; renaming is allowed).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment_id: The environment's id.
        environment: The checked body.
        actor: Who is changing it.

    Returns:
        The stored environment.

    Raises:
        PactPublicationError: ``pact-environment-not-found``; ``pact-environment-name-taken`` when
            another environment has the new name.
    """
    current = get_environment(db, tenant_id, environment_id)

    def work(cursor: Any) -> EnvironmentRecord:
        row = _fetch_one(
            cursor,
            f"""
            UPDATE apiome.pact_environment
            SET name = %s, display_name = %s, production = %s, contract_required = %s, contacts = %s,
                updated_by = %s::uuid, updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = %s::uuid AND id = %s::uuid
            RETURNING {_ENVIRONMENT_COLUMNS}
            """,
            (
                environment.name,
                environment.display_name,
                environment.production,
                environment.contract_required,
                Json(environment.contacts),
                _user_id(actor),
                tenant_id,
                current.id,
            ),
        )
        if row is None:
            raise PactPublicationError(CODE_ENVIRONMENT_NOT_FOUND, f"no environment '{current.id}' in this workspace")
        return environment_from_row(row)

    try:
        return db._guarded_tx(work)
    except psycopg2.errors.UniqueViolation as exc:
        if getattr(exc.diag, "constraint_name", None) == _NAME_KEY:
            raise _name_taken(environment.name) from exc
        raise


def delete_environment(db: Any, tenant_id: str, environment_id: str) -> EnvironmentRecord:
    """Delete an environment, and with it every deployment and release recorded to it.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment_id: The environment's id.

    Returns:
        The environment as it was.

    Raises:
        PactPublicationError: ``pact-environment-not-found``.
    """
    current = get_environment(db, tenant_id, environment_id)

    def work(cursor: Any) -> None:
        cursor.execute(
            "DELETE FROM apiome.pact_environment WHERE tenant_id = %s::uuid AND id = %s::uuid",
            (tenant_id, current.id),
        )

    db._guarded_tx(work)
    return current


# ---------------------------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------------------------


def _read_deployed(cursor_or_db: Any, tenant_id: str, deployed_id: str) -> Optional[DeployedVersionRecord]:
    """Read one deployment of the tenant, or ``None``."""
    query = _DEPLOYED_SELECT + " WHERE d.tenant_id = %s::uuid AND d.id = %s::uuid"
    if hasattr(cursor_or_db, "execute_query"):
        rows = cursor_or_db.execute_query(query, (tenant_id, deployed_id))
        row = dict(rows[0]) if rows else None
    else:
        row = _fetch_one(cursor_or_db, query, (tenant_id, deployed_id))
    return deployed_version_from_row(row) if row else None


def _lock_environment(cursor: Any, tenant_id: str, environment_id: str) -> None:
    """Lock the environment row, so deployments to it take turns.

    Raises:
        PactPublicationError: ``pact-environment-not-found`` when it was deleted meanwhile.
    """
    if (
        _fetch_one(
            cursor,
            "SELECT id FROM apiome.pact_environment WHERE tenant_id = %s::uuid AND id = %s::uuid FOR UPDATE",
            (tenant_id, environment_id),
        )
        is None
    ):
        raise PactPublicationError(CODE_ENVIRONMENT_NOT_FOUND, f"no environment '{environment_id}' in this workspace")


def record_deployment(
    db: Any,
    tenant_id: str,
    pacticipant_ref: str,
    version_number: str,
    environment_id: str,
    application_instance: Optional[str],
    *,
    actor: ConsumerActor,
    created_at: Optional[datetime] = None,
    replace_current: bool = True,
    recorded_verdict: Optional[str] = None,
) -> Tuple[DeployedVersionRecord, bool]:
    """Record that a version is now deployed to an environment (``pact-broker record-deployment``).

    The pacticipant's previous deployment to the same environment and application instance is
    marked undeployed in the same transaction; deployments to other instances are untouched.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant_ref: The pacticipant's handle, id or name.
        version_number: The deployed version, which must have been recorded.
        environment_id: The environment's id.
        application_instance: The instance deployed to; ``None`` for the unnamed one.
        actor: Who is recording it.
        created_at: When the source broker recorded it, for an import (PFX-6.7, #6959); ``None`` is now.
        replace_current: Whether a different version currently deployed there is marked undeployed.
            An import passes ``False``: Apiome's own newer record is kept and the import refused.
        recorded_verdict: can-i-deploy's answer for the version and environment just before it was
            recorded (``deployable``, ``not-deployable``, ``unknown``; V455), or ``None`` when not
            known (an import). Kept for the history's "verified at the time".

    Returns:
        The deployment, and whether this call created it (``False``: that version was already the
        current deployment there, and it is returned unchanged).

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``, ``pacticipant-version-not-found``.
        PactPublicationError: ``pact-environment-not-found``; ``pact-deployment-conflict`` when
            ``replace_current`` is false and another version is deployed there.
    """
    pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
    version = get_version(db, pacticipant, version_number)
    environment = get_environment(db, tenant_id, environment_id)

    def work(cursor: Any) -> Tuple[DeployedVersionRecord, bool]:
        _lock_environment(cursor, tenant_id, environment.id)
        current = _fetch_one(
            cursor,
            """
            SELECT id::text AS id, version_id::text AS version_id FROM apiome.deployed_version
            WHERE environment_id = %s::uuid AND pacticipant_id = %s::uuid
              AND COALESCE(application_instance, '') = COALESCE(%s, '') AND currently_deployed
            """,
            (environment.id, pacticipant.id, application_instance),
        )
        if current is not None and current["version_id"] == version.id:
            record = _read_deployed(cursor, tenant_id, current["id"])
            assert record is not None
            return record, False
        if current is not None and not replace_current:
            raise PactPublicationError(
                CODE_DEPLOYMENT_CONFLICT,
                f"another version of {pacticipant.name} is already recorded as deployed to "
                f"{environment.name}{' (' + application_instance + ')' if application_instance else ''}",
            )
        if current is not None:
            cursor.execute(
                "UPDATE apiome.deployed_version SET currently_deployed = FALSE, undeployed_at = CURRENT_TIMESTAMP,"
                " ended_reason = 'replaced', ended_actor_label = %s WHERE id = %s::uuid",
                (actor.label, current["id"]),
            )
        inserted = _fetch_one(
            cursor,
            """
            INSERT INTO apiome.deployed_version
                (tenant_id, pacticipant_id, version_id, environment_id, application_instance, created_by, actor_label,
                 created_at, recorded_verdict, replaced_id)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s::uuid, %s,
                    COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), %s, %s::uuid)
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                pacticipant.id,
                version.id,
                environment.id,
                application_instance,
                _user_id(actor),
                actor.label,
                created_at,
                recorded_verdict,
                current["id"] if current is not None else None,
            ),
        )
        assert inserted is not None
        record = _read_deployed(cursor, tenant_id, inserted["id"])
        assert record is not None
        return record, True

    return db._guarded_tx(work)


def get_deployed_version(db: Any, tenant_id: str, deployed_id: str) -> DeployedVersionRecord:
    """Read one deployment by its id.

    Raises:
        PactPublicationError: ``pact-deployed-version-not-found``.
    """
    ref = (deployed_id or "").strip()
    record = _read_deployed(db, tenant_id, ref) if is_uuid_string(ref) else None
    if record is None:
        raise PactPublicationError(CODE_DEPLOYED_VERSION_NOT_FOUND, f"no deployed version '{ref}' in this workspace")
    return record


def record_undeployment(
    db: Any, tenant_id: str, deployed_id: str, *, actor: Optional[ConsumerActor] = None
) -> DeployedVersionRecord:
    """Mark a deployment undeployed (``pact-broker record-undeployment``). Idempotent.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        deployed_id: The deployment's id.
        actor: Who is recording it (the history's "by whom"; V455), or ``None`` when not known.

    Returns:
        The deployment, no longer currently deployed.

    Raises:
        PactPublicationError: ``pact-deployed-version-not-found``.
    """
    current = get_deployed_version(db, tenant_id, deployed_id)
    if not current.currently_deployed:
        return current

    def work(cursor: Any) -> DeployedVersionRecord:
        cursor.execute(
            "UPDATE apiome.deployed_version SET currently_deployed = FALSE, undeployed_at = CURRENT_TIMESTAMP,"
            " ended_reason = 'undeployed', ended_actor_label = %s"
            " WHERE tenant_id = %s::uuid AND id = %s::uuid AND currently_deployed",
            (actor.label if actor else None, tenant_id, current.id),
        )
        record = _read_deployed(cursor, tenant_id, current.id)
        assert record is not None
        return record

    return db._guarded_tx(work)


def _pacticipant_id_or_none(db: Any, tenant_id: str, pacticipant_ref: Optional[str]) -> Optional[str]:
    """The id of a pacticipant filter; ``""`` when it names nothing (so the read matches nothing)."""
    if pacticipant_ref is None:
        return None
    try:
        return get_pacticipant(db, tenant_id, pacticipant_ref).id
    except PacticipantValidationError as exc:
        if exc.code == CODE_NOT_FOUND:
            return ""
        raise


def list_currently_deployed(
    db: Any,
    tenant_id: str,
    environment_id: str,
    *,
    pacticipant_ref: Optional[str] = None,
    application_instance: Any = UNSPECIFIED,
) -> Tuple[EnvironmentRecord, List[DeployedVersionRecord]]:
    """Read what is currently deployed to an environment, newest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment_id: The environment's id.
        pacticipant_ref: Only this pacticipant (handle, id or name); an unknown one matches nothing.
        application_instance: Only this instance (``None``: the unnamed one); :data:`UNSPECIFIED`
            for every instance.

    Returns:
        The environment and its current deployments.

    Raises:
        PactPublicationError: ``pact-environment-not-found``.
    """
    environment = get_environment(db, tenant_id, environment_id)
    pacticipant_id = _pacticipant_id_or_none(db, tenant_id, pacticipant_ref)
    if pacticipant_id == "":
        return environment, []
    where = " WHERE d.tenant_id = %s::uuid AND d.environment_id = %s::uuid AND d.currently_deployed"
    params: List[Any] = [tenant_id, environment.id]
    if pacticipant_id is not None:
        where += " AND d.pacticipant_id = %s::uuid"
        params.append(pacticipant_id)
    if application_instance is not UNSPECIFIED:
        where += " AND COALESCE(d.application_instance, '') = COALESCE(%s, '')"
        params.append(application_instance)
    rows = db.execute_query(_DEPLOYED_SELECT + where + " ORDER BY d.seq DESC", tuple(params))
    return environment, [deployed_version_from_row(dict(row)) for row in rows or []]


def list_deployments_of_version(
    db: Any, tenant_id: str, pacticipant_ref: str, version_number: str, environment_id: str
) -> List[DeployedVersionRecord]:
    """Read every deployment of one version to one environment, current or not, newest first.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``, ``pacticipant-version-not-found``.
        PactPublicationError: ``pact-environment-not-found``.
    """
    pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
    version = get_version(db, pacticipant, version_number)
    environment = get_environment(db, tenant_id, environment_id)
    rows = db.execute_query(
        _DEPLOYED_SELECT + " WHERE d.tenant_id = %s::uuid AND d.version_id = %s::uuid AND d.environment_id = %s::uuid"
        " ORDER BY d.seq DESC",
        (tenant_id, version.id, environment.id),
    )
    return [deployed_version_from_row(dict(row)) for row in rows or []]


# ---------------------------------------------------------------------------------------------
# Releases
# ---------------------------------------------------------------------------------------------


def _read_released(cursor_or_db: Any, tenant_id: str, released_id: str) -> Optional[ReleasedVersionRecord]:
    """Read one release of the tenant, or ``None``."""
    query = _RELEASED_SELECT + " WHERE r.tenant_id = %s::uuid AND r.id = %s::uuid"
    if hasattr(cursor_or_db, "execute_query"):
        rows = cursor_or_db.execute_query(query, (tenant_id, released_id))
        row = dict(rows[0]) if rows else None
    else:
        row = _fetch_one(cursor_or_db, query, (tenant_id, released_id))
    return released_version_from_row(row) if row else None


def record_release(
    db: Any,
    tenant_id: str,
    pacticipant_ref: str,
    version_number: str,
    environment_id: str,
    *,
    actor: ConsumerActor,
    created_at: Optional[datetime] = None,
    recorded_verdict: Optional[str] = None,
) -> Tuple[ReleasedVersionRecord, bool]:
    """Record that a version is released to an environment (``pact-broker record-release``).

    Other releases stay supported: releasing 2.0 does not end support for 1.0. Recording a
    release again starts supporting it again.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant_ref: The pacticipant's handle, id or name.
        version_number: The released version, which must have been recorded.
        environment_id: The environment's id.
        actor: Who is recording it.
        created_at: When the source broker recorded it, for an import (PFX-6.7, #6959); ``None`` is
            now. Only a new release takes it.
        recorded_verdict: can-i-deploy's answer just before it was recorded (V455), or ``None`` when
            not known. Recording the release again stores the new answer.

    Returns:
        The release, and whether this call created it.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``, ``pacticipant-version-not-found``.
        PactPublicationError: ``pact-environment-not-found``.
    """
    pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
    version = get_version(db, pacticipant, version_number)
    environment = get_environment(db, tenant_id, environment_id)

    def work(cursor: Any) -> Tuple[ReleasedVersionRecord, bool]:
        row = _fetch_one(
            cursor,
            """
            INSERT INTO apiome.released_version
                (tenant_id, pacticipant_id, version_id, environment_id, created_by, actor_label,
                 created_at, updated_at, recorded_verdict)
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s,
                    COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), %s)
            ON CONFLICT (version_id, environment_id) DO UPDATE
                SET currently_supported = TRUE, support_ended_at = NULL, ended_actor_label = NULL,
                    recorded_verdict = COALESCE(EXCLUDED.recorded_verdict, released_version.recorded_verdict),
                    updated_at = CASE WHEN released_version.currently_supported
                                      THEN released_version.updated_at ELSE CURRENT_TIMESTAMP END
            RETURNING id::text AS id, (xmax = 0) AS created
            """,
            (
                tenant_id,
                pacticipant.id,
                version.id,
                environment.id,
                _user_id(actor),
                actor.label,
                created_at,
                created_at,
                recorded_verdict,
            ),
        )
        assert row is not None
        record = _read_released(cursor, tenant_id, row["id"])
        assert record is not None
        return record, bool(row["created"])

    return db._guarded_tx(work)


def get_released_version(db: Any, tenant_id: str, released_id: str) -> ReleasedVersionRecord:
    """Read one release by its id.

    Raises:
        PactPublicationError: ``pact-released-version-not-found``.
    """
    ref = (released_id or "").strip()
    record = _read_released(db, tenant_id, ref) if is_uuid_string(ref) else None
    if record is None:
        raise PactPublicationError(CODE_RELEASED_VERSION_NOT_FOUND, f"no released version '{ref}' in this workspace")
    return record


def record_support_ended(
    db: Any, tenant_id: str, released_id: str, *, actor: Optional[ConsumerActor] = None
) -> ReleasedVersionRecord:
    """Mark a release no longer supported (``pact-broker record-support-ended``). Idempotent.

    can-i-deploy reads only the currently supported releases, so from now on this version's pacts
    no longer hold its counterparts back.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        released_id: The release's id.
        actor: Who is recording it (the history's "by whom"; V455), or ``None`` when not known.

    Returns:
        The release, no longer supported.

    Raises:
        PactPublicationError: ``pact-released-version-not-found``.
    """
    current = get_released_version(db, tenant_id, released_id)
    if not current.currently_supported:
        return current

    def work(cursor: Any) -> ReleasedVersionRecord:
        cursor.execute(
            "UPDATE apiome.released_version SET currently_supported = FALSE, support_ended_at = CURRENT_TIMESTAMP,"
            " updated_at = CURRENT_TIMESTAMP, ended_actor_label = %s"
            " WHERE tenant_id = %s::uuid AND id = %s::uuid AND currently_supported",
            (actor.label if actor else None, tenant_id, current.id),
        )
        record = _read_released(cursor, tenant_id, current.id)
        assert record is not None
        return record

    return db._guarded_tx(work)


def list_currently_supported(
    db: Any,
    tenant_id: str,
    environment_id: str,
    *,
    pacticipant_ref: Optional[str] = None,
    version_number: Optional[str] = None,
) -> Tuple[EnvironmentRecord, List[ReleasedVersionRecord]]:
    """Read the releases currently supported in an environment, newest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        environment_id: The environment's id.
        pacticipant_ref: Only this pacticipant; an unknown one matches nothing.
        version_number: Only this version number.

    Returns:
        The environment and its supported releases.

    Raises:
        PactPublicationError: ``pact-environment-not-found``.
    """
    environment = get_environment(db, tenant_id, environment_id)
    pacticipant_id = _pacticipant_id_or_none(db, tenant_id, pacticipant_ref)
    if pacticipant_id == "":
        return environment, []
    where = " WHERE r.tenant_id = %s::uuid AND r.environment_id = %s::uuid AND r.currently_supported"
    params: List[Any] = [tenant_id, environment.id]
    if pacticipant_id is not None:
        where += " AND r.pacticipant_id = %s::uuid"
        params.append(pacticipant_id)
    if version_number is not None:
        where += " AND v.number = %s"
        params.append(version_number)
    rows = db.execute_query(_RELEASED_SELECT + where + " ORDER BY r.seq DESC", tuple(params))
    return environment, [released_version_from_row(dict(row)) for row in rows or []]


def list_releases_of_version(
    db: Any, tenant_id: str, pacticipant_ref: str, version_number: str, environment_id: str
) -> List[ReleasedVersionRecord]:
    """Read the release of one version to one environment (none or one).

    Raises:
        PacticipantValidationError: ``pacticipant-not-found``, ``pacticipant-version-not-found``.
        PactPublicationError: ``pact-environment-not-found``.
    """
    pacticipant = get_pacticipant(db, tenant_id, pacticipant_ref)
    version = get_version(db, pacticipant, version_number)
    environment = get_environment(db, tenant_id, environment_id)
    rows = db.execute_query(
        _RELEASED_SELECT + " WHERE r.tenant_id = %s::uuid AND r.version_id = %s::uuid AND r.environment_id = %s::uuid",
        (tenant_id, version.id, environment.id),
    )
    return [released_version_from_row(dict(row)) for row in rows or []]
