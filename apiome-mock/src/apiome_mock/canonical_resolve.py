"""Cached, single-flight resolution of compiled canonical specs (#7208, DBP-1.25).

The event, gRPC and GraphQL transports share this path. The caller checks access first (the access
row is cached on its own), then :func:`resolve_compiled_canonical` returns the compiled spec from
:class:`~apiome_mock.canonical_spec_cache.CanonicalSpecCache`: on a miss exactly one request loads
it (one statement), the connection goes back to the pool, and :func:`compile_canonical_spec` runs in
a worker thread; at TTL expiry one statement checks whether the version changed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from psycopg_pool import AsyncConnectionPool

from apiome_mock.api_key import ValidatedApiKey
from apiome_mock.canonical_compiler import CompiledCanonicalSpec, compile_canonical_spec
from apiome_mock.canonical_loader import LoadedCanonicalSpec, load_canonical_spec
from apiome_mock.canonical_spec_cache import CanonicalSpecCache
from apiome_mock.spec_loader import fetch_spec_stamp

CanonicalLoadFn = Callable[..., Awaitable[LoadedCanonicalSpec | None]]
"""Signature of :func:`~apiome_mock.canonical_loader.load_canonical_spec` (transports pass their
module-level reference so tests can patch it there)."""


async def resolve_compiled_canonical(
    pool: AsyncConnectionPool,
    cache: CanonicalSpecCache,
    *,
    tenant: str,
    project: str,
    version: str,
    api_key: ValidatedApiKey | None,
    access_row: Mapping[str, Any] | None = None,
    load: CanonicalLoadFn = load_canonical_spec,
    on_loaded: Callable[[CompiledCanonicalSpec], None] | None = None,
) -> CompiledCanonicalSpec | None:
    """Return the compiled canonical spec of a version the caller may already access.

    Args:
        pool: Database pool.
        cache: Compiled canonical spec cache.
        tenant: Tenant slug.
        project: Project slug.
        version: Version label.
        api_key: The caller's validated key (a private draft needs one).
        access_row: The access row the caller already fetched, handed to the loader.
        load: The canonical loader.
        on_loaded: Called with a freshly compiled spec (not on cache hits or revalidations).

    Returns:
        The compiled spec, or ``None`` when the version has no mockable canonical model.

    Raises:
        ValueError: The model could not be compiled (for example an unbuildable GraphQL schema);
            nothing is cached, and every waiter of the same load sees the error.
    """

    async def _load() -> CompiledCanonicalSpec | None:
        loaded = await load(
            pool, tenant=tenant, project=project, version=version, api_key=api_key, access_row=access_row
        )
        if loaded is None:
            return None
        compiled = await asyncio.to_thread(compile_canonical_spec, loaded)
        if on_loaded is not None:
            on_loaded(compiled)
        return compiled

    return await cache.get_or_load(
        tenant,
        project,
        version,
        load=_load,
        revalidate=lambda: fetch_spec_stamp(pool, tenant=tenant, project=project, version=version),
    )
