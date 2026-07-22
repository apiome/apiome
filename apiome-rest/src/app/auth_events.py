"""Auth-event mapping — turn a 1.3 resolution outcome into an audit record (OLO-1.6, #4191).

The account-resolution engine (:mod:`app.account_resolution`, OLO-1.3) already decides what happens
when an OAuth identity arrives — sign in, auto-link, sign up, or a structured rejection. This module
is the pure seam that maps one of those outcomes onto a single durable :class:`AuthEvent`, so the
sign-in/sign-up/link paths leave a queryable trail without the resolution policy having to know
anything about auditing.

The mapping is intentionally pure (no I/O): callers turn a :class:`AuthEvent` into a row with
``Database.log_auth_event`` (or ``Database.write_auth_event``), and every write is best-effort — a
failed audit insert must never fail or block the sign-in it records.

Privacy: the raw client IP and User-Agent are never stored. :func:`hash_client_value` reduces them
to salted SHA-256 hashes suitable for correlating events (e.g. "same device") without retaining
directly-identifying network PII. See ``apiome-rest/docs/AUTH_EVENTS.md`` for the retention policy.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, Optional

from . import account_resolution as ar
from .database import normalize_email

# --- Event vocabulary — stable strings shared with the login-history consumers (#1607/#534/#2418).
#: A user was authenticated into an existing account.
EVENT_SIGN_IN = "sign_in"
#: A new account was created from a verified provider identity.
EVENT_SIGN_UP = "sign_up"
#: A provider identity was attached to a user (explicit link, or auto-link on a verified email).
EVENT_LINK = "link"
#: A provider identity was detached from a user.
EVENT_UNLINK = "unlink"

#: Every event type, for consumers that validate or enumerate them.
AUTH_EVENT_TYPES: FrozenSet[str] = frozenset(
    {EVENT_SIGN_IN, EVENT_SIGN_UP, EVENT_LINK, EVENT_UNLINK}
)

#: The attempt admitted the actor.
OUTCOME_SUCCESS = "success"
#: The attempt was refused (carries a stable ``error_code``).
OUTCOME_FAILURE = "failure"

#: Both outcomes, mirroring the ``auth_events_outcome_check`` DB constraint (V193).
AUTH_EVENT_OUTCOMES: FrozenSet[str] = frozenset({OUTCOME_SUCCESS, OUTCOME_FAILURE})

#: Default retention window for the ledger, in days (see ``docs/AUTH_EVENTS.md``). A year keeps a
#: full annual cycle available for support and security review while bounding growth; deployments
#: with stricter data-minimisation needs pass a smaller value to ``Database.prune_auth_events``.
DEFAULT_AUTH_EVENT_RETENTION_DAYS = 365


@dataclass(frozen=True)
class AuthEvent:
    """One authentication outcome, ready to append to ``apiome.auth_events``.

    Attributes:
        event_type: One of the ``EVENT_*`` constants.
        outcome: ``OUTCOME_SUCCESS`` or ``OUTCOME_FAILURE``.
        provider: OAuth provider slug (``github`` | ``gitlab`` | ``azure`` | ...), or None.
        user_id: The resolved user, when one exists (None for failures and pre-account sign-ups).
        user_label: Canonical email retained independent of the users row, when known.
        error_code: Stable rejection code for failures (see ``account_resolution.AUTH_ERROR_CODES``).
        detail: Optional structured context (e.g. ``{"auto_linked": True}``).
    """

    event_type: str
    outcome: str
    provider: Optional[str] = None
    user_id: Optional[str] = None
    user_label: Optional[str] = None
    error_code: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None


def hash_client_value(value: Optional[str], *, salt: str = "") -> Optional[str]:
    """Reduce a client IP or User-Agent to a salted SHA-256 hex digest for the audit ledger.

    The raw value is never returned or stored — only its digest — so the ledger can correlate
    events from the same address/device without retaining directly-identifying network PII. Supply a
    stable per-deployment ``salt`` to make the digests non-reversible against a precomputed table of
    common IPs/agents.

    Args:
        value: The raw IP or User-Agent string; whitespace is trimmed.
        salt: Optional deployment secret mixed in before hashing.

    Returns:
        A 64-char lowercase hex SHA-256 digest, or None when ``value`` is empty/absent.
    """
    if not isinstance(value, str):
        return None
    trimmed = value.strip()
    if not trimmed:
        return None
    return hashlib.sha256(f"{salt}{trimmed}".encode("utf-8")).hexdigest()


def _canonical_label(email: Optional[str]) -> Optional[str]:
    """Best-effort canonical email for ``user_label``; None for empty/absent input."""
    if not isinstance(email, str) or not email.strip():
        return None
    return normalize_email(email) or None


def event_from_decision(
    decision: ar.ResolutionDecision,
    facts: ar.ResolutionInput,
) -> AuthEvent:
    """Map an OLO-1.3 :class:`~app.account_resolution.ResolutionDecision` onto an :class:`AuthEvent`.

    The decision's ``action`` selects the event type and outcome; the originating ``facts`` supply
    the provider, the email label, and — for rejections, where the decision carries no user — the
    intent needed to tell a failed *link* or *sign-up* apart from a failed *sign-in*:

      * ``ACTION_SIGN_IN``       → ``sign_in`` / success
      * ``ACTION_SIGNUP``        → ``sign_up`` / success
      * ``ACTION_AUTO_LINK``     → ``link`` / success (``detail.auto_linked = True``)
      * ``ACTION_LINK_TO_SESSION`` → ``link`` / success
      * ``ACTION_REJECT``        → failure, with the stable ``error_code``; the event type is
        ``link`` when the round-trip was an explicit link, ``sign_up`` when self-signup was
        refused, otherwise ``sign_in``.

    Args:
        decision: The policy decision to record.
        facts: The resolution facts the decision was made from.

    Returns:
        The :class:`AuthEvent` to append (best-effort) to ``apiome.auth_events``.
    """
    provider = facts.provider or None
    label = _canonical_label(facts.email)

    if decision.action == ar.ACTION_SIGN_IN:
        return AuthEvent(
            event_type=EVENT_SIGN_IN,
            outcome=OUTCOME_SUCCESS,
            provider=provider,
            user_id=decision.user_id,
            user_label=label,
        )

    if decision.action == ar.ACTION_SIGNUP:
        return AuthEvent(
            event_type=EVENT_SIGN_UP,
            outcome=OUTCOME_SUCCESS,
            provider=provider,
            user_id=decision.user_id,
            user_label=label or _canonical_label(decision.email),
        )

    if decision.action == ar.ACTION_AUTO_LINK:
        return AuthEvent(
            event_type=EVENT_LINK,
            outcome=OUTCOME_SUCCESS,
            provider=provider,
            user_id=decision.user_id,
            user_label=label,
            detail={"auto_linked": True},
        )

    if decision.action == ar.ACTION_LINK_TO_SESSION:
        return AuthEvent(
            event_type=EVENT_LINK,
            outcome=OUTCOME_SUCCESS,
            provider=provider,
            user_id=decision.user_id,
            user_label=label,
        )

    # ACTION_REJECT (or any unrecognised action) → a failure. Recover the intended path so the
    # ledger distinguishes a refused link / sign-up from a refused sign-in.
    if facts.link_to_user_id:
        event_type = EVENT_LINK
        user_id: Optional[str] = facts.link_to_user_id
    elif decision.code == ar.SIGNUP_DISABLED:
        event_type = EVENT_SIGN_UP
        user_id = None
    else:
        event_type = EVENT_SIGN_IN
        user_id = None

    return AuthEvent(
        event_type=event_type,
        outcome=OUTCOME_FAILURE,
        provider=provider,
        user_id=user_id,
        user_label=label,
        error_code=decision.code,
    )
