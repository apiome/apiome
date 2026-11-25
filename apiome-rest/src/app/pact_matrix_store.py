"""Reading the Pact matrix from Postgres — PFX-1.6 (#6919).

:mod:`app.pact_matrix` says what a matrix query *means*; this module answers one from the tables
of PFX-1.1 to 1.5 (apiome-db V432 to V435). Nothing here writes.

:func:`query_matrix` follows the Pact Broker's ``Matrix::Repository#find``:

1. **Resolve** every ``ignore`` selector, then every selector the caller wrote, to pacticipant
   versions (:func:`_find_versions`).
2. **Find the integrations** the query involves. With a destination (``tag``, ``environment``,
   ``latest``, ``mainBranch``) or a single selector: every integration of the named pacticipants —
   as a consumer (the providers of the pacts *that version* published; required) and as a provider
   (every consumer with a pact for it; not required). Otherwise: only the integrations between the
   named pacticipants.
3. **Infer** a selector for each other pacticipant of those integrations from the destination:
   its versions in the environment, its latest version with the tag, and so on.
4. **Read the rows**: the pacts the selected consumer versions published, each left-joined to the
   verification results of the selected provider versions — so a pact that the provider version in
   question never verified still gives a row, with no result.
5. Collapse (``latestby``); to an environment, give every version there its own row
   (:func:`app.pact_matrix.expand_unverified`); filter, set ignored rows aside, and sort.

**Named statements.** The two statements every query runs — the rows and the version details —
are prepared once per connection (``PREPARE`` / ``EXECUTE``), so a matrix query does not pay to
plan them again; on a small catalogue planning costs more than running them. See
:func:`_execute_named`.

**Tenancy.** Pacticipants are looked up in the caller's tenant; every other id in a query comes
from those rows, and the row statements join ``pacticipant`` on ``tenant_id`` again. Nothing
reaches another tenant.

Every function takes the :class:`~app.database.Database` it runs on, so the live-database tests can
pass one bound to a rolled-back transaction.
"""

from __future__ import annotations

import re
import threading
import weakref
from typing import Any, Dict, List, MutableMapping, Optional, Sequence, Set, Tuple

import psycopg2
import psycopg2.errors

from .pact_environment import EnvironmentRecord
from .pact_environment_store import list_environments
from .pact_matrix import (
    IGNORED,
    INFERRED,
    SPECIFIED,
    Integration,
    MatrixOptions,
    MatrixResult,
    MatrixRow,
    ResolvedSelector,
    UnresolvedSelector,
    _invalid,
    apply_latestby,
    apply_success_filter,
    expand_unverified,
    resolve_selector,
    sort_rows,
    split_ignored,
)
from .pacticipant import PacticipantValidationError
from .pacticipant_store import get_pacticipant

__all__ = ["MAX_SELECTORS", "MAX_VERSIONS_PER_SELECTOR", "query_matrix", "read_version_details"]

#: The most selectors, ``ignore`` selectors included, one query may carry. Each costs a lookup.
MAX_SELECTORS = 100

#: The most versions one selector may stand for (every version with a tag, say). The newest win.
MAX_VERSIONS_PER_SELECTOR = 1000

_Pacticipant = Dict[str, Any]

# ---------------------------------------------------------------------------------------------
# Named statements
# ---------------------------------------------------------------------------------------------

#: The statements already prepared on each live connection.
_PREPARED: "MutableMapping[Any, Set[str]]" = weakref.WeakKeyDictionary()
_PREPARED_LOCK = threading.Lock()

_PLACEHOLDER = re.compile(r"\$(\d+)")


def _execute_named(db: Any, name: str, sql: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    """Run a statement by name, preparing it on the connection the first time.

    Args:
        db: The database.
        name: The statement's name, unique in the service.
        sql: The statement, with ``$1`` … ``$n`` placeholders, each cast to its type.
        params: The values, in placeholder order. Arrays are passed as Postgres array literals
            (:func:`_array`) so they take the placeholder's type.

    Returns:
        The rows.
    """
    conn = db.connect()
    try:
        with _PREPARED_LOCK:
            prepared = _PREPARED.setdefault(conn, set())
    except TypeError:
        # Not a real connection (a test double): run the statement as it is.
        named = {f"p{index + 1}": value for index, value in enumerate(params)}
        return [dict(row) for row in db.execute_query(_PLACEHOLDER.sub(r"%(p\1)s", sql), named) or []]
    call = f"EXECUTE {name} ({', '.join(['%s'] * len(params))})"
    for attempt in (1, 2):
        if name not in prepared:
            try:
                db._execute_write(f"PREPARE {name} AS {sql}")
            except psycopg2.errors.DuplicatePreparedStatement:
                pass
            prepared.add(name)
        try:
            return [dict(row) for row in db.execute_query(call, tuple(params)) or []]
        except psycopg2.errors.InvalidSqlStatementName:
            # The server forgot it (DISCARD ALL, a pooler): prepare it again, once.
            prepared.discard(name)
            if attempt == 2:
                raise
    return []


def _array(ids: Sequence[Optional[str]]) -> str:
    """A list of ids as a Postgres array literal, without repeats."""
    return "{" + ",".join(dict.fromkeys(i for i in ids if i)) + "}"


#: What every row statement selects. ``p`` is the publication, ``r`` the verification result.
_ROW_COLUMNS = """
    c.id::text AS consumer_id, c.slug AS consumer_slug, c.name AS consumer_name,
    cv.id::text AS consumer_version_id, cv.number AS consumer_version_number, cv.seq AS consumer_version_seq,
    pr.id::text AS provider_id, pr.slug AS provider_slug, pr.name AS provider_name,
    pv.sha::text AS pact_sha, p.created_at AS pact_created_at, p.revision AS pact_revision,
    rv.id::text AS provider_version_id, rv.number AS provider_version_number, rv.seq AS provider_version_seq,
    r.number AS verification_number, r.seq AS verification_seq, r.success, r.created_at AS verified_at,
    r.pact_pending, r.wip, r.kind AS verification_kind, r.comparison->>'verdict' AS comparison_verdict,
    GREATEST(cv.created_at, COALESCE(rv.created_at, cv.created_at)) AS last_action_at
"""

#: The names :data:`_ROW_COLUMNS` gives its columns, for reading them back out of a subquery.
_ROW_NAMES = """
    consumer_id, consumer_slug, consumer_name, consumer_version_id, consumer_version_number, consumer_version_seq,
    provider_id, provider_slug, provider_name, pact_sha, pact_created_at, pact_revision,
    provider_version_id, provider_version_number, provider_version_seq,
    verification_number, verification_seq, success, verified_at, pact_pending, wip, verification_kind,
    comparison_verdict, last_action_at
"""

_PUBLICATION_COLUMNS = (
    "p.id, p.consumer_id, p.provider_id, p.consumer_version_id, p.pact_version_id, p.revision, p.created_at"
)


def _row_from(source: str, join: str, matching: str, latest_flag: str) -> str:
    """The ``FROM`` of a row statement: publications joined to names, versions and results.

    Args:
        source: The publications to read (a CTE name).
        join: ``LEFT JOIN`` to keep pacts without a result, ``JOIN`` to drop them.
        matching: A condition on ``r`` that picks the provider versions asked about, or ``TRUE``.
        latest_flag: The boolean placeholder that keeps only the latest result per pact version
            and provider version.
    """
    return f"""
    FROM {source} p
    JOIN apiome.pacticipant c ON c.id = p.consumer_id AND c.tenant_id = $1::uuid AND c.deleted_at IS NULL
    JOIN apiome.pacticipant pr ON pr.id = p.provider_id AND pr.tenant_id = $1::uuid AND pr.deleted_at IS NULL
    JOIN apiome.pacticipant_version cv ON cv.id = p.consumer_version_id AND cv.deleted_at IS NULL
    JOIN apiome.pact_version pv ON pv.id = p.pact_version_id
    {join} apiome.verification_result r
           ON r.pact_version_id = p.pact_version_id
          AND {matching}
          AND {_LIVE_RESULT}
          AND (NOT {latest_flag}::boolean
               OR r.number = (SELECT max(l.number) FROM apiome.verification_result l
                              WHERE l.pact_version_id = r.pact_version_id
                                AND l.provider_version_id = r.provider_version_id))
    LEFT JOIN apiome.pacticipant_version rv ON rv.id = r.provider_version_id
    """


#: A publication of a live consumer version (PFX-1.11): deleted versions take their pacts with them.
#: Filtered inside each CTE, before its LIMIT, so hidden rows never take a row's place.
_LIVE_PUBLICATION = (
    "EXISTS (SELECT 1 FROM apiome.pacticipant_version lv"
    " WHERE lv.id = p.consumer_version_id AND lv.deleted_at IS NULL)"
)

#: A result published by a live provider version.
_LIVE_RESULT = (
    "EXISTS (SELECT 1 FROM apiome.pacticipant_version lr"
    " WHERE lr.id = r.provider_version_id AND lr.deleted_at IS NULL)"
)

#: A result is of a provider version the query asked about ($2 name-only ids, $3 version ids).
_ASKED_ABOUT = "(r.provider_id = ANY($2::uuid[]) OR r.provider_version_id = ANY($3::uuid[]))"

#: Rows between several selectors. $1 tenant, $2 ids of name-only selectors, $3 selected version
#: ids, $4 every selector's pacticipant id, $5 the pacticipants the caller named, $6 limit,
#: $7 latest result only.
_ROWS_BETWEEN = f"""
    WITH pubs AS (
        SELECT {_PUBLICATION_COLUMNS}
        FROM apiome.pact_publication p
        WHERE (p.consumer_id = ANY($2::uuid[]) OR p.consumer_version_id = ANY($3::uuid[]))
          AND p.provider_id = ANY($4::uuid[])
          AND (p.consumer_id = ANY($5::uuid[]) OR p.provider_id = ANY($5::uuid[]))
          AND {_LIVE_PUBLICATION}
        ORDER BY p.created_at DESC, p.id
        LIMIT $6::bigint
    )
    SELECT {_ROW_COLUMNS}
    {_row_from("pubs", "LEFT JOIN", _ASKED_ABOUT, "$7")}
    ORDER BY last_action_at DESC, p.created_at DESC, r.seq DESC NULLS LAST
    LIMIT $6::bigint
"""

#: Rows of one selector, as a consumer (every result of its pacts) and as a provider (the pacts it
#: verified). $1 tenant, $2 its pacticipant id when name-only, $3 its version ids, $4 its
#: pacticipant id, $5 limit, $6 latest result only.
_ROWS_SINGLE = f"""
    WITH as_consumer AS (
        SELECT {_PUBLICATION_COLUMNS}
        FROM apiome.pact_publication p
        WHERE (p.consumer_id = ANY($2::uuid[]) OR p.consumer_version_id = ANY($3::uuid[]))
          AND {_LIVE_PUBLICATION}
        ORDER BY p.created_at DESC, p.id
        LIMIT $5::bigint
    ), as_provider AS (
        SELECT {_PUBLICATION_COLUMNS}
        FROM apiome.pact_publication p
        WHERE p.provider_id = ANY($4::uuid[])
          AND {_LIVE_PUBLICATION}
          AND EXISTS (SELECT 1 FROM apiome.verification_result r
                      WHERE r.pact_version_id = p.pact_version_id
                        AND (r.provider_id = ANY($2::uuid[]) OR r.provider_version_id = ANY($3::uuid[]))
                        AND {_LIVE_RESULT})
        ORDER BY p.created_at DESC, p.id
        LIMIT $5::bigint
    )
    SELECT {_ROW_NAMES}
    FROM (
        SELECT {_ROW_COLUMNS}
        {_row_from("as_consumer", "LEFT JOIN", "TRUE", "$6")}
        UNION ALL
        SELECT {_ROW_COLUMNS}
        {_row_from("as_provider", "JOIN", _ASKED_ABOUT, "$6")}
    ) rows
    ORDER BY last_action_at DESC, pact_created_at DESC, verification_seq DESC NULLS LAST
    LIMIT $5::bigint
"""

#: The branches, tags and environments of versions. $1 version ids.
_VERSION_DETAILS = """
    SELECT v.id::text AS id,
           COALESCE((SELECT json_agg(json_build_object('name', b.name, 'latest', b.head_version_id = v.id)
                                     ORDER BY bv.created_at, b.name)
                     FROM apiome.pacticipant_branch_version bv
                     JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id
                     WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id), '[]'::json) AS branches,
           COALESCE((SELECT json_agg(json_build_object(
                                'name', t.name,
                                'latest', NOT EXISTS (
                                    SELECT 1 FROM apiome.pacticipant_version_tag t2
                                    JOIN apiome.pacticipant_version v2
                                      ON v2.id = t2.version_id AND v2.pacticipant_id = t2.pacticipant_id
                                    WHERE t2.pacticipant_id = t.pacticipant_id AND t2.name = t.name AND v2.seq > v.seq
                                      AND v2.deleted_at IS NULL))
                                     ORDER BY t.created_at, t.name)
                     FROM apiome.pacticipant_version_tag t
                     WHERE t.version_id = v.id AND t.pacticipant_id = v.pacticipant_id), '[]'::json) AS tags,
           COALESCE((SELECT json_agg(json_build_object(
                                'uuid', x.id, 'name', x.name, 'displayName', x.display_name,
                                'production', x.production) ORDER BY x.first_at, x.name)
                     FROM (SELECT e.id::text AS id, e.name, e.display_name, e.production, min(s.created_at) AS first_at
                           FROM (SELECT d.environment_id, d.tenant_id, d.created_at
                                 FROM apiome.deployed_version d
                                 WHERE d.version_id = v.id AND d.pacticipant_id = v.pacticipant_id
                                   AND d.currently_deployed
                                 UNION ALL
                                 SELECT s.environment_id, s.tenant_id, s.created_at
                                 FROM apiome.released_version s
                                 WHERE s.version_id = v.id AND s.pacticipant_id = v.pacticipant_id
                                   AND s.currently_supported) s
                           JOIN apiome.pact_environment e ON e.id = s.environment_id AND e.tenant_id = s.tenant_id
                           GROUP BY e.id, e.name, e.display_name, e.production) x), '[]'::json) AS environments
    FROM apiome.pacticipant_version v
    WHERE v.id = ANY($1::uuid[])
"""


# ---------------------------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------------------------


def _pacticipant_or_none(db: Any, tenant_id: str, name: Optional[str]) -> Optional[_Pacticipant]:
    """The tenant's pacticipant with this name, handle or id, or ``None``."""
    try:
        record = get_pacticipant(db, tenant_id, name or "")
    except PacticipantValidationError:
        return None
    return {"id": record.id, "slug": record.slug, "name": record.name, "main_branch": record.main_branch}


_IN_ENVIRONMENT = """
    EXISTS (SELECT 1 FROM apiome.{table} s
            JOIN apiome.pact_environment e ON e.id = s.environment_id AND e.tenant_id = s.tenant_id
            WHERE s.version_id = v.id AND s.pacticipant_id = v.pacticipant_id AND s.{flag}
              AND e.tenant_id = %s::uuid AND e.name = %s)
"""


def _find_versions(
    db: Any, tenant_id: str, pacticipant: _Pacticipant, selector: UnresolvedSelector
) -> Optional[List[Dict[str, Any]]]:
    """The versions of a pacticipant a selector describes, latest first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipant: The pacticipant.
        selector: The selector.

    Returns:
        ``None`` when the selector names only the pacticipant (all versions); otherwise the
        matching versions (``id``, ``number``) — one with ``latest``, at most
        :data:`MAX_VERSIONS_PER_SELECTOR` without, none when nothing matches.
    """
    if selector.only_pacticipant_name:
        return None
    where = ["v.pacticipant_id = %s::uuid", "v.deleted_at IS NULL"]
    params: List[Any] = [pacticipant["id"]]
    if selector.version_number:
        where.append("v.number = %s")
        params.append(selector.version_number)
    if selector.environment_name:
        deployed = _IN_ENVIRONMENT.format(table="deployed_version", flag="currently_deployed")
        released = _IN_ENVIRONMENT.format(table="released_version", flag="currently_supported")
        where.append(f"({deployed} OR {released})")
        params += [tenant_id, selector.environment_name, tenant_id, selector.environment_name]
    if selector.tag:
        where.append(
            "EXISTS (SELECT 1 FROM apiome.pacticipant_version_tag t"
            " WHERE t.version_id = v.id AND t.pacticipant_id = v.pacticipant_id AND t.name = %s)"
        )
        params.append(selector.tag)
    branch = selector.branch
    if selector.main_branch:
        branch = pacticipant.get("main_branch")
        if not branch:
            return []
    if branch:
        where.append(
            "EXISTS (SELECT 1 FROM apiome.pacticipant_branch_version bv"
            " JOIN apiome.pacticipant_branch b ON b.id = bv.branch_id AND b.pacticipant_id = bv.pacticipant_id"
            " WHERE bv.version_id = v.id AND bv.pacticipant_id = v.pacticipant_id AND b.name = %s)"
        )
        params.append(branch)
    params.append(1 if selector.latest else MAX_VERSIONS_PER_SELECTOR)
    rows = db.execute_query(
        f"""
        SELECT v.id::text AS id, v.number
        FROM apiome.pacticipant_version v
        WHERE {" AND ".join(where)}
        ORDER BY v.seq DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return [dict(row) for row in rows or []]


def _resolve(
    db: Any,
    tenant_id: str,
    unresolved: Sequence[UnresolvedSelector],
    kind: str,
    known: Dict[str, Optional[_Pacticipant]],
    ignore_selectors: Sequence[ResolvedSelector] = (),
) -> List[ResolvedSelector]:
    """Resolve selectors of one kind against the registry.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        unresolved: The selectors.
        kind: ``specified``, ``inferred`` or ``ignored``.
        known: Pacticipants already looked up, by the name asked for; filled as it goes.
        ignore_selectors: The resolved ``ignore`` selectors.

    Returns:
        The resolved selectors, in order.
    """
    resolved: List[ResolvedSelector] = []
    for selector in unresolved:
        name = selector.pacticipant_name or ""
        if name not in known:
            known[name] = _pacticipant_or_none(db, tenant_id, name)
        pacticipant = known[name]
        versions = _find_versions(db, tenant_id, pacticipant, selector) if pacticipant else None
        resolved += resolve_selector(selector, kind, pacticipant, versions, ignore_selectors)
    return resolved


# ---------------------------------------------------------------------------------------------
# Integrations
# ---------------------------------------------------------------------------------------------

_INTEGRATION_NAMES = """
    SELECT i.required, c.id::text AS consumer_id, c.slug AS consumer_slug, c.name AS consumer_name,
           c.main_branch AS consumer_main_branch,
           p.id::text AS provider_id, p.slug AS provider_slug, p.name AS provider_name,
           p.main_branch AS provider_main_branch
    FROM ({pairs}) i
    JOIN apiome.pacticipant c ON c.id = i.consumer_id AND c.tenant_id = %s::uuid AND c.deleted_at IS NULL
    JOIN apiome.pacticipant p ON p.id = i.provider_id AND p.tenant_id = %s::uuid AND p.deleted_at IS NULL
    ORDER BY c.name, p.name
"""

_AS_CONSUMER = """
    SELECT DISTINCT p.consumer_id, p.provider_id, TRUE AS required
    FROM apiome.pact_publication p
    WHERE (p.consumer_id = ANY(%s::uuid[]) OR p.consumer_version_id = ANY(%s::uuid[]))
      AND EXISTS (SELECT 1 FROM apiome.pacticipant_version lv
                  WHERE lv.id = p.consumer_version_id AND lv.deleted_at IS NULL)
"""

_AS_PROVIDER = """
    SELECT DISTINCT pv.consumer_id, pv.provider_id, FALSE AS required
    FROM apiome.pact_version pv
    WHERE pv.provider_id = ANY(%s::uuid[]) AND pv.tenant_id = %s::uuid
      AND EXISTS (SELECT 1 FROM apiome.pact_publication lp
                  JOIN apiome.pacticipant_version lv ON lv.id = lp.consumer_version_id AND lv.deleted_at IS NULL
                  WHERE lp.pact_version_id = pv.id)
"""


def _find_integrations(
    db: Any,
    tenant_id: str,
    specified: Sequence[ResolvedSelector],
    involving: bool,
) -> Tuple[List[Integration], Dict[str, _Pacticipant]]:
    """The integrations a query involves, and the pacticipants on either side of them.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        specified: The selectors the caller wrote, resolved.
        involving: ``True`` for every integration of the named pacticipants; ``False`` for only
            the integrations between them.

    Returns:
        The integrations, by consumer then provider name — an integration is *required* when a
        named pacticipant is its consumer — and every pacticipant they involve, by id.
    """
    name_only = _array([s.pacticipant_id for s in specified if s.version_id is None and not s.version_missing])
    version_ids = _array([s.version_id for s in specified])
    all_ids = _array([s.pacticipant_id for s in specified])
    if involving:
        pairs = f"{_AS_CONSUMER} UNION ALL {_AS_PROVIDER}"
        params: Tuple[Any, ...] = (name_only, version_ids, all_ids, tenant_id)
    else:
        pairs = f"{_AS_CONSUMER} AND p.provider_id = ANY(%s::uuid[])"
        params = (name_only, version_ids, all_ids)
    rows = db.execute_query(_INTEGRATION_NAMES.format(pairs=pairs), params + (tenant_id, tenant_id)) or []
    integrations: Dict[Tuple[str, str], Integration] = {}
    pacticipants: Dict[str, _Pacticipant] = {}
    for row in rows:
        for side in ("consumer", "provider"):
            pacticipants.setdefault(
                row[f"{side}_id"],
                {
                    "id": row[f"{side}_id"],
                    "slug": row[f"{side}_slug"],
                    "name": row[f"{side}_name"],
                    "main_branch": row.get(f"{side}_main_branch"),
                },
            )
        key = (row["consumer_id"], row["provider_id"])
        if key not in integrations or row["required"]:
            integrations[key] = Integration(
                consumer_id=row["consumer_id"],
                consumer_name=row["consumer_name"],
                provider_id=row["provider_id"],
                provider_name=row["provider_name"],
                required=bool(row["required"]),
            )
    return list(integrations.values()), pacticipants


def _inferred_selector(name: str, options: MatrixOptions) -> UnresolvedSelector:
    """The selector the destination gives a pacticipant the caller did not name."""
    return UnresolvedSelector(
        pacticipant_name=name,
        latest=options.latest,
        tag=options.tag,
        environment_name=options.environment_name,
        main_branch=options.main_branch,
    )


def _infer(
    db: Any,
    tenant_id: str,
    pacticipants: Dict[str, _Pacticipant],
    specified: Sequence[ResolvedSelector],
    options: MatrixOptions,
    ignore_selectors: Sequence[ResolvedSelector],
) -> List[ResolvedSelector]:
    """Resolve a selector for every pacticipant of the integrations that the caller did not name.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        pacticipants: The pacticipants the integrations involve, by id.
        specified: The selectors the caller wrote, resolved.
        options: The query's options; the destination says which versions.
        ignore_selectors: The resolved ``ignore`` selectors.

    Returns:
        The inferred selectors: the versions of each other pacticipant at the destination, or one
        marked ``version_missing`` when it has none there.
    """
    named = {s.pacticipant_id for s in specified}
    inferred: List[ResolvedSelector] = []
    for pacticipant_id, pacticipant in pacticipants.items():
        if pacticipant_id in named:
            continue
        selector = _inferred_selector(pacticipant["name"], options)
        versions = _find_versions(db, tenant_id, pacticipant, selector)
        inferred += resolve_selector(selector, INFERRED, pacticipant, versions, ignore_selectors)
    return inferred


# ---------------------------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------------------------


def _iso(value: Any) -> Optional[str]:
    """A timestamp as ISO 8601 text."""
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


def _row(row: Dict[str, Any]) -> MatrixRow:
    """Build a :class:`MatrixRow` from a row statement's row."""
    return MatrixRow(
        consumer_id=row["consumer_id"],
        consumer_slug=row["consumer_slug"],
        consumer_name=row["consumer_name"],
        consumer_version_id=row["consumer_version_id"],
        consumer_version_number=row["consumer_version_number"],
        consumer_version_seq=int(row["consumer_version_seq"]),
        provider_id=row["provider_id"],
        provider_slug=row["provider_slug"],
        provider_name=row["provider_name"],
        pact_sha=row["pact_sha"],
        pact_created_at=_iso(row.get("pact_created_at")),
        pact_revision=int(row.get("pact_revision") or 1),
        provider_version_id=row.get("provider_version_id"),
        provider_version_number=row.get("provider_version_number"),
        provider_version_seq=None if row.get("provider_version_seq") is None else int(row["provider_version_seq"]),
        verification_number=None if row.get("verification_number") is None else int(row["verification_number"]),
        verification_seq=None if row.get("verification_seq") is None else int(row["verification_seq"]),
        success=row.get("success"),
        verified_at=_iso(row.get("verified_at")),
        pact_pending=row.get("pact_pending"),
        wip=bool(row.get("wip")),
        verification_kind=row.get("verification_kind"),
        comparison_verdict=row.get("comparison_verdict"),
    )


def _read_rows(
    db: Any, tenant_id: str, selectors: Sequence[ResolvedSelector], options: MatrixOptions
) -> List[MatrixRow]:
    """Read the matrix rows the resolved selectors describe, newest activity first.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        selectors: Every resolved selector: specified, then inferred.
        options: The query's options (``limit``, ``latestby``).

    Returns:
        At most ``options.limit`` rows, before ``latestby`` is applied.
    """
    name_only = _array([s.pacticipant_id for s in selectors if s.version_id is None and not s.version_missing])
    version_ids = _array([s.version_id for s in selectors])
    all_ids = _array([s.pacticipant_id for s in selectors])
    latest_only = bool(options.latestby)
    if len(selectors) == 1:
        rows = _execute_named(
            db,
            "pfx_matrix_rows_single",
            _ROWS_SINGLE,
            (tenant_id, name_only, version_ids, all_ids, options.limit, latest_only),
        )
    else:
        specified = _array([s.pacticipant_id for s in selectors if s.specified])
        rows = _execute_named(
            db,
            "pfx_matrix_rows_between",
            _ROWS_BETWEEN,
            (tenant_id, name_only, version_ids, all_ids, specified, options.limit, latest_only),
        )
    return [_row(row) for row in rows]


def read_version_details(db: Any, version_ids: Sequence[Optional[str]]) -> Dict[str, Dict[str, Any]]:
    """Read the branches, tags and environments of versions, for rendering matrix rows.

    Args:
        db: The database.
        version_ids: Version ids taken from matrix rows (already the caller's tenant's).

    Returns:
        By version id: ``branches`` and ``tags`` (``name``, ``latest``) and ``environments``
        (``uuid``, ``name``, ``displayName``, ``production``) the version is currently in.
    """
    ids = _array(version_ids)
    if ids == "{}":
        return {}
    rows = _execute_named(db, "pfx_matrix_version_details", _VERSION_DETAILS, (ids,))
    return {row["id"]: row for row in rows}


# ---------------------------------------------------------------------------------------------
# The query
# ---------------------------------------------------------------------------------------------


def _environment(db: Any, tenant_id: str, name: Optional[str]) -> Optional[EnvironmentRecord]:
    """The destination environment, or a refusal when it does not exist."""
    if not name:
        return None
    found = list_environments(db, tenant_id, name=name)
    if not found:
        raise _invalid(f"Environment with name '{name}' does not exist", "/environment")
    return found[0]


def _uncontracted(db: Any, tenant_id: str, specified: Sequence[ResolvedSelector]) -> List[ResolvedSelector]:
    """The named versions that have no pact at all: none published, and no pact names them provider."""
    without: List[ResolvedSelector] = []
    for selector in specified:
        if selector.version_id is None:
            continue
        rows = db.execute_query(
            """
            SELECT (EXISTS (SELECT 1 FROM apiome.pact_publication WHERE consumer_version_id = %s::uuid)
                    OR EXISTS (SELECT 1 FROM apiome.pact_version pv
                               WHERE pv.provider_id = %s::uuid AND pv.tenant_id = %s::uuid
                                 AND EXISTS (SELECT 1 FROM apiome.pact_publication lp
                                             JOIN apiome.pacticipant_version lv
                                               ON lv.id = lp.consumer_version_id AND lv.deleted_at IS NULL
                                             WHERE lp.pact_version_id = pv.id))) AS contracted
            """,
            (selector.version_id, selector.pacticipant_id, tenant_id),
        )
        if not (rows and rows[0]["contracted"]):
            without.append(selector)
    return without


def query_matrix(
    db: Any, tenant_id: str, selectors: Sequence[UnresolvedSelector], options: MatrixOptions
) -> MatrixResult:
    """Answer one matrix query for the caller's tenant.

    Args:
        db: The database.
        tenant_id: The caller's tenant.
        selectors: The selectors the caller wrote (already validated by :mod:`app.pact_matrix`).
        options: The query's options.

    Returns:
        The rows (considered and ignored), every resolved selector, the integrations, and — when
        the destination environment requires a contract — the named versions that have none.
        Pass it to :func:`app.pact_matrix.deployment_verdict`.

    Raises:
        PactPublicationError: ``pact-matrix-invalid`` — a named pacticipant or the destination
            environment does not exist, or the query carries more than :data:`MAX_SELECTORS`.
    """
    if len(selectors) + len(options.ignore_selectors) > MAX_SELECTORS:
        raise _invalid(f"A query may carry at most {MAX_SELECTORS} selectors.", "/q")
    environment = _environment(db, tenant_id, options.environment_name)
    known: Dict[str, Optional[_Pacticipant]] = {}
    for index, selector in enumerate(selectors):
        name = selector.pacticipant_name or ""
        known[name] = _pacticipant_or_none(db, tenant_id, name)
        if known[name] is None:
            raise _invalid(f"Pacticipant {name} not found", f"/q/{index}/pacticipant")

    ignore = _resolve(db, tenant_id, options.ignore_selectors, IGNORED, known)
    specified = _resolve(db, tenant_id, selectors, SPECIFIED, known, ignore)
    infer = options.infers_selectors
    integrations, pacticipants = _find_integrations(db, tenant_id, specified, infer or len(specified) == 1)
    inferred = _infer(db, tenant_id, pacticipants, specified, options, ignore) if infer else []
    resolved = specified + inferred

    rows = apply_latestby(_read_rows(db, tenant_id, resolved, options), options.latestby)
    if environment:
        rows = expand_unverified(rows, resolved)
    rows = apply_success_filter(rows, options.success)
    considered, ignored = split_ignored(rows, ignore)
    return MatrixResult(
        considered_rows=sort_rows(considered),
        ignored_rows=sort_rows(ignored),
        selectors=resolved,
        ignore_selectors=ignore,
        integrations=integrations,
        options=options,
        uncontracted=_uncontracted(db, tenant_id, specified) if environment and environment.contract_required else (),
    )
