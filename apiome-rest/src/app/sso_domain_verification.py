"""Proving a workspace owns an email domain before single sign-on may route it — EID-1.2 (#5012).

A workspace owner who registers an identity provider lists the email domains it signs in. Until a
domain is *verified* it routes nothing (V312), and it is verified one way only: the owner publishes
a DNS TXT record that only someone controlling the domain's DNS could publish.

    _apiome-challenge.acme.com.  TXT  "<verification token>"

This module holds the rules, with no HTTP or database in it:

* :func:`challenge_record_name` — where the record goes;
* :func:`refuse_public_domain` — the public-mailbox deny list (``gmail.com`` and the like), so no
  workspace can try to claim a domain it could never own. ``APIOME_SSO_PUBLIC_DOMAINS`` replaces
  the built-in list;
* :func:`check_domain_challenge` — the lookup and its verdict. A lookup that *fails* (timeout,
  SERVFAIL) is :data:`STATUS_COULD_NOT_CHECK`, never "verified" and never "not found": the owner is
  shown what the resolver said;
* :func:`enforce_verify_budget` — three checks an hour per domain row, so the endpoint cannot be
  used to hammer someone's nameservers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, FrozenSet, List, Optional, Sequence, Tuple

import dns.asyncresolver
import dns.exception
import dns.resolver
from fastapi import HTTPException

from .config import settings
from .rate_limit import FixedWindowRateLimiter
from .sso_metadata import SsoConfigError

__all__ = [
    "CHALLENGE_LABEL",
    "CODE_DOMAIN_PUBLIC",
    "CODE_VERIFY_RATE_LIMITED",
    "DEFAULT_PUBLIC_DOMAINS",
    "DnsCheck",
    "STATUS_COULD_NOT_CHECK",
    "STATUS_MISMATCH",
    "STATUS_NOT_FOUND",
    "STATUS_VERIFIED",
    "VERIFY_ATTEMPTS_PER_HOUR",
    "challenge_record_name",
    "check_domain_challenge",
    "enforce_verify_budget",
    "evaluate_txt_answers",
    "lookup_txt",
    "public_mail_domains",
    "refuse_public_domain",
]

#: The DNS label the challenge record lives under: ``_apiome-challenge.<domain>``.
CHALLENGE_LABEL = "_apiome-challenge"

CODE_DOMAIN_PUBLIC = "sso-domain-public"
CODE_VERIFY_RATE_LIMITED = "sso-verify-rate-limited"

#: The record holds the token: the domain is proved.
STATUS_VERIFIED = "verified"
#: No TXT record exists at the challenge name.
STATUS_NOT_FOUND = "not-found"
#: TXT records exist at the challenge name, but none is the token.
STATUS_MISMATCH = "mismatch"
#: The lookup itself failed, so nothing is known about the record.
STATUS_COULD_NOT_CHECK = "could-not-check"

#: Checks allowed per domain row in one :data:`VERIFY_WINDOW_SECONDS`.
VERIFY_ATTEMPTS_PER_HOUR = 3
VERIFY_WINDOW_SECONDS = 3600

#: How long one lookup may take before it is reported as "could not check".
LOOKUP_TIMEOUT_SECONDS = 5.0

#: How much of an answer is echoed back to the page.
MAX_OBSERVED_VALUES = 10
MAX_OBSERVED_LENGTH = 255

#: Mailbox providers anyone can get an address at. Nobody registering an IdP owns these, and a
#: workspace that claimed one would be asking to sign in strangers.
DEFAULT_PUBLIC_DOMAINS: Tuple[str, ...] = (
    "aol.com",
    "fastmail.com",
    "gmail.com",
    "gmx.com",
    "gmx.net",
    "googlemail.com",
    "hey.com",
    "hotmail.com",
    "icloud.com",
    "live.com",
    "mac.com",
    "mail.com",
    "mail.ru",
    "me.com",
    "msn.com",
    "outlook.com",
    "pm.me",
    "proton.me",
    "protonmail.com",
    "qq.com",
    "yahoo.co.jp",
    "yahoo.co.uk",
    "yahoo.com",
    "yandex.com",
    "yandex.ru",
    "zoho.com",
    "163.com",
)

#: ``(state, values, detail)`` from one TXT lookup — see :func:`lookup_txt`.
TxtLookup = Tuple[str, List[str], Optional[str]]

_LOOKUP_ANSWERED = "answered"
_LOOKUP_EMPTY = "empty"
_LOOKUP_FAILED = "failed"

_verify_limiter = FixedWindowRateLimiter()


@dataclass(frozen=True)
class DnsCheck:
    """The outcome of one challenge lookup.

    Attributes:
        status: One of the ``STATUS_*`` values.
        record_name: The TXT record that was looked up.
        expected: The value the record must hold (the verification token; not a secret).
        observed: What the resolver answered: the TXT values found, or one line describing why
            the lookup failed. Bounded, so a hostile zone cannot inflate the response.
        message: One sentence for the page.
    """

    status: str
    record_name: str
    expected: str
    observed: List[str] = field(default_factory=list)
    message: str = ""

    @property
    def verified(self) -> bool:
        """Whether the domain is proved."""
        return self.status == STATUS_VERIFIED


def challenge_record_name(domain: str) -> str:
    """The TXT record a domain's owner publishes: ``_apiome-challenge.<domain>``.

    Args:
        domain: A normalized domain (:func:`app.sso_metadata.normalize_domain`).

    Returns:
        The record name, without a trailing dot.
    """
    return f"{CHALLENGE_LABEL}.{domain}"


def public_mail_domains() -> FrozenSet[str]:
    """The public-mailbox deny list in force.

    Returns:
        ``APIOME_SSO_PUBLIC_DOMAINS`` (comma-separated, lower-cased) when it names at least one
        domain, otherwise :data:`DEFAULT_PUBLIC_DOMAINS`.
    """
    configured = [part.strip().lower().rstrip(".") for part in (settings.sso_public_domains or "").split(",")]
    configured = [part for part in configured if part]
    return frozenset(configured or DEFAULT_PUBLIC_DOMAINS)


def refuse_public_domain(domain: str) -> None:
    """Refuse a public mailbox domain, or a subdomain of one.

    Args:
        domain: A normalized domain.

    Raises:
        SsoConfigError: ``sso-domain-public``.
    """
    public = public_mail_domains()
    labels = domain.split(".")
    # ``mail.gmail.com`` is as unownable as ``gmail.com``: test the domain and every parent.
    if any(".".join(labels[start:]) in public for start in range(len(labels) - 1)):
        raise SsoConfigError(
            CODE_DOMAIN_PUBLIC,
            f"{domain} is a public email provider. Add a domain your organization owns.",
        )


def _bounded(values: Sequence[str]) -> List[str]:
    """Trim an answer to what the page may echo."""
    return [value[:MAX_OBSERVED_LENGTH] for value in values[:MAX_OBSERVED_VALUES]]


def evaluate_txt_answers(domain: str, token: str, lookup: TxtLookup) -> DnsCheck:
    """Turn one TXT lookup into a verdict.

    Args:
        domain: The domain being proved.
        token: The verification token the record must hold.
        lookup: ``(state, values, detail)`` as :func:`lookup_txt` returns it.

    Returns:
        The verdict. Only an answer containing the token, whitespace-trimmed, is ``verified``; a
        failed lookup is ``could-not-check`` whatever else is true.
    """
    record = challenge_record_name(domain)
    state, values, detail = lookup
    if state == _LOOKUP_FAILED:
        return DnsCheck(
            status=STATUS_COULD_NOT_CHECK,
            record_name=record,
            expected=token,
            observed=_bounded([detail or "The DNS lookup failed."]),
            message=f"Could not check {record}. Nothing was changed; try again in a few minutes.",
        )
    if state == _LOOKUP_EMPTY or not values:
        return DnsCheck(
            status=STATUS_NOT_FOUND,
            record_name=record,
            expected=token,
            observed=_bounded([detail] if detail else []),
            message=f"No TXT record was found at {record}. DNS changes can take a while to appear.",
        )
    if any(value.strip() == token for value in values):
        return DnsCheck(
            status=STATUS_VERIFIED,
            record_name=record,
            expected=token,
            observed=_bounded(values),
            message=f"{domain} is verified.",
        )
    return DnsCheck(
        status=STATUS_MISMATCH,
        record_name=record,
        expected=token,
        observed=_bounded(values),
        message=f"{record} has a TXT record, but not the expected value.",
    )


async def lookup_txt(record_name: str) -> TxtLookup:
    """Look one TXT record up through the system resolvers. Never raises.

    Args:
        record_name: The fully qualified record name.

    Returns:
        ``("answered", values, None)`` with each record's strings joined; ``("empty", [], why)``
        when the name or the record type does not exist; ``("failed", [], why)`` when the lookup
        itself did not complete (timeout, SERVFAIL, no reachable nameserver).
    """
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = LOOKUP_TIMEOUT_SECONDS
    try:
        answer = await resolver.resolve(record_name, "TXT", lifetime=LOOKUP_TIMEOUT_SECONDS)
    except dns.resolver.NXDOMAIN:
        return (_LOOKUP_EMPTY, [], "NXDOMAIN: the name does not exist.")
    except dns.resolver.NoAnswer:
        return (_LOOKUP_EMPTY, [], "The name exists but has no TXT record.")
    except dns.resolver.NoNameservers:
        return (_LOOKUP_FAILED, [], "SERVFAIL: no nameserver answered for this name.")
    except dns.exception.Timeout:
        return (_LOOKUP_FAILED, [], f"The DNS lookup timed out after {int(LOOKUP_TIMEOUT_SECONDS)} seconds.")
    except (dns.exception.DNSException, OSError) as exc:
        return (_LOOKUP_FAILED, [], f"The DNS lookup failed ({type(exc).__name__}).")
    values = [b"".join(rdata.strings).decode("utf-8", errors="replace") for rdata in answer]
    return (_LOOKUP_ANSWERED, values, None)


async def check_domain_challenge(
    domain: str,
    token: str,
    *,
    lookup: Callable[[str], Awaitable[TxtLookup]] = lookup_txt,
) -> DnsCheck:
    """Look the challenge record up and say whether the domain is proved.

    Args:
        domain: A normalized domain.
        token: Its verification token.
        lookup: The TXT lookup (injectable for tests).

    Returns:
        The verdict.
    """
    return evaluate_txt_answers(domain, token, await lookup(challenge_record_name(domain)))


def enforce_verify_budget(bucket: str, *, now: Optional[float] = None) -> None:
    """Spend one of the hour's checks for a domain row, or refuse.

    Honours the global ``rate_limit_enabled`` kill switch, like the other auth budgets
    (:mod:`app.auth_rate_limit`). The window is per process.

    Args:
        bucket: What the budget is counted against — the provider id and the domain, so one
            workspace cannot spend another's checks.
        now: Monotonic time (injectable for tests).

    Raises:
        HTTPException: ``429`` ``sso-verify-rate-limited`` with ``Retry-After``.
    """
    if not settings.rate_limit_enabled:
        return
    allowed, _remaining, _reset_after, retry_after = _verify_limiter.check(
        f"ssoverify:{bucket}",
        VERIFY_ATTEMPTS_PER_HOUR,
        VERIFY_WINDOW_SECONDS,
        time.monotonic() if now is None else now,
    )
    if not allowed:
        minutes = max(1, round(retry_after / 60))
        raise HTTPException(
            status_code=429,
            detail={
                "error": CODE_VERIFY_RATE_LIMITED,
                "message": (
                    f"This domain was checked {VERIFY_ATTEMPTS_PER_HOUR} times in the last hour. "
                    f"Try again in about {minutes} minute{'s' if minutes != 1 else ''}."
                ),
            },
            headers={"Retry-After": str(retry_after)},
        )
