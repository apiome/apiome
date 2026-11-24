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

**Per-call cost (DBP-1.21 / #7204).** A toolset's credential rows are cached for
``agent_toolset_manifest_cache_seconds`` (:data:`BINDINGS_CACHE`), so a rotated or deleted credential
applies within that time. Only the *ciphertext* rows are cached: each call still opens (decrypts)
the one bound credential, so plaintext secrets never sit in a cache. The ``upstream_credential_uses``
row is queued for the batched audit writer instead of being awaited on the call path.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

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

from apiome_mcp.audit_writer import audit_writer_for
from apiome_mcp.settings import setting_or_default

_log = structlog.get_logger(__name__)

__all__ = [
    "BINDINGS_CACHE",
    "BindingsCache",
    "UpstreamCredentialUnavailableError",
    "record_credential_use",
    "resolve_upstream_injection",
]

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


class BindingsCache:
    """A toolset's credential rows (ciphertext only) for a few seconds, per (tenant, toolset)."""

    def __init__(
        self,
        *,
        ttl_seconds: Callable[[], float] | None = None,
        max_entries: int = 1024,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an empty cache.

        Args:
            ttl_seconds: Returns the current lifetime (default: the
                ``agent_toolset_manifest_cache_seconds`` setting). ``0`` turns caching off.
            max_entries: Most toolsets kept (least recently stored go first).
            clock: Monotonic clock (tests).
        """
        self._ttl = ttl_seconds or (lambda: setting_or_default("agent_toolset_manifest_cache_seconds", 5.0))
        self._max = max(1, max_entries)
        self._clock = clock
        self._entries: OrderedDict[tuple[str, str], tuple[float, list[dict[str, Any]]]] = OrderedDict()

    def get(self, tenant_id: str, toolset_id: str) -> list[dict[str, Any]] | None:
        """The live rows for a toolset, or ``None`` (missing, expired or caching off)."""
        if float(self._ttl()) <= 0:
            return None
        entry = self._entries.get((tenant_id, toolset_id))
        if entry is None or entry[0] <= self._clock():
            self._entries.pop((tenant_id, toolset_id), None)
            return None
        return entry[1]

    def put(self, tenant_id: str, toolset_id: str, rows: list[dict[str, Any]]) -> None:
        """Remember a toolset's rows (a no-op when caching is off)."""
        ttl = float(self._ttl())
        if ttl <= 0:
            return
        key = (tenant_id, toolset_id)
        self._entries.pop(key, None)
        self._entries[key] = (self._clock() + ttl, rows)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """Forget every toolset."""
        self._entries.clear()


#: The process's bindings cache.
BINDINGS_CACHE = BindingsCache()


async def record_credential_use(
    pool: AsyncConnectionPool, tenant_id: str, credential_id: str, toolset_id: str, outcome: str
) -> None:
    """Append one metadata-only ``upstream_credential_uses`` row (best-effort, never raises).

    With a batched audit writer registered for ``pool`` (the agent lifespan's) the row is only
    queued; otherwise it is written here.

    Args:
        pool: The shared Postgres pool.
        tenant_id: Owning tenant.
        credential_id: The credential opened (or that failed to open).
        toolset_id: The toolset it was opened for.
        outcome: ``injected`` or ``unavailable``.
    """
    writer = audit_writer_for(pool)
    if writer is not None:
        writer.submit("upstream_credential_uses", (tenant_id, credential_id, toolset_id, outcome, datetime.now(UTC)))
        return
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
    rows = BINDINGS_CACHE.get(tenant_id, toolset_id)
    if rows is None:
        async with pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(_BINDINGS, (tenant_id, toolset_id))
                rows = [dict(row) for row in await cur.fetchall()]
        BINDINGS_CACHE.put(tenant_id, toolset_id, rows)
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
