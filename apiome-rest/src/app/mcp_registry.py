"""MCP Registry API shape over the MCP server catalog — pure builders (AAU-5.3, #5724; CDG-4.1, #5973).

MCP hosts and gateways discover servers through the official registry API (``GET /v0.1/servers``
and friends). This module turns one cataloged ``apiome.mcp_endpoints`` row — joined to its current
snapshot and stored score by :meth:`app.database.Database.list_mcp_registry_endpoints` — into a
registry ``ServerResponse``: a ``server.json`` document (``server``) plus registry metadata
(``_meta``). :mod:`app.mcp_registry_routes` reads the rows and serves the pages.

Design rules:

* **Pure.** No database or network access, so every rule is unit-testable and the output is
  deterministic: the same row always yields the same entry (and the same ``ETag``).
* **Never leaks a credential.** A stored ``endpoint_url`` may embed ``user:pass@`` or a token in
  its query string; :func:`remote_url` keeps only scheme, host, port and path.
* **Valid by construction.** Names, titles and descriptions are trimmed to the schema's patterns
  and lengths, and the vendored schema (``data/mcp_registry_v0_1_schema.json``, pinned in its
  ``$comment``) is what the tests validate every built page against.

Naming: a server is ``apiome.<tenant-slug>/<endpoint-slug>`` — one namespace per tenant, one name
per endpoint. Each endpoint is served at its *current* snapshot only (``isLatest: true``); earlier
snapshots are discovery history, not published registry versions.

Sources (CDG-4.1): an endpoint's live ``mcp_endpoint_sources`` rows fill ``packages[]`` (package and
image sources) and ``repository`` (the newest git source). Nothing is invented: an endpoint with no
linked source has ``packages: []``, no ``repository``, and ``_meta["dev.apiome/catalog"].sources``
of ``"none"``. A package ``version`` is set only when the source pins an exact version.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import unquote, urlsplit

#: The ``server.json`` schema every built ``server`` document declares (``$schema``).
SERVER_SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"

#: The registry API version the routes serve (the ``/v0.1`` path segment).
REGISTRY_API_VERSION = "v0.1"

#: Prefix of every tenant namespace: a server is named ``apiome.<tenant-slug>/<endpoint-slug>``.
NAMESPACE_PREFIX = "apiome."

#: The registry-managed ``_meta`` key (official status fields).
OFFICIAL_META_KEY = "io.modelcontextprotocol.registry/official"

#: Apiome's own ``_meta`` extension key (grade, trust posture, catalog identity).
CATALOG_META_KEY = "dev.apiome/catalog"

#: Default and maximum page sizes for ``GET /v0.1/servers``.
DEFAULT_PAGE_LIMIT = 30
MAX_PAGE_LIMIT = 100

#: Schema bounds for ``server.title`` / ``server.description`` and ``server.name``.
_TEXT_MAX = 100
_NAME_MAX = 200

#: Catalog transports → registry remote types. ``stdio`` has no URL, so it has no remote.
_REMOTE_TYPES = {"streamable_http": "streamable-http", "sse": "sse"}

_NAMESPACE_UNSAFE = re.compile(r"[^a-zA-Z0-9.-]+")
_NAME_UNSAFE = re.compile(r"[^a-zA-Z0-9._-]+")

_SCHEMA_PATH = Path(__file__).resolve().parent / "data" / "mcp_registry_v0_1_schema.json"

#: Upstream registry OpenAPI the vendored ``ServerResponse`` / ``ServerList`` were copied from.
REGISTRY_API_SPEC_VERSION = "2025-12-01"
REGISTRY_API_SPEC_COMMIT = "11b7b0e274d518b6f449c5ee3518a6151d9848b9"

#: ``_meta["dev.apiome/catalog"].sources`` values: no live source linked, or at least one.
SOURCES_NONE = "none"
SOURCES_LINKED = "linked"

#: ``_meta["dev.apiome/catalog"].lintGate.verdict`` values.
LINT_GATE_PASS = "pass"
LINT_GATE_FAIL = "fail"
LINT_GATE_NOT_EVALUATED = "not_evaluated"

#: Registry base URLs for the package ecosystems whose purl type matches a registry type.
_REGISTRY_BASE_URLS = {
    "npm": "https://registry.npmjs.org",
    "pypi": "https://pypi.org",
    "nuget": "https://api.nuget.org/v3/index.json",
}

#: Git hosts whose ``repository.source`` is a well-known forge id rather than the hostname.
_FORGES = {"github.com": "github", "gitlab.com": "gitlab", "bitbucket.org": "bitbucket"}

#: Package versions that pin nothing (the schema rejects ``latest``; a range is not a version).
_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.\-+]+)?$")


class InvalidCursorError(ValueError):
    """Raised when a ``cursor`` query value is not one this API issued."""


def tenant_namespace(tenant_slug: str) -> str:
    """Return the registry namespace for a tenant (``apiome.<tenant-slug>``).

    Args:
        tenant_slug: The tenant's URL slug.

    Returns:
        The namespace, with any character the schema's namespace pattern forbids replaced by ``-``.
    """
    return NAMESPACE_PREFIX + _NAMESPACE_UNSAFE.sub("-", tenant_slug)


def server_name(tenant_slug: str, endpoint_slug: str) -> str:
    """Return the registry server name for an endpoint (``apiome.<tenant>/<endpoint>``).

    Args:
        tenant_slug: The owning tenant's URL slug.
        endpoint_slug: The endpoint's tenant-unique catalog slug.

    Returns:
        A name matching the schema pattern ``^[a-zA-Z0-9.-]+/[a-zA-Z0-9._-]+$``.
    """
    return f"{tenant_namespace(tenant_slug)}/{_NAME_UNSAFE.sub('-', endpoint_slug)}"[:_NAME_MAX]


def endpoint_slug_from_name(name: str, tenant_slug: str) -> Optional[str]:
    """Return the endpoint slug a server name addresses, or ``None`` when it is not this tenant's.

    Args:
        name: The (already URL-decoded) server name from the path.
        tenant_slug: The tenant whose registry is being read.

    Returns:
        The part after the ``/`` when the namespace is this tenant's, else ``None``.
    """
    namespace, sep, slug = name.partition("/")
    if not sep or not slug or namespace != tenant_namespace(tenant_slug):
        return None
    return slug


def remote_url(endpoint_url: Optional[str]) -> Optional[str]:
    """Return a stored endpoint URL with userinfo, query and fragment removed.

    Args:
        endpoint_url: The stored ``mcp_endpoints.endpoint_url`` (may carry credentials).

    Returns:
        ``scheme://host[:port]/path`` for an ``http``/``https`` URL with a host, else ``None``.
    """
    if not endpoint_url:
        return None
    try:
        parts = urlsplit(endpoint_url.strip())
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not host:
        return None
    if ":" in host:
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port is not None else host
    url = f"{parts.scheme}://{netloc}{parts.path}"
    return None if re.search(r"\s", url) else url


def entry_version(row: Mapping[str, Any]) -> str:
    """Return the version an entry advertises: ``serverInfo.version``, else the snapshot label.

    Args:
        row: A registry row (see :meth:`Database.list_mcp_registry_endpoints`).

    Returns:
        The server-reported version when present, else the snapshot's ``version_tag``.
    """
    reported = str(row.get("server_version") or "").strip()
    return (reported or str(row.get("version_tag") or "")).strip()[:255]


def _clip(text: str) -> str:
    """Trim ``text`` to the schema's 100-character bound, ending in an ellipsis when cut."""
    text = " ".join(text.split())
    return text if len(text) <= _TEXT_MAX else text[: _TEXT_MAX - 1].rstrip() + "…"


def _iso(value: Any) -> Optional[str]:
    """Render a datetime as an RFC 3339 UTC string (``Z`` suffix), or ``None``."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _package_from_purl(purl: str, digest: Optional[str]) -> Optional[Dict[str, Any]]:
    """Map a package source's Package URL to a registry ``Package``, or ``None`` when unusable.

    Args:
        purl: The stored canonical purl, e.g. ``pkg:npm/%40scope/name@1.2.3``.
        digest: The source's stored digest — for a package, its exact pinned version (else ``None``).

    Returns:
        ``{"registryType", "identifier", "transport", ["version"], ["registryBaseUrl"]}``; the
        version appears only when the source pins an exact one.
    """
    body = purl[len("pkg:"):] if purl.startswith("pkg:") else ""
    body = body.split("?", 1)[0].split("#", 1)[0]
    registry_type, sep, rest = body.partition("/")
    if not sep or not registry_type or not rest:
        return None
    # A trailing ``@version`` never contains ``/``; an ``@`` inside a scoped name (``@scope/name``) does.
    head, at, tail = rest.rpartition("@")
    coordinate = head if at and head and "/" not in tail else rest
    identifier = unquote(coordinate).strip("/")
    if not identifier:
        return None
    package: Dict[str, Any] = {
        "registryType": registry_type.lower(),
        "identifier": identifier,
        "transport": {"type": "stdio"},
    }
    base_url = _REGISTRY_BASE_URLS.get(package["registryType"])
    if base_url:
        package["registryBaseUrl"] = base_url
    if digest and _EXACT_VERSION.match(digest):
        package["version"] = digest
    return package


def build_packages(sources: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Build ``server.packages`` from an endpoint's live source rows (CDG-4.1).

    Package sources map through their purl (``registryType`` = purl type); image sources map to
    ``registryType: "oci"`` with the canonical image reference as ``identifier``. Git and MCP
    registry sources are not packages and are skipped. Duplicates collapse to the first (newest).

    Args:
        sources: Live ``mcp_endpoint_sources`` rows, newest first (``source_kind``, ``locator``,
            ``purl``, ``digest``).

    Returns:
        The packages, in source order; empty when no package or image source is linked.
    """
    packages: List[Dict[str, Any]] = []
    seen = set()
    for source in sources:
        kind = source.get("source_kind")
        package: Optional[Dict[str, Any]] = None
        if kind == "package" and source.get("purl"):
            package = _package_from_purl(str(source["purl"]), source.get("digest"))
        elif kind == "image" and source.get("locator"):
            package = {
                "registryType": "oci",
                "identifier": str(source["locator"]),
                "transport": {"type": "stdio"},
            }
        if package is None:
            continue
        key = (package["registryType"], package["identifier"], package.get("version"))
        if key not in seen:
            seen.add(key)
            packages.append(package)
    return packages


def build_repository(sources: List[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """Build ``server.repository`` from the newest live git source, or ``None`` when there is none.

    Args:
        sources: Live ``mcp_endpoint_sources`` rows, newest first. A git ``locator`` is already
            canonical ``https://host/owner/repo`` with any credentials stripped.

    Returns:
        ``{"url", "source"}`` — ``source`` is the forge id (``github`` / ``gitlab`` /
        ``bitbucket``) or else the hostname.
    """
    for source in sources:
        if source.get("source_kind") != "git":
            continue
        url = remote_url(str(source.get("locator") or ""))
        host = urlsplit(url).hostname if url else None
        if url and host:
            return {"url": url, "source": _FORGES.get(host, host)}
    return None


def lint_gate_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
    """Return the current snapshot's stored lint gate verdict (CDG-4.1).

    Reads the latest persisted ``lint_policy_evaluations`` row for the snapshot (joined into the
    registry row); the gate is never run on a registry read.

    Args:
        row: A registry row carrying ``lint_gate_passed`` / ``lint_gate_evaluated_at``.

    Returns:
        ``{"verdict": "pass" | "fail" | "not_evaluated", "evaluatedAt": <RFC 3339 or None>}``.
    """
    passed = row.get("lint_gate_passed")
    if passed is None:
        verdict = LINT_GATE_NOT_EVALUATED
    else:
        verdict = LINT_GATE_PASS if passed else LINT_GATE_FAIL
    return {"verdict": verdict, "evaluatedAt": _iso(row.get("lint_gate_evaluated_at"))}


def owner_team(row: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the endpoint's owner team (confirmed, else first suggestion) as ``{slug, name, status}``.

    Args:
        row: A registry row carrying the ``entity_owner`` envelope (or ``None``).

    Returns:
        The owner summary, or ``None`` when no team owns the endpoint.
    """
    owner = row.get("entity_owner")
    if not isinstance(owner, Mapping):
        return None
    team = owner.get("team")
    if not isinstance(team, Mapping) or not team.get("slug"):
        return None
    return {"slug": team.get("slug"), "name": team.get("name"), "status": owner.get("status")}


def build_server_response(
    row: Mapping[str, Any],
    *,
    trust_posture: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one registry ``ServerResponse`` from a registry row.

    Args:
        row: A row from :meth:`Database.list_mcp_registry_endpoints` (its ``sources`` list holds the
            endpoint's live source rows, newest first).
        trust_posture: The current snapshot's posture summary (``score`` / ``grade`` /
            ``gatePassed``), or ``None`` when it could not be computed.

    Returns:
        ``{"server": <server.json>, "_meta": {official status, dev.apiome/catalog}}``.
    """
    name = str(row.get("name") or row.get("slug") or "")
    description = str(row.get("description") or "").strip() or f"{name} (MCP server)"
    server: Dict[str, Any] = {
        "$schema": SERVER_SCHEMA_URL,
        "name": server_name(str(row["tenant_slug"]), str(row["slug"])),
        "title": _clip(str(row.get("server_title") or "").strip() or name),
        "description": _clip(description),
        "version": entry_version(row),
        "remotes": [],
    }
    remote_type = _REMOTE_TYPES.get(str(row.get("transport") or ""))
    url = remote_url(row.get("endpoint_url"))
    if remote_type and url:
        server["remotes"].append({"type": remote_type, "url": url})
    sources = [s for s in (row.get("sources") or []) if isinstance(s, Mapping)]
    server["packages"] = build_packages(sources)
    repository = build_repository(sources)
    if repository:
        server["repository"] = repository

    official: Dict[str, Any] = {"status": "active", "isLatest": True}
    published_at = _iso(row.get("created_at"))
    updated_at = _iso(row.get("entry_updated_at") or row.get("updated_at"))
    if published_at:
        official["publishedAt"] = published_at
    if updated_at:
        official["updatedAt"] = updated_at

    catalog: Dict[str, Any] = {
        "endpointId": str(row["id"]),
        "slug": str(row["slug"]),
        "visibility": str(row.get("visibility") or "private"),
        "published": bool(row.get("published")),
        "versionTag": row.get("version_tag"),
        "manifestDigest": row.get("surface_fingerprint"),
        "score": row.get("score"),
        "grade": row.get("grade"),
        "trustPosture": dict(trust_posture) if trust_posture is not None else None,
        "ownerTeam": owner_team(row),
        "lintGate": lint_gate_summary(row),
        "sources": SOURCES_LINKED if sources else SOURCES_NONE,
    }
    return {"server": server, "_meta": {OFFICIAL_META_KEY: official, CATALOG_META_KEY: catalog}}


def trust_posture_summary(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Reduce a trust-posture ``report_dict()`` to what a registry entry carries.

    Args:
        report: :meth:`app.mcp_trust_posture.PostureReport.report_dict` output.

    Returns:
        ``{"score", "grade", "gatePassed"}``.
    """
    gate = report.get("gate") or {}
    return {
        "score": report.get("score"),
        "grade": report.get("grade"),
        "gatePassed": bool(gate.get("passed")) if isinstance(gate, Mapping) else None,
    }


def server_list(entries: List[Dict[str, Any]], next_cursor: Optional[str]) -> Dict[str, Any]:
    """Wrap entries in a registry ``ServerList`` (``servers`` + ``metadata``).

    Args:
        entries: The page's ``ServerResponse`` documents.
        next_cursor: The cursor of the next page, or ``None`` on the last page.

    Returns:
        The ``ServerList`` body; ``metadata.nextCursor`` is omitted on the last page.
    """
    metadata: Dict[str, Any] = {"count": len(entries)}
    if next_cursor:
        metadata["nextCursor"] = next_cursor
    return {"servers": entries, "metadata": metadata}


def encode_cursor(last_slug: str) -> str:
    """Encode a keyset cursor (the last slug of a page) as an opaque base64url token.

    Args:
        last_slug: The slug of the page's last scanned row.

    Returns:
        The unpadded base64url token for ``metadata.nextCursor``.
    """
    raw = json.dumps({"v": 1, "s": last_slug}, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(token: str) -> str:
    """Decode a cursor from :func:`encode_cursor` back to its slug.

    Args:
        token: The ``cursor`` query value.

    Returns:
        The slug to resume after.

    Raises:
        InvalidCursorError: When the token is malformed or not version 1.
    """
    try:
        padded = token + "=" * (-len(token) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeError, binascii.Error) as exc:
        raise InvalidCursorError("invalid cursor") from exc
    if not isinstance(payload, dict) or payload.get("v") != 1 or not isinstance(payload.get("s"), str):
        raise InvalidCursorError("invalid cursor")
    return payload["s"]


def body_etag(document: Any) -> str:
    """Return a strong, content-addressed ``ETag`` for a JSON document.

    An entry embeds its snapshot's manifest digest (``manifestDigest``), so the tag moves whenever
    the manifest — or any other advertised field — changes, and only then.

    Args:
        document: The JSON-ready response body.

    Returns:
        The quoted SHA-256 hex of the canonical JSON.
    """
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), default=str)
    return '"' + hashlib.sha256(canonical.encode("utf-8")).hexdigest() + '"'


@lru_cache(maxsize=1)
def registry_schema() -> Dict[str, Any]:
    """Return the vendored MCP Registry API v0.1 response schema (``definitions`` document).

    Returns:
        The parsed schema; ``ServerList`` / ``ServerResponse`` / ``ServerDetail`` are under
        ``definitions``.
    """
    with _SCHEMA_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def definition_schema(definition: str) -> Dict[str, Any]:
    """Return a schema validating one vendored definition (e.g. ``"ServerList"``).

    Args:
        definition: A key under the vendored schema's ``definitions``.

    Returns:
        A draft-07 schema whose root ``$ref`` points at that definition.
    """
    schema = registry_schema()
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$ref": f"#/definitions/{definition}",
        "definitions": schema["definitions"],
    }


def schema_info() -> Dict[str, Any]:
    """Describe the registry API and schema versions this server serves (the ``schema`` route).

    Returns:
        ``{"registryApiVersion", "serverSchema", "apiSpec": {"version", "commit"}}`` — the path
        version, the ``server.json`` schema every entry declares, and the pinned upstream OpenAPI
        the vendored response schemas were copied from.
    """
    return {
        "registryApiVersion": REGISTRY_API_VERSION,
        "serverSchema": SERVER_SCHEMA_URL,
        "apiSpec": {"version": REGISTRY_API_SPEC_VERSION, "commit": REGISTRY_API_SPEC_COMMIT},
    }
