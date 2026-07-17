"""Entra ID nOAuth hardening tests — REST parity side (OLO-1.4, #4189).

Exercises ``app.account_resolution.resolve_entra_email_verified`` over the claim matrix,
mirroring ``apiome-ui/tests/entra-email-verification.test.ts``. Entra's ``email`` claim is
attacker-controlled in multi-tenant app registrations (the published nOAuth account-takeover
pattern), so the resolver must accept only real evidence — ``xms_edov``, ``email_verified``, or
email == member UPN — and fail closed on everything else. Also proves the engine
(``resolve_account_decision``) rejects an azure identity whose email failed these rules.
"""

from app.account_resolution import (
    ACTION_REJECT,
    UNVERIFIED_EMAIL,
    ResolutionInput,
    ResolutionUser,
    resolve_account_decision,
    resolve_entra_email_verified,
)

# The nOAuth forgery: an attacker admins their own tenant and sets the victim's address on the
# mutable ``mail`` attribute. The token is otherwise legitimate — only the email is a lie.
FORGED_NOAUTH_TOKEN = {
    "sub": "attacker-sub",
    "oid": "11111111-2222-3333-4444-555555555555",
    "tid": "attacker-tenant-id",
    "email": "victim@corp.example.com",
    "upn": "attacker@attackertenant.onmicrosoft.com",
}

# Forgery variant: a guest (B2B) account whose UPN embeds the victim address as ``#EXT#``.
FORGED_GUEST_TOKEN = {
    "sub": "guest-sub",
    "email": "victim@corp.example.com",
    "upn": "victim_corp.example.com#EXT#@attackertenant.onmicrosoft.com",
}

# Legitimate sign-in from an app registration with the ``xms_edov`` optional claim enabled.
LEGIT_EDOV_TOKEN = {
    "sub": "member-sub",
    "email": "Ada@Corp.example.com",
    "upn": "ada@corp.example.com",
    "xms_edov": True,
}


class TestForgedTokensRejected:
    def test_noauth_forgery_is_unverified(self):
        assert resolve_entra_email_verified(FORGED_NOAUTH_TOKEN) is False

    def test_guest_ext_upn_proves_nothing(self):
        assert resolve_entra_email_verified(FORGED_GUEST_TOKEN) is False

    def test_explicit_false_xms_edov_vetoes_everything(self):
        assert (
            resolve_entra_email_verified(
                {"email": "ada@corp.example.com", "email_verified": True, "xms_edov": False}
            )
            is False
        )
        assert (
            resolve_entra_email_verified(
                {"email": "ada@corp.example.com", "upn": "ada@corp.example.com", "xms_edov": False}
            )
            is False
        )
        assert (
            resolve_entra_email_verified({"email": "ada@corp.example.com", "xms_edov": "false"})
            is False
        )

    def test_explicit_false_email_verified_vetoes_upn_rule(self):
        assert (
            resolve_entra_email_verified(
                {
                    "email": "ada@corp.example.com",
                    "upn": "ada@corp.example.com",
                    "email_verified": False,
                }
            )
            is False
        )

    def test_claims_only_attest_the_token_email(self):
        # The token verified its own email, but the sign-in is about to use another address.
        assert (
            resolve_entra_email_verified(
                LEGIT_EDOV_TOKEN, email_in_use="someone-else@corp.example.com"
            )
            is False
        )
        # An explicit None email-in-use means "no usable address" — always unverified.
        assert resolve_entra_email_verified(LEGIT_EDOV_TOKEN, email_in_use=None) is False

    def test_unrecognized_values_and_missing_email_fail_closed(self):
        assert resolve_entra_email_verified({"email": "a@b.co", "xms_edov": "yes"}) is False
        assert (
            resolve_entra_email_verified({"email": "a@b.co", "email_verified": "verified"})
            is False
        )
        assert resolve_entra_email_verified({"xms_edov": True}) is False  # evidence, no email
        assert resolve_entra_email_verified(None, None) is False
        assert resolve_entra_email_verified({}) is False

    def test_non_email_shaped_or_non_string_upn_never_matches(self):
        # No dot in the domain — not an email-shaped UPN.
        assert resolve_entra_email_verified({"email": "ada@localhost", "upn": "ada@localhost"}) is False
        assert resolve_entra_email_verified({"email": "ada@corp.example.com", "upn": 42}) is False


class TestLegitimateEvidenceAccepted:
    def test_xms_edov_true_in_all_emitted_forms(self):
        assert resolve_entra_email_verified(LEGIT_EDOV_TOKEN) is True
        assert resolve_entra_email_verified({"email": "a@b.co", "xms_edov": "true"}) is True
        assert resolve_entra_email_verified({"email": "a@b.co", "xms_edov": 1}) is True
        assert resolve_entra_email_verified({"email": "a@b.co", "xms_edov": "1"}) is True

    def test_email_verified_true(self):
        assert resolve_entra_email_verified({"email": "a@b.co", "email_verified": True}) is True
        assert resolve_entra_email_verified({"email": "a@b.co", "email_verified": "true"}) is True

    def test_claims_fall_back_to_the_account_object(self):
        assert resolve_entra_email_verified({"email": "a@b.co"}, {"xms_edov": True}) is True
        assert resolve_entra_email_verified({"email": "a@b.co"}, {"email_verified": True}) is True

    def test_email_equal_to_member_upn_case_insensitively(self):
        assert (
            resolve_entra_email_verified(
                {"email": "Ada@Corp.example.com", "upn": "ada@CORP.example.com"}
            )
            is True
        )

    def test_email_in_use_verifies_when_it_matches_the_attested_address(self):
        assert (
            resolve_entra_email_verified(LEGIT_EDOV_TOKEN, email_in_use="ada@corp.example.com")
            is True
        )
        # UPN rule attests the address in use even when the token carries no email claim.
        assert (
            resolve_entra_email_verified(
                {"upn": "ada@corp.example.com"}, email_in_use="Ada@corp.example.com"
            )
            is True
        )


class TestEngineIntegration:
    """The resolver's verdict feeds ``email_verified`` — a failed verdict must reject (1.3d)."""

    def test_forged_azure_sign_in_never_auto_links(self):
        victim = ResolutionUser(id="user-victim", enabled=True, verified=True)
        verdict = resolve_entra_email_verified(FORGED_NOAUTH_TOKEN)
        decision = resolve_account_decision(
            ResolutionInput(
                provider="azure",
                provider_user_id=FORGED_NOAUTH_TOKEN["oid"],
                email=FORGED_NOAUTH_TOKEN["email"],
                email_verified=verdict,
                email_user=victim,
            )
        )
        assert decision.action == ACTION_REJECT
        assert decision.code == UNVERIFIED_EMAIL

    def test_legitimate_azure_sign_in_auto_links(self):
        ada = ResolutionUser(id="user-ada", enabled=True, verified=True)
        verdict = resolve_entra_email_verified(LEGIT_EDOV_TOKEN)
        decision = resolve_account_decision(
            ResolutionInput(
                provider="azure",
                provider_user_id="member-oid",
                email=LEGIT_EDOV_TOKEN["email"],
                email_verified=verdict,
                email_user=ada,
            )
        )
        assert decision.action == "auto-link"
        assert decision.user_id == ada.id
