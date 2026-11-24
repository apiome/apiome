"""Read a version's broker binding for the producer — XPC-2.2 (#5736).

The binding is the row apiome-rest stores (XPC-2.1, V372 ``apiome.mock_broker_bindings``). The mock
reads it through its own async pool and opens the SASL credential with apiome-rest's vault
(:func:`app.mock_broker_bindings.open_credential`, magic ``OMBB``, key map
``APIOME_BROKER_CREDENTIAL_ENCRYPTION_KEYS``), so the two services can never disagree about how a
credential is sealed. The opened credential lives only in the
:class:`~apiome_mock.broker_adapter.BrokerConnection` handed to an adapter.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.mock_broker_bindings import open_credential
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.broker_adapter import BrokerConnection, BrokerCredential

__all__ = [
    "BindingUnavailableError",
    "BoundVersion",
    "connection_from_row",
    "list_bound_versions",
    "binding_state_key",
    "load_kafka_binding",
    "load_tick_state",
    "version_mock_enabled",
]

_BINDING_COLUMNS = """
    b.id::text AS id, b.protocol, b.bootstrap, b.tls_enabled, b.tls_verify, b.sasl_mechanism,
    b.credential_ciphertext, b.key_version, b.client_id_prefix, b.rotated_at
"""

_LOAD_BINDING = f"""
    SELECT {_BINDING_COLUMNS}
    FROM apiome.mock_broker_bindings b
    WHERE b.version_id = %(version_id)s AND b.protocol = 'kafka'
    LIMIT 1
"""

#: Published versions whose hosted mock is on and that have a Kafka binding: what the periodic
#: producer serves. A private draft mock is key-gated, so with no caller there is no key to serve
#: it with; it publishes on demand only (``POST …/__channels__/{channel}/publish`` with its key).
_LIST_BOUND_VERSIONS = """
    SELECT v.id AS version_id, t.slug AS tenant_slug, p.slug AS project_slug,
           v.version_id AS version_label, b.id::text AS binding_id, b.rotated_at, b.key_version
    FROM apiome.mock_broker_bindings b
    INNER JOIN apiome.versions v ON v.id = b.version_id AND v.deleted_at IS NULL
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE b.protocol = 'kafka'
      AND v.mock_enabled IS TRUE
      AND v.published IS TRUE
"""

_MOCK_ENABLED = """
    SELECT v.mock_enabled IS TRUE AND v.deleted_at IS NULL AS enabled
    FROM apiome.versions v WHERE v.id = %(version_id)s
"""


#: What the periodic producer reads once per tick (#7207, DBP-1.24): whether the mock is still on,
#: and the binding's *state* — no ciphertext. The adapter is rebuilt (and the full binding read)
#: only when that state differs from the adapter's.
_TICK_STATE = """
    SELECT (v.mock_enabled IS TRUE AND v.deleted_at IS NULL) AS enabled,
           b.id::text AS id, b.rotated_at, b.key_version, b.bootstrap, b.tls_enabled, b.tls_verify
    FROM apiome.versions v
    LEFT JOIN apiome.mock_broker_bindings b ON b.version_id = v.id AND b.protocol = 'kafka'
    WHERE v.id = %(version_id)s
"""


def binding_state_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """The binding fields that, when any changes, mean the adapter must be rebuilt.

    Accepts a full binding row or a :func:`load_tick_state` row (same column names).
    """
    return (
        str(row.get("id")),
        str(row.get("rotated_at") or ""),
        row.get("key_version"),
        tuple(row.get("bootstrap") or ()),
        bool(row.get("tls_enabled")),
        bool(row.get("tls_verify", True)),
    )


class BindingUnavailableError(RuntimeError):
    """The version has a SASL binding whose credential cannot be opened on this deployment."""


class BoundVersion(dict[str, Any]):
    """One row of :func:`list_bound_versions` (``version_id``, slugs, ``binding_id``, ...)."""

    @property
    def state_key(self) -> tuple[Any, ...]:
        """What, when it changes, means the version's producer must be rebuilt."""
        return (str(self["binding_id"]), str(self.get("rotated_at") or ""), self.get("key_version"))


def connection_from_row(row: dict[str, Any]) -> BrokerConnection:
    """Turn a binding row into a :class:`BrokerConnection`, opening its credential.

    Args:
        row: A ``mock_broker_bindings`` row with ``credential_ciphertext``.

    Returns:
        The connection; ``client_id`` is ``<client_id_prefix>-producer``.

    Raises:
        BindingUnavailableError: The row has a SASL mechanism but its credential won't open
            (fail closed: never connect without the credential the binding names).
    """
    credential = None
    if row.get("sasl_mechanism"):
        opened = open_credential(row)
        if opened is None:
            raise BindingUnavailableError(str(row.get("id")))
        credential = BrokerCredential(username=opened.username, password=opened.password)
    return BrokerConnection(
        binding_id=str(row.get("id")),
        protocol=str(row.get("protocol") or "kafka"),
        bootstrap=tuple(str(entry) for entry in row.get("bootstrap") or ()),
        tls_enabled=bool(row.get("tls_enabled")),
        tls_verify=bool(row.get("tls_verify", True)),
        sasl_mechanism=row.get("sasl_mechanism"),
        credential=credential,
        client_id=f"{row.get('client_id_prefix') or 'apiome-mock'}-producer",
    )


async def load_kafka_binding(pool: AsyncConnectionPool, version_id: UUID | str) -> dict[str, Any] | None:
    """Return the version's Kafka binding row (with ciphertext), or ``None`` when unbound."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_LOAD_BINDING, {"version_id": str(version_id)})
            row = await cur.fetchone()
    return dict(row) if row else None


async def list_bound_versions(pool: AsyncConnectionPool) -> list[BoundVersion]:
    """Return every mock-enabled version with a Kafka binding."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_LIST_BOUND_VERSIONS)
            rows = await cur.fetchall()
    return [BoundVersion(row) for row in rows]


async def load_tick_state(pool: AsyncConnectionPool, version_id: UUID | str) -> dict[str, Any] | None:
    """Return ``enabled`` plus the binding state columns (``id`` is ``None`` when unbound).

    Returns:
        The row, or ``None`` when the version no longer exists.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_TICK_STATE, {"version_id": str(version_id)})
            row = await cur.fetchone()
    return dict(row) if row else None


async def version_mock_enabled(pool: AsyncConnectionPool, version_id: UUID | str) -> bool:
    """Whether the version's mock is still on (checked before every periodic publish)."""
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_MOCK_ENABLED, {"version_id": str(version_id)})
            row = await cur.fetchone()
    return bool(row and row.get("enabled"))
