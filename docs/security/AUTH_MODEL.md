# Authentication & Secret Model

> Status: RC1 baseline (RC1-0.3, #3610). Scope here is **authentication, tokens,
> secrets, CORS, and login-abuse protection**. The fine-grained authorization /
> RBAC model is RC1-1.1 and is intentionally out of scope for this document.

This document describes how callers authenticate to the Apiome platform, the
credential types in play, their lifetimes and scopes, how secrets are handled, and
the hardening controls applied for the first release candidate.

## Components

| Service | Role in auth |
|---------|--------------|
| `apiome-ui` (Next.js / NextAuth) | Issues the user session JWT; hosts the credentials + OAuth (GitHub/GitLab) login and the super-admin password form. |
| `apiome-rest` (FastAPI) | Validates JWTs (shared secret) and API keys on every tenant-scoped route. |
| `apiome-cli` / `apiome-mcp` | Clients that authenticate to REST with an API key (`X-API-Key`) or a session bearer token. |
| `apiome-db` (Postgres) | Stores users (bcrypt password hashes), API keys (hashed), and personal access tokens. |

## Credential types

### 1. User session JWT (NextAuth)

- **Issued by:** NextAuth in `apiome-ui` after a successful credentials or
  OAuth (GitHub/GitLab) login (`lib/auth/credentials.ts`,
  `src/app/api/auth/[...nextauth]/route.ts`).
- **Algorithm:** `HS256`, signed with `NEXTAUTH_SECRET`.
- **Shared secret:** REST validates the same token using
  `NEXTAUTH_SECRET` (preferred) or `JWT_SECRET` — see
  `apiome-rest/src/app/config.py` (`effective_jwt_secret`) and
  `auth.py` (`decode_jwt`). The UI and REST **must** share the same value.
- **Claims used:** `user_id` / `sub` (user identity), `email`, `name`,
  `current_tenant_id`.
- **Lifetime / refresh:** NextAuth default session (JWT strategy). The token is
  refreshed by NextAuth on activity; sign-out clears it client-side.
- **Transport:** `Authorization: Bearer <jwt>`.
- **Tenant access:** REST resolves tenant membership per request against
  `apiome.tenant_users` / `apiome.tenant_administrators`
  (`validate_user_tenant_access`). A valid JWT alone grants nothing — the user
  must be a member or administrator of the requested tenant.

### 2. Workspace API keys

- **Issued by:** REST `/api-keys` surface (create / rotate / revoke / policy).
- **Storage:** only a **hash** of the key is stored (`apiome.api_keys.key_hash`); the
  plaintext key is shown once at creation and never persisted.
- **Scope:** bound to a single tenant. REST rejects a key presented against a
  different tenant slug (403). Attribution falls back to
  `created_by_user_id` → first tenant administrator → first member.
- **Expiry:** `apiome.api_keys.expires_at` — a key past its expiry (or with
  `enabled = false`) is rejected at validation time
  (`database.validate_api_key`). `last_used_at` is updated on each successful use.
- **Policy:** per-tenant key policy (default expiry, etc.) via
  `GET/PUT /api-keys/policy`.
- **Transport:** `X-API-Key: <key>`.

### 3. Personal access tokens (PATs)

- **Issued by:** `/auth/personal-access-tokens` (CLI `tokens create`).
- **Display:** the raw PAT is printed **once** at creation; only a hash is stored.
- **Use:** session-scoped REST endpoints that accept a bearer token.

### 4. Super-admin session

- **Mechanism:** a single shared password (`ADMIN_PASSWORD`) gates the super-admin
  portal (`src/app/api/admin/auth/route.ts`). On success an `httpOnly`,
  `sameSite=strict`, `secure`-in-production cookie is set with an **8-hour**
  `maxAge`.
- **Hardening:** the password form is rate-limited per client IP (see below).

## Token / credential lifetime summary

| Credential | Lifetime | Refresh | Revoke |
|------------|----------|---------|--------|
| Session JWT | NextAuth session default | Automatic (NextAuth) | Sign out |
| API key | Until `expires_at` or disabled | Rotate (`/api-keys/{id}/rotate`) | `DELETE /api-keys/{id}` |
| PAT | Until expiry / revoke | — | `tokens revoke` |
| Admin cookie | 8 hours | Re-login | `DELETE /api/admin/auth` |

## CORS policy

REST applies a configuration-driven CORS allow-list
(`apiome-rest/src/app/main.py`, `config.py`):

- **Exact origins:** `APIOME_CORS_ALLOWED_ORIGINS` (comma-separated).
  Defaults to the local Next.js dev ports (`http://localhost:3000`, `:3001`).
- **Subdomain regex:** `APIOME_CORS_ALLOWED_ORIGIN_REGEX`. Defaults to
  `https://.*\.apiome\.dev`. Set to an empty string to disable subdomain
  matching entirely.
- `allow_credentials=True`; methods/headers are `*`.

Production deployments should set `APIOME_CORS_ALLOWED_ORIGINS` (and, if
needed, the regex) to the exact front-end origins rather than relying on defaults.

## Secret handling

- **No plaintext secrets in the repo or images.** All committed `.env*` files are
  `.example` / `.docker` / `.test` templates containing **placeholders only**
  (e.g. `NEXTAUTH_SECRET=[openssl rand -base64 32]`,
  `ADMIN_PASSWORD=your_secure_admin_password_here`). Real `.env` files are
  git-ignored.
- **Fail-closed JWT secret:** in production (`APIOME_ENV=production`) REST
  **refuses to start** if no JWT secret is configured rather than falling back to
  the insecure built-in default. In development the default is used with a logged
  warning. See `Settings.effective_jwt_secret`.
- **Hashed at rest:** user passwords (bcrypt), API keys, and PATs are stored only
  as hashes. Webhook signing secrets are encrypted at rest with a Fernet key
  (`APIOME_WEBHOOK_SIGNING_SECRET_ENCRYPTION_KEY`).
- **Docker:** the dev compose stack ships well-known **dev-only** Postgres
  credentials, documented as such in `docker-compose.env.example`; override them
  for any non-local use.

## Login-abuse protection (brute force / lockout)

Credential logins and the super-admin password form are protected by an in-memory
sliding-window limiter (`apiome-ui/lib/auth/login-rate-limit.ts`):

- **Threshold:** `5` failed attempts within a `15-minute` window.
- **Lockout:** a further `15-minute` block once the threshold is reached.
- **Keys:** credential logins are throttled per **email** (`cred:<email>`); the
  admin form is throttled per **client IP** (`admin:<ip>`). A successful login
  clears the counter.
- **Behaviour:** a locked credential login is rejected without touching the
  database or running bcrypt; a locked admin attempt returns `429` with a
  `Retry-After` header.

**Limitation / upgrade path:** counters live in the Node process only — they reset
on restart and are **not shared across instances**. This is sufficient for the
single-node RC1 spine. For horizontally-scaled deployments the limiter should be
backed by a shared store (Postgres or Redis) and/or a durable per-account lockout
column; this is the documented follow-up.

## Related

- `docs/security/RC1_HARDENING_CHECKLIST.md` — the RC1 hardening checklist and evidence.
- `apiome-rest/src/app/auth.py` — JWT / API-key validation.
- `apiome-ui/lib/auth/credentials.ts` — credential / OAuth login.
