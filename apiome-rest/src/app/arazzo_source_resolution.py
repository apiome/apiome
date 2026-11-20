"""Arazzo ``sourceDescriptions`` resolution — COA-1.2 (#7038).

An Arazzo workflow names the API descriptions it calls in ``sourceDescriptions[].url``. This
module decides where each of them comes from, in a fixed order:

1. **fileset** — a relative ``url`` that names a member of the same upload, archive or
   repository selection (:func:`resolve_fileset_sources`, called from
   :meth:`app.arazzo_import_source.ArazzoImportSource.parse_fileset`);
2. **catalog** — a description the tenant already imported: the spec read from the same
   repository and branch at that path, or the spec imported from that exact URL
   (:data:`CatalogSourceLookup`, supplied by the pipeline);
3. **remote** — an absolute ``http``/``https`` URL fetched through the SSRF-guarded remote
   document fetcher (:func:`app.remote_ref_resolver.fetch_remote_documents`), only when the
   import opted in to remote resolution and the deployment allows it.

A source none of the tiers resolves is never dropped: it is returned as an
:class:`UnresolvedSource` with a stable reason code, which the pipeline puts in the import
report (the job summary's ``arazzo_sources`` block) and as a warning event.

The module also carries the syntactic scan archive, bulk and git intake use to see that an
Arazzo document references its siblings (:func:`source_description_urls`), so a zip of a
workflow and the OpenAPI files it calls resolves the workflow as its root, and a ticked
workflow in a repository arrives with the files it names.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from posixpath import dirname, normpath
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "REASON_INVALID_ENTRY",
    "REASON_NOT_IN_FILESET",
    "REASON_RELATIVE_WITHOUT_FILESET",
    "REASON_UNPARSEABLE_MEMBER",
    "TIER_CATALOG",
    "TIER_FILESET",
    "TIER_REMOTE",
    "ArazzoSourceOutcome",
    "CatalogSourceLookup",
    "ResolvedSource",
    "UnresolvedSource",
    "member_candidates",
    "resolve_fileset_sources",
    "resolve_remaining_sources",
    "source_description_urls",
]

#: Where a source was resolved from (stable strings; they reach the job summary).
TIER_FILESET = "fileset"
TIER_CATALOG = "catalog"
TIER_REMOTE = "remote"

#: A relative ``url`` that names no member of the fileset and no catalog spec.
REASON_NOT_IN_FILESET = "not-in-fileset"
#: A relative ``url`` on a single-file import (nothing to resolve it against) and no catalog spec.
REASON_RELATIVE_WITHOUT_FILESET = "relative-without-fileset"
#: A relative ``url`` that names a fileset member which is not parseable JSON/YAML.
REASON_UNPARSEABLE_MEMBER = "unparseable-member"
#: A ``sourceDescriptions`` entry without a usable ``name`` or ``url``.
REASON_INVALID_ENTRY = "invalid-source-description"

#: Fileset members that are documents a workflow's sources could resolve to.
_DOCUMENT_SUFFIXES = (".yaml", ".yml", ".json")

#: Cap on how many sources are itemized in the job summary; the counts stay exact.
_MAX_REPORTED_SOURCES = 25

#: The ``arazzo: <version>`` marker, at the start of a line (YAML) or as a JSON key.
_ARAZZO_MARKER_RE = re.compile(r"""(?:^|[{,\s])["']?arazzo["']?\s*:""", re.MULTILINE)

#: A ``url`` value, YAML (quoted or bare) or JSON. Deliberately syntactic, like the other
#: intake reference scans: a value it picks up only matters when it names a member.
_URL_VALUE_RE = re.compile(
    r"""["']?\burl["']?\s*:\s*(?:"([^"\n]+)"|'([^'\n]+)'|([^\s"'{}\[\],#]+))"""
)

#: Looks up a source the tenant already imported. Called with the declared ``url`` and the
#: fileset-relative paths it could name (empty for an absolute URL); returns a mapping that
#: describes the catalog spec (``project_id``, ``version_id``, ``path`` …) or ``None``.
CatalogSourceLookup = Callable[[str, Tuple[str, ...]], Optional[Mapping[str, Any]]]

#: Fetches absolute URLs, returning :class:`app.remote_ref_resolver.FetchedDocument` by URL.
RemoteFetcher = Callable[[Sequence[str]], Mapping[str, Any]]


@dataclass(frozen=True)
class ResolvedSource:
    """One ``sourceDescriptions`` entry that was resolved, and from where.

    Attributes:
        name: The source's ``name``.
        url: The declared ``url``.
        tier: :data:`TIER_FILESET`, :data:`TIER_CATALOG` or :data:`TIER_REMOTE`.
        path: The fileset member (fileset tier) or repository path (catalog tier), if any.
        project_id: The catalog project that holds the spec (catalog tier).
        version_id: The catalog version that holds the spec (catalog tier), when known.
        digest: SHA-256 of the fetched document (remote tier).
    """

    name: str
    url: str
    tier: str
    path: Optional[str] = None
    project_id: Optional[str] = None
    version_id: Optional[str] = None
    digest: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for the job summary, leaving out fields that do not apply."""
        record: Dict[str, Any] = {"name": self.name, "url": self.url, "tier": self.tier}
        for key in ("path", "project_id", "version_id", "digest"):
            value = getattr(self, key)
            if value is not None:
                record[key] = value
        return record


@dataclass(frozen=True)
class UnresolvedSource:
    """One ``sourceDescriptions`` entry no tier resolved, and why.

    Attributes:
        name: The source's ``name`` (``""`` when the entry has none).
        url: The declared ``url`` (``""`` when the entry has none).
        reason: A stable code: one of this module's ``REASON_*`` constants, or a
            :mod:`app.remote_ref_resolver` reason for a remote fetch that failed
            (``resolution-disabled``, ``blocked-by-ssrf-guard``, ``fetch-failed`` …).
        detail: Human-readable detail.
    """

    name: str
    url: str
    reason: str
    detail: str = ""

    def as_dict(self) -> Dict[str, Any]:
        """Serialize for the job summary."""
        return {"name": self.name, "url": self.url, "reason": self.reason, "detail": self.detail}


@dataclass(frozen=True)
class ArazzoSourceOutcome:
    """Where every source of one workflow came from.

    Attributes:
        resolved: Resolved sources, in declaration order.
        unresolved: Unresolved sources, in declaration order.
        remote_documents: Parsed documents fetched by the remote tier, as
            ``{"name", "url", "type"?, "content"}`` records in the shape
            ``resolved_sources`` uses, so the lint pack can read them.
    """

    resolved: Tuple[ResolvedSource, ...] = ()
    unresolved: Tuple[UnresolvedSource, ...] = ()
    remote_documents: Tuple[Dict[str, Any], ...] = ()

    def report(self) -> Dict[str, Any]:
        """Build the deterministic ``arazzo_sources`` block for the job summary.

        Counts are exact; the itemized lists are capped at :data:`_MAX_REPORTED_SOURCES`.
        """
        by_tier: Dict[str, int] = {TIER_FILESET: 0, TIER_CATALOG: 0, TIER_REMOTE: 0}
        for source in self.resolved:
            by_tier[source.tier] = by_tier.get(source.tier, 0) + 1
        return {
            "resolved": len(self.resolved),
            "unresolved": len(self.unresolved),
            "by_tier": by_tier,
            "sources": [source.as_dict() for source in self.resolved[:_MAX_REPORTED_SOURCES]],
            "unresolved_sources": [
                source.as_dict() for source in self.unresolved[:_MAX_REPORTED_SOURCES]
            ],
            "truncated": max(len(self.resolved), len(self.unresolved)) > _MAX_REPORTED_SOURCES,
        }


# ---------------------------------------------------------------------------
# Syntactic scan (archive / bulk / git intake)
# ---------------------------------------------------------------------------


def source_description_urls(text: str) -> List[str]:
    """Return the ``url`` values an Arazzo document's text declares, without parsing it.

    Archive root ranking and the bulk/git reference closure scan every member's text, so a
    full parse per member is not affordable there. A document without an ``arazzo:`` marker
    yields nothing, which keeps an OpenAPI ``servers[].url`` from ever being read as a file
    reference.

    Args:
        text: A member's decoded text.

    Returns:
        The raw ``url`` values in order of appearance (callers resolve them against members).
    """
    if not text or not _ARAZZO_MARKER_RE.search(text):
        return []
    urls: List[str] = []
    for match in _URL_VALUE_RE.finditer(text):
        value = (match.group(1) or match.group(2) or match.group(3) or "").strip()
        if value:
            urls.append(value)
    return urls


def _is_absolute(url: str) -> bool:
    """Whether ``url`` carries a scheme (``https://…``, ``urn:…``) rather than being a path."""
    return bool(re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", url))


def member_candidates(url: str, root_path: str) -> Tuple[str, ...]:
    """Fileset member paths a ``sourceDescriptions[].url`` could name.

    Args:
        url: The declared source URL.
        root_path: The workflow member's own path inside the set.

    Returns:
        Candidate member paths, most specific first: the URL resolved relative to the
        workflow's own directory, then relative to the set root. Absolute URLs (with a
        scheme), fragment-only values and paths that climb out of the set yield nothing.
    """
    candidate = url.strip()
    if not candidate or _is_absolute(candidate) or candidate.startswith(("#", "//")):
        return ()
    candidate = candidate.split("#", 1)[0].lstrip("/")
    if not candidate:
        return ()
    directory = dirname(root_path)
    paths = []
    for joined in ((f"{directory}/{candidate}" if directory else candidate), candidate):
        resolved = normpath(joined)
        if resolved == ".." or resolved.startswith("../"):
            continue
        paths.append(resolved)
    return tuple(dict.fromkeys(paths))


# ---------------------------------------------------------------------------
# Tier 1: the fileset
# ---------------------------------------------------------------------------


def _source_entries(document: Mapping[str, Any]) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    """Yield ``(name, url, entry)`` for every ``sourceDescriptions`` entry, valid or not."""
    source_descriptions = document.get("sourceDescriptions")
    if not isinstance(source_descriptions, list):
        return
    for entry in source_descriptions:
        if not isinstance(entry, dict):
            yield "", "", {}
            continue
        name = entry.get("name")
        url = entry.get("url")
        yield (
            name.strip() if isinstance(name, str) else "",
            url.strip() if isinstance(url, str) else "",
            entry,
        )


def resolve_fileset_sources(
    document: Mapping[str, Any],
    root_path: str,
    documents: Mapping[str, Any],
    *,
    unparseable: Iterable[str] = (),
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Match each relative ``sourceDescriptions[].url`` to a parsed fileset member.

    Args:
        document: The parsed Arazzo workflow document.
        root_path: The workflow member's path inside the set.
        documents: Every parseable member, keyed by path.
        unparseable: Member paths that exist but did not parse as JSON/YAML.

    Returns:
        ``(resolved, pending)``. ``resolved`` has one record per source matched to a member,
        each with its ``name``, declared ``type``, the member ``path`` and that member's
        parsed ``content`` (the shape the lint pack reads). ``pending`` has one record per
        source still to resolve, each with ``name``, ``url``, ``type`` and the fileset
        ``reason`` it was not found (``None`` for an absolute URL, which the fileset could
        never hold).
    """
    unparseable_members = set(unparseable)
    resolved: List[Dict[str, Any]] = []
    pending: List[Dict[str, Any]] = []
    for name, url, entry in _source_entries(document):
        source_type = entry.get("type") if isinstance(entry.get("type"), str) else None
        if not name or not url:
            pending.append(
                {"name": name, "url": url, "type": source_type, "reason": REASON_INVALID_ENTRY}
            )
            continue
        candidates = member_candidates(url, root_path)
        match = next(
            (
                path
                for path in candidates
                if path != root_path
                and path in documents
                and path.lower().endswith(_DOCUMENT_SUFFIXES)
            ),
            None,
        )
        if match is not None:
            record: Dict[str, Any] = {"name": name, "path": match, "content": documents[match]}
            if source_type is not None:
                record["type"] = source_type
            resolved.append(record)
            continue
        if not candidates:
            reason = None
        elif any(path in unparseable_members for path in candidates):
            reason = REASON_UNPARSEABLE_MEMBER
        else:
            reason = REASON_NOT_IN_FILESET
        pending.append({"name": name, "url": url, "type": source_type, "reason": reason})
    return resolved, pending


# ---------------------------------------------------------------------------
# Tiers 2 and 3: the catalog, then remote
# ---------------------------------------------------------------------------


def resolve_remaining_sources(
    document: Mapping[str, Any],
    *,
    root_path: str = "",
    fileset_resolved: Sequence[Mapping[str, Any]] = (),
    pending: Optional[Sequence[Mapping[str, Any]]] = None,
    catalog_lookup: Optional[CatalogSourceLookup] = None,
    remote_fetcher: Optional[RemoteFetcher] = None,
) -> ArazzoSourceOutcome:
    """Resolve the sources the fileset did not hold, catalog first, then remote.

    Args:
        document: The parsed Arazzo workflow document.
        root_path: The workflow's member path in its fileset (``""`` for a single file).
        fileset_resolved: The records :func:`resolve_fileset_sources` resolved.
        pending: The records :func:`resolve_fileset_sources` left pending, or ``None`` for a
            single-file import (every source is then pending).
        catalog_lookup: Looks a source up among the tenant's imported specs; ``None`` skips
            the catalog tier. A lookup that raises counts as no match.
        remote_fetcher: Fetches absolute URLs through the SSRF guard; ``None`` means remote
            resolution is off for this import, reported as ``resolution-disabled``.

    Returns:
        The :class:`ArazzoSourceOutcome`, with every declared source either resolved or
        unresolved — none is left out.
    """
    from .remote_ref_resolver import REASON_DISABLED

    single_file = pending is None
    if pending is None:
        pending = [
            {
                "name": name,
                "url": url,
                "type": entry.get("type") if isinstance(entry.get("type"), str) else None,
                "reason": REASON_INVALID_ENTRY if not name or not url else None,
            }
            for name, url, entry in _source_entries(document)
        ]

    url_by_name = {name: url for name, url, _entry in _source_entries(document) if name}
    resolved: List[ResolvedSource] = [
        ResolvedSource(
            name=str(record.get("name")),
            url=url_by_name.get(str(record.get("name")), ""),
            tier=TIER_FILESET,
            path=record.get("path"),
        )
        for record in fileset_resolved
    ]
    unresolved: List[UnresolvedSource] = []
    remote_wanted: List[Mapping[str, Any]] = []

    for record in pending:
        name = str(record.get("name") or "")
        url = str(record.get("url") or "")
        if record.get("reason") == REASON_INVALID_ENTRY:
            unresolved.append(
                UnresolvedSource(
                    name=name,
                    url=url,
                    reason=REASON_INVALID_ENTRY,
                    detail="the entry needs both a `name` and a `url`",
                )
            )
            continue
        candidates = member_candidates(url, root_path)
        match = _catalog_match(catalog_lookup, url, candidates)
        if match is not None:
            resolved.append(
                ResolvedSource(
                    name=name,
                    url=url,
                    tier=TIER_CATALOG,
                    path=_optional_str(match.get("path")),
                    project_id=_optional_str(match.get("project_id")),
                    version_id=_optional_str(match.get("version_id")),
                )
            )
            continue
        if candidates or not _is_absolute(url):
            reason = record.get("reason") or (
                REASON_RELATIVE_WITHOUT_FILESET if single_file else REASON_NOT_IN_FILESET
            )
            unresolved.append(
                UnresolvedSource(name=name, url=url, reason=str(reason), detail=_detail(reason))
            )
            continue
        if remote_fetcher is None:
            unresolved.append(
                UnresolvedSource(
                    name=name,
                    url=url,
                    reason=REASON_DISABLED,
                    detail="remote resolution is off for this import",
                )
            )
            continue
        remote_wanted.append(record)

    remote_documents: List[Dict[str, Any]] = []
    if remote_wanted and remote_fetcher is not None:
        fetched = remote_fetcher([str(record["url"]) for record in remote_wanted])
        for record in remote_wanted:
            name, url = str(record["name"]), str(record["url"])
            outcome = fetched.get(url)
            document_value = getattr(outcome, "document", None)
            if outcome is None or not isinstance(document_value, dict):
                unresolved.append(
                    UnresolvedSource(
                        name=name,
                        url=url,
                        reason=getattr(outcome, "reason", None) or "unparseable-document",
                        detail=getattr(outcome, "detail", "") or "",
                    )
                )
                continue
            resolved.append(
                ResolvedSource(name=name, url=url, tier=TIER_REMOTE, digest=outcome.digest)
            )
            entry: Dict[str, Any] = {"name": name, "url": url, "content": document_value}
            if record.get("type"):
                entry["type"] = record["type"]
            remote_documents.append(entry)

    order = {name: index for index, (name, _url, _entry) in enumerate(_source_entries(document))}
    resolved.sort(key=lambda source: order.get(source.name, len(order)))
    return ArazzoSourceOutcome(
        resolved=tuple(resolved),
        unresolved=tuple(unresolved),
        remote_documents=tuple(remote_documents),
    )


def _catalog_match(
    lookup: Optional[CatalogSourceLookup], url: str, candidates: Tuple[str, ...]
) -> Optional[Mapping[str, Any]]:
    """Run the catalog lookup for one source, treating a fault as "not in the catalog"."""
    if lookup is None:
        return None
    try:
        match = lookup(url, candidates)
    except Exception:  # noqa: BLE001 - the catalog tier is best-effort
        return None
    return match if isinstance(match, Mapping) else None


def _optional_str(value: Any) -> Optional[str]:
    """``str(value)``, or ``None`` for a missing value."""
    return None if value is None else str(value)


def _detail(reason: Any) -> str:
    """The human-readable detail for a fileset-tier reason."""
    if reason == REASON_UNPARSEABLE_MEMBER:
        return "the fileset member it names is not valid JSON or YAML"
    if reason == REASON_RELATIVE_WITHOUT_FILESET:
        return "a relative source needs the file next to the workflow (upload a zip) or in the catalog"
    return "no fileset member or catalog spec has that path"
