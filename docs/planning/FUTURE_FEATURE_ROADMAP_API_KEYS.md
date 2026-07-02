# Apiome: API Keys - Feature Roadmap

> Advanced API key management layer providing fine-grained scopes, security hardening, lifecycle controls, and developer experience improvements for all Apiome REST API consumers. Built on top of the existing key management foundation (bcrypt hashing, expiration, enable/disable, last-used tracking).
>
> **Revenue Model**: Basic key management in Free tier; advanced security features (IP whitelisting, anomaly detection, rotation policies, MFA-backed keys) gated at Pro/Enterprise
>
> **Tech Stack**: NextJS App Router, PostgreSQL, Redis (rate limit counters), OpenAPI 3.1, HMAC-SHA256 for signed requests, JWT for short-lived token exchange

---

## MVP Definition

- Per API key rate limits (requests/minute, requests/hour) with rate limit headers in response
- Fine-grained permission scopes (read, write, delete, admin) with per-resource access control
- IP address whitelisting per API key
- Key rotation with configurable grace period
- Environment labels (production, staging, development)
- Show key once on creation; quick-copy button with confirmation
- Webhook notifications for key lifecycle events (created, used for first time, expired, revoked)

---

## Epic 1 (#1941): Rate Limiting

### Summary Table

| #   | Title                                    | Description                                                                       | Labels                                     | MVP | Parallel |
|-----|------------------------------------------|-----------------------------------------------------------------------------------|--------------------------------------------|-----|----------|
| 1.1 (#1942) | Per-Key Rate Limit Configuration         | Allow admins to set requests/minute and requests/hour limits per API key          | `enhancement`, `mvp`, `api-keys`, `rest`  | Yes | No       |
| 1.2 (#1943) | Per-Tenant Rate Limits                   | Configurable aggregate rate limits across all keys for a tenant                   | `enhancement`, `mvp`, `api-keys`          | Yes | Yes      |
| 1.3 (#1944) | Per-Endpoint Rate Limits                 | Override global limits for specific high-traffic or sensitive endpoints           | `enhancement`, `api-keys`                 | No  | Yes      |
| 1.4 (#1945) | Rate Limit Headers in Responses          | Include X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset headers      | `enhancement`, `mvp`, `api-keys`          | Yes | No       |
| 1.5 (#1946) | Rate Limit Dashboard                     | Per-key usage graph showing current period consumption vs limit                   | `enhancement`, `api-keys`                 | No  | Yes      |
| 1.6 (#1947) | Auto-Throttling on Spike Detection       | Detect sudden traffic spikes per key and apply temporary throttling               | `enhancement`, `api-keys`                 | No  | Yes      |
| 1.7 (#1948) | DDoS Protection Integration              | Block keys that sustain above-threshold traffic for > N seconds                   | `enhancement`, `api-keys`, `security`     | No  | Yes      |

### Detailed Issue Descriptions

#### 1.1 (#1942) — Per-Key Rate Limit Configuration

Extend the API key record with `rate_limit_per_minute` and `rate_limit_per_hour` nullable integer columns. When null, the tenant default applies. Rate limit state is tracked in Redis using a sliding window counter keyed on `key_id:minute:{epoch_minute}` and `key_id:hour:{epoch_hour}`.

```
api_key
├── id                UUID PK
├── rate_limit_per_minute  INTEGER NULL   ← null = use tenant default
├── rate_limit_per_hour    INTEGER NULL
└── ...existing columns...

Redis keys:
  ratelimit:key:{key_id}:min:{epoch_minute}   → counter (TTL: 61s)
  ratelimit:key:{key_id}:hr:{epoch_hour}      → counter (TTL: 3601s)
```

**Acceptance Criteria:**
- Rate limit checked on every authenticated API request before routing to handler
- Per-key limit takes precedence over tenant default when set
- Counter increments are atomic (Redis INCR + EXPIRE)
- Requests exceeding limit return 429 with standard rate limit headers

**Tech Stack:** PostgreSQL migration, Redis INCR/EXPIRE, middleware layer

Part of Epic: Rate Limiting

---

#### 1.4 (#1945) — Rate Limit Headers in Responses

Every API response must include rate limit context headers so consumers can self-throttle:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 73
X-RateLimit-Reset: 1712345678
Retry-After: 42   (only on 429 responses)
```

**Acceptance Criteria:**
- All three headers present on every authenticated response
- `X-RateLimit-Reset` is a Unix epoch timestamp of when the counter resets
- `Retry-After` seconds value accurate to ±1 second
- Headers documented in the OpenAPI spec as response headers on all secured endpoints

Part of Epic: Rate Limiting

---

## Epic 2 (#1949): Scopes & Permissions

### Summary Table

| #   | Title                                   | Description                                                                       | Labels                                    | MVP | Parallel |
|-----|-----------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------------|-----|----------|
| 2.1 (#1950) | Permission Scope Model                  | Define all API key scope strings and their mapping to resource operations          | `enhancement`, `mvp`, `api-keys`, `rest` | Yes | No       |
| 2.2 (#1951) | Scope Templates                         | Pre-built scope bundles: read-only, full-access, schema-only, paths-only          | `enhancement`, `api-keys`                | No  | Yes      |
| 2.3 (#1952) | Scope Validation Middleware             | Enforce scope checks on every API route; return 403 on scope mismatch            | `enhancement`, `mvp`, `api-keys`         | Yes | No       |
| 2.4 (#1953) | Scope Management UI                     | Checkbox-based scope selector on the key creation/edit form                       | `enhancement`, `mvp`, `api-keys`         | Yes | No       |
| 2.5 (#1954) | Scope Inheritance from Tenant Defaults  | Tenant-level default scope set applied to new keys unless overridden              | `enhancement`, `api-keys`                | No  | Yes      |

### Detailed Issue Descriptions

#### 2.1 (#1950) — Permission Scope Model

Define the canonical scope strings for all API key permission dimensions. Scopes follow the pattern `resource:action` and are stored as a `TEXT[]` column on the `api_key` table.

```
Scope Catalog:

Read-only:
  schemas:read, paths:read, projects:read, versions:read

Write:
  schemas:write, paths:write, projects:write, versions:write

Delete:
  schemas:delete, paths:delete, projects:delete

Admin:
  tenant:manage, users:manage, api-keys:manage

Export:
  export:openapi, export:code, export:docs

AI:
  ai:chat, ai:generate, ai:review
```

**Acceptance Criteria:**
- All scope strings documented in OpenAPI security scheme definition
- `api_key.scopes` column stores array; empty array = no permissions (deny all)
- Wildcard scope `*` (admin keys only) grants all permissions
- Migration adds `scopes TEXT[] NOT NULL DEFAULT '{}'` to `api_key` table

Part of Epic: Scopes & Permissions

---

## Epic 3 (#1955): Security Enhancements

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                                        | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------|-----|----------|
| 3.1 (#1956) | IP Address Whitelisting per Key            | Reject requests from IPs not in the key's whitelist CIDR list                     | `enhancement`, `mvp`, `api-keys`, `security` | Yes | No       |
| 3.2 (#1957) | Allowed Origins Restriction (CORS-like)    | Optionally restrict key usage to specified Origin headers                          | `enhancement`, `api-keys`, `security`        | No  | Yes      |
| 3.3 (#1958) | Key Rotation with Grace Period             | Generate new key secret; old secret valid for configurable grace period (hours)   | `enhancement`, `mvp`, `api-keys`             | Yes | No       |
| 3.4 (#1959) | Rotation Reminders & Notifications         | Email/webhook notification N days before key expiration or after max-age reached  | `enhancement`, `api-keys`                    | No  | Yes      |
| 3.5 (#1960) | Maximum Key Age Policy                     | Tenant-level policy forcing key rotation after X days; keys auto-expire if not   | `enhancement`, `api-keys`, `security`        | No  | Yes      |
| 3.6 (#1961) | GitHub Secret Scanning Integration         | Register as a GitHub secret scanning partner; receive callbacks on key exposure   | `enhancement`, `api-keys`, `security`        | No  | No       |
| 3.7 (#1962) | Key Usage Anomaly Detection                | Alert when a key is used from an unusual IP geolocation or at unusual hours       | `enhancement`, `api-keys`, `security`        | No  | No       |
| 3.8 (#1963) | Emergency Revocation (All Keys)            | One-click revoke all active keys for a tenant; log the triggering admin action    | `enhancement`, `api-keys`, `security`        | No  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#1956) — IP Address Whitelisting per Key

Store a `cidr_whitelist TEXT[]` on the API key record. On every authenticated request, extract the client IP (respecting `X-Forwarded-For` with a trusted proxy list) and check if it falls within any whitelisted CIDR. An empty whitelist means no IP restriction.

```
api_key
└── cidr_whitelist TEXT[]   -- e.g. ['192.168.1.0/24', '10.0.0.5/32']
```

**Acceptance Criteria:**
- Request from non-whitelisted IP returns `403 Forbidden` with body `{"error": "ip_not_whitelisted"}`
- IPv6 addresses supported (e.g., `::1/128`)
- `X-Forwarded-For` only trusted from configured proxy CIDR ranges (prevents spoofing)
- Empty `cidr_whitelist` (default) allows all IPs

Part of Epic: Security Enhancements

---

#### 3.3 (#1958) — Key Rotation with Grace Period

Implement a rotation flow that generates a new key secret while keeping the old secret valid for a configurable `grace_period_hours`. After the grace period elapses, the old secret is automatically invalidated. Consumers have time to update their configuration without a hard cutover.

**OpenAPI Endpoints:**
```
POST /api/v1/api-keys/{id}/rotate
  Body: { grace_period_hours: number }  // 0–168 (1 week max)
  → 200: {
      new_key: "ok_new_xxxxx",   // shown once
      old_key_expires_at: ISO8601
    }
```

**Acceptance Criteria:**
- New key returned in response body (shown once, never stored in plaintext)
- Old key continues to work until `old_key_expires_at`
- After grace period, old key returns 401 with `{"error": "key_rotated"}`
- Rotation event logged in audit log with `actor_id` and `grace_period_hours`

Part of Epic: Security Enhancements

---

## Epic 4 (#1964): Lifecycle Management

### Summary Table

| #   | Title                                   | Description                                                                       | Labels                          | MVP | Parallel |
|-----|-----------------------------------------|-----------------------------------------------------------------------------------|---------------------------------|-----|----------|
| 4.1 (#1965) | Environment Labels                      | Tag keys with environment: production, staging, development, testing              | `enhancement`, `mvp`, `api-keys` | Yes | Yes      |
| 4.2 (#1966) | Key Versioning                          | Track key generation (v1, v2, etc.) for rollback traceability                     | `enhancement`, `api-keys`       | No  | Yes      |
| 4.3 (#1967) | Deprecation Workflow with Sunset Dates  | Mark a key deprecated with a sunset date; consumers warned in response headers   | `enhancement`, `api-keys`       | No  | Yes      |
| 4.4 (#1968) | Scheduled Key Activation                | Set a future activation date so a key becomes active at a scheduled time         | `enhancement`, `api-keys`       | No  | Yes      |
| 4.5 (#1969) | Key Cloning                             | Duplicate key configuration (scopes, limits, whitelist) with a new secret        | `enhancement`, `api-keys`       | No  | Yes      |
| 4.6 (#1970) | Bulk Key Management                     | Select multiple keys to enable, disable, or delete in one action                  | `enhancement`, `api-keys`       | No  | Yes      |
| 4.7 (#1971) | Key Ownership Transfer                  | Transfer a key's ownership to another user within the tenant                     | `enhancement`, `api-keys`       | No  | Yes      |

---

## Epic 5 (#1972): Developer Experience

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                          | MVP | Parallel |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|---------------------------------|-----|----------|
| 5.1 (#1973) | Show Key Once on Creation                  | Return full key secret only in the creation response; never retrievable again     | `enhancement`, `mvp`, `api-keys` | Yes | No       |
| 5.2 (#1974) | Quick-Copy Button with Confirmation        | Copy key to clipboard with visual confirmation (green check, auto-clear after 30s) | `enhancement`, `mvp`, `api-keys` | Yes | Yes    |
| 5.3 (#1975) | Description / Notes Field                  | Free-text notes field on each key for documentation and context                   | `enhancement`, `mvp`, `api-keys` | Yes | Yes      |
| 5.4 (#1976) | Test Mode Keys                             | Keys flagged as test-mode operate against a sandboxed data environment            | `enhancement`, `api-keys`       | No  | No       |
| 5.5 (#1977) | API Usage Examples per Language            | Show curl, TypeScript, Python usage examples with the key pre-populated           | `enhancement`, `api-keys`       | No  | Yes      |
| 5.6 (#1978) | Webhook Notifications for Key Events       | POST to a tenant webhook URL on key create, first-use, expired, and revoked       | `enhancement`, `api-keys`, `rest` | No | Yes    |

### Detailed Issue Descriptions

#### 5.6 (#1978) — Webhook Notifications for Key Events

Emit a signed webhook payload to the tenant's configured webhook URL when a key lifecycle event occurs. Events: `api_key.created`, `api_key.first_used`, `api_key.expired`, `api_key.revoked`, `api_key.rotation_grace_expiring` (24h warning).

```json
{
  "event": "api_key.expired",
  "timestamp": "2026-04-03T12:00:00Z",
  "tenant_id": "...",
  "api_key": {
    "id": "...",
    "name": "Production Key",
    "environment": "production",
    "expired_at": "2026-04-03T12:00:00Z"
  }
}
```

**Acceptance Criteria:**
- Payload signed with HMAC-SHA256 using the tenant's webhook secret; signature in `X-Apiome-Signature` header
- Delivery retried up to 3 times with exponential backoff on non-2xx response
- Delivery log visible in admin UI (status, timestamp, response code per attempt)
- Tenant can configure webhook URL in tenant settings

Part of Epic: Developer Experience

---

## Epic 6 (#1979): Multi-Factor Authentication for Keys

### Summary Table

| #   | Title                                      | Description                                                                        | Labels                               | MVP | Parallel |
|-----|--------------------------------------------|------------------------------------------------------------------------------------|--------------------------------------|-----|----------|
| 6.1 (#1980) | MFA Requirement for Key Creation           | Require TOTP/SMS MFA verification before a new API key can be created              | `enhancement`, `api-keys`, `security` | No | No       |
| 6.2 (#1981) | HMAC Signed Requests                       | Optional per-key HMAC signing: clients sign requests with a shared secret          | `enhancement`, `api-keys`, `security` | No | No       |
| 6.3 (#1982) | Short-Lived Token Exchange (JWT)           | Exchange long-lived key for short-lived JWT token valid for N minutes              | `enhancement`, `api-keys`, `rest`    | No  | No       |
| 6.4 (#1983) | OAuth 2.0 Client Credentials Flow          | Support OAuth 2.0 `client_credentials` grant using key ID + secret as credentials | `enhancement`, `api-keys`, `rest`    | No  | No       |

### Detailed Issue Descriptions

#### 6.3 (#1982) — Short-Lived Token Exchange (JWT)

Allow API consumers to exchange their long-lived API key for a short-lived JWT (default: 15 minutes). This reduces the attack window if a token is intercepted, since the JWT expires quickly and cannot be refreshed without the original key.

**OpenAPI Endpoints:**
```
POST /api/v1/auth/token
  Authorization: Bearer {api_key}
  Body: { expires_in?: number }   // seconds, max 3600
  → 200: { access_token: "eyJ...", expires_at: ISO8601, token_type: "Bearer" }
  → 401: { error: "invalid_key" }
```

**Acceptance Criteria:**
- JWT signed with RS256 (asymmetric); public key available at `/.well-known/jwks.json`
- JWT payload includes: `sub` (key_id), `tid` (tenant_id), `scopes[]`, `exp`, `iat`
- Expired JWTs return 401 with `{"error": "token_expired"}`
- Token exchange rate-limited to 60 requests/minute per key

Part of Epic: Multi-Factor Authentication for Keys
