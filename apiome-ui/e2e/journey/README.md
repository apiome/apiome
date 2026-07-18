# OLO end-to-end journey suite (OLO-7.4, #4226)

The MVP acceptance gate for the OAuth Login & Onboarding roadmap (#4184): one continuous
Playwright journey through login (all three providers, mocked), the account-resolution
invariants, first-tenant onboarding, Free-license limits, and the tenant switcher.

## What is real, what is mocked

| Piece | Journey uses |
| --- | --- |
| Next.js UI | Real, dedicated dev server on `:3100` |
| REST API + Postgres | Real (`docker compose up --wait` from the repo root) |
| GitHub / GitLab / Microsoft OAuth | Mocked — `e2e/support/mock-oauth-server.mjs` on `:8091` |

The app is pointed at the mock via the OLO-7.4 base-URL overrides
(`GITHUB_OAUTH_BASE_URL`, `GITHUB_API_BASE_URL`, `GITLAB_BASE_URL`,
`AZURE_AD_AUTHORITY_BASE_URL`) — see `e2e/journey/support/env.ts` for the full env the
server under test boots with. Production deployments never set these vars.

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

## Suite layout

- `oauth-onboarding-journey.spec.ts` — the six-step journey (serial).
- `support/env.ts` — ports, URLs, and the app-under-test environment.
- `support/mock-oauth.ts` — persona control client for the mock provider.
- `support/db.ts` — seeding (zero-tenant user, invite targets) and storage-layer
  invariant checks (no-duplicate-account, linked identities).
- `support/global-setup.ts` — fails fast when REST/Postgres are missing.

The REST-side twin of this journey is `apiome-rest/tests/test_journey_olo.py`.
