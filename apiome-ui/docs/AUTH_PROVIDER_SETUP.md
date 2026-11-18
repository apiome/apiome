# Sign-in Provider Setup & Secrets Guide (OLO-7.2)

How to register the OAuth applications Apiome signs users in with (GitHub, GitLab,
Microsoft Entra ID, Google Workspace, Okta, Amazon Cognito, Keycloak, generic OIDC, Auth0, LINE, VK, WeChat, Atlassian, Bitbucket, Slack, LinkedIn, Discord, Salesforce, Notion, Figma, Linear, Dropbox, Zoom, Hugging Face, Vercel, Railway, HubSpot, Apple, Facebook, X / Twitter, Reddit, Spotify, Twitch, TikTok, Roblox, Kick), which
settings each provider needs, where those settings can live, and how boot-time validation reacts
when a provider is misconfigured.

The single source of truth for the provider list and each provider's config contract is the
provider registry: [`lib/auth/provider-registry.ts`](../lib/auth/provider-registry.ts)
(OLO-2.3). A provider is **enabled** only when *all* of its required fields resolve to a set,
non-blank value; clearing them all **cleanly disables** it everywhere at once (login button,
linked-accounts panel, Better Auth sign-in route). No code changes are needed either way.

## Config precedence — database first, `.env` fallback

Each required field can be supplied from two places, merged **field by field** on every login
(OLO-8.5/8.6):

| Rank | Source | Written from | Takes effect |
|---|---|---|---|
| **1** | `apiome.auth_provider_config` (server-global table, V196) | **Admin → System Configuration** (`/admin/dashboard/settings`) | at the **next login** — no restart |
| **2** | environment variables | `.env`, `docker-compose.env`, or your orchestrator's secret store | at the **next restart** |

One rule covers every case: **a stored value wins; an absent or blank stored value falls through to
the env var of the same name.** Consequences worth internalising:

- **No DB row** for a provider → it is governed entirely by env, exactly as before OLO-8.
- **A row with a `NULL`/blank field** → that field alone falls back to env. Rows are merged per
  field, not wholesale: a stored client id happily pairs with an env client secret.
- **`enabled = false`** pins the provider **off** even when env sets every var — the stored "off"
  is an explicit operator decision, so it removes the credentials from the merged view.
- **`enabled = NULL`** ("Use .env" in the admin screen) means enablement is derived the usual way:
  the provider is on when every required field resolves from either source.
- Forcing a provider **`enabled = true`** requires its client id *and* secret to be **stored in the
  database** — env values do not count toward that check, so an operator cannot enable a provider
  the DB alone could not serve.

### The env template is the fallback and the local-dev path

The provider variables in [`.env.example`](../.env.example) are **not** the primary configuration
surface for a deployment that uses the admin screen. Treat them as:

- the **local-dev path** — no database row, no admin login, no KEK needed; and
- the **fallback** for anything not stored in the database, including the bootstrap case where the
  admin screen itself is not yet usable.

A production deployment can legitimately leave every provider var unset and configure providers
entirely from Admin → System Configuration. It can equally run env-only and never create a row.
Both are supported; mixing them per field is supported too.

### Switching the database source on

The merge is only consulted when apiome-ui can read the decrypted config from apiome-rest, which is
gated by a shared service token:

| Variable | Where | Purpose |
|---|---|---|
| `INTERNAL_SERVICE_TOKEN` | apiome-ui **and** apiome-rest (identical value) | authorises `GET /v1/internal/auth-providers/resolved`, the login-time read path |
| `AUTH_CONFIG_ENC_KEY` | apiome-rest only | the KEK that seals/unseals stored client secrets — see [Encryption at rest](#encryption-at-rest-and-key-rotation-auth_config_enc_key) |
| `REST_API_BASE_URL` | apiome-ui (and Studio) | where the resolver reaches apiome-rest, read at **runtime** — set it in a container (e.g. `http://rest:8000/v1`), where `localhost` is the container itself. Unset ⇒ `NEXT_PUBLIC_REST_API_BASE_URL`, which is fixed when the image is built |
| `AUTH_PROVIDER_CONFIG_CACHE_TTL_MS` | apiome-ui | optional TTL (ms) of the in-process resolved-config cache; clamped to `[5000, 60000]`, default `30000` |

**Unset `INTERNAL_SERVICE_TOKEN` ⇒ the database layer is switched off entirely**: providers come
from env alone and anything saved in the admin screen has no effect on login. Because that is
indistinguishable from a dropped token, the server logs it **once at startup**:

```
[provider-config-resolver] INTERNAL_SERVICE_TOKEN is not set; sign-in providers are configured
from env only, and admin-screen provider config will have no effect
```

If the token *is* set but apiome-rest is unreachable or errors, sign-in **degrades to env** rather
than breaking (OLO-8.6) — see [Boot-time validation](#boot-time-validation) for how that affects
startup checks.

## Environment variable matrix

Every variable below is the **fallback** source for its field (rank 2 above). Providers whose
config is stored in the database need none of them set; see
[Config precedence](#config-precedence--database-first-env-fallback).

| Variable | Provider / scope | Required | Purpose |
|---|---|---|---|
| `BETTER_AUTH_URL` | all | Yes | Public base URL of the app; every OAuth callback URL below derives from it |
| `BETTER_AUTH_SECRET` | all | Yes | Shared signing secret for the Better Auth session and the downstream REST JWT (`openssl rand -base64 32`) |
| `SENDGRID_API_KEY` | 2FA email OTP | To enable email OTP | SendGrid API key used by `otpOptions.sendOTP` (OLO-9.50) |
| `EMAIL_FROM` | 2FA email OTP | To enable email OTP | Verified SendGrid sender (`addr@domain` or `Name <addr@domain>`) |
| `GITHUB_ID` | GitHub | To enable GitHub | OAuth app **Client ID** |
| `GITHUB_SECRET` | GitHub | To enable GitHub | OAuth app **Client secret** |
| `GITLAB_CLIENT_ID` | GitLab | To enable GitLab | Application **Application ID** |
| `GITLAB_CLIENT_SECRET` | GitLab | To enable GitLab | Application **Secret** |
| `AZURE_AD_CLIENT_ID` | Entra ID | To enable Microsoft | App registration **Application (client) ID** |
| `AZURE_AD_CLIENT_SECRET` | Entra ID | To enable Microsoft | Client secret **value** (not its ID) |
| `AZURE_AD_TENANT` | Entra ID | No (default `common`) | Tenant id/domain to restrict sign-in to one directory |
| `GOOGLE_CLIENT_ID` | Google | To enable Google | OAuth client **Client ID** |
| `GOOGLE_CLIENT_SECRET` | Google | To enable Google | OAuth client **Client secret** |
| `GOOGLE_WORKSPACE_DOMAIN` | Google | No (default: any account) | Restrict sign-in to one Workspace domain (`hd` param + verified claim) |
| `OKTA_CLIENT_ID` | Okta | To enable Okta | OIDC application **Client ID** |
| `OKTA_CLIENT_SECRET` | Okta | To enable Okta | OIDC application **Client secret** |
| `OKTA_ISSUER` | Okta | To enable Okta | Org / authorization-server issuer (e.g. `https://acme.okta.com/oauth2/default`) |
| `COGNITO_CLIENT_ID` | AWS Cognito | To enable AWS | App client **Client ID** |
| `COGNITO_CLIENT_SECRET` | AWS Cognito | To enable AWS | App client **Client secret** |
| `COGNITO_ISSUER` | AWS Cognito | To enable AWS | User-pool issuer (`https://cognito-idp.<region>.amazonaws.com/<userPoolId>`) |
| `KEYCLOAK_CLIENT_ID` | Keycloak | To enable Keycloak | Confidential client **Client ID** |
| `KEYCLOAK_CLIENT_SECRET` | Keycloak | To enable Keycloak | Confidential client **Client secret** |
| `KEYCLOAK_ISSUER` | Keycloak | To enable Keycloak | Realm issuer (`https://kc.example.com/realms/<realm>`) |
| `OIDC_CLIENT_ID` | Generic OIDC | To enable OIDC | Confidential client **Client ID** |
| `OIDC_CLIENT_SECRET` | Generic OIDC | To enable OIDC | Confidential client **Client secret** |
| `OIDC_ISSUER` | Generic OIDC | To enable OIDC | IdP issuer URL (discovery at `<issuer>/.well-known/openid-configuration`) |
| `OIDC_DISPLAY_NAME` | Generic OIDC | No (default `OIDC`) | Login-button and admin-card label (e.g. `Authentik`) |
| `OIDC_SCOPES` | Generic OIDC | No (default `openid profile email`) | Whitespace-separated scopes requested at authorize |
| `AUTH0_CLIENT_ID` | Auth0 | To enable Auth0 | Application **Client ID** |
| `AUTH0_CLIENT_SECRET` | Auth0 | To enable Auth0 | Application **Client Secret** |
| `AUTH0_ISSUER` | Auth0 | To enable Auth0 | Tenant issuer (`https://<tenant>.auth0.com`) |
| `LINE_CLIENT_ID` | LINE | To enable LINE | LINE Login channel **Channel ID** |
| `LINE_CLIENT_SECRET` | LINE | To enable LINE | LINE Login channel **Channel secret** |
| `VK_CLIENT_ID` | VK | To enable VK | VK ID application **App ID** |
| `VK_CLIENT_SECRET` | VK | To enable VK | VK ID application **Secure key** |
| `WECHAT_CLIENT_ID` | WeChat | To enable WeChat | WeChat Open Platform Website App **AppID** |
| `WECHAT_CLIENT_SECRET` | WeChat | To enable WeChat | WeChat Open Platform Website App **AppSecret** |
| `WECHAT_LANG` | WeChat | No (default `cn`) | QR page language: `cn` or `en` |
| `ATLASSIAN_CLIENT_ID` | Atlassian | To enable Atlassian | OAuth 2.0 (3LO) integration **Client ID** |
| `ATLASSIAN_CLIENT_SECRET` | Atlassian | To enable Atlassian | OAuth 2.0 (3LO) integration **Secret** |
| `BITBUCKET_CLIENT_ID` | Bitbucket | To enable Bitbucket | OAuth consumer **Key** |
| `BITBUCKET_CLIENT_SECRET` | Bitbucket | To enable Bitbucket | OAuth consumer **Secret** |
| `SLACK_CLIENT_ID` | Slack | To enable Slack | Slack app **Client ID** |
| `SLACK_CLIENT_SECRET` | Slack | To enable Slack | Slack app **Client Secret** |
| `LINKEDIN_CLIENT_ID` | LinkedIn | To enable LinkedIn | LinkedIn app **Client ID** |
| `LINKEDIN_CLIENT_SECRET` | LinkedIn | To enable LinkedIn | LinkedIn app **Primary Client Secret** |
| `DISCORD_CLIENT_ID` | Discord | To enable Discord | Discord application **Client ID** |
| `DISCORD_CLIENT_SECRET` | Discord | To enable Discord | Discord application **Client Secret** |
| `SALESFORCE_CLIENT_ID` | Salesforce | To enable Salesforce | Salesforce app **Consumer Key** |
| `SALESFORCE_CLIENT_SECRET` | Salesforce | To enable Salesforce | Salesforce app **Consumer Secret** |
| `SALESFORCE_ISSUER` | Salesforce | No (default `https://login.salesforce.com`) | Issuer for a My Domain (e.g. `https://acme.my.salesforce.com`) or a sandbox (`https://test.salesforce.com`) |
| `NOTION_CLIENT_ID` | Notion | To enable Notion | Notion public integration **OAuth Client ID** |
| `NOTION_CLIENT_SECRET` | Notion | To enable Notion | Notion public integration **OAuth Client Secret** |
| `FIGMA_CLIENT_ID` | Figma | To enable Figma | Figma OAuth app **Client ID** |
| `FIGMA_CLIENT_SECRET` | Figma | To enable Figma | Figma OAuth app **Client secret** |
| `LINEAR_CLIENT_ID` | Linear | To enable Linear | Linear OAuth application **Client ID** |
| `LINEAR_CLIENT_SECRET` | Linear | To enable Linear | Linear OAuth application **Client secret** |
| `DROPBOX_CLIENT_ID` | Dropbox | To enable Dropbox | Dropbox app **App key** |
| `DROPBOX_CLIENT_SECRET` | Dropbox | To enable Dropbox | Dropbox app **App secret** |
| `ZOOM_CLIENT_ID` | Zoom | To enable Zoom | Zoom app **Client ID** |
| `ZOOM_CLIENT_SECRET` | Zoom | To enable Zoom | Zoom app **Client Secret** |
| `HUGGINGFACE_CLIENT_ID` | Hugging Face | To enable Hugging Face | Hugging Face OAuth app client ID |
| `HUGGINGFACE_CLIENT_SECRET` | Hugging Face | To enable Hugging Face | Hugging Face OAuth app client secret |
| `VERCEL_CLIENT_ID` | Vercel | To enable Vercel | Vercel App **Client ID** |
| `VERCEL_CLIENT_SECRET` | Vercel | To enable Vercel | Vercel App client secret |
| `RAILWAY_CLIENT_ID` | Railway | To enable Railway | Railway OAuth app client ID |
| `RAILWAY_CLIENT_SECRET` | Railway | To enable Railway | Railway OAuth app client secret |
| `HUBSPOT_CLIENT_ID` | HubSpot | To enable HubSpot | HubSpot app **Client ID** |
| `HUBSPOT_CLIENT_SECRET` | HubSpot | To enable HubSpot | HubSpot app **Client secret** |
| `APPLE_CLIENT_ID` | Apple | To enable Apple | The **Services ID** identifier (e.g. `com.example.apiome.web`) |
| `APPLE_PRIVATE_KEY` | Apple | To enable Apple | The Sign in with Apple private key — the whole `.p8` file (stored as the sealed secret) |
| `APPLE_TEAM_ID` | Apple | To enable Apple | The 10-character Apple Developer **Team ID** |
| `APPLE_KEY_ID` | Apple | To enable Apple | The **Key ID** of the `.p8` private key |
| `FACEBOOK_CLIENT_ID` | Facebook | To enable Facebook | Meta app **App ID** |
| `FACEBOOK_CLIENT_SECRET` | Facebook | To enable Facebook | Meta app **App secret** |
| `TWITTER_CLIENT_ID` | X / Twitter | To enable X | X app OAuth 2.0 **Client ID** |
| `TWITTER_CLIENT_SECRET` | X / Twitter | To enable X | X app OAuth 2.0 **Client Secret** |
| `REDDIT_CLIENT_ID` | Reddit | To enable Reddit | Reddit web app **client ID** (under the app name) |
| `REDDIT_CLIENT_SECRET` | Reddit | To enable Reddit | Reddit web app **secret** |
| `SPOTIFY_CLIENT_ID` | Spotify | To enable Spotify | Spotify app **Client ID** |
| `SPOTIFY_CLIENT_SECRET` | Spotify | To enable Spotify | Spotify app **Client secret** |
| `TWITCH_CLIENT_ID` | Twitch | To enable Twitch | Twitch application **Client ID** |
| `TWITCH_CLIENT_SECRET` | Twitch | To enable Twitch | Twitch application **Client Secret** |
| `TIKTOK_CLIENT_KEY` | TikTok | To enable TikTok | TikTok app **Client key** (TikTok's name for the client ID) |
| `TIKTOK_CLIENT_SECRET` | TikTok | To enable TikTok | TikTok app **Client secret** |
| `ROBLOX_CLIENT_ID` | Roblox | To enable Roblox | Roblox OAuth 2.0 app **Client ID** |
| `ROBLOX_CLIENT_SECRET` | Roblox | To enable Roblox | Roblox OAuth 2.0 app **Client secret** |
| `KICK_CLIENT_ID` | Kick | To enable Kick | Kick app **Client ID** |
| `KICK_CLIENT_SECRET` | Kick | To enable Kick | Kick app **Client Secret** |
| `AUTH_PROVIDER_VALIDATION` | validation | No (default `strict`) | `strict` fails startup on partial provider config; `warn` logs and disables |

Rules that apply to every provider:

- Blank or whitespace-only values count as **unset** — a commented-template line like
  `GITHUB_ID=` does not enable a provider, and a blank *stored* value falls back to env rather
  than disabling the field.
- **All fields resolved** → provider enabled. **No fields resolved** → provider cleanly disabled.
  Both are valid deployments.
- **Some-but-not-all resolved** → misconfiguration; see
  [Boot-time validation](#boot-time-validation) below. "Resolved" is judged against the merged
  DB-over-env view, so an env var left unset because the value is stored in the database is not a
  gap.

### Required fields beyond client id/secret (OLO-9.1)

A registry entry declares its required fields structurally (`requiredFields`), each mapped to
an env var. Most providers require exactly a **client id** and a **client secret**. Issuer-based
providers (Okta, Cognito, Keycloak, generic OIDC, Auth0) additionally
require an OIDC **issuer** URL stored in the provider's `config` extras. Setting the id and secret
but leaving the issuer unset is *partial config* and boot-time validation names the missing issuer
var, exactly as it does for a missing secret. In the admin settings screen the same field is
required before the provider can be enabled from the database (the issuer is stored in the
`config` JSONB and overlaid onto its env var). For generic OIDC, a fully configured issuer is also
**probed** at boot and on admin Validate (`GET <issuer>/.well-known/openid-configuration`) so a bad
or unreachable IdP fails loud instead of leaving a broken login page.

## Provider vocabulary and trust classes (OLO-9.16)

Two things are decided once for the whole Better Auth catalog, so a provider ticket
(OLO-9.17–9.49) does neither on its own:

**The slug vocabulary.** `V395__auth_provider_vocabulary_full_catalog_5029.sql` widens both
provider CHECKs — `external_auth_providers_provider_supported_ck` (linked identities) and
`auth_provider_config_provider_id_check` (stored provider config) — to every slug in the table
below. A provider ticket needs **no migration**. A slug is inert until its registry entry ships:
the registry and `LINKABLE_PROVIDERS` remain the gates on what can be enabled, linked or signed
in with; the CHECK is only a typo backstop. Slugs are Better Auth's own provider ids.

**The trust-gate rule.** A provider joins `AUTO_LINK_TRUSTED_PROVIDERS`
(`lib/auth/account-resolution.ts`) only when it *proves* a verified email — a signed
`email_verified` claim, or an explicit verified flag from its own API that the provider's
`getUserInfo` normalizes onto `email_verified`, fail-closed (missing, malformed or false means
unverified). Each provider has exactly one class:

| Class | The provider gives | In `AUTO_LINK_TRUSTED_PROVIDERS` | Sign-in |
| --- | --- | --- | --- |
| **trusted** | An email and proof it is verified | Yes | A verified email auto-links the matching account or creates one; an unverified one is refused (`unverified-email`) |
| **link-first** | An email with no proof | No | Resolves only through an already-bound identity; bind one from **Linked accounts** while signed in |
| **link-only** | No email | No | As link-first (`email-required` when nothing is bound) |

The table of record is `PROVIDER_TRUST_CLASSES` in `lib/auth/provider-trust-classes.ts`; this
copy is for reading. A provider ticket cites its row and, in the change that ships its registry
entry:

1. adds the slug to `LINKABLE_PROVIDERS`;
2. adds the slug to `AUTO_LINK_TRUSTED_PROVIDERS` **only if** its class is `trusted`;
3. for a **provisional** class (the fail-closed default where the roadmap says *confirmed at
   implementation*): either keeps `link-first` and drops `provisional`, or promotes the row to
   `trusted` with the proving claim or field named in `evidence`. Never promote without one.

`tests/provider-trust-classes.test.ts` fails when the sets, the table and the V395 vocabulary
disagree, and proves that a verified-looking email from a link-first or link-only provider never
links an account.

| Slug | Trust class | Ticket | Shipped | Evidence |
| --- | --- | --- | --- | --- |
| `github` | **trusted** | OLO-2.5 | yes | Primary address with `verified: true` from `/user/emails` |
| `gitlab` | **trusted** | OLO-2.5 | yes | `email_verified` claim, or `confirmed_at` on the user |
| `azure` | **trusted** | OLO-1.4 | yes | `xms_edov` domain-owner-verified claim (nOAuth hardening); never the bare email claim |
| `google` | **trusted** | OLO-9.2 | yes | `email_verified` id-token claim |
| `okta` | **trusted** | OLO-9.3 | yes | `email_verified` id-token claim |
| `aws` | **trusted** | OLO-9.4 | yes | Cognito `email_verified` claim |
| `keycloak` | **trusted** | OLO-9.5 | yes | `email_verified` claim |
| `oidc` | **trusted** | OLO-9.6 | yes | `email_verified` claim from the configured issuer |
| `auth0` | **trusted** | OLO-9.7 | yes | `email_verified` claim |
| `atlassian` | **trusted** | OLO-9.8 | yes | `email_verified` from the User Identity API; absent means unverified |
| `bitbucket` | **trusted** | OLO-9.9 | yes | Primary address with `is_confirmed` from `/2.0/user/emails` |
| `line` | **trusted** | OLO-9.41 | yes | `email_verified` claim, sent only with the approved email permission; absent means unverified |
| `vk` | **link-first** | OLO-9.42 | yes | Email returned with the grant, no verified claim |
| `wechat` | **link-only** | OLO-9.43 | yes | No email; identity is keyed on `openid` / `unionid` |
| `slack` | **trusted** | OLO-9.17 | yes | `email_verified` claim (Sign in with Slack, OIDC) |
| `linkedin` | **trusted** | OLO-9.18 | yes | `email_verified` claim (Sign In with LinkedIn, OIDC) |
| `discord` | **trusted** | OLO-9.19 | yes | `verified` on `/users/@me` |
| `salesforce` | **trusted** | OLO-9.20 | yes | `email_verified` claim |
| `notion` | **link-first** | OLO-9.21 | yes | Owner-user email from the token exchange, no verified claim |
| `figma` | **link-first** | OLO-9.22 | yes | `/v1/me` email, no verified claim |
| `linear` | **link-first** | OLO-9.23 | yes | Viewer email, no verified claim |
| `dropbox` | **trusted** | OLO-9.24 | yes | `email_verified` on `get_current_account` |
| `zoom` | **trusted** | OLO-9.25 | yes | `verified` on `/v2/users/me` |
| `huggingface` | **trusted** | OLO-9.26 | yes | `email_verified` claim |
| `vercel` | **trusted** | OLO-9.27 | yes | `email_verified` on `/login/oauth/userinfo` |
| `railway` | **link-first** | OLO-9.28 | yes | `/oauth/me` email, no documented verified claim |
| `hubspot` | **link-first** | OLO-9.29 | yes | Token-info email, no verified claim |
| `apple` | **trusted** | OLO-9.30 | yes | `email_verified` id-token claim; Hide My Email relay addresses (`is_private_email`) are verified too |
| `facebook` | **link-first** | OLO-9.31 | yes | Graph email, no verified claim |
| `twitter` | **link-first** | OLO-9.32 | yes | Email needs elevated API access and carries no verified claim |
| `reddit` | **link-only** | OLO-9.33 | yes | No email address (`has_verified_email` alone names no address) |
| `spotify` | **link-first** | OLO-9.34 | yes | `/v1/me` email is documented as unverified |
| `twitch` | **trusted** | OLO-9.35 | yes | `email_verified` claim with the `user:read:email` scope |
| `tiktok` | **link-only** | OLO-9.36 | yes | No email in user info |
| `roblox` | **link-only** | OLO-9.37 | yes | Profile claims only, no email claim |
| `kick` | **link-first** | OLO-9.38 | yes | `/public/v1/users` email, no verified claim |
| `kakao` | **trusted** | OLO-9.39 | no | `is_email_valid` and `is_email_verified` on `kakao_account`, both true |
| `naver` | **link-first** (provisional) | OLO-9.40 | no | `/v1/nid/me` email; verified semantics confirmed at implementation |
| `yandex` | **link-first** (provisional) | OLO-9.44 | no | `default_email`; verified semantics confirmed at implementation |
| `paypal` | **trusted** | OLO-9.45 | no | `email_verified` claim |
| `polar` | **link-first** (provisional) | OLO-9.46 | no | Email and verified semantics confirmed at implementation |
| `patreon` | **trusted** | OLO-9.47 | no | `is_email_verified` on the identity resource |
| `gumroad` | **link-first** | OLO-9.48 | no | User email, no verified claim |
| `paybin` | **link-first** (provisional) | OLO-9.49 | no | Email semantics confirmed at implementation |

## Boot-time validation

At server startup ([`src/instrumentation.ts`](../src/instrumentation.ts) →
`validateProviderEnv()`), every provider's config contract is checked. A *partially*
configured provider — e.g. `GITHUB_ID` set but `GITHUB_SECRET` missing, typically a typo'd
var name or a secret that never reached the deployment — is reported per
`AUTH_PROVIDER_VALIDATION`:

- **`strict`** (default): startup **fails** with one actionable message per issue, naming
  the missing and present fields and both ways to resolve (set them all, or clear them all).
  Misconfiguration fails loud at boot, not silently at first login.
- **`warn`**: each issue is logged via `console.warn` and the provider stays **cleanly
  disabled** (a provider missing any required field is never registered as a sign-in provider).

Any other value of `AUTH_PROVIDER_VALIDATION` is itself a startup error, so a typo cannot
silently weaken validation.

Example strict-mode failure:

```
Error: Refusing to start: 1 sign-in provider(s) partially configured.
  - Sign-in provider 'GitHub' (github) is partially configured: GITHUB_SECRET is unset or
    blank while GITHUB_ID is set. Set all of GITHUB_ID, GITHUB_SECRET to enable GitHub
    sign-in, or unset all of them to disable it. Setup guide: apiome-ui/docs/AUTH_PROVIDER_SETUP.md
Set AUTH_PROVIDER_VALIDATION=warn to log instead and leave the provider(s) disabled.
```

### Validation and the database source (OLO-8.8)

Validation runs against the **merged** DB-over-env config, not raw `process.env`. Boot resolves the
overlay first (which also warms the resolver's cache, so the first login does not pay for the
fetch), then validates what login will actually see. Three cases, distinguished by whether the
stored config could be read:

| Config source | What it means | Strict-mode behaviour |
|---|---|---|
| **env-only** | `INTERNAL_SERVICE_TOKEN` unset — the database layer is off | unchanged: env is the whole truth, partial config fails startup |
| **database** | the resolved endpoint answered; stored values are merged in | a provider completed from the database is **not** flagged; one still partial after the merge fails startup, and its message names the admin screen as well as the env vars |
| **unavailable** | the token is set but the endpoint could not be read | strict is **downgraded to a warning** and startup continues |

The first row is the acceptance criterion this feature exists for: with `GITHUB_ID` in `.env` and
the secret stored from the admin screen, the deployment is complete and boot says nothing.

The **unavailable** downgrade is deliberate. When apiome-rest is unreachable at UI startup — a
common container-ordering situation — the merged view is missing whatever is stored, so a provider
that *looks* partial may be perfectly configured. Refusing to start on that evidence would turn a
transient REST outage into a boot outage. Startup continues, sign-in runs on env config until the
endpoint is reachable again, and the downgrade is never silent:

```
[provider-registry] AUTH_PROVIDER_VALIDATION=strict not enforced: the stored provider config
could not be read, so partial config cannot be told apart from config that lives in the
database. Startup continues on env config; the provider(s) below are disabled until the
resolved endpoint is reachable again.
[provider-registry] Sign-in provider 'GitHub' (github) is partially configured: GITHUB_SECRET is
unset or blank in env, and the stored provider config could not be read, while GITHUB_ID is set.
… This may be a false alarm: GitHub may already be fully configured in the database. … (provider disabled)
```

An invalid `AUTH_PROVIDER_VALIDATION` value still aborts startup in every case — the downgrade
covers unproven partial config only, never a typo'd mode.

## GitHub — OAuth app

1. Go to **GitHub → Settings → Developer settings → OAuth Apps** (org-owned apps: the org's
   **Settings → Developer settings**) and click **New OAuth App**.
2. Fill in:
   - **Application name:** `Apiome` (or your deployment's name)
   - **Homepage URL:** your `BETTER_AUTH_URL`, e.g. `https://app.apiome.dev`
   - **Authorization callback URL:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/github`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/github` for local dev)
3. Click **Register application**, then **Generate a new client secret**. Copy the secret
   immediately — GitHub shows it only once.
4. Set the env vars:

```bash
GITHUB_ID=<Client ID>
GITHUB_SECRET=<Client secret>
```

   …or store the same client id and secret from **Admin → System Configuration** instead. The
   stored values take precedence over these vars and take effect at the next login without a
   restart; leave the vars unset if the database is where you keep them
   ([Config precedence](#config-precedence--database-first-env-fallback)).

No extra scopes need configuring in the app — the sign-in flow requests `read:user
user:email` itself so it can resolve a **verified** primary email even when the public
profile email is hidden (OLO-2.5).

## GitLab — application

1. On GitLab, go to **Settings → Applications**
   (<https://gitlab.com/-/user_settings/applications>) — or a group/instance-level
   application for team use — and click **Add new application**.
2. Fill in:
   - **Name:** `Apiome`
   - **Redirect URI:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/gitlab`
   - **Confidential:** checked
   - **Scopes:** `read_user` (the sign-in flow requests `read_user` — email verification is
     read from the GitLab profile, OLO-2.5)
3. Save, then copy the **Application ID** and **Secret**.
4. Set the env vars:

```bash
GITLAB_CLIENT_ID=<Application ID>
GITLAB_CLIENT_SECRET=<Secret>
```

   …or store the same application id and secret from **Admin → System Configuration** instead —
   along with `GITLAB_BASE_URL` for a self-managed instance, which lives in the same stored `config`
   extras. Stored values take precedence over these vars and take effect at the next login without a
   restart ([Config precedence](#config-precedence--database-first-env-fallback)).

Step-by-step walkthrough with screenshots and self-managed-instance notes:
[`GITLAB_SSO_SETUP.md`](./GITLAB_SSO_SETUP.md).

## Microsoft Entra ID — app registration

1. In the [Entra admin center](https://entra.microsoft.com), go to **Identity →
   Applications → App registrations → New registration**.
2. Fill in:
   - **Name:** `Apiome`
   - **Supported account types:** multi-tenant (any directory) unless you want to restrict
     sign-in to one tenant — then single-tenant and set `AZURE_AD_TENANT` to your tenant id
     or domain.
   - **Redirect URI:** platform **Web**, value `{BETTER_AUTH_URL}/api/auth/oauth2/callback/azure`
3. Under **Certificates & secrets**, create a **client secret** and copy its **Value**
   (not the Secret ID) — it is shown only once.
4. **Required — enable the `xms_edov` optional claim** (OLO-1.4): under **Token
   configuration → Add optional claim**, token type **ID**, select **`xms_edov`** ("email
   domain owner verified"). Without this claim, Entra sign-ins are treated as having
   **unverified** email domains and users fall back to email verification instead of
   auto-joining their tenant. Full rationale, claim matrix, and verification steps:
   [`ENTRA_ID_APP_REGISTRATION.md`](./ENTRA_ID_APP_REGISTRATION.md).
5. Set the env vars:

```bash
AZURE_AD_CLIENT_ID=<Application (client) ID>
AZURE_AD_CLIENT_SECRET=<client secret Value>
# Optional: restrict to one directory (defaults to `common`, multi-tenant)
# AZURE_AD_TENANT=<tenant id or domain>
```

   …or store the same application id and client secret from **Admin → System Configuration**
   instead; `AZURE_AD_TENANT` (and the `AZURE_AD_AUTHORITY_BASE_URL` override) live in the same
   stored `config` extras. Stored values take precedence over these vars and take effect at the next
   login without a restart ([Config precedence](#config-precedence--database-first-env-fallback)).
   The `xms_edov` optional claim in step 4 is configured in Entra either way — it is a property of
   the app registration, not of Apiome's config.

## Google — OAuth client (Workspace sign-in)

1. In the [Google Cloud console](https://console.cloud.google.com/apis/credentials), pick (or
   create) a project, then go to **APIs & Services → Credentials**. Configure the **OAuth consent
   screen** first if prompted — **Internal** for a single Workspace org, **External** otherwise.
2. Click **Create credentials → OAuth client ID**:
   - **Application type:** **Web application**
   - **Authorized redirect URI:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/google`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/google` for local dev)
3. Click **Create**, then copy the **Client ID** and **Client secret**.
4. Set the env vars:

```bash
GOOGLE_CLIENT_ID=<Client ID>
GOOGLE_CLIENT_SECRET=<Client secret>
# Optional: restrict sign-in to one Google Workspace domain (defaults to any Google account)
# GOOGLE_WORKSPACE_DOMAIN=example.com
```

The sign-in flow requests the `openid email profile` scopes and reads Google's native
`email_verified` claim, so a verified Google address auto-joins its account exactly like the other
providers (OLO-2.5). No extra scopes need configuring on the OAuth client.

**Workspace domain restriction.** When `GOOGLE_WORKSPACE_DOMAIN` is set, the flow adds Google's
`hd` ("hosted domain") authorization parameter *and* verifies the `hd` claim on the returned id
token, rejecting any account outside that domain. The `hd` parameter alone is only advisory — a
user can still complete the flow with a personal or foreign-domain account — so the claim check is
the real boundary (per Google's OIDC docs). Leave the variable unset to allow any Google account,
including personal `@gmail.com` addresses.

## Okta — OIDC application (workforce IdP)

1. In the [Okta Admin Console](https://login.okta.com/), go to **Applications → Applications →
   Create App Integration**.
2. Choose **OIDC - OpenID Connect**, then **Web Application**.
3. Configure:
   - **Sign-in redirect URIs:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/okta`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/okta` for local dev)
   - **Controlled access:** assign the groups / people who may sign in
4. After creation, copy the **Client ID** and **Client secret**.
5. Determine the issuer URL for the authorization server you want to use:
   - Org authorization server (default): `https://{yourOktaDomain}/oauth2/default`
   - Custom authorization server: `https://{yourOktaDomain}/oauth2/{authServerId}`
   - The issuer is also listed under **Security → API → Authorization Servers** (the
     **Issuer URI** column).
6. Set the env vars:

```bash
OKTA_CLIENT_ID=<Client ID>
OKTA_CLIENT_SECRET=<Client secret>
OKTA_ISSUER=https://acme.okta.com/oauth2/default
```

The sign-in flow discovers endpoints from `{OKTA_ISSUER}/.well-known/openid-configuration`,
uses PKCE, requests the `openid email profile` scopes, and reads Okta's native `email_verified`
claim (fail-closed — a missing or false claim is treated as unverified). All three variables are
required; setting only the client id and secret is *partial config* and boot / admin Validate name
`OKTA_ISSUER`.

The same issuer can also be set from **Admin → System Configuration** (stored under `config.OKTA_ISSUER`
and overlaid onto the env var per OLO-8.5 / OLO-10.8).

## Amazon Cognito — user pool + Hosted UI (OLO-9.4)

1. In the [Amazon Cognito console](https://console.aws.amazon.com/cognito/), open (or create) a
   **User pool**.
2. Under **App integration → App clients → Create an app client**:
   - **App type:** Confidential client (client secret generated)
   - **Authentication flows:** allow the Authorization code grant
   - **Allowed callback URLs:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/aws`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/aws` for local dev)
3. Under **App integration → Domain**, configure a Cognito domain (or custom domain) so Hosted UI
   can serve the authorize endpoint discovered from the issuer.
4. Copy the app client's **Client ID** and **Client secret**.
5. Build the user-pool issuer URL:
   `https://cognito-idp.<region>.amazonaws.com/<userPoolId>`
   (Region and pool id are on the user-pool overview; the issuer is also the `issuer` claim in
   Cognito id tokens.)
6. Set the env vars:

```bash
COGNITO_CLIENT_ID=<Client ID>
COGNITO_CLIENT_SECRET=<Client secret>
COGNITO_ISSUER=https://cognito-idp.us-east-1.amazonaws.com/us-east-1_AbCdEf
```

The sign-in flow discovers endpoints from `{COGNITO_ISSUER}/.well-known/openid-configuration`,
uses PKCE, requests the `openid email profile` scopes, and reads Cognito's native `email_verified`
claim (fail-closed — a missing or false claim is treated as unverified). All three variables are
required; setting only the client id and secret is *partial config* and boot / admin Validate name
`COGNITO_ISSUER`.

The same issuer can also be set from **Admin → System Configuration** (stored under
`config.COGNITO_ISSUER` and overlaid onto the env var per OLO-8.5 / OLO-10.8).

## Keycloak — realm OIDC client (OLO-9.5)

1. In the Keycloak Admin Console, open (or create) a **realm** (e.g. `apiome`).
2. Under **Clients → Create client**:
   - **Client type:** OpenID Connect
   - **Client authentication:** On (confidential client — secret generated)
   - **Authentication flow:** Standard flow (authorization code)
   - **Valid redirect URIs:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/keycloak`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/keycloak` for local dev)
3. Copy the client's **Client ID** and **Client secret** (Credentials tab).
4. Build the realm issuer URL: `https://{keycloakHost}/realms/{realm}`
   (also listed as the `issuer` in `{issuer}/.well-known/openid-configuration`).
5. Ensure the client (or realm) mapper set includes `email`, `email verified`, and ideally
   `preferred_username` / `name` claims on the ID token.
6. Set the env vars:

```bash
KEYCLOAK_CLIENT_ID=<Client ID>
KEYCLOAK_CLIENT_SECRET=<Client secret>
KEYCLOAK_ISSUER=https://kc.example.com/realms/apiome
```

The sign-in flow discovers endpoints from `{KEYCLOAK_ISSUER}/.well-known/openid-configuration`,
uses PKCE, requests the `openid email profile` scopes, and reads Keycloak's native `email_verified`
claim (fail-closed — a missing or false claim is treated as unverified). All three variables are
required; setting only the client id and secret is *partial config* and boot / admin Validate name
`KEYCLOAK_ISSUER`.

The same issuer can also be set from **Admin → System Configuration** (stored under
`config.KEYCLOAK_ISSUER` and overlaid onto the env var per OLO-8.5 / OLO-10.8).

### Local testing with Docker Compose

A minimal Keycloak for local Apiome sign-in (dev credentials only — never reuse in production):

```yaml
# docker-compose.keycloak.yml
services:
  keycloak:
    image: quay.io/keycloak/keycloak:26.0
    command: start-dev
    environment:
      KEYCLOAK_ADMIN: admin
      KEYCLOAK_ADMIN_PASSWORD: admin
      KC_HTTP_PORT: 8080
    ports:
      - "8080:8080"
```

```bash
docker compose -f docker-compose.keycloak.yml up -d
```

Then in the Admin Console (`http://localhost:8080`):

1. Create realm `apiome`.
2. Create a confidential OIDC client (e.g. `apiome-ui`) with redirect
   `http://localhost:3000/api/auth/oauth2/callback/keycloak`.
3. Create a user with a verified email.
4. Point Apiome at:

```bash
KEYCLOAK_CLIENT_ID=apiome-ui
KEYCLOAK_CLIENT_SECRET=<from Credentials tab>
KEYCLOAK_ISSUER=http://localhost:8080/realms/apiome
```

## Generic OIDC — any conformant OpenID Provider (OLO-9.6)

Use this connector when the IdP is OIDC-compliant but has no first-class catalog entry
(PingFederate, OneLogin, JumpCloud, Authentik, ZITADEL, FusionAuth, Duende IdentityServer, …).
**v1 supports exactly one generic OIDC IdP per deployment** — configure a single
`OIDC_ISSUER` / client pair. Prefer a first-class provider (Okta, Keycloak, Auth0, …) when one
exists.

1. In your IdP, register a **confidential** OIDC / OAuth 2.0 client:
   - **Redirect URI / callback:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/oidc`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/oidc` for local dev)
   - **Grant:** Authorization code (with PKCE)
   - **Scopes:** at least `openid`, and typically `profile` + `email` (or set `OIDC_SCOPES`)
2. Copy the **Client ID** and **Client secret**.
3. Determine the issuer URL — the value that serves
   `{issuer}/.well-known/openid-configuration` (often the realm/tenant base URL; must match the
   `issuer` claim in id tokens).
4. Ensure the IdP emits `email`, `email_verified`, and ideally `name` / `preferred_username` /
   `sub` on the ID token.
5. Set the env vars:

```bash
OIDC_CLIENT_ID=<Client ID>
OIDC_CLIENT_SECRET=<Client secret>
OIDC_ISSUER=https://auth.example.com
# Optional: login button / admin card label (defaults to "OIDC")
# OIDC_DISPLAY_NAME=Authentik
# Optional: whitespace-separated scopes (defaults to openid profile email)
# OIDC_SCOPES=openid profile email
```

The sign-in flow discovers endpoints from `{OIDC_ISSUER}/.well-known/openid-configuration`,
uses PKCE, requests the configured scopes, and reads the IdP's native `email_verified` claim
(fail-closed — a missing or false claim is treated as unverified). All three required variables
must be set; setting only the client id and secret is *partial config* and boot / admin Validate
name `OIDC_ISSUER`. When the trio is complete, boot and admin Validate also **probe** discovery —
an unreachable or non-conformant issuer surfaces a clear error instead of a broken login page.

The same issuer / display name / scopes can also be set from **Admin → System Configuration**
(stored under `config.OIDC_*` and overlaid onto the env vars per OLO-8.5 / OLO-10.8).

## Auth0 — Regular Web Application (OLO-9.7)

1. In the [Auth0 Dashboard](https://manage.auth0.com/), go to **Applications → Applications →
   Create Application**.
2. Choose **Regular Web Applications**, then create.
3. On the **Settings** tab, configure:
   - **Allowed Callback URLs:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/auth0`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/auth0` for local dev)
   - **Allowed Logout URLs** / **Allowed Web Origins:** your app origin as needed
4. Copy the **Client ID** and **Client Secret**.
5. The tenant issuer is `https://{yourTenant}.auth0.com` (shown as **Domain** on Settings —
   prefix with `https://`). Custom domains use that hostname instead.
6. Set the env vars:

```bash
AUTH0_CLIENT_ID=<Client ID>
AUTH0_CLIENT_SECRET=<Client Secret>
AUTH0_ISSUER=https://acme.auth0.com
```

The sign-in flow discovers endpoints from `{AUTH0_ISSUER}/.well-known/openid-configuration`,
uses PKCE, requests the `openid email profile` scopes, and reads Auth0's native `email_verified`
claim (fail-closed — a missing or false claim is treated as unverified). All three variables are
required; setting only the client id and secret is *partial config* and boot / admin Validate name
`AUTH0_ISSUER`.

The same issuer can also be set from **Admin → System Configuration** (stored under
`config.AUTH0_ISSUER` and overlaid onto the env var per OLO-8.5 / OLO-10.8).

## LINE Login (OLO-9.41 — Japan / Taiwan / Thailand country MVP)

1. In the [LINE Developers Console](https://developers.line.biz/console/), create a **LINE Login**
   channel (or open an existing one).
2. On the channel **LINE Login** settings, set:
   - **Callback URL:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/line`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/line` for local dev)
3. Copy the **Channel ID** and **Channel secret**.
4. To receive the user's email, apply for **email address permission** under OpenID Connect on the
   channel's Basic settings. Until that permission is approved, LINE will not return an `email`
   claim even if the `email` scope is requested.
5. Set the env vars:

```bash
LINE_CLIENT_ID=<Channel ID>
LINE_CLIENT_SECRET=<Channel secret>
```

The sign-in flow uses LINE Login v2.1 fixed endpoints (`https://access.line.me/oauth2/v2.1/authorize`,
`https://api.line.me/oauth2/v2.1/token`, `https://api.line.me/oauth2/v2.1/userinfo`), PKCE, and the
`openid profile email` scopes. Prefer the ID token for profile claims; fall back to userinfo when
needed. **Email verified semantics:** when an `email_verified` claim arrives it is honored; when
the claim is absent or false the engine fail-closes (**link-first** — explicit link intent or an
already-bound identity). Missing email (permission not granted / user declined) surfaces
`email-required`.

### Multi-channel providerIds (JP / TW / TH)

LINE requires a **separate OAuth channel** per country/market (Japan, Taiwan, Thailand, …), each
with its own Channel ID and secret. Apiome's default registry entry uses a single `providerId`
of `line` with `LINE_CLIENT_ID` / `LINE_CLIENT_SECRET` — correct for a single-country deployment.

When one deployment must serve multiple LINE channels, mirror Better Auth's `line()` helper and
register distinct generic-OAuth configs (e.g. `line-jp`, `line-tw`, `line-th`) each with that
channel's credentials. Persist identities under those slugs; do not reuse a single `line` identity
across countries. Contact the platform team before enabling multi-channel — the DB vocabulary and
registry currently ship the single `line` slug (OLO-9.41); additional slug widenings land with
OLO-9.16 / follow-up tickets.

## VK ID (OLO-9.42 — Russia / CIS country MVP)

1. In the [VK ID Apps](https://id.vk.com/about/business/go/docs/en/vkid/latest/vk-id/connection/create-application)
   console, create an application (or open an existing one).
2. Set the **Redirect URI** to:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/vk`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/vk` for local dev)
3. Copy the **App ID** and **Secure key**.
4. Set the env vars:

```bash
VK_CLIENT_ID=<App ID>
VK_CLIENT_SECRET=<Secure key>
```

The sign-in flow uses fixed VK ID endpoints (`https://id.vk.com/authorize`,
`https://id.vk.com/oauth2/auth`, `https://id.vk.com/oauth2/user_info`), PKCE, and the
`email phone` scopes (mirroring Better Auth's `vk()` helper). User info is fetched via
**POST** form body (`access_token` + `client_id`). **Email verified semantics:** VK returns
email with the grant but does **not** assert a verified claim (Better Auth hard-codes
`emailVerified: false`). The engine always fail-closes (**link-first** — explicit link intent
or an already-bound identity), and `vk` is not in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16). Missing email surfaces `email-required`.

### Hosting / compliance (RU / CIS)

VK is the country-MVP SSO provider for Russia / CIS. Prefer hosting Apiome in the
RU/CIS region when enabling VK so identity traffic and personal data stay aligned with local
compliance expectations. Enabling VK from a non-RU/CIS deployment is technically possible but
should be a deliberate operator choice.

## WeChat Open Platform (OLO-9.43 — China country MVP)

1. In the [WeChat Open Platform](https://open.weixin.qq.com/) console, create a **Website App**
   (网站应用) — the QR web login flow Apiome uses.
2. Set the **Authorized callback domain / redirect URI** to:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/wechat`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/wechat` for local dev)
3. Copy the **AppID** and **AppSecret**.
4. Set the env vars:

```bash
WECHAT_CLIENT_ID=<AppID>
WECHAT_CLIENT_SECRET=<AppSecret>
# Optional: QR page language (cn | en). Defaults to cn.
# WECHAT_LANG=en
```

The sign-in flow mirrors Better Auth's `wechat()` helper:

- Authorize: `https://open.weixin.qq.com/connect/qrconnect` (QR scan) with scope `snsapi_login`,
  credential param `appid`, and hash `#wechat_redirect`
- Token: GET `https://api.weixin.qq.com/sns/oauth2/access_token` with `appid` / `secret` / `code`
  (custom `getToken` — WeChat does not use a standard POST client_id exchange)
- User info: GET `https://api.weixin.qq.com/sns/userinfo` with `access_token` + `openid`

**Email / trust class:** WeChat exposes **no email address**. Sign-in is **link-only** — users must
already have an Apiome account and **explicitly link** WeChat from linked accounts; subsequent
sign-in works via the bound `(wechat, openid|unionid)` identity. Fresh sign-in without a prior link
is rejected with the structured `OAuthEmailRequired` code.

### UnionID (multi-app deployments)

WeChat issues an **openid** per app and, when the developer account has bound multiple apps under
the same open-platform subject, a stable **unionid** across those apps. Apiome keys the identity on
`unionid` when present, otherwise `openid` (matching Better Auth's `wechat()` helper). Prefer
binding every Apiome-related WeChat app under one open-platform account so the same person keeps a
single identity across environments; otherwise each app's openid is a separate identity and users
must re-link.

### Hosting / compliance (CN)

WeChat is the country-MVP SSO provider for China. Prefer hosting Apiome in the CN region when
enabling WeChat so identity traffic and personal data stay aligned with local compliance
expectations. Enabling WeChat from a non-CN deployment is technically possible but should be a
deliberate operator choice.

## Atlassian — OAuth 2.0 (3LO) integration (OLO-9.8)

For teams whose people hold Atlassian accounts (Jira, Confluence) rather than GitHub or GitLab.

1. In the [Atlassian developer console](https://developer.atlassian.com/console/myapps/), choose
   **Create → OAuth 2.0 integration** (or open an existing one).
2. Under **Permissions**, add the **User identity API** and configure it with the
   **`read:me`** and **`read:account`** scopes.
3. Under **Authorization**, add **OAuth 2.0 (3LO)** with the **Callback URL**:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/atlassian`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/atlassian` for local dev)
4. Under **Distribution**, set the status to **Sharing** if people outside the account that owns
   the integration must be able to sign in.
5. Under **Settings**, copy the **Client ID** and **Secret**.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
ATLASSIAN_CLIENT_ID=<Client ID>
ATLASSIAN_CLIENT_SECRET=<Secret>
```

The sign-in flow uses fixed Atlassian endpoints — there is no issuer to configure:

- Authorize: `https://auth.atlassian.com/authorize` with `audience=api.atlassian.com`,
  `prompt=consent`, PKCE, and the `read:me read:account` scopes
- Token: `https://auth.atlassian.com/oauth/token`
- User info: GET `https://api.atlassian.com/me` (the User Identity API) with the bearer token

The identity is keyed on the Atlassian `account_id`. **Email verified semantics:** the
`email_verified` value in the `/me` response is honored when it is `true`; when it is absent or
false the engine fail-closes (**link-first** — explicit link intent or an already-bound identity).
A profile with no email surfaces `email-required` — an Atlassian account whose email visibility is
restricted must link from **Linked accounts** first.

## Bitbucket Cloud — OAuth consumer (OLO-9.9)

1. In Bitbucket, open the workspace's **Settings → OAuth consumers** and choose **Add consumer**
   (or open an existing one).
2. Set the **Callback URL** to:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/bitbucket`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/bitbucket` for local dev)
3. Leave **This is a private consumer** ticked — Apiome holds the secret server-side.
4. Under **Permissions → Account**, tick **Email** and **Read**.
5. Save, then copy the consumer's **Key** and **Secret**.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
BITBUCKET_CLIENT_ID=<Key>
BITBUCKET_CLIENT_SECRET=<Secret>
```

The sign-in flow uses fixed Bitbucket Cloud endpoints — there is no issuer to configure:

- Authorize: `https://bitbucket.org/site/oauth2/authorize` with the `account email` scopes
- Token: `https://bitbucket.org/site/oauth2/access_token`, the consumer authenticated with HTTP
  Basic (`Key:Secret`); no PKCE (state is enforced)
- User info: GET `https://api.bitbucket.org/2.0/user`, then GET
  `https://api.bitbucket.org/2.0/user/emails` — the profile itself carries no email

The identity is keyed on the Bitbucket user `uuid`. **Email verified semantics:** the sign-in
email is the account's **primary** address, and it is verified only when Bitbucket marks that
address **confirmed** (`is_confirmed`). An unconfirmed primary address fail-closes
(`unverified-email`); a consumer without the **Email** permission, or an account with no primary
address, surfaces `email-required`. Bitbucket Data Center is not covered — the endpoints are
Bitbucket Cloud's.

## Slack — Sign in with Slack (OLO-9.17)

For teams whose workspace identity is Slack rather than a formal identity provider. Apiome uses
**Sign in with Slack**, Slack's OpenID Connect flow.

1. On [api.slack.com/apps](https://api.slack.com/apps), choose **Create New App → From scratch**,
   name the app and pick the workspace that owns it (or open an existing app).
2. Under **OAuth & Permissions → Redirect URLs**, choose **Add New Redirect URL**, enter the
   callback URL and **Save URLs**:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/slack`
   - Slack accepts only `https://` redirect URLs. For local development, put an HTTPS tunnel in
     front of the UI and set `BETTER_AUTH_URL` to the tunnel's address.
3. Under **OAuth & Permissions → Scopes → User Token Scopes**, add **`openid`**, **`profile`** and
   **`email`**. No bot scopes are needed.
4. To let people from workspaces other than the app's own sign in, open **Manage Distribution**
   and **Activate Public Distribution**. Without it, only members of the app's workspace can.
5. Under **Basic Information → App Credentials**, copy the **Client ID** and **Client Secret**.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
SLACK_CLIENT_ID=<Client ID>
SLACK_CLIENT_SECRET=<Client Secret>
```

Slack is one fixed OpenID Connect issuer, so there is no issuer to configure. The endpoints come
from Slack's discovery document:

- Discovery: `https://slack.com/.well-known/openid-configuration`
- Authorize: `https://slack.com/openid/connect/authorize` with the `openid profile email` scopes
- Token: `https://slack.com/api/openid.connect.token`
- User info: `https://slack.com/api/openid.connect.userInfo` — read only when the token response
  carries no id token

The identity is keyed on the Slack user id (the `sub` claim). A person who belongs to several
Slack workspaces has one user id per workspace, so each is a separate linked identity.
**Email verified semantics:** the `email_verified` claim is honored only when it is `true`; when
it is absent or false the engine fail-closes (**link-first** — explicit link intent or an
already-bound identity). A sign-in with no `email` claim surfaces `email-required`.

## LinkedIn — Sign In with LinkedIn (OLO-9.18)

For people whose professional identity is their LinkedIn account. Apiome uses **Sign In with
LinkedIn using OpenID Connect**, LinkedIn's OpenID Connect flow.

1. On the [LinkedIn Developer Portal](https://www.linkedin.com/developers/apps), choose **Create
   app**, name the app and associate it with a **LinkedIn Page** (LinkedIn requires one), or open
   an existing app.
2. On the **Products** tab, find **Sign In with LinkedIn using OpenID Connect** and choose
   **Request access**. This adds the **`openid`**, **`profile`** and **`email`** scopes to the
   app; without it LinkedIn refuses the sign-in with an `unauthorized_scope_error`.
3. On the **Auth** tab, under **OAuth 2.0 settings**, add the callback URL to **Authorized
   redirect URLs for your app**:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/linkedin`
4. On the **Auth** tab, under **Application credentials**, copy the **Client ID** and the
   **Primary Client Secret**.
5. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
LINKEDIN_CLIENT_ID=<Client ID>
LINKEDIN_CLIENT_SECRET=<Primary Client Secret>
```

LinkedIn is one fixed OpenID Connect issuer, so there is no issuer to configure. The endpoints
come from LinkedIn's discovery document:

- Discovery: `https://www.linkedin.com/oauth/.well-known/openid-configuration`
- Authorize: `https://www.linkedin.com/oauth/v2/authorization` with the `openid profile email`
  scopes
- Token: `https://www.linkedin.com/oauth/v2/accessToken` — the client secret is sent in the
  request body; no PKCE challenge is sent
- User info: `https://api.linkedin.com/v2/userinfo` — read only when the token response carries
  no id token

The identity is keyed on the `sub` claim, a member identifier LinkedIn issues **per
application**: the same person has a different `sub` under a different LinkedIn app, so replacing
the app (rather than rotating its secret) orphans existing linked identities. The address is the
member's primary LinkedIn email.
**Email verified semantics:** the `email_verified` claim is honored only when it is `true`; when
it is absent or false the engine fail-closes (**link-first** — explicit link intent or an
already-bound identity). A sign-in with no `email` claim surfaces `email-required`.

## Discord (OLO-9.19)

For developer communities whose members already have a Discord account.

1. On the [Discord Developer Portal](https://discord.com/developers/applications), choose **New
   Application** and name it (or open an existing application). The name and icon are what
   people see on Discord's consent screen.
2. Open **OAuth2**. Under **Redirects**, choose **Add Redirect**, enter the callback URL and
   **Save Changes**:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/discord`
3. Still on **OAuth2**, under **Client information**, copy the **Client ID**, then choose **Reset
   Secret** and copy the **Client Secret** — Discord shows it once.
4. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
DISCORD_CLIENT_ID=<Client ID>
DISCORD_CLIENT_SECRET=<Client Secret>
```

No bot, and no scope selection in the portal, is needed: Apiome asks for the scopes at sign-in.
Discord's endpoints are fixed, so there is no issuer to configure:

- Authorize: `https://discord.com/api/oauth2/authorize` with the `identify email` scopes and
  `prompt=none` (a person who has already authorized the application is not asked again)
- Token: `https://discord.com/api/oauth2/token` — the client secret is sent in the request body;
  no PKCE challenge is sent
- User: `https://discord.com/api/users/@me`

The identity is keyed on the Discord user id (`id`, a snowflake); the username can change and is
never the key. The display name is `global_name`, falling back to `username`.
**Email verified semantics:** Discord reports the boolean `verified` on `/users/@me`; Apiome
normalizes it to `email_verified`, true only when `verified` is exactly `true`. An unverified
address is rejected with `unverified-email` unless the person is linking Discord explicitly or
the identity is already bound (**link-first**). An account with no email address surfaces
`email-required`.

## Salesforce — OIDC (OLO-9.20)

For organizations whose people already sign in to a Salesforce org.

1. In Salesforce **Setup**, create the app that represents Apiome: an **External Client App**
   (**External Client App Manager → New External Client App**) or a **Connected App**
   (**App Manager → New Connected App**).
2. Turn on **Enable OAuth Settings** and configure:
   - **Callback URL:** `{BETTER_AUTH_URL}/api/auth/oauth2/callback/salesforce`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/salesforce` for local dev)
   - **Selected OAuth Scopes:** **Access the identity URL service (id, profile, email, address,
     phone)** and **Access unique user identifiers (openid)**
   - Keep **Require Secret for Web Server Flow** ticked. **Require Proof Key for Code Exchange
     (PKCE)** may be ticked too — Apiome always sends a PKCE challenge.
3. Save, then copy the **Consumer Key** and **Consumer Secret** (**Manage Consumer Details**).
   Salesforce can take up to 10 minutes to start accepting a new app.
4. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
SALESFORCE_CLIENT_ID=<Consumer Key>
SALESFORCE_CLIENT_SECRET=<Consumer Secret>
# Optional — only for a My Domain or a sandbox:
# SALESFORCE_ISSUER=https://acme.my.salesforce.com
```

**The issuer is optional.** Unset, sign-in goes through `https://login.salesforce.com`,
Salesforce's shared login page for production orgs. Set `SALESFORCE_ISSUER` to:

- an org's **My Domain** — `https://acme.my.salesforce.com` — to send everyone to that org's own
  login page (its branding, and its single sign-on if it has one);
- `https://test.salesforce.com`, or a sandbox My Domain
  (`https://acme--dev.sandbox.my.salesforce.com`), to sign in against a **sandbox**.

`SALESFORCE_ISSUER` is read the way `OKTA_ISSUER` is: surrounding whitespace is trimmed, a blank
value counts as unset (so the default applies) and one trailing slash is dropped. It is the base
URL only — no path. The same value can be set from **Admin → System Configuration** (the
**Issuer** field on the Salesforce card, stored under `config.SALESFORCE_ISSUER` and overlaid onto
the env var per OLO-8.5 / OLO-10.8). Because it is optional it is never reported as missing by
boot validation or by the admin **Validate** action: the client id and secret alone enable the
provider.

The sign-in flow discovers its endpoints from
`{SALESFORCE_ISSUER}/.well-known/openid-configuration`, uses PKCE and requests the
`openid email profile` scopes. Salesforce's id token carries the profile claims only when the
app is configured to include them, so when the id token has no `email` Apiome reads
`{SALESFORCE_ISSUER}/services/oauth2/userinfo` with the access token instead; a userinfo answer
for a different `sub` than the id token's is discarded.

The identity is keyed on `sub` — the person's Salesforce **identity URL**, which names both the
org and the user, so the same username in two orgs is two identities.
**Email verified semantics:** Salesforce reports `email_verified`; it is honored when true. When
it is absent or false the engine fail-closes (**link-first** — explicit link intent or an
already-bound identity), and the sign-in is rejected with `unverified-email`. A person whose
Salesforce email address is unverified verifies it in Salesforce, or signs in another way and
links Salesforce. A sign-in with no
email at all surfaces `email-required`.

## Notion (OLO-9.21)

For product and documentation teams whose people already have a Notion account. Notion is a
**link-first** provider: read [Email verified semantics](#notion-email-verified-semantics) below
before turning it on, because nobody can *create* an Apiome account with it.

1. On Notion's [integrations page](https://www.notion.so/profile/integrations), choose **New
   integration**, name it and set its **Type** to **Public** — only a public integration has an
   OAuth client. Notion asks for a company name, a website, a privacy policy URL, a terms of use
   URL and a support email address.
2. Under **Redirect URIs**, add the callback URL:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/notion`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/notion` for local dev)
3. Under **Capabilities → User Capabilities**, choose **Read user information including email
   addresses**. Without it Notion shares no address and every sign-in ends in `email-required`.
   Apiome reads no pages or databases, so the content capabilities can be left at their minimum.
4. Copy the **OAuth Client ID** and the **OAuth Client Secret**.
5. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
NOTION_CLIENT_ID=<OAuth Client ID>
NOTION_CLIENT_SECRET=<OAuth Client Secret>
```

Notion has no scopes — what an integration may do is set by its capabilities — and its endpoints
are fixed, so there is no issuer to configure (mirroring Better Auth's `notion()` helper):

- Authorize: `https://api.notion.com/v1/oauth/authorize` with `owner=user`, so the grant is a
  user-level one that names the person who authorized it
- Token: `https://api.notion.com/v1/oauth/token` — the client id and secret are sent as HTTP
  Basic credentials; no PKCE challenge is sent
- User: the **owner user** on the token response; when it carries no email address,
  `https://api.notion.com/v1/users/me` (`bot.owner.user`), sent with `Notion-Version: 2022-06-28`

Notion's consent screen asks the person which pages to share with the integration. Apiome reads
none of them, so they can share nothing and continue.

The identity is keyed on the Notion user id (`id`, a UUID). The display name is `name` and the
picture is `avatar_url`. Only a **person** can sign in: a bot owner or a workspace-level token
carries no identity and is refused.

<a id="notion-email-verified-semantics"></a>
**Email verified semantics:** Notion returns the owner user's email address (`person.email`) but
does **not** assert a verified claim (Better Auth hard-codes `emailVerified: false`). The engine
always fail-closes (**link-first**), and `notion` is not in `AUTO_LINK_TRUSTED_PROVIDERS`
(OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the Notion card on **Linked accounts**.
  The explicit link binds the Notion identity to their account whatever its email address.
- **Subsequent sign-in** — once linked, **Sign in with Notion** signs that person in.
- **Fresh sign-up, or a first sign-in without linking** — rejected with `unverified-email`, even
  when the address matches an existing account. This is intended: the address is never used to
  join or create an account.

A Notion account that shares no email address surfaces `email-required`.

## Figma (OLO-9.22)

For design-adjacent API consumers — designers and front-end developers who already have a Figma
account. Figma is a **link-first** provider: read
[Email verified semantics](#figma-email-verified-semantics) below before turning it on, because
nobody can *create* an Apiome account with it.

1. On Figma's [developer apps page](https://www.figma.com/developers/apps), choose **Create a new
   app**, name it and pick the team or organization that owns it.
2. On the app's **OAuth credentials** tab, add the callback URL under **Redirect URLs**:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/figma`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/figma` for local dev)
3. On the **OAuth scopes** tab, select **`current_user:read`** — the one scope Apiome asks for.
   Without it Figma refuses the authorization request. Apiome reads no files, so no other scope
   is needed.
4. Copy the **Client ID** and the **Client secret**. Figma shows the secret once.
5. A new app is a draft that only members of the owning team can authorize. To let anyone sign
   in, set its audience to **Public** and **publish** it (Figma reviews public apps); a
   **Private** app serves the owning organization only.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
FIGMA_CLIENT_ID=<Client ID>
FIGMA_CLIENT_SECRET=<Client secret>
```

Figma's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`figma()` helper):

- Authorize: `https://www.figma.com/oauth` with the scope `current_user:read` and a PKCE (S256)
  challenge
- Token: `https://api.figma.com/v1/oauth/token` — the client id and secret are sent as HTTP
  Basic credentials
- User: `https://api.figma.com/v1/me`

The identity is keyed on the Figma user id (`id`). The display name is `handle` and the picture
is `img_url`; the mutable handle is never the key.

<a id="figma-email-verified-semantics"></a>
**Email verified semantics:** `/v1/me` returns the account's email address (`email`) but does
**not** assert a verified claim (Better Auth hard-codes `emailVerified: false`). The engine
always fail-closes (**link-first**), and `figma` is not in `AUTO_LINK_TRUSTED_PROVIDERS`
(OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the Figma card on **Linked accounts**.
  The explicit link binds the Figma identity to their account whatever its email address.
- **Subsequent sign-in** — once linked, **Sign in with Figma** signs that person in.
- **Fresh sign-up, or a first sign-in without linking** — rejected with `unverified-email`, even
  when the address matches an existing account. This is intended: the address is never used to
  join or create an account.

A `/v1/me` response with no email address surfaces `email-required`.

## Linear (OLO-9.23)

For product-engineering teams that track their work in Linear. Linear is a **link-first**
provider: read [Email verified semantics](#linear-email-verified-semantics) below before turning
it on, because nobody can *create* an Apiome account with it.

1. In Linear, open **Settings → API → OAuth applications** and create a new application
   ([linear.app/settings/api/applications/new](https://linear.app/settings/api/applications/new)).
   You need to be an admin of the Linear workspace that owns the application.
2. Under **Callback URLs**, add:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/linear`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/linear` for local dev)
3. Turn on **Public** to let people from other Linear workspaces sign in; leave it off to serve
   the owning workspace only.
4. Save the application and copy its **Client ID** and **Client secret**.
5. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
LINEAR_CLIENT_ID=<Client ID>
LINEAR_CLIENT_SECRET=<Client secret>
```

Linear's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`linear()` helper):

- Authorize: `https://linear.app/oauth/authorize` with the scope `read` — the only scope Apiome
  asks for. Linear has no narrower scope; Apiome uses the grant for one request, the `viewer`
  query below, and reads no issues, projects or teams. No PKCE challenge is sent.
- Token: `https://api.linear.app/oauth/token` — the client id and secret are sent in the form
  body
- User: Linear has no REST userinfo endpoint. Apiome POSTs the GraphQL query
  `query { viewer { id name email avatarUrl } }` to `https://api.linear.app/graphql`

The identity is keyed on the Linear user id (`viewer.id`, a UUID). The display name is `name`
and the picture is `avatarUrl`; the mutable name is never the key.

<a id="linear-email-verified-semantics"></a>
**Email verified semantics:** the `viewer` carries the account's email address (`email`) but
Linear does **not** assert a verified claim (Better Auth hard-codes `emailVerified: false`). The
engine always fail-closes (**link-first**), and `linear` is not in `AUTO_LINK_TRUSTED_PROVIDERS`
(OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the Linear card on **Linked accounts**.
  The explicit link binds the Linear identity to their account whatever its email address.
- **Subsequent sign-in** — once linked, **Sign in with Linear** signs that person in.
- **Fresh sign-up, or a first sign-in without linking** — rejected with `unverified-email`, even
  when the address matches an existing account. This is intended: the address is never used to
  join or create an account.

A `viewer` with no email address surfaces `email-required`. A GraphQL error, or a response with
no `viewer`, yields no identity and the sign-in is refused.

## Dropbox (OLO-9.24)

For people whose personal or work identity is their Dropbox account.

1. On the [Dropbox App Console](https://www.dropbox.com/developers/apps), choose **Create app**.
   Choose **Scoped access**, then **App folder** — Apiome reads no files, so the narrowest access
   type is enough — and name the app. The name is what people see on Dropbox's consent screen.
2. On the **Settings** tab, under **OAuth 2 → Redirect URIs**, add:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/dropbox`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/dropbox` for local dev)
3. On the **Permissions** tab, make sure **`account_info.read`** is selected (it is by default)
   and choose **Submit** if you changed anything. No other permission is needed.
4. Back on **Settings**, copy the **App key**, then choose **Show** beside **App secret** and
   copy it.
5. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
DROPBOX_CLIENT_ID=<App key>
DROPBOX_CLIENT_SECRET=<App secret>
```

A new Dropbox app has **Development** status and can be linked by a limited number of Dropbox
users; choose **Apply for production** on the **Settings** tab before opening sign-in to
everyone.

Dropbox's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`dropbox()` helper):

- Authorize: `https://www.dropbox.com/oauth2/authorize` with the scope `account_info.read` — the
  only scope Apiome asks for — and a PKCE challenge (`S256`). No `token_access_type` is sent, so
  Dropbox issues a short-lived access token and no refresh token; Apiome uses it for one request
  and keeps no Dropbox token.
- Token: `https://api.dropboxapi.com/oauth2/token` — the client id and secret are sent in the
  form body, with the PKCE verifier
- User: `https://api.dropboxapi.com/2/users/get_current_account` — an RPC endpoint, so Apiome
  sends a `POST` with no body

The identity is keyed on the Dropbox account id (`account_id`, `dbid:…`). The display name is
`name.display_name` and the picture is `profile_photo_url`; the mutable name is never the key.

**Email verified semantics:** `get_current_account` reports the boolean `email_verified`; Apiome
honors it only when it is exactly `true` — a missing, `null` or non-boolean value is unverified.
Dropbox is a **trusted** provider and `dropbox` is in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Verified address** — signs in the linked account, joins the account with the same address,
  or starts a new account.
- **Unverified address** — rejected with `unverified-email` unless the person is linking Dropbox
  explicitly or the identity is already bound (**link-first**).

An account with no email address surfaces `email-required`. A failed `get_current_account`
request, or a response with no `account_id`, yields no identity and the sign-in is refused.

## Zoom (OLO-9.25)

For organizations whose people already have a Zoom account.

1. On the [Zoom App Marketplace](https://marketplace.zoom.us/), sign in, open **Develop** and
   choose **Build App**, then **General App**. On **Basic Information**, keep the app
   **User-managed**: each person authorizes it for their own Zoom account.
2. Still on **Basic Information**, under **OAuth Information**, set the **OAuth Redirect URL** and
   add the same URL to the **OAuth Allow Lists**:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/zoom`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/zoom` for local dev)
3. On **Scopes**, choose **Add Scopes** and add **`user:read:user`** (*View a user*). No other
   scope is needed. Zoom takes an app's scopes from this page, so Apiome sends no scope parameter.
4. Back on **Basic Information**, copy the **Client ID** and the **Client Secret** from **App
   Credentials**. Zoom shows a **Development** and a **Production** pair; use the pair that
   matches the redirect URL you entered.
5. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
ZOOM_CLIENT_ID=<Client ID>
ZOOM_CLIENT_SECRET=<Client Secret>
```

An app that is not published can be authorized only by people in the Zoom account that built it.
That is enough for a single organization; publish the app on the Zoom App Marketplace before
opening sign-in to people in other Zoom accounts.

Zoom's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's `zoom()`
helper):

- Authorize: `https://zoom.us/oauth/authorize` with a PKCE challenge (`S256`) and no scope
  parameter
- Token: `https://zoom.us/oauth/token` — the client id and secret are sent in the form body, with
  the PKCE verifier
- User: `https://api.zoom.us/v2/users/me`

The identity is keyed on the Zoom user id (`id`). The display name is `display_name` and the
picture is `pic_url`; the mutable name is never the key. Apiome uses the access token for that
one request and keeps no Zoom token.

**Email verified semantics:** `/v2/users/me` reports the integer `verified` — `1` when the
account's email address is verified, `0` when it is not. Apiome normalizes it to `email_verified`
and honors it only when it is exactly the number `1`; a missing, `null`, boolean or string value
is unverified. Zoom is a **trusted** provider and `zoom` is in `AUTO_LINK_TRUSTED_PROVIDERS`
(OLO-9.16):

- **Verified address** — signs in the linked account, joins the account with the same address,
  or starts a new account.
- **Unverified address** — rejected with `unverified-email` unless the person is linking Zoom
  explicitly or the identity is already bound (**link-first**).

A user with no email address surfaces `email-required`. A failed `/v2/users/me` request — for
example when the app lacks the `user:read:user` scope — or a response with no string `id`, yields
no identity and the sign-in is refused.

## Hugging Face — Sign in with Hugging Face (OLO-9.26)

For machine-learning teams whose people already have a Hugging Face account. Apiome uses **Sign
in with Hugging Face**, Hugging Face's OpenID Connect flow.

1. Sign in to Hugging Face and open
   [huggingface.co/settings/applications/new](https://huggingface.co/settings/applications/new)
   to create an OAuth app. On a Team or Enterprise plan, an organization admin can create it
   under the organization's settings (**OAuth Apps**) instead, so the app belongs to the
   organization rather than to one person.
2. Create the app **with a client secret**. Hugging Face also offers public apps with no secret;
   Apiome needs the secret.
3. Select the **`openid`**, **`profile`** and **`email`** scopes. No other scope is needed.
   Without `email`, Hugging Face sends no address and the sign-in fails with `email-required`.
4. Add the redirect URI. Hugging Face requires an exact match:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/huggingface`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/huggingface` for local dev)
5. Copy the app's client ID and client secret.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
HUGGINGFACE_CLIENT_ID=<client ID>
HUGGINGFACE_CLIENT_SECRET=<client secret>
```

Hugging Face is one fixed OpenID Connect issuer, so there is no issuer to configure. The endpoints
come from Hugging Face's discovery document (the scopes and PKCE mirror Better Auth's
`huggingface()` helper):

- Discovery: `https://huggingface.co/.well-known/openid-configuration`
- Authorize: `https://huggingface.co/oauth/authorize` with the `openid profile email` scopes and
  a PKCE challenge (`S256`)
- Token: `https://huggingface.co/oauth/token` — the client id and secret are sent in the form
  body, with the PKCE verifier
- User info: `https://huggingface.co/oauth/userinfo`

The identity is keyed on the `sub` claim, the Hugging Face user id. The display name is `name`,
or `preferred_username` (the Hugging Face username) when the account has no full name; the
picture is `picture`. The mutable username is never the key. Apiome uses the access token for
that one request and keeps no Hugging Face token; it reads no models, datasets or Spaces.

**Email verified semantics:** the `email_verified` claim is honored only when it is `true`.
Hugging Face is a **trusted** provider and `huggingface` is in `AUTO_LINK_TRUSTED_PROVIDERS`
(OLO-9.16):

- **Verified address** — signs in the linked account, joins the account with the same address,
  or starts a new account.
- **Unverified address** (the claim is absent or false) — rejected with `unverified-email` unless
  the person is linking Hugging Face explicitly or the identity is already bound
  (**link-first**).

A sign-in with no `email` claim surfaces `email-required`. A failed userinfo request, or a
response with no string `sub`, yields no identity and the sign-in is refused.

## Vercel — Sign in with Vercel (OLO-9.27)

For frontend and API teams whose people already have a Vercel account. Apiome uses **Sign in with
Vercel**, Vercel's OAuth 2.0 / OpenID Connect flow.

1. In the Vercel dashboard, open your team's **Settings**, select **Apps** and click **Create**.
   Give the app a name (unique across Vercel — people see it on the consent page) and click
   **Save**. The app belongs to the team, not to one person.
2. On the app's **Manage** page, under **Authorization Callback URLs**, enter the callback URL and
   click **Add**:
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/vercel`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/vercel` for local dev)
3. Open **Permissions** and enable **openid**, **email** and **profile**, then click **Save**. No
   other scope or permission is needed, and **offline_access** can stay off — Apiome keeps no
   Vercel token. Apiome asks for exactly these three scopes; Vercel rejects the sign-in with
   `invalid_scope` when the app does not have **email** or **profile**.
4. Open **Authentication** and make sure **client_secret_post** is selected — Apiome sends the
   client secret in the form body of the token request.
5. Click **Generate** to create a client secret and copy it; copy the app's **Client ID** from the
   same page.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
VERCEL_CLIENT_ID=<Client ID>
VERCEL_CLIENT_SECRET=<client secret>
```

By default anyone with a Vercel account can sign in through the app. To limit sign-in to members of
the owning team, set **Sign-In Access** to **Members of the team** on the app's **General** page;
everyone else then sees Vercel's `access_denied` error.

Vercel's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`vercel()` helper; they match Vercel's discovery document at
`https://vercel.com/.well-known/openid-configuration`):

- Authorize: `https://vercel.com/oauth/authorize` with the `openid email profile` scopes and a
  PKCE challenge (`S256`) — Vercel requires PKCE
- Token: `https://api.vercel.com/login/oauth/token` — the client id and secret are sent in the form
  body, with the PKCE verifier
- User info: `https://api.vercel.com/login/oauth/userinfo`

The identity is keyed on the `sub` claim, the Vercel user id. The display name is `name`, or
`preferred_username` (the Vercel username) when the account has no full name; the picture is
`picture`. The mutable username is never the key. Apiome uses the access token for that one
request and keeps no Vercel token; it reads no projects, deployments or teams.

**Email verified semantics:** Vercel's userinfo resource reports the boolean `email_verified`.
Apiome re-stamps it fail-closed and honors it only when it is exactly `true`; a missing, `null`,
numeric or string value is unverified. Vercel's discovery document leaves `email_verified` out
of `claims_supported`, so the claim is read from the userinfo response only, never assumed. Vercel
was a provisional **link-first** provider until this was confirmed; it is now a **trusted**
provider and `vercel` is in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Verified address** — signs in the linked account, joins the account with the same address,
  or starts a new account.
- **Unverified address** — rejected with `unverified-email` unless the person is linking Vercel
  explicitly or the identity is already bound (**link-first**).

A sign-in with no `email` claim surfaces `email-required`. A failed userinfo request, or a response
with no string `sub`, yields no identity and the sign-in is refused.

## Railway — Login with Railway (OLO-9.28)

For indie and startup API builders who deploy on Railway. Apiome uses **Login with Railway**,
Railway's OAuth 2.0 / OpenID Connect flow. Railway is a **link-first** provider: read
[Email verified semantics](#railway-email-verified-semantics) below before turning it on, because
nobody can *create* an Apiome account with it.

1. In the Railway dashboard, open your workspace's **Settings**, select **Developer** and click
   **New OAuth App**. Only a workspace admin can create one. Give the app a name people will
   recognize — Railway shows it on the consent screen.
2. Add the redirect URI (Railway requires an exact match of scheme, host, port and path):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/railway`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/railway` for local dev)
3. Choose the **Web** app type. A **Native** app has no client secret, and Apiome cannot use it.
4. Create the app and copy the client secret straight away — Railway shows it only once. Copy the
   client ID from the same page.
5. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
RAILWAY_CLIENT_ID=<client ID>
RAILWAY_CLIENT_SECRET=<client secret>
```

Railway's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`railway()` helper; they match Railway's discovery document at
`https://backboard.railway.com/.well-known/openid-configuration`):

- Authorize: `https://backboard.railway.com/oauth/auth` with the `openid email profile` scopes
  and a PKCE challenge (`S256`). Apiome asks for no `offline_access`, workspace or project scope:
  it keeps no Railway token and reads no workspaces, projects or deployments.
- Token: `https://backboard.railway.com/oauth/token` — the client id and secret are sent as HTTP
  Basic, with the PKCE verifier
- User info: `https://backboard.railway.com/oauth/me` — Railway puts no claims in the id token

The identity is keyed on the `sub` claim, the Railway user id. The display name is `name` and the
picture is `picture`.

<a id="railway-email-verified-semantics"></a>
**Email verified semantics:** `/oauth/me` carries the account's email address (`email`), but
Railway does **not** document a verified claim: its claims table lists only `sub`, `email`, `name`
and `picture`, and Better Auth hard-codes `emailVerified: false`. Railway's discovery document
names `email_verified` in `claims_supported`, but because `/oauth/me` is not documented to return
it, Apiome drops any such field rather than trust it. The engine always fail-closes
(**link-first**), and `railway` is not in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16). Railway was a
provisional **link-first** provider until this was confirmed; the class is now decided:

- **Linking** — a signed-in person chooses **Link** on the Railway card on **Linked accounts**.
  The explicit link binds the Railway identity to their account whatever its email address.
- **Subsequent sign-in** — once linked, **Sign in with Railway** signs that person in.
- **Fresh sign-up, or a first sign-in without linking** — rejected with `unverified-email`, even
  when the address matches an existing account. This is intended: the address is never used to
  join or create an account.

A sign-in with no `email` claim surfaces `email-required`. A failed `/oauth/me` request, or a
response with no string `sub`, yields no identity and the sign-in is refused.

## HubSpot — OAuth (OLO-9.29)

For the marketing and CRM-adjacent teams that consume APIs. Apiome uses HubSpot's OAuth 2.0 flow
for apps. HubSpot is a **link-first** provider: read
[Email verified semantics](#hubspot-email-verified-semantics) below before turning it on, because
nobody can *create* an Apiome account with it.

1. In a [HubSpot developer account](https://developers.hubspot.com/), create a **public app** (an
   app that uses OAuth). Give it a name people will recognize — HubSpot shows it on the consent
   screen.
2. On the app's **Auth** settings, add the redirect URL (HubSpot requires an exact match):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/hubspot`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/hubspot` for local dev; HubSpot accepts
     plain `http` only for `localhost`)
3. Keep **`oauth`** as the only required scope. Apiome asks for nothing else, and a request that
   omits a scope the app marks required is refused by HubSpot.
4. Copy the **Client ID** and **Client secret** from the same page.
5. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
HUBSPOT_CLIENT_ID=<client ID>
HUBSPOT_CLIENT_SECRET=<client secret>
```

HubSpot's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`hubspot()` helper):

- Authorize: `https://app.hubspot.com/oauth/authorize` with the `oauth` scope. Apiome asks for no
  CRM scope: it keeps no HubSpot token and reads no contacts, companies, deals or other HubSpot
  data. HubSpot asks the person which HubSpot account to connect; any of them works.
- Token: `https://api.hubapi.com/oauth/v1/token` — the client id and secret are sent in the form
  body. No PKCE challenge is sent (like the helper; Better Auth enforces `state`).
- Token info: `https://api.hubapi.com/oauth/v1/access-tokens/{token}` — HubSpot has no userinfo
  endpoint, so the signed-in user is read from the access token's metadata.

The identity is keyed on `user_id` (falling back to `signed_access_token.userId`), the HubSpot user
id, which stays the same whichever HubSpot account the person connected. `user` — the email
address the person signs in to HubSpot with — is both the email and the display name; HubSpot
returns no name or picture. The token-info response echoes the access token; Apiome keeps only the
identity fields and never stores it.

<a id="hubspot-email-verified-semantics"></a>
**Email verified semantics:** token info carries the user's email address (`user`), but **no**
verified claim, and Better Auth hard-codes `emailVerified: false`. Any `email_verified` field in a
response is dropped rather than trusted. The engine always fail-closes (**link-first**), and
`hubspot` is not in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the HubSpot card on **Linked accounts**.
  The explicit link binds the HubSpot identity to their account whatever its email address.
- **Subsequent sign-in** — once linked, **Sign in with HubSpot** signs that person in.
- **Fresh sign-up, or a first sign-in without linking** — rejected with `unverified-email`, even
  when the address matches an existing account. This is intended: the address is never used to
  join or create an account.

A sign-in with no `user` email surfaces `email-required`. A failed token-info request, or a
response with no usable user id, yields no identity and the sign-in is refused.

## Sign in with Apple (OLO-9.30)

For individual developers on Apple hardware, and the most-requested consumer sign-in. Apiome uses
Sign in with Apple on the web (OpenID Connect on the `https://appleid.apple.com` issuer). Apple is a
**trusted** provider: a verified Apple email signs in, links or creates an account. Read
[Hide My Email relay addresses](#apple-relay-addresses) before turning it on.

Unlike every other provider, Apple has **no static client secret**. You give Apiome a private key,
and Apiome signs a short-lived client secret (an ES256 JWT) with it for each sign-in.

1. In [Certificates, Identifiers & Profiles](https://developer.apple.com/account/resources/) of an
   Apple Developer Program account, open **Identifiers**, select your App ID (create one if you
   have none) and turn on **Sign in with Apple**.
2. Create a **Services ID** (Identifiers → **+** → **Services IDs**). Its identifier — for example
   `com.example.apiome.web` — is the client ID. Turn on **Sign in with Apple** for it, choose
   **Configure**, pick the App ID as the primary App ID, and add:
   - **Domains and Subdomains**: the host of `BETTER_AUTH_URL` (e.g. `apiome.example.com`)
   - **Return URLs**: `{BETTER_AUTH_URL}/api/auth/oauth2/callback/apple`
     (e.g. `https://apiome.example.com/api/auth/oauth2/callback/apple`)

   Apple accepts only `https` return URLs on a real domain — not `localhost` or an IP address — so
   test locally through an HTTPS tunnel whose host you register here.
3. Create a key (Keys → **+**), turn on **Sign in with Apple**, configure it with the same primary
   App ID, and register it. **Download the `.p8` file** — Apple offers it only once — and note the
   **Key ID** shown on the key.
4. Note your **Team ID** (top right of the developer account, or **Membership details**).
5. Set the env vars (or save them on the admin console's **Auth providers** page, where the
   **Services ID**, **Private key (.p8)**, **Team ID** and **Key ID** fields map to them):

```bash
APPLE_CLIENT_ID=com.example.apiome.web
APPLE_TEAM_ID=A1B2C3D4E5
APPLE_KEY_ID=ABC123DEFG
# The whole .p8 file. In a .env file keep it on one line with \n for the line breaks:
APPLE_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\nMIGTAgEAMBMG…\n-----END PRIVATE KEY-----"
```

The private key is stored as the provider's **sealed, write-only secret** — encrypted at rest and
never shown again, like every other client secret. The Team ID and Key ID are ordinary settings.
Paste the `.p8` file as it is: the single-line admin field drops its line breaks, and Apiome reads
the key either way (with or without the `BEGIN`/`END` lines). A key that is not an EC P-256 private
key is refused at sign-in, and the reason — never the key — is logged.

Apple's endpoints are fixed, so there is no issuer to configure:

- Authorize: `https://appleid.apple.com/auth/authorize` with the scopes `name email` and
  `response_mode=form_post` (Apple requires `form_post` whenever it is asked for the name or
  email). No PKCE challenge is sent (like Better Auth's `apple()` helper; Better Auth enforces
  `state`).
- Callback: Apple **POSTs** the result to the return URL. Apiome answers that POST with a `303`
  redirect to the same URL as a GET, which Better Auth then completes; the browser's follow-up GET
  carries the sign-in's state cookie, which a cross-site POST cannot.
- Token: `https://appleid.apple.com/auth/token` — the code is exchanged with a client secret
  minted for this one exchange.

<a id="apple-client-secret"></a>
**The client-secret JWT, and rotating it:** for every code exchange Apiome signs a new JWT with the
`.p8` key — header `{"alg":"ES256","kid":"<Key ID>"}`, claims `iss` = Team ID, `sub` = Services ID,
`aud` = `https://appleid.apple.com`, `iat` = now and `exp` = now + 5 minutes. Apple allows up to six
months, but nothing is cached, so **there is no client secret to expire or rotate**. What you
rotate is the key:

1. Create a new Sign in with Apple key in the developer account and download its `.p8` file.
2. Save the new **Private key (.p8)** and **Key ID** together (admin console, or the two env vars
   and a restart). The next sign-in signs with the new key — saving any of the Team ID, Key ID or
   key rebuilds the sign-in configuration on the next request.
3. Revoke the old key in the developer account. Apple allows two active Sign in with Apple keys
   per team, so the old one keeps working until you revoke it, and nobody is signed out.

Revoke a key at once if its `.p8` file may have leaked, then save the new one.

**Identity and profile:** the identity is keyed on the id token's `sub`, Apple's stable user id for
your team. Apiome checks that the id token's `iss` is `https://appleid.apple.com` and its `aud` is
the Services ID, or it refuses the sign-in. The email comes only from the id token. Apple sends the
person's **name only once** — in the `user` field of the first authorization — and never in the
id token. Apiome reads just the first and last name from that field (never its email, which is
not signed) and stores it then: on the new account, on the pending sign-up, or on the linked
identity. Later sign-ins carry no name, so the account keeps the one stored at first consent. If the first consent was lost (for example, the sign-in was
abandoned after Apple's screen), the person can remove Apiome under **Sign in with Apple** in their
Apple Account settings and sign in again to send the name once more.

**Email verified semantics:** the id token carries `email_verified`, which Apple sends as `true` or
the string `"true"`; anything else is unverified (fail-closed). `apple` is in
`AUTO_LINK_TRUSTED_PROVIDERS`, so:

- a verified address matching an existing account **auto-links** that account;
- a verified address with no account **creates one** (subject to the sign-up policy);
- an unverified address is rejected with `unverified-email`;
- once bound, later sign-ins resolve through the identity (`sub`), even if Apple's id token omits
  the email.

<a id="apple-relay-addresses"></a>
**Hide My Email relay addresses:** a person may choose **Hide My Email**, and Apple then shares a
private relay address such as `x7k2p9q4mz@privaterelay.appleid.com` (the id token's
`is_private_email` is `true`). The relay address is verified and forwards to the person's real
inbox, so Apiome treats it like any verified address, and records `is_private_email` on the linked
identity. What it means for linking:

- **It never matches an existing account.** A person who already has an Apiome account under their
  real address and signs in with Apple using Hide My Email gets a **new** account under the relay
  address, not their existing one. To use Apple with an existing account, sign in the usual way
  first and choose **Link** on the Apple card on **Linked accounts**; from then on **Sign in with
  Apple** signs that account in, whichever address Apple shares.
- **It is per app.** The same Apple Account gets a different relay address for each Services ID's
  team, so changing team creates new identities.
- **Mail to it must come from a registered domain.** Apple's relay delivers only mail from domains
  you register under **Sign in with Apple for Email Communication** in the developer account (with
  SPF set up). Register the domain Apiome sends invitations and notifications from, or that mail to
  relay addresses is dropped.
- **A sign-up domain allowlist refuses it.** If the sign-up policy restricts new accounts to
  certain email domains, `privaterelay.appleid.com` is not one of them, so relay addresses cannot
  create accounts; linking still works.

## Facebook — Facebook Login (OLO-9.31)

For the many people whose main consumer identity is Facebook. Apiome uses Facebook Login's OAuth
2.0 web flow. Facebook is a **link-first** provider: read
[Email verified semantics](#facebook-email-verified-semantics) below before turning it on, because
nobody can *create* an Apiome account with it.

1. In [Meta for Developers](https://developers.facebook.com/apps/), create an app with the
   **Authenticate and request data from users with Facebook Login** use case. Give it a name people
   will recognize — Facebook shows it on the consent screen.
2. Under **Facebook Login → Settings**, add the callback to **Valid OAuth Redirect URIs**
   (Facebook requires an exact match and HTTPS):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/facebook`
     (`http://localhost` callbacks work only while the app is in development mode)
3. Keep the **`email`** and **`public_profile`** permissions — the only ones Apiome asks for.
4. Under **App settings → Advanced**, leave **Require App Secret** off: Apiome reads the profile
   with the person's access token and sends no `appsecret_proof`.
5. Copy the **App ID** and **App secret** from **App settings → Basic**.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
FACEBOOK_CLIENT_ID=<App ID>
FACEBOOK_CLIENT_SECRET=<App secret>
```

7. Until the app is switched to **Live**, only people with a role on it (administrators,
   developers, testers) can sign in.

Facebook's endpoints are fixed (Graph API v24.0), so there is no issuer to configure (mirroring
Better Auth's `facebook()` helper):

- Authorize: `https://www.facebook.com/v24.0/dialog/oauth` with the `email public_profile` scopes.
  Apiome keeps no Facebook token and reads no pages, posts, friends or other Facebook data.
- Token: `https://graph.facebook.com/v24.0/oauth/access_token` — the App ID and App secret are sent
  in the form body. No PKCE challenge is sent (like the helper; Better Auth enforces `state`).
- Token check: `https://graph.facebook.com/debug_token`, authenticated with the app access token
  `<App ID>|<App secret>`. Graph `/me` answers for a token minted to *any* Facebook app, so —
  as the helper does — the token must be valid, issued to this App ID, and tied to a user before
  Apiome reads the profile.
- Profile: `https://graph.facebook.com/me?fields=id,name,email,picture`, with the access token as
  a bearer token. Its `id` must be the user the token check named.

The identity is keyed on `id`, the person's app-scoped Facebook user id: it stays the same for this
app, but is different for each Meta app, so replacing the app (rather than rotating its secret)
creates new identities and people link Facebook again. `name` is the display name and
`picture.data.url` the avatar.

<a id="facebook-email-verified-semantics"></a>
**Email verified semantics:** Graph returns the person's email address (`email`), but **no**
verified claim. Any `email_verified` field in a response is dropped rather than trusted (Better
Auth's helper would honor one). The engine always fail-closes (**link-first**), and `facebook` is
not in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the Facebook card on **Linked accounts**.
  The explicit link binds the Facebook identity to their account whatever its email address.
- **Subsequent sign-in** — once linked, **Sign in with Facebook** signs that person in.
- **Fresh sign-up, or a first sign-in without linking** — rejected with `unverified-email`, even
  when the address matches an existing account. This is intended: the address is never used to
  join or create an account. Revisit only with a documented policy decision.

A sign-in with no `email` — the person declined the `email` permission, or their Facebook account
has only a phone number — surfaces `email-required`. A token that fails the check, a failed `/me`
request, or a `/me` `id` that is not the token's user yields no identity and the sign-in is
refused.

## X / Twitter — X OAuth 2.0 (OLO-9.32)

For the developer-adjacent audience that lives on X. Apiome uses X's OAuth 2.0 authorization-code
flow with PKCE. X is a **link-first** provider, and often shares **no email address at all**: read
[Email semantics](#twitter-email-semantics) below before turning it on, because nobody can
*create* an Apiome account with it.

1. In the [X Developer Portal](https://developer.x.com/en/portal/dashboard), open your app (or
   create one in a project) and choose **User authentication settings → Set up**.
2. Turn on **OAuth 2.0** and choose **Web App, Automated App or Bot** as the type of app — a
   confidential client, which has a client secret. A **Native App** has none, and Apiome cannot
   use it.
3. Add the callback under **Callback URI / Redirect URL** (X requires an exact match):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/twitter`
4. Fill in **Website URL**. To receive email addresses, turn on **Request email from users**, which
   also needs a **Privacy policy** and **Terms of service** URL.
5. Save, then copy the OAuth 2.0 **Client ID** and **Client Secret** that X shows (also under
   **Keys and tokens → OAuth 2.0 Client ID and Client Secret**). These are not the OAuth 1.0a
   API key and secret.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
TWITTER_CLIENT_ID=<OAuth 2.0 Client ID>
TWITTER_CLIENT_SECRET=<OAuth 2.0 Client Secret>
```

X's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's `twitter()`
helper):

- Authorize: `https://x.com/i/oauth2/authorize` with the `users.read tweet.read users.email`
  scopes and a PKCE (`S256`) challenge, which X requires. The helper's `offline.access` is not
  asked for: Apiome keeps no X token and posts or reads no posts, followers or messages.
  (`tweet.read` is asked for only because X requires it to read the signed-in user.)
- Token: `https://api.x.com/2/oauth2/token` — the Client ID and Client Secret are sent as HTTP
  Basic.
- Profile: `https://api.x.com/2/users/me?user.fields=profile_image_url`, with the access token as a
  bearer token. Its `data.id` keys the identity.
- Email: `https://api.x.com/2/users/me?user.fields=confirmed_email`, a second request as the helper
  makes. A failed request, or one that answers for a different `data.id`, only leaves the email out.

The identity is keyed on `data.id`, the numeric X user id, which stays the same when the person
changes their `@username`. `data.name` is the display name (the `@username` when it is empty) and
`data.profile_image_url` the avatar.

<a id="twitter-email-semantics"></a>
**Email semantics:** X returns `confirmed_email` only when **Request email from users** is on and
the person granted `users.email` — so it is **often missing**. When it is present, Apiome does not
treat it as verified: the profile never carries `email_verified` (Better Auth's helper marks a
`confirmed_email` as verified; Apiome does not), and any field of that name is dropped. Unlike the
helper, the `@username` is never used in place of a missing email. The engine always fail-closes
(**link-first**), and `twitter` is not in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the X card on **Linked accounts**. The
  explicit link binds the X identity to their account, with or without an email address.
- **Subsequent sign-in** — once linked, **Continue with X (Twitter)** signs that person in, with or
  without an email address (the account's own address is used).
- **Fresh sign-in with no email** — rejected with `email-required` (`OAuthEmailRequired`).
- **Fresh sign-up, or a first sign-in without linking, with an email** — rejected with
  `unverified-email`, even when the address matches an existing account. This is intended: the
  address is never used to join or create an account. Revisit only with a documented policy
  decision.

A failed profile request, or a profile with no string `data.id`, yields no identity and the
sign-in is refused.

## Reddit (OLO-9.33)

For the developer communities on Reddit. Apiome uses Reddit's OAuth 2.0 authorization-code flow.
Reddit is a **link-only** provider: it shares **no email address at all**, so read
[Email semantics](#reddit-email-semantics) below before turning it on — nobody can *create* an
Apiome account with it.

1. Signed in to Reddit, open [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) and choose
   **create another app…** (or **are you a developer? create an app…**).
2. Give it a **name**, choose **web app** — a confidential client, which has a secret. An
   **installed app** has none, and Apiome cannot use it.
3. Set **redirect uri** to the callback (Reddit requires an exact match):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/reddit`
4. Choose **create app**. The **client ID** is the string under the app's name (below
   **web app**); the **secret** is labeled **secret**.
5. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
REDDIT_CLIENT_ID=<client ID>
REDDIT_CLIENT_SECRET=<secret>
```

Reddit's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`reddit()` helper):

- Authorize: `https://www.reddit.com/api/v1/authorize` with the `identity` scope (the helper's
  default and the only one `/api/v1/me` needs) and `duration=temporary`, so Reddit issues no
  refresh token — Apiome keeps no Reddit token and reads no posts, comments, subreddits or
  messages. No PKCE challenge is sent; Better Auth enforces `state`.
- Token: `https://www.reddit.com/api/v1/access_token` — the client ID and secret are sent as HTTP
  Basic.
- Profile: `https://oauth.reddit.com/api/v1/me`, with the access token as a bearer token and
  Apiome's `User-Agent` (Reddit refuses requests without one).

The identity is keyed on `id`, Reddit's base-36 account id, which never changes. `name` is the
username, and `icon_img` the avatar (its HTML-escaped query string dropped, as the helper does).

<a id="reddit-email-semantics"></a>
**Email semantics:** Reddit's API exposes `has_verified_email` — whether the account *has* a
verified address — but never the address itself. Apiome therefore never has an email for a
Reddit sign-in. Better Auth's helper puts `oauth_client_id` in the email slot and
`has_verified_email` in `emailVerified`; Apiome uses neither: the profile carries no `email` and no
`email_verified`. The engine always fail-closes (**link-only**), and `reddit` is not in
`AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the Reddit card on **Linked accounts**. The
  explicit link binds the Reddit identity to their account.
- **Subsequent sign-in** — once linked, **Continue with Reddit** signs that person in (the
  account's own address is used).
- **Fresh sign-in or sign-up** — rejected with `email-required` (`OAuthEmailRequired`), whatever
  `has_verified_email` says.

A failed profile request, or a profile with no string `id`, yields no identity and the sign-in is
refused.

## Spotify (OLO-9.34)

For the developer communities on Spotify. Apiome uses Spotify's OAuth 2.0 authorization-code flow
with PKCE. Spotify is a **link-first** provider: it documents the `/v1/me` email as
**unverified**, so read [Email semantics](#spotify-email-semantics) below before turning it on —
nobody can *create* an Apiome account with it.

1. Signed in to Spotify, open the
   [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and choose
   **Create app**.
2. Give it an **App name** and **App description**, and under **Which API/SDKs are you planning
   to use?** tick **Web API**.
3. Add the callback under **Redirect URIs** (Spotify requires an exact match):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/spotify`

   Spotify accepts only `https` redirect URIs, except loopback addresses such as
   `http://127.0.0.1:3000/…` — `localhost` itself is refused.
4. Accept the terms and choose **Save**. On the app's **Settings** page the **Client ID** is shown;
   choose **View client secret** for the **Client secret**.
5. Until the app has an extended quota, only people added under **User Management** (up to 25)
   can sign in with it.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
SPOTIFY_CLIENT_ID=<Client ID>
SPOTIFY_CLIENT_SECRET=<Client secret>
```

Spotify's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`spotify()` helper):

- Authorize: `https://accounts.spotify.com/authorize` with the `user-read-email` scope (the
  helper's default) and a PKCE `S256` challenge. Apiome reads no playlists, library, listening
  history or playback.
- Token: `https://accounts.spotify.com/api/token` — the client ID and secret are sent in the form
  body. Apiome keeps no Spotify token.
- Profile: `https://api.spotify.com/v1/me`, with the access token as a bearer token.

The identity is keyed on `id`, the Spotify user ID, which never changes. `display_name` is the
name (it may be missing), and the first entry of `images` the picture.

<a id="spotify-email-semantics"></a>
**Email semantics:** Spotify's Web API reference documents the `/v1/me` `email` as *unverified* —
Spotify does not check that the person owns it — and Better Auth's helper hard-codes
`emailVerified: false`. Apiome never trusts it: the profile carries no `email_verified` (any such
field in the body is dropped). The engine fail-closes (**link-first**), and `spotify` is not in
`AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the Spotify card on **Linked accounts**.
  The explicit link binds the Spotify identity to their account.
- **Subsequent sign-in** — once linked, **Continue with Spotify** signs that person in.
- **Fresh sign-in or sign-up** — rejected with `unverified-email`, even
  when the email matches an existing account; with no email, `email-required`
  (`OAuthEmailRequired`).

A failed profile request, or a profile with no string `id`, yields no identity and the sign-in is
refused.

## Twitch (OLO-9.35)

For the developer-streaming communities on Twitch. Apiome uses Twitch's OpenID Connect
authorization-code flow.

1. Signed in to Twitch (the account needs two-factor authentication turned on), open the
   [Twitch Developer Console](https://dev.twitch.tv/console/apps) and choose **Register Your
   Application**.
2. Give it a **Name** and pick a **Category** (for example **Website Integration**).
3. Add the callback under **OAuth Redirect URLs** (Twitch requires an exact match):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/twitch`
     (e.g. `http://localhost:3000/api/auth/oauth2/callback/twitch` for local dev — Twitch accepts
     `http` only for `localhost`)
4. Set **Client Type** to **Confidential** — a **Public** client has no secret, and Apiome needs
   one. Choose **Create**.
5. Choose **Manage** on the new application. The **Client ID** is shown there; choose **New
   Secret** for the **Client Secret** (Twitch shows it once).
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
TWITCH_CLIENT_ID=<Client ID>
TWITCH_CLIENT_SECRET=<Client Secret>
```

Twitch is one fixed OpenID Connect issuer, so there is no issuer to configure. The endpoints come
from Twitch's discovery document (the scopes and claims request mirror Better Auth's `twitch()`
helper):

- Discovery: `https://id.twitch.tv/oauth2/.well-known/openid-configuration`
- Authorize: `https://id.twitch.tv/oauth2/authorize` with the `openid user:read:email` scopes and a
  `claims` request for `email`, `email_verified`, `preferred_username` and `picture` in the id
  token — Twitch leaves them out unless they are asked for. Twitch documents no PKCE support, so
  no challenge is sent.
- Token: `https://id.twitch.tv/oauth2/token` — the client ID and secret are sent in the form body.
  Apiome keeps no Twitch token.

The claims come from the id token, which must be issued by `https://id.twitch.tv/oauth2` to this
application (`aud` includes `TWITCH_CLIENT_ID`). The identity is keyed on the `sub` claim, the
Twitch user ID; `preferred_username` is the name and `picture` the picture. The login name can
change and is never the key. Apiome reads no streams, follows, chat or subscriptions.

**Email verified semantics:** the `email_verified` claim is honored only when it is `true`. Twitch
is a **trusted** provider and `twitch` is in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Verified address** — signs in the linked account, joins the account with the same address,
  or starts a new account.
- **Unverified address** (the claim is absent or false) — rejected with `unverified-email` unless
  the person is linking Twitch explicitly or the identity is already bound (**link-first**).

A sign-in with no `email` claim surfaces `email-required`. A missing or unparseable id token, one
from another issuer or for another application, or one with no string `sub` yields no identity
and the sign-in is refused.

## TikTok (OLO-9.36)

For the developer and creator communities on TikTok. Apiome uses TikTok Login Kit's OAuth 2.0
authorization-code flow. TikTok is a **link-only** provider: it shares **no email address at
all**, so read [Email semantics](#tiktok-email-semantics) below before turning it on — nobody can
*create* an Apiome account with it.

1. Signed in to [TikTok for Developers](https://developers.tiktok.com/apps), choose **Connect an
   app** (or **Manage apps → Connect an app**) and create an app.
2. Under **Platforms** choose **Web** and fill in the **Website URL**, **Terms of Service URL**
   and **Privacy Policy URL** TikTok asks for.
3. Under **Products** add **Login Kit**, and under **Login Kit → Redirect URI** add the callback
   (TikTok requires an exact match and an `https` address):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/tiktok`
4. Under **Scopes** keep **user.info.profile** (with **user.info.basic**, which Login Kit always
   includes). Apiome asks for nothing else.
5. Submit the app for review. Until TikTok approves it, only the accounts you add under
   **Sandbox → Target users** can sign in.
6. The **Client key** and **Client secret** are on the app's **App details** page. TikTok calls
   the client ID a *client key*, so Apiome's env var is `TIKTOK_CLIENT_KEY`. Set the env vars (or
   save them on the admin console's **Auth providers** page, where the key goes in the **client
   ID** field):

```bash
TIKTOK_CLIENT_KEY=<Client key>
TIKTOK_CLIENT_SECRET=<Client secret>
```

TikTok's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's
`tiktok()` helper):

- Authorize: `https://www.tiktok.com/v2/auth/authorize` with the `user.info.profile` scope (the
  helper's default) and the client key as the `client_key` parameter. No PKCE challenge is sent;
  Better Auth enforces `state`.
- Token: `https://open.tiktokapis.com/v2/oauth/token/` — a form-encoded POST carrying
  `client_key` and `client_secret`. TikTok does not accept the standard `client_id`, so Apiome
  runs this exchange itself rather than through the generic OAuth plugin. Apiome keeps no TikTok
  token.
- Profile: `https://open.tiktokapis.com/v2/user/info/?fields=open_id,avatar_large_url,display_name,username`,
  with the access token as a bearer token.

The identity is keyed on `open_id`, the person's stable id within this TikTok app.
`display_name` is the name (the `username` when there is none), and `avatar_large_url` the
picture. Apiome reads no videos, followers, likes or messages.

<a id="tiktok-email-semantics"></a>
**Email semantics:** TikTok's user-info API returns no email address. Better Auth's helper puts
the `username` in the email slot when there is no email; Apiome never does — the profile carries
no `email` and no `email_verified`, and an `email` field in the response is ignored. The engine
always fail-closes (**link-only**), and `tiktok` is not in `AUTO_LINK_TRUSTED_PROVIDERS`
(OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the TikTok card on **Linked accounts**. The
  explicit link binds the TikTok identity to their account.
- **Subsequent sign-in** — once linked, **Continue with TikTok** signs that person in (the
  account's own address is used).
- **Fresh sign-in or sign-up** — rejected with `email-required` (`OAuthEmailRequired`).

A failed token exchange ends the sign-in at Better Auth's OAuth error. A failed profile request,
a response whose `error.code` is not `ok`, or a user with no string `open_id` yields no identity
and the sign-in is refused.

## Roblox (OLO-9.37)

For the creator communities on Roblox. Apiome uses Roblox's OpenID Connect authorization-code
flow. Roblox is a **link-only** provider: Apiome asks for **profile claims only**, so there is no
email address, and nobody can *create* an Apiome account with it — read
[Email semantics](#roblox-email-semantics) below before turning it on.

1. Signed in to the [Roblox Creator Dashboard](https://create.roblox.com/dashboard/credentials),
   open **Credentials → OAuth 2.0 Apps** and choose **Create OAuth App**.
2. Give the app a **Name** (and the description, entry link and privacy and terms links Roblox
   asks for).
3. Under **Redirect URLs** add the callback (Roblox requires an exact match):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/roblox`
4. Under **Permissions** add the **openid** and **profile** scopes. Apiome asks for nothing else —
   not **email**.
5. Save the app. The **Client ID** is on the app's page; generate the **Client secret** there
   (Roblox shows it once).
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
ROBLOX_CLIENT_ID=<Client ID>
ROBLOX_CLIENT_SECRET=<Client secret>
```

Roblox is one fixed OpenID Connect issuer (`https://apis.roblox.com/oauth/`), so there is no
issuer to configure. The endpoints come from Roblox's discovery document (the scopes, prompt and
exchange mirror Better Auth's `roblox()` helper):

- Discovery: `https://apis.roblox.com/oauth/.well-known/openid-configuration`
- Authorize: `https://apis.roblox.com/oauth/v1/authorize` with the `openid profile` scopes and
  `prompt=select_account consent`. No PKCE challenge is sent; Better Auth enforces `state`.
- Token: `https://apis.roblox.com/oauth/v1/token` — the client ID and secret are sent in the form
  body. Apiome keeps no Roblox token.
- Profile: `https://apis.roblox.com/oauth/v1/userinfo`, with the access token as a bearer token.

The identity is keyed on the `sub` claim, the Roblox user ID; the username can change and is
never the key. `nickname` (the display name) is the name — `preferred_username`, then `name`,
when there is none — and `picture` the avatar headshot. Apiome reads no experiences, groups,
inventory or Robux.

<a id="roblox-email-semantics"></a>
**Email semantics:** Apiome does not ask for the `email` scope, so Roblox returns no email
address. Better Auth's helper puts the `preferred_username` in the email slot; Apiome never does —
the profile carries no `email` and no `email_verified`, and an `email` claim in the response is
ignored. The engine always fail-closes (**link-only**), and `roblox` is not in
`AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the Roblox card on **Linked accounts**. The
  explicit link binds the Roblox identity to their account.
- **Subsequent sign-in** — once linked, **Continue with Roblox** signs that person in (the
  account's own address is used).
- **Fresh sign-in or sign-up** — rejected with `email-required` (`OAuthEmailRequired`).

A failed token exchange ends the sign-in at Better Auth's OAuth error. A failed userinfo request,
or a response with no string `sub`, yields no identity and the sign-in is refused.

## Kick (OLO-9.38)

For the streaming communities on Kick. Apiome uses Kick's OAuth 2.1 authorization-code flow with
PKCE. Kick is a **link-first** provider: it returns an email address with **no verified claim**,
so read [Email semantics](#kick-email-semantics) below before turning it on — nobody can *create*
an Apiome account with it.

1. Signed in to Kick, open **Settings → Developer** and choose **Create new** app.
2. Give the app an **Application name** and **Description**.
3. Add the callback as the **Redirect URL** (Kick requires an exact match):
   - `{BETTER_AUTH_URL}/api/auth/oauth2/callback/kick`
4. Under **Scopes** tick **Read user information (including email address)** (`user:read`) only —
   Apiome asks for nothing else.
5. Create the app. The **Client ID** and **Client Secret** are shown on the app's page.
6. Set the env vars (or save them on the admin console's **Auth providers** page):

```bash
KICK_CLIENT_ID=<Client ID>
KICK_CLIENT_SECRET=<Client Secret>
```

Kick's endpoints are fixed, so there is no issuer to configure (mirroring Better Auth's `kick()`
helper):

- Authorize: `https://id.kick.com/oauth/authorize` with the `user:read` scope (the helper's
  default) and a PKCE `S256` challenge — Kick refuses an authorization without one. Apiome reads
  no channels, chat, streams, followers or subscriptions.
- Token: `https://id.kick.com/oauth/token` — the client ID and secret are sent in the form body.
  Apiome keeps no Kick token.
- Profile: `https://api.kick.com/public/v1/users` with no `id` query (so Kick returns the
  authorizing user alone), with the access token as a bearer token.

The identity is keyed on `user_id` (the first entry of `data`), the Kick user ID; the username
(`name`) can change and is never the key. `name` is the display name and `profile_picture` the
avatar.

<a id="kick-email-semantics"></a>
**Email semantics:** Kick's `/public/v1/users` returns the account's `email` with no claim that it
is verified, and Better Auth's helper hard-codes `emailVerified: false`. Apiome never trusts it:
the profile carries no `email_verified` (any such field in the body is dropped). The engine
fail-closes (**link-first**), and `kick` is not in `AUTO_LINK_TRUSTED_PROVIDERS` (OLO-9.16):

- **Linking** — a signed-in person chooses **Link** on the Kick card on **Linked accounts**. The
  explicit link binds the Kick identity to their account.
- **Subsequent sign-in** — once linked, **Continue with Kick** signs that person in.
- **Fresh sign-in or sign-up** — rejected with `unverified-email`, even when the email matches an
  existing account; with no email, `email-required` (`OAuthEmailRequired`).

A failed token exchange ends the sign-in at Better Auth's OAuth error. A failed profile request,
a response with no `data` entry, or a user with no integer (or string) `user_id` yields no
identity and the sign-in is refused.

## Secrets handling

- Never commit client secrets — `.env` files are gitignored; the checked-in
  [`.env.example`](../.env.example) carries placeholders only.
- OAuth client secrets are server-side only: never expose them under a `NEXT_PUBLIC_`
  name.
- When rotating a **provider** secret, register the new secret in the provider console first, then
  update wherever Apiome holds it — the env var (and restart) or the admin screen's secret field
  (effective at the next login). Sessions already issued stay valid either way.
- A secret stored from the admin screen is written **encrypted**; the database never holds
  plaintext. See [Encryption at rest](#encryption-at-rest-and-key-rotation-auth_config_enc_key).
- Docker deployments: see [`.env.docker`](../.env.docker) and
  [`DOCKER_README.md`](../../docs/archive/apiome-ui/DOCKER_README.md) for where these variables are injected.

## Database provider config store (OLO-8.2, env-fallback)

The store behind the [precedence rule](#config-precedence--database-first-env-fallback): a
deployment can override provider config from the admin UI (OLO-8.4) without editing env and
restarting. The server-global table
`apiome.auth_provider_config` (migration **V196**, `apiome-db`) holds one row per provider
with an explicit `enabled` toggle, `client_id`, an envelope-encrypted `client_secret`
(ciphertext only — the DB never holds plaintext — with an `enc_key_id` for rotation,
OLO-8.3), and a `config` JSONB for provider extras (Azure tenant/authority, GitLab/GitHub
base URLs).

The store is layered **over** env, field by field:

- **No row** for a provider → it is governed entirely by env (the matrix above), unchanged.
- **A row with a `NULL` field** → that field falls back to env (e.g. `enabled = NULL` uses
  the env-derived enablement; `client_id = NULL` uses the env client id).
- **A row with a non-`NULL` field** → the stored value wins over env for that field.

The table is created empty and rows are written lazily on first save, so a fresh deployment
behaves exactly as if the store did not exist.

### Linked-account tokens (`APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS`)

The tokens a provider issues at sign-in, and the personal access tokens users save on a linked
account, are a different secret from the client secrets below and have their own key (#4960).
apiome-ui seals them before they are written (`lib/auth/linked-account-token-crypto.ts`) and
apiome-rest opens them, so `APIOME_LINKED_ACCOUNT_TOKEN_ENCRYPTION_KEYS` — a JSON map of
key-version to base64 32-byte key — must be **identical in both services**. Unset, sign-in and
linking still work but no provider token is stored and saving a personal access token is refused;
a token is never written in plaintext. Upgrade and rotation steps are in
[`docs/runbooks/PRODUCTION_DEPLOY.md`](../../docs/runbooks/PRODUCTION_DEPLOY.md) §7.1.

### Encryption at rest and key rotation (`AUTH_CONFIG_ENC_KEY`)

A plaintext secret in Postgres is strictly worse than one in an env var, so stored client secrets
are **envelope-encrypted** (OLO-8.3) and the key that protects them lives outside the database:

- a random per-secret **data-encryption key (DEK)** encrypts the secret with AES-256-GCM;
- a long-lived **key-encryption key (KEK)** from `AUTH_CONFIG_ENC_KEY` wraps that DEK;
- only the wrapped DEK, the ciphertext, and the non-secret `enc_key_id` are stored.

`AUTH_CONFIG_ENC_KEY` is read by **apiome-rest only** (the one process that seals and unseals
secrets); apiome-ui never sees it. It accepts two forms:

```bash
# Single key — the common case. Sealed under AUTH_CONFIG_ENC_ACTIVE_KEY_ID (default "default").
AUTH_CONFIG_ENC_KEY=<base64 32-byte key>

# Key map — several ids at once, for rotation without a flag day.
AUTH_CONFIG_ENC_KEY={"v1": "<base64 key>", "v2": "<base64 key>"}
AUTH_CONFIG_ENC_ACTIVE_KEY_ID=v2
```

Generate a key with `openssl rand -base64 32` (or
`python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"`). It must decode
to exactly 32 bytes; both standard and URL-safe base64 are accepted.

**When it is required.** Only for storing and reading *stored* secrets. An env-only deployment
never needs it. Without it:

- saving a client secret from the admin screen is refused (**503**) rather than stored in the clear;
- a row that already carries a sealed secret **fails loud** on the read path instead of silently
  falling back to the env secret — a wrong-OAuth-app sign-in is a worse outcome than a clear error.
  A provider with no stored secret still falls back to env normally.

A malformed key, or an active id with no matching key, fails **apiome-rest startup** rather than
surfacing at the first save.

**Rotating the KEK.** `enc_key_id` records which key sealed each row, and the id is bound into the
GCM additional-authenticated-data, so rows cannot be silently re-pointed at another key:

1. Switch to the map form and **add** the new key alongside the current one
   (`{"v1": "<old>", "v2": "<new>"}`). Keep `v1` — existing rows still need it.
2. Point `AUTH_CONFIG_ENC_ACTIVE_KEY_ID` at the new id (`v2`) and restart apiome-rest. New saves are
   sealed under `v2`; older rows stay readable under `v1`.
3. Re-seal the existing rows onto the active key (`reseal_provider_secret` in
   `apiome-rest/src/app/auth_provider_secret_crypto.py`; `needs_reseal` identifies the rows).
   Re-saving each provider's secret from the admin screen achieves the same thing by hand.
4. Only once no row references `v1` may it be dropped from the map. **Removing a KEK that still
   seals a row makes that secret unrecoverable** — the remedy is re-entering it from the provider's
   console.

Rotating the KEK does not touch the OAuth secrets themselves, so no provider console changes and no
user sessions are affected.

### Admin configuration screen (OLO-8.7)

The store is edited at **`/admin/dashboard/settings`** ("System Configuration" in the admin
sidebar), behind the signed super-admin session (OLO-8.1). The screen shows one card per
provider with an enablement control (**Enabled / Disabled / Use .env**, mapping to
`true`/`false`/`NULL`), the client id, a **write-only** secret field (only "set / not set" is
ever shown), and the provider extras above. Every field that has no DB value carries a
"using .env fallback" badge, and a **Validate** button reports whether the DB row is complete
enough to enable. Forcing a provider **Enabled** requires its client id *and* secret to be
stored in the DB (env values do not count toward that check); saves take effect at the next
login without a restart (OLO-8.5/8.6).

#### How the screen relates to `.env.example`

The screen and the env template describe the **same fields**, one per row of the
[matrix above](#environment-variable-matrix) — they are two ways to supply one contract, not two
contracts:

| | `.env` / `.env.example` | Admin → System Configuration |
|---|---|---|
| Precedence | fallback | **wins**, field by field |
| Applies | at restart | at the next login |
| Scope | that one host's process | every server sharing the database |
| Secret at rest | plaintext in the env/secret store | envelope-encrypted (`AUTH_CONFIG_ENC_KEY`) |
| Needs | nothing | `INTERNAL_SERVICE_TOKEN` on both sides, plus the KEK for secrets |
| Good for | local dev, bootstrap, single-host deploys | multi-server deploys, rotating creds without a redeploy |

Provider extras keep their **env-var names** as their keys inside the stored `config` JSONB
(`OKTA_ISSUER`, `GITLAB_BASE_URL`, `AZURE_AD_TENANT`, …), so a field is named identically in both
places and the template doubles as the field reference for the screen. A field with no stored value
shows a **"using .env fallback"** badge, which is the screen's live read of exactly this precedence.

#### Removing a provider

A card's **Remove** button deletes that provider's whole `auth_provider_config` row, returning it
to the env-only behaviour described above — the card disappears and the provider is offered again
in **Add Provider**. It is confirmed inline first, because unlike every other control on the card
it cannot be undone: **the encrypted client secret is destroyed with the row**, and re-configuring
the provider means re-entering it from the provider's console.

Removal is not the same as clearing fields individually:

- **Clear stored secret** (on the secret field) drops only the secret; the row, client id, extras,
  and any `enabled` override remain.
- **Remove** drops everything, including the `enabled` override — so a provider that was forced on
  from the DB reverts to env-derived enablement, which may turn its login button off.

Like a save, a removal takes effect at the next login without a restart. If the provider's
credentials are also present in `.env`, sign-in keeps working from those; if they are not, the
provider disappears from the login page.

## Test-only endpoint overrides (OLO-7.4)

The end-to-end journey suite (`e2e/journey/`, #4226) points every provider at a local
mock server via base-URL override env vars:

| Variable | Overrides | Production default |
| --- | --- | --- |
| `GITHUB_OAUTH_BASE_URL` | GitHub authorize/token endpoints | `https://github.com` |
| `GITHUB_API_BASE_URL` | GitHub `/user` + `/user/emails` API | `https://api.github.com` |
| `GITLAB_BASE_URL` | GitLab authorize/token/userinfo | `https://gitlab.com` |
| `AZURE_AD_AUTHORITY_BASE_URL` | Entra ID OIDC discovery authority | `https://login.microsoftonline.com` |
| `GOOGLE_ISSUER` | Google OIDC discovery issuer | `https://accounts.google.com` |

`OKTA_ISSUER`, `COGNITO_ISSUER`, `KEYCLOAK_ISSUER`, `OIDC_ISSUER`, and `AUTH0_ISSUER` are
**required** production config vars (not test-only overrides) — see the
[Okta](#okta--oidc-application-workforce-idp),
[Cognito](#amazon-cognito--user-pool--hosted-ui-olo-94),
[Keycloak](#keycloak--realm-oidc-client-olo-95),
[Generic OIDC](#generic-oidc--any-conformant-openid-provider-olo-96), and
[Auth0](#auth0--regular-web-application-olo-97),
[LINE](#line-login-olo-941--japan--taiwan--thailand-country-mvp),
[VK](#vk-id-olo-942--russia--cis-country-mvp), and
[WeChat](#wechat-open-platform-olo-943--china-country-mvp) sections. (Atlassian, Bitbucket, Slack, LinkedIn, Discord, Notion, Figma, Linear, Dropbox, Zoom, Hugging Face, Vercel, Railway, HubSpot, Apple, Facebook, X / Twitter, Reddit, Spotify, Twitch, TikTok, Roblox and Kick need no issuer; Salesforce's `SALESFORCE_ISSUER` is optional — see [Salesforce](#salesforce--oidc-olo-920).) Pointing any of them
at a mock issuer for the e2e journey is fine in test; never point a real deployment's issuer at a
non-provider host.

**Never set the GitHub / GitLab / Azure authority / Google issuer overrides in a real deployment** —
they redirect the entire sign-in flow to the named host. Unset (the default) the real provider
endpoints are used; the boot-time validation matrix above is unaffected by them.

## Two-factor email OTP (OLO-9.50)

Email OTP is an alternate **login** second factor once a user has 2FA enabled (TOTP enroll). It is
**not** a separate per-user enrollment: Better Auth registers `otpOptions.sendOTP` at the server
level when both env vars are set.

| Variable | Required | Purpose |
|---|---|---|
| `SENDGRID_API_KEY` | To enable email OTP | SendGrid API key |
| `EMAIL_FROM` | To enable email OTP | Verified sender address |

Unset either variable → credential 2FA stays TOTP-only (`twoFactorMethods` will not include `otp`).
