"""Short-lived caches for authentication and permission resolution (DBP-1.3, #7186).

Every authenticated request used to repeat the same tenant, membership, administrator and role
lookups (5–8 statements), and every API-key request ran a bcrypt verification. This module keeps
what those lookups found for a short time, in two layers:

* **Per request** — a :class:`RequestMemo` lives for one HTTP request (started and ended by the
  observability middleware). The authentication dependency and every permission check of the same
  request share it, so a request resolves a (user, tenant) pair at most once even with the process
  cache turned off.
* **Per process** — a :class:`TtlCache` keyed by (user, tenant) holds the
  :class:`AuthorizationContext` for ``AUTH_CACHE_TTL_SECONDS`` (default 30 s), and a second one
  keyed by ``sha256(presented API key)`` holds the verified key for ``API_KEY_CACHE_TTL_SECONDS``
  (default 60 s). ``0`` turns either off.

Changes made through this process (role, membership, administrator and tenant writes, API key
revocation) call the ``invalidate_*`` functions, so they take effect on the next request here.
Changes made elsewhere (the web app, another REST instance) take effect once the entry expires.
A cached API key is still re-checked against its row on every request (see
``Database.validate_api_key``), so a revoked, disabled, expired or regenerated key is refused on
its next request wherever it was revoked.
"""

from __future__ import annotations

import contextvars
import hashlib
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, FrozenSet, Hashable, Optional, Tuple

from .config import settings


# ─────────────────────────────── the cached values ───────────────────────────────


@dataclass(frozen=True)
class AuthorizationContext:
    """What one statement learns about a user in a tenant.

    Attributes:
        tenant_id: The tenant's id (text UUID).
        tenant_slug: The tenant's slug.
        tenant_name: The tenant's display name.
        tenant_active: False when the tenant is soft-deleted (only a lookup by id can see one).
        user_id: The user the context was resolved for (canonical UUID text).
        is_admin: The user is a tenant administrator (passes every permission check).
        is_active_member: The user has a ``tenant_users`` row that is not suspended.
        permissions: The ``resource:action`` keys the user's role grants — their assigned roles,
            or the built-in Editor grid for an active member with no role. Administrators are
            handled by ``is_admin`` and do not need entries here.
    """

    tenant_id: str
    tenant_slug: str
    tenant_name: Optional[str]
    tenant_active: bool
    user_id: str
    is_admin: bool
    is_active_member: bool
    permissions: FrozenSet[str] = field(default_factory=frozenset)

    @property
    def has_tenant_access(self) -> bool:
        """True when the user may call the tenant's routes: an active member or an administrator."""
        return self.tenant_active and (self.is_active_member or self.is_admin)

    def allows(self, resource: str, action: str) -> bool:
        """True when the user holds ``resource:action`` (administrators hold everything).

        Args:
            resource: A permission resource (``app.permissions.Resource``).
            action: A permission action (``app.permissions.Action``).
        """
        return self.is_admin or f"{resource}:{action}" in self.permissions

    def tenant_row(self) -> Dict[str, Any]:
        """The tenant dict authentication returns (same keys as ``get_active_tenant_auth_row``)."""
        return {
            "tenant_id": self.tenant_id,
            "tenant_slug": self.tenant_slug,
            "tenant_name": self.tenant_name,
        }


@dataclass
class ApiKeyCacheEntry:
    """A presented API key whose bcrypt hash has already been verified.

    Attributes:
        key_id: The ``api_keys.id`` the secret verified against.
        key_hash: The stored hash it verified against. The per-request check requires the row to
            still carry it, so regenerating the key (new hash) refuses the old secret.
        tenant_id: The owning tenant, for tenant-wide invalidation.
        stamped_at: ``time.monotonic()`` when ``last_used_at`` was last written for this key by
            this process; the write is skipped while that is under a minute old.
        variant: Which schema generation's columns the key was read with (``workspace_kind`` on
            a current database), so the re-read selects the same columns.
    """

    key_id: str
    key_hash: Any
    tenant_id: Optional[str]
    stamped_at: float
    variant: str = "workspace_kind"


#: How often (seconds) a cached API key's ``last_used_at`` is written — the same once-a-minute
#: throttle the uncached path's ``UPDATE`` predicate applies.
API_KEY_STAMP_INTERVAL_SECONDS = 60.0


# ─────────────────────────────── the process cache ───────────────────────────────


class TtlCache:
    """A small thread-safe map whose entries expire after a configurable number of seconds.

    The TTL is read on every call (from ``ttl_seconds()``), so changing the setting — or a test
    patching it — takes effect at once. A TTL of ``0`` or less disables the cache: reads miss and
    writes are dropped. When full, expired entries are dropped first and then the oldest ones.
    """

    def __init__(
        self,
        ttl_seconds: Callable[[], float],
        max_entries: Callable[[], int],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create an empty cache.

        Args:
            ttl_seconds: Returns the current TTL in seconds.
            max_entries: Returns the most entries to keep (``0`` or less = unbounded).
            clock: Monotonic clock, injectable for tests.
        """
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: Dict[Hashable, Tuple[float, Any]] = {}

    @property
    def enabled(self) -> bool:
        """True when the TTL is positive."""
        return float(self._ttl() or 0) > 0

    def get(self, key: Hashable) -> Any:
        """Return the live value stored under ``key``, or ``None`` (missing, expired or disabled)."""
        if not self.enabled:
            return None
        now = self._clock()
        with self._lock:
            hit = self._entries.get(key)
            if hit is None:
                return None
            expires_at, value = hit
            if expires_at <= now:
                self._entries.pop(key, None)
                return None
            return value

    def put(self, key: Hashable, value: Any) -> None:
        """Store ``value`` under ``key`` for one TTL (a no-op when the cache is disabled)."""
        ttl = float(self._ttl() or 0)
        if ttl <= 0:
            return
        now = self._clock()
        limit = int(self._max() or 0)
        with self._lock:
            self._entries.pop(key, None)
            if limit > 0 and len(self._entries) >= limit:
                self._evict(now, limit)
            self._entries[key] = (now + ttl, value)

    def _evict(self, now: float, limit: int) -> None:
        """Make room for one entry: drop expired entries, then the oldest. Caller holds the lock."""
        for k in [k for k, (exp, _) in self._entries.items() if exp <= now]:
            del self._entries[k]
        while len(self._entries) >= limit:
            self._entries.pop(next(iter(self._entries)))

    def discard_where(self, predicate: Callable[[Hashable, Any], bool]) -> int:
        """Remove every entry for which ``predicate(key, value)`` is true.

        Returns:
            How many entries were removed.
        """
        with self._lock:
            doomed = [k for k, (_, v) in self._entries.items() if predicate(k, v)]
            for k in doomed:
                del self._entries[k]
            return len(doomed)

    def clear(self) -> None:
        """Remove every entry."""
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


_authz = TtlCache(
    ttl_seconds=lambda: settings.auth_cache_ttl_seconds,
    max_entries=lambda: settings.auth_cache_max_entries,
)
_api_keys = TtlCache(
    ttl_seconds=lambda: settings.api_key_cache_ttl_seconds,
    max_entries=lambda: settings.auth_cache_max_entries,
)


# ─────────────────────────────── the per-request memo ───────────────────────────────


class RequestMemo:
    """Authorization contexts resolved during one request.

    The middleware's context variable holds the object, and worker threads see the same object
    through their copied context, so a lookup made in the authentication dependency is reused by
    the handler's permission checks. :meth:`close` empties it when the response is done, so a task
    that outlives the request cannot keep reading what the request saw.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: Dict[Hashable, AuthorizationContext] = {}
        self._closed = False

    def get(self, key: Hashable) -> Optional[AuthorizationContext]:
        """The context stored under ``key`` during this request, or ``None``."""
        with self._lock:
            return None if self._closed else self._entries.get(key)

    def put(self, key: Hashable, value: AuthorizationContext) -> None:
        """Remember ``value`` for the rest of the request (ignored once closed)."""
        with self._lock:
            if not self._closed:
                self._entries[key] = value

    def discard_where(self, predicate: Callable[[AuthorizationContext], bool]) -> None:
        """Forget every context for which ``predicate`` is true."""
        with self._lock:
            for k in [k for k, v in self._entries.items() if predicate(v)]:
                del self._entries[k]

    def close(self) -> None:
        """Forget everything and stop remembering (the request is over)."""
        with self._lock:
            self._entries.clear()
            self._closed = True


_memo: contextvars.ContextVar[Optional[RequestMemo]] = contextvars.ContextVar(
    "apiome_authz_request_memo", default=None
)


def begin_request() -> Tuple[RequestMemo, contextvars.Token]:
    """Start the current request's memo.

    Returns:
        The memo (the middleware also exposes it as ``request.state.authz_memo``) and the token
        :func:`end_request` needs.
    """
    memo = RequestMemo()
    return memo, _memo.set(memo)


def end_request(memo: RequestMemo, token: contextvars.Token) -> None:
    """Close the memo :func:`begin_request` started and unset it.

    Args:
        memo: The memo :func:`begin_request` returned.
        token: The token :func:`begin_request` returned.
    """
    memo.close()
    try:
        _memo.reset(token)
    except ValueError:
        # Reset from another context; clearing is the same outcome for the next request.
        _memo.set(None)


def current_memo() -> Optional[RequestMemo]:
    """The current request's memo, or ``None`` outside a request."""
    return _memo.get()


# ─────────────────────────────── authorization contexts ───────────────────────────────


def slug_key(user_id: str, tenant_slug: str) -> Tuple[str, str, str]:
    """Cache key of a context looked up by tenant slug."""
    return (str(user_id), "slug", str(tenant_slug))


def id_key(user_id: str, tenant_id: str) -> Tuple[str, str, str]:
    """Cache key of a context looked up by tenant id."""
    return (str(user_id), "id", str(tenant_id).lower())


def resolve(
    key: Tuple[str, str, str],
    load: Callable[[], Optional[AuthorizationContext]],
) -> Optional[AuthorizationContext]:
    """Return the context for ``key`` from the request memo, the process cache or ``load()``.

    A loaded context is remembered under its id key and — when the tenant is active — its slug
    key, so the authentication dependency (by slug) and the permission guard (by id) share one
    lookup. ``None`` (no such tenant) is not remembered, so a new tenant is found at once.

    Args:
        key: :func:`slug_key` or :func:`id_key`.
        load: Runs the authorization statement.

    Returns:
        The context, or ``None`` when ``load`` found no tenant.
    """
    memo = current_memo()
    ctx = memo.get(key) if memo is not None else None
    if ctx is None:
        ctx = _authz.get(key)
        if ctx is None:
            ctx = load()
            if ctx is None:
                return None
            for k in _keys_of(ctx):
                _authz.put(k, ctx)
        if memo is not None:
            for k in _keys_of(ctx):
                memo.put(k, ctx)
    if key[1] == "slug" and not ctx.tenant_active:
        return None
    return ctx


def _keys_of(ctx: AuthorizationContext) -> Tuple[Tuple[str, str, str], ...]:
    """Every key ``ctx`` is reachable under."""
    keys = (id_key(ctx.user_id, ctx.tenant_id),)
    if ctx.tenant_active:
        keys += (slug_key(ctx.user_id, ctx.tenant_slug),)
    return keys


def _drop_contexts(predicate: Callable[[AuthorizationContext], bool]) -> None:
    """Forget every context matching ``predicate`` in the process cache and the request memo."""
    _authz.discard_where(lambda _k, v: predicate(v))
    memo = current_memo()
    if memo is not None:
        memo.discard_where(predicate)


def invalidate_member(tenant_id: Optional[str], user_id: Optional[str]) -> None:
    """Forget what is known about one user in one tenant (membership, administrator or role change).

    Args:
        tenant_id: The tenant; ``None`` forgets the user in every tenant.
        user_id: The user; ``None`` forgets every user of the tenant.
    """
    tid = str(tenant_id).lower() if tenant_id else None
    uid = str(user_id).lower() if user_id else None
    _drop_contexts(
        lambda c: (tid is None or c.tenant_id.lower() == tid) and (uid is None or c.user_id.lower() == uid)
    )


def invalidate_tenant(tenant_id: Optional[str]) -> None:
    """Forget every user's context in a tenant (a role grid, tenant or slug change).

    Also forgets the tenant's cached API keys, since a disabled or deleted tenant refuses them.

    Args:
        tenant_id: The tenant; ``None`` forgets every tenant.
    """
    invalidate_member(tenant_id, None)
    invalidate_api_keys(tenant_id=tenant_id)


def invalidate_all() -> None:
    """Forget every cached context and API key (tests; an operator-wide change)."""
    _authz.clear()
    _api_keys.clear()
    memo = current_memo()
    if memo is not None:
        memo.discard_where(lambda _c: True)


# ─────────────────────────────── API keys ───────────────────────────────


def api_key_digest(api_key: str) -> str:
    """The cache key of a presented API key: its SHA-256, so the secret itself is never stored."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def get_api_key(api_key: str) -> Optional[ApiKeyCacheEntry]:
    """The cached verification of ``api_key``, or ``None`` (not seen, expired or cache disabled)."""
    return _api_keys.get(api_key_digest(api_key))


def remember_api_key(api_key: str, entry: ApiKeyCacheEntry) -> None:
    """Remember that ``api_key`` verified against ``entry.key_id`` (for one TTL)."""
    _api_keys.put(api_key_digest(api_key), entry)


def forget_api_key(api_key: str) -> None:
    """Forget one presented key (its row no longer accepts it)."""
    digest = api_key_digest(api_key)
    _api_keys.discard_where(lambda k, _v: k == digest)


def invalidate_api_keys(*, key_id: Optional[str] = None, tenant_id: Optional[str] = None) -> None:
    """Forget cached API keys by key id, by tenant, or all of them (both ``None``).

    Args:
        key_id: The ``api_keys.id`` revoked or regenerated.
        tenant_id: Every key of this tenant.
    """
    kid = str(key_id).lower() if key_id else None
    tid = str(tenant_id).lower() if tenant_id else None
    _api_keys.discard_where(
        lambda _k, e: (kid is None or str(e.key_id).lower() == kid)
        and (tid is None or str(e.tenant_id or "").lower() == tid)
    )
