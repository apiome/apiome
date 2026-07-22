"""Structured auth error contract tests — REST parity side (OLO-1.5, #4190).

Mirrors ``apiome-ui/tests/auth-error-contract.test.ts``:

  1. Code values are stable — exact-value assertions fail the build on any accidental rename.
  2. Every engine-emitted code has a test forcing it through the policy.

The contract is documented in ``apiome-ui/docs/AUTH_ERROR_CODES.md``; the TypeScript engine
defines the same values in ``AUTH_ERROR_CODES`` and both sides must stay identical.
"""

from app.account_resolution import (
    ACCOUNT_DISABLED,
    ACCOUNT_NOT_VERIFIED,
    ACTION_AUTO_LINK,
    ACTION_REJECT,
    AUTH_ERROR_CODES,
    EMAIL_REQUIRED,
    IDENTITY_LINKED_ELSEWHERE,
    LAST_SIGN_IN_METHOD,
    MEMBERSHIP_SUSPENDED,
    PROFILE_INCOMPLETE,
    PROVIDER_ALREADY_LINKED,
    PROVIDER_NOT_CONFIGURED,
    SIGNUP_DISABLED,
    UNVERIFIED_EMAIL,
    ResolutionIdentity,
    ResolutionInput,
    ResolutionUser,
    resolve_account_decision,
)

OK_USER = ResolutionUser(id="user-ok", enabled=True, verified=True)


def _base(**overrides) -> ResolutionInput:
    defaults = dict(
        provider="github",
        provider_user_id="prov-123",
        email="ada@example.com",
        email_verified=True,
        link_to_user_id=None,
        identity=ResolutionIdentity(),
        email_user=None,
    )
    defaults.update(overrides)
    return ResolutionInput(**defaults)


# --- 1. Value stability -------------------------------------------------------


def test_every_code_keeps_its_documented_value():
    """Never change these values — add a new code instead (see AUTH_ERROR_CODES.md)."""
    assert UNVERIFIED_EMAIL == "unverified-email"
    assert EMAIL_REQUIRED == "OAuthEmailRequired"
    assert PROFILE_INCOMPLETE == "OAuthProfileIncomplete"
    assert ACCOUNT_DISABLED == "account-disabled"
    assert ACCOUNT_NOT_VERIFIED == "account-not-verified"
    assert PROVIDER_ALREADY_LINKED == "provider-already-linked"
    assert IDENTITY_LINKED_ELSEWHERE == "identity-linked-elsewhere"
    assert LAST_SIGN_IN_METHOD == "last-sign-in-method"
    assert MEMBERSHIP_SUSPENDED == "membership-suspended"
    assert PROVIDER_NOT_CONFIGURED == "provider-not-configured"
    assert SIGNUP_DISABLED == "signup-disabled"


def test_the_enumeration_lists_exactly_the_contract():
    assert AUTH_ERROR_CODES == frozenset(
        {
            "unverified-email",
            "OAuthEmailRequired",
            "OAuthProfileIncomplete",
            "account-disabled",
            "account-not-verified",
            "provider-already-linked",
            "identity-linked-elsewhere",
            "last-sign-in-method",
            "membership-suspended",
            "provider-not-configured",
            "signup-disabled",
        }
    )


# --- 2. A forcing test per engine-emitted code --------------------------------


def test_unverified_email_forced_by_unproven_address():
    decision = resolve_account_decision(_base(email_verified=False))
    assert (decision.action, decision.code) == (ACTION_REJECT, UNVERIFIED_EMAIL)


def test_email_required_forced_by_absent_address():
    decision = resolve_account_decision(_base(email=None))
    assert (decision.action, decision.code) == (ACTION_REJECT, EMAIL_REQUIRED)


def test_profile_incomplete_forced_by_missing_provider_user_id():
    decision = resolve_account_decision(_base(provider_user_id=None))
    assert (decision.action, decision.code) == (ACTION_REJECT, PROFILE_INCOMPLETE)


def test_account_disabled_forced_on_both_admission_paths():
    disabled = ResolutionUser(id="u", enabled=False, verified=True)
    for facts in (
        _base(identity=ResolutionIdentity(found=True, user=disabled)),
        _base(email_user=disabled),
    ):
        decision = resolve_account_decision(facts)
        assert (decision.action, decision.code) == (ACTION_REJECT, ACCOUNT_DISABLED), facts


def test_account_not_verified_forced_on_both_admission_paths():
    unverified = ResolutionUser(id="u", enabled=True, verified=False)
    for facts in (
        _base(identity=ResolutionIdentity(found=True, user=unverified)),
        _base(email_user=unverified),
    ):
        decision = resolve_account_decision(facts)
        assert (decision.action, decision.code) == (ACTION_REJECT, ACCOUNT_NOT_VERIFIED), facts


def test_membership_suspended_forced_on_both_admission_paths():
    suspended = ResolutionUser(id="u", enabled=True, verified=True, membership_suspended=True)
    for facts in (
        _base(identity=ResolutionIdentity(found=True, user=suspended)),
        _base(email_user=suspended),
    ):
        decision = resolve_account_decision(facts)
        assert (decision.action, decision.code) == (ACTION_REJECT, MEMBERSHIP_SUSPENDED), facts


def test_account_gates_outrank_the_membership_gate():
    """A disabled or unverified account reports its own stronger code first."""
    disabled_and_suspended = ResolutionUser(
        id="u", enabled=False, verified=True, membership_suspended=True
    )
    decision = resolve_account_decision(
        _base(identity=ResolutionIdentity(found=True, user=disabled_and_suspended))
    )
    assert (decision.action, decision.code) == (ACTION_REJECT, ACCOUNT_DISABLED)

    unverified_and_suspended = ResolutionUser(
        id="u", enabled=True, verified=False, membership_suspended=True
    )
    decision = resolve_account_decision(
        _base(identity=ResolutionIdentity(found=True, user=unverified_and_suspended))
    )
    assert (decision.action, decision.code) == (ACTION_REJECT, ACCOUNT_NOT_VERIFIED)


def test_signup_disabled_forced_when_self_signup_is_off():
    decision = resolve_account_decision(_base(signup_disabled=True))
    assert (decision.action, decision.code) == (ACTION_REJECT, SIGNUP_DISABLED)


def test_signup_disabled_still_admits_existing_accounts():
    """Only account creation is refused — existing users keep signing in."""
    decision = resolve_account_decision(_base(signup_disabled=True, email_user=OK_USER))
    assert decision.action == ACTION_AUTO_LINK
    assert decision.user_id == OK_USER.id
