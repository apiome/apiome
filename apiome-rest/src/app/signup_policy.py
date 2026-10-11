"""Installation sign-up policy — who may create an account (SGN-1.4, #5653).

One policy decides whether a new person may create an account, for **every** sign-up path: the
email form and each OAuth provider. It replaces the single ``AUTH_SIGNUP_DISABLED`` env flag with a
database-stored setting a super-admin changes from the admin console, keeping the env flag as the
fallback (the OLO-8 DB-first pattern):

* **No stored policy** ⇒ env governs, exactly as before: ``AUTH_SIGNUP_DISABLED=true|1`` reads as
  ``closed``, anything else as ``open``.
* **Stored policy** (``apiome.signup_policy``, V274) ⇒ its ``mode`` and
  ``allowed_email_domains`` win over env.

Modes:

* ``open`` — anyone may create an account; when ``allowed_email_domains`` is non-empty, only an
  address at one of those domains may.
* ``invite_only`` — no self-service account creation. Tenant invitations go to people who already
  hold an account, so they sign in (and activate their pending membership) as usual; a person with
  no account is refused with ``signup-invite-only``.
* ``closed`` — no self-service account creation at all (``signup-disabled``).

The policy only ever gates **creating** an account. It never stops an existing user signing in.

This module is the Python mirror of ``apiome-ui/lib/auth/signup-policy.ts`` (pure policy) and
``apiome-ui/lib/auth/signup-policy-resolver.ts`` (cached read). Any behavioural change here MUST be
made there as well; both sides run the same table-driven matrix.

The pure half (:class:`SignupPolicy`, :func:`signup_rejection_code`, the normalizers) does no I/O.
:func:`get_effective_signup_policy` is the cached read every enforcement point shares.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# --- Modes ---

#: Anyone may create an account (subject to ``allowed_email_domains``).
MODE_OPEN = "open"
#: No self-service account creation; existing accounts (incl. invited members) sign in.
MODE_INVITE_ONLY = "invite_only"
#: No self-service account creation at all.
MODE_CLOSED = "closed"

#: Every mode, in the order the admin console lists them.
SIGNUP_MODES: Tuple[str, ...] = (MODE_OPEN, MODE_INVITE_ONLY, MODE_CLOSED)

# --- Where the effective policy came from ---

#: The policy is stored in ``apiome.signup_policy``.
SOURCE_DB = "db"
#: No policy is stored; ``AUTH_SIGNUP_DISABLED`` governs.
SOURCE_ENV = "env"

# --- Stable rejection codes (part of the auth error contract, OLO-1.5) ---
# Re-exported by :mod:`app.account_resolution` (``AUTH_ERROR_CODES``) and mirrored in
# ``apiome-ui/lib/auth/account-resolution.ts``. Never change or reuse a value.

#: Self-signup is disabled on this deployment (mode ``closed``).
SIGNUP_DISABLED = "signup-disabled"
#: Sign-up is by invitation only and this address has no account (mode ``invite_only``).
SIGNUP_INVITE_ONLY = "signup-invite-only"
#: Sign-up is open, but not to this address's email domain.
SIGNUP_DOMAIN_NOT_ALLOWED = "signup-domain-not-allowed"

#: Upper bound on the allowed-domain list (matches the V274 CHECK).
MAX_ALLOWED_EMAIL_DOMAINS = 200

#: A bare DNS domain: dot-separated labels of letters/digits/hyphens, no leading/trailing hyphen,
#: at least two labels, at most 253 characters overall.
_DOMAIN_SHAPE = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


@dataclass(frozen=True)
class SignupPolicy:
    """The installation's effective sign-up policy.

    Attributes:
        mode: One of :data:`SIGNUP_MODES`.
        allowed_email_domains: Lower-case email domains allowed to sign up while ``mode`` is
            ``open``; empty means any domain. Ignored by the other modes.
        source: :data:`SOURCE_DB` when the policy is stored, :data:`SOURCE_ENV` when it is the
            env fallback.
    """

    mode: str = MODE_OPEN
    allowed_email_domains: Tuple[str, ...] = ()
    source: str = SOURCE_ENV


def normalize_email_domain(raw: Any) -> str:
    """Normalize one allowed-domain entry to a lower-case bare domain.

    Accepts the forms an operator is likely to type — ``Example.com``, ``@example.com``,
    ``  example.com  `` — and reduces them to ``example.com``. Matching is exact, so a subdomain
    must be listed in its own right.

    Args:
        raw: The entry as supplied.

    Returns:
        The normalized domain.

    Raises:
        ValueError: When the entry is not a string or is not a valid bare domain (an address, a
            URL, a wildcard, a single label, …).
    """
    if not isinstance(raw, str):
        raise ValueError("an email domain must be a string")
    domain = raw.strip().lower()
    if domain.startswith("@"):
        domain = domain[1:]
    if not _DOMAIN_SHAPE.match(domain):
        raise ValueError(f"{raw!r} is not a valid email domain (expected e.g. 'example.com')")
    return domain


def normalize_allowed_email_domains(raw: Optional[Iterable[Any]]) -> Tuple[str, ...]:
    """Normalize an allowed-domain list: each entry normalized, duplicates dropped, order kept.

    Args:
        raw: The entries as supplied, or None for "no restriction".

    Returns:
        The normalized domains, first occurrence first.

    Raises:
        ValueError: When any entry is invalid (see :func:`normalize_email_domain`) or the list
            exceeds :data:`MAX_ALLOWED_EMAIL_DOMAINS`.
    """
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)):
        raise ValueError("allowed email domains must be a list")
    seen = []
    for entry in raw:
        domain = normalize_email_domain(entry)
        if domain not in seen:
            seen.append(domain)
    if len(seen) > MAX_ALLOWED_EMAIL_DOMAINS:
        raise ValueError(f"at most {MAX_ALLOWED_EMAIL_DOMAINS} email domains may be listed")
    return tuple(seen)


def email_domain(email: Optional[str]) -> Optional[str]:
    """Return the lower-case domain of an email address, or None when it has none.

    Args:
        email: The address (canonical or not).

    Returns:
        The text after the last ``@``, trimmed and lower-cased; None for a missing or malformed
        address.
    """
    if not isinstance(email, str):
        return None
    local, at, domain = email.strip().lower().rpartition("@")
    if not at or not local or not domain:
        return None
    return domain


def is_signup_disabled_by_env(env: Optional[Mapping[str, Optional[str]]] = None) -> bool:
    """Whether the env fallback refuses self-signup (``AUTH_SIGNUP_DISABLED=true|1``).

    Args:
        env: Environment to read (injectable for tests; defaults to ``os.environ``).

    Returns:
        True when the flag is explicitly ``true`` or ``1`` (case-insensitive, trimmed).
    """
    source = os.environ if env is None else env
    raw = source.get("AUTH_SIGNUP_DISABLED")
    if not isinstance(raw, str):
        return False
    return raw.strip().lower() in ("true", "1")


def signup_policy_from_env(env: Optional[Mapping[str, Optional[str]]] = None) -> SignupPolicy:
    """The env-fallback policy: ``closed`` when ``AUTH_SIGNUP_DISABLED`` is set, else ``open``.

    Args:
        env: Environment to read (injectable for tests; defaults to ``os.environ``).

    Returns:
        A policy with :data:`SOURCE_ENV` and no domain restriction — the pre-SGN-1.4 behaviour.
    """
    mode = MODE_CLOSED if is_signup_disabled_by_env(env) else MODE_OPEN
    return SignupPolicy(mode=mode, allowed_email_domains=(), source=SOURCE_ENV)


def signup_policy_from_row(row: Optional[Mapping[str, Any]]) -> Optional[SignupPolicy]:
    """Build a policy from a stored ``apiome.signup_policy`` row.

    Args:
        row: The stored row, or None when no policy is stored.

    Returns:
        The stored policy with :data:`SOURCE_DB`, or None when there is no usable row — the
        caller then falls back to env. A row whose mode is unrecognized is treated as unusable
        rather than guessed at.
    """
    if not row:
        return None
    mode = row.get("mode")
    if mode not in SIGNUP_MODES:
        return None
    domains = []
    for entry in row.get("allowed_email_domains") or ():
        try:
            domain = normalize_email_domain(entry)
        except ValueError:
            # A malformed stored entry can never match an address; drop it rather than fail.
            continue
        if domain not in domains:
            domains.append(domain)
    return SignupPolicy(mode=mode, allowed_email_domains=tuple(domains), source=SOURCE_DB)


def signup_rejection_code(policy: SignupPolicy, email: Optional[str]) -> Optional[str]:
    """Decide whether the policy refuses creating an account for this address (pure — no I/O).

    The single gate every sign-up path shares, so email and each OAuth provider can never be
    treated differently.

    Args:
        policy: The effective policy.
        email: The address the account would be created with.

    Returns:
        None when the account may be created; otherwise the stable rejection code —
        :data:`SIGNUP_DISABLED` (``closed``), :data:`SIGNUP_INVITE_ONLY` (``invite_only``), or
        :data:`SIGNUP_DOMAIN_NOT_ALLOWED` (``open`` with a domain list the address is not on).
        An unrecognized mode fails closed.
    """
    if policy.mode == MODE_INVITE_ONLY:
        return SIGNUP_INVITE_ONLY
    if policy.mode != MODE_OPEN:
        return SIGNUP_DISABLED
    if policy.allowed_email_domains:
        domain = email_domain(email)
        if domain is None or domain not in policy.allowed_email_domains:
            return SIGNUP_DOMAIN_NOT_ALLOWED
    return None


# ---------------------------------------------------------------------------
# Cached read of the effective policy
# ---------------------------------------------------------------------------

#: Default cache lifetime in seconds: a policy change made on another instance lands within this.
DEFAULT_CACHE_TTL_SECONDS = 30.0
#: Bounds on the configurable lifetime, so it is neither a per-request read nor unboundedly stale.
MIN_CACHE_TTL_SECONDS = 1.0
MAX_CACHE_TTL_SECONDS = 300.0

_cache_lock = threading.Lock()
_cached_policy: Optional[SignupPolicy] = None
_cached_at: float = 0.0


def signup_policy_cache_ttl_seconds(env: Optional[Mapping[str, Optional[str]]] = None) -> float:
    """Resolve the cache lifetime from ``SIGNUP_POLICY_CACHE_TTL_SECONDS``.

    Args:
        env: Environment to read (injectable for tests; defaults to ``os.environ``).

    Returns:
        The configured lifetime clamped to the allowed bounds, or the default when unset or not a
        number.
    """
    source = os.environ if env is None else env
    raw = source.get("SIGNUP_POLICY_CACHE_TTL_SECONDS")
    try:
        value = float(raw) if raw is not None and str(raw).strip() else DEFAULT_CACHE_TTL_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_CACHE_TTL_SECONDS
    if value != value:  # NaN
        return DEFAULT_CACHE_TTL_SECONDS
    return min(MAX_CACHE_TTL_SECONDS, max(MIN_CACHE_TTL_SECONDS, value))


def invalidate_signup_policy_cache() -> None:
    """Drop the cached policy so the next read goes to the database.

    Called after a successful write so the instance that served the change applies it at once
    instead of after the cache lifetime.
    """
    global _cached_policy, _cached_at
    with _cache_lock:
        _cached_policy = None
        _cached_at = 0.0


def _read_stored_row() -> Optional[Mapping[str, Any]]:
    """Read the stored policy row through the shared ``db`` singleton (lazy import)."""
    from .database import db

    return db.get_signup_policy()


def get_effective_signup_policy(
    *,
    read_row: Optional[Callable[[], Optional[Mapping[str, Any]]]] = None,
    env: Optional[Mapping[str, Optional[str]]] = None,
    now: Optional[Callable[[], float]] = None,
) -> SignupPolicy:
    """Return the effective sign-up policy: the stored one, else the env fallback (cached).

    The result is cached in-process for :func:`signup_policy_cache_ttl_seconds`, so a change takes
    effect without a restart — at once on the instance that wrote it (the write invalidates the
    cache), and within the cache lifetime everywhere else.

    Failure handling: when the database cannot be read, the last policy this process read is
    served if there is one; otherwise sign-up **fails closed** (``closed``) rather than falling
    back to a possibly more permissive env value. The failure is not cached, so the next call
    retries.

    Args:
        read_row: Reads the stored row (injectable for tests; defaults to the ``db`` singleton).
        env: Environment for the fallback and the cache lifetime (defaults to ``os.environ``).
        now: Monotonic clock (injectable for tests).

    Returns:
        The effective policy.
    """
    global _cached_policy, _cached_at
    clock = now or time.monotonic
    ttl = signup_policy_cache_ttl_seconds(env)

    with _cache_lock:
        if _cached_policy is not None and clock() - _cached_at < ttl:
            return _cached_policy
        stale = _cached_policy

    try:
        row = (read_row or _read_stored_row)()
    except Exception as exc:  # noqa: BLE001 — any read fault degrades the same way
        logger.warning("sign-up policy: could not read the stored policy: %s", exc)
        if stale is not None:
            return stale
        return SignupPolicy(mode=MODE_CLOSED, allowed_email_domains=(), source=SOURCE_DB)

    policy = signup_policy_from_row(row) or signup_policy_from_env(env)
    with _cache_lock:
        _cached_policy = policy
        _cached_at = clock()
    return policy
