"""Shadow-API report — CDG-1.6 (#5957).

Connected gateways (CDG-1.1 connectors) say what *runs*; the catalog says what is *described*.
This module answers the difference, in three sections plus the matches a person must confirm:

* **Shadow** — served by a gateway, described nowhere: an inventory row with no catalog item and no
  plausible match.
* **Possible matches** — an inventory row with no catalog item that *looks* like a catalog item or a
  published Project. Each carries its match **tier** and **confidence**; nothing is ever linked
  automatically — a person clicks "Link to item".
* **Undeployed** — described (a catalog item, or a Project's published version, that declares an
  HTTP server) but served by no connected gateway: nothing links to it and no inventory row matches
  its servers.
* **Drift** — linked, but the gateway now serves a revision the catalog does not have. The RAR-2.2
  comparator (:func:`app.repository_refresh_comparator.evaluate_refresh`) decides it, against the
  catalog item's latest synced revision.

**Matching tiers**, strongest first (:func:`match_item`):

1. ``remote-id`` (confidence 1.0) — a catalog revision whose ``format_metadata.remoteId`` is the
   row's remote id (an item imported earlier and since unlinked, or by another connector).
2. ``host`` (0.9 for host and base path, 0.7 for the host alone) — one of the row's hosts, and its
   base path, against the servers of a catalog item's latest revision or a Project's latest
   published version. The host alone matches when the server declares no path, the row's path is
   under the server's, or the row declares no path; a row on another path of the same host does not
   match.
3. ``title`` (at most 0.5) — the row's name against a catalog item's or Project's name, when they
   are at least :data:`TITLE_THRESHOLD` similar.

**Ignored rows** keep their reason. A row ignored on one host or base path and now served on
another *reappears* in its section, with the reason still shown, because what was judged is no
longer what runs.

**Stale inventory.** A connector whose last run failed (``failing``) still contributes its last
known inventory, but the report lists it under ``stale`` with the time of its last successful run,
so an empty Shadow list is never mistaken for a clean bill of health.

This module is pure: :func:`build_shadow_report` takes plain rows (see :mod:`app.shadow_api_store`
for the SQL that loads them) and returns a JSON-ready dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

from .repository_refresh_comparator import evaluate_refresh

__all__ = [
    "CATEGORIES",
    "TIER_HOST",
    "TIER_REMOTE_ID",
    "TIER_TITLE",
    "TITLE_THRESHOLD",
    "Endpoint",
    "build_shadow_report",
    "failing_categories",
    "item_endpoints",
    "match_item",
    "server_endpoint",
]

#: Match tiers, strongest first.
TIER_REMOTE_ID = "remote-id"
TIER_HOST = "host"
TIER_TITLE = "title"

#: Report sections a CI gate may fail on (``apiome connectors shadow-report --fail-on``).
CATEGORIES: Tuple[str, ...] = ("shadow", "possible-matches", "undeployed", "drift")

#: Minimum name similarity (0–1) for a ``title`` match.
TITLE_THRESHOLD = 0.8
#: Confidence of each tier (a title match scales by its similarity, up to this ceiling).
CONFIDENCE_REMOTE_ID = 1.0
CONFIDENCE_HOST_AND_PATH = 0.9
CONFIDENCE_HOST_ONLY = 0.7
CONFIDENCE_TITLE_MAX = 0.5

#: How many alternative candidates a possible match lists beside the best one.
MAX_ALTERNATIVES = 3


@dataclass(frozen=True)
class Endpoint:
    """Where something is served: a lower-case host and a normalized base path (``""`` = root)."""

    host: str
    path: str


def _norm_path(path: Optional[str]) -> str:
    """``/a/b`` with no trailing slash; ``""`` for the root or nothing."""
    text = "/" + str(path or "").strip().strip("/")
    return "" if text == "/" else text


def _endpoint(value: str, default_path: Optional[str]) -> Optional[Endpoint]:
    """One host (bare, ``host:port`` or a URL) as an :class:`Endpoint`; ``None`` if unusable."""
    text = str(value or "").strip()
    if not text:
        return None
    if "://" not in text:
        text = f"//{text}"
    parts = urlsplit(text)
    host = (parts.hostname or "").lower()
    if not host or "{" in host:
        return None
    path = parts.path if parts.path not in ("", "/") else (default_path or "")
    return Endpoint(host, _norm_path(path))


def item_endpoints(hosts: Iterable[str], base_path: Optional[str]) -> List[Endpoint]:
    """The endpoints an inventory row is served on.

    A bare host (``api.example.com``) is served under the row's base path; a host given as a URL
    (an AWS invoke URL, an APIM gateway URL) carries its own path, which wins.
    """
    found: List[Endpoint] = []
    for host in hosts or []:
        endpoint = _endpoint(host, base_path)
        if endpoint is not None and endpoint not in found:
            found.append(endpoint)
    return found


def server_endpoint(url: str) -> Optional[Endpoint]:
    """A declared server URL as an :class:`Endpoint`; ``None`` for a relative or templated host."""
    text = str(url or "").strip()
    if "://" not in text:
        return None
    return _endpoint(text, None)


def _similarity(a: Optional[str], b: Optional[str]) -> float:
    left, right = str(a or "").strip().lower(), str(b or "").strip().lower()
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def _entry_ref(entry: Mapping[str, Any]) -> Dict[str, Any]:
    """The catalog entry a match points at."""
    return {
        "projectId": str(entry["project_id"]),
        "name": entry.get("name"),
        "kind": "project" if entry.get("publishable") else "catalog-item",
        "versionId": str(entry["version_id"]) if entry.get("version_id") else None,
        "versionLabel": entry.get("version_label"),
    }


def match_item(item: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Every catalog entry an unlinked inventory row could be, best first.

    Args:
        item: An inventory row (``remote_id``, ``remote_name``, ``hosts``, ``base_path``).
        entries: Catalog entries (see :func:`build_shadow_report`).

    Returns:
        ``[{tier, confidence, reason, target}]`` sorted by confidence (Projects before catalog items
        on a tie, then by name); empty when nothing matches. One entry appears at most once, under
        its strongest tier.
    """
    endpoints = item_endpoints(item.get("hosts") or [], item.get("base_path"))
    best: Dict[str, Dict[str, Any]] = {}

    def offer(entry: Mapping[str, Any], tier: str, confidence: float, reason: str) -> None:
        key = str(entry["project_id"])
        current = best.get(key)
        if current is None or confidence > current["confidence"]:
            best[key] = {
                "tier": tier,
                "confidence": round(confidence, 2),
                "reason": reason,
                "target": _entry_ref(entry),
                "_publishable": bool(entry.get("publishable")),
            }

    remote_id = str(item.get("remote_id") or "")
    for entry in entries:
        if remote_id and remote_id in (entry.get("remote_ids") or []):
            offer(entry, TIER_REMOTE_ID, CONFIDENCE_REMOTE_ID, f"A revision was imported from remote id {remote_id}.")
            continue
        for url in entry.get("servers") or []:
            server = server_endpoint(url)
            if server is None:
                continue
            for endpoint in endpoints:
                if endpoint.host != server.host:
                    continue
                if endpoint.path == server.path:
                    offer(entry, TIER_HOST, CONFIDENCE_HOST_AND_PATH, f"Served on {url}, a declared server.")
                elif not server.path or not endpoint.path or endpoint.path.startswith(server.path + "/"):
                    # The server covers the row's path, or the row does not say its path.
                    offer(entry, TIER_HOST, CONFIDENCE_HOST_ONLY, f"Same host as the declared server {url}.")
        ratio = _similarity(item.get("remote_name"), entry.get("name"))
        if ratio >= TITLE_THRESHOLD:
            offer(
                entry,
                TIER_TITLE,
                CONFIDENCE_TITLE_MAX * ratio,
                f"Name is {round(ratio * 100)}% similar to {entry.get('name')!r}.",
            )
    ranked = sorted(best.values(), key=lambda m: (-m["confidence"], not m["_publishable"], str(m["target"]["name"])))
    for match in ranked:
        match.pop("_publishable", None)
    return ranked


def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _reappeared(item: Mapping[str, Any]) -> bool:
    """Whether an ignored row is now served somewhere other than where it was ignored."""
    snapshot = item.get("ignored_hosts")
    if snapshot is None:
        return False
    moved_host = sorted(snapshot) != sorted(item.get("hosts") or [])
    return moved_host or _norm_path(item.get("ignored_base_path")) != _norm_path(item.get("base_path"))


def _item_view(item: Mapping[str, Any], connector: Mapping[str, Any], stale: bool) -> Dict[str, Any]:
    view: Dict[str, Any] = {
        "itemId": str(item["id"]),
        "connectorId": str(connector["id"]),
        "connectorName": connector.get("name"),
        "connectorKind": connector.get("kind"),
        "remoteId": item.get("remote_id"),
        "name": item.get("remote_name") or item.get("remote_id"),
        "environment": item.get("environment"),
        "hosts": list(item.get("hosts") or []),
        "basePath": item.get("base_path"),
        "status": item.get("status"),
        "firstSeenAt": _iso(item.get("first_seen_at")),
        "lastSeenAt": _iso(item.get("last_seen_at")),
        "stale": stale,
    }
    if item.get("ignored_reason") is not None or item.get("status") == "ignored":
        view["ignored"] = {
            "reason": item.get("ignored_reason"),
            "at": _iso(item.get("ignored_at")),
            "by": str(item["ignored_by"]) if item.get("ignored_by") else None,
            "hosts": list(item.get("ignored_hosts") or []),
            "basePath": item.get("ignored_base_path"),
            "reappeared": _reappeared(item),
        }
    return view


def _drift(item: Mapping[str, Any], entry: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The drift record for a linked row, or ``None`` when it is in step (or cannot be judged).

    A row whose gateway reports neither a revision nor an update time (Azure API Management, whose
    revision number does not move on a policy edit) cannot be judged here, and is never reported.
    """
    remote_revision = item.get("remote_revision")
    remote_updated = item.get("remote_updated_at")
    if remote_revision is None and remote_updated is None:
        return None
    catalog_revision = (entry or {}).get("remote_revision") or item.get("imported_revision")
    decision = evaluate_refresh(
        remote_committed_at=remote_updated,
        last_imported_committed_at=item.get("imported_remote_updated_at"),
        remote_checksum=remote_revision,
        last_imported_checksum=catalog_revision,
    )
    if not decision.should_refresh:
        return None
    return {
        "deployedRevision": remote_revision,
        "deployedUpdatedAt": _iso(remote_updated),
        "catalogRevision": catalog_revision,
        "catalogVersionLabel": (entry or {}).get("version_label"),
        "reasonCode": decision.reason.value,
    }


def build_shadow_report(
    *,
    connectors: Sequence[Mapping[str, Any]],
    items: Sequence[Mapping[str, Any]],
    entries: Sequence[Mapping[str, Any]],
    connector_filter: Optional[str] = None,
    environment: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the report from plain rows.

    Args:
        connectors: Live connectors (``id``, ``name``, ``kind``, ``status``, ``last_success_at``).
        items: Their inventory rows that are not ``missing`` (catalog connector item columns plus the
            V283 ignore columns), already filtered by connector and environment.
        entries: Catalog entries: one per catalog item (its latest revision) and per Project with a
            published version (its latest published version) — ``project_id``, ``name``,
            ``publishable``, ``version_id``, ``version_label``, ``servers`` (URLs), ``remote_ids``
            and ``remote_revision`` (from the revision's connector provenance).
        connector_filter: The ``connector`` filter the caller applied, echoed back.
        environment: The ``environment`` filter the caller applied, echoed back.
        now: Clock override for tests.

    Returns:
        ``{generatedAt, filters, connectors, stale, summary, shadow, possibleMatches, undeployed,
        drift, ignored}``.
    """
    by_connector = {str(c["id"]): c for c in connectors}
    stale_ids = {cid for cid, c in by_connector.items() if c.get("status") == "failing"}
    entries_by_project = {str(e["project_id"]): e for e in entries}

    shadow: List[Dict[str, Any]] = []
    possible: List[Dict[str, Any]] = []
    drift: List[Dict[str, Any]] = []
    ignored: List[Dict[str, Any]] = []
    linked_projects: Set[str] = set()
    matched_projects: Set[str] = set()
    counts: Dict[str, int] = {}

    for item in items:
        connector = by_connector.get(str(item["connector_id"]))
        if connector is None or item.get("status") == "missing":
            continue
        counts[str(connector["id"])] = counts.get(str(connector["id"]), 0) + 1
        stale = str(connector["id"]) in stale_ids
        view = _item_view(item, connector, stale)
        if item.get("project_id"):
            project_id = str(item["project_id"])
            linked_projects.add(project_id)
            record = _drift(item, entries_by_project.get(project_id))
            if record is not None:
                drift.append({**view, "catalogItemId": project_id, **record})
            continue
        if item.get("status") == "ignored" and not view.get("ignored", {}).get("reappeared"):
            ignored.append(view)
            continue
        matches = match_item(item, entries)
        if matches:
            matched_projects.update(m["target"]["projectId"] for m in matches)
            possible.append({**view, "match": matches[0], "alternatives": matches[1 : 1 + MAX_ALTERNATIVES]})
        else:
            shadow.append(view)

    undeployed = [
        {
            **_entry_ref(entry),
            "servers": [url for url in entry.get("servers") or [] if server_endpoint(url) is not None],
        }
        for entry in entries
        if str(entry["project_id"]) not in linked_projects
        and str(entry["project_id"]) not in matched_projects
        and any(server_endpoint(url) is not None for url in entry.get("servers") or [])
    ]

    def by_name(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return sorted(
            rows, key=lambda r: (str(r.get("name") or "").lower(), str(r.get("itemId") or r.get("projectId")))
        )

    connector_views = [
        {
            "id": cid,
            "name": c.get("name"),
            "kind": c.get("kind"),
            "status": c.get("status"),
            "itemCount": counts.get(cid, 0),
            "stale": cid in stale_ids,
            "staleSince": _iso(c.get("last_success_at")) if cid in stale_ids else None,
        }
        for cid, c in sorted(by_connector.items(), key=lambda kv: str(kv[1].get("name") or "").lower())
    ]
    stale = [
        {
            "connectorId": view["id"],
            "connectorName": view["name"],
            "since": view["staleSince"],
            "message": (
                f"Inventory stale since {view['staleSince']}: the last sync of {view['name']} failed."
                if view["staleSince"]
                else f"Inventory stale: {view['name']} has never synced successfully."
            ),
        }
        for view in connector_views
        if view["stale"]
    ]
    sections = {
        "shadow": by_name(shadow),
        "possibleMatches": by_name(possible),
        "undeployed": by_name(undeployed),
        "drift": by_name(drift),
        "ignored": by_name(ignored),
    }
    return {
        "generatedAt": _iso(now or datetime.now(timezone.utc)),
        "filters": {"connector": connector_filter, "environment": environment},
        "connectors": connector_views,
        "stale": stale,
        "summary": {key: len(rows) for key, rows in sections.items()},
        **sections,
    }


def failing_categories(report: Mapping[str, Any], fail_on: Iterable[str]) -> List[str]:
    """The ``--fail-on`` categories that have at least one row in ``report``.

    Args:
        report: A report from :func:`build_shadow_report`.
        fail_on: Category names from :data:`CATEGORIES`.

    Returns:
        The named categories that are non-empty, in :data:`CATEGORIES` order.
    """
    keys = {"shadow": "shadow", "possible-matches": "possibleMatches", "undeployed": "undeployed", "drift": "drift"}
    wanted = set(fail_on)
    summary = report.get("summary") or {}
    return [c for c in CATEGORIES if c in wanted and int(summary.get(keys[c], 0)) > 0]
