"""Account-resolution & auto-link policy tests — REST parity side (OLO-1.3, #4188).

Property-tests ``app.account_resolution.resolve_account_decision`` over the full matrix of
{new/known identity} x {new/known email} x {verified/unverified} x {signed-in link}, mirroring
``apiome-ui/tests/account-resolution.test.ts``. The two acceptance invariants:

  * a second account can never be created for an existing email, and
  * unverified emails never authenticate (nor sign up).
"""

import itertools

from app.account_resolution import (
    ACCOUNT_DISABLED,
    ACCOUNT_NOT_VERIFIED,
    ACTION_AUTO_LINK,
    ACTION_LINK_TO_SESSION,
    ACTION_REJECT,
    ACTION_SIGN_IN,
    ACTION_SIGNUP,
    AUTO_LINK_TRUSTED_PROVIDERS,
    EMAIL_REQUIRED,
    PROFILE_INCOMPLETE,
    UNVERIFIED_EMAIL,
    ResolutionIdentity,
    ResolutionInput,
    ResolutionUser,
    resolve_account_decision,
)

OK_USER = ResolutionUser(id="user-ok", enabled=True, verified=True)
DISABLED_USER = ResolutionUser(id="user-disabled", enabled=False, verified=True)
UNVERIFIED_USER = ResolutionUser(id="user-unverified", enabled=True, verified=False)

_IDENTITIES = {
    "none": ResolutionIdentity(found=False, user=None),
    "known": ResolutionIdentity(found=True, user=OK_USER),
    "known-disabled": ResolutionIdentity(found=True, user=DISABLED_USER),
    "known-unverified": ResolutionIdentity(found=True, user=UNVERIFIED_USER),
    "dangling": ResolutionIdentity(found=True, user=None),
}

_EMAIL_USERS = {
    "none": None,
    "match": OK_USER,
    "match-disabled": DISABLED_USER,
    "match-unverified": UNVERIFIED_USER,
}


def _matrix():
    """Yield every combination the policy can face for a trusted provider."""
    for identity_kind, email, email_user_kind, email_verified, link in itertools.product(
        _IDENTITIES, (None, "ada@example.com"), _EMAIL_USERS, (False, True), (None, "session-user")
    ):
        # A user can only match an email that exists.
        if email is None and email_user_kind != "none":
            continue
        yield ResolutionInput(
            provider="github",
            provider_user_id="prov-123",
            email=email,
            email_verified=email_verified,
            link_to_user_id=link,
            identity=_IDENTITIES[identity_kind],
            email_user=_EMAIL_USERS[email_user_kind],
        )


def test_matrix_covers_the_full_state_space():
    # 5 identities x (1 no-email + 4 email-user kinds) x 2 verified x 2 link intents.
    assert sum(1 for _ in _matrix()) == 5 * 5 * 2 * 2


def test_invariant_second_account_never_created_for_existing_email():
    for facts in _matrix():
        decision = resolve_account_decision(facts)
        if decision.action == ACTION_SIGNUP:
            assert facts.email_user is None, facts


def test_invariant_unverified_emails_never_authenticate():
    for facts in _matrix():
        if facts.link_to_user_id or facts.identity.found or facts.email_verified:
            continue
        decision = resolve_account_decision(facts)
        assert decision.action == ACTION_REJECT, facts
        expected = UNVERIFIED_EMAIL if facts.email else EMAIL_REQUIRED
        assert decision.code == expected, facts


def test_invariant_disabled_or_unverified_accounts_never_admitted():
    admitted_ids = {OK_USER.id, "session-user"}
    for facts in _matrix():
        decision = resolve_account_decision(facts)
        if decision.action in (ACTION_SIGN_IN, ACTION_AUTO_LINK, ACTION_LINK_TO_SESSION):
            assert decision.user_id in admitted_ids, facts


def test_invariant_link_intent_always_attaches_to_session_user():
    for facts in _matrix():
        if not facts.link_to_user_id:
            continue
        decision = resolve_account_decision(facts)
        assert decision.action == ACTION_LINK_TO_SESSION, facts
        assert decision.user_id == "session-user", facts


def test_invariant_known_healthy_identity_signs_in_regardless_of_email_state():
    for facts in _matrix():
        if facts.link_to_user_id or not facts.identity.found or facts.identity.user is not OK_USER:
            continue
        decision = resolve_account_decision(facts)
        assert decision.action == ACTION_SIGN_IN, facts
        assert decision.user_id == OK_USER.id, facts


def test_invariant_auto_link_exactly_when_verified_email_matches_healthy_account():
    for facts in _matrix():
        decision = resolve_account_decision(facts)
        should_auto_link = (
            not facts.link_to_user_id
            and not facts.identity.found
            and facts.email_verified
            and facts.email_user is OK_USER
        )
        assert (decision.action == ACTION_AUTO_LINK) == should_auto_link, facts


# --- Targeted branch coverage -------------------------------------------------


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


def test_known_identity_signs_in_without_email_trust():
    decision = resolve_account_decision(
        _base(email=None, email_verified=False, identity=ResolutionIdentity(found=True, user=OK_USER))
    )
    assert decision.action == ACTION_SIGN_IN
    assert decision.user_id == OK_USER.id


def test_verified_email_match_auto_links():
    decision = resolve_account_decision(_base(email_user=OK_USER))
    assert decision.action == ACTION_AUTO_LINK
    assert decision.user_id == OK_USER.id


def test_verified_new_email_routes_to_signup_with_canonical_address():
    decision = resolve_account_decision(_base(email="  Ada@Example.COM "))
    assert decision.action == ACTION_SIGNUP
    assert decision.email == "ada@example.com"


def test_unverified_email_rejected_with_stable_code():
    decision = resolve_account_decision(_base(email_verified=False, email_user=OK_USER))
    assert decision.action == ACTION_REJECT
    assert decision.code == UNVERIFIED_EMAIL


def test_untrusted_provider_verified_claim_treated_as_unverified():
    assert "bitbucket" not in AUTO_LINK_TRUSTED_PROVIDERS
    decision = resolve_account_decision(_base(provider="bitbucket", email_user=OK_USER))
    assert decision.action == ACTION_REJECT
    assert decision.code == UNVERIFIED_EMAIL


def test_dangling_identity_refused_as_disabled():
    decision = resolve_account_decision(_base(identity=ResolutionIdentity(found=True, user=None)))
    assert decision.action == ACTION_REJECT
    assert decision.code == ACCOUNT_DISABLED


def test_disabled_and_not_verified_accounts_refused_on_both_paths():
    for facts, code in (
        (_base(identity=ResolutionIdentity(found=True, user=DISABLED_USER)), ACCOUNT_DISABLED),
        (_base(identity=ResolutionIdentity(found=True, user=UNVERIFIED_USER)), ACCOUNT_NOT_VERIFIED),
        (_base(email_user=DISABLED_USER), ACCOUNT_DISABLED),
        (_base(email_user=UNVERIFIED_USER), ACCOUNT_NOT_VERIFIED),
    ):
        decision = resolve_account_decision(facts)
        assert decision.action == ACTION_REJECT, facts
        assert decision.code == code, facts


def test_missing_provider_user_id_rejected_as_incomplete_profile():
    decision = resolve_account_decision(_base(provider_user_id=None))
    assert decision.action == ACTION_REJECT
    assert decision.code == PROFILE_INCOMPLETE
