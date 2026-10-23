"""Persistence for SSO providers and their domains — EID-1.1 (#5011).

:mod:`app.sso_metadata` says what a provider is; this module is the only place one is read or
written (apiome-db V312: ``sso_provider``, ``sso_provider_domain``).

**Ciphertext never leaves through a read.** :data:`_READ_COLUMNS` does not select the two
``*_encrypted`` columns — only their key ids, so a caller can report "secret set" — and the one
function that does select them, :func:`list_routable_with_secrets`, exists solely for the
service-token-gated internal endpoint that unseals them for apiome-ui.

Every function takes the :class:`~app.database.Database` it runs on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

import psycopg2
from psycopg2.extras import Json

from .sso_metadata import CODE_DOMAIN_CLAIMED, CODE_SLUG_TAKEN, SsoConfigError

__all__ = [
    "add_domain",
    "create_provider",
    "delete_provider",
    "get_provider",
    "list_domains",
    "list_providers",
    "list_routable_with_secrets",
    "remove_domain",
    "update_provider",
    "verify_domain",
]

#: A provider row as every admin read returns it. The ciphertext columns are deliberately absent.
_READ_COLUMNS = """
    p.id::text AS id, p.slug, p.protocol, p.display_name, p.issuer, p.tenant_id::text AS tenant_id,
    t.name AS tenant_name, p.oidc_config, p.saml_config,
    (p.client_secret_key_id IS NOT NULL) AS has_client_secret,
    (p.sp_private_key_key_id IS NOT NULL) AS has_sp_private_key,
    p.enabled, p.preset, p.default_role_slug, p.created_by, p.updated_by, p.created_at, p.updated_at
"""

_DOMAIN_COLUMNS = """
    d.id::text AS id, d.provider_id::text AS provider_id, d.domain, d.verification_token,
    d.verified_at, d.verified_by, d.created_at
"""

#: Columns an update may set, with whether the value is JSONB.
_UPDATABLE = {
    "display_name": False,
    "issuer": False,
    "tenant_id": False,
    "oidc_config": True,
    "saml_config": True,
    "client_secret_encrypted": False,
    "client_secret_key_id": False,
    "sp_private_key_encrypted": False,
    "sp_private_key_key_id": False,
    "enabled": False,
    "preset": False,
    "default_role_slug": False,
}


def _adapt(column: str, value: Any) -> Any:
    """Wrap a JSONB value for psycopg2; pass every other value through."""
    if _UPDATABLE.get(column) and value is not None:
        return Json(value)
    return value


def list_providers(db) -> List[Dict[str, Any]]:
    """Every provider, newest first, each with its domains under ``domains``.

    Args:
        db: The database.

    Returns:
        Provider rows (no ciphertext), each carrying a ``domains`` list.
    """
    providers = db.execute_query(
        f"""
        SELECT {_READ_COLUMNS}
        FROM apiome.sso_provider p
        LEFT JOIN apiome.tenants t ON t.id = p.tenant_id
        ORDER BY p.created_at DESC, p.slug
        """
    )
    domains = db.execute_query(f"SELECT {_DOMAIN_COLUMNS} FROM apiome.sso_provider_domain d ORDER BY d.domain")
    by_provider: Dict[str, List[Dict[str, Any]]] = {}
    for row in domains:
        by_provider.setdefault(row["provider_id"], []).append(dict(row))
    return [{**dict(row), "domains": by_provider.get(row["id"], [])} for row in providers]


def get_provider(db, provider_id: str) -> Optional[Dict[str, Any]]:
    """One provider with its domains, or ``None``.

    Args:
        db: The database.
        provider_id: The provider's uuid.

    Returns:
        The provider row (no ciphertext) with ``domains``, or ``None`` when absent.
    """
    rows = db.execute_query(
        f"""
        SELECT {_READ_COLUMNS}
        FROM apiome.sso_provider p
        LEFT JOIN apiome.tenants t ON t.id = p.tenant_id
        WHERE p.id = %s::uuid
        """,
        (provider_id,),
    )
    if not rows:
        return None
    return {**dict(rows[0]), "domains": list_domains(db, provider_id)}


def list_domains(db, provider_id: str) -> List[Dict[str, Any]]:
    """A provider's domains, alphabetically."""
    return [
        dict(row)
        for row in db.execute_query(
            f"SELECT {_DOMAIN_COLUMNS} FROM apiome.sso_provider_domain d "
            "WHERE d.provider_id = %s::uuid ORDER BY d.domain",
            (provider_id,),
        )
    ]


def create_provider(db, values: Mapping[str, Any], *, actor: str) -> Dict[str, Any]:
    """Insert a provider.

    Args:
        db: The database.
        values: ``slug``, ``protocol``, ``display_name``, ``issuer`` and any :data:`_UPDATABLE` column.
        actor: Who is creating it (``admin`` for the admin console).

    Returns:
        The created provider (no ciphertext).

    Raises:
        SsoConfigError: ``sso-slug-taken`` when the slug is in use.
    """
    columns = ["slug", "protocol", "display_name", "issuer", "created_by", "updated_by"]
    params: List[Any] = [values["slug"], values["protocol"], values["display_name"], values["issuer"], actor, actor]
    for column in _UPDATABLE:
        if column in values and column not in columns:
            columns.append(column)
            params.append(_adapt(column, values[column]))
    placeholders = ", ".join("%s::uuid" if column == "tenant_id" else "%s" for column in columns)
    try:
        rows = db.execute_query(
            f"INSERT INTO apiome.sso_provider ({', '.join(columns)}) VALUES ({placeholders}) RETURNING id::text AS id",
            tuple(params),
        )
    except psycopg2.errors.UniqueViolation as exc:
        raise SsoConfigError(CODE_SLUG_TAKEN, f"An SSO provider called “{values['slug']}” already exists.") from exc
    return get_provider(db, rows[0]["id"])  # type: ignore[return-value]


def update_provider(db, provider_id: str, updates: Mapping[str, Any], *, actor: str) -> Optional[Dict[str, Any]]:
    """Partially update a provider: only the columns in ``updates`` are written.

    Args:
        db: The database.
        provider_id: The provider's uuid.
        updates: Column → value, limited to :data:`_UPDATABLE`.
        actor: Who is changing it.

    Returns:
        The updated provider (no ciphertext), or ``None`` when it does not exist.
    """
    sets: List[str] = []
    params: List[Any] = []
    for column, value in updates.items():
        if column not in _UPDATABLE:
            raise ValueError(f"not an updatable SSO provider column: {column}")
        sets.append(f"{column} = %s::uuid" if column == "tenant_id" else f"{column} = %s")
        params.append(_adapt(column, value))
    sets.extend(["updated_by = %s", "updated_at = now()"])
    params.extend([actor, provider_id])
    rows = db.execute_query(
        f"UPDATE apiome.sso_provider SET {', '.join(sets)} WHERE id = %s::uuid RETURNING id::text AS id",
        tuple(params),
    )
    return get_provider(db, rows[0]["id"]) if rows else None


def delete_provider(db, provider_id: str) -> Optional[Dict[str, Any]]:
    """Delete a provider and (by cascade) its domains.

    Returns:
        The provider as it was before deletion, or ``None`` when it did not exist.
    """
    existing = get_provider(db, provider_id)
    if existing is None:
        return None
    db.execute_query("DELETE FROM apiome.sso_provider WHERE id = %s::uuid RETURNING id", (provider_id,))
    return existing


def add_domain(db, provider_id: str, domain: str, *, token: str) -> Dict[str, Any]:
    """Attach an email domain to a provider, unverified.

    Args:
        db: The database.
        provider_id: The provider's uuid.
        domain: A normalized domain (:func:`app.sso_metadata.normalize_domain`).
        token: The verification token EID-1.2's DNS check will look for.

    Returns:
        The domain row.

    Raises:
        SsoConfigError: ``sso-domain-claimed`` when any provider already holds the domain.
    """
    try:
        rows = db.execute_query(
            f"""
            INSERT INTO apiome.sso_provider_domain AS d (provider_id, domain, verification_token)
            VALUES (%s::uuid, %s, %s)
            RETURNING {_DOMAIN_COLUMNS}
            """,
            (provider_id, domain, token),
        )
    except psycopg2.errors.UniqueViolation as exc:
        raise SsoConfigError(CODE_DOMAIN_CLAIMED, f"{domain} is already assigned to an SSO provider.") from exc
    return dict(rows[0])


def verify_domain(db, provider_id: str, domain: str, *, actor: str) -> Optional[Dict[str, Any]]:
    """Mark a provider's domain verified (idempotent: the first verification time is kept).

    Returns:
        The domain row, or ``None`` when the provider has no such domain.
    """
    rows = db.execute_query(
        f"""
        UPDATE apiome.sso_provider_domain AS d
        SET verified_at = COALESCE(d.verified_at, now()),
            verified_by = COALESCE(d.verified_by, %s)
        WHERE d.provider_id = %s::uuid AND d.domain = %s
        RETURNING {_DOMAIN_COLUMNS}
        """,
        (actor, provider_id, domain),
    )
    return dict(rows[0]) if rows else None


def remove_domain(db, provider_id: str, domain: str) -> bool:
    """Detach a domain from a provider.

    Returns:
        Whether a row was removed.
    """
    rows = db.execute_query(
        "DELETE FROM apiome.sso_provider_domain WHERE provider_id = %s::uuid AND domain = %s RETURNING id",
        (provider_id, domain),
    )
    return bool(rows)


def list_routable_with_secrets(db) -> List[Dict[str, Any]]:
    """Enabled providers with at least one verified domain, **including ciphertext**.

    For the service-token-gated internal endpoint only: the caller unseals the secrets in-process
    and hands them to apiome-ui's sign-in resolver. This must never back a client-facing response.

    Args:
        db: The database.

    Returns:
        One row per routable provider: id, slug, protocol, display name, issuer, tenant, configs,
        both ciphertexts with their key ids, and ``domains`` — the verified domains only.
    """
    rows = db.execute_query(
        """
        SELECT p.id::text AS id, p.slug, p.protocol, p.display_name, p.issuer,
               p.tenant_id::text AS tenant_id, p.oidc_config, p.saml_config,
               p.client_secret_encrypted, p.client_secret_key_id,
               p.sp_private_key_encrypted, p.sp_private_key_key_id,
               array_agg(d.domain ORDER BY d.domain) AS domains
        FROM apiome.sso_provider p
        JOIN apiome.sso_provider_domain d
          ON d.provider_id = p.id AND d.verified_at IS NOT NULL
        WHERE p.enabled
        GROUP BY p.id
        ORDER BY p.slug
        """
    )
    return [dict(row) for row in rows]
