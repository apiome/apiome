# Portal readers — reader sign-in for Browse (PCX-1.1, #5889)

A **reader** reads a tenant's published APIs in Browse without being a member of its workspace. A reader is an
ordinary `users` row; a `portal_memberships` row (apiome-db V378) makes them a reader of one tenant. Readers sign
in with a **magic link** and hold a **reader session**.

## Flow

```mermaid
sequenceDiagram
  participant R as Reader's browser
  participant B as apiome-browse
  participant REST as apiome-rest
  R->>REST: POST /v1/portal/acme/auth/magic-link {email, return_to}
  REST-->>R: 202 (always)
  REST-)R: email: <browse>/portal/auth/exchange?tenant=acme&token=pml_…
  R->>B: GET /portal/auth/exchange?tenant=acme&token=…
  B->>REST: POST /v1/portal/acme/auth/exchange {token} (User-Agent forwarded)
  REST-->>B: {session_token, expires_at, return_to, reader}
  B-->>R: Set-Cookie apiome_reader_session (HttpOnly; SameSite=Lax), redirect to return_to
  B->>REST: GET /v1/portal/acme/auth/me  (Authorization: Reader prs_…)
```

The magic-link request is sent **from the reader's browser**, so the per-address budget sees the reader's own
address. The exchange is server-to-server so the session token only ever lives in an `HttpOnly` cookie.

## Endpoints (tag `portal-auth`)

| Route | Answer |
|---|---|
| `POST /v1/portal/{tenant}/auth/magic-link` | `202` always for well-formed input; `422` malformed email / `return_to`; `429 portal-rate-limited` |
| `POST …/auth/exchange` | `200` session grant; `400 portal-token-invalid`; `410 portal-token-used` / `portal-token-expired` |
| `POST …/auth/sign-out` | `204`, idempotent |
| `GET …/auth/me` | `200` reader profile; `401 portal-session-invalid` |

## Rules

- **One person, one user, one membership.** A new address gets a password-less user (when the installation
  sign-up policy, `app.signup_policy`, allows new accounts) and an `invited` membership; repeats reuse both. The
  first exchange activates the membership and marks the user verified.
- **Never verify someone else's password.** The exchange sets `users.verified` only on a password-less account
  (no `users.password`, no Better Auth `credential` row with a password). An unconfirmed workspace sign-up that
  holds a password stays unverified, so a stranger who signed up with the address cannot have it unlocked when its
  real owner uses a reader link (account pre-hijacking; the RC6 rule `redeemVerificationToken` enforces).
- **Secrets are hashed.** Magic links: bcrypt + lookup prefix (`pml_<16 hex>.<48 hex>`, 69 bytes — inside
  bcrypt's 72-byte window). Sessions: SHA-256 of 256 random bits (`prs_…`), found through a unique index.
- **Burn once.** The exchange verifies the hash, then burns the token with a conditional `UPDATE`.
- **Revocation applies on the next request.** Every session read re-checks the session, membership and user.
- **Never a REST credential elsewhere.** `validate_authentication` / `validate_session_credentials` do not
  understand the `Reader` scheme. `resolve_optional_tenant_member_auth` (browse routes) checks the session and
  returns the public slice; PCX-1.3 widens it. `tests/test_portal_reader_rest_refusal.py` sweeps every `GET`.
- **Audit** (`apiome.access_audit`, source `portal`): `portal.reader.enrolled`, `portal.reader.signed_in`,
  `portal.reader.session_revoked`. Metadata only; an audit failure never fails sign-in.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `APIOME_PUBLIC_BROWSE_URL` | — | Browse root the magic link points at |
| `SENDGRID_API_KEY`, `EMAIL_FROM` | — | Mail; unset → no mail is sent (a warning is logged, never the link) |
| `APIOME_PORTAL_MAGIC_LINK_RATE_LIMIT_EMAIL_PER_MINUTE` | 3 | Per tenant + address |
| `APIOME_PORTAL_MAGIC_LINK_RATE_LIMIT_IP_PER_MINUTE` | 10 | Per client address |
| `APIOME_PORTAL_READER_SESSION_TTL_HOURS` | 168 | Session lifetime |

Code: `app/portal_auth.py` (vocabulary, tokens), `app/portal_auth_store.py` (rules + SQL repository),
`app/portal_auth_routes.py`, `app/portal_mail.py` (the `ReaderMailer` seam PCX-3.1 replaces).
