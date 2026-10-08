# DEMONSTRATION — OLO-EPIC-8: Database-driven auth provider configuration

> **Written ahead of the recording.** Routes, control labels and outputs below come from the
> epic's acceptance criteria, not from a running build. Walk it once against the shipped UI and
> correct this file before you record.

| | |
|---|---|
| Epic | [OLO-EPIC-8 #4966](https://github.com/apiome/apiome/issues/4966) · umbrella [OLO #4184](https://github.com/apiome/apiome/issues/4184) |
| Wave | 0 — the last leaf before the OLO tree closes |
| Closing ticket | [OLO-8.9 · Provider-config e2e + parity tests #4975](https://github.com/apiome/apiome/issues/4975) |
| Also shown | 8.1 signed admin cookie · 8.3 secret encryption · 8.5 DB↔env merge · [8.8 #4974](https://github.com/apiome/apiome/issues/4974) config validation |
| Runtime | ~7 min, plus 10 min prep |
| Audience | anyone who has waited on a deploy to add an SSO provider |
| The one beat | **A new SSO provider goes live without a deploy, a restart, or a secret in a repo.** |

---

## Run sheet

| # | Act | The beat it lands | Time |
|---|---|---|---|
| 1 | The old way | Adding a provider meant editing `.env` and redeploying. | 0:45 |
| 2 | Configure it in the admin UI | A form. Thirty seconds. | 1:30 |
| 3 | Sign in with it — no restart | The running server picked it up per-request. | 1:15 |
| 4 | Try to read the secret back | You can't. Neither can we. | 1:00 |
| 5 | Delete the row | It falls back to `.env` instead of locking everyone out. | 1:30 |
| 6 | Forge the admin cookie | Fails closed. | 1:00 |

---

## PREP — before anyone is watching (~10 min)

**DO** — Start the stack from the repo root.

```bash
yarn dev
```

**DO** — Confirm you have a mock OAuth provider to point at. The OLO-7.4 journey harness ships
one; the e2e suite in [#4975](https://github.com/apiome/apiome/issues/4975) drives the same
harness. Using a real GitHub OAuth app on stage is a bad trade — the redirect leaves your
machine and the failure modes are not yours.

**DO** — Put **one** provider in `apiome-rest/.env` so Act 5's fallback has somewhere to land.
Leave a second provider *absent* from `.env` — that is the one you configure on camera in Act 2.

**DO** — REST reads `.env` once at import. After any edit:

```bash
touch apiome-rest/src/app/main.py
```

**DO** — Log in as a platform administrator and park on <http://localhost:3000/admin/dashboard>.

> If the admin console 403s, REST is missing its admin secret — a `.env` problem, not a
> permissions problem. Fix it in prep; it is not recoverable on stage.

**DO** — Full dry run, then reset: delete the provider row you created.

---

## ACT 1 — The old way (0:45)

*Establish the cost before you remove it.*

**DO** — Show `apiome-rest/.env` on screen. Scroll the provider block.

**SAY**

> This is how most platforms configure single sign-on. A provider is a set of environment
> variables. Adding one means a code change, a secret in your deployment pipeline, a restart,
> and — if you are a hosted product — a deploy for *every* customer who wants a provider you
> don't already ship.
>
> Watch what that becomes.

---

## ACT 2 — Configure a provider in the admin UI (1:30)

**DO** — Browse to <http://localhost:3000/admin/dashboard/settings> → **Auth providers**.

**DO** — Click **Add provider**. Choose the provider kind. Fill in client ID, client secret,
issuer/discovery URL, and the scopes.

**DO** — *Before* saving, put a deliberate typo in the discovery URL and click **Save**. The
form rejects it with a specific message — that is [#4974](https://github.com/apiome/apiome/issues/4974)
doing its job.

**DO** — Fix the URL. Save. The provider appears in the list, enabled.

**SAY**

> Client ID, secret, issuer, scopes. That's it.
>
> And notice it refused the bad discovery URL before storing it. Configuration validation is the
> difference between a provider that doesn't work and a login page that is *down* — because a
> broken provider is still a button users will click.

---

## ACT 3 — Sign in with it, with no restart (1:15)

**DO** — Open a private window. Go to <http://localhost:3000/login>.

**DO** — *Pause on the login page.* The new provider's button is there. Nothing was restarted.

**DO** — Complete the sign-in against the mock provider. Land in the tenant.

**SAY**

> No restart. No deploy. The server resolved that provider on this request, from the database.
>
> That is the whole epic in one screen: provider configuration became data instead of
> deployment. A customer who needs Okta on Tuesday gets Okta on Tuesday.

---

## ACT 4 — Try to read the secret back (1:00)

**DO** — Return to the admin provider list. Open the provider you created. The secret field shows
a masked placeholder and a **Rotate** action — there is no reveal.

**DO** — Query it directly. Show the row's secret column is ciphertext, not the value you typed.

```bash
psql -c "select provider_kind, client_id, left(client_secret_encrypted::text, 40) from apiome.auth_providers;"
```

**SAY**

> Write-only. The API will not return it, the UI will not show it, and what is on disk is
> ciphertext.
>
> You can rotate it. Nobody — including a support engineer with database access — can read it
> back out. If a secret can be displayed, it will eventually be displayed in a screenshot.

---

## ACT 5 — Delete the row (1:30)

*The beat that makes this safe to adopt.*

**DO** — In the admin UI, delete the **`.env`-backed** provider's database row (the one from
prep — the one that also exists in the environment file).

**DO** — Reload <http://localhost:3000/login>. The provider button is **still there**.

**DO** — Sign in with it. It works.

**SAY**

> The database row is gone and that provider still works — because it is also in `.env`, and the
> environment is the fallback layer.
>
> The precedence rule is: database first, environment second, and absent from both means the
> provider is not offered. Which means turning this feature on cannot break an existing
> deployment, and a bad row in the database is recoverable by deleting it rather than by an
> emergency deploy.
>
> That matrix — set, partially set, absent — is what [#4975](https://github.com/apiome/apiome/issues/4975)
> pins with tests, so it cannot regress quietly. And it *would* regress quietly. That is exactly
> the kind of behaviour nobody notices until a customer cannot log in.

---

## ACT 6 — Forge the admin cookie (1:00)

**DO** — In dev tools, tamper with the signed admin cookie — change one character of the payload.

**DO** — Reload the admin console. Rejected. Not a partial view, not a degraded page — refused.

**SAY**

> Everything you just saw is reachable only by a platform administrator, and that check is a
> signature, not a flag in a cookie anyone can flip.
>
> A tampered cookie fails closed. It doesn't fall back to a lesser role, and it doesn't
> half-render an admin page. That test is in the suite too.

---

## RESCUE — when it goes wrong on stage

**The new provider's button doesn't appear on the login page**
The provider is saved but not enabled, or the login page cached the registry.
*On stage:* hard-reload the login page. If it is still missing, check the enabled toggle — do
not debug the registry live.

**The mock OAuth redirect fails**
The callback URL registered with the mock harness doesn't match the port you are running on.
*On stage:* skip to Act 4. Acts 4–6 don't need a completed sign-in.

**The admin console 403s**
REST is missing its admin secret.
*On stage:* nothing. This one ends the demo; catch it in prep.

**Act 5 locks you out instead of falling back**
The `.env` provider was never there, or REST didn't reload after you added it.
*On stage:* re-add the database row to restore the login page, and describe the fallback rather
than showing it.

---

## IF ASKED

**"Where does the encryption key live?"**
Application layer, same key management as the existing backup encryption — not in the database
holding the ciphertext. Rotating the key re-wraps the secrets without them ever being displayed.

**"Can a tenant admin configure their own provider, or only platform admins?"**
Platform administrators, in this epic. Tenant-scoped provider configuration is a separate
question — deliberately, because a tenant-configured identity provider changes who can claim an
email address, and that interacts with the one-account-per-email invariant the OLO roadmap is
built on.

**"What happens to users already signed in when a provider is deleted?"**
Existing sessions survive; the provider simply stops being offered for new sign-ins. Users whose
*only* identity is that provider cannot sign in again — which is why the unlink flow refuses to
remove the last sign-in method.

---

## Reference

| Surface | Where |
|---|---|
| Admin console | <http://localhost:3000/admin/dashboard> |
| Auth providers | <http://localhost:3000/admin/dashboard/settings> |
| Login page | <http://localhost:3000/login> |
| Roadmap | `private-suite/docs/roadmaps/ROADMAP_OAUTH_LOGIN_ONBOARDING.md` |
| Provider catalog roadmap | `private-suite/docs/roadmaps/ROADMAP_ADDITIONAL_SSO_PROVIDERS.md` |
