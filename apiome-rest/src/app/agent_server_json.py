"""Registry ``server.json`` export for the agent runtime — AAU-5.1 (#5722).

Hosts, gateways and registries exchange MCP servers as ``server.json`` documents (the MCP Registry
schema vendored in ``data/mcp_registry_v0_1_schema.json``, ``ServerDetail``). This module describes
Apiome's own agent runtime (apiome-mcp's ``/agent/mcp``) in that shape:

* :func:`build_toolset_server_json` — one toolset as one server: its compiled tools
  (:func:`app.agent_toolset_enrichment.compile_agent_toolset`), the runtime's public URL as a
  ``streamable-http`` remote, an auth hint, the published version label, and a ``digest``.
* :func:`build_tenant_server_json` — the tenant's runtime as one remote: every **enabled** toolset
  as an entry of ``_meta["dev.apiome/agent-runtime"].toolsets`` (the schema has no per-server
  sub-entries, so they live in the vendor ``_meta`` block), with a digest over all of them.

Design rules:

* **The digest is the catalog's surface fingerprint.** Each toolset document embeds the MCP
  manifest of its compiled tools under ``_meta["dev.apiome/agent-runtime"].manifest``; ``digest`` is
  :meth:`~app.mcp_client.normalize.DiscoverySurface.fingerprint` of that manifest — the
  ``surface_fingerprint`` (registry ``manifestDigest``) the catalog and trust engine key on.
  Importing the export through the MCP manifest importer
  (:func:`app.mcp_manifest_parser.embedded_server_json_manifest`) therefore yields a catalog entry
  with the same tools *and* the same fingerprint. Curation (enabling a tool, accepting a
  description) changes the tools and so the digest; nothing else does.
* **Byte-stable.** No timestamps or request data enter the document; tools keep the compiler's
  canonical order and toolsets are ordered by id, so the same curation always yields the same JSON.
* **Never carries a secret.** The auth hint names the header and a ``{agent_key}`` placeholder;
  the runtime URL is passed through :func:`app.mcp_registry.remote_url`, which drops userinfo,
  query and fragment.

The pure builders take everything as arguments; :func:`export_toolset_server_json` and
:func:`export_tenant_server_json` read the toolsets and settings and call them.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .agent_toolset_enrichment import CompiledToolsetOut, compile_agent_toolset
from .agent_toolsets import AgentToolsetError, AgentToolsetOut, get_agent_toolset, list_agent_toolsets
from .config import settings
from .database import db
from .mcp_client.handshake import ServerInfo
from .mcp_manifest_parser import AGENT_RUNTIME_META_KEY, McpManifestDocument, manifest_surface
from .mcp_registry import OFFICIAL_META_KEY, SERVER_SCHEMA_URL, _clip, remote_url, tenant_namespace

logger = logging.getLogger(__name__)

__all__ = [
    "AGENT_KEY_VARIABLE",
    "AGENT_RUNTIME_META_KEY",
    "AUTH_AGENT_KEY",
    "AUTH_OAUTH",
    "CODE_RUNTIME_URL_INVALID",
    "MANIFEST_PROTOCOL_VERSION",
    "SERVER_JSON_SCHEMA_VERSION",
    "auth_hint",
    "build_tenant_server_json",
    "build_toolset_server_json",
    "export_tenant_server_json",
    "export_toolset_server_json",
    "runtime_server_name",
    "runtime_server_response",
    "toolset_manifest",
    "toolset_server_name",
]

#: Shape of the ``_meta["dev.apiome/agent-runtime"]`` block.
SERVER_JSON_SCHEMA_VERSION = "aau.server-json.v1"

#: The protocol revision the embedded manifest declares: the newest one ``/agent/mcp`` serves
#: (``apiome_mcp.protocol_versions.SERVED_PROTOCOL_VERSIONS[0]``).
MANIFEST_PROTOCOL_VERSION = "2026-07-28"

#: Auth hint schemes: an OAuth bearer discovered through Protected Resource Metadata (AAU-1.1), or
#: an Apiome agent key sent as ``Authorization: Bearer`` when OAuth is unavailable.
AUTH_OAUTH = "oauth"
AUTH_AGENT_KEY = "agent-key"

#: The ``{placeholder}`` of the agent-key header value (a ``KeyValueInput`` variable).
AGENT_KEY_VARIABLE = "agent_key"

#: Refusal code when ``agent_mcp_public_url`` is not an ``http(s)`` URL.
CODE_RUNTIME_URL_INVALID = "agent-runtime-url-invalid"

#: The registry server name of the tenant-wide runtime entry, after the tenant namespace.
_TENANT_RUNTIME_SLUG = "agent-runtime"


def toolset_server_name(tenant_slug: str, toolset_id: str) -> str:
    """Return the registry name of one toolset's server (``apiome.<tenant>/agent-toolset-<id>``).

    Args:
        tenant_slug: The owning tenant's slug.
        toolset_id: The toolset id (a UUID, so the name matches the schema pattern).

    Returns:
        The ``namespace/name`` server name.
    """
    return f"{tenant_namespace(tenant_slug)}/agent-toolset-{toolset_id}"


def runtime_server_name(tenant_slug: str) -> str:
    """Return the registry name of the tenant-wide runtime server (``apiome.<tenant>/agent-runtime``).

    Args:
        tenant_slug: The tenant's slug.

    Returns:
        The ``namespace/name`` server name.
    """
    return f"{tenant_namespace(tenant_slug)}/{_TENANT_RUNTIME_SLUG}"


def auth_hint(prm_url: Optional[str]) -> Dict[str, Any]:
    """Describe how a client authenticates to the runtime.

    Args:
        prm_url: The runtime's Protected Resource Metadata URL, or empty/``None`` when OAuth is
            unavailable.

    Returns:
        ``{"scheme": "oauth", "protectedResourceMetadata": <url>}`` when a PRM URL is configured,
        else ``{"scheme": "agent-key", "header": "Authorization", "format": "Bearer <agent key>"}``.
    """
    url = (prm_url or "").strip()
    if url:
        return {"scheme": AUTH_OAUTH, "protectedResourceMetadata": url}
    return {"scheme": AUTH_AGENT_KEY, "header": "Authorization", "format": "Bearer <agent key>"}


def _remote(runtime_url: str, auth: Mapping[str, Any]) -> Dict[str, Any]:
    """The ``streamable-http`` remote; an agent-key hint also declares the secret header."""
    remote: Dict[str, Any] = {"type": "streamable-http", "url": runtime_url}
    if auth.get("scheme") == AUTH_AGENT_KEY:
        remote["headers"] = [
            {
                "name": "Authorization",
                "description": "An Apiome agent key bound to this toolset.",
                "value": "Bearer {" + AGENT_KEY_VARIABLE + "}",
                "isRequired": True,
                "isSecret": True,
                "variables": {
                    AGENT_KEY_VARIABLE: {
                        "description": "The agent key (Workspace → Agent Access → Agent keys).",
                        "isRequired": True,
                        "isSecret": True,
                    }
                },
            }
        ]
    return remote


def toolset_manifest(
    compiled: CompiledToolsetOut, *, name: str, title: str, version: str
) -> Dict[str, Any]:
    """Build the MCP manifest of a compiled toolset (the shape the manifest importer reads).

    Args:
        compiled: The compiled toolset.
        name: ``serverInfo.name`` (the registry server name).
        title: ``serverInfo.title``.
        version: ``serverInfo.version`` (the published version label).

    Returns:
        ``{"protocolVersion", "serverInfo", "capabilities", "tools"}``.
    """
    return {
        "protocolVersion": MANIFEST_PROTOCOL_VERSION,
        "serverInfo": {"name": name, "title": title, "version": version},
        "capabilities": {"tools": {}},
        "tools": [dict(tool) for tool in compiled.tools],
    }


def manifest_digest(manifest: Mapping[str, Any]) -> str:
    """Return the catalog surface fingerprint of a manifest from :func:`toolset_manifest`.

    Built with :func:`app.mcp_manifest_parser.manifest_surface`, the constructor an import of the
    same manifest runs, so the import's ``surface_fingerprint`` equals this digest. Unlike a parse,
    a toolset with no tools (disabled, or nothing enabled) still has a digest.

    Args:
        manifest: The manifest.

    Returns:
        The SHA-256 hex fingerprint.
    """
    document = McpManifestDocument(
        protocol_version=manifest["protocolVersion"],
        server_info=ServerInfo.from_dict(manifest["serverInfo"]),
        capabilities=dict(manifest["capabilities"]),
        tools=tuple(dict(tool) for tool in manifest["tools"]),
    )
    return manifest_surface(document).fingerprint()


def _version(toolset: AgentToolsetOut) -> str:
    """The published version label, else the version id."""
    return (toolset.version_label or "").strip()[:255] or toolset.version_id


def _title(project_name: Optional[str], version: str) -> str:
    """A ≤100-character title: ``<project> <version> agent toolset``."""
    return _clip(f"{(project_name or '').strip() or 'API'} {version} agent toolset")


def _coordinates(toolset: AgentToolsetOut) -> Dict[str, Any]:
    """The toolset identity fields every ``_meta`` entry repeats."""
    return {
        "toolsetId": toolset.id,
        "projectId": toolset.project_id,
        "versionId": toolset.version_id,
        "versionLabel": toolset.version_label,
    }


def build_toolset_server_json(
    *,
    tenant_slug: str,
    toolset: AgentToolsetOut,
    compiled: CompiledToolsetOut,
    project_name: Optional[str],
    runtime_url: str,
    prm_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the ``server.json`` of one toolset.

    Args:
        tenant_slug: The owning tenant's slug (the registry namespace).
        toolset: The toolset.
        compiled: Its compiled tools (a disabled toolset compiles to none).
        project_name: The version's project name, for the title and description.
        runtime_url: The runtime's public ``/agent/mcp`` URL (already validated).
        prm_url: The runtime's Protected Resource Metadata URL, or empty when OAuth is unavailable.

    Returns:
        A ``ServerDetail`` document with ``_meta["dev.apiome/agent-runtime"]`` holding the
        toolset coordinates, ``digest``, auth hint and embedded ``manifest``.
    """
    name = toolset_server_name(tenant_slug, toolset.id)
    version = _version(toolset)
    title = _title(project_name, version)
    tool_count = len(compiled.tools)
    auth = auth_hint(prm_url)
    manifest = toolset_manifest(compiled, name=name, title=title, version=version)
    runtime: Dict[str, Any] = {
        "schemaVersion": SERVER_JSON_SCHEMA_VERSION,
        **_coordinates(toolset),
        "enabled": compiled.enabled,
        "target": toolset.target,
        "toolCount": tool_count,
        "digest": manifest_digest(manifest),
        "auth": auth,
        "manifest": manifest,
    }
    return {
        "$schema": SERVER_SCHEMA_URL,
        "name": name,
        "title": title,
        "description": _clip(
            f"Agent Access to {(project_name or '').strip() or 'an API'} {version}: "
            f"{tool_count} MCP tool{'' if tool_count == 1 else 's'}."
        ),
        "version": version,
        "remotes": [_remote(runtime_url, auth)],
        "_meta": {AGENT_RUNTIME_META_KEY: runtime},
    }


def build_tenant_server_json(
    *,
    tenant_slug: str,
    toolsets: Sequence[Mapping[str, Any]],
    runtime_url: str,
    prm_url: Optional[str] = None,
    unavailable: Sequence[str] = (),
) -> Dict[str, Any]:
    """Build the tenant-wide ``server.json``: the runtime as one remote, one entry per toolset.

    Args:
        tenant_slug: The tenant's slug.
        toolsets: Per-toolset documents from :func:`build_toolset_server_json` (enabled ones).
        runtime_url: The runtime's public ``/agent/mcp`` URL.
        prm_url: The Protected Resource Metadata URL, or empty when OAuth is unavailable.
        unavailable: Ids of enabled toolsets that could not be compiled (listed, not exported).

    Returns:
        A ``ServerDetail`` whose ``_meta["dev.apiome/agent-runtime"].toolsets`` lists each toolset's
        server name, coordinates, digest and tool names, ordered by toolset id. ``digest`` is the
        SHA-256 of the sorted ``(toolsetId, digest)`` pairs, and ``version`` is ``1.0.0+<digest
        prefix>`` — there is no single published label, so the version moves with the content.
    """
    entries: List[Dict[str, Any]] = []
    for document in toolsets:
        runtime = document["_meta"][AGENT_RUNTIME_META_KEY]
        entries.append(
            {
                "name": document["name"],
                "title": document["title"],
                **{key: runtime[key] for key in ("toolsetId", "projectId", "versionId", "versionLabel")},
                "toolCount": runtime["toolCount"],
                "tools": [str(tool.get("name")) for tool in runtime["manifest"]["tools"]],
                "digest": runtime["digest"],
            }
        )
    entries.sort(key=lambda entry: entry["toolsetId"])
    pairs = [[entry["toolsetId"], entry["digest"]] for entry in entries]
    digest = hashlib.sha256(json.dumps(pairs, separators=(",", ":")).encode("utf-8")).hexdigest()
    auth = auth_hint(prm_url)
    count = len(entries)
    return {
        "$schema": SERVER_SCHEMA_URL,
        "name": runtime_server_name(tenant_slug),
        "title": _clip(f"{tenant_slug} agent runtime"),
        "description": _clip(
            f"Apiome agent runtime for {tenant_slug}: {count} enabled toolset"
            f"{'' if count == 1 else 's'}; an agent key selects one."
        ),
        "version": f"1.0.0+{digest[:12]}",
        "remotes": [_remote(runtime_url, auth)],
        "_meta": {
            AGENT_RUNTIME_META_KEY: {
                "schemaVersion": SERVER_JSON_SCHEMA_VERSION,
                "toolsetCount": count,
                "digest": digest,
                "auth": auth,
                "toolsets": entries,
                "unavailable": sorted(unavailable),
            }
        },
    }


def runtime_server_response(document: Mapping[str, Any]) -> Dict[str, Any]:
    """Wrap a runtime ``server.json`` as a registry ``ServerResponse`` (AAU-5.3 listing).

    Args:
        document: A document from :func:`build_tenant_server_json`.

    Returns:
        ``{"server": document, "_meta": {official status}}`` — always the latest, active entry.
    """
    return {"server": dict(document), "_meta": {OFFICIAL_META_KEY: {"status": "active", "isLatest": True}}}


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _runtime_url() -> str:
    """The configured public runtime URL, cleaned of any credential.

    Raises:
        AgentToolsetError: ``agent-runtime-url-invalid`` when it is not an ``http(s)`` URL.
    """
    url = remote_url(settings.agent_mcp_public_url)
    if not url:
        raise AgentToolsetError(
            CODE_RUNTIME_URL_INVALID,
            "APIOME_AGENT_MCP_PUBLIC_URL must be the agent runtime's http(s) /agent/mcp URL",
        )
    return url


def _project_name(tenant_id: str, project_id: str) -> Optional[str]:
    """The project's name, or ``None`` when it cannot be read (the title falls back)."""
    try:
        project = db.get_project_by_id(project_id, tenant_id)
    except Exception:  # noqa: BLE001 - a missing name degrades the title, not the export
        logger.warning("server.json: project %s name unavailable", project_id, exc_info=True)
        return None
    if not project:
        return None
    return str(project.get("name") or "").strip() or None


def _toolset_document(
    tenant_id: str, tenant_slug: str, toolset: AgentToolsetOut, runtime_url: str
) -> Dict[str, Any]:
    """Compile one toolset and build its document."""
    return build_toolset_server_json(
        tenant_slug=tenant_slug,
        toolset=toolset,
        compiled=compile_agent_toolset(tenant_id, toolset.id),
        project_name=_project_name(tenant_id, toolset.project_id),
        runtime_url=runtime_url,
        prm_url=settings.agent_mcp_protected_resource_metadata_url,
    )


def export_toolset_server_json(tenant_id: str, tenant_slug: str, toolset_id: str) -> Dict[str, Any]:
    """Export one toolset's ``server.json``.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: Its slug (the registry namespace).
        toolset_id: The toolset.

    Returns:
        The document from :func:`build_toolset_server_json`.

    Raises:
        AgentToolsetError: ``agent-toolset-not-found``; ``agent-toolset-source-unavailable`` when it
            cannot be compiled; ``agent-runtime-url-invalid`` when the runtime URL is misconfigured.
    """
    runtime_url = _runtime_url()
    return _toolset_document(tenant_id, tenant_slug, get_agent_toolset(tenant_id, toolset_id), runtime_url)


def export_tenant_server_json(tenant_id: str, tenant_slug: str) -> Dict[str, Any]:
    """Export the tenant-wide ``server.json`` over every enabled toolset.

    A toolset whose version can no longer be compiled is listed under ``unavailable`` rather than
    failing the whole export.

    Args:
        tenant_id: The caller's tenant.
        tenant_slug: Its slug.

    Returns:
        The document from :func:`build_tenant_server_json`.

    Raises:
        AgentToolsetError: ``agent-runtime-url-invalid`` when the runtime URL is misconfigured.
    """
    runtime_url = _runtime_url()
    documents: List[Dict[str, Any]] = []
    unavailable: List[str] = []
    for toolset in list_agent_toolsets(tenant_id):
        if not toolset.enabled:
            continue
        try:
            documents.append(_toolset_document(tenant_id, tenant_slug, toolset, runtime_url))
        except AgentToolsetError:
            logger.warning("server.json: toolset %s could not be compiled", toolset.id, exc_info=True)
            unavailable.append(toolset.id)
    return build_tenant_server_json(
        tenant_slug=tenant_slug,
        toolsets=documents,
        runtime_url=runtime_url,
        prm_url=settings.agent_mcp_protected_resource_metadata_url,
        unavailable=unavailable,
    )
