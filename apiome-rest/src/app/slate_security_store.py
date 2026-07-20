"""Persistence for the Slate security control plane — UXE-3.2 (private-suite#2474).

Reads and writes the V188 tables. Follows :mod:`app.slate_cache_store` exactly: a small
``_DbLike`` protocol rather than a dependency on the concrete ``Database`` singleton, so the whole
surface can be exercised against a fake connection without a live Postgres.

**Concurrency.** Every write that changes policy goes through :func:`bump_policy_version`, whose
conditional UPDATE mirrors the cache plane's:

    UPDATE apiome.slate_security_policies
       SET policy_version = policy_version + 1
     WHERE environment_id = %s AND policy_version = %s

The second of two simultaneous edits matches zero rows and is refused as
``policy-version-conflict`` rather than silently overwriting the first. During an incident two
operators editing the same lane is the normal case, not the exotic one, so there is deliberately no
last-write-wins path.

**Every rule write leaves a document behind.** :func:`upsert_rule`, :func:`set_rollout`,
:func:`revert_rule` and :func:`delete_rule` all write the rule body to
``slate_security_rule_revisions`` before mutating anything. §29.4's "every rule change can be
reverted" is only true if reverting means applying a stored body rather than reconstructing intent
from an audit sentence — so the revision is written inside the same transaction as the change, and
a rolled-back change leaves no orphan revision.

**Redaction is this module's job, not the caller's.** V188 constrains ``evidence`` to an allowlist
of *top-level keys*, which is a backstop and not a mechanism: a nested object under an allowed key
would satisfy that CHECK while carrying an entire request body into the database.
:func:`redact_evidence` is the mechanism. It drops every key outside the allowlist, drops every
value that is not a scalar, bounds the two free-text fields, and reduces any address to a network
prefix. Callers pass raw request data to it and cannot pass raw request data past it.

**Nothing here blocks anything.** ``deploy/`` is a single Caddyfile with no WAF behind it.
:func:`record_event` therefore writes ``source = 'policy-simulation'``, ``mitigated = FALSE`` and
``edge_attached = FALSE`` as literals rather than as parameters: there is no argument by which a
caller can ask this module to record an observation or a mitigation, and V188's CHECKs refuse the
row if one ever appeared. An unenforced cache rule wastes a purge; an unenforced WAF rule means
somebody believes they are stopping an attacker and is not.
"""

from __future__ import annotations

import ipaddress
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

__all__ = [
    "EVIDENCE_ALLOWED_KEYS",
    "SlateSecurityPolicyConflictError",
    "SlateSecurityStoreError",
    "append_audit",
    "bump_policy_version",
    "create_exception",
    "delete_exception",
    "delete_rule",
    "ensure_policy",
    "get_event",
    "get_policy",
    "get_rule",
    "last_simulated_at",
    "list_approvals",
    "list_audit",
    "list_events",
    "list_exceptions",
    "list_managed_groups",
    "list_revisions",
    "list_rules",
    "record_approval",
    "record_event",
    "redact_evidence",
    "revert_rule",
    "rule_evaluation_context",
    "set_managed_group",
    "set_presets",
    "set_rollout",
    "upsert_rule",
]


class _DbLike(Protocol):
    """Minimal database surface used by this module."""

    def connect(self) -> Any: ...


class SlateSecurityStoreError(Exception):
    """A security control-plane row was missing or malformed.

    Carries a machine-readable ``code`` so the REST layer maps it to a status without
    string-matching. Codes: ``policy_not_found``, ``rule_not_found``, ``revision_not_found``,
    ``exception_not_found``, ``event_not_found``.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SlateSecurityPolicyConflictError(Exception):
    """Another operator changed the lane's security policy first.

    Raised when the conditional UPDATE matched zero rows. The REST layer turns this into the
    ``policy-version-conflict`` refusal, whose sentence tells the operator to re-read.
    """

    def __init__(self, environment_id: str, expected: int, actual: Optional[int]) -> None:
        self.environment_id = environment_id
        self.expected_policy_version = expected
        self.actual_policy_version = actual
        super().__init__(
            f"Environment {environment_id} security policy changed while this edit was being "
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

#: The only keys that may appear in ``slate_security_events.evidence``. Identical to V188's CHECK
#: array, and deliberately an allowlist: a denylist of sensitive headers fails open on the field
#: nobody thought of, and the field nobody thought of is the one that carries the session.
EVIDENCE_ALLOWED_KEYS = (
    "method",
    "path",
    "query",
    "userAgent",
    "country",
    "asn",
    "clientIpPrefix",
    "matchedFragment",
    "statusCode",
    "botClass",
)

#: Keys whose values are attacker-influenced free text. Bounded so a single event cannot carry a
#: kilobyte of payload into the audit record under a permitted name.
_BOUNDED_KEYS = ("userAgent", "matchedFragment")

#: The bound. Long enough for a real user-agent string and for the fragment that explains why a
#: rule matched; short enough that the field cannot be used as storage.
_BOUNDED_LENGTH = 256

#: Keys that must be reduced to a network prefix before they are stored.
_ADDRESS_KEYS = ("clientIpPrefix",)

#: How far an address is generalized. A /24 identifies the network a probe came from — which is
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
    """Reduce request data to the evidence a security event is permitted to carry.

    This is the mechanism; V188's ``evidence - ARRAY[...] = '{}'`` CHECK is the backstop. The
    distinction matters because that CHECK constrains only *top-level keys*: a value of
    ``{"userAgent": {"cookie": "session=..."}}`` satisfies it perfectly while carrying exactly
    what the constraint exists to exclude. Four things happen here, and each closes one of those
    routes:

    1. Every key outside :data:`EVIDENCE_ALLOWED_KEYS` is dropped, including keys that differ only
       in case — ``Cookie`` is not a permitted key and neither is ``cookie``.
    2. Every value that is not a scalar is dropped outright rather than stringified. Rendering a
       nested object as text would preserve its contents under a permitted name, which is the
       smuggling route this step exists to close.
    3. ``userAgent`` and ``matchedFragment`` are truncated to :data:`_BOUNDED_LENGTH`.
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

        # An address can arrive under any key — a matched fragment quoting a header, a query
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
    """Load a lane's security policy, scoped to its tenant.

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
              FROM apiome.slate_security_policies
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
) -> Dict[str, Any]:
    """Return a lane's security policy, creating the shipped default if it has none.

    A lane with no row is not a lane with no policy — it is a lane running Core coverage with the
    Balanced bot preset and the Standard rate budget, which is what V188's column defaults say.
    Materializing that on first read keeps "what is this lane protected by" answerable with one
    query and gives the optimistic-concurrency token something to count from.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        site_id: Site the environment belongs to.
        environment_id: The lane.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

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
                INSERT INTO apiome.slate_security_policies
                    (tenant_id, site_id, environment_id, managed_ruleset, bot_preset,
                     rate_preset, challenge_mode, updated_by_actor_id, updated_by_actor_name)
                VALUES (%s::uuid, %s::uuid, %s::uuid, 'core', 'balanced', 'standard', 'managed',
                        %s, %s)
                ON CONFLICT (environment_id) DO NOTHING
                RETURNING *
                """,
                (tenant_id, site_id, environment_id, actor_id, actor_name),
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
        raise SlateSecurityStoreError(
            "policy_not_found",
            f"Security policy for environment {environment_id} could not be read.",
        )
    return policy


def bump_policy_version(cursor: Any, *, environment_id: str, expected_policy_version: int) -> int:
    """Advance a lane's policy version, refusing a stale expectation.

    The conditional UPDATE is the concurrency control. Callers run this inside the same
    transaction as the write it guards, so a refused edit leaves nothing behind — including the
    revision row a rule write would otherwise have left as a record of a change that never
    happened.

    Args:
        cursor: Open cursor inside the caller's transaction.
        environment_id: The lane.
        expected_policy_version: The version the caller read before preparing this edit.

    Returns:
        The new policy version.

    Raises:
        SlateSecurityPolicyConflictError: When the expectation was stale, i.e. someone else wrote
            first.
    """
    row = _fetch_one(
        cursor,
        """
        UPDATE apiome.slate_security_policies
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
              FROM apiome.slate_security_policies
             WHERE environment_id = %s::uuid
            """,
            (environment_id,),
        )
        raise SlateSecurityPolicyConflictError(
            environment_id,
            expected_policy_version,
            None if actual is None else int(actual["policy_version"]),
        )
    return int(row["policy_version"])


def set_presets(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    managed_ruleset: str,
    bot_preset: str,
    rate_preset: str,
    challenge_mode: str,
    preset_overrides: Optional[Mapping[str, Any]],
    managed_off_reason: Optional[str],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Change a lane's managed tier and its bot, rate and challenge settings.

    All four move together because they are one decision. Splitting them into four endpoints
    would let a lane sit in a state nobody chose — Strict coverage with bot classification off, say
    — between two requests, and the audit trail would show the intermediate state as though
    somebody had wanted it.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        managed_ruleset: ``off``, ``core`` or ``strict``.
        bot_preset: One of the four bot presets.
        rate_preset: One of the four rate presets.
        challenge_mode: ``off``, ``managed`` or ``always``.
        preset_overrides: Fields moved off a preset default.
        managed_off_reason: Why the managed ruleset is off. Required by V188's CHECK when it is,
            and refused with a sentence by :func:`app.slate_security.evaluate_policy_safety`
            before it ever reaches the constraint.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The updated policy row.

    Raises:
        SlateSecurityPolicyConflictError: On a stale ``expected_policy_version``.
        SlateSecurityStoreError: When the lane has no policy row.
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
                UPDATE apiome.slate_security_policies
                   SET managed_ruleset = %s,
                       bot_preset = %s,
                       rate_preset = %s,
                       challenge_mode = %s,
                       preset_overrides = %s::jsonb,
                       managed_off_reason = %s,
                       updated_by_actor_id = %s,
                       updated_by_actor_name = %s
                 WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING *
                """,
                (
                    managed_ruleset,
                    bot_preset,
                    rate_preset,
                    challenge_mode,
                    json.dumps(_json(dict(preset_overrides or {}))),
                    managed_off_reason,
                    actor_id,
                    actor_name,
                    environment_id,
                    tenant_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    if updated is None:
        raise SlateSecurityStoreError(
            "policy_not_found", f"Security policy for environment {environment_id} was not found."
        )
    return updated


# ─── Managed groups ──────────────────────────────────────────────────────────


def list_managed_groups(
    db: _DbLike, *, tenant_id: str, environment_id: str
) -> List[Dict[str, Any]]:
    """Load a lane's managed-group overrides.

    A row exists only where an operator moved a group off its catalog default, so an empty result
    means "everything is as shipped" rather than "nothing is configured".

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        Override rows in catalog-id order.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_security_managed_groups
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY group_id
            """,
            (environment_id, tenant_id),
        )


def set_managed_group(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    group_id: str,
    mode: str,
    reason: Optional[str],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Set one managed WAF group's mode on this lane.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        group_id: Catalog id of the group.
        mode: ``off``, ``log``, ``challenge`` or ``block``.
        reason: Why. Required by V188 for ``off`` and ``log``, the two modes that remove
            protection.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The written override row.

    Raises:
        SlateSecurityPolicyConflictError: On a stale ``expected_policy_version``.
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
                INSERT INTO apiome.slate_security_managed_groups
                    (tenant_id, environment_id, group_id, mode, reason, actor_id, actor_name)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s)
                ON CONFLICT (environment_id, group_id) DO UPDATE
                    SET mode = EXCLUDED.mode,
                        reason = EXCLUDED.reason,
                        updated_at = CURRENT_TIMESTAMP,
                        actor_id = EXCLUDED.actor_id,
                        actor_name = EXCLUDED.actor_name
                RETURNING *
                """,
                (tenant_id, environment_id, group_id, mode, reason, actor_id, actor_name),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Rules ───────────────────────────────────────────────────────────────────

#: The columns a rule write sets, in the order the INSERT and UPDATE below use them. Kept as one
#: literal so the two statements cannot drift into setting different subsets.
_RULE_COLUMNS = (
    "ordinal",
    "enabled",
    "label",
    "matcher_kind",
    "matcher_value",
    "matcher_methods",
    "matcher_hosts",
    "action",
    "rate_requests",
    "rate_window_seconds",
    "rollout_mode",
    "rollout_percent",
    "expires_at",
    "acknowledged_warnings",
    "body_digest",
)


def list_rules(db: _DbLike, *, tenant_id: str, environment_id: str) -> List[Dict[str, Any]]:
    """Load a lane's custom security rules in precedence order.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        Rule rows ordered by ``ordinal``. The order is the evaluation order, and V188's
        ``UNIQUE (environment_id, ordinal)`` is what makes it total rather than a set with ties.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_security_rules
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY ordinal, id
            """,
            (environment_id, tenant_id),
        )


def get_rule(
    db: _DbLike, *, tenant_id: str, environment_id: str, rule_id: str
) -> Optional[Dict[str, Any]]:
    """Load one custom rule, scoped to its lane and tenant.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: The rule.

    Returns:
        The rule row, or None when it is not on this lane.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT *
              FROM apiome.slate_security_rules
             WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
            """,
            (rule_id, environment_id, tenant_id),
        )


def _append_revision(
    cursor: Any,
    *,
    tenant_id: str,
    environment_id: str,
    rule_id: str,
    revision: int,
    body: Mapping[str, Any],
    body_digest: str,
    change_kind: str,
    actor_id: Optional[str],
    actor_name: str,
) -> None:
    """Record a rule body as it stood, inside the caller's transaction.

    Args:
        cursor: Open cursor inside the caller's transaction, so a rolled-back change leaves no
            revision claiming it happened.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: The rule this revision describes.
        revision: Which revision of that rule this body was.
        body: The complete body, so reverting applies a document rather than reconstructing
            intent from a sentence.
        body_digest: The digest of that body.
        change_kind: What produced this revision.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
    """
    cursor.execute(
        """
        INSERT INTO apiome.slate_security_rule_revisions
            (tenant_id, environment_id, rule_id, revision, body, body_digest, change_kind,
             actor_id, actor_name)
        VALUES (%s::uuid, %s::uuid, %s::uuid, %s, %s::jsonb, %s, %s, %s, %s)
        ON CONFLICT (rule_id, revision) DO NOTHING
        """,
        (
            tenant_id,
            environment_id,
            rule_id,
            revision,
            json.dumps(_json(dict(body))),
            body_digest,
            change_kind,
            actor_id,
            actor_name,
        ),
    )


def upsert_rule(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    rule_id: Optional[str],
    values: Mapping[str, Any],
    conditions: Sequence[Mapping[str, Any]],
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
    actor_kind: str = "user",
) -> Dict[str, Any]:
    """Create or replace a custom security rule, recording a revision in the same transaction.

    On a replace the *prior* body is written to ``slate_security_rule_revisions`` before the
    UPDATE runs, so a revert has a document to apply. On a create the new body is recorded as
    revision 1, which gives a rule that is later edited a first state to go back to rather than
    only its second.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: Existing rule to replace, or None to create one.
        values: Column values, already validated by :mod:`app.slate_security`.
        conditions: The rule's non-route predicates.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.

    Returns:
        The written rule row.

    Raises:
        SlateSecurityPolicyConflictError: On a stale ``expected_policy_version``.
        SlateSecurityStoreError: When ``rule_id`` names no rule on this lane.
    """
    payload = [values.get(column) for column in _RULE_COLUMNS]
    encoded_conditions = json.dumps(_json(list(conditions or [])))

    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            bump_policy_version(
                cursor,
                environment_id=environment_id,
                expected_policy_version=expected_policy_version,
            )

            if rule_id:
                prior = _fetch_one(
                    cursor,
                    """
                    SELECT *
                      FROM apiome.slate_security_rules
                     WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (rule_id, environment_id, tenant_id),
                )
                if prior is None:
                    raise SlateSecurityStoreError(
                        "rule_not_found", f"Security rule {rule_id} was not found on this lane."
                    )
                _append_revision(
                    cursor,
                    tenant_id=tenant_id,
                    environment_id=environment_id,
                    rule_id=rule_id,
                    revision=int(prior.get("revision") or 1),
                    body=prior,
                    body_digest=str(prior.get("body_digest") or ""),
                    change_kind="disabled" if not values.get("enabled") else "updated",
                    actor_id=actor_id,
                    actor_name=actor_name,
                )

                assignments = ", ".join(f"{column} = %s" for column in _RULE_COLUMNS)
                written = _fetch_one(
                    cursor,
                    f"""
                    UPDATE apiome.slate_security_rules
                       SET {assignments},
                           conditions = %s::jsonb,
                           revision = revision + 1,
                           updated_at = CURRENT_TIMESTAMP
                     WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                    RETURNING *
                    """,
                    (*payload, encoded_conditions, rule_id, environment_id, tenant_id),
                )
                if written is None:
                    raise SlateSecurityStoreError(
                        "rule_not_found", f"Security rule {rule_id} was not found on this lane."
                    )
            else:
                placeholders = ", ".join(["%s"] * len(_RULE_COLUMNS))
                written = _fetch_one(
                    cursor,
                    f"""
                    INSERT INTO apiome.slate_security_rules
                        (tenant_id, environment_id, {", ".join(_RULE_COLUMNS)}, conditions,
                         created_by_actor_id, created_by_actor_name, created_by_actor_kind)
                    VALUES (%s::uuid, %s::uuid, {placeholders}, %s::jsonb, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        tenant_id,
                        environment_id,
                        *payload,
                        encoded_conditions,
                        actor_id,
                        actor_name,
                        actor_kind,
                    ),
                )
                if written is None:
                    raise SlateSecurityStoreError(
                        "rule_not_found", "The security rule could not be created."
                    )
                _append_revision(
                    cursor,
                    tenant_id=tenant_id,
                    environment_id=environment_id,
                    rule_id=str(written["id"]),
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
    rule_id: str,
    rollout_mode: str,
    rollout_percent: int,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Advance or retreat a rule's staged rollout, recording the stage it left.

    Reaching ``enforce`` at 100% is a sequence of audited writes rather than one checkbox, and
    every stage leaves a revision behind — which is what lets an operator answer "what was this
    rule doing an hour ago" without inferring it from a sentence.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: The rule.
        rollout_mode: ``simulate`` or ``enforce``.
        rollout_percent: 0 to 100.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The updated rule row.

    Raises:
        SlateSecurityPolicyConflictError: On a stale ``expected_policy_version``.
        SlateSecurityStoreError: When ``rule_id`` names no rule on this lane.
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
                  FROM apiome.slate_security_rules
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (rule_id, environment_id, tenant_id),
            )
            if prior is None:
                raise SlateSecurityStoreError(
                    "rule_not_found", f"Security rule {rule_id} was not found on this lane."
                )
            _append_revision(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                rule_id=rule_id,
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
                UPDATE apiome.slate_security_rules
                   SET rollout_mode = %s,
                       rollout_percent = %s,
                       revision = revision + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING *
                """,
                (rollout_mode, rollout_percent, rule_id, environment_id, tenant_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def delete_rule(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    rule_id: str,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> bool:
    """Remove a custom rule, keeping its body.

    The revision is written first and deliberately outlives the row: V188 gives
    ``slate_security_rule_revisions.rule_id`` no foreign key precisely because a deleted rule is
    the case where "revert my change" is most needed.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: Rule to remove.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        True when a rule was removed.

    Raises:
        SlateSecurityPolicyConflictError: On a stale ``expected_policy_version``.
        SlateSecurityStoreError: When ``rule_id`` names no rule on this lane.
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
                  FROM apiome.slate_security_rules
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (rule_id, environment_id, tenant_id),
            )
            if prior is None:
                raise SlateSecurityStoreError(
                    "rule_not_found", f"Security rule {rule_id} was not found on this lane."
                )
            _append_revision(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                rule_id=rule_id,
                revision=int(prior.get("revision") or 1),
                body=prior,
                body_digest=str(prior.get("body_digest") or ""),
                change_kind="deleted",
                actor_id=actor_id,
                actor_name=actor_name,
            )
            cursor.execute(
                """
                DELETE FROM apiome.slate_security_rules
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (rule_id, environment_id, tenant_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return True


def list_revisions(
    db: _DbLike, *, tenant_id: str, rule_id: str, limit: int = 50
) -> List[Dict[str, Any]]:
    """Load a rule's revision history, newest first.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        rule_id: The rule.
        limit: How many revisions to return.

    Returns:
        Revision rows, newest first. Scoped by tenant rather than by environment so a deleted
        rule's history is still readable, which is the case a revert cares about most.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_security_rule_revisions
             WHERE rule_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY revision DESC
             LIMIT %s
            """,
            (rule_id, tenant_id, limit),
        )


def last_simulated_at(db: _DbLike, *, tenant_id: str, rule_id: str) -> Optional[datetime]:
    """When this rule last stood in simulate mode.

    :func:`app.slate_security.evaluate_security_safety` refuses ``enforce-without-simulation``
    when this is absent, and it is a fact about history rather than about the body being written —
    so it is reconstructed here from the revision trail rather than taken from the request, where
    a client could simply assert it.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        rule_id: The rule.

    Returns:
        The timestamp of the most recent revision whose body was in simulate mode, or None when
        the rule has never run in simulate.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        row = _fetch_one(
            cursor,
            """
            SELECT at
              FROM apiome.slate_security_rule_revisions
             WHERE rule_id = %s::uuid
               AND tenant_id = %s::uuid
               AND body ->> 'rollout_mode' = 'simulate'
             ORDER BY at DESC
             LIMIT 1
            """,
            (rule_id, tenant_id),
        )
    return None if row is None else row.get("at")


def rule_evaluation_context(
    db: _DbLike, *, tenant_id: str, environment_id: str, rule_id: Optional[str]
) -> Dict[str, Any]:
    """Reconstruct the two facts about a rule's *history* that its body cannot state.

    :func:`app.slate_security.normalize_rule` reads ``simulated_at`` and
    ``previous_rollout_percent``, and neither is a column in V188. That is deliberate on both
    sides. They are not properties of the body being written — they are properties of what this
    rule has already done — so a body cannot carry them honestly, and the pure module is
    query-free by design and cannot go and look. The derivation therefore belongs here, in the one
    layer that can read the revision trail, and it must not be delegated to the request: a client
    that could assert ``simulated_at`` could promote a rule straight to enforcing, which is the
    lockout the ``enforce-without-simulation`` refusal exists to prevent.

    ``simulated_at`` comes from the revision trail, because "has this rule ever stood in simulate"
    is a question only history answers — a rule currently in enforce has no field saying it once
    was not. ``previous_rollout_percent`` comes from the live row, because the stage a rule is
    *leaving* is the stage it is in right now; the newest revision records the state before the
    previous edit and would be one change stale. When the rule row is gone — a revert after a
    delete — the newest revision is the best remaining answer and is used instead.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: The rule, or None when the body being evaluated is a create. A rule that does not
            exist yet has no history, and both facts are correctly absent — which is why a create
            that asks to enforce immediately is refused.

    Returns:
        ``{"simulated_at": ..., "previous_rollout_percent": ...}``, either value None when the
        history does not support it.
    """
    if not rule_id:
        return {"simulated_at": None, "previous_rollout_percent": None}

    simulated_at = last_simulated_at(db, tenant_id=tenant_id, rule_id=rule_id)

    current = get_rule(
        db, tenant_id=tenant_id, environment_id=environment_id, rule_id=rule_id
    )
    if current is not None and current.get("rollout_percent") is not None:
        previous = int(current["rollout_percent"])
    else:
        newest = list_revisions(db, tenant_id=tenant_id, rule_id=rule_id, limit=1)
        body = dict(newest[0].get("body") or {}) if newest else {}
        previous = (
            None if body.get("rollout_percent") is None else int(body["rollout_percent"])
        )

    return {"simulated_at": simulated_at, "previous_rollout_percent": previous}


def revert_rule(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    rule_id: str,
    revision: int,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Restore a rule to a stored revision.

    Reverting applies the recorded document. The state being left is itself recorded first, as a
    ``reverted`` revision, so a revert of a revert reads correctly in history rather than looking
    like the original change happening twice.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_id: The rule.
        revision: Which stored revision to apply.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The restored rule row.

    Raises:
        SlateSecurityPolicyConflictError: On a stale ``expected_policy_version``.
        SlateSecurityStoreError: When the rule or the named revision does not exist.
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
                  FROM apiome.slate_security_rule_revisions
                 WHERE rule_id = %s::uuid AND tenant_id = %s::uuid AND revision = %s
                """,
                (rule_id, tenant_id, revision),
            )
            if target is None:
                raise SlateSecurityStoreError(
                    "revision_not_found",
                    f"Security rule {rule_id} has no revision {revision} to revert to.",
                )
            prior = _fetch_one(
                cursor,
                """
                SELECT *
                  FROM apiome.slate_security_rules
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                """,
                (rule_id, environment_id, tenant_id),
            )
            if prior is None:
                raise SlateSecurityStoreError(
                    "rule_not_found", f"Security rule {rule_id} was not found on this lane."
                )
            _append_revision(
                cursor,
                tenant_id=tenant_id,
                environment_id=environment_id,
                rule_id=rule_id,
                revision=int(prior.get("revision") or 1),
                body=prior,
                body_digest=str(prior.get("body_digest") or ""),
                change_kind="reverted",
                actor_id=actor_id,
                actor_name=actor_name,
            )

            body = dict(target.get("body") or {})
            assignments = ", ".join(f"{column} = %s" for column in _RULE_COLUMNS)
            written = _fetch_one(
                cursor,
                f"""
                UPDATE apiome.slate_security_rules
                   SET {assignments},
                       conditions = %s::jsonb,
                       revision = revision + 1,
                       updated_at = CURRENT_TIMESTAMP
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING *
                """,
                (
                    *[body.get(column) for column in _RULE_COLUMNS],
                    json.dumps(_json(list(body.get("conditions") or []))),
                    rule_id,
                    environment_id,
                    tenant_id,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


# ─── Exceptions ──────────────────────────────────────────────────────────────


def list_exceptions(db: _DbLike, *, tenant_id: str, environment_id: str) -> List[Dict[str, Any]]:
    """Load a lane's carve-outs, soonest to expire first.

    Expired exceptions are returned rather than filtered out. A hole that has just lapsed is
    exactly what an operator investigating a newly-blocked request needs to see.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.

    Returns:
        Exception rows.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_all(
            cursor,
            """
            SELECT *
              FROM apiome.slate_security_exceptions
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY expires_at
            """,
            (environment_id, tenant_id),
        )


def create_exception(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    subject_kind: str,
    subject_ref: str,
    matcher_kind: str,
    matcher_value: str,
    expires_at: datetime,
    reason: str,
    expected_policy_version: int,
    actor_id: Optional[str],
    actor_name: str,
) -> Dict[str, Any]:
    """Open a scoped, expiring carve-out.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        subject_kind: ``managed-group``, ``rule`` or ``policy``.
        subject_ref: The group catalog id or rule id, ignored for policy-wide carve-outs.
        matcher_kind: How ``matcher_value`` is interpreted.
        matcher_value: The route pattern the exception covers.
        expires_at: When it lapses. NOT NULL in V188 and refused with a sentence before that.
        reason: Why it exists.
        expected_policy_version: The version the caller read.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.

    Returns:
        The written exception row.

    Raises:
        SlateSecurityPolicyConflictError: On a stale ``expected_policy_version``.
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
                INSERT INTO apiome.slate_security_exceptions
                    (tenant_id, environment_id, subject_kind, subject_ref, matcher_kind,
                     matcher_value, expires_at, reason, actor_id, actor_name)
                VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    subject_kind,
                    subject_ref,
                    matcher_kind,
                    matcher_value,
                    expires_at,
                    reason,
                    actor_id,
                    actor_name,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def delete_exception(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    exception_id: str,
    expected_policy_version: int,
) -> bool:
    """Close a carve-out early.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        exception_id: The carve-out.
        expected_policy_version: The version the caller read.

    Returns:
        True when an exception was removed.

    Raises:
        SlateSecurityPolicyConflictError: On a stale ``expected_policy_version``.
        SlateSecurityStoreError: When the exception is not on this lane.
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
                DELETE FROM apiome.slate_security_exceptions
                 WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
                RETURNING id
                """,
                (exception_id, environment_id, tenant_id),
            )
            if removed is None:
                raise SlateSecurityStoreError(
                    "exception_not_found",
                    f"Security exception {exception_id} was not found on this lane.",
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
        subject_id: Restrict to one subject. Used when checking an edit to an existing rule, so
            an approval of the *previous* body is found and reported as ``approval-stale`` rather
            than as no approval at all — the two need different actions.
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
              FROM apiome.slate_security_approvals
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

    The distinctness of author and approver is checked in :mod:`app.slate_security` so the
    operator meets a sentence, and again by V188's
    ``CHECK (approver_actor_key <> author_actor_key)`` so no code path can bypass it. Both are
    deliberate: the first is the explanation, the second is the guarantee.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        subject_kind: ``rule``, ``exception``, ``policy`` or ``managed-group``.
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
                INSERT INTO apiome.slate_security_approvals
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


# ─── Events ──────────────────────────────────────────────────────────────────


def record_event(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    rule_kind: str,
    rule_ref: str,
    rule_label: str,
    route: str,
    method: str,
    release_id: Optional[str],
    region: Optional[str],
    action: str,
    evidence: Mapping[str, Any],
    retain_until: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Persist one security event.

    ``source``, ``mitigated`` and ``edge_attached`` are literals in the statement below rather
    than parameters. There is no delivery tier, so there is nothing that observed this request and
    nothing that stopped it — and rather than trusting every caller to pass the honest value,
    this function offers no way to pass a dishonest one. V188 CHECKs the same three facts, so a
    future caller that reaches the table by another route still cannot claim a mitigation.

    ``evidence`` is passed through :func:`redact_evidence` here, not by the caller. A redaction the
    caller could skip is a redaction that will eventually be skipped.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        rule_kind: ``managed-group``, ``rule``, ``bot-preset`` or ``rate-preset``.
        rule_ref: Catalog id or rule id of whatever decided.
        rule_label: Its label as it read at the time, so a rename does not rewrite history.
        route: The request path.
        method: The request method.
        release_id: Release active at the time, when there is one.
        region: Region that handled the request, when known.
        action: What the policy decided.
        evidence: Raw request data; redacted here.
        retain_until: When the evidence must be purged. Defaults to 30 days after the event,
            because V188 forbids NULL and indefinite retention of request data is a liability
            rather than a feature.

    Returns:
        The written event row.
    """
    at = _now()
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            written = _fetch_one(
                cursor,
                """
                INSERT INTO apiome.slate_security_events
                    (tenant_id, environment_id, at, source, rule_kind, rule_ref, rule_label,
                     route, method, release_id, region, action, mitigated, edge_attached,
                     evidence, retain_until)
                VALUES (%s::uuid, %s::uuid, %s, 'policy-simulation', %s, %s, %s, %s, %s, %s, %s,
                        %s, FALSE, FALSE, %s::jsonb, %s)
                RETURNING *
                """,
                (
                    tenant_id,
                    environment_id,
                    at,
                    rule_kind,
                    rule_ref,
                    rule_label,
                    route,
                    method,
                    release_id,
                    region,
                    action,
                    json.dumps(redact_evidence(evidence)),
                    retain_until or (at + timedelta(days=_DEFAULT_RETENTION_DAYS)),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return written or {}


def list_events(
    db: _DbLike,
    *,
    tenant_id: str,
    environment_id: str,
    limit: int = 50,
    rule_ref: Optional[str] = None,
    action: Optional[str] = None,
    route: Optional[str] = None,
    release_id: Optional[str] = None,
    region: Optional[str] = None,
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Load a lane's security events, most recent first.

    The filter names are the designer's dimension ids, unchanged. Two vocabularies for the same
    axis would mean an operator filtering by ``rule`` on screen and by ``ruleRef`` in an export
    and quietly getting different answers.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        limit: How many events to return.
        rule_ref: Restrict to one rule or managed group.
        action: Restrict to one decision.
        route: Restrict to one request path.
        release_id: Restrict to the events during one release.
        region: Restrict to one region.
        source: Restrict to ``policy-simulation`` or ``edge-observed``.

    Returns:
        Event rows, most recent first.
    """
    clauses = ["environment_id = %s::uuid", "tenant_id = %s::uuid"]
    params: List[Any] = [environment_id, tenant_id]
    for column, value, cast in (
        ("rule_ref", rule_ref, ""),
        ("action", action, ""),
        ("route", route, ""),
        ("release_id", release_id, "::uuid"),
        ("region", region, ""),
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
              FROM apiome.slate_security_events
             WHERE {" AND ".join(clauses)}
             ORDER BY at DESC
             LIMIT %s
            """,
            tuple(params),
        )


def get_event(
    db: _DbLike, *, tenant_id: str, environment_id: str, event_id: str
) -> Optional[Dict[str, Any]]:
    """Load one security event.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        event_id: The event.

    Returns:
        The event row, or None when it is not on this lane.
    """
    conn = db.connect()
    with conn.cursor() as cursor:
        return _fetch_one(
            cursor,
            """
            SELECT *
              FROM apiome.slate_security_events
             WHERE id = %s::uuid AND environment_id = %s::uuid AND tenant_id = %s::uuid
            """,
            (event_id, environment_id, tenant_id),
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
    """Append a security audit entry.

    Used for every policy change, approval, revert and refusal — and for evidence exports, because
    who read the record of who disabled the WAF is itself part of that record. A *refused* action
    must leave a trace even though nothing changed: refusing to weaken protection during an
    incident is exactly the event the review afterwards asks about.

    Args:
        db: Database handle exposing ``connect()``.
        tenant_id: Owning tenant.
        environment_id: The lane.
        actor_id: Acting user, when a person acted.
        actor_name: Display name of the actor.
        actor_kind: ``user`` or ``automation``.
        subject_kind: One of V188's eight subjects, ``export`` included.
        subject_id: Id of the subject row, when there is one.
        summary: What happened.
        detail: Extra context, e.g. the refusal reason and its sentence.
    """
    conn = db.connect()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO apiome.slate_security_audit
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
    """Load a lane's security audit trail, most recent first.

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
              FROM apiome.slate_security_audit
             WHERE environment_id = %s::uuid AND tenant_id = %s::uuid
             ORDER BY at DESC
             LIMIT %s
            """,
            (environment_id, tenant_id, limit),
        )
