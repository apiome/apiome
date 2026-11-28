"""Writing an imported Pact Broker / PactFlow workspace — PFX-6.7 (#6959).

:mod:`app.pact_migration` reads a batch; this module writes it (:func:`import_records`) or says what
writing it would do (:func:`check_records`).

**Each record is its own transaction.** A refused record changes nothing and does not stop the batch;
a record written stays written when a later one is refused, so a batch that failed half-way is simply
sent again.

**Importing again changes nothing.** Every write is keyed on the record's natural key: a pacticipant
on its handle, a version on its number, a pact on the consumer version that published it, a result on
its number on the pact version, an environment on its name, a deployment on what is currently
deployed there, a release on its version and environment, a webhook on its uuid. What exists is left
as it is — except for what a record adds to it (a label, a tag, a branch), which is ``updated``.

**The source's timestamps are kept.** Each write passes the record's ``created_at`` to the store
function that inserts the row (:func:`app.pacticipant_store.record_version_tx`,
:func:`app.pact_publication_store._store_pact`, …); rows that already exist keep their own.

**An import fires nothing.** It writes through the stores, not the routes, so no webhook, commit
status, notification or comparison runs for history that happened at the source.

Every lookup is scoped to the caller's tenant; another workspace's rows are never read or written.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import psycopg2

from .consumer_contract_store import ConsumerActor
from .pact_deployments import environment_by_name
from .pact_environment import CODE_DEPLOYMENT_CONFLICT, CODE_ENVIRONMENT_NAME_TAKEN, CODE_ENVIRONMENT_NOT_FOUND
from .pact_environment_store import create_environment, list_environments, record_deployment, record_release
from .pact_migration import (
    CODE_MIGRATION_CONFLICT,
    CODE_MIGRATION_INVALID,
    CODE_MIGRATION_REFERENCE,
    DeploymentImport,
    EnvironmentImport,
    ImportRecord,
    ImportRequest,
    MigrationOutcome,
    PacticipantImport,
    PactImport,
    RefusedRecord,
    ReleaseImport,
    VerificationImport,
    VersionImport,
    WebhookImport,
)
from .pact_publication import CODE_PACT_CONFLICT, PactPublicationError
from .pact_publication_store import _store_pact
from .pact_secret_store import create_placeholder_tx
from .pact_webhook import CODE_WEBHOOK_NOT_FOUND
from .pact_webhook_store import create_webhook, get_webhook
from .pacticipant import PacticipantRecord, PacticipantValidationError, slugify_pacticipant_name
from .pacticipant_store import _insert_tags, _read_version, ensure_pacticipant_tx, get_pacticipant, record_version_tx
from .revision_deprecation import is_uuid_string
from .verification_result import TRIGGER_PUBLISHED
from .verification_result_store import publish_verification_result

__all__ = ["check_records", "import_records"]

#: What one importer returns: the outcome (``created`` / ``updated`` / ``unchanged``) and a note.
_Done = Tuple[str, Optional[str]]


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _find_pacticipant(db: Any, tenant_id: str, name: str) -> Optional[PacticipantRecord]:
    """The tenant's live pacticipant with this name's handle, or ``None``."""
    try:
        return get_pacticipant(db, tenant_id, slugify_pacticipant_name(name))
    except PacticipantValidationError:
        return None


def _one(db: Any, query: str, params: Tuple[Any, ...]) -> Optional[Dict[str, Any]]:
    """The first row of a read, or ``None``."""
    rows = db.execute_query(query, params)
    return dict(rows[0]) if rows else None


def _publication(db: Any, consumer_id: str, provider_id: str, number: str) -> Optional[Dict[str, Any]]:
    """The pact a live consumer version published for a provider: its pact version id and sha."""
    return _one(
        db,
        """
        SELECT pv.id::text AS pact_version_id, pv.sha
        FROM apiome.pact_publication pub
        JOIN apiome.pacticipant_version v ON v.id = pub.consumer_version_id AND v.pacticipant_id = pub.consumer_id
        JOIN apiome.pact_version pv ON pv.id = pub.pact_version_id
        WHERE pub.consumer_id = %s::uuid AND pub.provider_id = %s::uuid AND v.number = %s AND v.deleted_at IS NULL
        """,
        (consumer_id, provider_id, number),
    )


def _stored_result(db: Any, pact_version_id: str, number: int) -> Optional[Dict[str, Any]]:
    """The pact version's result with this number: its provider version and verdict, or ``None``."""
    return _one(
        db,
        """
        SELECT v.number AS provider_version, r.success
        FROM apiome.verification_result r
        JOIN apiome.pacticipant_version v ON v.id = r.provider_version_id
        WHERE r.pact_version_id = %s::uuid AND r.number = %s
        """,
        (pact_version_id, number),
    )


def _result_exists(db: Any, pact_version_id: str, number: int) -> bool:
    """Whether the pact version already has a result with this number."""
    return _stored_result(db, pact_version_id, number) is not None


# ---------------------------------------------------------------------------------------------
# Importers, one per kind
# ---------------------------------------------------------------------------------------------


def _import_pacticipant(db: Any, tenant_id: str, record: PacticipantImport, actor: ConsumerActor) -> _Done:
    """Register a pacticipant, or add what the record has that the existing one lacks.

    An existing pacticipant keeps its name, repository and main branch; a missing repository or main
    branch is filled in and missing labels are added (``updated``).
    """
    user_id = _user_id(actor)

    def work(cursor: Any) -> _Done:
        cursor.execute(
            """
            INSERT INTO apiome.pacticipant
                (tenant_id, slug, name, repository_url, main_branch, created_by, updated_by, created_at, updated_at)
            VALUES (%s::uuid, %s, %s, %s, %s, %s::uuid, %s::uuid,
                    COALESCE(%s::timestamptz, CURRENT_TIMESTAMP), COALESCE(%s::timestamptz, CURRENT_TIMESTAMP))
            ON CONFLICT (tenant_id, slug) WHERE deleted_at IS NULL DO NOTHING
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                record.slug,
                record.name,
                record.repository_url,
                record.main_branch,
                user_id,
                user_id,
                record.created_at,
                record.created_at,
            ),
        )
        inserted = cursor.fetchone()
        note: Optional[str] = None
        changed = False
        if inserted is not None:
            pacticipant_id = inserted["id"]
        else:
            cursor.execute(
                "SELECT id::text AS id, name FROM apiome.pacticipant"
                " WHERE tenant_id = %s::uuid AND slug = %s AND deleted_at IS NULL",
                (tenant_id, record.slug),
            )
            existing = cursor.fetchone()
            pacticipant_id = existing["id"]
            if existing["name"] != record.name:
                note = f"merged into the existing pacticipant '{existing['name']}' (same handle '{record.slug}')"
            cursor.execute(
                """
                UPDATE apiome.pacticipant
                SET repository_url = COALESCE(repository_url, %s), main_branch = COALESCE(main_branch, %s),
                    updated_at = CURRENT_TIMESTAMP, updated_by = %s::uuid
                WHERE id = %s::uuid
                  AND ((repository_url IS NULL AND %s::text IS NOT NULL)
                       OR (main_branch IS NULL AND %s::text IS NOT NULL))
                """,
                (
                    record.repository_url,
                    record.main_branch,
                    user_id,
                    pacticipant_id,
                    record.repository_url,
                    record.main_branch,
                ),
            )
            changed = cursor.rowcount > 0
        if record.labels:
            cursor.execute(
                """
                INSERT INTO apiome.pacticipant_label (pacticipant_id, tenant_id, name, created_by, created_at)
                SELECT %s::uuid, %s::uuid, label, %s::uuid, COALESCE(%s::timestamptz, CURRENT_TIMESTAMP)
                FROM unnest(%s::text[]) AS label
                ON CONFLICT (pacticipant_id, name) DO NOTHING
                """,
                (pacticipant_id, tenant_id, user_id, record.created_at, list(record.labels)),
            )
            changed = changed or (inserted is None and cursor.rowcount > 0)
        if inserted is not None:
            return "created", note
        return ("updated" if changed else "unchanged"), note

    return db._guarded_tx(work)


def _import_version(db: Any, tenant_id: str, record: VersionImport, actor: ConsumerActor) -> _Done:
    """Record a version on each of its branches, with its tags, keeping the source's times.

    The pacticipant is registered when missing (as a publish does). A version that exists is never
    changed; branches and tags it lacks are added (``updated``).
    """

    def work(cursor: Any) -> _Done:
        pacticipant = ensure_pacticipant_tx(cursor, tenant_id, record.pacticipant, actor=actor)
        before = _read_version(cursor, pacticipant.id, record.number)
        recorded = None
        for branch in record.branches or (None,):
            recorded = record_version_tx(
                cursor,
                pacticipant,
                record.number,
                build_url=record.build_url,
                branch=branch,
                tags=[],
                actor=actor,
                created_at=record.created_at,
            )
        assert recorded is not None
        for tag in record.tags:
            _insert_tags(
                cursor, pacticipant.id, recorded.version.id, [tag.name], created_at=tag.created_at or record.created_at
            )
        after = _read_version(cursor, pacticipant.id, record.number) or {}
        if before is None:
            return "created", None
        same = sorted(before.get("branches") or []) == sorted(after.get("branches") or []) and sorted(
            before.get("tags") or []
        ) == sorted(after.get("tags") or [])
        return ("unchanged" if same else "updated"), None

    return db._guarded_tx(work)


def _import_pact(db: Any, tenant_id: str, record: PactImport, actor: ConsumerActor) -> _Done:
    """Store the pact a consumer version published, keeping the source's time.

    The consumer, the provider and the consumer version are registered when missing. A consumer
    version that already has a *different* pact for the provider is refused
    (``pact-content-conflict``): a published pact is never replaced.
    """

    def work(cursor: Any) -> _Done:
        consumer = ensure_pacticipant_tx(cursor, tenant_id, record.pact.consumer_name, actor=actor)
        provider = ensure_pacticipant_tx(cursor, tenant_id, record.pact.provider_name, actor=actor)
        version = record_version_tx(
            cursor,
            consumer,
            record.consumer_version,
            build_url=None,
            branch=None,
            tags=[],
            actor=actor,
            created_at=record.created_at,
        )
        stored = _store_pact(
            cursor,
            tenant_id,
            consumer,
            provider,
            version,
            record.pact,
            actor=actor,
            allow_modification=False,
            created_at=record.created_at,
        )
        return ("created" if stored.created else "unchanged"), None

    return db._guarded_tx(work)


def _import_verification(db: Any, tenant_id: str, record: VerificationImport, actor: ConsumerActor) -> _Done:
    """Store a verification result under the source's number and time.

    The pact it verifies must have been imported (``pact-migration-reference-missing`` otherwise).
    A result with that number on the pact version is left as it is (``unchanged``) when it records
    the same provider version and verdict, and refused (``pact-migration-conflict``) when it does not.
    """
    consumer = _find_pacticipant(db, tenant_id, record.consumer)
    provider = _find_pacticipant(db, tenant_id, record.provider)
    pact = _publication(db, consumer.id, provider.id, record.consumer_version) if consumer and provider else None
    if pact is None:
        raise PactPublicationError(
            CODE_MIGRATION_REFERENCE,
            f"no pact of {record.consumer} version {record.consumer_version} with {record.provider} in this "
            "workspace: import the pact before its verification results",
        )
    assert consumer is not None and provider is not None
    stored = _stored_result(db, pact["pact_version_id"], record.number)
    if stored is not None:
        if (stored["provider_version"], bool(stored["success"])) == (
            record.result.provider_version,
            record.result.success,
        ):
            return "unchanged", None
        # Two source pact versions whose content Apiome reads as the same pact share a pact version
        # here, so their result numbers can collide: say so rather than reporting it as imported.
        raise PactPublicationError(
            CODE_MIGRATION_CONFLICT,
            f"result {record.number} of this pact is already recorded with a different provider version or "
            f"verdict ({stored['provider_version']}, {'passed' if stored['success'] else 'failed'}); the source "
            "holds two pact versions Apiome stores as one",
        )
    try:
        publish_verification_result(
            db,
            tenant_id,
            provider.id,
            consumer.id,
            pact["sha"],
            record.result,
            actor=actor,
            trigger=TRIGGER_PUBLISHED,
            number=record.number,
            created_at=record.created_at,
        )
    except psycopg2.errors.UniqueViolation:
        # Another import of the same batch stored it meanwhile.
        return "unchanged", None
    return "created", None


def _import_environment(db: Any, tenant_id: str, record: EnvironmentImport, actor: ConsumerActor) -> _Done:
    """Create an environment; one of that name already in the workspace is left as it is."""
    if list_environments(db, tenant_id, name=record.environment.name):
        return "unchanged", None
    try:
        create_environment(db, tenant_id, record.environment, actor=actor, created_at=record.created_at)
    except PactPublicationError as exc:
        if exc.code == CODE_ENVIRONMENT_NAME_TAKEN:
            return "unchanged", None
        raise
    return "created", None


def _environment_id(db: Any, tenant_id: str, name: str) -> str:
    """The id of the environment named ``name``, or a ``pact-migration-reference-missing`` refusal."""
    try:
        return environment_by_name(db, tenant_id, name).id
    except PactPublicationError as exc:
        if exc.code != CODE_ENVIRONMENT_NOT_FOUND:
            raise
        raise PactPublicationError(
            CODE_MIGRATION_REFERENCE,
            f"this workspace has no environment named '{name}': import the environment before what is deployed to it",
        ) from exc


def _import_deployment(db: Any, tenant_id: str, record: DeploymentImport, actor: ConsumerActor) -> _Done:
    """Record that a version is currently deployed, keeping the source's time.

    The version must have been imported. When Apiome already records *another* version as deployed
    in that place, the import is refused (``pact-migration-conflict``) and Apiome's record kept.
    """
    environment_id = _environment_id(db, tenant_id, record.environment)
    try:
        _, created = record_deployment(
            db,
            tenant_id,
            slugify_pacticipant_name(record.pacticipant),
            record.version,
            environment_id,
            record.application_instance,
            actor=actor,
            created_at=record.created_at,
            replace_current=False,
        )
    except PactPublicationError as exc:
        if exc.code != CODE_DEPLOYMENT_CONFLICT:
            raise
        raise PactPublicationError(CODE_MIGRATION_CONFLICT, str(exc)) from exc
    return ("created" if created else "unchanged"), None


def _import_release(db: Any, tenant_id: str, record: ReleaseImport, actor: ConsumerActor) -> _Done:
    """Record that a version is currently released (supported), keeping the source's time."""
    environment_id = _environment_id(db, tenant_id, record.environment)
    _, created = record_release(
        db,
        tenant_id,
        slugify_pacticipant_name(record.pacticipant),
        record.version,
        environment_id,
        actor=actor,
        created_at=record.created_at,
    )
    return ("created" if created else "unchanged"), None


def _webhook_exists(db: Any, tenant_id: str, uuid: Optional[str]) -> bool:
    """Whether the workspace has a webhook with this uuid."""
    if not uuid:
        return False
    try:
        get_webhook(db, tenant_id, uuid)
    except PactPublicationError:
        return False
    return True


def _import_webhook(db: Any, tenant_id: str, record: WebhookImport, actor: ConsumerActor) -> _Done:
    """Create a webhook under the source's uuid, keeping the source's time.

    A webhook with that uuid in the workspace is left as it is. When another workspace uses the uuid
    the webhook is created under a new one (said in the note). Every ``${user.<name>}`` reference
    must name a workspace secret (``pact-webhook-invalid`` otherwise): create the secrets first.

    A value the source redacted is a reference to a placeholder secret (PFX-8.15): the placeholders
    are created without a value and the webhook turned off, waiting for them (said in the note);
    setting their values under Contracts → Settings → Secrets turns it on.
    """
    if _webhook_exists(db, tenant_id, record.uuid):
        return "unchanged", None
    waiting = bool(record.placeholders)
    if waiting:

        def make(cursor: Any) -> bool:
            for name, description in record.placeholders:
                create_placeholder_tx(cursor, tenant_id, name, description, actor)
            return True

        db._guarded_tx(make)
    note = (
        "turned off until its secrets have values: set "
        + ", ".join(name for name, _ in record.placeholders)
        + " under Contracts → Settings → Secrets"
        if waiting
        else None
    )
    try:
        create_webhook(
            db,
            tenant_id,
            record.webhook,
            actor=actor,
            webhook_id=record.uuid,
            created_at=record.created_at,
            awaiting_secrets=waiting,
        )
    except PactPublicationError as exc:
        if exc.code != CODE_WEBHOOK_NOT_FOUND or not record.uuid:
            raise
        created = create_webhook(
            db, tenant_id, record.webhook, actor=actor, created_at=record.created_at, awaiting_secrets=waiting
        )
        moved = f"another workspace uses the uuid {record.uuid}; created as {created.id}"
        return "created", f"{moved}; {note}" if note else moved
    return "created", note


_IMPORTERS: Dict[str, Callable[[Any, str, Any, ConsumerActor], _Done]] = {
    "pacticipant": _import_pacticipant,
    "version": _import_version,
    "pact": _import_pact,
    "verification": _import_verification,
    "environment": _import_environment,
    "deployment": _import_deployment,
    "release": _import_release,
    "webhook": _import_webhook,
}


# ---------------------------------------------------------------------------------------------
# Checks (a dry run): does the record's natural key exist?
# ---------------------------------------------------------------------------------------------


def _version_exists(db: Any, tenant_id: str, pacticipant: str, number: str) -> bool:
    """Whether the pacticipant (by name) has a live version with this number."""
    found = _find_pacticipant(db, tenant_id, pacticipant)
    return found is not None and _read_version(db, found.id, number) is not None


def _exists(db: Any, tenant_id: str, record: ImportRecord) -> bool:
    """Whether importing ``record`` would find it already there (its natural key exists)."""
    if isinstance(record, PacticipantImport):
        return _find_pacticipant(db, tenant_id, record.name) is not None
    if isinstance(record, VersionImport):
        return _version_exists(db, tenant_id, record.pacticipant, record.number)
    if isinstance(record, PactImport):
        consumer = _find_pacticipant(db, tenant_id, record.pact.consumer_name)
        provider = _find_pacticipant(db, tenant_id, record.pact.provider_name)
        return bool(consumer and provider and _publication(db, consumer.id, provider.id, record.consumer_version))
    if isinstance(record, VerificationImport):
        consumer = _find_pacticipant(db, tenant_id, record.consumer)
        provider = _find_pacticipant(db, tenant_id, record.provider)
        pact = _publication(db, consumer.id, provider.id, record.consumer_version) if consumer and provider else None
        return bool(pact and _result_exists(db, pact["pact_version_id"], record.number))
    if isinstance(record, EnvironmentImport):
        return bool(list_environments(db, tenant_id, name=record.environment.name))
    if isinstance(record, (DeploymentImport, ReleaseImport)):
        return _placement_exists(db, tenant_id, record)
    if isinstance(record, WebhookImport):
        return _webhook_exists(db, tenant_id, record.uuid)
    return False  # pragma: no cover - every kind is handled above


def _placement_exists(db: Any, tenant_id: str, record: Any) -> bool:
    """Whether the version is already currently deployed (or released) there."""
    pacticipant = _find_pacticipant(db, tenant_id, record.pacticipant)
    if pacticipant is None:
        return False
    if isinstance(record, DeploymentImport):
        query = """
            SELECT 1 AS found FROM apiome.deployed_version d
            JOIN apiome.pacticipant_version v ON v.id = d.version_id AND v.pacticipant_id = d.pacticipant_id
            JOIN apiome.pact_environment e ON e.id = d.environment_id AND e.tenant_id = d.tenant_id
            WHERE d.tenant_id = %s::uuid AND d.pacticipant_id = %s::uuid AND v.number = %s AND e.name = %s
              AND d.currently_deployed AND COALESCE(d.application_instance, '') = COALESCE(%s, '')
        """
        params: Tuple[Any, ...] = (
            tenant_id,
            pacticipant.id,
            record.version,
            record.environment,
            record.application_instance,
        )
    else:
        query = """
            SELECT 1 AS found FROM apiome.released_version r
            JOIN apiome.pacticipant_version v ON v.id = r.version_id AND v.pacticipant_id = r.pacticipant_id
            JOIN apiome.pact_environment e ON e.id = r.environment_id AND e.tenant_id = r.tenant_id
            WHERE r.tenant_id = %s::uuid AND r.pacticipant_id = %s::uuid AND v.number = %s AND e.name = %s
              AND r.currently_supported
        """
        params = (tenant_id, pacticipant.id, record.version, record.environment)
    return _one(db, query, params) is not None


# ---------------------------------------------------------------------------------------------
# The batch
# ---------------------------------------------------------------------------------------------


def _refused(record: Any, code: str, message: str) -> MigrationOutcome:
    """The outcome of a record that was refused."""
    return MigrationOutcome(
        index=record.index, kind=record.kind, key=record.key, outcome="refused", code=code, message=message
    )


def _run(record: Any, attempt: Callable[[], _Done]) -> MigrationOutcome:
    """Run one record's write or check, turning every refusal into a ``refused`` outcome.

    Args:
        record: The read (or refused) record.
        attempt: The write or check.

    Returns:
        The outcome: nothing is dropped — a database refusal is reported with its reason too.
    """
    if isinstance(record, RefusedRecord):
        return _refused(record, record.code, record.message)
    try:
        outcome, note = attempt()
    except (PacticipantValidationError, PactPublicationError) as exc:
        code = exc.code
        if code == CODE_PACT_CONFLICT:
            code = CODE_MIGRATION_CONFLICT
        return _refused(record, code, str(exc))
    except psycopg2.DataError:
        return _refused(
            record,
            CODE_MIGRATION_INVALID,
            "a value the database does not accept (a \\u0000 character in a string is the usual cause)",
        )
    except psycopg2.IntegrityError as exc:
        constraint = getattr(getattr(exc, "diag", None), "constraint_name", None) or "a constraint"
        return _refused(record, CODE_MIGRATION_INVALID, f"the database refused the record ({constraint})")
    return MigrationOutcome(index=record.index, kind=record.kind, key=record.key, outcome=outcome, note=note)


def import_records(db: Any, tenant_id: str, request: ImportRequest, *, actor: ConsumerActor) -> List[MigrationOutcome]:
    """Write a batch, record by record.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        request: The read batch.
        actor: Who is importing.

    Returns:
        One outcome per record, in batch order: ``created``, ``updated``, ``unchanged`` or ``refused``.
    """
    return [
        _run(record, lambda record=record: _IMPORTERS[record.kind](db, tenant_id, record, actor))
        for record in request.records
    ]


def check_records(db: Any, tenant_id: str, request: ImportRequest) -> List[MigrationOutcome]:
    """Say what writing a batch would do, writing nothing (a dry run).

    Each record is read as an import reads it and its natural key looked up: ``exists`` or
    ``would-create``; ``refused`` when it cannot be read. References between records (the pact a
    result verifies, the environment a deployment names) are not checked — an earlier batch of the
    same migration may create them.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        request: The read batch.

    Returns:
        One outcome per record, in batch order.
    """
    return [
        _run(record, lambda record=record: ("exists" if _exists(db, tenant_id, record) else "would-create", None))
        for record in request.records
    ]
