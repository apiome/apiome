"""Persistence for provider contracts — PFX-2.1 (#6925).

:mod:`app.provider_contract` says what a provider contract *is*; this module is the only place one
is read or written (apiome-db V438).

**A publish is one transaction.** :func:`publish_provider_contract` registers the provider when the
workspace does not have it yet, records the provider version with its branch, tags and build URL
through the registry's own statements (:func:`app.pacticipant_store.record_version_tx`), and stores
the contract. A refusal rolls all of it back.

**Content is stored once.** A document is looked up by ``(provider, sha)`` before it is inserted;
ten provider versions publishing the same document share one ``provider_contract`` row.

**Write-once per provider version.** Publishing the same contract again for a provider version —
the same document and the same self-verification results — is a no-op. Publishing anything else
for a version that already has a contract is refused with ``provider-contract-conflict``; a
changed provider is a new provider version.

**Everything starts from the provider of the caller's tenant**, resolved by
:func:`app.pacticipant_store.get_pacticipant`; a read cannot reach another tenant's contract.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence, Tuple

import psycopg2
from psycopg2.extras import Json

from .consumer_contract_store import ConsumerActor
from .pacticipant import validate_branch, validate_tags, validate_url, validate_version_number
from .pacticipant_store import ensure_pacticipant_tx, get_pacticipant, record_version_tx
from .provider_contract import (
    CODE_CONTRACT_CONFLICT,
    CODE_CONTRACT_INVALID,
    CODE_CONTRACT_NOT_FOUND,
    ProviderContractError,
    ProviderContractRecord,
    ProviderContractToStore,
    PublishedProviderContract,
    contract_record_from_row,
    sent_verification_results,
)
from .revision_deprecation import is_uuid_string

__all__ = ["get_provider_contract", "publish_provider_contract"]

#: What every contract read returns: the publication, its document and the provider's names.
_CONTRACT_SELECT = """
    SELECT pr.slug AS provider_slug, pr.name AS provider_name, v.number AS provider_version,
           c.sha, c.content, c.oas_version, c.operation_count,
           p.content_type, p.source, p.source_project_slug, p.source_version_label,
           p.source_project_id::text AS source_project_id, p.source_version_id::text AS source_version_id,
           p.verification_results, p.created_at
    FROM apiome.provider_contract_publication p
    JOIN apiome.provider_contract c ON c.id = p.provider_contract_id AND c.provider_id = p.provider_id
    JOIN apiome.pacticipant_version v ON v.id = p.provider_version_id AND v.pacticipant_id = p.provider_id
    JOIN apiome.pacticipant pr ON pr.id = p.provider_id
    WHERE p.provider_id = %s::uuid
      -- PFX-1.11: a deleted provider version's contract is gone with it.
      AND v.deleted_at IS NULL
"""


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _store_contract_tx(
    cursor: Any, tenant_id: str, provider_id: str, contract: ProviderContractToStore
) -> Tuple[str, bool]:
    """Insert the document unless the provider already has it.

    Args:
        cursor: The open transaction's cursor.
        tenant_id: The caller's tenant.
        provider_id: The provider pacticipant's id.
        contract: The validated contract.

    Returns:
        ``(provider_contract id, whether this call inserted it)``.
    """
    cursor.execute(
        """
        INSERT INTO apiome.provider_contract (tenant_id, provider_id, sha, content, oas_version, operation_count)
        VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
        ON CONFLICT (provider_id, sha) DO NOTHING
        RETURNING id::text AS id
        """,
        (tenant_id, provider_id, contract.sha, Json(contract.document), contract.oas_version, contract.operation_count),
    )
    inserted = cursor.fetchone()
    if inserted is not None:
        return inserted["id"], True
    cursor.execute(
        "SELECT id::text AS id FROM apiome.provider_contract WHERE provider_id = %s::uuid AND sha = %s",
        (provider_id, contract.sha),
    )
    return cursor.fetchone()["id"], False


def publish_provider_contract(
    db: Any,
    tenant_id: str,
    *,
    provider_name: str,
    version_number: str,
    contract: ProviderContractToStore,
    actor: ConsumerActor,
    branch: Optional[str] = None,
    tags: Optional[Sequence[str]] = None,
    build_url: Optional[str] = None,
) -> PublishedProviderContract:
    """Publish the provider contract of one provider version, all or nothing.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_name: The provider; registered when the tenant does not have it yet.
        version_number: The provider's application version.
        contract: The validated contract.
        actor: Who is publishing.
        branch: The branch the version was built from.
        tags: Tags to put on the version.
        build_url: The CI build URL (kept only when this request creates the version).

    Returns:
        The stored contract and what the write did.

    Raises:
        PacticipantValidationError: For a provider name no handle can be derived from, or a
            malformed version number, branch, tag or build URL.
        ProviderContractError: ``provider-contract-conflict`` when the version already published
            a different contract (or the same one with different self-verification results);
            ``provider-contract-invalid`` for a document the database cannot hold. Nothing of the
            request is stored.
    """
    number = validate_version_number(version_number)
    checked_url = validate_url(build_url, what="build URL")
    checked_branch = validate_branch(branch) if branch else None
    checked_tags = validate_tags(list(tags or []))

    def store(cursor: Any) -> PublishedProviderContract:
        provider = ensure_pacticipant_tx(cursor, tenant_id, provider_name, actor=actor)
        version = record_version_tx(
            cursor, provider, number, build_url=checked_url, branch=checked_branch, tags=checked_tags, actor=actor
        )
        contract_id, new_content = _store_contract_tx(cursor, tenant_id, provider.id, contract)
        cursor.execute(
            """
            INSERT INTO apiome.provider_contract_publication (
                tenant_id, provider_id, provider_version_id, provider_contract_id, content_type, source,
                source_project_id, source_version_id, source_project_slug, source_version_label,
                verification_results, created_by, actor_label
            )
            VALUES (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s::uuid, %s::uuid, %s, %s, %s, %s::uuid, %s)
            ON CONFLICT (provider_version_id) DO NOTHING
            RETURNING id::text AS id
            """,
            (
                tenant_id,
                provider.id,
                version.version.id,
                contract_id,
                contract.content_type,
                contract.source,
                contract.source_project_id,
                contract.source_version_id,
                contract.source_project_slug,
                contract.source_version_label,
                Json(contract.verification_results) if contract.verification_results is not None else None,
                _user_id(actor),
                actor.label,
            ),
        )
        created = cursor.fetchone() is not None
        cursor.execute(_CONTRACT_SELECT + " AND p.provider_version_id = %s::uuid", (provider.id, version.version.id))
        stored = contract_record_from_row(dict(cursor.fetchone()))
        if not created and (
            stored.sha != contract.sha
            or sent_verification_results(stored.verification_results)
            != sent_verification_results(contract.verification_results)
        ):
            what = "contract" if stored.sha != contract.sha else "self-verification results"
            raise ProviderContractError(
                CODE_CONTRACT_CONFLICT,
                f"Cannot change the provider contract of {provider.name} version {number}: it was published "
                f"with a different {what}, and a provider version's contract is fixed once published. "
                f"Publish the changed contract under a new provider version number (a commit SHA makes "
                f"every build's version unique).",
            )
        return PublishedProviderContract(
            contract=stored, created=created, new_content=new_content, version_created=version.created
        )

    def work(cursor: Any) -> PublishedProviderContract:
        # The savepoint makes "all or nothing" hold on its own, whatever transaction the caller's
        # database handle is already in.
        cursor.execute("SAVEPOINT provider_contract_publish")
        try:
            outcome = store(cursor)
        except Exception:
            cursor.execute("ROLLBACK TO SAVEPOINT provider_contract_publish")
            raise
        cursor.execute("RELEASE SAVEPOINT provider_contract_publish")
        return outcome

    try:
        return db._guarded_tx(work)
    except psycopg2.DataError as exc:
        # JSONB cannot hold every JSON document: a string with a NUL escape (\u0000) is the known case.
        raise ProviderContractError(
            CODE_CONTRACT_INVALID,
            "the OpenAPI document cannot be stored: it contains a value the database does not accept "
            "(a \\u0000 character in a string is the usual cause)",
            pointer="",
        ) from exc


def get_provider_contract(db: Any, tenant_id: str, provider_ref: str, version_number: str) -> ProviderContractRecord:
    """Read the provider contract one provider version published.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        provider_ref: The provider's handle, id or name.
        version_number: The provider version number, exactly as recorded.

    Returns:
        The contract.

    Raises:
        PacticipantValidationError: ``pacticipant-not-found`` for an unknown provider.
        ProviderContractError: ``provider-contract-not-found`` when that version published none.
    """
    provider = get_pacticipant(db, tenant_id, provider_ref)
    rows = db.execute_query(_CONTRACT_SELECT + " AND v.number = %s", (provider.id, version_number or ""))
    if not rows:
        raise ProviderContractError(
            CODE_CONTRACT_NOT_FOUND,
            f"provider '{provider.slug}' version '{version_number}' has published no provider contract",
        )
    return contract_record_from_row(dict(rows[0]))
