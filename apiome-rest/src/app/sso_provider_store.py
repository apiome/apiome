"""Persistence for SSO providers and their domains — EID-1.1 (#5011), EID-1.2 (#5012).

:mod:`app.sso_metadata` says what a provider is; this module is the only place one is read or
written (apiome-db V312, V393: ``sso_provider``, ``sso_provider_domain``).

**A workspace sees only its own providers.** The reads and writes the workspace-owner routes use
take ``tenant_id``; with it, a provider of another workspace is simply not found.

**A verified domain is unique installation-wide; an unverified one is not** (V393). Several
workspaces may list ``acme.com``; the first to prove it holds it, and the others are refused
``sso-domain-claimed`` when they add or verify it.

**Ciphertext never leaves through a read.** :data:`_READ_COLUMNS` does not select the two
``*_encrypted`` columns — only their key ids, so a caller can report "secret set" — and the one
function that does select them, :func:`list_routable_with_secrets`, exists solely for the
service-token-gated internal endpoint that unseals them for apiome-ui.

Every function takes the :class:`~app.database.Database` it runs on.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

import psycopg2
from psycopg2.extras import Json

from .keyset_lists import ListOrder, SortColumn, by_name
from .sso_metadata import CODE_DOMAIN_CLAIMED, CODE_DOMAIN_EXISTS, CODE_SLUG_TAKEN, SsoConfigError

__all__ = [
    "add_domain",
    "count_linked_members",
    "create_provider",
    "delete_provider",
    "domain_verified_elsewhere",
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


#: The provider list's ordering: newest first, then by slug (#7196).
PROVIDERS_ORDER = ListOrder(
    "sso-providers",
    (
        SortColumn("p.created_at", "time", ("created_at",), descending=True),
        SortColumn("p.slug", "text", ("slug",)),
        SortColumn("p.id", "uuid", ("id",)),
    ),
)

#: The routable-provider list's ordering: by slug (#7196).
ROUTABLE_PROVIDERS_ORDER = by_name("sso-routable-providers", "p.slug", "p.id", name_field="slug")


def list_providers(
    db,
    *,
    tenant_id: Optional[str] = None,
    limit: Optional[int] = None,
    cursor: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Providers, newest first, each with its domains under ``domains``.

    Args:
        db: The database.
        tenant_id: When given, only that workspace's providers.
        limit: Providers to read; ``None`` reads them all.
        cursor: :data:`PROVIDERS_ORDER` values of the last provider already seen (#7196).

    Returns:
        Provider rows (no ciphertext), each carrying a ``domains`` list.
    """
    scope, params = ("WHERE p.tenant_id = %s::uuid", (tenant_id,)) if tenant_id else ("WHERE TRUE", ())
    after_sql, after_params, limit_sql, limit_params = PROVIDERS_ORDER.window(limit, cursor)
    providers = db.execute_query(
        f"""
        SELECT {_READ_COLUMNS}
        FROM apiome.sso_provider p
        LEFT JOIN apiome.tenants t ON t.id = p.tenant_id
        {scope}{after_sql}
        ORDER BY {PROVIDERS_ORDER.order_by}{limit_sql}
        """,
        (*params, *after_params, *limit_params),
    )
    if limit is None and cursor is None:
        domain_scope, domain_params = scope, params
    else:
        # One page of providers: read only their domains.
        domain_scope = "WHERE d.provider_id = ANY(%s::uuid[])"
        domain_params = ([row["id"] for row in providers],)
    domains = db.execute_query(
        f"""
        SELECT {_DOMAIN_COLUMNS}
        FROM apiome.sso_provider_domain d
        JOIN apiome.sso_provider p ON p.id = d.provider_id
        {domain_scope}
        ORDER BY d.domain
        """,
        domain_params,
    )
    by_provider: Dict[str, List[Dict[str, Any]]] = {}
    for row in domains:
        by_provider.setdefault(row["provider_id"], []).append(dict(row))
    return [{**dict(row), "domains": by_provider.get(row["id"], [])} for row in providers]


def get_provider(db, provider_id: str, *, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """One provider with its domains, or ``None``.

    Args:
        db: The database.
        provider_id: The provider's uuid.
        tenant_id: When given, the provider must belong to that workspace.

    Returns:
        The provider row (no ciphertext) with ``domains``, or ``None`` when absent — or when it
        belongs to another workspace.
    """
    scope, params = ("AND p.tenant_id = %s::uuid", (provider_id, tenant_id)) if tenant_id else ("", (provider_id,))
    rows = db.execute_query(
        f"""
        SELECT {_READ_COLUMNS}
        FROM apiome.sso_provider p
        LEFT JOIN apiome.tenants t ON t.id = p.tenant_id
        WHERE p.id = %s::uuid {scope}
        """,
        params,
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
        token: The verification token the DNS check looks for (EID-1.2).

    Returns:
        The domain row.

    Raises:
        SsoConfigError: ``sso-domain-claimed`` when another provider has verified the domain;
            ``sso-domain-exists`` when this provider already lists it.
    """
    if domain_verified_elsewhere(db, provider_id, domain):
        raise SsoConfigError(CODE_DOMAIN_CLAIMED, f"{domain} is already verified for another SSO provider.")
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
        raise SsoConfigError(CODE_DOMAIN_EXISTS, f"{domain} is already on this SSO provider.") from exc
    return dict(rows[0])


def domain_verified_elsewhere(db, provider_id: str, domain: str) -> bool:
    """Whether a *different* provider has already verified ``domain``.

    Args:
        db: The database.
        provider_id: The provider asking.
        domain: A normalized domain.

    Returns:
        True when the domain is taken: it can be neither added to nor verified for this provider.
    """
    rows = db.execute_query(
        """
        SELECT 1 FROM apiome.sso_provider_domain
        WHERE domain = %s AND verified_at IS NOT NULL AND provider_id <> %s::uuid
        LIMIT 1
        """,
        (domain, provider_id),
    )
    return bool(rows)


def count_linked_members(db, tenant_id: str, slug: str) -> int:
    """How many of a workspace's members have signed in through a provider.

    A member counts when they hold an ``sso:<slug>`` identity (``external_auth_providers``).
    Removing the provider keeps those identities, but the members can no longer use them.

    Args:
        db: The database.
        tenant_id: The workspace.
        slug: The provider's slug.

    Returns:
        The number of members.
    """
    rows = db.execute_query(
        """
        SELECT COUNT(DISTINCT tu.user_id) AS members
        FROM apiome.tenant_users tu
        JOIN apiome.external_auth_providers eap ON eap.user_id = tu.user_id
        WHERE tu.tenant_id = %s::uuid AND eap.provider = %s
        """,
        (tenant_id, f"sso:{slug}"),
    )
    return int(rows[0]["members"]) if rows else 0


def verify_domain(db, provider_id: str, domain: str, *, actor: str) -> Optional[Dict[str, Any]]:
    """Mark a provider's domain verified (idempotent: the first verification time is kept).

    Returns:
        The domain row, or ``None`` when the provider has no such domain.

    Raises:
        SsoConfigError: ``sso-domain-claimed`` when another provider verified it first (V393's
            partial unique index decides a race).
    """
    try:
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
    except psycopg2.errors.UniqueViolation as exc:
        raise SsoConfigError(CODE_DOMAIN_CLAIMED, f"{domain} is already verified for another SSO provider.") from exc
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


def list_routable_with_secrets(
    db, *, limit: Optional[int] = None, cursor: Optional[Sequence[Any]] = None
) -> List[Dict[str, Any]]:
    """Enabled providers with a workspace and at least one verified domain, **including ciphertext**.

    A provider without a workspace (registered before EID-1.3 and switched off by V394) has nowhere
    to provision into, so it never routes.

    For the service-token-gated internal endpoint only: the caller unseals the secrets in-process
    and hands them to apiome-ui's sign-in resolver. This must never back a client-facing response.

    Args:
        db: The database.
        limit: Providers to read; ``None`` reads them all.
        cursor: :data:`ROUTABLE_PROVIDERS_ORDER` values of the last provider already seen (#7196).

    Returns:
        One row per routable provider: id, slug, protocol, display name, issuer, tenant, configs,
        both ciphertexts with their key ids, and ``domains`` — the verified domains only.
    """
    after_sql, after_params, limit_sql, limit_params = ROUTABLE_PROVIDERS_ORDER.window(limit, cursor)
    rows = db.execute_query(
        f"""
        SELECT p.id::text AS id, p.slug, p.protocol, p.display_name, p.issuer,
               p.tenant_id::text AS tenant_id, p.oidc_config, p.saml_config,
               p.client_secret_encrypted, p.client_secret_key_id,
               p.sp_private_key_encrypted, p.sp_private_key_key_id,
               array_agg(d.domain ORDER BY d.domain) AS domains
        FROM apiome.sso_provider p
        JOIN apiome.sso_provider_domain d
          ON d.provider_id = p.id AND d.verified_at IS NOT NULL
        WHERE p.enabled AND p.tenant_id IS NOT NULL{after_sql}
        GROUP BY p.id
        ORDER BY {ROUTABLE_PROVIDERS_ORDER.order_by}{limit_sql}
        """,
        (*after_params, *limit_params),
    )
    return [dict(row) for row in rows]
