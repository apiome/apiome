"""
Cross-protocol search over the normalized model (MFI-6.2, #3754).

"Find every API with a ``createOrder`` operation" — whatever format it was imported from. One
search runs Postgres full-text search over a tenant's normalized model and returns the matching
**operations**, **types** and **messages**, each with the API (project, revision) it belongs to and
that revision's paradigm, source format and quality grade, so the three facets can narrow the
result and compose with each other.

Two stores hold the normalized model, and the search reads both:

* **The canonical model** (MFI-2.2, V135): ``api_operations`` / ``api_types`` / ``api_messages``
  under a live ``api_artifacts`` row. The match predicates reuse V135's expression GIN indexes
  verbatim (``idx_api_operations_fts`` / ``idx_api_types_fts`` / ``idx_api_messages_fts``) — the
  ``to_tsvector`` expressions below must stay byte-for-byte equal to the index definitions, or the
  planner falls back to a sequential scan. Every import persists its canonical model (see
  :func:`app.import_source_pipeline.persist_adapter_import`), and catalog items imported before
  that are filled in by :mod:`app.canonical_model_reindex`.
* **The classic OpenAPI model**: an OpenAPI Project's operations (``version_path`` →
  ``path_operation``) and schemas (``classes``). A revision is read from here only when it has
  *no* live canonical artifact, so a revision present in both stores is never reported twice.

This module owns the pure parts — the statement, filter normalization, facet counting and paging —
so they are unit-tested without a database; :meth:`app.database.Database.search_normalized_model`
runs the statement and :mod:`app.model_search_routes` serves it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .browse_facets import normalize_format_filter, normalize_protocol_filter

__all__ = [
    "FACETS",
    "GRADE_VALUES",
    "HIT_KINDS",
    "MAX_QUERY_LENGTH",
    "SEARCH_HIT_CAP",
    "ModelSearchFilters",
    "build_model_search_sql",
    "facet_counts",
    "filter_hits",
    "normalize_grade_filter",
    "normalize_kind_filter",
    "ordered_buckets",
    "UNGRADED",
]


#: The kinds of normalized-model element a search returns, in presentation order.
HIT_KINDS: Tuple[str, ...] = ("operation", "type", "message")

#: The captured quality grades (``versions.quality_grade``, V124), best first.
GRADE_VALUES: Tuple[str, ...] = ("A", "B", "C", "D", "F")

#: Facet value for a revision that has no captured grade yet.
UNGRADED = "ungraded"

#: Longest query accepted; a longer one is refused with 422 rather than sent to the parser.
MAX_QUERY_LENGTH = 200

#: Rows past this many (best-ranked first) are not counted or paged; the response says so.
SEARCH_HIT_CAP = 2000

#: Index-matching ``to_tsvector`` expressions — identical to V135's GIN index definitions.
_OPERATION_TSV = (
    "to_tsvector('english', coalesce(o.name, '') || ' ' || coalesce(o.description, '') || ' ' || "
    "coalesce(o.http_path, '') || ' ' || coalesce(o.key, ''))"
)
_TYPE_TSV = (
    "to_tsvector('english', coalesce(t.name, '') || ' ' || coalesce(t.description, '') || ' ' || "
    "coalesce(t.key, ''))"
)
_MESSAGE_TSV = "to_tsvector('english', coalesce(m.name, '') || ' ' || coalesce(m.description, ''))"

#: Classic OpenAPI text (no index; scoped to the tenant's revisions first, so it stays small).
_CLASSIC_OPERATION_TSV = (
    "to_tsvector('english', coalesce(vp.pathname, '') || ' ' || coalesce(pod.operation_id, '') "
    "|| ' ' || coalesce(pod.summary, '') || ' ' || coalesce(pod.description, ''))"
)
_CLASSIC_TYPE_TSV = (
    "to_tsvector('english', coalesce(c.name, '') || ' ' || coalesce(c.description, ''))"
)


@dataclass(frozen=True)
class ModelSearchFilters:
    """The facet selection of a search: values within a facet OR together, facets AND.

    Attributes:
        kinds: Element kinds to keep (``operation`` / ``type`` / ``message``); empty = all.
        protocols: Paradigms to keep (``rest``, ``rpc``, …); empty = all.
        formats: Source-format keys to keep (``openapi-3.1``, ``protobuf``, …); empty = all.
        grades: Grades to keep (``A``–``F`` or ``ungraded``); empty = all.
    """

    kinds: Tuple[str, ...] = ()
    protocols: Tuple[str, ...] = ()
    formats: Tuple[str, ...] = ()
    grades: Tuple[str, ...] = ()

    @classmethod
    def from_query(
        cls,
        *,
        kinds: Optional[Iterable[str]] = None,
        protocols: Optional[Iterable[str]] = None,
        formats: Optional[Iterable[str]] = None,
        grades: Optional[Iterable[str]] = None,
    ) -> "ModelSearchFilters":
        """Build a selection from repeatable query parameters, normalizing every value.

        Blank values are dropped and duplicates collapse. An unknown value is kept in its
        normalized form, so it narrows to nothing instead of failing the request — the same
        "filters only narrow" contract as the browse and catalog facets.

        Args:
            kinds: Raw ``kind`` values.
            protocols: Raw ``protocol`` values (aliases such as ``grpc`` or ``graphql`` work).
            formats: Raw ``format`` values.
            grades: Raw ``grade`` values (case-insensitive).

        Returns:
            The normalized selection.
        """
        return cls(
            kinds=_normalized(kinds, normalize_kind_filter),
            protocols=_normalized(protocols, normalize_protocol_filter),
            formats=_normalized(formats, normalize_format_filter),
            grades=_normalized(grades, normalize_grade_filter),
        )

    def selected(self, facet: str) -> Tuple[str, ...]:
        """The selected values of one facet (``kind`` / ``protocol`` / ``format`` / ``grade``)."""
        return {
            "kind": self.kinds,
            "protocol": self.protocols,
            "format": self.formats,
            "grade": self.grades,
        }[facet]


def _normalized(values: Optional[Iterable[str]], normalize: Any) -> Tuple[str, ...]:
    """Normalize, drop blanks and de-duplicate a repeatable parameter, keeping first-seen order."""
    kept: List[str] = []
    for value in values or ():
        token = normalize(value)
        if token and token not in kept:
            kept.append(token)
    return tuple(kept)


def normalize_kind_filter(value: Optional[str]) -> Optional[str]:
    """Normalize a ``kind`` filter (``Operations`` → ``operation``; ``schema`` → ``type``).

    Args:
        value: The raw value, or None.

    Returns:
        The normalized kind, the lower-cased unknown token, or None when blank.
    """
    raw = (value or "").strip().lower()
    if not raw:
        return None
    aliases = {
        "operations": "operation",
        "op": "operation",
        "method": "operation",
        "types": "type",
        "schema": "type",
        "schemas": "type",
        "messages": "message",
        "payload": "message",
    }
    return aliases.get(raw, raw)


def normalize_grade_filter(value: Optional[str]) -> Optional[str]:
    """Normalize a ``grade`` filter: a letter is upper-cased, ``ungraded`` is kept as is.

    Args:
        value: The raw value, or None.

    Returns:
        ``A``–``F``, ``ungraded``, the upper-cased unknown token, or None when blank.
    """
    raw = (value or "").strip()
    if not raw:
        return None
    if raw.lower() in (UNGRADED, "none", "null"):
        return UNGRADED
    return raw.upper()[:8]


def build_model_search_sql(
    *, tenant_id: str, query: str, all_versions: bool = False, cap: int = SEARCH_HIT_CAP
) -> Tuple[str, Dict[str, Any]]:
    """Build the one statement that finds every normalized-model element matching ``query``.

    The query text goes through ``websearch_to_tsquery('english', …)``: words AND together,
    ``"quoted phrases"`` match in order, ``or`` alternates and ``-word`` excludes; the English
    stemmer folds ``createOrder`` and ``CreateOrder`` to the same lexeme. Rows are ranked with
    ``ts_rank`` and capped at ``cap``, best first; filters and facets are applied afterwards
    (:func:`filter_hits`, :func:`facet_counts`) so every facet can be counted from one round trip.

    Args:
        tenant_id: The tenant whose projects are searched (catalog items and Projects alike).
        query: The visitor's search text (already length-checked by the caller).
        all_versions: Search every live revision instead of each project's latest.
        cap: Maximum rows returned.

    Returns:
        The SQL text and its named parameters for ``cursor.execute``.
    """
    version_scope = (
        "SELECT v.id, v.version_id, v.quality_grade, v.source_format, v.protocol, v.created_at "
        "FROM apiome.versions v WHERE v.project_id = p.id AND v.deleted_at IS NULL"
    )
    if not all_versions:
        version_scope += " ORDER BY v.created_at DESC NULLS LAST, v.id DESC LIMIT 1"

    # The match predicates call websearch_to_tsquery inline (not via the ``q`` CTE) so the
    # planner can turn them into V135 GIN index conditions; ``q`` only feeds ts_rank.
    sql = f"""
        WITH q AS (SELECT websearch_to_tsquery('english', %(query)s) AS tsq),
        scope AS (
            SELECT sv.id AS version_pk, sv.version_id AS version_label, sv.quality_grade,
                   sv.source_format AS version_format, sv.protocol AS version_protocol,
                   p.id AS project_id, p.slug AS project_slug, p.name AS project_name,
                   p.publishable
            FROM apiome.projects p
            JOIN LATERAL ({version_scope}) sv ON TRUE
            WHERE p.tenant_id = %(tenant_id)s AND p.deleted_at IS NULL
        ),
        art AS (
            SELECT a.id AS artifact_id, a.version_id, a.paradigm, a.format
            FROM apiome.api_artifacts a
            JOIN scope s ON s.version_pk = a.version_id
            WHERE a.tenant_id = %(tenant_id)s AND a.deleted_at IS NULL
        ),
        hits AS (
            SELECT 'operation' AS kind, o.id::text AS element_id, o.version_id,
                   o.name AS name, o.key AS element_key, o.kind AS detail,
                   o.http_method AS method, o.http_path AS path, svc.name AS parent,
                   LEFT(o.description, 400) AS snippet, art.paradigm, art.format,
                   'canonical' AS store, ts_rank({_OPERATION_TSV}, q.tsq) AS rank
            FROM apiome.api_operations o
            JOIN apiome.api_services svc ON svc.id = o.service_id AND svc.deleted_at IS NULL
            JOIN art ON art.artifact_id = svc.artifact_id
            CROSS JOIN q
            WHERE o.tenant_id = %(tenant_id)s AND o.deleted_at IS NULL
              AND {_OPERATION_TSV} @@ websearch_to_tsquery('english', %(query)s)
            UNION ALL
            SELECT 'type', t.id::text, t.version_id,
                   t.name, t.key, t.kind,
                   NULL, NULL, t.namespace,
                   LEFT(t.description, 400), art.paradigm, art.format,
                   'canonical', ts_rank({_TYPE_TSV}, q.tsq)
            FROM apiome.api_types t
            JOIN art ON art.artifact_id = t.artifact_id
            CROSS JOIN q
            WHERE t.tenant_id = %(tenant_id)s AND t.deleted_at IS NULL
              AND {_TYPE_TSV} @@ websearch_to_tsquery('english', %(query)s)
            UNION ALL
            SELECT 'message', m.id::text, m.version_id,
                   COALESCE(NULLIF(m.name, ''), o.name || ' ' || m.role), m.key, m.role,
                   o.http_method, o.http_path, o.name,
                   LEFT(m.description, 400), art.paradigm, art.format,
                   'canonical', ts_rank({_MESSAGE_TSV}, q.tsq)
            FROM apiome.api_messages m
            JOIN apiome.api_operations o ON o.id = m.operation_id AND o.deleted_at IS NULL
            JOIN apiome.api_services svc ON svc.id = o.service_id AND svc.deleted_at IS NULL
            JOIN art ON art.artifact_id = svc.artifact_id
            CROSS JOIN q
            WHERE m.tenant_id = %(tenant_id)s AND m.deleted_at IS NULL
              AND {_MESSAGE_TSV} @@ websearch_to_tsquery('english', %(query)s)
            UNION ALL
            SELECT 'operation', po.id::text, s.version_pk,
                   COALESCE(NULLIF(TRIM(pod.operation_id), ''), NULLIF(TRIM(pod.summary), ''),
                            UPPER(po.operation) || ' ' || vp.pathname),
                   UPPER(po.operation) || ' ' || vp.pathname, 'request_response',
                   UPPER(po.operation), vp.pathname, NULL,
                   LEFT(COALESCE(NULLIF(TRIM(pod.description), ''), pod.summary), 400),
                   COALESCE(NULLIF(TRIM(s.version_protocol), ''), 'rest'),
                   COALESCE(NULLIF(TRIM(s.version_format), ''), 'openapi'),
                   'openapi', ts_rank({_CLASSIC_OPERATION_TSV}, q.tsq)
            FROM scope s
            JOIN apiome.version_path vp ON vp.version_id = s.version_pk
            JOIN apiome.path_operation po ON po.version_path_id = vp.id
            LEFT JOIN apiome.path_operation_description pod ON pod.path_operation_id = po.id
            CROSS JOIN q
            WHERE NOT EXISTS (SELECT 1 FROM art WHERE art.version_id = s.version_pk)
              AND {_CLASSIC_OPERATION_TSV} @@ websearch_to_tsquery('english', %(query)s)
            UNION ALL
            SELECT 'type', c.id::text, s.version_pk,
                   c.name, c.name, 'record',
                   NULL, NULL, NULL,
                   LEFT(c.description, 400),
                   COALESCE(NULLIF(TRIM(s.version_protocol), ''), 'rest'),
                   COALESCE(NULLIF(TRIM(s.version_format), ''), 'openapi'),
                   'openapi', ts_rank({_CLASSIC_TYPE_TSV}, q.tsq)
            FROM scope s
            JOIN apiome.classes c ON c.version_id = s.version_pk AND c.deleted_at IS NULL
            CROSS JOIN q
            WHERE NOT EXISTS (SELECT 1 FROM art WHERE art.version_id = s.version_pk)
              AND {_CLASSIC_TYPE_TSV} @@ websearch_to_tsquery('english', %(query)s)
        )
        SELECT h.kind, h.element_id, h.name, h.element_key, h.detail, h.method, h.path,
               h.parent, h.snippet, LOWER(h.paradigm) AS paradigm, LOWER(h.format) AS format,
               h.store, h.rank,
               s.project_id::text AS project_id, s.project_slug, s.project_name, s.publishable,
               s.version_pk::text AS version_record_id, s.version_label, s.quality_grade
        FROM hits h
        JOIN scope s ON s.version_pk = h.version_id
        ORDER BY h.rank DESC, h.name ASC, h.element_id ASC
        LIMIT %(cap)s
    """
    return sql, {"query": query, "tenant_id": tenant_id, "cap": int(cap)}


def _hit_value(hit: Mapping[str, Any], facet: str) -> str:
    """The value a hit contributes to one facet (``ungraded`` for a revision with no grade)."""
    if facet == "kind":
        return str(hit.get("kind") or "")
    if facet == "protocol":
        return normalize_protocol_filter(hit.get("paradigm")) or ""
    if facet == "format":
        return normalize_format_filter(hit.get("format")) or ""
    grade = normalize_grade_filter(hit.get("quality_grade"))
    return grade or UNGRADED


#: The four facets, in the order the response lists them.
FACETS: Tuple[str, ...] = ("kind", "protocol", "format", "grade")


def _keeps(hit: Mapping[str, Any], filters: ModelSearchFilters, *, skip: Optional[str]) -> bool:
    """Whether a hit survives every facet of ``filters`` except ``skip``."""
    for facet in FACETS:
        if facet == skip:
            continue
        selected = filters.selected(facet)
        if selected and _hit_value(hit, facet) not in selected:
            return False
    return True


def filter_hits(
    hits: Sequence[Mapping[str, Any]], filters: ModelSearchFilters
) -> List[Mapping[str, Any]]:
    """Keep the hits that every selected facet allows (values OR within a facet, facets AND).

    Args:
        hits: Rows from the search statement.
        filters: The facet selection.

    Returns:
        The kept rows, in their original (rank) order.
    """
    return [hit for hit in hits if _keeps(hit, filters, skip=None)]


def facet_counts(
    hits: Sequence[Mapping[str, Any]], filters: ModelSearchFilters
) -> Dict[str, Dict[str, int]]:
    """Count each facet's values over the hits every *other* facet keeps.

    That is what makes facets compose: a count says how many results ticking that value would
    show given the rest of the selection. A selected value is always listed, at 0 when nothing
    matches it, so the client can still render (and clear) it.

    Args:
        hits: Rows from the search statement (before filtering).
        filters: The facet selection.

    Returns:
        ``{"kind": {...}, "protocol": {...}, "format": {...}, "grade": {...}}`` value → count.
    """
    counts: Dict[str, Dict[str, int]] = {}
    for facet in FACETS:
        bucket: Dict[str, int] = {value: 0 for value in filters.selected(facet)}
        for hit in hits:
            if not _keeps(hit, filters, skip=facet):
                continue
            value = _hit_value(hit, facet)
            if value:
                bucket[value] = bucket.get(value, 0) + 1
        counts[facet] = bucket
    return counts


def ordered_buckets(facet: str, bucket: Mapping[str, int]) -> List[Tuple[str, int]]:
    """Order a facet's buckets for display: fixed vocabularies first, then by count, then name.

    Kinds and grades follow their fixed order (``operation``, ``type``, ``message``; ``A``…``F``,
    ``ungraded``); protocol and format buckets are sorted by count descending, then value.

    Args:
        facet: The facet name.
        bucket: Value → count.

    Returns:
        ``(value, count)`` pairs in display order.
    """
    fixed = {"kind": HIT_KINDS, "grade": GRADE_VALUES + (UNGRADED,)}.get(facet)
    if fixed is not None:
        rank = {value: index for index, value in enumerate(fixed)}
        return sorted(bucket.items(), key=lambda kv: (rank.get(kv[0], len(rank)), kv[0]))
    return sorted(bucket.items(), key=lambda kv: (-kv[1], kv[0]))
