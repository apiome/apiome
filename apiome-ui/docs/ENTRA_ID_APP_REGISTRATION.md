# Entra ID App Registration — nOAuth Hardening (OLO-1.4, #4189)

Apiome does **not** trust the `email` claim in Microsoft Entra ID (azure) tokens by default. In
multi-tenant app registrations that claim is attacker-controlled: any admin of any tenant can put
an arbitrary address — including one belonging to your users — on the mutable `mail` attribute.
Trusting it for account auto-linking is the published **nOAuth** account-takeover pattern.

Sign-ins through the `azure` provider therefore classify the email as *verified* only when the
token carries acceptable evidence, evaluated by `resolveEntraEmailVerified`
(`apiome-ui/lib/auth/account-resolution.ts`, mirrored in
`apiome-rest/src/app/account_resolution.py`):

1. **`xms_edov` is true** — "email domain owner verified", the purpose-built optional claim
   (recommended; setup below), or
2. **`email_verified` is true** — the standard OIDC claim, when Entra emits it, or
3. **The email equals the token's `upn`** — member UPNs can only carry domains verified in the
   issuing tenant, which an attacker cannot forge for a domain they do not own. Guest UPNs
   (containing `#EXT#`) never qualify.

Anything else — including a token whose `xms_edov` or `email_verified` is explicitly `false` —
is treated as **unverified**, and the sign-in is rejected with the structured `unverified-email`
error instead of auto-linking or creating an account (OLO-1.3 policy step d).

## Required app-registration setup: enable `xms_edov`

Without this claim, legitimate users whose `mail` attribute differs from their UPN cannot be
auto-linked. Enable it on the app registration that backs `AZURE_AD_CLIENT_ID`:

1. In the [Entra admin center](https://entra.microsoft.com), open **App registrations** → your
   application → **Token configuration**.
2. Click **Add optional claim**, choose token type **ID**, and select **`xms_edov`** (listed as
   *Email domain owner verified*). Repeat for token type **Access** if the token is consumed
   server-side.
3. Accept the prompt to add the `email` claim / Microsoft Graph `email` permission if offered.

Alternatively, add it directly to the app manifest under `optionalClaims`:

```json
{
  "optionalClaims": {
    "idToken": [{ "name": "xms_edov", "essential": false }]
  }
}
```

Entra emits the claim as a boolean (or `0`/`1`); the resolver accepts both encodings.

## Verifying the setup

Sign in with a test account whose email domain is verified in its tenant and confirm the id token
(e.g. via [jwt.ms](https://jwt.ms)) contains `"xms_edov": true`. The claim-matrix behaviour is
unit-tested in `apiome-ui/tests/entra-email-verification.test.ts` and
`apiome-rest/tests/test_entra_email_verification.py`.

## References

- Descope, ["nOAuth: How Microsoft OAuth Misconfiguration Can Lead to Full Account Takeover"](https://www.descope.com/blog/post/noauth)
- Microsoft, [Optional claims reference — `xms_edov`](https://learn.microsoft.com/en-us/entra/identity-platform/optional-claims-reference)
- Microsoft, [Migrate away from using email claims for user identification or authorization](https://learn.microsoft.com/en-us/entra/identity-platform/migrate-off-email-claim-authorization)
