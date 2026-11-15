"""Reader enrolment, exchange and sessions — PCX-1.1 (#5889) acceptance criteria, store level."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fake_portal_auth_repo import TENANT_ID, FakePortalAuthRepository, RecordingMailer

from app import portal_auth_store as store
from app.portal_auth import (
    AUDIT_ENROLLED,
    AUDIT_SESSION_REVOKED,
    AUDIT_SIGNED_IN,
    CODE_SESSION_INVALID,
    CODE_TOKEN_EXPIRED,
    CODE_TOKEN_INVALID,
    CODE_TOKEN_USED,
    PortalAuthError,
)

T0 = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
TTL = timedelta(days=7)
CHROME = "Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/130.0 Safari/537.36"


class Clock:
    """A settable clock."""

    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def repo():
    return FakePortalAuthRepository()


@pytest.fixture
def mailer():
    return RecordingMailer()


@pytest.fixture
def clock():
    return Clock()


def _request(repo, mailer, clock, email="ada@example.com", *, tenant="acme", rejection=None, return_to=None):
    return store.request_magic_link(
        repo,
        mailer,
        tenant_slug=tenant,
        email=email,
        return_to=return_to,
        browse_url="https://browse.example",
        signup_rejection=lambda _email: rejection,
        now=clock,
    )


def _exchange(repo, clock, token, tenant="acme"):
    return store.exchange_token(
        repo, tenant_slug=tenant, token=token, user_agent=CHROME, session_ttl=TTL, now=clock
    )


def _sign_in(repo, mailer, clock, email="ada@example.com"):
    assert _request(repo, mailer, clock, email)
    return _exchange(repo, clock, mailer.last_token())


# ---------------------------------------------------------------------------------------------
# A magic link signs a new reader in and creates exactly one user and one membership
# ---------------------------------------------------------------------------------------------


def test_a_new_reader_gets_one_user_one_membership_and_a_link(repo, mailer, clock):
    assert _request(repo, mailer, clock, "  Ada@Example.com ", return_to="/tenant/acme")
    assert len(repo.users) == 1 and len(repo.memberships) == 1 and len(repo.links) == 1
    membership = repo.membership_for("ada@example.com")
    assert membership["status"] == "invited" and membership["source"] == "magic_link"
    (sent,) = mailer.sent
    assert sent["to"] == "ada@example.com" and sent["tenant_name"] == "Acme"
    assert sent["link"].startswith("https://browse.example/portal/auth/exchange?tenant=acme&token=pml_")
    link = next(iter(repo.links.values()))
    assert link["expires_at"] == T0 + timedelta(minutes=15)
    assert mailer.last_token() not in link["token_hash"]


def test_the_exchange_signs_the_reader_in(repo, mailer, clock):
    _request(repo, mailer, clock, return_to="/tenant/acme/pets")
    grant = _exchange(repo, clock, mailer.last_token())
    assert grant.return_to == "/tenant/acme/pets"
    assert grant.expires_at == T0 + TTL
    assert grant.reader.email == "ada@example.com" and grant.reader.tenant_slug == "acme"
    assert grant.reader.membership_status == "active"
    (session,) = repo.sessions.values()
    assert session["user_agent_family"] == "Chrome"
    assert session["token_hash"] != grant.session_token
    (user,) = repo.users.values()
    assert user["verified"] is True


def test_a_second_request_reuses_the_user_and_the_membership(repo, mailer, clock):
    _sign_in(repo, mailer, clock)
    _sign_in(repo, mailer, clock, "ADA@example.com")
    assert len(repo.users) == 1 and len(repo.memberships) == 1
    assert len(repo.links) == 2 and len(repo.sessions) == 2
    # Enrolment is recorded once; every sign-in is recorded.
    actions = [row["action"] for row in repo.audit]
    assert actions.count(AUDIT_ENROLLED) == 1 and actions.count(AUDIT_SIGNED_IN) == 2


def test_an_existing_account_becomes_a_reader_without_a_new_user(repo, mailer, clock):
    repo.add_user("lin@example.com")
    _sign_in(repo, mailer, clock, "lin@example.com")
    assert len(repo.users) == 1 and repo.membership_for("lin@example.com")["status"] == "active"


def test_a_reader_link_never_verifies_an_account_that_holds_a_password(repo, mailer, clock):
    """Pre-hijacking guard: a stranger signed up with the address (unverified, their password)."""
    user_id = repo.add_user("victim@example.com", password="$2b$10$attackerhash")
    grant = _sign_in(repo, mailer, clock, "victim@example.com")
    # The real owner still gets their reader session …
    assert grant.reader.email == "victim@example.com"
    # … but the stranger's password is not unlocked.
    assert repo.users[user_id]["verified"] is False


def test_an_already_verified_account_stays_verified(repo, mailer, clock):
    user_id = repo.add_user("lin@example.com", password="$2b$10$hash", verified=True)
    _sign_in(repo, mailer, clock, "lin@example.com")
    assert repo.users[user_id]["verified"] is True


def test_one_user_can_read_two_portals(repo, mailer, clock):
    _sign_in(repo, mailer, clock)
    _request(repo, mailer, clock, tenant="globex")
    grant = _exchange(repo, clock, mailer.last_token(), tenant="globex")
    assert grant.reader.tenant_slug == "globex"
    assert len(repo.users) == 1 and len(repo.memberships) == 2


# ---------------------------------------------------------------------------------------------
# What a request never does (and never reveals)
# ---------------------------------------------------------------------------------------------


def test_the_signup_policy_refuses_creating_an_account(repo, mailer, clock):
    assert _request(repo, mailer, clock, rejection="signup-invite-only") is False
    assert repo.users == {} and mailer.sent == []


def test_the_signup_policy_never_refuses_an_existing_account(repo, mailer, clock):
    repo.add_user("ada@example.com")
    assert _request(repo, mailer, clock, rejection="signup-disabled") is True


@pytest.mark.parametrize("kwargs", [{"enabled": False}, {"deleted": True}])
def test_a_disabled_or_deleted_account_gets_no_link(repo, mailer, clock, kwargs):
    repo.add_user("ada@example.com", **kwargs)
    assert _request(repo, mailer, clock) is False
    assert mailer.sent == [] and repo.memberships == {}


def test_an_unknown_tenant_gets_no_link(repo, mailer, clock):
    assert _request(repo, mailer, clock, tenant="nope") is False
    assert repo.users == {} and mailer.sent == []


def test_a_revoked_reader_gets_no_link(repo, mailer, clock):
    _sign_in(repo, mailer, clock)
    membership = repo.membership_for("ada@example.com")
    membership["status"] = "revoked"
    assert _request(repo, mailer, clock) is False
    assert len(mailer.sent) == 1


# ---------------------------------------------------------------------------------------------
# An expired or reused token is refused with a reason
# ---------------------------------------------------------------------------------------------


def _refusal(repo, clock, token, tenant="acme"):
    with pytest.raises(PortalAuthError) as exc:
        _exchange(repo, clock, token, tenant)
    return exc.value.code


def test_a_reused_token_is_refused_as_used(repo, mailer, clock):
    _request(repo, mailer, clock)
    token = mailer.last_token()
    _exchange(repo, clock, token)
    assert _refusal(repo, clock, token) == CODE_TOKEN_USED
    assert len(repo.sessions) == 1


def test_an_expired_token_is_refused_as_expired(repo, mailer, clock):
    _request(repo, mailer, clock)
    clock.now = T0 + timedelta(minutes=15)
    assert _refusal(repo, clock, mailer.last_token()) == CODE_TOKEN_EXPIRED
    assert repo.sessions == {}


def test_a_token_still_works_just_before_it_expires(repo, mailer, clock):
    _request(repo, mailer, clock)
    clock.now = T0 + timedelta(minutes=14, seconds=59)
    assert _exchange(repo, clock, mailer.last_token()).reader.email == "ada@example.com"


def test_losing_the_burn_race_is_refused_as_used(repo, mailer, clock, monkeypatch):
    _request(repo, mailer, clock)
    monkeypatch.setattr(repo, "burn_magic_link", lambda *_: False)
    assert _refusal(repo, clock, mailer.last_token()) == CODE_TOKEN_USED


@pytest.mark.parametrize("token", ["", "garbage", "pml_0123456789abcdef." + "0" * 48])
def test_unknown_or_malformed_tokens_are_invalid(repo, mailer, clock, token):
    assert _refusal(repo, clock, token) == CODE_TOKEN_INVALID


def test_a_token_with_the_wrong_secret_is_invalid_and_not_burned(repo, mailer, clock):
    _request(repo, mailer, clock)
    token = mailer.last_token()
    prefix, secret = token.split(".")
    forged = f"{prefix}.{'0' * 48 if secret != '0' * 48 else '1' * 48}"
    assert _refusal(repo, clock, forged) == CODE_TOKEN_INVALID
    # The real token still works: a guess cannot burn someone else's link.
    assert _exchange(repo, clock, token).reader.email == "ada@example.com"


def test_a_token_is_bound_to_its_tenant(repo, mailer, clock):
    _request(repo, mailer, clock)
    assert _refusal(repo, clock, mailer.last_token(), tenant="globex") == CODE_TOKEN_INVALID


def test_a_membership_revoked_before_the_exchange_gets_no_session(repo, mailer, clock):
    _sign_in(repo, mailer, clock)
    _request(repo, mailer, clock)
    repo.membership_for("ada@example.com")["status"] = "revoked"
    assert _refusal(repo, clock, mailer.last_token()) == CODE_TOKEN_INVALID
    assert all(session["revoked_at"] is not None for session in list(repo.sessions.values())[1:])


# ---------------------------------------------------------------------------------------------
# Sessions: revoking takes effect on the next request
# ---------------------------------------------------------------------------------------------


def test_a_live_session_resolves_and_is_touched(repo, mailer, clock):
    grant = _sign_in(repo, mailer, clock)
    clock.now = T0 + timedelta(hours=1)
    session = store.resolve_session(repo, grant.session_token, now=clock)
    assert session.tenant_id == TENANT_ID and session.profile.email == "ada@example.com"
    assert repo.sessions[session.session_id]["last_seen_at"] == clock.now


def test_sign_out_takes_effect_on_the_next_request(repo, mailer, clock):
    grant = _sign_in(repo, mailer, clock)
    assert store.revoke_session(repo, grant.session_token, now=clock) is True
    with pytest.raises(PortalAuthError) as exc:
        store.resolve_session(repo, grant.session_token, now=clock)
    assert exc.value.code == CODE_SESSION_INVALID
    assert repo.audit[-1]["action"] == AUDIT_SESSION_REVOKED
    # Idempotent: signing out again changes nothing and writes no second row.
    assert store.revoke_session(repo, grant.session_token, now=clock) is False
    assert [row["action"] for row in repo.audit].count(AUDIT_SESSION_REVOKED) == 1


def test_revoking_the_membership_ends_every_session(repo, mailer, clock):
    grant = _sign_in(repo, mailer, clock)
    repo.membership_for("ada@example.com")["status"] = "revoked"
    with pytest.raises(PortalAuthError):
        store.resolve_session(repo, grant.session_token, now=clock)


def test_disabling_the_user_ends_every_session(repo, mailer, clock):
    grant = _sign_in(repo, mailer, clock)
    next(iter(repo.users.values()))["enabled"] = False
    with pytest.raises(PortalAuthError):
        store.resolve_session(repo, grant.session_token, now=clock)


def test_an_expired_session_is_refused(repo, mailer, clock):
    grant = _sign_in(repo, mailer, clock)
    clock.now = T0 + TTL
    with pytest.raises(PortalAuthError):
        store.resolve_session(repo, grant.session_token, now=clock)


@pytest.mark.parametrize("token", [None, "", "prs_unknown"])
def test_unknown_sessions_are_refused(repo, token):
    with pytest.raises(PortalAuthError) as exc:
        store.resolve_session(repo, token)
    assert exc.value.code == CODE_SESSION_INVALID


def test_sign_out_of_nothing_is_not_an_error(repo):
    assert store.revoke_session(repo, None) is False
    assert store.revoke_session(repo, "prs_unknown") is False


# ---------------------------------------------------------------------------------------------
# Audit: metadata only, never fatal
# ---------------------------------------------------------------------------------------------


def test_audit_rows_carry_metadata_and_never_a_token(repo, mailer, clock):
    grant = _sign_in(repo, mailer, clock)
    token = mailer.sent[-1]["link"].split("token=")[1]
    for row in repo.audit:
        assert row["tenant_id"] == TENANT_ID and row["target"] == "ada@example.com"
        flat = repr(row)
        assert grant.session_token not in flat and token not in flat
    signed_in = next(row for row in repo.audit if row["action"] == AUDIT_SIGNED_IN)
    assert signed_in["detail"]["user_agent_family"] == "Chrome"


def test_an_audit_failure_never_fails_sign_in(repo, mailer, clock):
    repo.fail_audit = True
    assert _sign_in(repo, mailer, clock).reader.email == "ada@example.com"
