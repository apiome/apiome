"""Factory for session store backends (#4453)."""

from __future__ import annotations

from psycopg_pool import AsyncConnectionPool

from apiome_mock.memory_session_store import InMemorySessionStore
from apiome_mock.postgres_session_store import PostgresSessionStore
from apiome_mock.session_store import SessionCaps, SessionStore
from apiome_mock.settings import Settings


def session_caps_from_settings(settings: Settings) -> SessionCaps:
    return SessionCaps(
        ttl_seconds=settings.session_ttl_seconds,
        max_resources=settings.session_max_resources,
        max_bytes=settings.session_max_bytes,
        max_sessions=settings.session_max_sessions,
    )


def create_session_store(
    settings: Settings,
    pool: AsyncConnectionPool,
) -> SessionStore:
    """Build the configured session store backend."""
    caps = session_caps_from_settings(settings)
    if settings.session_store_backend == "postgres":
        return PostgresSessionStore(pool, caps)
    return InMemorySessionStore(caps)
