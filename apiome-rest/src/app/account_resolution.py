"""Account-resolution & auto-link policy — REST-side parity (OLO-1.3, #4188).

This module is the Python mirror of the TypeScript resolution engine
(``apiome-ui/lib/auth/account-resolution.ts``). One ordered, provider-gated policy decides what
happens when an OAuth identity arrives, so the NextAuth callbacks and the REST signup /
provisioning path (OLO-4.3) can never drift apart:

  0. While signed in, "link another provider" attaches the identity to the session user
     regardless of the provider email (explicit user intent).
  a. A known ``(provider, provider_user_id)`` identity signs in the user it is bound to.
  b. Else a **verified** provider email matching an existing user auto-links the identity to that
     user and signs in (the Auth.js ``allowDangerousEmailAccountLinking`` guidance, implemented
     explicitly so the policy is provider-gated and auditable).
  c. Else a verified email with no matching user creates the account (routed via onboarding).
  d. An unverified email is rejected with the stable ``unverified-email`` code — auto-linking or
     account creation on an unverified address is an account-takeover vector (nOAuth advisory).

The policy function is pure (no I/O): callers gather the facts into a :class:`ResolutionInput`
and act on the returned :class:`ResolutionDecision`. Any behavioural change here MUST be made in
the TypeScript engine as well (and vice versa); both sides are covered by the same property-test
matrix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, FrozenSet, Mapping, Optional

from .database import normalize_email

# --- Stable machine-readable rejection codes (pre-seeds the OLO-1.5 error contract). ---

#: The provider could not prove the email address is verified — never auto-link or sign up.
UNVERIFIED_EMAIL = "unverified-email"
#: The provider shared no email address at all.
EMAIL_REQUIRED = "OAuthEmailRequired"
#: The OAuth response carried no stable provider user id.
PROFILE_INCOMPLETE = "OAuthProfileIncomplete"
#: The resolved user account is disabled (or its identity points at a deleted user).
ACCOUNT_DISABLED = "account-disabled"
#: The resolved user account has not completed its own email verification.
ACCOUNT_NOT_VERIFIED = "account-not-verified"

#: Providers whose ``email_verified`` evidence is accepted for auto-link / account creation.
#: The policy is deliberately provider-gated: any provider outside this set is treated as
#: unverified no matter what its profile claims. ``azure`` is pre-listed for OLO-2.x but its
#: claims are additionally subject to the nOAuth hardening rules (OLO-1.4) before
#: ``email_verified`` may be set true.
AUTO_LINK_TRUSTED_PROVIDERS: FrozenSet[str] = frozenset({"github", "gitlab", "azure"})

# --- Decision vocabulary ---

#: Attach the identity to the signed-in session user (explicit link intent).
ACTION_LINK_TO_SESSION = "link-to-session"
#: Sign in the user already bound to this identity (policy step a).
ACTION_SIGN_IN = "sign-in"
#: Link this identity to the verified-email-matching user, then sign in (policy step b).
ACTION_AUTO_LINK = "auto-link"
#: No account exists for this verified email — create user + identity via onboarding (step c).
ACTION_SIGNUP = "signup"
#: Refuse the sign-in with the stable error code in ``code`` (policy step d and account gates).
ACTION_REJECT = "reject"


@dataclass(frozen=True)
class ResolutionUser:
    """The user-account facts the policy needs to admit or refuse a sign-in.

    Attributes:
        id: The user's primary key.
        enabled: Account switch — disabled accounts never authenticate.
        verified: The account's own email-verification flag (``apiome.users.verified``).
    """

    id: str
    enabled: bool = True
    verified: bool = True


@dataclass(frozen=True)
class ResolutionIdentity:
    """The ``(provider, provider_user_id)`` binding, when one exists.

    Attributes:
        found: True when an identity row exists for the pair.
        user: The bound user, or None when the row points at a user that no longer resolves
            (soft-deleted) — a dangling identity, which is refused.
    """

    found: bool = False
    user: Optional[ResolutionUser] = None


@dataclass(frozen=True)
class ResolutionInput:
    """Pre-gathered facts :func:`resolve_account_decision` decides over.

    Attributes:
        provider: OAuth provider slug (``github`` | ``gitlab`` | ``azure`` | ...).
        provider_user_id: Stable provider-side user id from the OAuth response, if present.
        email: Provider email; canonicalized internally (see :func:`normalize_email`).
        email_verified: Whether the provider proved that email is verified (OLO-1.2/1.4).
        link_to_user_id: Session user id when this round-trip is an explicit "link another
            provider" action; None for a normal sign-in.
        identity: The existing identity binding, if any.
        email_user: Existing user whose canonical email equals ``email``, if any.
    """

    provider: str
    provider_user_id: Optional[str] = None
    email: Optional[str] = None
    email_verified: bool = False
    link_to_user_id: Optional[str] = None
    identity: ResolutionIdentity = field(default_factory=ResolutionIdentity)
    email_user: Optional[ResolutionUser] = None


@dataclass(frozen=True)
class ResolutionDecision:
    """What the policy decided; the caller turns this into effects.

    Attributes:
        action: One of the ``ACTION_*`` constants.
        user_id: The user to sign in / link to, for the actions that carry one.
        email: The canonical email to create the account with, for ``ACTION_SIGNUP``.
        code: The stable rejection code, for ``ACTION_REJECT``.
    """

    action: str
    user_id: Optional[str] = None
    email: Optional[str] = None
    code: Optional[str] = None


def _canonical_email(email: Optional[str]) -> Optional[str]:
    """Canonicalize an address defensively, returning None for empty/absent input."""
    if not isinstance(email, str):
        return None
    canonical = normalize_email(email)
    return canonical or None


def _read_claim_flag(value: Any) -> Optional[bool]:
    """Tri-state reading of a boolean-ish token claim.

    Returns True / False when the token explicitly asserts the value (boolean, ``"true"`` /
    ``"false"``, or the 0/1 forms Entra emits for optional claims), and None when the claim is
    absent or unrecognizable. The distinction matters because an explicit False is stronger
    evidence than a missing claim — it must veto, not merely fail to prove.

    Args:
        value: The raw claim value from the token/profile.

    Returns:
        True, False, or None (absent/unrecognized).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        if value == 1:
            return True
        if value == 0:
            return False
        return None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1"):
            return True
        if normalized in ("false", "0"):
            return False
    return None


#: Minimal email shape gate for the UPN rule: ``local@domain.tld``, no whitespace.
_EMAIL_SHAPE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

#: Sentinel distinguishing "caller did not supply email_in_use" from an explicit None.
_UNSET: Any = object()


def resolve_entra_email_verified(
    profile: Optional[Mapping[str, Any]],
    account: Optional[Mapping[str, Any]] = None,
    email_in_use: Optional[str] = _UNSET,
) -> bool:
    """Entra ID (azure) verified-email evidence — the nOAuth hardening rules (OLO-1.4, #4189).

    Mirror of ``resolveEntraEmailVerified`` in ``apiome-ui/lib/auth/account-resolution.ts`` —
    any behavioural change here MUST be made there as well.

    Entra ID's ``email`` claim is attacker-controlled in multi-tenant app registrations: any
    tenant admin can set an arbitrary address on the mutable ``mail`` attribute (the published
    **nOAuth** account-takeover pattern), so for ``azure`` the generic ``email_verified`` handling
    is not enough. The email is treated as verified only when the token carries acceptable
    evidence:

      - ``xms_edov`` ("email domain owner verified") — the optional claim the app registration
        must request — is explicitly true, or
      - ``email_verified`` is explicitly true, or
      - the email equals the token's ``upn`` claim: member UPNs (no ``#EXT#`` guest marker) can
        only carry domains verified in the issuing tenant, which an attacker cannot forge for a
        domain they do not own.

    Fail-closed rules: an explicitly-false ``xms_edov`` or ``email_verified`` claim vetoes
    everything (a contradictory token is never trusted), claim-based evidence only attests the
    token's own ``email`` claim (never a different address the caller ended up with), and anything
    unrecognized resolves to unverified.

    Args:
        profile: The OIDC profile / id-token claims from the provider.
        account: Optional secondary claims source (fallback for ``xms_edov`` /
            ``email_verified``).
        email_in_use: The canonical address the sign-in will actually use, when the caller derived
            it from somewhere other than the profile's email claim; defaults to the profile's own
            email claim. Pass None explicitly to signal "no usable address" (always False).

    Returns:
        True only when the token proves the address is verified; False otherwise.
    """
    profile = profile or {}
    account = account or {}

    claimed_email = _canonical_email(profile.get("email"))
    email = claimed_email if email_in_use is _UNSET else _canonical_email(email_in_use)
    if not email:
        return False

    def claim(name: str) -> Optional[bool]:
        value = profile.get(name)
        if value is None:
            value = account.get(name)
        return _read_claim_flag(value)

    domain_owner_verified = claim("xms_edov")
    email_verified_claim = claim("email_verified")

    # An explicit negative claim is the strongest signal in the token — it vetoes every other rule.
    if domain_owner_verified is False or email_verified_claim is False:
        return False

    # Positive claims attest the token's own email claim, never a different address.
    if (domain_owner_verified is True or email_verified_claim is True) and claimed_email == email:
        return True

    # UPN rule: a member UPN's domain is enforced-verified in the issuing tenant. Guest UPNs
    # (marked ``#EXT#``) are rewritten onto the host tenant's domain and prove nothing.
    upn = profile.get("upn")
    if isinstance(upn, str) and "#ext#" not in upn.lower():
        canonical_upn = _canonical_email(upn)
        if canonical_upn and _EMAIL_SHAPE.match(canonical_upn) and canonical_upn == email:
            return True

    return False


def _rejection_for_user(user: Optional[ResolutionUser]) -> Optional[str]:
    """Shared gate refusing disabled / not-yet-verified accounts (or a dangling identity)."""
    if user is None or not user.enabled:
        return ACCOUNT_DISABLED
    if not user.verified:
        return ACCOUNT_NOT_VERIFIED
    return None


def resolve_account_decision(facts: ResolutionInput) -> ResolutionDecision:
    """Run the account-resolution policy over pre-gathered facts (pure — no I/O).

    Applies, in order: explicit link intent → (a) known identity → (d) unverified rejection →
    (b) verified-email auto-link → (c) verified-email signup. See the module docstring for the
    policy rationale.

    Args:
        facts: The resolution facts (see :class:`ResolutionInput`).

    Returns:
        The decision to execute. Never returns ``ACTION_SIGNUP`` when a user already exists for
        the email, and never admits (sign-in / auto-link / signup) an unproven email — the two
        acceptance invariants of OLO-1.3.
    """
    # 0. Explicit "link another provider" while signed in: the session is the proof of intent
    #    and ownership, so the provider email plays no role.
    if facts.link_to_user_id:
        return ResolutionDecision(action=ACTION_LINK_TO_SESSION, user_id=facts.link_to_user_id)

    # Without a stable provider user id the identity can be neither keyed nor safely linked.
    if not facts.provider_user_id:
        return ResolutionDecision(action=ACTION_REJECT, code=PROFILE_INCOMPLETE)

    # (a) Known identity → sign in its user. No email trust is required: the binding was
    #     established under this same policy (or by explicit linking).
    if facts.identity.found:
        rejection = _rejection_for_user(facts.identity.user)
        if rejection:
            return ResolutionDecision(action=ACTION_REJECT, code=rejection)
        assert facts.identity.user is not None  # narrowed by _rejection_for_user
        return ResolutionDecision(action=ACTION_SIGN_IN, user_id=facts.identity.user.id)

    # From here on the email is the only evidence: it must exist and be proven verified by a
    # provider trusted to assert that.
    email = normalize_email(facts.email) if facts.email else None
    if not email:
        return ResolutionDecision(action=ACTION_REJECT, code=EMAIL_REQUIRED)

    email_proven = facts.email_verified and facts.provider in AUTO_LINK_TRUSTED_PROVIDERS
    if not email_proven:
        # (d) Unverified email → structured rejection. Never auto-link, never create an account.
        return ResolutionDecision(action=ACTION_REJECT, code=UNVERIFIED_EMAIL)

    if facts.email_user is not None:
        # (b) Verified email matches an existing account → auto-link this identity and sign in.
        #     This is the invariant's teeth: a second account can never be created for this email.
        rejection = _rejection_for_user(facts.email_user)
        if rejection:
            return ResolutionDecision(action=ACTION_REJECT, code=rejection)
        return ResolutionDecision(action=ACTION_AUTO_LINK, user_id=facts.email_user.id)

    # (c) Verified email, no account → create user + identity (routed via onboarding/signup).
    return ResolutionDecision(action=ACTION_SIGNUP, email=email)
