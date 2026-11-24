"""Load and compile OpenAPI specs from Postgres (apiome-mcp read path).

A load (#7208, DBP-1.25) is a constant number of statements on one pooled connection: the resolve
query plus apiome-mcp's set-based loader (:func:`~apiome_mcp.spec_openapi_loaders.load_openapi_inputs`,
at most 11 statements whatever the size of the spec; component pins included, so the generator never
opens a connection of its own). The connection is returned to the pool before the document is
generated and the routing table extracted, and that CPU work runs in a worker thread, off the
event loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Mapping, NamedTuple
from uuid import UUID

from apiome_mcp.spec_openapi_loaders import OpenApiInputs, load_openapi_inputs
from app.mock_routing import MockOperation, extract_operations
from app.openapi_generator import generate_openapi_spec
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mock.api_key import ValidatedApiKey, is_private_mock_mode
from apiome_mock.callbacks import CallbackDefinition, parse_callbacks
from apiome_mock.capture import RuntimeCapturePolicy, parse_capture_policy
from apiome_mock.chaos import EMPTY_CHAOS, ChaosConfig, parse_chaos
from apiome_mock.correlation import (
    EMPTY_CORRELATION,
    CorrelationConfig,
    parse_response_correlation,
)
from apiome_mock.fixture_packs import FixturePack, merged_template_data, parse_fixture_packs
from apiome_mock.scenarios import Scenario, parse_active_scenario, parse_scenarios
from apiome_mock.ttl_cache import TtlCache

MockAccessStatus = Literal["ok", "disabled", "missing"]

#: The access decision's inputs, and nothing else (#7207, DBP-1.24): the mode is read out of
#: ``mock_settings`` in SQL instead of shipping the whole JSONB (scenarios, fixtures, callbacks, …),
#: and "is a public spec" is the ``mcp_v_public_specs`` predicate written inline rather than a join
#: of the view (``v.deleted_at`` / ``p.deleted_at`` are already filtered by the joins below).
_RESOLVE_MOCK_ACCESS = """
    SELECT
      v.mock_enabled,
      v.published,
      v.mock_settings->>'mode' AS mock_mode,
      v.source_format,
      (
        v.published IS TRUE
        AND v.enabled IS TRUE
        AND p.enabled IS TRUE
        AND v.visibility = 'public'::apiome.visibility_type
      ) AS is_public_spec
    FROM apiome.versions v
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE t.slug = %(tenant)s
      AND p.slug = %(project)s
      AND v.version_id = %(version)s
      AND v.deleted_at IS NULL
    LIMIT 1
"""

#: What a compiled spec is stamped with, and what revalidation compares (#7208, DBP-1.25):
#: ``versions.content_stamp`` (bumped by any write to the revision's rows or content columns,
#: ``mock_settings`` included) and the ``GREATEST`` of the version's, project's and newest tag's
#: ``updated_at`` — the ``updated_at`` of ``mcp_v_public_specs`` for a published spec, the same
#: expression for a draft. Needs the ``v`` and ``p`` aliases.
FRESHNESS_COLUMNS = """
      v.content_stamp,
      GREATEST(
        v.updated_at,
        p.updated_at,
        COALESCE(
          (SELECT max(vt.updated_at) FROM apiome.version_tags vt
            WHERE vt.version_id = v.id AND vt.project_id = v.project_id),
          '-infinity'::timestamptz
        )
      ) AS stamp_updated_at
"""

#: One statement: the freshness stamp of a mock-enabled version, read when a cached entry expires.
SPEC_STAMP_QUERY = f"""
    SELECT
      v.id,
      {FRESHNESS_COLUMNS}
    FROM apiome.versions v
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE t.slug = %(tenant)s
      AND p.slug = %(project)s
      AND v.version_id = %(version)s
      AND v.deleted_at IS NULL
      AND v.mock_enabled IS TRUE
    LIMIT 1
"""

_RESOLVE_PUBLISHED_SPEC = f"""
    SELECT
      s.id,
      s.updated_at,
      {FRESHNESS_COLUMNS},
      t.slug AS tenant_slug,
      p.slug AS project_slug,
      v.version_id AS version_label,
      p.description AS project_description,
      v.metadata,
      v.mock_settings
    FROM apiome.mcp_v_public_specs s
    INNER JOIN apiome.versions v ON v.id = s.id AND v.deleted_at IS NULL
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE t.slug = %(tenant)s
      AND p.slug = %(project)s
      AND v.version_id = %(version)s
      AND v.mock_enabled IS TRUE
    LIMIT 1
"""

_RESOLVE_DRAFT_SPEC = f"""
    SELECT
      v.id,
      v.updated_at,
      {FRESHNESS_COLUMNS},
      t.slug AS tenant_slug,
      p.slug AS project_slug,
      v.version_id AS version_label,
      p.description AS project_description,
      v.metadata,
      v.mock_settings
    FROM apiome.versions v
    INNER JOIN apiome.projects p ON p.id = v.project_id AND p.deleted_at IS NULL
    INNER JOIN apiome.tenants t ON t.id = p.tenant_id AND t.deleted_at IS NULL AND t.enabled IS TRUE
    WHERE t.slug = %(tenant)s
      AND p.slug = %(project)s
      AND v.version_id = %(version)s
      AND v.deleted_at IS NULL
      AND v.published IS FALSE
      AND v.mock_enabled IS TRUE
      AND COALESCE(v.mock_settings->>'mode', '') = 'private'
    LIMIT 1
"""


def _project_description(row: dict[str, Any]) -> str | None:
    description = row.get("project_description")
    if description is None:
        return None
    text = str(description).strip()
    return text if text else None


class SpecStamp(NamedTuple):
    """A version's freshness stamp: equal stamps mean the compiled spec is still current."""

    revision_id: UUID
    content_stamp: int
    updated_at: datetime


def spec_stamp_from_row(row: Mapping[str, Any], *, id_column: str = "id") -> SpecStamp | None:
    """Build the stamp from a row carrying the revision id and the ``FRESHNESS_COLUMNS``.

    Args:
        row: Resolve-query or stamp-query row.
        id_column: The column holding ``versions.id``.

    Returns:
        The stamp, or ``None`` when the row lacks the columns (an entry with no stamp is reloaded
        at expiry rather than revalidated).
    """
    revision_id = row.get(id_column)
    content_stamp = row.get("content_stamp")
    updated_at = row.get("stamp_updated_at")
    if revision_id is None or content_stamp is None or not isinstance(updated_at, datetime):
        return None
    return SpecStamp(revision_id=revision_id, content_stamp=int(content_stamp), updated_at=updated_at)


async def fetch_spec_stamp(
    pool: AsyncConnectionPool,
    *,
    tenant: str,
    project: str,
    version: str,
) -> SpecStamp | None:
    """Read a version's current freshness stamp (one statement) for cache revalidation.

    Args:
        pool: Database pool.
        tenant: Tenant slug.
        project: Project slug.
        version: Version label.

    Returns:
        The stamp, or ``None`` when no live, mock-enabled version has these coordinates.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(SPEC_STAMP_QUERY, {"tenant": tenant, "project": project, "version": version})
            row = await cur.fetchone()
    return spec_stamp_from_row(row) if row is not None else None


@dataclass(frozen=True)
class CompiledSpec:
    """Routing table compiled from an OpenAPI document."""

    revision_id: UUID
    tenant_slug: str
    project_slug: str
    version_label: str
    updated_at: datetime
    spec: dict[str, Any]
    operations: tuple[MockOperation, ...]
    scenarios: Mapping[str, Scenario] = field(default_factory=dict)
    """Scenario overrides parsed from ``versions.mock_settings`` (#4454, SIM-4.2)."""
    active_scenario: str | None = None
    """The version's stored default scenario, applied when a request sends no
    ``X-Mock-Scenario`` header (#5531, MSC-2.1). A name that no longer resolves is ignored with a
    warning at serve time, never an error."""
    chaos: ChaosConfig = EMPTY_CHAOS
    """Version-level chaos knobs parsed from ``versions.mock_settings`` (#4455, SIM-4.3)."""
    fixtures: Mapping[str, Any] = field(default_factory=dict)
    """Fixture data readable by response templates (#4744, PMR-2.1)."""
    fixture_packs: Mapping[str, FixturePack] = field(default_factory=dict)
    """Versioned fixture packs sessions can reset to (#4745, PMR-2.2)."""
    callbacks: Mapping[str, CallbackDefinition] = field(default_factory=dict)
    """Outbound callback/webhook definitions this version simulates (#4746, PMR-2.3)."""
    correlation: CorrelationConfig = EMPTY_CORRELATION
    """Request-correlation settings parsed from ``versions.mock_settings`` (#5527, MSC-1.1)."""
    capture_policy: RuntimeCapturePolicy | None = None
    """The version's guarded proxy capture grant, when one is stored (#4747, PMR-2.4).

    Hosted-only: ``proxyCapture`` is not a bundled settings key, so a spec compiled from a portable
    bundle always leaves this ``None`` and the portable runtime can never proxy or record.
    """
    freshness: SpecStamp | None = None
    """The stamp the spec was compiled from (#7208, DBP-1.25); the cache revalidates against it.
    ``None`` (portable bundles, tests) means an expired entry is reloaded."""

    @property
    def cache_key(self) -> tuple[str, str, str]:
        return (self.tenant_slug, self.project_slug, self.version_label)


DEFAULT_ACCESS_CACHE_TTL_SECONDS = 5.0
"""Access-decision TTL until :func:`configure_access_cache` runs at startup."""

_ACCESS_CACHE: TtlCache[dict[str, Any]] = TtlCache(ttl_seconds=DEFAULT_ACCESS_CACHE_TTL_SECONDS)
"""Access rows by ``(tenant, project, version)``; ``None`` entries remember missing versions."""


def configure_access_cache(ttl_seconds: float) -> None:
    """Set the access-decision TTL (``APIOME_MOCK_ACCESS_CACHE_TTL_SECONDS``) and empty the cache."""
    _ACCESS_CACHE.ttl_seconds = ttl_seconds
    _ACCESS_CACHE.negative_ttl_seconds = ttl_seconds
    _ACCESS_CACHE.clear()


def invalidate_access(tenant: str, project: str, version: str) -> None:
    """Forget one version's cached access decision (publish / settings NOTIFY)."""
    _ACCESS_CACHE.invalidate((tenant, project, version))


def clear_access_cache() -> None:
    """Forget every cached access decision (NOTIFY listener reconnect, tests)."""
    _ACCESS_CACHE.clear()


async def _query_access_row(
    pool: AsyncConnectionPool,
    *,
    tenant: str,
    project: str,
    version: str,
) -> dict[str, Any] | None:
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                _RESOLVE_MOCK_ACCESS,
                {"tenant": tenant, "project": project, "version": version},
            )
            row = await cur.fetchone()
    return dict(row) if row is not None else None


async def _fetch_access_row(
    pool: AsyncConnectionPool,
    *,
    tenant: str,
    project: str,
    version: str,
) -> dict[str, Any] | None:
    """Return the version's access row, from the access cache when it is fresh.

    The row does not depend on the caller's API key (the key is checked against it per request in
    :func:`access_status_from_row`), so one cached row serves every caller of a version. A missing
    version is cached as well, so repeated 404s do not repeat the query.

    Args:
        pool: Database pool used on a miss.
        tenant: Tenant slug.
        project: Project slug.
        version: Version label.

    Returns:
        ``mock_enabled``, ``published``, ``mock_mode``, ``source_format``, ``is_public_spec``, or
        ``None`` when the coordinates name no live version.
    """
    return await _ACCESS_CACHE.get_or_load(
        (tenant, project, version),
        lambda: _query_access_row(pool, tenant=tenant, project=project, version=version),
    )


def row_is_private_mode(row: Mapping[str, Any]) -> bool:
    """True when an unpublished access row is configured as a key-gated draft mock.

    Accepts the narrow ``mock_mode`` column, and the full ``mock_settings`` document older callers
    (and tests) still hand over.
    """
    if "mock_mode" in row:
        return row.get("mock_mode") == "private"
    return is_private_mock_mode(row.get("mock_settings"), published=False)


def access_status_from_row(
    row: Mapping[str, Any] | None,
    *,
    tenant: str,
    api_key: ValidatedApiKey | None,
) -> MockAccessStatus:
    """Decide whether a version's mock may be served to this caller.

    Args:
        row: The access row (``None`` when the version does not exist).
        tenant: Tenant slug from the URL.
        api_key: The caller's validated key, if any.

    Returns:
        ``ok``, ``disabled`` (mock switched off), or ``missing`` (not found, not public, or a
        private draft without a key of its tenant).
    """
    if row is None:
        return "missing"
    if not row.get("mock_enabled"):
        return "disabled"
    if bool(row.get("published")):
        return "ok" if row.get("is_public_spec") else "missing"
    if not row_is_private_mode(row):
        return "missing"
    if api_key is None or api_key.tenant_slug != tenant:
        return "missing"
    return "ok"


async def get_mock_access_status(
    pool: AsyncConnectionPool,
    *,
    tenant: str,
    project: str,
    version: str,
    api_key: ValidatedApiKey | None = None,
) -> MockAccessStatus:
    """Return whether mock serving is allowed for the slug coordinates (cached access row)."""
    row = await _fetch_access_row(pool, tenant=tenant, project=project, version=version)
    return access_status_from_row(row, tenant=tenant, api_key=api_key)


async def _read_spec_inputs(
    conn: Any,
    query: str,
    *,
    tenant: str,
    project: str,
    version: str,
) -> tuple[dict[str, Any], OpenApiInputs] | None:
    """Run the resolve query and the batched input loader on one connection.

    Returns:
        ``(row, inputs)``, or ``None`` when the resolve query matched nothing.
    """
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, {"tenant": tenant, "project": project, "version": version})
        row = await cur.fetchone()
    if row is None:
        return None
    inputs = await load_openapi_inputs(conn, row["id"], part="document")
    return dict(row), inputs


def compile_spec(
    row: Mapping[str, Any],
    inputs: OpenApiInputs,
    *,
    mock_settings: Any = None,
) -> CompiledSpec:
    """Generate the OpenAPI document and the routing table (CPU only: no I/O, no connection).

    Args:
        row: The resolve-query row (slugs, metadata, ``updated_at``, freshness columns).
        inputs: The rows the document is generated from, component pins included.
        mock_settings: The version's ``mock_settings`` (scenarios, chaos, fixtures, ...).

    Returns:
        The compiled spec.
    """
    revision_id = row["id"]
    spec = generate_openapi_spec(
        str(row["tenant_slug"]),
        str(row["project_slug"]),
        str(row["version_label"]),
        project_description=_project_description(dict(row)),
        version_db_id=str(revision_id),
        revision_metadata=row.get("metadata"),
        **inputs.generator_kwargs(),
    )
    operations = tuple(extract_operations(spec))
    updated_at = row["updated_at"]
    if not isinstance(updated_at, datetime):
        raise TypeError("expected versions.updated_at to be a datetime")

    fixture_packs = parse_fixture_packs(mock_settings)
    return CompiledSpec(
        revision_id=revision_id,
        tenant_slug=str(row["tenant_slug"]),
        project_slug=str(row["project_slug"]),
        version_label=str(row["version_label"]),
        updated_at=updated_at,
        spec=spec,
        operations=operations,
        scenarios=parse_scenarios(mock_settings),
        active_scenario=parse_active_scenario(mock_settings),
        chaos=parse_chaos(mock_settings),
        # Fixture packs are the one hosted source of template data (#4745, PMR-2.2).
        fixtures=merged_template_data(fixture_packs),
        fixture_packs=fixture_packs,
        callbacks=parse_callbacks(mock_settings),
        correlation=parse_response_correlation(mock_settings),
        capture_policy=parse_capture_policy(mock_settings),
        freshness=spec_stamp_from_row(row),
    )


async def load_compiled_spec(
    pool: AsyncConnectionPool,
    *,
    tenant: str,
    project: str,
    version: str,
    api_key: ValidatedApiKey | None = None,
    access_row: Mapping[str, Any] | None = None,
) -> CompiledSpec | None:
    """Resolve a spec by slug coordinates and compile its routing table.

    One pooled connection is held for the reads only (resolve + at most 11 loader statements); it
    is back in the pool before :func:`compile_spec` runs, in a worker thread.

    Args:
        pool: Database pool.
        tenant: Tenant slug.
        project: Project slug.
        version: Version label.
        api_key: The caller's validated key (required for a private draft).
        access_row: The access row the caller already fetched; read from the access cache when
            omitted.

    Returns:
        The compiled spec, or ``None`` when the version is not mockable for this caller.
    """
    if access_row is None:
        access_row = await _fetch_access_row(pool, tenant=tenant, project=project, version=version)
    if access_row is None or not access_row.get("mock_enabled"):
        return None

    published = bool(access_row.get("published"))
    if published:
        query = _RESOLVE_PUBLISHED_SPEC
    else:
        if api_key is None or not row_is_private_mode(access_row):
            return None
        query = _RESOLVE_DRAFT_SPEC

    async with pool.connection() as conn:
        read = await _read_spec_inputs(conn, query, tenant=tenant, project=project, version=version)
    if read is None:
        return None
    row, inputs = read
    mock_settings = row.get("mock_settings", access_row.get("mock_settings"))
    return await asyncio.to_thread(compile_spec, row, inputs, mock_settings=mock_settings)
