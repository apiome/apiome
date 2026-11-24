"""Session-scoped stateful mock store protocol (#4453, SIM-4.1)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

MOCK_SESSION_HEADER = "X-Mock-Session"

SeedCollections = Mapping[str, Sequence[tuple[str, dict[str, Any]]]]
"""Seed state for one session: ordered ``(resource_id, resource)`` pairs per collection path
(#4745, PMR-2.2). This is the shape ``FixturePack.collections`` carries."""

CreateBuilder = Callable[[int], tuple[str, dict[str, Any]]]
"""Builds a new resource from the integer id the store allocated: returns ``(resource_id, resource)``.

The builder may ignore the allocated id (a client-supplied id wins); it runs inside the store's
write, so it must be quick and must not touch the store (#7209, DBP-1.26)."""

UpdateBuilder = Callable[[dict[str, Any] | None], dict[str, Any]]
"""Builds the resource to store from the current one (``None`` when it does not exist yet).

Runs inside the store's write, like :data:`CreateBuilder` (#7209, DBP-1.26)."""


@dataclass(frozen=True)
class SessionKey:
    """Namespace for one mock session."""

    tenant: str
    project: str
    version: str
    session_token: str


@dataclass(frozen=True)
class SessionCaps:
    """Abuse limits for a single session and process-wide session count."""

    ttl_seconds: float
    max_resources: int
    max_bytes: int
    max_sessions: int


class SessionStoreError(Exception):
    """Base error for session store operations."""


class SessionCapacityError(SessionStoreError):
    """Raised when a write would exceed configured session caps."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


def resource_byte_size(resource: dict[str, Any]) -> int:
    """Return UTF-8 JSON byte length used for per-session size accounting."""
    return len(json.dumps(resource, separators=(",", ":"), default=str).encode("utf-8"))


@runtime_checkable
class SessionStore(Protocol):
    """CRUD memory for one mock session namespace."""

    async def list_resources(
        self,
        key: SessionKey,
        collection_path: str,
    ) -> list[dict[str, Any]]:
        """Return all resources in ``collection_path`` (empty if none / expired)."""

    async def get_resource(
        self,
        key: SessionKey,
        collection_path: str,
        resource_id: str,
    ) -> dict[str, Any] | None:
        """Return one resource or ``None`` when missing / expired."""

    async def put_resource(
        self,
        key: SessionKey,
        collection_path: str,
        resource_id: str,
        resource: dict[str, Any],
        *,
        replace: bool,
    ) -> dict[str, Any]:
        """Create or replace a resource; raise ``SessionCapacityError`` on caps."""

    async def delete_resource(
        self,
        key: SessionKey,
        collection_path: str,
        resource_id: str,
    ) -> bool:
        """Delete a resource; return whether it existed."""

    async def create_resource(
        self,
        key: SessionKey,
        collection_path: str,
        build: CreateBuilder,
    ) -> dict[str, Any]:
        """Allocate the next integer id and store the resource ``build`` returns, in one step.

        Concurrent creates in one collection get distinct allocated ids (#7209, DBP-1.26).

        Args:
            key: The session namespace.
            collection_path: The collection the resource goes into.
            build: Called once with the allocated id; returns ``(resource_id, resource)``.

        Returns:
            The stored resource.

        Raises:
            SessionCapacityError: The write would exceed a session cap.
        """

    async def update_resource(
        self,
        key: SessionKey,
        collection_path: str,
        resource_id: str,
        build: UpdateBuilder,
    ) -> dict[str, Any]:
        """Read the current resource, store what ``build`` returns from it, in one step (#7209).

        Args:
            key: The session namespace.
            collection_path: The collection of the resource.
            resource_id: The resource's id.
            build: Called once with the current resource (``None`` when missing).

        Returns:
            The stored resource.

        Raises:
            SessionCapacityError: The write would exceed a session cap.
        """

    async def next_integer_id(
        self,
        key: SessionKey,
        collection_path: str,
    ) -> int:
        """Allocate a monotonic integer id for ``collection_path`` within the session.

        The allocation is persisted: the next call returns a higher number (sequence scenarios
        count calls with it), and it is never lower than one past the highest numeric
        ``resource_id`` stored in the collection.
        """

    async def replace_session(
        self,
        key: SessionKey,
        collections: SeedCollections,
    ) -> tuple[int, int]:
        """Atomically replace the session's entire state with ``collections`` (#4745, PMR-2.2).

        Everything previously stored under ``key`` — resources *and* id/sequence counters — is
        discarded and the seed resources become the session's only state, in one step: on any
        failure (including ``SessionCapacityError``) the previous state is left untouched.
        Passing an empty mapping resets the session to nothing (and frees its session slot).

        Only ``key``'s own namespace is affected; state under any other tenant, project,
        version, or session token is never read or written.

        Returns:
            ``(resource_count, total_bytes)`` of the state now stored.

        Raises:
            SessionCapacityError: The seed exceeds resource/byte caps, or a brand-new session
                would exceed the process session cap.
        """
