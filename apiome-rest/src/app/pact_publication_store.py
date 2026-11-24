"""Persistence for published pacts — PFX-1.2 (#6915).

:mod:`app.pact_publication` says what a pact *is*; this module is the only place one is read or
written (apiome-db V433), so the rules of publication are applied once.

**A publish is one transaction.** :func:`publish_pacts` registers the pacticipants a request names
(the first publication to name an application registers it, as a Pact Broker does), records the
consumer version with its branch and tags through the registry's own statements
(:func:`app.pacticipant_store.record_version_tx`), and stores every pact of the request. A refusal
of any one pact rolls all of it back, so a build never leaves half a publication behind.

**Content is stored once.** A pact version is looked up by ``(consumer, provider, sha)`` before it
is inserted; ten consumer versions publishing the same pact share one row.

**A published pact does not silently change.** Publishing the same content again for the same
consumer version is a no-op. Publishing *different* content for a consumer version that already
has a pact for the provider is refused with ``pact-content-conflict`` unless the caller passes
``allow_modification`` — then the publication is repointed and its ``revision`` goes up.

**Everything starts from pacticipants of the caller's tenant**, resolved by
:func:`app.pacticipant_store.get_pacticipant`; a read can not reach another tenant's pact.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

from typing import Any, List, Optional, Sequence, Tuple

import psycopg2
from psycopg2.extras import Json

from .consumer_contract_store import ConsumerActor
from .pact_publication import (
    CODE_PACT_CONFLICT,
    CODE_PACT_INVALID,
    CODE_PACT_NOT_FOUND,
    PactPublicationError,
    PactRecord,
    PactToStore,
    PublishedPact,
    pact_record_from_row,
)
from .pact_selectors import PactCandidate
from .pacticipant import (
    PacticipantRecord,
    RecordedPacticipantVersion,
    validate_branch,
    validate_tags,
    validate_url,
    validate_version_number,
)
from .pacticipant_store import ensure_pacticipant_tx, get_pacticipant, record_version_tx
from .revision_deprecation import is_uuid_string

__all__ = [
    "PublishOutcome",
    "get_latest_pact",
    "get_pact",
    "get_pact_by_sha",
    "list_pact_candidates",
    "publish_pacts",
]

#: What every pact read returns: the publication, its content and both pacticipants' names.
_PACT_SELECT = """
    SELECT c.slug AS consumer_slug, c.name AS consumer_name,
           pr.slug AS provider_slug, pr.name AS provider_name,
           v.number AS consumer_version, pv.sha, pv.content, pv.specification_version,
           pv.interaction_count, p.revision, p.created_at, p.updated_at
    FROM apiome.pact_publication p
    JOIN apiome.pact_version pv ON pv.id = p.pact_version_id
    JOIN apiome.pacticipant_version v ON v.id = p.consumer_version_id
    JOIN apiome.pacticipant c ON c.id = p.consumer_id
    JOIN apiome.pacticipant pr ON pr.id = p.provider_id
    WHERE p.provider_id = %s::uuid AND p.consumer_id = %s::uuid
"""


class PublishOutcome:
    """What one publish request stored.

    Attributes:
        consumer: The consumer pacticipant.
        version: The consumer version as recorded, and whether this request created it.
        pacts: One outcome per pact, in request order.
    """

    def __init__(
        self,
        consumer: PacticipantRecord,
        version: RecordedPacticipantVersion,
        pacts: List[PublishedPact],
    ) -> None:
        """Hold the outcome.

        Args:
            consumer: The consumer pacticipant.
            version: The recorded consumer version.
            pacts: One outcome per pact.
        """
        self.consumer = consumer
        self.version = version
        self.pacts = pacts


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _store_pact(
    cursor: Any,
    tenant_id: str,
    consumer: PacticipantRecord,
    provider: PacticipantRecord,
    version: RecordedPacticipantVersion,
    pact: PactToStore,
    *,
    actor: ConsumerActor,
    allow_modification: bool,
) -> PublishedPact:
    """Store one pact of a consumer version, inside the publish transaction.

    Args:
        cursor: The open transaction's cursor.
        tenant_id: The caller's tenant.
        consumer: The consumer pacticipant.
        provider: The provider pacticipant.
        version: The recorded consumer version.
        pact: The validated pact.
        actor: Who is publishing.
        allow_modification: Whether a version's existing pact may be replaced by new content.

    Returns:
        The stored pact and what the write did.

    Raises:
        PactPublicationError: ``pact-content-conflict`` when the consumer version already has a
            different pact for this provider and replacing it is not allowed.
    """
    cursor.execute(
        """
        INSERT INTO apiome.pact_version (
            tenant_id, consumer_id, provider_id, sha, content, specification_version, interaction_count
        )
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s)
        ON CONFLICT (consumer_id, provider_id, sha) DO NOTHING
        RETURNING id::text AS id
        """,
        (
            tenant_id,
            consumer.id,
            provider.id,
            pact.sha,
            Json(pact.document),
            pact.specification_version,
            pact.interaction_count,
        ),
    )
    inserted = cursor.fetchone()
    new_content = inserted is not None
    if inserted is None:
        cursor.execute(
            """
            SELECT id::text AS id FROM apiome.pact_version
            WHERE consumer_id = %s::uuid AND provider_id = %s::uuid AND sha = %s
            """,
            (consumer.id, provider.id, pact.sha),
        )
        inserted = cursor.fetchone()
    pact_version_id = inserted["id"]

    cursor.execute(
        """
        INSERT INTO apiome.pact_publication (
            consumer_id, provider_id, consumer_version_id, pact_version_id, created_by, actor_label
        )
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s::uuid, %s)
        ON CONFLICT (consumer_version_id, consumer_id, provider_id) DO NOTHING
        RETURNING id::text AS id
        """,
        (consumer.id, provider.id, version.version.id, pact_version_id, _user_id(actor), actor.label),
    )
    created = cursor.fetchone() is not None
    replaced = False
    if not created:
        # The version already has a pact for this provider. The row lock makes two builds that
        # publish different content for it queue up instead of both passing the comparison.
        cursor.execute(
            """
            SELECT id::text AS id, pact_version_id::text AS pact_version_id
            FROM apiome.pact_publication
            WHERE consumer_version_id = %s::uuid AND consumer_id = %s::uuid AND provider_id = %s::uuid
            FOR UPDATE
            """,
            (version.version.id, consumer.id, provider.id),
        )
        existing = cursor.fetchone()
        if existing["pact_version_id"] != pact_version_id:
            if not allow_modification:
                raise PactPublicationError(
                    CODE_PACT_CONFLICT,
                    f"Cannot change the content of the pact for {consumer.name} version "
                    f"{version.version.number} and provider {provider.name}: a consumer version's pact "
                    f"is fixed once published. Publish the changed pact under a new consumer version "
                    f"number (a commit SHA makes every build's version unique).",
                )
            cursor.execute(
                """
                UPDATE apiome.pact_publication
                SET pact_version_id = %s::uuid, revision = revision + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s::uuid
                """,
                (pact_version_id, existing["id"]),
            )
            replaced = True

    cursor.execute(
        _PACT_SELECT + " AND p.consumer_version_id = %s::uuid", (provider.id, consumer.id, version.version.id)
    )
    return PublishedPact(
        pact=pact_record_from_row(dict(cursor.fetchone())),
        created=created,
        replaced=replaced,
        new_content=new_content,
    )


def publish_pacts(
    db: Any,
    tenant_id: str,
    *,
    consumer_name: str,
    version_number: str,
    pacts: Sequence[PactToStore],
    actor: ConsumerActor,
    branch: Optional[str] = None,
    tags: Optional[Sequence[str]] = None,
    build_url: Optional[str] = None,
    allow_modification: bool = False,
) -> PublishOutcome:
    """Publish the pacts of one consumer version, all or nothing.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        consumer_name: The consumer publishing; registered when the tenant does not have it yet.
        version_number: The consumer's application version.
        pacts: The validated pacts, one per provider; each provider is registered when missing.
        actor: Who is publishing.
        branch: The branch the version was built from.
        tags: Tags to put on the version.
        build_url: The CI build URL (kept only when this request creates the version).
        allow_modification: Whether an already-published pact of this version may be replaced.

    Returns:
        The consumer, the recorded version and one outcome per pact.

    Raises:
        PacticipantValidationError: For a pacticipant name no handle can be derived from, or a
            malformed version number, branch, tag or build URL.
        PactPublicationError: ``pact-content-conflict``, or ``pact-invalid`` for a document the
            database cannot hold. Nothing of the request is stored.
    """
    number = validate_version_number(version_number)
    checked_url = validate_url(build_url, what="build URL")
    checked_branch = validate_branch(branch) if branch else None
    checked_tags = validate_tags(list(tags or []))

    def store(cursor: Any) -> PublishOutcome:
        consumer = ensure_pacticipant_tx(cursor, tenant_id, consumer_name, actor=actor)
        version = record_version_tx(
            cursor, consumer, number, build_url=checked_url, branch=checked_branch, tags=checked_tags, actor=actor
        )
        stored = [
            _store_pact(
                cursor,
                tenant_id,
                consumer,
                ensure_pacticipant_tx(cursor, tenant_id, pact.provider_name, actor=actor),
                version,
                pact,
                actor=actor,
                allow_modification=allow_modification,
            )
            for pact in pacts
        ]
        return PublishOutcome(consumer, version, stored)

    def work(cursor: Any) -> PublishOutcome:
        # The savepoint makes "all or nothing" hold on its own, whatever transaction the caller's
        # database handle is already in.
        cursor.execute("SAVEPOINT pact_publish")
        try:
            outcome = store(cursor)
        except Exception:
            cursor.execute("ROLLBACK TO SAVEPOINT pact_publish")
            raise
        cursor.execute("RELEASE SAVEPOINT pact_publish")
        return outcome

    try:
        return db._guarded_tx(work)
    except psycopg2.DataError as exc:
        # JSONB cannot hold every JSON document: a string with a NUL escape (\u0000) is the known case.
        raise PactPublicationError(
            CODE_PACT_INVALID,
            "the Pact document cannot be stored: it contains a value the database does not accept "
            "(a \\u0000 character in a string is the usual cause)",
            pointer="",
        ) from exc


def _read_pact(db: Any, where: str, params: Sequence[Any], *, missing: str) -> PactRecord:
    """Run one pact read and return the latest matching publication.

    Args:
        db: The database.
        where: Extra ``AND …`` SQL narrowing :data:`_PACT_SELECT`.
        params: Its parameters, after the provider and consumer ids.
        missing: The message of the 404 when nothing matches.

    Returns:
        The pact of the latest-recorded consumer version that matches.

    Raises:
        PactPublicationError: ``pact-not-found``.
    """
    rows = db.execute_query(_PACT_SELECT + where + " ORDER BY v.seq DESC LIMIT 1", tuple(params))
    if not rows:
        raise PactPublicationError(CODE_PACT_NOT_FOUND, missing)
    return pact_record_from_row(dict(rows[0]))


def get_pact(db: Any, tenant_id: str, provider_ref: str, consumer_ref: str, version_number: str) -> PactRecord:
    """Read the pact one consumer version published for a provider.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        consumer_ref: The consumer's handle, id or name.
        version_number: The consumer version number, exactly as recorded.

    Returns:
        The pact.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown consumer or provider.
        PactPublicationError: ``pact-not-found`` when that version published no pact for it.
    """
    provider = get_pacticipant(db, tenant_id, provider_ref)
    consumer = get_pacticipant(db, tenant_id, consumer_ref)
    return _read_pact(
        db,
        " AND v.number = %s",
        (provider.id, consumer.id, version_number or ""),
        missing=(
            f"no pact between consumer '{consumer.slug}' version '{version_number}' and provider " f"'{provider.slug}'"
        ),
    )


def get_latest_pact(
    db: Any,
    tenant_id: str,
    provider_ref: str,
    consumer_ref: str,
    *,
    tag: Optional[str] = None,
    branch: Optional[str] = None,
) -> PactRecord:
    """Read the pact of the latest-recorded consumer version that published one for a provider.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        consumer_ref: The consumer's handle, id or name.
        tag: Only consumer versions with this tag (``…/latest/{tag}``).
        branch: Only consumer versions recorded on this branch (``…/branch/{branch}/latest``).

    Returns:
        The pact.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown consumer or provider.
        PactPublicationError: ``pact-not-found`` when no consumer version matches.
    """
    provider = get_pacticipant(db, tenant_id, provider_ref)
    consumer = get_pacticipant(db, tenant_id, consumer_ref)
    where = ""
    params: List[Any] = [provider.id, consumer.id]
    qualifier = ""
    if tag is not None:
        where += (
            " AND EXISTS (SELECT 1 FROM apiome.pacticipant_version_tag t"
            " WHERE t.version_id = v.id AND t.pacticipant_id = v.pacticipant_id AND t.name = %s)"
        )
        params.append(tag)
        qualifier += f" with tag '{tag}'"
    if branch is not None:
        where += (
            " AND EXISTS (SELECT 1 FROM apiome.pacticipant_branch_version bv"
            " JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id"
            " WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id AND b.name = %s)"
        )
        params.append(branch)
        qualifier += f" from branch '{branch}'"
    return _read_pact(
        db,
        where,
        params,
        missing=f"no pact between consumer '{consumer.slug}'{qualifier} and provider '{provider.slug}'",
    )


def get_pact_by_sha(db: Any, tenant_id: str, provider_ref: str, consumer_ref: str, sha: str) -> PactRecord:
    """Read a pact version by its content address.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        consumer_ref: The consumer's handle, id or name.
        sha: The pact version's SHA-256, as 64 hex characters.

    Returns:
        The pact, as the latest-recorded consumer version carrying that content published it.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown consumer or provider.
        PactPublicationError: ``pact-not-found`` when the pair has no pact version with that SHA.
    """
    provider = get_pacticipant(db, tenant_id, provider_ref)
    consumer = get_pacticipant(db, tenant_id, consumer_ref)
    return _read_pact(
        db,
        " AND pv.sha = %s",
        (provider.id, consumer.id, (sha or "").strip().lower()),
        missing=(f"no pact version '{sha}' between consumer '{consumer.slug}' and provider '{provider.slug}'"),
    )


#: The provider's publications, without content: what consumer-version selectors are applied to.
_CANDIDATE_SELECT = """
    SELECT c.id::text AS consumer_id, c.slug AS consumer_slug, c.name AS consumer_name,
           c.main_branch AS consumer_main_branch,
           v.id::text AS version_id, v.number AS version_number, v.seq AS version_seq, pv.sha,
           p.created_at AS published_at,
           COALESCE(
               (SELECT array_agg(b.name ORDER BY b.name)
                FROM apiome.pacticipant_branch_version bv
                JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
                WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id),
               ARRAY[]::text[]) AS branches,
           COALESCE(
               (SELECT array_agg(t.name ORDER BY t.name)
                FROM apiome.pacticipant_version_tag t
                WHERE t.version_id = v.id AND t.pacticipant_id = v.pacticipant_id),
               ARRAY[]::text[]) AS tags,
           COALESCE(
               (SELECT array_agg(DISTINCT e.name::text ORDER BY e.name::text)
                FROM apiome.deployed_version d
                JOIN apiome.pact_environment e ON e.id = d.environment_id AND e.tenant_id = d.tenant_id
                WHERE d.version_id = v.id AND d.pacticipant_id = v.pacticipant_id AND d.currently_deployed),
               ARRAY[]::text[]) AS deployed_to,
           COALESCE(
               (SELECT array_agg(e.name::text ORDER BY e.name::text)
                FROM apiome.released_version r
                JOIN apiome.pact_environment e ON e.id = r.environment_id AND e.tenant_id = r.tenant_id
                WHERE r.version_id = v.id AND r.pacticipant_id = v.pacticipant_id AND r.currently_supported),
               ARRAY[]::text[]) AS released_in
    FROM apiome.pact_publication p
    JOIN apiome.pact_version pv ON pv.id = p.pact_version_id
    JOIN apiome.pacticipant_version v ON v.id = p.consumer_version_id
    JOIN apiome.pacticipant c ON c.id = p.consumer_id
    WHERE p.provider_id = %s::uuid
    ORDER BY v.seq
"""


def list_pact_candidates(db: Any, tenant_id: str, provider_ref: str) -> Tuple[PacticipantRecord, List[PactCandidate]]:
    """Read every publication of a pact for a provider, for selectors to choose from.

    One row per consumer version that published a pact for the provider, with the version's
    branches and tags, the environments it is deployed or released to, and the pact's content
    address and when it was published — not the content, which a for-verification response links
    to rather than carries.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.

    Returns:
        The provider, and its publications in the order their consumer versions were recorded.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown provider.
    """
    provider = get_pacticipant(db, tenant_id, provider_ref)
    rows = db.execute_query(_CANDIDATE_SELECT, (provider.id,)) or []
    candidates = [
        PactCandidate(
            consumer_id=row["consumer_id"],
            consumer_slug=row["consumer_slug"],
            consumer_name=row["consumer_name"],
            consumer_main_branch=row.get("consumer_main_branch"),
            version_id=row["version_id"],
            version_number=row["version_number"],
            version_seq=int(row["version_seq"]),
            sha=row["sha"],
            branches=tuple(row.get("branches") or ()),
            tags=tuple(row.get("tags") or ()),
            deployed_to=tuple(row.get("deployed_to") or ()),
            released_in=tuple(row.get("released_in") or ()),
            published_at=row.get("published_at"),
        )
        for row in rows
    ]
    return provider, candidates
