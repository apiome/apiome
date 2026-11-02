"""``server.json`` → MCP catalog endpoint: schema normalization and registry metadata — V2-MCP-26.2 (#3708).

The MCP Registry describes a server with a ``server.json`` document
(https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/server-json/draft/server.schema.json).
The ``mcp-registry`` connector (:mod:`app.mcp_registry_connector_source`, CDG-4.4) imports each entry
as an MCP server; this module holds the two pure steps that make that import faithful:

* :func:`normalize_server_json` — the registry's earlier drafts spelled the document in snake_case
  (``version_detail.version``, ``website_url``, ``remotes[].transport_type``, ``packages[].registry_name``,
  ``is_required`` / ``is_secret``); the current draft is camelCase. A document in either spelling,
  or a mix, comes out in the current camelCase shape, so the rest of the import reads one schema.
* :func:`registry_metadata` — what the endpoint records about its registry entry
  (``apiome.mcp_endpoints.registry_metadata``): server name, ``version``, ``websiteUrl``, the
  registry's ``_meta`` status and dates, the chosen remote, and the headers that remote declares.
  A header's **name**, description and required / secret flags are kept so a reader knows what the
  server expects; a **secret** header's value or default is never stored.

Pure: no database or network access.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional

from .mcp_registry import remote_url

__all__ = [
    "OFFICIAL_META_KEY",
    "camelize",
    "camelize_key",
    "normalize_server_json",
    "registry_metadata",
    "remote_headers",
]

#: The registry's own metadata key under ``_meta``.
OFFICIAL_META_KEY = "io.modelcontextprotocol.registry/official"

#: A snake_case key (``website_url``, ``is_latest``). Reverse-DNS ``_meta`` keys never match.
_SNAKE_KEY = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$")


def camelize_key(key: str) -> str:
    """``website_url`` → ``websiteUrl``; any other key unchanged."""
    if not _SNAKE_KEY.match(key):
        return key
    head, *rest = key.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in rest)


def _camelize(value: Any) -> Any:
    """Every snake_case key of ``value`` camelized, recursively.

    When a document carries both spellings of one key (``website_url`` and ``websiteUrl``), the
    camelCase one — the current draft's — wins.
    """
    if isinstance(value, Mapping):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            target = camelize_key(key) if isinstance(key, str) else key
            if target != key and target in value:
                continue
            out[target] = _camelize(item)
        return out
    if isinstance(value, list):
        return [_camelize(item) for item in value]
    return value


def camelize(value: Any) -> Any:
    """Public :func:`_camelize`: the ``_meta`` registry block of an older entry needs it too."""
    return _camelize(value)


def normalize_server_json(server: Mapping[str, Any]) -> Dict[str, Any]:
    """A ``server.json`` document in the current camelCase draft shape.

    Beyond camelizing keys, the earlier drafts' renamed fields are moved to their current names:
    ``versionDetail.version`` → ``version``, ``packages[].registryName`` → ``registryType``,
    ``packages[].name`` → ``identifier``, ``remotes[].transportType`` → ``type``.

    Args:
        server: The document as the registry served it.

    Returns:
        A new document; the input is not modified. Fields already in the current spelling are kept
        as they are.
    """
    doc: Dict[str, Any] = _camelize(dict(server))
    detail = doc.pop("versionDetail", None)
    if isinstance(detail, Mapping) and detail.get("version") and not doc.get("version"):
        doc["version"] = detail["version"]
    packages = doc.get("packages")
    if isinstance(packages, list):
        doc["packages"] = [_current_package(p) if isinstance(p, Mapping) else p for p in packages]
    remotes = doc.get("remotes")
    if isinstance(remotes, list):
        doc["remotes"] = [_current_remote(r) if isinstance(r, Mapping) else r for r in remotes]
    return doc


def _current_package(package: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(package)
    if "registryName" in out and "registryType" not in out:
        out["registryType"] = out.pop("registryName")
    if "name" in out and "identifier" not in out:
        out["identifier"] = out.pop("name")
    return out


def _current_remote(remote: Mapping[str, Any]) -> Dict[str, Any]:
    out = dict(remote)
    if "transportType" in out and "type" not in out:
        out["type"] = out.pop("transportType")
    return out


def remote_headers(remote: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """The headers a remote declares (``remotes[].headers``), without secret values.

    Each header keeps ``name``, ``description``, ``isRequired`` and ``isSecret``; a non-secret
    header also keeps its fixed ``value`` and ``default`` (``{variables}`` templates included, since
    they name what the client must supply, not a credential). A secret header never keeps either:
    ``hasValue`` says whether the registry gave one.

    Args:
        remote: One ``remotes[]`` entry (normalized).

    Returns:
        The headers, in declaration order (unnamed entries are skipped).
    """
    headers: List[Dict[str, Any]] = []
    for header in remote.get("headers") or []:
        if not isinstance(header, Mapping) or not str(header.get("name") or "").strip():
            continue
        secret = bool(header.get("isSecret"))
        row: Dict[str, Any] = {
            "name": str(header["name"]).strip(),
            "isRequired": bool(header.get("isRequired")),
            "isSecret": secret,
        }
        if isinstance(header.get("description"), str) and header["description"].strip():
            row["description"] = header["description"].strip()[:500]
        if secret:
            row["hasValue"] = bool(header.get("value") or header.get("default"))
        else:
            for key in ("value", "default"):
                if isinstance(header.get(key), str) and header[key]:
                    row[key] = header[key][:500]
        headers.append(row)
    return headers


def _chosen_remote(server: Mapping[str, Any], url: str) -> Optional[Mapping[str, Any]]:
    for remote in server.get("remotes") or []:
        if isinstance(remote, Mapping) and str(remote.get("url") or "").strip() == url:
            return remote
    return None


def registry_metadata(
    server: Mapping[str, Any],
    official: Mapping[str, Any],
    *,
    registry_url: str,
    transport: str,
    url: str,
) -> Dict[str, Any]:
    """What an imported endpoint records about its registry entry.

    Args:
        server: The normalized ``server.json``.
        official: ``_meta["io.modelcontextprotocol.registry/official"]`` (``status``, ``isLatest``,
            ``publishedAt``, ``updatedAt``), or ``{}``.
        registry_url: The registry root the entry came from.
        transport: The transport chosen for the endpoint (``streamable_http`` / ``sse``).
        url: The chosen remote's URL.

    Returns:
        ``registryUrl``, ``serverName``, ``version``, ``websiteUrl``, ``title``, ``status``,
        ``isLatest``, ``publishedAt``, ``updatedAt``, ``remote`` (``type``, credential-free ``url``,
        ``headers``) — keys with no value are left out.
    """
    remote = _chosen_remote(server, url) or {}
    status = official.get("status")
    out: Dict[str, Any] = {
        "registryUrl": registry_url,
        "serverName": server.get("name"),
        "title": server.get("title"),
        "version": str(server.get("version") or "").strip() or None,
        "websiteUrl": remote_url(str(server.get("websiteUrl") or "")) or None,
        "status": str(status).lower() if isinstance(status, str) and status else None,
        "isLatest": official.get("isLatest") if isinstance(official.get("isLatest"), bool) else None,
        "publishedAt": official.get("publishedAt"),
        "updatedAt": official.get("updatedAt"),
        "remote": {
            "type": remote.get("type") or transport.replace("_", "-"),
            "url": remote_url(url) or url[:500],
            "headers": remote_headers(remote),
        },
    }
    return {key: value for key, value in out.items() if value not in (None, "")}
