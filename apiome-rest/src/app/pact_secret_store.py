"""Persistence for workspace secrets — PFX-6.5 (#6957).

:mod:`app.pact_secret` says what a secret *is*; this module is the only place one is read or
written (``apiome.pact_secret``, apiome-db V450).

**Sealed on the way in, opened in one place.** :func:`create_secret` and :func:`update_secret` seal
the value with the shared envelope cipher (:mod:`app.envelope_crypto`) under the credential vault's
master keys (``APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS``) and this vault's own magic (``OPSC``), so a
sealed secret does not open as any other vault's blob. Every read returns a
:class:`~app.pact_secret.SecretRecord`, which has no field the value could be in. The only function
that opens values is :func:`resolve_secrets`, for a webhook send or a verification run, in memory.

**Fails closed.** Without a key a secret cannot be stored (``pact-secret-vault-unavailable``) and a
stored one cannot be resolved; the send or the run then fails with the reason rather than going out
without its credential.

**A secret in use is not deleted.** :func:`secret_usage` finds the webhooks (``secret_refs``, written
when a webhook is saved) and the verification targets that refer to it, and :func:`delete_secret`
refuses while there are any, naming them.

**Everything starts from the caller's tenant.** A secret of another workspace reads as not found,
and a reference resolves only within the workspace of the webhook or target that makes it.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from .config import settings
from .consumer_contract_store import ConsumerActor
from .envelope_crypto import EnvelopeCipher, EnvelopeEncryptionError
from .pact_secret import (
    CODE_SECRET_IN_USE,
    CODE_SECRET_INVALID,
    CODE_SECRET_LIMIT,
    CODE_SECRET_NAME_TAKEN,
    CODE_SECRET_NOT_FOUND,
    CODE_SECRET_VAULT_UNAVAILABLE,
    MAX_SECRETS_PER_TENANT,
    PactSecretError,
    SecretCreate,
    SecretRecord,
    SecretUpdate,
    SecretUsage,
    SecretUser,
    secret_reference,
)
from .pact_webhook import request_description
from .revision_deprecation import is_uuid_string

__all__ = [
    "KEYS_SETTING",
    "create_secret",
    "delete_secret",
    "get_secret",
    "list_secrets",
    "missing_secret_names",
    "resolve_secrets",
    "secret_usage",
    "update_secret",
]

#: The environment variable holding the master keys (the credential vault's).
KEYS_SETTING = "APIOME_MCP_CREDENTIAL_ENCRYPTION_KEYS"

#: ``OPSC`` = *apiome Pact SeCret*.
_CIPHER = EnvelopeCipher(
    magic=b"OPSC",
    subject="workspace secret",
    keys_setting=KEYS_SETTING,
    read_keys=lambda: settings.mcp_credential_encryption_keys,
    read_active_version=lambda: settings.mcp_credential_active_key_version,
)

_SELECT = """
    SELECT s.id::text AS id, s.name, s.description, s.value_updated_at, s.created_at, s.updated_at
    FROM apiome.pact_secret s
    WHERE s.tenant_id = %s::uuid
"""


def _iso(value: Any) -> Optional[str]:
    """Render a timestamp column as ISO-8601 text (``None`` stays ``None``)."""
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else (str(value) if value is not None else None)


def _user_id(actor: ConsumerActor) -> Optional[str]:
    """The actor's user id when it is a storable UUID, else ``None``."""
    return actor.user_id if actor.user_id and is_uuid_string(str(actor.user_id)) else None


def _missing(secret_id: str) -> PactSecretError:
    """The 404 for a secret the workspace does not have."""
    return PactSecretError(CODE_SECRET_NOT_FOUND, f"no secret '{secret_id}' in this workspace")


def _seal(value: str) -> tuple:
    """Seal one value: ``(ciphertext, key_version)``.

    Raises:
        PactSecretError: ``pact-secret-vault-unavailable`` when no master key is configured.
    """
    try:
        return _CIPHER.seal({"value": value})
    except EnvelopeEncryptionError as exc:
        raise PactSecretError(
            CODE_SECRET_VAULT_UNAVAILABLE, f"the server cannot seal a secret: set {KEYS_SETTING}"
        ) from exc


def _record(row: Mapping[str, Any], usage: SecretUsage) -> SecretRecord:
    """Adapt a :data:`_SELECT` row (no sealed column is selected) into its record."""
    return SecretRecord(
        id=str(row["id"]),
        name=str(row["name"]),
        description=row.get("description"),
        reference=secret_reference(str(row["name"])),
        used_by=usage,
        value_updated_at=_iso(row.get("value_updated_at")),
        created_at=_iso(row.get("created_at")),
        updated_at=_iso(row.get("updated_at")),
    )


# ---------------------------------------------------------------------------------------------
# Usage
# ---------------------------------------------------------------------------------------------


def _usages(db: Any, tenant_id: str, names: Optional[Sequence[str]] = None) -> Dict[str, SecretUsage]:
    """What refers to each secret name of the workspace (or only to ``names``).

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        names: Only these names; ``None`` for every name referred to.

    Returns:
        ``{name: usage}`` for each name something refers to.
    """
    usage: Dict[str, SecretUsage] = {}
    only = list(names) if names is not None else None
    webhooks = (
        db.execute_query(
            """
            SELECT w.id::text AS id, w.description, w.request_method, w.request_url, ref.name
            FROM apiome.pact_webhook w
            CROSS JOIN LATERAL unnest(w.secret_refs) AS ref(name)
            WHERE w.tenant_id = %s::uuid AND (%s::text[] IS NULL OR ref.name = ANY(%s::text[]))
            ORDER BY w.created_at, w.id
            """,
            (tenant_id, only, only),
        )
        or []
    )
    for row in webhooks:
        shown = row.get("description") or request_description(
            str(row.get("request_method") or ""), str(row.get("request_url") or "")
        )
        usage.setdefault(row["name"], SecretUsage()).webhooks.append(
            SecretUser(kind="webhook", id=str(row["id"]), name=str(shown))
        )
    targets = (
        db.execute_query(
            """
            SELECT t.id::text AS id, t.slug, t.auth_ref AS name
            FROM apiome.verification_target t
            WHERE t.tenant_id = %s::uuid AND t.auth_kind = 'secret' AND t.deleted_at IS NULL
              AND (%s::text[] IS NULL OR t.auth_ref = ANY(%s::text[]))
            ORDER BY t.slug
            """,
            (tenant_id, only, only),
        )
        or []
    )
    for row in targets:
        usage.setdefault(row["name"], SecretUsage()).targets.append(
            SecretUser(kind="verification_target", id=str(row["id"]), name=str(row["slug"]))
        )
    return usage


def secret_usage(db: Any, tenant_id: str, name: str) -> SecretUsage:
    """What refers to one secret.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        name: The secret's name.

    Returns:
        The webhooks and verification targets that refer to it (both empty when none do).
    """
    return _usages(db, tenant_id, [name]).get(name, SecretUsage())


# ---------------------------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------------------------


def list_secrets(db: Any, tenant_id: str) -> List[SecretRecord]:
    """List the workspace's secrets by name, each with what refers to it.

    Args:
        db: The database.
        tenant_id: The caller's tenant.

    Returns:
        The secrets, never their values.
    """
    rows = db.execute_query(_SELECT + " ORDER BY s.name", (tenant_id,)) or []
    usage = _usages(db, tenant_id) if rows else {}
    return [_record(dict(row), usage.get(row["name"], SecretUsage())) for row in rows]


def _read_row(db: Any, tenant_id: str, secret_id: str) -> Optional[Dict[str, Any]]:
    """Read one secret row (no sealed column); ``None`` when the tenant has none."""
    if not is_uuid_string(str(secret_id or "")):
        return None
    rows = db.execute_query(_SELECT + " AND s.id = %s::uuid", (tenant_id, secret_id))
    return dict(rows[0]) if rows else None


def get_secret(db: Any, tenant_id: str, secret_id: str) -> SecretRecord:
    """Read one secret.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        secret_id: The secret's id.

    Returns:
        The secret, never its value.

    Raises:
        PactSecretError: ``pact-secret-not-found``.
    """
    row = _read_row(db, tenant_id, secret_id)
    if row is None:
        raise _missing(secret_id)
    return _record(row, secret_usage(db, tenant_id, row["name"]))


def missing_secret_names(db: Any, tenant_id: str, names: Sequence[str]) -> List[str]:
    """The names among ``names`` the workspace has no secret for, in the order given.

    Args:
        db: The database.
        tenant_id: The tenant whose secrets a reference may name.
        names: The referred names.

    Returns:
        The names that name nothing.
    """
    if not names:
        return []
    rows = (
        db.execute_query(
            "SELECT name FROM apiome.pact_secret WHERE tenant_id = %s::uuid AND name = ANY(%s::text[])",
            (tenant_id, list(names)),
        )
        or []
    )
    known = {row["name"] for row in rows}
    return [name for name in names if name not in known]


def resolve_secrets(db: Any, tenant_id: str, names: Sequence[str]) -> Dict[str, str]:
    """Open the values of the secrets ``names`` refers to, in memory, for one send or run.

    Args:
        db: The database.
        tenant_id: The tenant of the webhook or target making the reference.
        names: The referred names.

    Returns:
        ``{name: value}`` for every name.

    Raises:
        PactSecretError: ``pact-secret-not-found`` naming the first name the workspace has no
            secret for; ``pact-secret-vault-unavailable`` naming the first that cannot be opened
            (no key, wrong key, tampered). Never a value.
    """
    wanted = list(dict.fromkeys(names))
    if not wanted:
        return {}
    rows = (
        db.execute_query(
            """
            SELECT name, secret_ciphertext, key_version FROM apiome.pact_secret
            WHERE tenant_id = %s::uuid AND name = ANY(%s::text[])
            """,
            (tenant_id, wanted),
        )
        or []
    )
    by_name = {row["name"]: row for row in rows}
    values: Dict[str, str] = {}
    for name in wanted:
        row = by_name.get(name)
        if row is None:
            raise PactSecretError(CODE_SECRET_NOT_FOUND, f"no secret '{name}' in this workspace")
        opened = _CIPHER.unseal(bytes(row["secret_ciphertext"]), row.get("key_version"))
        value = opened.get("value") if isinstance(opened, Mapping) else None
        if not isinstance(value, str):
            raise PactSecretError(
                CODE_SECRET_VAULT_UNAVAILABLE, f"the secret '{name}' cannot be opened (check {KEYS_SETTING})"
            )
        values[name] = value
    return values


# ---------------------------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------------------------


def create_secret(db: Any, tenant_id: str, secret: SecretCreate, *, actor: ConsumerActor) -> SecretRecord:
    """Create a secret.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        secret: The checked body.
        actor: Who is creating it.

    Returns:
        The stored secret, never its value.

    Raises:
        PactSecretError: ``pact-secret-vault-unavailable`` without a key; ``pact-secret-limit-reached``
            at :data:`MAX_SECRETS_PER_TENANT`; ``pact-secret-name-taken`` for a name in use.
    """
    ciphertext, key_version = _seal(secret.value)
    user_id = _user_id(actor)

    def work(cursor: Any) -> Optional[str]:
        cursor.execute("SELECT count(*) AS n FROM apiome.pact_secret WHERE tenant_id = %s::uuid", (tenant_id,))
        if int(cursor.fetchone()["n"]) >= MAX_SECRETS_PER_TENANT:
            raise PactSecretError(
                CODE_SECRET_LIMIT,
                f"this workspace already has {MAX_SECRETS_PER_TENANT} secrets; delete one before adding another",
            )
        cursor.execute(
            """
            INSERT INTO apiome.pact_secret
              (tenant_id, name, description, secret_ciphertext, key_version, created_by, updated_by)
            VALUES (%s::uuid, %s, %s, %s, %s, %s::uuid, %s::uuid)
            ON CONFLICT (tenant_id, name) DO NOTHING
            RETURNING id::text AS id
            """,
            (tenant_id, secret.name, secret.description, ciphertext, key_version, user_id, user_id),
        )
        row = cursor.fetchone()
        return row["id"] if row else None

    created_id = db._guarded_tx(work)
    if not created_id:
        raise PactSecretError(
            CODE_SECRET_NAME_TAKEN,
            f"this workspace already has a secret named '{secret.name}'; update it to change its value",
            pointer="/name",
        )
    return get_secret(db, tenant_id, created_id)


def update_secret(
    db: Any, tenant_id: str, secret_id: str, change: SecretUpdate, *, actor: ConsumerActor
) -> SecretRecord:
    """Change a secret's description and, when a value is sent, rotate its value.

    Every webhook and target that refers to it uses the new value from its next send or run.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        secret_id: The secret's id.
        change: The checked body.
        actor: Who is changing it.

    Returns:
        The stored secret, never its value.

    Raises:
        PactSecretError: ``pact-secret-not-found``; ``pact-secret-invalid`` for a different
            ``name``; ``pact-secret-vault-unavailable`` without a key.
    """
    row = _read_row(db, tenant_id, secret_id)
    if row is None:
        raise _missing(secret_id)
    if change.name is not None and change.name != row["name"]:
        raise PactSecretError(
            CODE_SECRET_INVALID,
            f"/name: a secret cannot be renamed (references use '{row['name']}'); create a new one instead",
            pointer="/name",
        )
    sealed = _seal(change.value) if change.value is not None else None
    user_id = _user_id(actor)

    def work(cursor: Any) -> bool:
        if sealed is None:
            cursor.execute(
                """
                UPDATE apiome.pact_secret
                SET description = %s, updated_by = %s::uuid, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = %s::uuid AND id = %s::uuid
                """,
                (change.description, user_id, tenant_id, secret_id),
            )
        else:
            cursor.execute(
                """
                UPDATE apiome.pact_secret
                SET description = %s, secret_ciphertext = %s, key_version = %s,
                    value_updated_at = CURRENT_TIMESTAMP,
                    updated_by = %s::uuid, updated_at = CURRENT_TIMESTAMP
                WHERE tenant_id = %s::uuid AND id = %s::uuid
                """,
                (change.description, sealed[0], sealed[1], user_id, tenant_id, secret_id),
            )
        return cursor.rowcount > 0

    if not db._guarded_tx(work):
        raise _missing(secret_id)
    return get_secret(db, tenant_id, secret_id)


def _in_use_message(name: str, usage: SecretUsage) -> str:
    """Why a secret cannot be deleted, naming what refers to it."""
    parts = []
    if usage.webhooks:
        parts.append("webhooks " + ", ".join(f"'{user.name}' ({user.id})" for user in usage.webhooks))
    if usage.targets:
        parts.append("verification targets " + ", ".join(f"'{user.name}'" for user in usage.targets))
    return f"the secret '{name}' is still used by {' and '.join(parts)}; change them first"


def delete_secret(db: Any, tenant_id: str, secret_id: str) -> SecretRecord:
    """Delete a secret nothing refers to.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        secret_id: The secret's id.

    Returns:
        The secret as it was.

    Raises:
        PactSecretError: ``pact-secret-not-found``; ``pact-secret-in-use`` naming the webhooks and
            targets that still refer to it.
    """
    record = get_secret(db, tenant_id, secret_id)
    if not record.used_by.is_empty():
        raise PactSecretError(CODE_SECRET_IN_USE, _in_use_message(record.name, record.used_by))

    def work(cursor: Any) -> bool:
        cursor.execute(
            "DELETE FROM apiome.pact_secret WHERE tenant_id = %s::uuid AND id = %s::uuid", (tenant_id, secret_id)
        )
        return True

    db._guarded_tx(work)
    return record
