# RC1 Bug Burn-down Ledger

**Ticket:** RC1-4.2 / [#3621](https://github.com/apiome/apiome/issues/3621) · **Epic:** [#3607](https://github.com/apiome/apiome/issues/3607) · **Owner:** Release lead

The release gate for `v1.0.0-rc.1` asks two things of the defect list: **no open Critical or
High**, and **every deferred item documented**. This file is where both answers live. It is
the source the gate review reads, and the `sev:*` / `triage:*` labels on GitHub must agree with
it. Severity and triage states are defined in
[`docs/runbooks/BETA_TRIAGE.md`](../runbooks/BETA_TRIAGE.md) §3.

`scripts/tests/test_burn_down_ledger.py` checks this file's tables for consistency.

---

## 1. Gate status

**Gate status:** RED

**As of:** 2026-10-07

One High is open: [#4960](https://github.com/apiome/apiome/issues/4960). The gate stays red until
it is fixed and merged. There is no deferral for it: the release lead decided it ships fixed.

---

## 2. Open Critical / High

Every row blocks the tag. A row leaves this table when its fix merges and the issue closes. It is
never moved to §3 without the release lead's written decision, recorded in its own row there.

| Issue | Severity | Source | Next step | Blocks tag |
|---|---|---|---|---|
| [#4960](https://github.com/apiome/apiome/issues/4960) Encrypt OAuth tokens & PATs at rest | sev:high | OLO-7.3 auth threat-model review (#4225) | Fix under its own ticket (`/implement 4960`): encrypt on write in apiome-ui, decrypt on read in apiome-rest, with a migration and key-versioned sealing | yes |

---

## 3. Deferred

Each reason below matches the comment posted on the issue. A deferred item is not forgotten. It
carries `triage:deferred` and its original release label until the revisit target picks it up.

| Issue | Severity | Reason | Revisit | Constraint |
|---|---|---|---|---|
| [#4961](https://github.com/apiome/apiome/issues/4961) Public Suffix List for callback allowlist & cookie domain | sev:medium | Latent: the naive last-two-labels `registrableDomain()` is only exploitable when the app is served under a multi-label public suffix. RC deployments are self-hosted behind Caddy on `DEPLOY_*_DOMAIN` hosts, and no platform-preview host appears in `deploy/`. The review itself tags it v2. | v2 | Do not deploy the RC under a multi-label public suffix (`*.vercel.app`, `*.pages.dev`, `*.co.uk`, `github.io`). |
| [#4962](https://github.com/apiome/apiome/issues/4962) Account enumeration on legacy self-signup | sev:medium | The oracle is reachable in the RC (the login page always offers "Create one"), but it reveals membership of the waitlist `signup` table only, not of user accounts, and grants no access. The review tags it v2. | v2 | — |
| [#4963](https://github.com/apiome/apiome/issues/4963) Auth hygiene: link-route CSRF, login tenant fail-closed, identity-proxy scoping | sev:medium | Per the review, none of the three items is independently exploitable for account takeover. The link-intent cookie's user is server-derived. The login fail-open needs a concurrent membership-store outage *and* a tampered cookie. The proxy item is a confirm-and-test task. The review tags it v2. | v2 | — |

---

## 4. Beta intake

**Reports from the private beta ([#3620](https://github.com/apiome/apiome/issues/3620)) so far: 0.**

Beta reports are triaged daily per `BETA_TRIAGE.md` §4. When one is accepted as `sev:critical` or
`sev:high`:
1. add a row to §2;
2. set the gate status in §1 to RED.

A beta report deferred at medium or low gets a row in §3 with the same reason as its issue
comment.

---

## 5. Gate queries

Run these before the gate review and export them as files (the demo's prep list wants
artifacts, not live queries). Severity is queried across **all** issues, not only `beta`,
because the security follow-ups are not beta reports.

```bash
# Must both be empty, apart from the rows in §2, for the gate to go green
gh issue list --label sev:critical --state open
gh issue list --label sev:high --state open

# The deferred list. Every one must have a row in §3 and a reason comment.
gh issue list --label triage:deferred --state open --json number,title,labels,url

# Untriaged beta reports. Must be empty before the review.
gh issue list --label beta --label triage:new --state open
```
