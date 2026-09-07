# OLO end-to-end journey suite (OLO-7.4 #4226, rebuilt on Better Auth in OLO-10.13 #5008)

The MVP acceptance gate for the OAuth Login & Onboarding roadmap (#4184): one continuous
Playwright journey through login (all four providers, mocked), the account-resolution
invariants, first-tenant onboarding, Free-license limits, the tenant switcher, credentials
sign-in, and 2FA (TOTP + backup code).

The suite runs entirely on the **Better Auth engine** — the only engine since the OLO-10.14 cutover
(`support/env.ts`). Built as the OLO-10.13 acceptance gate for the migration, it covers the full auth
regression: credentials, all four OAuth providers, account linking, and 2FA.

## What is real, what is mocked

| Piece | Journey uses |
| --- | --- |
| Next.js UI | Real, dedicated dev server on `:3100`, on the Better Auth engine |
| REST API + Postgres | Real (`docker compose up --wait` from the repo root; V201 `two_factor` migration applied) |
| GitHub / GitLab / Microsoft / Google OAuth | Mocked — `e2e/support/mock-oauth-server.mjs` on `:8091` |

The app is pointed at the mock via the base-URL overrides
(`GITHUB_OAUTH_BASE_URL`, `GITHUB_API_BASE_URL`, `GITLAB_BASE_URL`,
`AZURE_AD_AUTHORITY_BASE_URL`, `GOOGLE_ISSUER`) — see `e2e/journey/support/env.ts` for the full
env the server under test boots with. Production deployments never set these vars.

## 2FA legs

Profile enrollment + `/login/2fa` UI shipped in OLO-9.13 (#5014). The journey suite still drives
Better Auth's `two-factor` HTTP endpoints directly over the browser context's session cookies
(stable acceptance gate), generating live TOTP codes with the dependency-free `support/totp.ts`
helper (RFC 6238, matching the plugin's SHA1/6-digit/30s defaults). Backup-code / trusted-device
UX remains OLO-9.14 (#5006).

## Running locally

```bash
# from the repo root — Postgres + migrations + REST must be up
docker compose up --wait

# from apiome-ui/
yarn test:e2e:journey
```

The Playwright config starts the mock provider server and the dedicated UI dev server
itself. Database connectivity comes from `DATABASE_URL` (env or `apiome-ui/.env`).

Runs are re-entrant: every email, slug, and provider-side id carries a per-run suffix,
so repeated runs against the same database never collide.

## Provider-config legs (OLO-8.9, #4975)

`provider-config-precedence.spec.ts` drives the OLO-EPIC-8 story end to end: an admin configures
GitHub credentials in `/admin/dashboard/settings`, the next sign-in uses them instead of `.env`,
removing the row falls back to `.env`, and the fallback still signs in. It asserts the `client_id`
on the outgoing authorization request — the only place the *effective* credentials are observable —
and asserts at the storage layer that the secret is stored as ciphertext, never plaintext.

It needs three variables that the rest of the suite does not, because they gate the **database**
config source. All three default to empty in `docker-compose.yml`, so the spec probes first and
**skips with the variable to set** rather than silently passing on `.env`:

| Variable | Where it must be set | Why |
| --- | --- | --- |
| `INTERNAL_SERVICE_TOKEN` | `apiome-ui/.env` **and** `apiome-rest/.env`, identical | Gates `GET /v1/internal/auth-providers/resolved`. Unset ⇒ `resolveProviderEnv` degrades to `env-only` and never reads the DB. |
| `ADMIN_SESSION_SECRET` | `apiome-ui/.env` **and** `apiome-rest/.env`, identical | REST re-verifies the signed `admin_session` the UI forwards; a mismatch 403s every admin save. `ADMIN_PASSWORD` is the fallback derivation on both sides. |
| `AUTH_CONFIG_ENC_KEY` | `apiome-rest/.env` (base64, 32 bytes) | The KEK that seals stored client secrets. Absent ⇒ writing a secret returns `encryption_not_configured`. |

`ADMIN_PASSWORD` (in `apiome-ui/.env`) is what the spec signs in to the portal with.

The spec also pins `AUTH_PROVIDER_CONFIG_CACHE_TTL_MS=5000` — the resolver's clamped floor — so an
admin edit reaches the login path within a bounded wait instead of the 30s default. It runs last
(alphabetically) and clears its `auth_provider_config` row before *and* after: that table is
**global**, so a leaked row would change which credentials every other spec signs in with.

## Suite layout

- `oauth-onboarding-journey.spec.ts` — the eleven-step journey (serial): four OAuth providers,
  invariants, onboarding, license, switcher, credentials sign-in, and the 2FA legs.
- `provider-config-precedence.spec.ts` — the OLO-8.9 DB-over-`.env` provider-config story (above).
- `support/env.ts` — ports, URLs, and the app-under-test environment (the four provider mock
  overrides, plus the OLO-8.9 database-config-source variables).
- `support/provider-config.ts` — the OLO-8.9 readiness probe, the resolved-endpoint poller, and the
  authorization-request `client_id` capture.
- `support/mock-oauth.ts` — persona control client for the mock provider.
- `support/db.ts` — seeding (zero-tenant user, credential user, invite targets) and storage-layer
  invariant checks (no-duplicate-account, linked identities, 2FA state).
- `support/totp.ts` — dependency-free RFC 6238 TOTP generator for the 2FA login legs.
- `support/global-setup.ts` — fails fast when REST/Postgres are missing.

The REST-side twin of this journey is `apiome-rest/tests/test_journey_olo.py`.
