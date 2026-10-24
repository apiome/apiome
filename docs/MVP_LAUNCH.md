# MVP launch — the weekend plan

> **Written:** Saturday 2026-10-24 · **Status updated:** 2026-10-24 20:30 UTC (see the table below) ·
> **Target:** launch the first MVP (RC6) by **Sunday 2026-10-25**.
> **Scope:** RC6 as defined in [`RC6_OOE.md`](RC6_OOE.md) — Catalog, Projects (with Versions),
> sign-in and sign-up. Nothing else ships; held-back features stay behind
> `UNRELEASED_FEATURE_IDS`.
> **Source:** the RC6 validation of 2026-10-24 (GitHub issue states, CI runs on `main`, a local
> reproduction of each failure).

## Every step, in order

Work top to bottom. A **gate** row must be green before the next phase starts. Details for each
step are under [Order of execution](#order-of-execution); blockers **B1–B9** are described under
[Blockers](#blockers).

**Last updated:** Saturday 2026-10-24, 20:30 UTC.

**Status key:** ✅ Done · 🔄 In progress · ⏳ Waiting on you · ⬜ Not started

| Step | Status | When | What | Fixes | Owner | Done when | Notes |
| ---: | :---: | --- | --- | --- | --- | --- | --- |
| 1 | ✅ | Sat afternoon | Fix the apiome-ui image build (`--legacy-peer-deps` + pin `@better-auth/core` 1.6.25) | B1 | Claude | `apiome-ui-publish` pushes an image from `main` | #6259; publish green on `main` |
| 2 | ✅ | Sat afternoon | Install Chromium's system libraries on runner `server-node-5` | B2 | You | the a11y job gets past "Install Chromium's system libraries" | Done by you; visual parity ran green afterwards |
| 3 | ✅ | Sat afternoon | Raise the RC6-H6 timing ceilings for the CI runner | B3 | Claude | `apiome-ui.yml` green on `main` | #6259 (ceilings) and #6261 (5 s Testing Library wait for every suite) |
| 4 | 🔄 | Sat afternoon | Replace the hand-typed "53 formats" with the tagged count | B4 | Claude | `generate_format_counts.py --check` passes | Fixed in #6259 and passes locally; the nightly REST run on `main` is confirming it |
| 5 | 🔄 | Sat afternoon | **Gate 1:** re-run every workflow on `main` | — | You | all green | Runs queued behind the single self-hosted runner after #6260 and #6261 merged; `apiome-rest` green |
| 6 | ✅ | Sat evening | Move the 10 deferred issues out of `RC6`; update the milestone description | B9 | You approve, Claude applies | `RC6` has 0 open issues | Moved to the new `RC7` milestone; `RC6` has 0 open issues |
| 7 | ✅ | Sat evening | Decide lane E (recommended: "allow-lists only shrink" + a post-launch ticket) | B8 | You | decision recorded in `RC6_OOE.md` §4 | Accepted; §4 reworded; follow-up #6263 (RC7) |
| 8 | ✅ | Sat evening | Run `/security-review` on the sign-up and two-factor changes | B6 | Claude runs, You accept | findings recorded in `RC6_OOE.md` §7 | One HIGH finding (sign-up pre-hijacking), fixed in #6260; deploy V318 with it |
| 9 | ✅ | Sat evening | Bump What's new to RC6 | B7 | Claude (You pick the heading) | `WHATS_NEW.md` starts with RC6 | "Apiome 10-2026 RC6" |
| 10 | 🔄 | Sat evening | Bring `RC6_OOE.md` up to date; tick gate boxes as they turn green | — | Claude | §7 matches reality | §1, §4, §6 and §7 current; B6, B7, B9 ticked; Gate 1 and B5 still open |
| 11 | ⬜ | Sat night | Production host: DNS, firewall, secrets, **SendGrid email** | — | You | `PRODUCTION_DEPLOY.md` §2–§3 done | |
| 12 | ⏳ | Sat night | Serve the CLI installer at `get.apiome.dev` with a valid certificate | B5 | You (script ready) | the install one-liner works on a clean machine | Run `sudo deploy/get-apiome/get-apiome-installer.sh setup --email <ops address>` on the `get.apiome.dev` host: nginx site, Let's Encrypt cert, 15-min refresh from `main` |
| 13 | ⬜ | Sun morning | **Gate 2:** staging run of the full release journey | — | You | every step passes, recorded in `RC6_OOE.md` §7 | Include the new sign-up confirmation step (password) |
| 14 | ⬜ | Sun morning | Bug bar: both §7.1 queries return 0 | — | You | 0 and 0 | Both returned 0 on 2026-10-24 |
| 15 | ⬜ | Sun morning | Tag `RC6`; merge the release-notes PR it opens | — | You | RC6 post published | |
| 16 | ⬜ | Sun | First production deploy at `RC6` (migrate, bootstrap admin, backups) | — | You | `PRODUCTION_DEPLOY.md` §4–§6 done | Migrations through **V318** |
| 17 | ⬜ | Sun | **Gate 3:** production smoke test of the release journey | — | You | every step passes | |
| 18 | ⬜ | Sun | Set the sign-up policy to **open** (or **invite-only** for a soft launch) | — | You | strangers can sign up | |
| 19 | ⬜ | Sun onward | Triage new reports per `BETA_TRIAGE.md` | — | You | every report labelled the same day | |

## Where we are

All planned RC6 work is merged: every ticket in lanes A, B, D, E and H is closed (lane H, #6208–#6215,
on 2026-10-24). What stands between `main` and a launch is **not features**: it is a broken image
build, a CI runner, an installer host, and the release ceremony.

**Owner key:** **You** = needs access only you have (servers, DNS, secrets, sudo, GitHub admin
decisions). **Claude** = a code or docs change Claude can make and open as a PR.

## Blockers

| # | Status | Blocker | Why it blocks launch | Owner | Effort |
| --- | :---: | --- | --- | --- | --- |
| **B1** | ✅ | **The apiome-ui image does not build.** `apiome-ui-publish` has failed on every run since 2026-10-23 18:27 UTC: `npm install` in `apiome-ui/Dockerfile` resolves without a lockfile and hits `ERESOLVE` (`@better-auth/sso@1.6.25` pins `@better-auth/utils@0.4.2`; a fresh resolve now picks `@better-auth/core@1.7.12`, and a second, unrelated `vitest`/`@sveltejs/kit` peer conflict). | No UI image ⇒ nothing to deploy | Claude | 30 min |
| **B2** | ✅ | **The self-hosted runner `server-node-5` cannot start Chromium** (system libraries missing, no passwordless sudo). The accessibility gate, the visual-parity harness and the Catalog → Project journey (RC6-H1) all fail before running a test. | The release gate's journey and a11y checks cannot go green | You | 5 min |
| **B3** | ✅ | **Two of the RC6-H6 timing tests fail on the CI runner** (`tests/rc6-list-budgets-*.test.tsx`): the runner is ~10× slower than a laptop, so a 1 s ceiling for filter/sort trips (1.0–1.4 s measured). The exact guard (one page of rows mounted) passes. | `apiome-ui.yml` is red | Claude | 15 min |
| **B4** | 🔄 | **The nightly REST suite fails its format-count check**: `apiome-docs/docs/ship/export-a-spec.md:48` hand-types "**53 formats**" (from #6211). | `apiome-rest-test.yml` is red | Claude | 10 min |
| **B5** | ⬜ | **`https://get.apiome.dev` does not serve the CLI installer.** DNS points at the `apiome.dev` host, whose certificate is for `ai-dev.apiome.dev` only (TLS fails); plain HTTP returns 404; the production `Caddyfile` has no `get.` site. | Lane D's exit criterion and every "install the CLI" instruction in the docs fail | You (Claude can write the Caddy block) | 30 min |
| **B6** | ✅ | **No recorded `/security-review`** of the sign-up and two-factor changes (SGN-1.1…1.5, TFA-1.1…1.4) — a release-gate item. | Release gate | Claude runs it, You accept | 1 h |
| **B7** | ✅ | **What's new still says "Apiome 08-2026 RC5".** | Release gate | Claude (You pick the label) | 5 min |
| **B8** | ✅ | **Lane E's exit criterion is not met as written** ("gates … without allow-listed exceptions"): first-row allowances remain on Catalog (390 px) and Versions (710 px), and the disabled-button-without-reason ratchet still tolerates ~92 offenders on released screens. | Lane E is not formally exited | You decide | — |
| **B9** | ✅ | **The RC6 milestone still holds 10 deferred issues** (the §6 "move out" list) and its description still promises formats and the full HIVE pass. | Tagging `RC6` closes the milestone with open issues in it | You approve, Claude applies | 10 min |

**Not blockers** (fix after launch): the OpenAPI catalog push (`apiome-openapi.yml`) times out
uploading the 7.4 MB spec — it publishes the API document to the live catalog and does not gate a
deploy.

## Order of execution

Each step lists what "done" looks like. Do not start a phase until the previous phase's gate is green.

### Phase 1 — Saturday afternoon: make `main` green and buildable

1. **B1 — Fix the UI image build.** *(Claude)* In `apiome-ui/Dockerfile` use
   `npm install --legacy-peer-deps`, and add `"overrides": { "@better-auth/core": "1.6.25" }` to
   `apiome-ui/package.json` so better-auth stays on the version `yarn.lock` and every test ran
   against (verified: a lock-only resolve then lands `better-auth`, `@better-auth/core` and
   `@better-auth/sso` on 1.6.25 and `@better-auth/utils` on 0.4.2).
   **Done when:** `apiome-ui-publish` builds and pushes the image from `main`.
2. **B2 — Give the runner Chromium's libraries.** *(You)* On `server-node-5`:
   `sudo npx playwright install-deps chromium` (once).
   **Done when:** a re-run of `apiome-ui-a11y` gets past "Install Chromium's system libraries".
3. **B3 — Raise the RC6-H6 timing ceilings.** *(Claude)* In `apiome-ui/tests/helpers/list-budgets.ts`:
   first row 5,000 ms, filter and sort 3,000 ms (the row-count assertion stays the exact guard);
   update the table on `apiome-docs/docs/reference/visual-parity.md`.
   **Done when:** `apiome-ui.yml` passes on `main`.
4. **B4 — Tag the export count.** *(Claude)* Replace "**53 formats**" with the generated, tagged
   count (`<!--format-count:exportable-->` form) or reword without a number.
   **Done when:** `uv run python scripts/generate_format_counts.py --check` passes.
5. **Gate 1 — re-run CI on `main`** (`workflow_dispatch` where needed): `apiome-ui`,
   `apiome-ui-a11y`, `apiome-ui-visual-parity`, `e2e-catalog-journey`, `apiome-rest-test`,
   `apiome-docs`, `apiome-ui-publish`, `apiome-rest`. **All green**, or each red one explained here.

### Phase 2 — Saturday evening: release decisions and paperwork

6. **B9 — Apply the milestone moves.** *(You approve, Claude applies)* Move #5610, #5611, #5613,
   #5614, #5617, #5594, #5595, #5596, #4311, #4312 out of `RC6` (to `RC7` or `Future`); point the
   milestone description at `docs/RC6_OOE.md`.
   **Done when:** the `RC6` milestone has 0 open issues.
7. **B8 — Decide lane E.** *(You)* Recommended for this weekend: accept "allow-lists that only
   shrink" as the RC6 bar, reword the criterion in `RC6_OOE.md` §4, and file one post-launch ticket
   to retire the Catalog/Versions first-row allowances and the released-screen disabled-button
   offenders. The alternative (doing the clean-up now) is days of work across ~30 files.
8. **B6 — Security review.** *(Claude runs, You accept)* `/security-review` over the sign-up and
   two-factor merge range; fix anything rated high before launch, file the rest.
   **Done when:** findings are recorded in `RC6_OOE.md` §7 (or "none").
9. **B7 — What's new to RC6.** *(Claude; You pick the heading, e.g. "Apiome 10-2026 RC6")*
   **Done when:** `apiome-ui/public/WHATS_NEW.md` starts with the RC6 heading.
10. **Correct `RC6_OOE.md`.** *(Claude)* §1 table (lane H 0 open / 8 done), the status line, the
    release-gate checkboxes ticked as each item turns green.

### Phase 3 — Saturday night: production prerequisites

11. **Production host ready** *(You)* — [`docs/runbooks/PRODUCTION_DEPLOY.md`](runbooks/PRODUCTION_DEPLOY.md) §2–§3:
    - DNS `A`/`AAAA` for the app, API, MCP (and mock, if offered) domains, **before** first boot.
    - Firewall: 80/tcp, 443/tcp, 443/udp only.
    - Secrets in the secret manager and `.env` (from `docker-compose.prod.env.example` and
      `apiome-ui/.env.example`): `BETTER_AUTH_SECRET`, `BETTER_AUTH_URL`,
      `BETTER_AUTH_COOKIE_DOMAIN`, `APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS` (same in UI and
      REST), `AUTH_CONFIG_ENC_KEY`, `INTERNAL_SERVICE_TOKEN` (same in UI and REST),
      `ADMIN_PASSWORD`, `ACME_EMAIL`, the backup encryption key.
    - **Email for sign-up verification:** `SENDGRID_API_KEY` and `EMAIL_FROM` — without them
      email sign-up cannot verify an address.
    - Optional: `TURNSTILE_SITE_KEY` / `TURNSTILE_SECRET_KEY` (bot check on email sign-up),
      `APIOME_SERVER_ACTION_BODY_LIMIT` (default 25 MB, read at UI build time).
12. **B5 — Serve the installer.** *(You; Claude can write the block)* Add a `get.apiome.dev` site to
    `deploy/Caddyfile` (or the host that owns `apiome.dev`) that serves `apiome-cli/install.sh` —
    either the file itself or a redirect to
    `https://raw.githubusercontent.com/apiome/apiome/RC6/apiome-cli/install.sh` (the repository is
    public) — with a certificate that covers `get.apiome.dev`.
    **Done when:** `curl -fsSL https://get.apiome.dev -o get-apiome.sh && sh ./get-apiome.sh`
    installs the CLI on a clean machine.

### Phase 4 — Sunday morning: release candidate

13. **Staging run of the release journey** *(You, Claude can watch logs)* on a clean stack built
    from `main`: **sign up (email) → verify → onboard → enrol Authy → sign out → sign in with a
    code → `apiome login` → import a non-OpenAPI spec into the Catalog → convert it to a project →
    cut a version → publish → export through the Export dialog.** Also: a held-back URL shows
    *Not available yet*; a Viewer sees no write controls.
    **Done when:** every step passes; record the date and build in `RC6_OOE.md` §7.
14. **Bug bar** — both queries in [`RC6_OOE.md` §7.1](RC6_OOE.md#71-the-bug-bar) return 0
    (anything found in step 13 is filed, triaged, and fixed or downgraded with a reason).
15. **Tag `RC6`.** *(You)* `git tag RC6 <sha> && git push origin RC6`. The
    `apiome-release-notes` workflow opens a PR that closes the milestone, records the REST range
    in `apiome-docs/release-notes/releases.json` (check that RC5 is recorded too) and publishes
    the RC6 post. **Merge it.**

### Phase 5 — Sunday: launch

16. **First production deploy at `RC6`** *(You)* — `PRODUCTION_DEPLOY.md` §4 (staged, with the gated
    migration), §4.7 verify, §5 bootstrap the first tenant and admin, §6 backups wired in. Keep §8
    rollback at hand.
17. **Production smoke test** — repeat step 13 against production with a real email address.
18. **Open the doors** — in the admin console set the sign-up policy to **open** (or
    **invite-only** for a soft launch), with any allowed email domains.
19. **Watch** — [`docs/runbooks/BETA_TRIAGE.md`](runbooks/BETA_TRIAGE.md): new reports get `bug`,
    a severity and an area label (`catalog`, `versions`, `projects`) the same day.

### After launch (not this weekend)

- Retire the lane-E allowances and the released-screen disabled-button offenders (step 7).
- Fix the OpenAPI catalog push timeout (`apiome-openapi.yml`).
- Install apiome-ui's Docker dependencies from a lockfile instead of a fresh `npm install`, so a
  new upstream release cannot break the image again (B1's root cause).
- Next-plan work listed in `RC6_OOE.md` §5.

## Launch checklist

- [x] B1 UI image builds and publishes from `main` (#6259)
- [x] B2 runner can start Chromium
- [x] B3 UI unit suite fixes merged (#6259, #6261) — confirm on the next `main` run
- [ ] B4 nightly REST suite green (fix merged in #6259; run in progress)
- [ ] Gate 1: every workflow on `main` green
- [x] B9 `RC6` milestone has 0 open issues (deferred work → `RC7`)
- [x] B8 lane E decision recorded ("allow-lists only shrink", #6263)
- [x] B6 security review recorded — one HIGH finding (sign-up pre-hijacking), fixed
- [x] B7 What's new reads RC6 ("Apiome 10-2026 RC6")
- [ ] Production host, DNS, secrets and email ready
- [ ] B5 `get.apiome.dev` installs the CLI
- [ ] Staging release journey passes
- [ ] Bug bar returns 0
- [ ] `RC6` tagged; release-notes PR merged
- [ ] Production deployed, smoke-tested, sign-up policy set
