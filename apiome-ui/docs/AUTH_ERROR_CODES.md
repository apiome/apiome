# Structured Auth Error Contract (OLO-1.5, #4190)

Login failures are never free text: every rejection carries a **stable machine-readable code**
delivered to the login page as the NextAuth error redirect param:

```
/login?error=<code>
```

The login page maps each code to distinct user guidance. The codes below are a **public
contract** consumed by the login UX (OLO-3.2) and any future surface that needs to explain an
auth failure.

## Stability rules

- **Never change or reuse an existing code value.** Add a new code instead, and document it here.
- A code's *meaning* is fixed forever; its user-facing copy may be reworded.
- The same values are defined in both engines and must stay identical:
  - TypeScript: `AUTH_ERROR_CODES` in `apiome-ui/lib/auth/account-resolution.ts`
  - Python: module constants + `AUTH_ERROR_CODES` in `apiome-rest/src/app/account_resolution.py`
- User copy lives in `apiome-ui/src/app/login/auth-error-copy.ts` (`AUTH_ERROR_COPY`); every
  contract code must have an entry there.
- Redirects are built through `loginErrorRedirect()` in `account-resolution.ts` so the transport
  shape can never drift.

## Stable codes

| Code | Meaning | Emitted by |
|------|---------|-----------|
| `unverified-email` | The provider could not prove the sign-in email is verified; auto-link and signup are refused (nOAuth hardening, OLO-1.3(d)/1.4). | Resolution engine (both sides) |
| `identity-linked-elsewhere` | This `(provider, provider_user_id)` identity is already bound to a **different** user. | `linkExternalAccount` (`lib/db/helper.ts`), resolution engine auto-link fallback |
| `account-disabled` | The resolved user account is disabled (`users.enabled = false`), or the identity points at a deleted user. | Resolution engine, credentials sign-in |
| `membership-suspended` | The user's tenant membership is suspended (`tenant_users.status = 'suspended'`). | Resolution engine gate, via `ResolutionUser.membershipSuspended` / `membership_suspended` — populated by tenant-scoped sign-in surfaces (invitation acceptance, tenant selection; OLO-3.x/5.x). The plain login flow has no tenant context and does not set it. |
| `provider-not-configured` | The requested sign-in provider is not configured/supported on this deployment. | `signInForProvider` dispatch (`lib/auth/credentials.ts`) |
| `signup-disabled` | Self-signup is disabled on this deployment — the sign-up policy is `closed` (SGN-1.4), or no policy is stored and `AUTH_SIGNUP_DISABLED=true|1`. A new address is refused instead of routed to onboarding. | Sign-up policy gate: resolution engine step (c), OAuth sign-up completion, email sign-up |
| `signup-invite-only` | The sign-up policy is `invite_only` (SGN-1.4) and the address has no account. Invitations go to existing accounts, so an invited person signs in normally and never sees this. | Sign-up policy gate (same emitters as `signup-disabled`) |
| `signup-domain-not-allowed` | The sign-up policy is `open` with an allowed-email-domain list (SGN-1.4) and the address's domain is not on it. | Sign-up policy gate (same emitters as `signup-disabled`) |
| `account-not-verified` | The resolved account exists but has not completed its own email verification (`users.verified = false`). | Resolution engine, credentials sign-in |
| `provider-already-linked` | The user already has a different identity linked for this provider (link flow). | `linkExternalAccount` (`lib/db/helper.ts`) |
| `last-sign-in-method` | Unlink refused: the identity is the user's last remaining sign-in method — no other linked identity and no usable password (`users.password` empty) — so removing it would lock them out (OLO-2.4). | `unlinkExternalAccount` (`lib/db/helper.ts`) |
| `sign-in-failed` | Generic sign-in failure with no user-actionable detail; the `signIn` callback's defensive fallback when a provider yields no resolvable user. Kept generic so the redirect leaks no account existence signal (OLO-7.3). Renders the generic banner. | NextAuth `signIn` callback (`src/app/api/auth/[...nextauth]/route.ts`) |

## Enterprise SSO codes (EID-1.1, #5011)

Emitted by the SSO sign-in hooks (`lib/auth/sso-resolution.ts`, `SSO_ERROR_CODES`) for refusals the
resolution engine does not own; the engine's own codes above (`unverified-email`, `account-disabled`,
`identity-linked-elsewhere`, the sign-up policy codes …) apply to SSO sign-ins unchanged. Every
refusal is also written to `auth_events` with `provider = sso:<slug>`.

| Code | Meaning | Emitted by |
| --- | --- | --- |
| `sso-token-invalid` | The OIDC id token failed verification (signature, issuer, audience), was missing, or named another email. | `ssoAccountCreateBefore`; plugin failures on an OIDC provider |
| `sso-assertion-invalid` | The SAML response failed validation (signature, audience, timestamps, shape). | Plugin failures on a SAML provider (`ssoCallbackAfterHandler`) |
| `sso-assertion-replayed` | The SAML assertion had already been used. | Plugin `replay_detected` |
| `sso-binding-unsupported` | The IdP answered over HTTP-Artifact (`SAMLart`). | `ssoArtifactBeforeHandler` |
| `sso-discovery-failed` | The OIDC discovery document could not be read at sign-in. | Plugin `discovery_failed` |
| `sso-state-invalid` | The sign-in state was missing, expired or did not match. | Plugin `invalid_state` |
| `sso-provider-not-found` | No enabled provider with a verified domain covers the request. | SSO hooks; plugin `invalid_provider` |
| `sso-email-domain-mismatch` | The IdP asserted an email outside the domains verified for it. | `ssoUserCreateBefore`, `ssoAccountCreateBefore` |
| `sso-account-not-linked` | An account with the email exists but Better Auth could not link it. | Plugin `account_not_linked` |

## Pre-contract stable copy keys

These predate the kebab-case convention and keep their original values under the stability rule:

| Code | Meaning | Emitted by |
|------|---------|-----------|
| `OAuthEmailRequired` | The provider shared no email address at all. | Resolution engine |
| `OAuthProfileIncomplete` | The OAuth response carried no stable provider user id. | Resolution engine |

## Other codes the login page understands

Not part of the resolution contract, but they arrive on the same query param:

| Code | Source |
|------|--------|
| `AccessDenied`, `CredentialsSignin` | NextAuth built-ins |
| `TwoFactorInvalid` | TOTP second-step failure (OLO-9.13 #5014) |
| `OAuthAccountExists` | Signup flow (`lib/auth/oauth-signup-actions.ts`) |
| `SignupSessionExpired` | OAuth signup completion page (`src/app/signup/oauth/page.tsx`) |

Unknown codes fall back to a **safe generic banner** (`GENERIC_AUTH_ERROR` in
`auth-error-copy.ts`) — the page never breaks on a new code, and because the `?error=` value is
attacker-influenced it is **never echoed back into the page**. Every intentional emission should
still be mapped and documented.

## Rendering affordances (OLO-3.2, #4200)

## Sign-up abuse-guard codes (SGN-1.5, #5654)

Returned by the email sign-up actions (`lib/auth/email-signup-actions.ts`, `EMAIL_SIGNUP_CODES`)
and the sign-up intent route. Each refusal is also written to `auth_events` as a failed `sign_up`
row with `detail.guard` (`rate_limit` · `disposable_domain` · `captcha`); super-admins read them on
the System settings Sign-up card. A rate-limit refusal is recorded once per budget window.

| Code | Meaning | Emitted by |
| --- | --- | --- |
| `email-signup-rate-limited` | Too many sign-up or resend requests from this client (20 an hour) or emails to this address (3 an hour). | `startEmailSignup`, `resendSignupVerification` |
| `email-signup-disposable-domain` | The address is at a disposable email provider: the bundled list or the admin's extra blocked domains. Email sign-up only. | `startEmailSignup` |
| `email-signup-captcha-failed` | Turnstile is configured and the widget token was missing or Cloudflare did not confirm it (fails closed if Cloudflare cannot be reached). | `startEmailSignup` |
| `auth-rate-limited` | HTTP 429 from `POST /api/auth/signup-intent`: too many provider sign-ups started from this client (10 a minute). The only guard provider sign-up shares. | `src/app/api/auth/signup-intent/route.ts` |

Each copy entry may set `retry: true`, which renders a **"Try again"** link in the login banner
pointing back to a clean `/login` (error cleared, validated `callbackUrl` preserved). It is set
on codes the user can resolve outside Apiome and then retry (`unverified-email`,
`account-not-verified`, `OAuthEmailRequired`, `OAuthProfileIncomplete`, `SignupSessionExpired`,
and the generic fallback). Terminal states — `account-disabled`, `membership-suspended`,
`signup-disabled`, `signup-invite-only`, `signup-domain-not-allowed`, `provider-not-configured`,
link conflicts — deliberately offer none;
`CredentialsSignin` instead re-expands the credentials form (OLO-3.1).

## Configuration

| Variable | Effect |
|----------|--------|
| `AUTH_SIGNUP_DISABLED` | The **fallback** when no sign-up policy is stored (SGN-1.4): `true` or `1` reads as `closed`, any other value (or unset) as `open`. A policy saved on **System settings → Sign-up** wins over it. |
| `SIGNUP_POLICY_CACHE_TTL_SECONDS` | How long each server instance caches the effective sign-up policy (default `30`, clamped to 1–300). A policy change applies at once on the instance that saved it and within this window elsewhere. Read by apiome-ui and apiome-rest. |

## Tests forcing each code

- `apiome-ui/tests/auth-error-contract.test.ts` — value stability, an emission test per code, and
  copy coverage/distinctness.
- `apiome-ui/tests/login-error-rendering.test.tsx` — OLO-3.2 rendering: a banner snapshot per
  code, safe-generic fallback for unknown codes, and retry-affordance coverage.
- `apiome-ui/tests/account-resolution.test.ts`, `apiome-rest/tests/test_account_resolution.py` —
  the OLO-1.3 policy matrix.
- `apiome-rest/tests/test_auth_error_contract.py` — Python parity: values, set membership, and an
  emission test per engine-emitted code.
