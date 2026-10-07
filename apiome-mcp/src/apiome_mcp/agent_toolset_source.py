"""AGX-2.1 served toolset — what an agent key's toolset compiles to, with request bindings (#4533).

The agent runtime serves each key's toolset the way apiome-rest's ``/compiled`` view shows it
(:func:`app.agent_toolset_enrichment.compile_agent_toolset`): the version's canonical model,
rebuilt from its captured source, with accepted description enrichments (AGX-1.3) written in, compiled
by :func:`app.mcp_tool_mapping.compile_mcp_tools` over the toolset's enabled operations (AGX-1.2).
That is what makes the names here the names the key's allowlist holds, and the descriptions the ones
a reviewer accepted.

apiome-rest builds that view through its synchronous database layer. This module reads the same rows
through the MCP pool and calls the same pure steps
(:func:`app.catalog_conversion.build_conversion_source`,
:func:`app.agent_tool_enrichment.served_description_overrides`,
:func:`app.agent_tool_enrichment.apply_description_overrides`, ``compile_mcp_tools``).

**Cost.** Every request reads one small *manifest* row (target, slugs, enabled operation keys,
accepted descriptions). The compile — parsing the captured source — runs only when the manifest's
fingerprint changes, and is cached per toolset (:class:`ServedToolsetCache`). Enabling a tool,
accepting a description or switching target therefore applies on the next request, with no restart.

A toolset that cannot be served (missing, disabled, version unpublished, source unreadable, or no
longer compiling) resolves to ``None`` or raises :class:`ToolsetSourceUnavailableError`; the agent
surface turns both into ``agent_toolset_unavailable`` (fail closed).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

import structlog
from app.agent_tool_enrichment import apply_description_overrides, served_description_overrides
from app.canonical_model import CanonicalApi, Operation
from app.catalog_conversion import build_conversion_source
from app.import_source import ImportSourceError
from app.mcp_tool_mapping import McpToolDefinition, McpToolMappingError, compile_mcp_tools
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from apiome_mcp.agent_invocations import BodyCapturePolicy
from apiome_mcp.agent_request_builder import OperationBinding, OperationNotInvocableError, binding_for

_log = structlog.get_logger(__name__)

__all__ = [
    "DEFAULT_CACHE_SIZE",
    "ServedTool",
    "ServedToolset",
    "ServedToolsetCache",
    "ToolsetManifest",
    "ToolsetSourceUnavailableError",
    "compile_served_toolset",
    "load_served_toolset",
    "load_toolset_manifest",
]

#: Compiled toolsets kept per process.
DEFAULT_CACHE_SIZE = 256


class ToolsetSourceUnavailableError(RuntimeError):
    """The toolset exists and is enabled, but its version's source cannot be read or compiled."""


@dataclass(frozen=True)
class ToolsetManifest:
    """The per-request facts about one toolset: cheap to read, and the compile's cache key.

    Attributes:
        toolset_id: The toolset.
        tenant_id: Its tenant.
        version_id: The published version it exposes.
        target: ``agent_toolsets.target`` as stored (``prod`` / ``mock``).
        tenant_slug: The tenant slug (mock URL coordinate).
        project_slug: The project slug (mock URL coordinate).
        version_label: The version label (mock URL coordinate).
        exposed: Enabled operation keys, sorted.
        overrides: Accepted descriptions served to agents (``{target_key: text}``).
        body_capture: The toolset's AGX-3.3 body-capture opt-in.
    """

    toolset_id: str
    tenant_id: str
    version_id: str
    target: str
    tenant_slug: str
    project_slug: str
    version_label: str
    exposed: tuple[str, ...] = ()
    overrides: Mapping[str, str] = field(default_factory=dict)
    body_capture: BodyCapturePolicy = field(default_factory=BodyCapturePolicy)

    def fingerprint(self) -> str:
        """A digest of everything the compiled tools depend on (not target or capture)."""
        material = json.dumps(
            {"version": self.version_id, "exposed": list(self.exposed), "overrides": sorted(self.overrides.items())},
            separators=(",", ":"),
            sort_keys=True,
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ServedTool:
    """One tool as served, with what the proxy needs to call it.

    Attributes:
        definition: The compiled tool (name, description, input schema, output).
        binding: Where its arguments go (:func:`~apiome_mcp.agent_request_builder.binding_for`), or
            ``None`` when the operation has no HTTP binding (calling it is refused).
    """

    definition: McpToolDefinition
    binding: OperationBinding | None

    @property
    def name(self) -> str:
        """The tool name."""
        return self.definition.name


@dataclass(frozen=True)
class ServedToolset:
    """A compiled toolset, ready to list and call.

    Attributes:
        manifest: The manifest it was compiled for.
        api: The canonical model (servers for the ``prod`` base URL).
        tools: The tools by name, in compile order.
    """

    manifest: ToolsetManifest
    api: CanonicalApi
    tools: Mapping[str, ServedTool]

    def with_manifest(self, manifest: ToolsetManifest) -> ServedToolset:
        """The same compile under a newer manifest (target or capture changed, tools did not)."""
        return ServedToolset(manifest=manifest, api=self.api, tools=self.tools)


#: Everything the manifest needs in one round trip. No row: no such toolset in the tenant.
_MANIFEST = """
    SELECT ts.id::text AS toolset_id,
           ts.tenant_id::text AS tenant_id,
           ts.version_id::text AS version_id,
           ts.target,
           ts.body_capture_rate,
           ts.body_capture_until,
           t.slug AS tenant_slug,
           p.slug AS project_slug,
           v.version_id AS version_label,
           (ts.enabled AND v.published AND v.deleted_at IS NULL AND p.deleted_at IS NULL) AS available,
           COALESCE(
               (SELECT array_agg(tt.operation_key ORDER BY tt.operation_key)
                FROM apiome.agent_toolset_tools tt
                WHERE tt.toolset_id = ts.id AND tt.enabled),
               ARRAY[]::text[]
           ) AS exposed,
           CASE WHEN ts.description_enrichment THEN COALESCE(
               (SELECT jsonb_agg(jsonb_build_object(
                           'target_key', te.target_key,
                           'operation_key', te.operation_key,
                           'accepted_description', te.accepted_description)
                        ORDER BY te.target_key)
                FROM apiome.agent_toolset_enrichments te
                WHERE te.toolset_id = ts.id AND te.status = 'accepted'),
               '[]'::jsonb
           ) ELSE '[]'::jsonb END AS accepted
    FROM apiome.agent_toolsets ts
    JOIN apiome.versions v ON v.id = ts.version_id
    JOIN apiome.projects p ON p.id = v.project_id
    JOIN apiome.tenants t ON t.id = ts.tenant_id
    WHERE ts.id = %s::uuid AND ts.tenant_id = %s::uuid
"""

#: One revision's captured source, shaped like a catalog item row (mirrors
#: ``db.get_version_source_projection``).
_SOURCE = """
    SELECT v.project_id::text AS id, p.slug AS project_slug,
           v.version_id AS version_label,
           v.source_format, v.protocol, v.format_metadata,
           v.source_tool_versions AS tool_versions,
           p.metadata
    FROM apiome.versions v
    JOIN apiome.projects p ON v.project_id = p.id
    WHERE v.id = %s::uuid AND p.tenant_id = %s::uuid
      AND v.deleted_at IS NULL AND p.deleted_at IS NULL
"""


def _capture_policy(rate: Any, until: Any) -> BodyCapturePolicy:
    """The body-capture opt-in from its two columns (no capture when unreadable)."""
    value = float(rate) if isinstance(rate, (int, float, Decimal)) else 0.0
    return BodyCapturePolicy(rate=value, until=until if isinstance(until, datetime) else None)


def _accepted_rows(raw: Any) -> list[Mapping[str, Any]]:
    """The ``accepted`` JSONB aggregate as a list of rows (decoded or not)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    return [row for row in raw if isinstance(row, Mapping)] if isinstance(raw, list) else []


async def load_toolset_manifest(pool: AsyncConnectionPool, tenant_id: str, toolset_id: str) -> ToolsetManifest | None:
    """Read one toolset's manifest.

    Args:
        pool: The shared Postgres pool.
        tenant_id: The agent key's tenant (a toolset of another tenant is missing).
        toolset_id: The agent key's toolset.

    Returns:
        The manifest, or ``None`` when the toolset is missing, switched off, or its version is no
        longer published.
    """
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_MANIFEST, (toolset_id, tenant_id))
            row = await cur.fetchone()
    if row is None or not row.get("available"):
        return None
    exposed = tuple(str(key) for key in row.get("exposed") or [])
    return ToolsetManifest(
        toolset_id=str(row["toolset_id"]),
        tenant_id=str(row["tenant_id"]),
        version_id=str(row["version_id"]),
        target=str(row.get("target") or ""),
        tenant_slug=str(row.get("tenant_slug") or ""),
        project_slug=str(row.get("project_slug") or ""),
        version_label=str(row.get("version_label") or ""),
        exposed=exposed,
        overrides=served_description_overrides(_accepted_rows(row.get("accepted")), exposed),
        body_capture=_capture_policy(row.get("body_capture_rate"), row.get("body_capture_until")),
    )


def _operations_by_key(api: CanonicalApi) -> dict[str, Operation]:
    """Every operation of the model, by canonical key."""
    return {operation.key: operation for service in api.services for operation in service.operations}


def compile_served_toolset(manifest: ToolsetManifest, item: Mapping[str, Any]) -> ServedToolset:
    """Rebuild the version's model from its captured source and compile the served toolset.

    Pure (CPU only); :func:`load_served_toolset` runs it in a worker thread.

    Args:
        manifest: The toolset's manifest.
        item: The version's source projection (see ``_SOURCE``).

    Returns:
        The served toolset.

    Raises:
        ToolsetSourceUnavailableError: The source is missing or does not parse, or the enabled
            operations no longer compile (for example an operation key the source lost).
    """
    try:
        api = build_conversion_source(dict(item), source_version_id=manifest.version_id).api
        compiled = compile_mcp_tools(apply_description_overrides(api, manifest.overrides), exposed=manifest.exposed)
    except (ImportSourceError, McpToolMappingError) as exc:
        raise ToolsetSourceUnavailableError(str(exc)) from exc
    except Exception as exc:  # ConversionError and anything a parser raises: fail closed.
        raise ToolsetSourceUnavailableError(f"the version's source could not be compiled: {exc}") from exc
    operations = _operations_by_key(api)
    tools: dict[str, ServedTool] = {}
    for definition in compiled.tools:
        binding: OperationBinding | None
        try:
            binding = binding_for(api, operations[definition.operation])
        except (KeyError, OperationNotInvocableError):
            binding = None
        tools[definition.name] = ServedTool(definition=definition, binding=binding)
    return ServedToolset(manifest=manifest, api=api, tools=tools)


class ServedToolsetCache:
    """Compiled toolsets per process, keyed by toolset and checked against the manifest fingerprint."""

    def __init__(self, max_entries: int = DEFAULT_CACHE_SIZE) -> None:
        """Hold at most ``max_entries`` compiled toolsets (least recently used goes first)."""
        self._max = max(1, max_entries)
        self._entries: OrderedDict[str, tuple[str, ServedToolset]] = OrderedDict()

    def get(self, manifest: ToolsetManifest) -> ServedToolset | None:
        """The cached compile for ``manifest``'s toolset, if its fingerprint still matches."""
        entry = self._entries.get(manifest.toolset_id)
        if entry is None or entry[0] != manifest.fingerprint():
            return None
        self._entries.move_to_end(manifest.toolset_id)
        return entry[1].with_manifest(manifest)

    def put(self, served: ServedToolset) -> None:
        """Remember a compile."""
        key = served.manifest.toolset_id
        self._entries[key] = (served.manifest.fingerprint(), served)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """Forget every compile."""
        self._entries.clear()


async def load_served_toolset(
    pool: AsyncConnectionPool, cache: ServedToolsetCache, tenant_id: str, toolset_id: str
) -> ServedToolset | None:
    """The served toolset of an agent key, compiled at most once per manifest change.

    Args:
        pool: The shared Postgres pool.
        cache: The process's compile cache.
        tenant_id: The key's tenant.
        toolset_id: The key's toolset.

    Returns:
        The served toolset, or ``None`` when the toolset is missing, disabled or unpublished.

    Raises:
        ToolsetSourceUnavailableError: The version's source cannot be read or compiled.
    """
    manifest = await load_toolset_manifest(pool, tenant_id, toolset_id)
    if manifest is None:
        return None
    cached = cache.get(manifest)
    if cached is not None:
        return cached
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_SOURCE, (manifest.version_id, tenant_id))
            item = await cur.fetchone()
    if item is None:
        raise ToolsetSourceUnavailableError("the toolset's version has no readable source")
    served = await asyncio.to_thread(compile_served_toolset, manifest, item)
    cache.put(served)
    _log.info(
        "agent_toolset_compiled",
        toolset_id=toolset_id,
        tenant_id=tenant_id,
        tools=len(served.tools),
        fingerprint=manifest.fingerprint()[:12],
    )
    return served
