"""Persistence for the Slate Edge functions control plane — UXE-3.3 (private-suite#2475).

Reads and writes the V189 tables. Follows :mod:`app.slate_security_store` exactly, which follows
:mod:`app.slate_cache_store`: a small ``_DbLike`` protocol rather than a dependency on the concrete
``Database`` singleton, so the whole surface can be exercised against a fake connection without a
live Postgres.

**Concurrency.** Every write that changes function policy goes through
:func:`bump_policy_version`, whose conditional UPDATE mirrors the cache and security planes':

    UPDATE apiome.slate_function_policies
       SET policy_version = policy_version + 1
     WHERE environment_id = %s AND policy_version = %s

The second of two simultaneous edits matches zero rows and is refused as
``policy-version-conflict`` rather than silently overwriting the first. Two operators editing the
same lane while a rollout is in flight is the normal case, not the exotic one, so there is
deliberately no last-write-wins path anywhere in this module.

**Every function write leaves a document behind.** :func:`upsert_function`, :func:`set_rollout`,
:func:`revert_function`, :func:`delete_function` and :func:`add_version` all write the function
body to ``slate_function_revisions`` before mutating anything. §29.5's "every function change can
be reverted" is only true if reverting means applying a stored body rather than reconstructing
intent from an audit sentence — so the revision is written inside the same transaction as the
change, and a rolled-back change leaves no orphan revision claiming something happened.
``add_version`` is included because promoting new code is a change to the function even when
nothing else moved, which is exactly why V189 gives ``change_kind`` a ``version-added`` value.

**Redaction is this module's job, not the caller's.** V189 constrains ``evidence`` to an allowlist
of *top-level keys*, which is a backstop and not a mechanism: a nested object under an allowed key
would satisfy that CHECK while carrying an entire request body into the database. This matters
more here than it did for security events, because a function's inputs *are* the request.
:func:`redact_evidence` is the mechanism. It drops every key outside the allowlist, drops every
value that is not a scalar, bounds the free-text fields, and reduces any address to a network
prefix. Callers pass raw request data to it and cannot pass raw request data past it.

**Nothing here executes.** ``deploy/`` is a single Caddyfile: there is no isolate pool, no WASM
runtime and no egress proxy. :func:`record_invocation` therefore writes
``source = 'policy-simulation'``, ``executed = FALSE`` and ``edge_attached = FALSE`` as literals
rather than as parameters: there is no argument by which a caller can ask this module to record an
observation or an execution, and V189's CHECKs refuse the row if one ever appeared. An unenforced
cache rule wastes a purge and an unenforced WAF rule leaves an attacker unblocked — but a green
"ran" row would be evidence of an isolation guarantee that was never tested, which is worse than
either.
"""

from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

__all__ = [
    "EVIDENCE_ALLOWED_KEYS",
    "SlateFunctionPolicyConflictError",
    "SlateFunctionStoreError",
    "add_version",
    "append_audit",
    "bump_policy_version",
    "delete_egress_rule",
    "delete_function",
    "delete_secret_ref",
    "delete_variant",
    "ensure_policy",
    "function_evaluation_context",
    "get_function",
    "get_invocation",
    "get_policy",
    "grant_capability",
    "last_simulated_at",
    "list_approvals",
    "list_audit",
    "list_capabilities",
    "list_egress_rules",
    "list_functions",
    "list_invocations",
    "list_revisions",
    "list_secret_refs",
    "list_variants",
    "list_versions",
    "record_approval",
    "record_invocation",
    "redact_evidence",
    "revert_function",
    "revoke_capability",
    "set_egress_rule",
    "set_policy",
    "set_rollout",
    "set_secret_ref",
    "upsert_function",
    "upsert_variant",
]


class _DbLike(Protocol):
    """Minimal database surface used by this module."""

    def connect(self) -> Any: ...


class SlateFunctionStoreError(Exception):
    """A function control-plane row was missing or malformed.

    Carries a machine-readable ``code`` so the REST layer maps it to a status without
    string-matching. Codes: ``policy_not_found``, ``function_not_found``, ``revision_not_found``,
    ``variant_not_found``, ``capability_not_found``, ``egress_rule_not_found``,
    ``secret_ref_not_found``, ``invocation_not_found``.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SlateFunctionPolicyConflictError(Exception):
    """Another operator changed the lane's function policy first.

    Raised when the conditional UPDATE matched zero rows. The REST layer turns this into the
    ``policy-version-conflict`` refusal, whose sentence tells the operator to re-read.
    """

    def __init__(self, environment_id: str, expected: int, actual: Optional[int]) -> None:
        self.environment_id = environment_id
        self.expected_policy_version = expected
        self.actual_policy_version = actual
        super().__init__(
            f"Environment {environment_id} function policy changed while this edit was being "
            f"prepared (expected policy_version {expected}, found {actual})."
        )


def _as_dict(row: Any) -> Optional[Dict[str, Any]]:
    """Normalize a cursor row to a plain dict, preserving None."""
    return None if row is None else dict(row)


def _fetch_all(cursor: Any, query: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    """Execute a query and return every row as a plain dict."""
    cursor.execute(query, params)
    return [dict(row) for row in (cursor.fetchall() or [])]


def _fetch_one(cursor: Any, query: str, params: Sequence[Any]) -> Optional[Dict[str, Any]]:
    """Execute a query and return the first row as a plain dict, or None."""
    cursor.execute(query, params)
    return _as_dict(cursor.fetchone())


def _json(value: Any) -> Any:
    """Return a JSON-serializable value; psycopg2 needs plain dict/list for JSONB."""
    return None if value is None else json.loads(json.dumps(value, default=str))


def _now() -> datetime:
    """Current UTC time, isolated so tests can patch one place."""
    return datetime.now(timezone.utc)


# ─── Evidence redaction ──────────────────────────────────────────────────────

#: The only keys that may appear in ``slate_function_invocations.evidence``. Identical to V189's
#: CHECK array, and deliberately an allowlist: a denylist of sensitive headers fails open on the
#: field nobody thought of, and the field nobody thought of is the one that carries the session.
EVIDENCE_ALLOWED_KEYS = (
    "method",
    "path",
    "query",
    "userAgent",
    "country",
    "region",
    "clientIpPrefix",
    "variant",
    "outcome",
    "statusCode",
    "denialReason",
    "cpuMs",
    "wallMs",
)

#: Keys whose values are attacker-influenced or server-authored free text. Bounded so a single
#: invocation cannot carry a kilobyte of payload into the database under a permitted name.
_BOUNDED_KEYS = ("userAgent", "denialReason", "query", "path")

#: The bound. Long enough for a real user-agent string and for the sentence explaining a denial;
#: short enough that the field cannot be used as storage.
_BOUNDED_LENGTH = 256

#: Keys that must be reduced to a network prefix before they are stored.
_ADDRESS_KEYS = ("clientIpPrefix",)

#: How far an address is generalized. A /24 identifies the network a request came from — which is
#: what an investigation needs — without retaining the household or the individual behind it, and
#: a /48 is the equivalent unit of allocation in IPv6.
_IPV4_PREFIX_BITS = 24
_IPV6_PREFIX_BITS = 48

#: How long request evidence lives when the caller does not say. Request data is a liability
#: rather than an asset: the audit row lives forever, the captured user agent does not.
_DEFAULT_RETENTION_DAYS = 30


def _network_prefix(value: Any) -> Optional[str]:
    """Reduce an address to the network it came from.

    Args:
        value: An IPv4 or IPv6 address, or a CIDR that may be narrower than the permitted prefix.

    Returns:
        ``203.0.113.0/24`` or ``2001:db8::/48``, or ``None`` when the value is not an address at
        all. Returning None rather than the original string is deliberate: this function is the
        only path by which a client address reaches the database, and a value it cannot prove is
        a network must not be stored as though it were one.
    """
    text = str(value).strip()
    if not text:
        return None
    try:
        network = ipaddress.ip_network(text, strict=False)
    except ValueError:
        return None
    bits = _IPV4_PREFIX_BITS if network.version == 4 else _IPV6_PREFIX_BITS
    # A caller may already have generalized further than we require; never narrow their choice
    # back down to ours.
    width = min(network.prefixlen, bits)
    return str(network.supernet(new_prefix=width))


def redact_evidence(raw: Mapping[str, Any]) -> Dict[str, str]:
    """Reduce request data to the evidence an invocation record is permitted to carry.

    This is the mechanism; V189's ``evidence - ARRAY[...] = '{}'`` CHECK is the backstop. The
    distinction matters because that CHECK constrains only *top-level keys*: a value of
    ``{"userAgent": {"cookie": "session=..."}}`` satisfies it perfectly while carrying exactly
    what the constraint exists to exclude. Four things happen here, and each closes one of those
    routes:

    1. Every key outside :data:`EVIDENCE_ALLOWED_KEYS` is dropped, including keys that differ only
       in case — ``Cookie`` is not a permitted key and neither is ``cookie``.
    2. Every value that is not a scalar is dropped outright rather than stringified. Rendering a
       nested object as text would preserve its contents under a permitted name, which is the
       smuggling route this step exists to close.
    3. The free-text keys are truncated to :data:`_BOUNDED_LENGTH`.
    4. Anything that parses as an address is reduced to a network prefix — ``/24`` for IPv4 and
       ``/48`` for IPv6. A full client address is never stored, whichever key it arrives under.

    Args:
        raw: Request data as the caller observed or constructed it, unredacted.

    Returns:
        A new dict of string values, safe to store. Never the input object.
    """
    redacted: Dict[str, str] = {}
    for key in EVIDENCE_ALLOWED_KEYS:
        if key not in raw:
            continue
        value = raw[key]
        if value is None:
            continue
        # bool is a subclass of int, and both are scalars; anything with a length or an iterator
        # that is not a string is a container and is dropped rather than rendered.
        if isinstance(value, (Mapping, list, tuple, set)):
            continue
        if not isinstance(value, (str, int, float, bool)):
            continue
        text = str(value)

        if key in _ADDRESS_KEYS:
            prefix = _network_prefix(text)
            if prefix is None:
                continue
            redacted[key] = prefix
            continue

        # An address can arrive under any key — a denial sentence quoting a header, a query
        # parameter carrying a forwarded-for value. Generalize it wherever it appears.
        as_network = _network_prefix(text)
        if as_network is not None and text != as_network:
            redacted[key] = as_network
            continue

        if key in _BOUNDED_KEYS:
            text = text[:_BOUNDED_LENGTH]
        redacted[key] = text
    return redacted


# ─── Policy ──────────────────────────────────────────────────────────────────


def get_policy(db: _DbLike, *, tenant_id: str, environment_id: str) -> Optional[Dict[str, Any]]:
    """Load a lane's function policy, scoped to its tenant.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Caller's tenant. A scope miss returns None so the REST layer can answer 404
            rather than confirming the lane exists to another tenant.
        environment_id: The lane.

    Returns:
        The policy row, or None when the lane has none yet or belongs to another tenant.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT *
              FROM apiome.slate_function_policies
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
            """,
            (environment_id, tenant_id),
        )


def ensure_policy(
    db: _DbLike,
    *,
    tenant_id: str,
    site_id: str,
    environment_id: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_key: str,
) -> Dict[str, Any]:
    """Return a lane's function policy, creating the shipped default if it has none.

    A lane with no row is not a lane with no policy — it is a lane with functions disabled,
    running in region only, under the shipped CPU, memory and wall-clock ceilings, which is what
    V189's column defaults say. Materializing that on first read keeps "what may run on this lane"
    answerable with one query and gives the optimistic-concurrency token something to count from.

    ``functions_enabled`` and ``edge_attached`` are deliberately left to their column defaults
    rather than named here: both are FALSE, and a statement that does not mention them cannot set
    them to anything else.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the environment belongs to.
        environment_id: The lane.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_key: Immutable identity of the actor.

    Returns:
        The existing or newly created policy row.
    """
    existing = get_policy(db, tenant_id=tenant_id, environment_id=environment_id)
    if existing is not None:
        return existing

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            created = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_function_policies
                    (tenant_id, site_id, environment_id, default_region,
                     default_residency_class, updated_by_actor_id, updated_by_actor_name,
                     updated_by_actor_key)
                VALUES (%s::uuid, %s::uuid, %s::uuid, 'auto', 'in-region-only', %s, %s, %s)
                ON CONFLICT (environment_id) DO NOTHING
                RETURNING *
                """,
                (tenant_id, site_id, environment_id, actor_id, actor_name, actor_key),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if created is not None:
        return created
    # A concurrent first read won the insert. Re-reading is correct rather than raising: both
    # callers wanted the same default and both should get it.
    policy = get_policy(db, tenant_id=tenant_id, environment_id=environment_id)
    if policy is None:
        raise SlateFunctionStoreError(
            "policy_not_found",
            f"Function policy for environment {environment_id} could not be read.",
        )
    return policy


def bump_policy_version(cursor: Any, *, environment_id: str, expected_policy_version: int) -> int:
    """Advance a lane's policy version, refusing a stale expectation.

    The conditional UPDATE is the concurrency control. Callers run this inside the same
    transaction as the write it guards, so a refused edit leaves nothing behind — including the
    revision row a function write would otherwise have left as a record of a change that never
    happened.

    Args:
        cursor: Open cursor inside the caller's transaction.
        environment_id: The lane.
        expected_policy_version: The version the caller read before preparing this edit.

    Returns:
        The new policy version.

    Raises:
        SlateFunctionPolicyConflictError: When the expectation was stale, i.e. someone else wrote
            first. There is no branch that merges instead.
    """
    row = _fetch_one(
        cursor,
        """
        UPDATE apiome.slate_function_policies
           SET policy_version = policy_version + 1,
               updated_at = CURRENT_TIMESTAMP
         WHERE environment_id = %s::uuid AND policy_version = %s
        RETURNING policy_version
        """,
        (environment_id, expected_policy_version),
    )
    if row is None:
        actual = _fetch_one(
            cursor,
            """
            SELECT policy_version
              FROM apiome.slate_function_policies
             WHERE environment_id = %s::uuid
            """,
            (environment_id,),
        )
        raise SlateFunctionPolicyConflictError(
            environment_id,
            expected_policy_version,
            None if actual is None else int(actual["policy_version"]),
        )
    return int(row["policy_version"])


def set_policy(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    functions_enabled: bool,
    default_region: str,
    default_residency_class: str,
    default_cpu_ms_limit: int,
    default_memory_mb_limit: int,
    default_wall_ms_limit: int,
    residency_waiver_reason: Optional[str],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
    actor_key: str,
) -> Dict[str, Any]:
    """Change a lane's function policy: whether functions may run, where, and within what ceilings.

    All of it moves together because it is one decision. §29.5 pairs region with data policy and
    with the resource ceilings for a reason: splitting them into separate endpoints would let a
    lane sit in a state nobody chose — unrestricted residency with no waiver reason, say — between
    two requests, and the audit trail would show that intermediate state as though somebody had
    wanted it.

    ``edge_attached`` is not a parameter and is not named in the statement. There is one honest
    value for it while nothing executes, and a function that offered no way to write the other one
    cannot be talked into it.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        functions_enabled: Whether functions may exist on this lane at all.
        default_region: Where functions run by default.
        default_residency_class: ``in-region-only``, ``region-pinned`` or ``unrestricted``.
        default_cpu_ms_limit: CPU ceiling a function may tighten and cannot exceed.
        default_memory_mb_limit: Memory ceiling.
        default_wall_ms_limit: Wall-clock ceiling.
        residency_waiver_reason: Why residency was loosened. Required by V189's CHECK for
            ``unrestricted``, and refused with a sentence by
            :func:`app.slate_functions.evaluate_policy_safety` before it ever reaches the
            constraint.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_key: Immutable identity of the actor.

    Returns:
        The updated policy row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When the lane has no policy row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            updated = _fetch_one(
                cursor,
                """
                UPDATE apiome.slate_function_policies
                   SET functions_enabled = %s,
                       default_region = %s,
                       default_residency_class = %s,
                       default_cpu_ms_limit = %s,
                       default_memory_mb_limit = %s,
                       default_wall_ms_limit = %s,
                       residency_waiver_reason = %s,
                       updated_by_actor_id = %s,
                       updated_by_actor_name = %s,
                       updated_by_actor_key = %s
                 WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING *
                """,
                (
                    functions_enabled,
                    default_region,
                    default_residency_class,
                    default_cpu_ms_limit,
                    default_memory_mb_limit,
                    default_wall_ms_limit,
                    residency_waiver_reason,
                    actor_id,
                    actor_name,
                    actor_key,
                    environment_id,
                    tenant_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if updated is None:
        raise SlateFunctionStoreError(
            "policy_not_found", f"Function policy for environment {environment_id} was not found."
        )
    return updated


# ─── Functions ───────────────────────────────────────────────────────────────

#: The columns a function write sets, in the order the INSERT and UPDATE below use them. Kept as
#: one literal so the two statements cannot drift into setting different subsets — a drift there
#: would mean a create and a replace produced different functions from the same body.
_FUNCTION_COLUMNS = (
    "ordinal",
    "enabled",
    "label",
    "matcher_kind",
    "matcher_value",
    "matcher_methods",
    "matcher_hosts",
    "runtime",
    "active_version_id",
    "rollout_mode",
    "rollout_percent",
    "region",
    "residency_class",
    "cpu_ms_limit",
    "memory_mb_limit",
    "wall_ms_limit",
    "env_var_names",
    "acknowledged_warnings",
    "body_digest",
)

#: Columns whose placeholder needs an explicit cast. ``active_version_id`` is a bare UUID column
#: with no foreign key (V189 explains why), so a text parameter has to be told what it is.
_FUNCTION_COLUMN_CASTS: Mapping[str, str] = {"active_version_id": "::uuid"}


def _function_placeholder(column: str) -> str:
    """The parameter placeholder for one function column, with its cast when it needs one."""
    return "%s" + _FUNCTION_COLUMN_CASTS.get(column, "")


def list_functions(db: _DbLike, *, tenant_id: str, environment_id: str) -> List[Dict[str, Any]]:
    """Load a lane's functions in precedence order.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        Function rows ordered by ``ordinal``. The order is the evaluation order, and V189's
        ``UNIQUE (environment_id, ordinal)`` is what makes it total rather than a set with ties —
        which is what makes a simulation of the lane reproducible.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_functions
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY ordinal, id
            """,
            (environment_id, tenant_id),
        )


def get_function(
    db: _DbLike, *, tenant_id: str, environment_id: str, function_id: str
) -> Optional[Dict[str, Any]]:
    """Load one function, scoped to its lane and tenant.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function.

    Returns:
        The function row, or None when it is not on this lane.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT *
              FROM apiome.slate_functions
             WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
            """,
            (function_id, environment_id, tenant_id),
        )


def _append_revision(
    cursor: Any,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    revision: int,
    body: Mapping[str, Any],
    body_digest: str,
    change_kind: str,
    actor_id: Optional[str],
    actor_name: str,
) -> None:
    """Record a function body as it stood, inside the caller's transaction.

    Called before *every* mutation of a function, by every path that mutates one. A change with no
    stored body is a change that cannot be reverted, and V189 gives
    ``slate_function_revisions.function_id`` no foreign key precisely so the record outlives the
    row it describes.

    Args:
        cursor: Open cursor inside the caller's transaction, so a rolled-back change leaves no
            revision claiming it happened.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function this revision describes.
        revision: Which revision of that function this body was.
        body: The complete body, so reverting applies a document rather than reconstructing
            intent from a sentence.
        body_digest: The digest of that body.
        change_kind: What produced this revision, one of V189's seven kinds.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
    """
    cursor.execute(
        """
        INSERT INTO apiome.slate_function_revisions
            (tenant_id, environment_id, function_id, revision, body, body_digest, change_kind,
             actor_id, actor_name)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s, %s, %s, %s)
        ON CONFLICT (function_id, revision) DO NOTHING
        """,
        (
            tenant_id,
            environment_id,
            function_id,
            revision,
            json.dumps(_json(dict(body))),
            body_digest,
            change_kind,
            actor_id,
            actor_name,
        ),
    )


def upsert_function(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: Optional[str],
    values: Mapping[str, Any],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str = "user",
) -> Dict[str, Any]:
    """Create or replace a function, recording a revision in the same transaction.

    On a replace the *prior* body is written to ``slate_function_revisions`` before the UPDATE
    runs, so a revert has a document to apply. On a create the new body is recorded as revision 1,
    which gives a function that is later edited a first state to go back to rather than only its
    second.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: Existing function to replace, or None to create one.
        values: Column values, already validated by :mod:`app.slate_functions`.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.

    Returns:
        The written function row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When ``function_id`` names no function on this lane.
    """
    payload = [values.get(column) for column in _FUNCTION_COLUMNS]

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )

            if function_id:
                prior = _fetch_one(
                    cursor,
                    """
                    SELECT *
                      FROM apiome.slate_functions
                     WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (function_id, environment_id, tenant_id),
                )
                if prior is None:
                    raise SlateFunctionStoreError(
                        "function_not_found", f"Function {function_id} was not found on this lane."
                    )
                _append_revision(
                    cursor,
                    tenant_id=tenant_id,
                    environment_id=environment_id,
                    function_id=function_id,
                    revision=int(prior.get("revision") or 1),
                    body=prior,
                    body_digest=str(prior.get("body_digest") or ""),
                    change_kind="disabled" if not values.get("enabled") else "updated",
                    actor_id=actor_id,
                    actor_name=actor_name,
                )

                assignments = ", ".join(
                    f"{column} = {_function_placeholder(column)}" for column in _FUNCTION_COLUMNS
                )
                written = _fetch_one(
                    cursor,
                    f"""
                    UPDATE apiome.slate_functions
                       SET {assignments},
                           revision = revision + 1,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                    RETURNING *
                    """,
                    (*payload, function_id, environment_id, tenant_id),
                )
                if written is None:
                    raise SlateFunctionStoreError(
                        "function_not_found", f"Function {function_id} was not found on this lane."
                    )
            else:
                placeholders = ", ".join(
                    _function_placeholder(column) for column in _FUNCTION_COLUMNS
                )
                written = _fetch_one(
                    cursor,
                    f"""
                    INSERT INTO apiome.slate_functions
                        (tenant_id, environment_id, {", ".join(_FUNCTION_COLUMNS)},
                         created_by_actor_id, created_by_actor_name, created_by_actor_kind)
                    VALUES (%s::uuid, %s::uuid, {placeholders}, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        tenant_id,
                        environment_id,
                        *payload,
                        actor_id,
                        actor_name,
                        actor_kind,
                    ),
                )
                if written is None:
                    raise SlateFunctionStoreError(
                        "function_not_found", "The function could not be created."
                    )
                _append_revision(
                    cursor,
                    tenant_id=tenant_id,
                    environment_id=environment_id,
                    function_id=str(written["id"]),
                    revision=int(written.get("revision") or 1),
                    body=written,
                    body_digest=str(written.get("body_digest") or ""),
                    change_kind="created",
                    actor_id=actor_id,
                    actor_name=actor_name,
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written


def set_rollout(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    rollout_mode: str,
    rollout_percent: int,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Advance or retreat a function's staged rollout, recording the stage it left.

    Reaching ``enforce`` at 100% is a sequence of audited writes rather than one checkbox, and
    every stage leaves a revision behind — which is what lets an operator answer "what was this
    function doing an hour ago" without inferring it from a sentence.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function.
        rollout_mode: ``simulate`` or ``enforce``.
        rollout_percent: 0 to 100.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The updated function row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When ``function_id`` names no function on this lane.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            prior = _fetch_one(
                cursor,
                """
                SELECT *
                  FROM apiome.slate_functions
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (function_id, environment_id, tenant_id),
            )
            if prior is None:
                raise SlateFunctionStoreError(
                    "function_not_found", f"Function {function_id} was not found on this lane."
                )
            _append_revision(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                function_id=function_id,
                revision=int(prior.get("revision") or 1),
                body=prior,
                body_digest=str(prior.get("body_digest") or ""),
                change_kind="rollout-changed",
                actor_id=actor_id,
                actor_name=actor_name,
            )
            written = _fetch_one(
                cursor,
                """
                UPDATE apiome.slate_functions
                   SET rollout_mode = %s,
                       rollout_percent = %s,
                       revision = revision + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING *
                """,
                (rollout_mode, rollout_percent, function_id, environment_id, tenant_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def delete_function(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> bool:
    """Remove a function, keeping its body.

    The revision is written first and deliberately outlives the row: V189 gives
    ``slate_function_revisions.function_id`` no foreign key precisely because a deleted function is
    the case where "revert my change" is most needed. The capability grants, egress allowances,
    secret references and variants hanging off it go with it, by CASCADE — deny-by-default means a
    deleted function's privileges cannot outlive it.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: Function to remove.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        True when a function was removed.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When ``function_id`` names no function on this lane.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            prior = _fetch_one(
                cursor,
                """
                SELECT *
                  FROM apiome.slate_functions
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (function_id, environment_id, tenant_id),
            )
            if prior is None:
                raise SlateFunctionStoreError(
                    "function_not_found", f"Function {function_id} was not found on this lane."
                )
            _append_revision(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                function_id=function_id,
                revision=int(prior.get("revision") or 1),
                body=prior,
                body_digest=str(prior.get("body_digest") or ""),
                change_kind="deleted",
                actor_id=actor_id,
                actor_name=actor_name,
            )
            cursor.execute(
                """
                DELETE FROM apiome.slate_functions
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (function_id, environment_id, tenant_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def list_revisions(
    db: _DbLike, *, tenant_id: str, function_id: str, limit: int = 50
) -> List[Dict[str, Any]]:
    """Load a function's revision history, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        function_id: The function.
        limit: How many revisions to return.

    Returns:
        Revision rows, newest first. Scoped by tenant rather than by environment so a deleted
        function's history is still readable, which is the case a revert cares about most.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_function_revisions
             WHERE function_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY revision DESC
             LIMIT %s
            """,
            (function_id, tenant_id, limit),
        )


def last_simulated_at(db: _DbLike, *, tenant_id: str, function_id: str) -> Optional[datetime]:
    """When this function last stood in simulate mode.

    :func:`app.slate_functions.evaluate_function_safety` refuses ``enforce-without-simulation``
    when this is absent, and it is a fact about history rather than about the body being written —
    so it is reconstructed here from the revision trail rather than taken from the request, where
    a client could simply assert it.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        function_id: The function.

    Returns:
        The timestamp of the most recent revision whose body was in simulate mode, or None when
        the function has never run in simulate.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        row = _fetch_one(
            cursor,
            """
            SELECT at
              FROM apiome.slate_function_revisions
             WHERE function_id = %s::uuid
               AND tenant_id = %s::uuid
               AND body ->> 'rollout_mode' = 'simulate'
             ORDER BY at DESC
             LIMIT 1
            """,
            (function_id, tenant_id),
        )
    return None if row is None else row.get("at")


def function_evaluation_context(
    db: _DbLike, *, tenant_id: str, environment_id: str, function_id: Optional[str]
) -> Dict[str, Any]:
    """Reconstruct the two facts about a function's *history* that its body cannot state.

    :func:`app.slate_functions.normalize_function` reads ``simulated_at`` and
    ``previous_rollout_percent``, and neither is a column in V189. That is deliberate on both
    sides. They are not properties of the body being written — they are properties of what this
    function has already done — so a body cannot carry them honestly, and the pure module is
    query-free by design and cannot go and look. The derivation therefore belongs here, in the one
    layer that can read the revision trail, and it must not be delegated to the request: a client
    that could assert ``simulated_at`` could promote a function straight to enforcing, which is the
    lockout the ``enforce-without-simulation`` refusal exists to prevent.

    ``simulated_at`` comes from the revision trail, because "has this function ever stood in
    simulate" is a question only history answers. ``previous_rollout_percent`` comes from the live
    row, because the stage a function is *leaving* is the stage it is in right now; the newest
    revision records the state before the previous edit and would be one change stale. When the
    function row is gone — a revert after a delete — the newest revision is the best remaining
    answer and is used instead.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function, or None when the body being evaluated is a create. A function
            that does not exist yet has no history, and both facts are correctly absent — which is
            why a create that asks to enforce immediately is refused.

    Returns:
        ``{"simulated_at": ..., "previous_rollout_percent": ...}``, either value None when the
        history does not support it.
    """
    if not function_id:
        return {"simulated_at": None, "previous_rollout_percent": None}

    simulated_at = last_simulated_at(db, tenant_id=tenant_id, function_id=function_id)

    current = get_function(
        db, tenant_id=tenant_id, environment_id=environment_id, function_id=function_id
    )
    if current is not None and current.get("rollout_percent") is not None:
        previous = int(current["rollout_percent"])
    else:
        newest = list_revisions(db, tenant_id=tenant_id, function_id=function_id, limit=1)
        body = dict(newest[0].get("body") or {}) if newest else {}
        previous = (
            None if body.get("rollout_percent") is None else int(body["rollout_percent"])
        )

    return {"simulated_at": simulated_at, "previous_rollout_percent": previous}


def revert_function(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    revision: int,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Restore a function to a stored revision.

    Reverting applies the recorded document. The state being left is itself recorded first, as a
    ``reverted`` revision, so a revert of a revert reads correctly in history rather than looking
    like the original change happening twice.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function.
        revision: Which stored revision to apply.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The restored function row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When the function or the named revision does not exist.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            target = _fetch_one(
                cursor,
                """
                SELECT *
                  FROM apiome.slate_function_revisions
                 WHERE function_id = %s::uuid AND tenant_id = %s::uuid AND revision = %s
                """,
                (function_id, tenant_id, revision),
            )
            if target is None:
                raise SlateFunctionStoreError(
                    "revision_not_found",
                    f"Function {function_id} has no revision {revision} to revert to.",
                )
            prior = _fetch_one(
                cursor,
                """
                SELECT *
                  FROM apiome.slate_functions
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (function_id, environment_id, tenant_id),
            )
            if prior is None:
                raise SlateFunctionStoreError(
                    "function_not_found", f"Function {function_id} was not found on this lane."
                )
            _append_revision(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                function_id=function_id,
                revision=int(prior.get("revision") or 1),
                body=prior,
                body_digest=str(prior.get("body_digest") or ""),
                change_kind="reverted",
                actor_id=actor_id,
                actor_name=actor_name,
            )

            body = dict(target.get("body") or {})
            assignments = ", ".join(
                f"{column} = {_function_placeholder(column)}" for column in _FUNCTION_COLUMNS
            )
            written = _fetch_one(
                cursor,
                f"""
                UPDATE apiome.slate_functions
                   SET {assignments},
                       revision = revision + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING *
                """,
                (
                    *[body.get(column) for column in _FUNCTION_COLUMNS],
                    function_id,
                    environment_id,
                    tenant_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Versions ────────────────────────────────────────────────────────────────


def list_versions(
    db: _DbLike, *, tenant_id: str, function_id: str, limit: int = 50
) -> List[Dict[str, Any]]:
    """Load a function's immutable versions, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        function_id: The function.
        limit: How many versions to return.

    Returns:
        Version rows, newest revision first.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_function_versions
             WHERE function_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY revision DESC
             LIMIT %s
            """,
            (function_id, tenant_id, limit),
        )


def add_version(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    source_digest: str,
    body: Mapping[str, Any],
    runtime: str,
    source_bytes: Optional[int],
    source_origin: str,
    source_ref: Optional[str],
    activate: bool,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Record a new immutable source version, optionally promoting it.

    Versions are written once and never updated: promoting different code moves
    ``slate_functions.active_version_id`` rather than editing a version in place. Promoting is
    still a change to the function, so the function's prior body is recorded as a
    ``version-added`` revision before the pointer moves — which is what makes "put the previous
    code back" a document to apply rather than a memory to reconstruct.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function this version belongs to.
        source_digest: Content address of the source.
        body: The complete version manifest.
        runtime: Runtime this version was built for.
        source_bytes: Size of the source, when known.
        source_origin: ``upload``, ``build`` or ``import``.
        source_ref: Commit, build id or upload reference.
        activate: Whether to make this the live version.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The written version row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When ``function_id`` names no function on this lane.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            prior = _fetch_one(
                cursor,
                """
                SELECT *
                  FROM apiome.slate_functions
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (function_id, environment_id, tenant_id),
            )
            if prior is None:
                raise SlateFunctionStoreError(
                    "function_not_found", f"Function {function_id} was not found on this lane."
                )
            _append_revision(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                function_id=function_id,
                revision=int(prior.get("revision") or 1),
                body=prior,
                body_digest=str(prior.get("body_digest") or ""),
                change_kind="version-added",
                actor_id=actor_id,
                actor_name=actor_name,
            )

            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_function_versions
                    (tenant_id, environment_id, function_id, revision, source_digest, body,
                     runtime, source_bytes, source_origin, source_ref, created_by_actor_id,
                     created_by_actor_name)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    function_id,
                    int(prior.get("revision") or 1) + 1,
                    source_digest,
                    json.dumps(_json(dict(body))),
                    runtime,
                    source_bytes,
                    source_origin,
                    source_ref,
                    actor_id,
                    actor_name,
                ),
            )
            if written is None:
                raise SlateFunctionStoreError(
                    "function_not_found", "The function version could not be created."
                )

            if activate:
                cursor.execute(
                    """
                    UPDATE apiome.slate_functions
                       SET active_version_id = %s::uuid,
                           revision = revision + 1,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (str(written["id"]), function_id, environment_id, tenant_id),
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written


# ─── Secret references ───────────────────────────────────────────────────────


def list_secret_refs(
    db: _DbLike, *, tenant_id: str, environment_id: str, function_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Load the secret references declared on a lane, or on one function.

    Nothing returned here can hold a secret value: V189's table has no column able to. What these
    rows record is that a function *asked* for a name, which is exactly what an auditor reads.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: Restrict to one function, or None for the whole lane.

    Returns:
        Secret reference rows, in alias order.
    """
    clauses = ["environment_id = %s::uuid", "tenant_id = %s::uuid"]
    params: List[Any] = [environment_id, tenant_id]
    if function_id:
        clauses.append("function_id = %s::uuid")
        params.append(function_id)

    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT *
              FROM apiome.slate_function_secret_refs
             WHERE {" AND ".join(clauses)}
             ORDER BY alias
            """,
            tuple(params),
        )


def set_secret_ref(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    secret_name: str,
    alias: str,
    scope: str,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Declare, or redeclare, a secret reference on a function.

    A name, an alias and a scope. There is no value parameter here because there is no value
    column there, and the absence is the guarantee: exposure is a schema impossibility rather than
    a validation somebody has to keep passing.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function declaring it.
        secret_name: Name of the secret in the vault that holds the material.
        alias: Identifier the function code binds to.
        scope: ``function`` or ``environment``.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The written reference row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_function_secret_refs
                    (tenant_id, environment_id, function_id, secret_name, alias, scope,
                     actor_id, actor_name)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s)
                ON CONFLICT (function_id, alias) DO UPDATE
                    SET secret_name = EXCLUDED.secret_name,
                        scope = EXCLUDED.scope,
                        actor_id = EXCLUDED.actor_id,
                        actor_name = EXCLUDED.actor_name
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    function_id,
                    secret_name,
                    alias,
                    scope,
                    actor_id,
                    actor_name,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def delete_secret_ref(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    ref_id: str,
    expected_policy_version: int,
) -> bool:
    """Withdraw a secret reference.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function that declared it.
        ref_id: The reference.
        expected_policy_version: The version the caller read.

    Returns:
        True when a reference was removed.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When the reference is not on this function.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            removed = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_function_secret_refs
                 WHERE id = %s::uuid AND function_id = %s::uuid
                   AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING id
                """,
                (ref_id, function_id, environment_id, tenant_id),
            )
            if removed is None:
                raise SlateFunctionStoreError(
                    "secret_ref_not_found",
                    f"Secret reference {ref_id} was not found on this function.",
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


# ─── Capabilities (deny-by-default: a row is a grant) ────────────────────────


def list_capabilities(
    db: _DbLike, *, tenant_id: str, environment_id: str, function_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Load the capability grants on a lane, or on one function.

    An absent row is a denial, so an empty result means "this function may do nothing" rather than
    "nothing is configured". Expired grants are returned rather than filtered out: a privilege that
    has just lapsed is exactly what an operator investigating a newly-failing function needs to
    see.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: Restrict to one function, or None for the whole lane.

    Returns:
        Grant rows, in capability order.
    """
    clauses = ["environment_id = %s::uuid", "tenant_id = %s::uuid"]
    params: List[Any] = [environment_id, tenant_id]
    if function_id:
        clauses.append("function_id = %s::uuid")
        params.append(function_id)

    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT *
              FROM apiome.slate_function_capabilities
             WHERE {" AND ".join(clauses)}
             ORDER BY capability
            """,
            tuple(params),
        )


def grant_capability(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    capability: str,
    reason: str,
    expires_at: Optional[datetime],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
    actor_key: str,
) -> Dict[str, Any]:
    """Grant one runtime capability to a function.

    Writing the row *is* the grant. There is no ``granted`` boolean here because V189 has no such
    column: a bug that fails to write cannot accidentally grant, it can only fail closed, and
    revoking is :func:`revoke_capability` deleting the row rather than flipping a flag.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function being granted.
        capability: One of V189's eight capabilities.
        reason: Why. NOT NULL in V189, and refused with a sentence by
            :func:`app.slate_functions.evaluate_capability_safety` before it reaches the column.
        expires_at: When the grant lapses, or None for a permanent one. The capabilities whose
            legitimate uses are incidents and migrations are refused without one.
        expected_policy_version: The version the caller read.
        actor_id: Granting user, when a person acted.
        actor_name: Display name of the granter.
        actor_key: Immutable identity of the granter, so offboarding cannot erase who widened a
            function's privileges.

    Returns:
        The written grant row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_function_capabilities
                    (tenant_id, environment_id, function_id, capability, reason, expires_at,
                     granted_by_actor_id, granted_by_actor_name, granted_by_actor_key)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (function_id, capability) DO UPDATE
                    SET reason = EXCLUDED.reason,
                        expires_at = EXCLUDED.expires_at,
                        granted_at = CURRENT_TIMESTAMP,
                        granted_by_actor_id = EXCLUDED.granted_by_actor_id,
                        granted_by_actor_name = EXCLUDED.granted_by_actor_name,
                        granted_by_actor_key = EXCLUDED.granted_by_actor_key
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    function_id,
                    capability,
                    reason,
                    expires_at,
                    actor_id,
                    actor_name,
                    actor_key,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def revoke_capability(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    capability: str,
    expected_policy_version: int,
) -> bool:
    """Revoke one capability by deleting its grant row.

    Revoking is a DELETE and never an UPDATE, because the absence of a row is the denial. A
    revocation that wrote ``granted = FALSE`` would leave the denial dependent on a value being
    read correctly; this leaves it dependent on nothing.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function.
        capability: The capability to revoke.
        expected_policy_version: The version the caller read.

    Returns:
        True when a grant was removed.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When the function held no such grant.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            removed = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_function_capabilities
                 WHERE function_id = %s::uuid AND capability = %s
                   AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING id
                """,
                (function_id, capability, environment_id, tenant_id),
            )
            if removed is None:
                raise SlateFunctionStoreError(
                    "capability_not_found",
                    f"Capability {capability} is not granted to function {function_id}.",
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


# ─── Egress rules (deny-by-default: a row is an allowlist entry) ─────────────


def list_egress_rules(
    db: _DbLike, *, tenant_id: str, environment_id: str, function_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Load the egress allowlist entries on a lane, or on one function.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: Restrict to one function, or None for the whole lane.

    Returns:
        Allowlist rows, narrowest destination kind first then by destination — the order an SSRF
        review reads them in.
    """
    clauses = ["environment_id = %s::uuid", "tenant_id = %s::uuid"]
    params: List[Any] = [environment_id, tenant_id]
    if function_id:
        clauses.append("function_id = %s::uuid")
        params.append(function_id)

    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT *
              FROM apiome.slate_function_egress_rules
             WHERE {" AND ".join(clauses)}
             ORDER BY destination_kind, destination
            """,
            tuple(params),
        )


def set_egress_rule(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    destination_kind: str,
    destination: str,
    scheme: str,
    port: Optional[int],
    methods: Sequence[str],
    reason: str,
    expires_at: Optional[datetime],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
    actor_key: str,
) -> Dict[str, Any]:
    """Allowlist one outbound destination for a function.

    Deny-by-default in the same shape as a capability: the row is the allowance, and there is no
    wildcard destination kind to write, because an egress allowlist with a wildcard is a denylist
    wearing a costume.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function permitted to reach it.
        destination_kind: ``exact-host`` or ``host-suffix``.
        destination: The host or host suffix.
        scheme: ``https`` or ``http``.
        port: The permitted port, or None for the scheme default.
        methods: HTTP methods permitted; empty means every method.
        reason: Why this destination is reachable.
        expires_at: When the allowance lapses, or None for a permanent one.
        expected_policy_version: The version the caller read.
        actor_id: Granting user, when a person acted.
        actor_name: Display name of the granter.
        actor_key: Immutable identity of the granter.

    Returns:
        The written allowlist row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_function_egress_rules
                    (tenant_id, environment_id, function_id, destination_kind, destination,
                     scheme, port, methods, reason, expires_at, granted_by_actor_id,
                     granted_by_actor_name, granted_by_actor_key)
                VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (function_id, destination_kind, destination) DO UPDATE
                    SET scheme = EXCLUDED.scheme,
                        port = EXCLUDED.port,
                        methods = EXCLUDED.methods,
                        reason = EXCLUDED.reason,
                        expires_at = EXCLUDED.expires_at,
                        granted_at = CURRENT_TIMESTAMP,
                        granted_by_actor_id = EXCLUDED.granted_by_actor_id,
                        granted_by_actor_name = EXCLUDED.granted_by_actor_name,
                        granted_by_actor_key = EXCLUDED.granted_by_actor_key
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    function_id,
                    destination_kind,
                    destination,
                    scheme,
                    port,
                    list(methods or []),
                    reason,
                    expires_at,
                    actor_id,
                    actor_name,
                    actor_key,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def delete_egress_rule(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_id: str,
    rule_id: str,
    expected_policy_version: int,
) -> bool:
    """Withdraw an egress allowance by deleting its row.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: The function.
        rule_id: The allowlist entry.
        expected_policy_version: The version the caller read.

    Returns:
        True when an allowance was removed.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When the entry is not on this function.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            removed = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_function_egress_rules
                 WHERE id = %s::uuid AND function_id = %s::uuid
                   AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING id
                """,
                (rule_id, function_id, environment_id, tenant_id),
            )
            if removed is None:
                raise SlateFunctionStoreError(
                    "egress_rule_not_found",
                    f"Egress rule {rule_id} was not found on this function.",
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


# ─── Personalization variants ────────────────────────────────────────────────


def list_variants(
    db: _DbLike, *, tenant_id: str, environment_id: str, function_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Load a lane's personalization variants, or one function's.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_id: Restrict to one function, or None for the whole lane.

    Returns:
        Variant rows in selection order. V189's ``UNIQUE (function_id, ordinal)`` makes that order
        total, so which variant a reader receives is reproducible.
    """
    clauses = ["environment_id = %s::uuid", "tenant_id = %s::uuid"]
    params: List[Any] = [environment_id, tenant_id]
    if function_id:
        clauses.append("function_id = %s::uuid")
        params.append(function_id)

    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT *
              FROM apiome.slate_personalization_variants
             WHERE {" AND ".join(clauses)}
             ORDER BY function_id, ordinal, id
            """,
            tuple(params),
        )


def upsert_variant(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    variant_id: Optional[str],
    function_id: str,
    values: Mapping[str, Any],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Create or replace a personalization variant.

    Audience rule, fallback, cache-key effect, analytics dimension, privacy class and consent
    basis are written in one statement because they are one row: split across writes they would
    drift, and the drift is invisible until a shared cache serves one reader's page to another.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        variant_id: Existing variant to replace, or None to create one.
        function_id: The function that selects between variants.
        values: Column values, already validated by
            :func:`app.slate_functions.evaluate_variant_safety`.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The written variant row.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When ``variant_id`` names no variant on this lane.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            params = (
                int(values.get("ordinal") or 0),
                str(values.get("label") or ""),
                str(values.get("audience_kind") or "geo"),
                json.dumps(_json(list(values.get("audience_matcher") or []))),
                str(values.get("fallback_variant") or ""),
                str(values.get("cache_key_effect") or "none"),
                str(values.get("analytics_dimension") or ""),
                str(values.get("privacy_class") or "non-personal"),
                str(values.get("consent_basis") or "not-required"),
                bool(values.get("enabled", True)),
                actor_id,
                actor_name,
            )
            if variant_id:
                written = _fetch_one(
                    cursor,
                    """
                    UPDATE apiome.slate_personalization_variants
                       SET ordinal = %s,
                           label = %s,
                           audience_kind = %s,
                           audience_matcher = %s::jsonb,
                           fallback_variant = %s,
                           cache_key_effect = %s,
                           analytics_dimension = %s,
                           privacy_class = %s,
                           consent_basis = %s,
                           enabled = %s,
                           actor_id = %s,
                           actor_name = %s,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                    RETURNING *
                    """,
                    (*params, variant_id, environment_id, tenant_id),
                )
                if written is None:
                    raise SlateFunctionStoreError(
                        "variant_not_found",
                        f"Personalization variant {variant_id} was not found on this lane.",
                    )
            else:
                written = _fetch_one(
                    cursor,
                    """
                    INSERT INTO apiome.slate_personalization_variants
                        (tenant_id, environment_id, function_id, ordinal, label, audience_kind,
                         audience_matcher, fallback_variant, cache_key_effect,
                         analytics_dimension, privacy_class, consent_basis, enabled, actor_id,
                         actor_name)
                    VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s::jsonb, %s, %s, %s, %s,
                            %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (tenant_id, environment_id, function_id, *params),
                )
                if written is None:
                    raise SlateFunctionStoreError(
                        "variant_not_found", "The personalization variant could not be created."
                    )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written


def delete_variant(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    variant_id: str,
    expected_policy_version: int,
) -> bool:
    """Remove a personalization variant.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        variant_id: The variant.
        expected_policy_version: The version the caller read.

    Returns:
        True when a variant was removed.

    Raises:
        SlateFunctionPolicyConflictError: On a stale ``expected_policy_version``.
        SlateFunctionStoreError: When the variant is not on this lane.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )
            removed = _fetch_one(
                cursor,
                """
                DELETE FROM apiome.slate_personalization_variants
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING id
                """,
                (variant_id, environment_id, tenant_id),
            )
            if removed is None:
                raise SlateFunctionStoreError(
                    "variant_not_found",
                    f"Personalization variant {variant_id} was not found on this lane.",
                )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


# ─── Approvals ───────────────────────────────────────────────────────────────


def list_approvals(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    subject_id: Optional[str] = None,
    digest: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load recorded approvals, optionally narrowed to one subject or one approved body.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        subject_id: Restrict to one subject. Used when checking an edit to an existing function,
            so an approval of the *previous* body is found and reported as ``approval-stale``
            rather than as no approval at all — the two need different actions.
        digest: Restrict to approvals of one exact body.

    Returns:
        Approval rows, newest first.
    """
    clauses = ["environment_id = %s::uuid", "tenant_id = %s::uuid"]
    params: List[Any] = [environment_id, tenant_id]
    if subject_id is not None:
        clauses.append("subject_id = %s")
        params.append(subject_id)
    if digest is not None:
        clauses.append("digest = %s")
        params.append(digest)

    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT *
              FROM apiome.slate_function_approvals
             WHERE {" AND ".join(clauses)}
             ORDER BY approved_at DESC
            """,
            tuple(params),
        )


def record_approval(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    subject_kind: str,
    subject_id: str,
    digest: str,
    author_actor_id: Optional[str],
    author_actor_name: str,
    author_actor_key: str,
    approver_actor_id: Optional[str],
    approver_actor_name: str,
    approver_actor_key: str,
    note: Optional[str],
) -> Dict[str, Any]:
    """Record a dual-control approval of one exact body.

    The distinctness of author and approver is checked in :mod:`app.slate_functions` so the
    operator meets a sentence, and again by V189's
    ``CHECK (approver_actor_key <> author_actor_key)`` so no code path can bypass it. Both are
    deliberate: the first is the explanation, the second is the guarantee.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        subject_kind: ``policy``, ``function``, ``version``, ``capability``, ``egress-rule`` or
            ``variant``.
        subject_id: Id of the subject.
        digest: The body that was reviewed, content-addressed.
        author_actor_id: The proposer's user id, when still present.
        author_actor_name: The proposer's display name.
        author_actor_key: The proposer's immutable identity.
        approver_actor_id: The approver's user id, when still present.
        approver_actor_name: The approver's display name.
        approver_actor_key: The approver's immutable identity.
        note: Optional reviewer note.

    Returns:
        The written approval row.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_function_approvals
                    (tenant_id, environment_id, subject_kind, subject_id, digest,
                     author_actor_id, author_actor_name, author_actor_key,
                     approver_actor_id, approver_actor_name, approver_actor_key, note)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (subject_id, digest, approver_actor_key) DO UPDATE
                    SET note = EXCLUDED.note
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    subject_kind,
                    subject_id,
                    digest,
                    author_actor_id,
                    author_actor_name,
                    author_actor_key,
                    approver_actor_id,
                    approver_actor_name,
                    approver_actor_key,
                    note,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Invocations ─────────────────────────────────────────────────────────────


def record_invocation(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    function_ref: str,
    function_label: str,
    route: str,
    method: str,
    release_id: Optional[str],
    region: Optional[str],
    variant_ref: Optional[str],
    outcome: str,
    denial_reason: Optional[str],
    evidence: Mapping[str, Any],
    retain_until: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Persist one function invocation record.

    ``source``, ``executed`` and ``edge_attached`` are literals in the statement below rather than
    parameters. There is no runtime tier, so nothing observed this request and nothing ran — and
    rather than trusting every caller to pass the honest value, this function offers no way to
    pass a dishonest one. V189 CHECKs the same three facts, so a future caller reaching the table
    by another route still cannot claim an execution.

    ``cpu_ms``, ``wall_ms`` and ``memory_peak_mb`` are equally absent. A simulation consumed none
    of them, and storing a zero would be a measurement where NULL is the honest absence of one.

    ``evidence`` is passed through :func:`redact_evidence` here, not by the caller. A redaction the
    caller could skip is a redaction that will eventually be skipped, and a function's inputs are
    the request itself.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        function_ref: Id of the function that decided, as text so the record outlives it.
        function_label: Its label as it read at the time, so a rename does not rewrite history.
        route: The request path.
        method: The request method.
        release_id: Release active at the time, when there is one.
        region: Region that would have handled the request, when known.
        variant_ref: Personalization variant selected, when one was.
        outcome: What the evaluation concluded. Never ``ran``; nothing here can produce it.
        denial_reason: Why a denial happened, quoted verbatim from the evaluation so the UI does
            not restate it and the two cannot drift.
        evidence: Raw request data; redacted here.
        retain_until: When the evidence must be purged. Defaults to 30 days after the invocation,
            because V189 forbids NULL and indefinite retention of request data is a liability
            rather than a feature.

    Returns:
        The written invocation row.
    """
    at = _now()
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_function_invocations
                    (tenant_id, environment_id, at, source, function_ref, function_label, route,
                     method, release_id, region, variant_ref, outcome, executed, edge_attached,
                     denial_reason, evidence, retain_until)
                VALUES (%s::uuid, %s::uuid, %s, 'policy-simulation', %s, %s, %s, %s, %s, %s, %s,
                        %s, FALSE, FALSE, %s, %s::jsonb, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    at,
                    function_ref,
                    function_label,
                    route,
                    method,
                    release_id,
                    region,
                    variant_ref,
                    outcome,
                    denial_reason,
                    json.dumps(redact_evidence(evidence)),
                    retain_until or (at + timedelta(days=_DEFAULT_RETENTION_DAYS)),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def list_invocations(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    limit: int = 50,
    function_ref: Optional[str] = None,
    outcome: Optional[str] = None,
    route: Optional[str] = None,
    release_id: Optional[str] = None,
    region: Optional[str] = None,
    variant_ref: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load a lane's invocation records, most recent first.

    The filter names are the designer's dimension ids, unchanged. Two vocabularies for the same
    axis would mean an operator filtering by ``function`` on screen and by ``functionRef`` in an
    export and quietly getting different answers.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        limit: How many records to return.
        function_ref: Restrict to one function.
        outcome: Restrict to one conclusion.
        route: Restrict to one request path.
        release_id: Restrict to the records during one release.
        region: Restrict to one region.
        variant_ref: Restrict to one personalization variant — "which function served this
            customer" narrows here.
        source: Restrict to ``policy-simulation`` or ``edge-observed``.

    Returns:
        Invocation rows, most recent first.
    """
    clauses = ["environment_id = %s::uuid", "tenant_id = %s::uuid"]
    params: List[Any] = [environment_id, tenant_id]
    for column, value, cast in (
        ("function_ref", function_ref, ""),
        ("outcome", outcome, ""),
        ("route", route, ""),
        ("release_id", release_id, "::uuid"),
        ("region", region, ""),
        ("variant_ref", variant_ref, ""),
        ("source", source, ""),
    ):
        if value:
            clauses.append(f"{column} = %s{cast}")
            params.append(value)
    params.append(limit)

    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            f"""
            SELECT *
              FROM apiome.slate_function_invocations
             WHERE {" AND ".join(clauses)}
             ORDER BY at DESC
             LIMIT %s
            """,
            tuple(params),
        )


def get_invocation(
    db: _DbLike, *, tenant_id: str, environment_id: str, invocation_id: str
) -> Optional[Dict[str, Any]]:
    """Load one invocation record.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        invocation_id: The record.

    Returns:
        The invocation row, or None when it is not on this lane.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT *
              FROM apiome.slate_function_invocations
             WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
            """,
            (invocation_id, environment_id, tenant_id),
        )


# ─── Audit ───────────────────────────────────────────────────────────────────


def append_audit(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str,
    subject_kind: str,
    subject_id: Optional[str],
    summary: str,
    detail: Optional[str] = None,
) -> None:
    """Append a function audit entry.

    Used for every policy change, capability and egress grant, variant change, approval, revert and
    refusal — and for evidence exports, because who read the record of who let a function read
    secrets is itself part of that record. A *refused* action must leave a trace even though
    nothing changed: refusing to widen a function's privileges during an incident is exactly the
    event the review afterwards asks about.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.
        subject_kind: One of V189's eleven subjects, ``export`` included.
        subject_id: Id of the subject row, when there is one.
        summary: What happened.
        detail: Extra context, e.g. the refusal reason and its sentence.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO apiome.slate_function_audit
                    (tenant_id, environment_id, actor_id, actor_name, actor_kind, subject_kind,
                     subject_id, summary, detail)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    environment_id,
                    actor_id,
                    actor_name,
                    actor_kind,
                    subject_kind,
                    subject_id,
                    summary,
                    detail,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def list_audit(
    db: _DbLike, *, tenant_id: str, environment_id: str, limit: int = 100
) -> List[Dict[str, Any]]:
    """Load a lane's function audit trail, most recent first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        limit: How many entries to return.

    Returns:
        Audit rows, most recent first.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_function_audit
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY at DESC
             LIMIT %s
            """,
            (environment_id, tenant_id, limit),
        )
