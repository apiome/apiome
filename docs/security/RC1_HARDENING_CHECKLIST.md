# RC1 Auth & Secret Hardening Checklist

> Ticket: **RC1-0.3 — Auth & secret hardening pass** (#3610).
> Epic: #3603 — RC1 Phase 0. Scope: tokens, keys, scopes/expiry, CORS, secret
> handling, and login-abuse protection. (Authorization/RBAC is RC1-1.1.)

This checklist records the public-release-bar review for the first release
candidate. Each item lists the control and the evidence in the codebase.

## Acceptance criteria

- [x] **Documented auth model (tokens, keys, scopes, expiry)**
  → `docs/security/AUTH_MODEL.md`.
- [x] **No plaintext secrets in repo or built images**
  → see "Secret handling" below.
- [x] **Login rate-limit / lockout in place**
  → `apiome-ui/lib/auth/login-rate-limit.ts` wired into credential and
  admin login; tests in `tests/lib/login-rate-limit.test.ts`.
- [x] **Hardening checklist passed** → this document.

## Tokens & keys

| # | Control | Status | Evidence |
|---|---------|--------|----------|
| 1 | Session JWT signed with shared `NEXTAUTH_SECRET` (HS256) | ✅ | `apiome-rest/src/app/auth.py` `decode_jwt`; `config.py` `effective_jwt_secret` |
| 2 | Expired/invalid JWTs rejected | ✅ | `decode_jwt` handles `ExpiredSignatureError` / `InvalidTokenError` |
| 3 | JWT alone grants no tenant access (membership re-checked per request) | ✅ | `validate_user_tenant_access` against `tenant_users` / `tenant_administrators` |
| 4 | API keys stored hashed, never in plaintext | ✅ | `apiome.api_keys.key_hash`; raw key shown once |
| 5 | API keys tenant-scoped; cross-tenant use rejected (403) | ✅ | `validate_authentication` tenant-slug check |
| 6 | API key expiry + disable honoured at validation | ✅ | `database.validate_api_key` (`expires_at`, `enabled`) |
| 7 | API key rotation & revocation available | ✅ | `/api-keys/{id}/rotate`, `DELETE /api-keys/{id}` |
| 8 | PAT raw value shown once; stored hashed | ✅ | CLI `tokens create`; `/auth/personal-access-tokens` |
| 9 | Admin cookie `httpOnly` + `sameSite=strict` + `secure` in prod, 8h expiry | ✅ | `src/app/api/admin/auth/route.ts` |

## CORS

| # | Control | Status | Evidence |
|---|---------|--------|----------|
| 10 | CORS origins configuration-driven (not hard-coded) | ✅ | `APIOME_CORS_ALLOWED_ORIGINS` / `_ORIGIN_REGEX` in `config.py`, applied in `main.py` |
| 11 | Safe defaults preserved (localhost + `*.apiome.app`) | ✅ | `DEFAULT_CORS_ORIGINS`, `DEFAULT_CORS_ORIGIN_REGEX` |
| 12 | Subdomain matching can be disabled in locked-down deployments | ✅ | empty `APIOME_CORS_ALLOWED_ORIGIN_REGEX` → no regex applied |

## Secret handling

| # | Control | Status | Evidence |
|---|---------|--------|----------|
| 13 | No plaintext secrets in tracked files | ✅ | repo scan (AWS keys / private keys / GH tokens / hardcoded secret-key assignments) returns nothing |
| 14 | Real `.env` files git-ignored; only templates committed | ✅ | root + package `.gitignore`; tracked files are `.example` / `.docker` / `.test` placeholders |
| 15 | JWT secret fails closed in production (no insecure fallback) | ✅ | `Settings.effective_jwt_secret` raises when `APIOME_ENV=production` and no secret set; startup probe in `main.py` |
| 16 | Passwords (bcrypt), API keys, PATs hashed at rest | ✅ | `lib/auth/credentials.ts` bcrypt; `api_keys.key_hash` |
| 17 | Webhook signing secrets encrypted at rest (Fernet) | ✅ | `APIOME_WEBHOOK_SIGNING_SECRET_ENCRYPTION_KEY`, `push_webhook_crypto.py` |
| 18 | Docker dev credentials are clearly dev-only and overridable | ✅ | `docker-compose.env.example` documents overrides |

## Login-abuse protection

| # | Control | Status | Evidence |
|---|---------|--------|----------|
| 19 | Credential login rate-limited per account | ✅ | `credentialsAuthorize` uses `checkLoginRateLimit` / `recordLoginFailure` |
| 20 | Lockout after 5 failures / 15-min window for 15 min | ✅ | `LOGIN_MAX_ATTEMPTS`, `LOGIN_WINDOW_MS`, `LOGIN_BLOCK_MS` |
| 21 | Locked login skips DB + bcrypt (cheap reject) | ✅ | early return in `credentialsAuthorize` |
| 22 | Super-admin form rate-limited per IP, returns 429 + `Retry-After` | ✅ | `src/app/api/admin/auth/route.ts` |
| 23 | Successful login clears the counter | ✅ | `recordLoginSuccess` |

## Known limitations (tracked follow-ups)

- The login limiter is **in-memory / per-instance** (resets on restart, not shared
  across replicas). Acceptable for the single-node RC1 spine; move to a shared
  (Postgres/Redis) store and/or durable per-account lockout for scaled
  deployments. See `docs/security/AUTH_MODEL.md`.
- Fine-grained authorization (RBAC) is **out of scope** here and tracked as
  RC1-1.1.
