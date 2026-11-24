"""Compiled canonical (event / gRPC / GraphQL) spec cache (#7208, DBP-1.25)."""

from __future__ import annotations

import time
from collections.abc import Hashable
from typing import TYPE_CHECKING, Callable

from apiome_mock.revalidating_cache import RevalidatingSpecCache

if TYPE_CHECKING:
    from apiome_mock.canonical_compiler import CompiledCanonicalSpec


def _canonical_spec_stamp(compiled: CompiledCanonicalSpec) -> Hashable | None:
    return compiled.loaded.freshness


class CanonicalSpecCache(RevalidatingSpecCache["CompiledCanonicalSpec"]):
    """LRU of :class:`CompiledCanonicalSpec` by ``(tenant, project, version)``.

    See :class:`~apiome_mock.revalidating_cache.RevalidatingSpecCache`: concurrent misses share one
    load, and an expired entry whose ``freshness`` stamp is unchanged is kept rather than reloaded.
    """

    def __init__(self, *, max_entries: int, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(
            max_entries=max_entries,
            ttl_seconds=ttl_seconds,
            stamp_of=_canonical_spec_stamp,
            event_prefix="canonical_spec_cache",
            clock=clock,
        )
