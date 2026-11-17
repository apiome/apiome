"""Proving a domain by DNS — EID-1.2 (#5012).

The rules of :mod:`app.sso_domain_verification`, with the resolver replaced by canned answers (no
network):

* where the challenge record goes;
* the public-mailbox deny list, its subdomains, and its ``APIOME_SSO_PUBLIC_DOMAINS`` override;
* the verdict for every kind of answer — and above all that a lookup which *fails* is
  ``could-not-check`` with what the resolver said, never ``verified``;
* how dnspython's outcomes map onto a lookup;
* three checks an hour per domain row.
"""

from __future__ import annotations

from typing import List

import dns.exception
import dns.resolver
import pytest
from fastapi import HTTPException

from app import sso_domain_verification as verification
from app.config import settings
from app.sso_domain_verification import (
    CODE_DOMAIN_PUBLIC,
    CODE_VERIFY_RATE_LIMITED,
    STATUS_COULD_NOT_CHECK,
    STATUS_MISMATCH,
    STATUS_NOT_FOUND,
    STATUS_VERIFIED,
    VERIFY_ATTEMPTS_PER_HOUR,
    challenge_record_name,
    check_domain_challenge,
    enforce_verify_budget,
    evaluate_txt_answers,
    lookup_txt,
    public_mail_domains,
    refuse_public_domain,
)
from app.sso_metadata import SsoConfigError

TOKEN = "tok-3fJ9aQ2LxZ"


def test_the_challenge_record_sits_under_the_domain() -> None:
    assert challenge_record_name("acme.com") == "_apiome-challenge.acme.com"


# ---------------------------------------------------------------------------
# Public mailbox domains
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("domain", ["gmail.com", "outlook.com", "yahoo.com", "mail.gmail.com", "a.b.yahoo.co.uk"])
def test_public_mailbox_domains_and_their_subdomains_are_refused(domain: str) -> None:
    with pytest.raises(SsoConfigError) as caught:
        refuse_public_domain(domain)
    assert caught.value.code == CODE_DOMAIN_PUBLIC


@pytest.mark.parametrize("domain", ["acme.com", "notgmail.com", "gmail.com.acme.io", "com"])
def test_other_domains_pass(domain: str) -> None:
    refuse_public_domain(domain)


def test_the_deny_list_is_replaced_by_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sso_public_domains", " Example.org , webmail.test. ,, ")
    assert public_mail_domains() == frozenset({"example.org", "webmail.test"})
    with pytest.raises(SsoConfigError):
        refuse_public_domain("example.org")
    refuse_public_domain("gmail.com")  # no longer listed


def test_a_blank_setting_keeps_the_built_in_list(monkeypatch) -> None:
    monkeypatch.setattr(settings, "sso_public_domains", " , ")
    assert "gmail.com" in public_mail_domains()


# ---------------------------------------------------------------------------
# The verdict
# ---------------------------------------------------------------------------


def test_the_token_verifies_the_domain() -> None:
    check = evaluate_txt_answers("acme.com", TOKEN, ("answered", ["v=spf1 -all", f"  {TOKEN} "], None))
    assert check.status == STATUS_VERIFIED and check.verified is True
    assert check.record_name == "_apiome-challenge.acme.com"
    assert check.expected == TOKEN


def test_another_value_is_a_mismatch_and_is_shown() -> None:
    check = evaluate_txt_answers("acme.com", TOKEN, ("answered", ["someone-elses-token", TOKEN + "x"], None))
    assert check.status == STATUS_MISMATCH and check.verified is False
    assert check.observed == ["someone-elses-token", TOKEN + "x"]


def test_no_record_is_not_found() -> None:
    check = evaluate_txt_answers("acme.com", TOKEN, ("empty", [], "NXDOMAIN: the name does not exist."))
    assert check.status == STATUS_NOT_FOUND and check.verified is False
    assert check.observed == ["NXDOMAIN: the name does not exist."]


def test_a_failed_lookup_is_could_not_check_never_verified() -> None:
    """Even an answer carrying the token does not verify when the lookup is reported failed."""
    check = evaluate_txt_answers("acme.com", TOKEN, ("failed", [TOKEN], "SERVFAIL: no nameserver answered."))
    assert check.status == STATUS_COULD_NOT_CHECK and check.verified is False
    assert check.observed == ["SERVFAIL: no nameserver answered."]
    assert "Could not check" in check.message


def test_the_echoed_answer_is_bounded() -> None:
    values = ["x" * 5000] * 50
    check = evaluate_txt_answers("acme.com", TOKEN, ("answered", values, None))
    assert len(check.observed) == verification.MAX_OBSERVED_VALUES
    assert all(len(value) == verification.MAX_OBSERVED_LENGTH for value in check.observed)


async def test_the_check_looks_up_the_challenge_record() -> None:
    asked: List[str] = []

    async def lookup(name: str):
        asked.append(name)
        return ("answered", [TOKEN], None)

    check = await check_domain_challenge("acme.com", TOKEN, lookup=lookup)
    assert asked == ["_apiome-challenge.acme.com"]
    assert check.verified is True


# ---------------------------------------------------------------------------
# dnspython outcomes
# ---------------------------------------------------------------------------


class _Rdata:
    def __init__(self, *strings: bytes) -> None:
        self.strings = strings


def _resolver(monkeypatch, outcome):
    class FakeResolver:
        lifetime = 0.0

        async def resolve(self, name, rdtype, lifetime=None):
            assert rdtype == "TXT"
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

    monkeypatch.setattr(verification.dns.asyncresolver, "Resolver", FakeResolver)


async def test_txt_strings_of_one_record_are_joined(monkeypatch) -> None:
    _resolver(monkeypatch, [_Rdata(b"tok-", b"abc"), _Rdata(b"other")])
    assert await lookup_txt("_apiome-challenge.acme.com") == ("answered", ["tok-abc", "other"], None)


@pytest.mark.parametrize(
    "error,state",
    [
        (dns.resolver.NXDOMAIN(), "empty"),
        (dns.resolver.NoAnswer(), "empty"),
        (dns.resolver.NoNameservers(), "failed"),
        (dns.exception.Timeout(), "failed"),
        (dns.exception.DNSException("boom"), "failed"),
        (OSError("network unreachable"), "failed"),
    ],
)
async def test_resolver_outcomes_map_onto_a_lookup(monkeypatch, error, state) -> None:
    _resolver(monkeypatch, error)
    found_state, values, detail = await lookup_txt("_apiome-challenge.acme.com")
    assert found_state == state and values == [] and detail


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------


def test_three_checks_an_hour_per_domain_row(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(verification, "_verify_limiter", verification.FixedWindowRateLimiter())
    for _ in range(VERIFY_ATTEMPTS_PER_HOUR):
        enforce_verify_budget("provider-1:acme.com", now=100.0)
    with pytest.raises(HTTPException) as caught:
        enforce_verify_budget("provider-1:acme.com", now=200.0)
    assert caught.value.status_code == 429
    assert caught.value.detail["error"] == CODE_VERIFY_RATE_LIMITED
    assert int(caught.value.headers["Retry-After"]) > 0
    # Another workspace's row for the same domain has its own budget; so does the next hour.
    enforce_verify_budget("provider-2:acme.com", now=200.0)
    enforce_verify_budget("provider-1:acme.com", now=100.0 + verification.VERIFY_WINDOW_SECONDS + 1)


def test_the_kill_switch_turns_the_budget_off(monkeypatch) -> None:
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(verification, "_verify_limiter", verification.FixedWindowRateLimiter())
    for _ in range(VERIFY_ATTEMPTS_PER_HOUR + 5):
        enforce_verify_budget("provider-1:acme.com", now=100.0)
