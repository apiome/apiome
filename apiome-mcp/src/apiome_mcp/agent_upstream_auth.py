"""AGX-2.1 upstream auth injection — open the AGX-2.2 vault for one outgoing request (#4533).

Agents never hold upstream credentials. For a ``prod`` toolset the proxy asks the vault for the
credential bound to the exact URL it is about to call and attaches it server-side; the agent only
ever sees its Apiome agent key.

apiome-rest's :func:`app.upstream_credentials.resolve_injection` does this through apiome-rest's
synchronous database layer. The MCP runtime is async, so this module reads the same rows through
the MCP pool and calls the same pure steps
(:func:`~app.upstream_credentials.select_bound_credential`,
:func:`~app.upstream_credentials.open_bound_credential`), so the two services can never disagree
about which secret goes with which URL. It writes the same metadata-only
``upstream_credential_uses`` row for every open.

* No credential bound to the URL → ``None``: the request goes out without one (a public upstream).
* A bound credential that cannot be opened → :class:`UpstreamCredentialUnavailableError`: the call
  fails closed and is never sent unauthenticated.

Opening needs the vault's master key in this process too: set
``APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS`` to the same key map apiome-rest uses.
"""

from __future__ import annotations

import structlog
from app.upstream_credential_binding import CredentialInjection
from app.upstream_credentials import (
    USE_OUTCOME_INJECTED,
    USE_OUTCOME_UNAVAILABLE,
    UpstreamCredentialUnavailableError,
    open_bound_credential,
    select_bound_credential,
)
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_log = structlog.get_logger(__name__)

__all__ = ["UpstreamCredentialUnavailableError", "record_credential_use", "resolve_upstream_injection"]

#: A toolset's credentials with their ciphertext (mirrors ``db.get_upstream_credential_bindings``).
_BINDINGS = """
    SELECT c.id::text AS id, c.server_url, c.kind, c.api_key_in, c.api_key_name,
           c.encrypted_secret, c.key_version
    FROM apiome.upstream_credentials c
    WHERE c.tenant_id = %s::uuid AND c.toolset_id = %s::uuid
"""

_RECORD_USE = """
    INSERT INTO apiome.upstream_credential_uses (tenant_id, credential_id, toolset_id, outcome)
    VALUES (%s::uuid, %s::uuid, %s::uuid, %s)
"""


async def record_credential_use(
    pool: AsyncConnectionPool, tenant_id: str, credential_id: str, toolset_id: str, outcome: str
) -> None:
    """Append one metadata-only ``upstream_credential_uses`` row (best-effort, never raises).

    Args:
        pool: The shared Postgres pool.
        tenant_id: Owning tenant.
        credential_id: The credential opened (or that failed to open).
        toolset_id: The toolset it was opened for.
        outcome: ``injected`` or ``unavailable``.
    """
    try:
        async with pool.connection() as conn:
            await conn.execute(_RECORD_USE, (tenant_id, credential_id, toolset_id, outcome))
            await conn.commit()
    except Exception:
        _log.warning(
            "upstream_credential_use_record_failed",
            credential_id=credential_id,
            toolset_id=toolset_id,
            outcome=outcome,
            exc_info=True,
        )


async def resolve_upstream_injection(
    pool: AsyncConnectionPool, tenant_id: str, toolset_id: str, request_url: str
) -> CredentialInjection | None:
    """Open the credential bound to ``request_url`` for this toolset, if there is one.

    Args:
        pool: The shared Postgres pool.
        tenant_id: The agent key's tenant.
        toolset_id: The agent key's toolset.
        request_url: The absolute URL about to be called.

    Returns:
        The injection to :meth:`~CredentialInjection.apply`, or ``None`` when no credential of the
        toolset is bound to the URL.

    Raises:
        UpstreamCredentialUnavailableError: A credential is bound but cannot be opened (no master
            key in this process, a blob that fails authentication, or a payload that does not fit
            its kind). The caller must not send the request.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_BINDINGS, (tenant_id, toolset_id))
            rows = await cur.fetchall()
    row = select_bound_credential(rows, request_url)
    if row is None:
        return None
    credential_id = str(row.get("id"))
    injection = open_bound_credential(row)
    if injection is None:
        await record_credential_use(pool, tenant_id, credential_id, toolset_id, USE_OUTCOME_UNAVAILABLE)
        raise UpstreamCredentialUnavailableError(credential_id)
    await record_credential_use(pool, tenant_id, credential_id, toolset_id, USE_OUTCOME_INJECTED)
    return injection
