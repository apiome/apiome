"""Reader enrolment, magic-link exchange and reader sessions — PCX-1.1 (#5889).

The behaviour lives in four functions — :func:`request_magic_link`, :func:`exchange_token`,
:func:`resolve_session` and :func:`revoke_session` — that talk to storage only through a
:class:`PortalAuthRepository`. :class:`SqlPortalAuthRepository` is the real one (apiome-db V378);
the unit tests pass an in-memory fake, so every rule below is tested without a database.

The rules:

* **One person, one user, one membership.** A magic-link request for an address that has no
  ``users`` row creates exactly one (when the installation sign-up policy allows it — the existing
  :func:`app.signup_policy.signup_rejection_code`, until PCX-1.2 adds a portal policy), plus exactly
  one ``invited`` membership for the tenant. A second request for the same address reuses both.
  An existing account is never refused by the policy, which only gates *creating* accounts.
* **A reader sign-in never verifies someone else's password.** The exchange marks the user verified
  only when the account has no usable password. An unverified account that holds one (a workspace
  sign-up nobody confirmed) stays unverified, so a stranger who signed up with the address cannot
  have it unlocked by its real owner clicking a reader link.
* **The answer never tells.** The route answers ``202`` whether or not a link was sent, so the
  endpoint cannot be used to learn who has an account or a membership. Refusals are logged by
  reason only — never with the address.
* **A token is burned once.** The exchange verifies the bcrypt hash, refuses an expired or used
  token with its own code, then burns it with a conditional ``UPDATE`` so two concurrent exchanges
  of one token cannot both win.
* **Revocation applies on the next request.** Every :func:`resolve_session` reads the session and
  its membership; a revoked session, a revoked membership, a disabled user or a passed expiry is
  refused at once. Nothing is cached.
* **Audit is metadata only.** ``portal.reader.enrolled`` (first activation),
  ``portal.reader.signed_in`` and ``portal.reader.session_revoked`` rows go to the access audit with
  the reader's address as the target and no token anywhere. An audit failure never fails sign-in.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Mapping, Optional, Protocol

from .portal_auth import (
    AUDIT_ENROLLED,
    AUDIT_SESSION_REVOKED,
    AUDIT_SIGNED_IN,
    CODE_SESSION_INVALID,
    CODE_TOKEN_EXPIRED,
    CODE_TOKEN_INVALID,
    CODE_TOKEN_USED,
    MAGIC_LINK_TTL_MINUTES,
    MEMBERSHIP_ACTIVE,
    MEMBERSHIP_REVOKED,
    SOURCE_MAGIC_LINK,
    PortalAuthError,
    ReaderProfile,
    ReaderSessionGrant,
    hash_session_token,
    mint_magic_link_token,
    mint_session_token,
    normalize_email,
    safe_return_to,
    split_magic_link_token,
    user_agent_family,
    verify_magic_link_token,
)
from .portal_mail import ReaderMailer, magic_link_url

_logger = logging.getLogger(__name__)

__all__ = [
    "PortalAuthRepository",
    "ReaderSession",
    "SqlPortalAuthRepository",
    "default_repository",
    "exchange_token",
    "request_magic_link",
    "resolve_session",
    "revoke_session",
]

#: The access-audit ``source`` for reader events.
AUDIT_SOURCE = "portal"

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    """The current instant, timezone-aware."""
    return datetime.now(timezone.utc)


class PortalAuthRepository(Protocol):
    """The storage the reader flows need. Rows are plain mappings."""

    def find_tenant(self, tenant_slug: str) -> Optional[Mapping[str, Any]]:
        """``{tenant_id, tenant_slug, tenant_name}`` of an active tenant, or ``None``."""
        ...

    def find_user_by_email(self, email: str) -> Optional[Mapping[str, Any]]:
        """``{id, email, name, enabled, deleted_at}`` for an address (case-insensitive), or ``None``."""
        ...

    def create_user(self, email: str, name: str) -> Mapping[str, Any]:
        """Create a password-less user and return it like :meth:`find_user_by_email`."""
        ...

    def find_membership(self, tenant_id: str, user_id: str) -> Optional[Mapping[str, Any]]:
        """``{id, tenant_id, user_id, status, activated_at}``, or ``None``."""
        ...

    def create_membership(self, tenant_id: str, user_id: str, source: str) -> Mapping[str, Any]:
        """Create an ``invited`` membership (or return the existing one) like :meth:`find_membership`."""
        ...

    def insert_magic_link(
        self,
        *,
        tenant_id: str,
        membership_id: str,
        lookup_prefix: str,
        token_hash: str,
        return_to: Optional[str],
        expires_at: datetime,
    ) -> None:
        """Store a magic link."""
        ...

    def find_magic_link(self, tenant_id: str, lookup_prefix: str) -> Optional[Mapping[str, Any]]:
        """``{id, membership_id, token_hash, return_to, expires_at, consumed_at}``, or ``None``."""
        ...

    def burn_magic_link(self, link_id: str, now: datetime) -> bool:
        """Set ``consumed_at`` if still unused and unexpired; True when this call burned it."""
        ...

    def activate_membership(self, membership_id: str, now: datetime) -> bool:
        """Move an ``invited`` membership to ``active``; True when this call activated it."""
        ...

    def mark_user_verified(self, user_id: str) -> None:
        """Record that the user proved they own their address — **only** for a password-less account.

        An unverified account with a password is left unverified: it may belong to someone who
        signed up with this address without owning it, and verifying it would hand them the
        account (pre-hijacking). The reader still gets their session; only the workspace flag is
        withheld.
        """
        ...

    def insert_session(
        self, *, membership_id: str, token_hash: str, expires_at: datetime, user_agent_family: str
    ) -> Mapping[str, Any]:
        """Store a session and return ``{id, expires_at}``."""
        ...

    def find_session(self, token_hash: str) -> Optional[Mapping[str, Any]]:
        """The session joined to its membership, user and tenant, or ``None``.

        Keys: ``session_id, expires_at, revoked_at, membership_id, membership_status, tenant_id,
        tenant_slug, tenant_name, user_id, email, name, user_enabled, user_deleted_at``.
        """
        ...

    def touch_session(self, session_id: str, now: datetime) -> None:
        """Record the session was just used."""
        ...

    def revoke_session(self, session_id: str, now: datetime) -> bool:
        """Stamp ``revoked_at`` if not yet revoked; True when this call revoked it."""
        ...

    def write_audit(
        self, *, tenant_id: str, action: str, actor_id: str, target: str, detail: Dict[str, Any]
    ) -> None:
        """Append an access-audit row."""
        ...


@dataclass(frozen=True)
class ReaderSession:
    """A session that just authenticated a request.

    Attributes:
        session_id: The session row.
        tenant_id: The tenant the session is bound to.
        tenant_slug: That tenant's slug.
        profile: The reader, as ``GET …/auth/me`` returns them.
    """

    session_id: str
    tenant_id: str
    tenant_slug: str
    profile: ReaderProfile


def _audit(repo: PortalAuthRepository, **kwargs: Any) -> None:
    """Write an audit row; a failure is logged, never raised (the audit ledger's contract)."""
    try:
        repo.write_audit(**kwargs)
    except Exception as exc:  # noqa: BLE001 — audit never fails the action it records
        _logger.warning("portal auth: could not write %s audit row (%s)", kwargs.get("action"), type(exc).__name__)


def _user_is_usable(user: Mapping[str, Any]) -> bool:
    """Whether an account may sign in (not disabled, not soft-deleted)."""
    return bool(user.get("enabled", True)) and user.get("deleted_at") is None


def _aware(value: Any) -> Any:
    """Treat a naive datetime from the database as UTC."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


# ---------------------------------------------------------------------------------------------
# Magic link
# ---------------------------------------------------------------------------------------------


def request_magic_link(
    repo: PortalAuthRepository,
    mailer: ReaderMailer,
    *,
    tenant_slug: str,
    email: str,
    return_to: Optional[str],
    browse_url: str,
    signup_rejection: Callable[[str], Optional[str]],
    now: Clock = _utc_now,
) -> bool:
    """Enrol the reader if needed and mail them a sign-in link.

    Args:
        repo: Storage.
        mailer: Sends the link.
        tenant_slug: The portal being signed into.
        email: The address as typed.
        return_to: A Browse path to land on afterwards.
        browse_url: The public Browse root the link points at.
        signup_rejection: Returns the sign-up policy's refusal code for a *new* address, or
            ``None`` when an account may be created (see :func:`app.signup_policy.signup_rejection_code`).
        now: Clock.

    Returns:
        True when a link was issued. The route ignores this and always answers ``202``.

    Raises:
        PortalAuthError: ``portal-invalid-email`` or ``portal-invalid-return-to`` for malformed
            input — the only refusals that are not hidden, since they reveal nothing.
    """
    address = normalize_email(email)
    landing = safe_return_to(return_to)

    tenant = repo.find_tenant(tenant_slug)
    if not tenant:
        _logger.info("portal auth: magic link refused (unknown tenant)")
        return False
    tenant_id = str(tenant["tenant_id"])

    user = repo.find_user_by_email(address)
    if user is None:
        refusal = signup_rejection(address)
        if refusal:
            _logger.info("portal auth: magic link refused (%s)", refusal)
            return False
        user = repo.create_user(address, address.split("@", 1)[0])
    if not _user_is_usable(user):
        _logger.info("portal auth: magic link refused (account disabled)")
        return False
    user_id = str(user["id"])

    membership = repo.find_membership(tenant_id, user_id) or repo.create_membership(
        tenant_id, user_id, SOURCE_MAGIC_LINK
    )
    if membership.get("status") == MEMBERSHIP_REVOKED:
        _logger.info("portal auth: magic link refused (membership revoked)")
        return False

    token, lookup_prefix, token_hash = mint_magic_link_token()
    repo.insert_magic_link(
        tenant_id=tenant_id,
        membership_id=str(membership["id"]),
        lookup_prefix=lookup_prefix,
        token_hash=token_hash,
        return_to=landing,
        expires_at=now() + timedelta(minutes=MAGIC_LINK_TTL_MINUTES),
    )
    mailer.send_magic_link(
        to=address,
        tenant_name=str(tenant.get("tenant_name") or tenant_slug),
        link=magic_link_url(browse_url, str(tenant["tenant_slug"]), token),
    )
    return True


def exchange_token(
    repo: PortalAuthRepository,
    *,
    tenant_slug: str,
    token: str,
    user_agent: Optional[str],
    session_ttl: timedelta,
    now: Clock = _utc_now,
) -> ReaderSessionGrant:
    """Exchange a magic-link token for a reader session, burning the token.

    Args:
        repo: Storage.
        tenant_slug: The tenant named in the link.
        token: The token from the link.
        user_agent: The reader's ``User-Agent``; only its family is kept.
        session_ttl: How long the new session lives.
        now: Clock.

    Returns:
        The session token (returned once), its expiry, the ``return_to`` the link carried, and the
        reader.

    Raises:
        PortalAuthError: ``portal-token-invalid`` (malformed, unknown, wrong tenant, wrong secret,
            or a revoked membership), ``portal-token-expired`` or ``portal-token-used``.
    """
    invalid = PortalAuthError(CODE_TOKEN_INVALID, "This sign-in link is not valid.")
    lookup_prefix = split_magic_link_token(token)
    tenant = repo.find_tenant(tenant_slug) if lookup_prefix else None
    if not tenant:
        raise invalid
    tenant_id = str(tenant["tenant_id"])
    link = repo.find_magic_link(tenant_id, lookup_prefix)
    if not link or not verify_magic_link_token(token, str(link["token_hash"])):
        raise invalid

    instant = now()
    if link.get("consumed_at") is not None:
        raise PortalAuthError(CODE_TOKEN_USED, "This sign-in link has already been used.")
    if _aware(link["expires_at"]) <= instant:
        raise PortalAuthError(CODE_TOKEN_EXPIRED, "This sign-in link has expired.")
    if not repo.burn_magic_link(str(link["id"]), instant):
        # Lost a race with a concurrent exchange of the same token.
        raise PortalAuthError(CODE_TOKEN_USED, "This sign-in link has already been used.")

    membership_id = str(link["membership_id"])
    newly_active = repo.activate_membership(membership_id, instant)
    session_token, session_hash = mint_session_token()
    family = user_agent_family(user_agent)
    stored = repo.insert_session(
        membership_id=membership_id,
        token_hash=session_hash,
        expires_at=instant + session_ttl,
        user_agent_family=family,
    )

    session = repo.find_session(session_hash)
    if not session or session.get("membership_status") != MEMBERSHIP_ACTIVE:
        # The membership was revoked between the link being issued and exchanged.
        repo.revoke_session(str(stored["id"]), instant)
        raise invalid
    repo.mark_user_verified(str(session["user_id"]))

    target = str(session["email"])
    actor = str(session["user_id"])
    if newly_active:
        _audit(
            repo,
            tenant_id=tenant_id,
            action=AUDIT_ENROLLED,
            actor_id=actor,
            target=target,
            detail={"source": SOURCE_MAGIC_LINK, "membership_id": membership_id},
        )
    _audit(
        repo,
        tenant_id=tenant_id,
        action=AUDIT_SIGNED_IN,
        actor_id=actor,
        target=target,
        detail={"session_id": str(stored["id"]), "user_agent_family": family, "method": SOURCE_MAGIC_LINK},
    )
    return ReaderSessionGrant(
        session_token=session_token,
        expires_at=_aware(stored["expires_at"]),
        return_to=link.get("return_to"),
        reader=_profile(session),
    )


# ---------------------------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------------------------


def _profile(session: Mapping[str, Any]) -> ReaderProfile:
    """Build the reader profile from a :meth:`PortalAuthRepository.find_session` row."""
    return ReaderProfile(
        user_id=str(session["user_id"]),
        email=str(session["email"]),
        name=session.get("name"),
        tenant_slug=str(session["tenant_slug"]),
        tenant_name=session.get("tenant_name"),
        membership_status=session["membership_status"],
        session_expires_at=_aware(session["expires_at"]),
    )


def resolve_session(
    repo: PortalAuthRepository, token: Optional[str], *, now: Clock = _utc_now
) -> ReaderSession:
    """Authenticate a reader session token.

    Args:
        repo: Storage.
        token: The token from ``Authorization: Reader <token>``.
        now: Clock.

    Returns:
        The live session.

    Raises:
        PortalAuthError: ``portal-session-invalid`` for a missing, unknown, expired or revoked
            session, a membership that is not active, or a disabled or deleted user.
    """
    invalid = PortalAuthError(CODE_SESSION_INVALID, "Sign in again to continue.")
    if not token:
        raise invalid
    session = repo.find_session(hash_session_token(token))
    instant = now()
    if (
        not session
        or session.get("revoked_at") is not None
        or _aware(session["expires_at"]) <= instant
        or session.get("membership_status") != MEMBERSHIP_ACTIVE
        or not session.get("user_enabled", True)
        or session.get("user_deleted_at") is not None
    ):
        raise invalid
    repo.touch_session(str(session["session_id"]), instant)
    return ReaderSession(
        session_id=str(session["session_id"]),
        tenant_id=str(session["tenant_id"]),
        tenant_slug=str(session["tenant_slug"]),
        profile=_profile(session),
    )


def revoke_session(repo: PortalAuthRepository, token: Optional[str], *, now: Clock = _utc_now) -> bool:
    """Sign a session out.

    Idempotent: an unknown or already revoked token changes nothing and is not an error, so a
    sign-out never fails.

    Args:
        repo: Storage.
        token: The session token.
        now: Clock.

    Returns:
        True when this call revoked a live session.
    """
    if not token:
        return False
    session = repo.find_session(hash_session_token(token))
    if not session or not repo.revoke_session(str(session["session_id"]), now()):
        return False
    _audit(
        repo,
        tenant_id=str(session["tenant_id"]),
        action=AUDIT_SESSION_REVOKED,
        actor_id=str(session["user_id"]),
        target=str(session["email"]),
        detail={"session_id": str(session["session_id"]), "reason": "sign_out"},
    )
    return True


# ---------------------------------------------------------------------------------------------
# The real repository (apiome-db V378)
# ---------------------------------------------------------------------------------------------


class SqlPortalAuthRepository:
    """:class:`PortalAuthRepository` over the shared ``db`` handle."""

    def __init__(self, database: Any) -> None:
        """Wrap a :class:`app.database.Database`.

        Args:
            database: The handle (``execute_query`` / ``connect``).
        """
        self._db = database

    def _one(self, query: str, params: tuple) -> Optional[Dict[str, Any]]:
        """Run a query and return its first row."""
        rows = self._db.execute_query(query, params)
        return dict(rows[0]) if rows else None

    def _write(self, query: str, params: tuple) -> Optional[Dict[str, Any]]:
        """Run a write with ``RETURNING`` and commit; returns the first returned row."""
        conn = self._db.connect()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params)
                row = cursor.fetchone() if cursor.description else None
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return dict(row) if row else None

    def find_tenant(self, tenant_slug: str) -> Optional[Mapping[str, Any]]:
        return self._db.get_active_tenant_auth_row(tenant_slug)

    def find_user_by_email(self, email: str) -> Optional[Mapping[str, Any]]:
        return self._one(
            """
            SELECT id::text AS id, email, name, enabled, deleted_at
            FROM apiome.users WHERE lower(email) = lower(%s)
            ORDER BY deleted_at NULLS FIRST LIMIT 1
            """,
            (email,),
        )

    def create_user(self, email: str, name: str) -> Mapping[str, Any]:
        # A reader has no password: ``''`` is the "no usable password" value V200 already skips.
        row = self._write(
            """
            INSERT INTO apiome.users (name, email, password, verified, enabled)
            VALUES (%s, %s, '', false, true)
            ON CONFLICT (lower(email::text)) WHERE deleted_at IS NULL
                DO UPDATE SET email = apiome.users.email
            RETURNING id::text AS id, email, name, enabled, deleted_at
            """,
            (name, email),
        )
        assert row is not None
        return row

    def find_membership(self, tenant_id: str, user_id: str) -> Optional[Mapping[str, Any]]:
        return self._one(
            """
            SELECT id::text AS id, tenant_id::text AS tenant_id, user_id::text AS user_id, status, activated_at
            FROM apiome.portal_memberships WHERE tenant_id = %s::uuid AND user_id = %s::uuid
            """,
            (tenant_id, user_id),
        )

    def create_membership(self, tenant_id: str, user_id: str, source: str) -> Mapping[str, Any]:
        row = self._write(
            """
            INSERT INTO apiome.portal_memberships (tenant_id, user_id, status, source)
            VALUES (%s::uuid, %s::uuid, 'invited', %s)
            ON CONFLICT (tenant_id, user_id) DO UPDATE SET updated_at = apiome.portal_memberships.updated_at
            RETURNING id::text AS id, tenant_id::text AS tenant_id, user_id::text AS user_id, status, activated_at
            """,
            (tenant_id, user_id, source),
        )
        assert row is not None
        return row

    def insert_magic_link(
        self,
        *,
        tenant_id: str,
        membership_id: str,
        lookup_prefix: str,
        token_hash: str,
        return_to: Optional[str],
        expires_at: datetime,
    ) -> None:
        self._write(
            """
            INSERT INTO apiome.portal_magic_links
                (tenant_id, membership_id, lookup_prefix, token_hash, return_to, expires_at)
            VALUES (%s::uuid, %s::uuid, %s, %s, %s, %s)
            """,
            (tenant_id, membership_id, lookup_prefix, token_hash, return_to, expires_at),
        )

    def find_magic_link(self, tenant_id: str, lookup_prefix: str) -> Optional[Mapping[str, Any]]:
        return self._one(
            """
            SELECT id::text AS id, membership_id::text AS membership_id, token_hash, return_to,
                   expires_at, consumed_at
            FROM apiome.portal_magic_links WHERE tenant_id = %s::uuid AND lookup_prefix = %s
            """,
            (tenant_id, lookup_prefix),
        )

    def burn_magic_link(self, link_id: str, now: datetime) -> bool:
        return (
            self._write(
                """
                UPDATE apiome.portal_magic_links SET consumed_at = %s
                WHERE id = %s::uuid AND consumed_at IS NULL AND expires_at > %s
                RETURNING id
                """,
                (now, link_id, now),
            )
            is not None
        )

    def activate_membership(self, membership_id: str, now: datetime) -> bool:
        return (
            self._write(
                """
                UPDATE apiome.portal_memberships
                SET status = 'active', activated_at = COALESCE(activated_at, %s), updated_at = %s
                WHERE id = %s::uuid AND status = 'invited'
                RETURNING id
                """,
                (now, now, membership_id),
            )
            is not None
        )

    def mark_user_verified(self, user_id: str) -> None:
        # Only a password-less account (the kind request_magic_link creates) is ever verified here.
        # An unverified account that holds a password — in ``users.password`` or a Better Auth
        # credential row — may have been signed up by someone else; verifying it would unlock that
        # stranger's password (account pre-hijacking). The workspace's own verification link
        # (apiome-ui ``redeemVerificationToken``) is the only path that verifies such an account.
        self._write(
            """
            UPDATE apiome.users u SET verified = true
            WHERE u.id = %s::uuid
              AND u.verified = false
              AND COALESCE(u.password, '') = ''
              AND NOT EXISTS (
                  SELECT 1 FROM apiome.account a
                  WHERE a."userId" = u.id
                    AND a."providerId" = 'credential'
                    AND COALESCE(a.password, '') <> ''
              )
            """,
            (user_id,),
        )

    def insert_session(
        self, *, membership_id: str, token_hash: str, expires_at: datetime, user_agent_family: str
    ) -> Mapping[str, Any]:
        row = self._write(
            """
            INSERT INTO apiome.portal_reader_sessions (membership_id, token_hash, expires_at, user_agent_family)
            VALUES (%s::uuid, %s, %s, %s)
            RETURNING id::text AS id, expires_at
            """,
            (membership_id, token_hash, expires_at, user_agent_family),
        )
        assert row is not None
        return row

    def find_session(self, token_hash: str) -> Optional[Mapping[str, Any]]:
        return self._one(
            """
            SELECT s.id::text AS session_id, s.expires_at, s.revoked_at,
                   m.id::text AS membership_id, m.status AS membership_status,
                   t.id::text AS tenant_id, t.slug AS tenant_slug, t.name AS tenant_name,
                   u.id::text AS user_id, u.email, u.name, u.enabled AS user_enabled,
                   u.deleted_at AS user_deleted_at
            FROM apiome.portal_reader_sessions s
            JOIN apiome.portal_memberships m ON m.id = s.membership_id
            JOIN apiome.tenants t ON t.id = m.tenant_id AND t.deleted_at IS NULL
            JOIN apiome.users u ON u.id = m.user_id
            WHERE s.token_hash = %s
            """,
            (token_hash,),
        )

    def touch_session(self, session_id: str, now: datetime) -> None:
        self._write(
            "UPDATE apiome.portal_reader_sessions SET last_seen_at = %s WHERE id = %s::uuid",
            (now, session_id),
        )

    def revoke_session(self, session_id: str, now: datetime) -> bool:
        return (
            self._write(
                """
                UPDATE apiome.portal_reader_sessions SET revoked_at = %s
                WHERE id = %s::uuid AND revoked_at IS NULL
                RETURNING id
                """,
                (now, session_id),
            )
            is not None
        )

    def write_audit(
        self, *, tenant_id: str, action: str, actor_id: str, target: str, detail: Dict[str, Any]
    ) -> None:
        self._db.write_access_audit(
            tenant_id=tenant_id,
            action=action,
            actor_id=actor_id,
            actor_label=target,
            target=target,
            source=AUDIT_SOURCE,
            detail=detail,
        )


_repository: Optional[PortalAuthRepository] = None


def default_repository() -> PortalAuthRepository:
    """The repository the routes and :mod:`app.auth` use (patched by tests)."""
    global _repository
    if _repository is None:
        from .database import db

        _repository = SqlPortalAuthRepository(db)
    return _repository
