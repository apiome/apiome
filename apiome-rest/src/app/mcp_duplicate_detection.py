"""Duplicate / near-duplicate detection for the MCP catalog (V2-MCP-36.1 / MCAT-22.1, #4664).

Pure grouping over endpoint rows: normalized ``endpoint_url``, shared host (when fingerprints
do not prove distinct servers), and identical ``surface_fingerprint``. Advisory only — never
auto-merges endpoints.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlsplit, urlunparse

from .models import (
    MCP_ENDPOINT_URL_TRANSPORTS,
    McpDuplicateCrossTenantHint,
    McpDuplicateEndpointOut,
    McpDuplicateGroup,
    McpDuplicateReportResponse,
    mcp_duplicate_endpoint_out_from_row,
    mcp_endpoint_host,
)

McpDuplicateKind = Literal["exact_url", "same_host", "identical_surface"]

_DUPLICATE_KIND_LABELS: Dict[McpDuplicateKind, str] = {
    "exact_url": "These endpoints share the same normalized URL and may be the same server.",
    "same_host": "These endpoints share a host and may be the same server — review before keeping both.",
    "identical_surface": "These endpoints expose an identical capability surface fingerprint.",
}


def normalize_mcp_endpoint_url_for_dedup(url: str, *, transport: Optional[str] = None) -> str:
    """Canonical URL string for duplicate detection within a tenant.

  For ``http``/``https`` endpoints: lowercases scheme and host, strips userinfo (tokens in the
  authority must not make two registrations look distinct), trims a trailing slash on the path,
  and drops the fragment. Query is preserved. For ``stdio`` and other non-URL targets the
  trimmed stored value is used as-is.
    """
    raw = (url or "").strip()
    if not raw:
        return ""

    parts = urlsplit(raw)
    scheme = parts.scheme.lower()
    if scheme in ("http", "https"):
        host = (parts.hostname or "").lower()
        if not host:
            return raw
        port = parts.port
        default_port = 443 if scheme == "https" else 80
        if port is not None and port != default_port:
            netloc = f"{host}:{port}"
        else:
            netloc = host

        path = parts.path or "/"
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")

        return urlunparse((scheme, netloc, path, "", parts.query, ""))

    if transport in MCP_ENDPOINT_URL_TRANSPORTS:
        return raw

    return raw


def _endpoint_out(row: Mapping[str, Any]) -> McpDuplicateEndpointOut:
    return mcp_duplicate_endpoint_out_from_row(dict(row))


def _group(
    kind: McpDuplicateKind,
    match_key: str,
    rows: Sequence[Mapping[str, Any]],
) -> McpDuplicateGroup:
    endpoints = [_endpoint_out(r) for r in rows]
    return McpDuplicateGroup(
        kind=kind,
        match_key=match_key,
        reason=_DUPLICATE_KIND_LABELS[kind],
        endpoint_count=len(endpoints),
        endpoints=endpoints,
    )


def build_mcp_duplicate_groups(
    candidates: Sequence[Mapping[str, Any]],
) -> List[McpDuplicateGroup]:
    """Group tenant endpoints that look like duplicates or near-duplicates."""
    if not candidates:
        return []

    enriched: List[Dict[str, Any]] = []
    for row in candidates:
        transport = str(row.get("transport") or "")
        raw_url = str(row.get("endpoint_url") or "")
        enriched.append(
            {
                **dict(row),
                "_normalized_url": normalize_mcp_endpoint_url_for_dedup(raw_url, transport=transport),
                "_host": mcp_endpoint_host(raw_url),
                "_fingerprint": row.get("surface_fingerprint"),
            }
        )

    groups: List[McpDuplicateGroup] = []

    by_url: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        key = row["_normalized_url"]
        if key:
            by_url[key].append(row)
    for key, rows in sorted(by_url.items()):
        if len(rows) > 1:
            groups.append(_group("exact_url", key, rows))

    by_fingerprint: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        fp = row.get("_fingerprint")
        if fp:
            by_fingerprint[str(fp)].append(row)
    for key, rows in sorted(by_fingerprint.items()):
        if len(rows) > 1:
            groups.append(_group("identical_surface", key, rows))

    by_host: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        host = row["_host"]
        transport = str(row.get("transport") or "")
        if host != "(local)" and transport in MCP_ENDPOINT_URL_TRANSPORTS:
            by_host[host].append(row)

    exact_url_sets = {frozenset(str(r["id"]) for r in rows) for rows in by_url.values() if len(rows) > 1}

    for host, rows in sorted(by_host.items()):
        if len(rows) < 2:
            continue
        norm_urls = {r["_normalized_url"] for r in rows if r["_normalized_url"]}
        if len(norm_urls) < 2:
            continue

        fingerprints = [str(r["_fingerprint"]) for r in rows if r.get("_fingerprint")]
        if len(fingerprints) >= 2 and len(set(fingerprints)) == len(fingerprints):
            continue

        endpoint_ids = frozenset(str(r["id"]) for r in rows)
        if endpoint_ids in exact_url_sets:
            continue

        groups.append(_group("same_host", host, rows))

    groups.sort(key=lambda g: (g.kind, g.match_key))
    return groups


def build_mcp_cross_tenant_hints(
    tenant_id: str,
    local_candidates: Sequence[Mapping[str, Any]],
    foreign_published: Sequence[Mapping[str, Any]],
) -> List[McpDuplicateCrossTenantHint]:
    """Hint when a published endpoint in another tenant matches a local registration key."""
    if not local_candidates or not foreign_published:
        return []

    local_by_url: Dict[str, List[str]] = defaultdict(list)
    local_by_fp: Dict[str, List[str]] = defaultdict(list)
    for row in local_candidates:
        eid = str(row["id"])
        transport = str(row.get("transport") or "")
        norm = normalize_mcp_endpoint_url_for_dedup(
            str(row.get("endpoint_url") or ""),
            transport=transport,
        )
        if norm:
            local_by_url[norm].append(eid)
        fp = row.get("surface_fingerprint")
        if fp:
            local_by_fp[str(fp)].append(eid)

    hints: List[McpDuplicateCrossTenantHint] = []
    seen: set[Tuple[str, str, str]] = set()

    for row in foreign_published:
        if str(row.get("tenant_id")) == str(tenant_id):
            continue
        transport = str(row.get("transport") or "")
        norm = normalize_mcp_endpoint_url_for_dedup(
            str(row.get("endpoint_url") or ""),
            transport=transport,
        )
        fp = row.get("surface_fingerprint")
        foreign_slug = str(row.get("tenant_slug") or "")
        foreign_ep_slug = str(row.get("slug") or "")

        for kind, key, local_ids in (
            ("exact_url", norm, local_by_url.get(norm, [])),
            ("identical_surface", str(fp) if fp else "", local_by_fp.get(str(fp), []) if fp else []),
        ):
            if not key or not local_ids:
                continue
            dedupe = (kind, key, foreign_slug)
            if dedupe in seen:
                continue
            seen.add(dedupe)
            hints.append(
                McpDuplicateCrossTenantHint(
                    kind=kind,
                    match_key=key,
                    local_endpoint_ids=sorted(local_ids),
                    foreign_tenant_slug=foreign_slug,
                    foreign_endpoint_slug=foreign_ep_slug,
                    foreign_endpoint_name=str(row.get("name") or ""),
                )
            )

    hints.sort(key=lambda h: (h.kind, h.match_key, h.foreign_tenant_slug))
    return hints


def mcp_duplicate_report_from_rows(
    *,
    tenant_id: str,
    candidates: Sequence[Mapping[str, Any]],
    foreign_published: Sequence[Mapping[str, Any]],
) -> McpDuplicateReportResponse:
    """Build the advisory duplicate report envelope."""
    groups = build_mcp_duplicate_groups(candidates)
    hints = build_mcp_cross_tenant_hints(tenant_id, candidates, foreign_published)
    endpoint_ids = {e.id for g in groups for e in g.endpoints}
    return McpDuplicateReportResponse(
        success=True,
        advisory=True,
        group_count=len(groups),
        flagged_endpoint_count=len(endpoint_ids),
        groups=groups,
        cross_tenant_hints=hints,
    )
