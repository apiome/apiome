# Objectified: User Profile & Identity - Feature Roadmap

> Comprehensive user profile, account settings, and identity management system covering personal information, notification preferences, security settings, personalization, and developer access — with enterprise-grade SSO, SCIM provisioning, compliance controls, and delegation capabilities.
>
> **Revenue Model**: Basic profile and account settings in all tiers; enterprise identity (SAML/OIDC/LDAP, SCIM, conditional access, PAM) gated at Enterprise; user access reviews and compliance workflows are Enterprise upsells
>
> **Tech Stack**: NextJS App Router, Radix UI, PostgreSQL, TOTP (otplib), WebAuthn (SimpleWebAuthn), SAML 2.0 (node-saml), SCIM 2.0, OpenAPI 3.1

---

## MVP Definition

- Profile information: avatar upload, job title, department, phone number, timezone, language, bio, social links
- Account settings: email change with verification, session management (view/revoke), login history, account deletion request, GDPR data export
- Notification preferences: per-event-type email toggles, digest frequency, quiet hours
- Security settings: TOTP 2FA, backup codes, WebAuthn security keys, trusted devices, password strength indicator, security activity log
- Personalization: theme preference (light/dark/system), default landing page, favorite projects
- Developer settings: personal API keys, SSH keys for Git, webhook endpoints, CLI auth tokens

---

## Epic 1: Profile Information & Account Settings

**GitHub Epic:** #2408

### Summary Table

| #   | Title                                    | Description                                                                        | Labels                                    | MVP | Parallel | Issue  |
|-----|------------------------------------------|------------------------------------------------------------------------------------|-------------------------------------------|-----|----------|--------|
| 1.1 | Profile Avatar Upload                    | Upload, crop, and store a profile photo (S3-backed); serve via CDN                | `enhancement`, `mvp`, `profile`          | Yes | Yes      | #2414  |
| 1.2 | Extended Profile Fields                  | Job title, department/team, phone (with country code), bio, social links           | `enhancement`, `mvp`, `profile`, `rest`  | Yes | No       | #2415  |
| 1.3 | Timezone & Locale Preferences            | Store user timezone and locale; apply to all timestamps and date formatting        | `enhancement`, `mvp`, `profile`          | Yes | Yes      | #2416  |
| 1.4 | Email Change with Verification           | Initiate email change; verify new address via token before committing              | `enhancement`, `mvp`, `profile`, `rest`  | Yes | No       | #2417  |
| 1.5 | Session Management UI                    | List all active sessions with device/IP/geolocation; revoke individual sessions   | `enhancement`, `mvp`, `profile`, `rest`  | Yes | No       | #2418  |
| 1.6 | Login History                            | Paginated list of login attempts: timestamp, IP, device, geolocation, success/fail| `enhancement`, `mvp`, `profile`          | Yes | Yes      | #2419  |
| 1.7 | Account Deletion Request                 | Initiate account deletion; 7-day cool-down period with cancellation option        | `enhancement`, `mvp`, `profile`, `rest`  | Yes | No       | #2421  |
| 1.8 | GDPR Data Export                         | Generate a ZIP archive of all user data: profile, schemas, activity, audit events | `enhancement`, `mvp`, `profile`, `rest`  | Yes | No       | #2420  |

### Detailed Issue Descriptions

#### 1.2 — Extended Profile Fields

Add optional profile fields to the `user_profile` table. All fields are nullable and user-controlled. Fields: `job_title` (varchar 100), `department` (varchar 100), `phone` (E.164 format), `bio` (text, max 500 chars), `social_links` (JSONB: { github, linkedin, twitter, website }).

**OpenAPI Endpoints:**
```
GET  /api/v1/profile          → 200: UserProfile
PUT  /api/v1/profile          → 200: UserProfile
  Body: {
    job_title?, department?, phone?, timezone?, locale?,
    bio?, social_links?: { github?, linkedin?, twitter?, website? }
  }
```

**Acceptance Criteria:**
- Phone stored in E.164 format; client validates format before submission
- Bio field enforces 500-character maximum
- Social link URLs validated as valid HTTPS URLs (no other schemes)
- Profile changes emit an `profile.update` audit log event
- #533 addressed by this issue

**Tech Stack:** PostgreSQL migration, libphonenumber-js for phone validation

Part of Epic: Profile Information & Account Settings (#2408)

---

#### 1.7 — Account Deletion Request

Implement a soft-deletion flow with a mandatory 7-day cool-down. On deletion request: mark user as `pending_deletion`, send confirmation email, schedule a background job. During cool-down the user can log in and cancel. After 7 days: anonymize PII, delete linked OAuth accounts, revoke all sessions and API keys.

**OpenAPI Endpoints:**
```
POST /api/v1/profile/deletion-request
  → 202: { scheduled_at: ISO8601, cancellation_deadline: ISO8601 }

DELETE /api/v1/profile/deletion-request
  → 200: { cancelled: true }
```

**Acceptance Criteria:**
- User receives confirmation email with cancellation link
- Login during cool-down shows a prominent "Your account is scheduled for deletion" banner
- After deletion: email becomes `deleted_{uuid}@deleted.invalid`, name becomes "Deleted User"
- All API keys revoked immediately on deletion request (not after cool-down)
- #535 addressed by this issue

Part of Epic: Profile Information & Account Settings (#2408)

---

#### 1.8 — GDPR Data Export

Generate a downloadable ZIP archive containing all data Objectified holds for the requesting user. Archive structure: `profile.json`, `schemas/`, `activity_log.jsonl`, `audit_events.jsonl`, `api_keys.json` (metadata only, not secrets). Export generated asynchronously; user notified via email with download link (expires 48 hours).

**OpenAPI Endpoints:**
```
POST /api/v1/profile/data-export
  → 202: { job_id }

GET /api/v1/profile/data-export/{job_id}
  → 200: { status: pending|complete, download_url?, expires_at? }
```

**Acceptance Criteria:**
- Export job completes in < 5 minutes for typical user data sets
- Download URL is signed and expires after 48 hours
- Archive verified to include all GDPR Article 20 data categories
- Export request itself logged in audit log
- #536 addressed by this issue

Part of Epic: Profile Information & Account Settings (#2408)

---

## Epic 2: Notification Preferences

**GitHub Epic:** #2409

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                           | MVP | Parallel | Issue  |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|----------------------------------|-----|----------|--------|
| 2.1 | Per-Event Email Notification Toggles       | Enable/disable email notifications per event type (review, mention, approval)    | `enhancement`, `mvp`, `profile` | Yes | No       | #2422  |
| 2.2 | In-App Notification Preferences            | Toggle in-app notification categories; configure unread badge visibility         | `enhancement`, `profile`        | No  | Yes      | #2423  |
| 2.3 | Digest Frequency Setting                   | Choose: instant, daily digest, weekly digest per event category                  | `enhancement`, `profile`        | No  | Yes      | #2424  |
| 2.4 | Quiet Hours / Do Not Disturb               | Define time windows (per timezone) when no notifications are sent                | `enhancement`, `profile`        | No  | Yes      | #2425  |
| 2.5 | Slack/Teams Integration Preferences        | Link personal Slack/Teams handle for direct message notifications                | `enhancement`, `profile`        | No  | Yes      | #2427  |
| 2.6 | Webhook Notifications for Account Events   | POST to a personal webhook URL on account events (login, key created, etc.)      | `enhancement`, `profile`, `rest` | No | Yes     | #2426  |

---

## Epic 3: Security Settings

**GitHub Epic:** #2410

### Summary Table

| #   | Title                                      | Description                                                                       | Labels                                      | MVP | Parallel | Issue  |
|-----|--------------------------------------------|-----------------------------------------------------------------------------------|---------------------------------------------|-----|----------|--------|
| 3.1 | TOTP Two-Factor Authentication             | Enroll and verify TOTP (Google Authenticator, Authy); enforce on login            | `enhancement`, `mvp`, `profile`, `security` | Yes | No       | #2428  |
| 3.2 | Backup / Recovery Codes                    | Generate 10 single-use recovery codes on 2FA enrollment; regenerate on demand    | `enhancement`, `mvp`, `profile`, `security` | Yes | Yes      | #2429  |
| 3.3 | WebAuthn Security Keys (FIDO2)             | Register hardware security keys (YubiKey, etc.) as 2FA or passwordless method    | `enhancement`, `profile`, `security`        | No  | No       | #2430  |
| 3.4 | Trusted Devices Management                 | Mark a device as trusted to skip 2FA for 30 days; view and revoke trusted devices| `enhancement`, `profile`, `security`        | No  | Yes      | #2431  |
| 3.5 | Password Strength Indicator                | Real-time strength meter on password change; enforce minimum score of "Good"     | `enhancement`, `mvp`, `profile`             | Yes | Yes      | #2432  |
| 3.6 | Security Activity Log                      | Last 30 days of security-relevant events: logins, 2FA changes, key activity      | `enhancement`, `mvp`, `profile`             | Yes | Yes      | #2433  |
| 3.7 | Suspicious Activity Alerts                 | Email alert when login occurs from a new country or unusual IP geolocation       | `enhancement`, `mvp`, `profile`             | Yes | Yes      | #2434  |

### Detailed Issue Descriptions

#### 3.1 — TOTP Two-Factor Authentication

Implement TOTP enrollment using otplib. Generate a QR code linking a TOTP secret to the user's account. Require verification of the first TOTP code before enabling 2FA. Once enabled, require TOTP on every login after password verification.

```
Enrollment Flow:
  1. User clicks "Enable 2FA"
  2. Server generates secret, stores encrypted in user_2fa_config
  3. QR code rendered (otpauth:// URI)
  4. User scans with authenticator app
  5. User enters 6-digit code → server verifies → 2FA enabled
  6. Backup codes generated and displayed once
```

**Acceptance Criteria:**
- TOTP secret stored AES-256 encrypted at rest
- 30-second time window with ±1 step tolerance (handles clock skew)
- Disabling 2FA requires TOTP verification first
- Recovery code consumption is idempotent (used code cannot be reused)

**Tech Stack:** otplib, QRCode.js, AES-256-GCM secret encryption

Part of Epic: Security Settings (#2410)

---

## Epic 4: Personalization

**GitHub Epic:** #2411

### Summary Table

| #   | Title                                   | Description                                                                        | Labels                           | MVP | Parallel | Issue  |
|-----|-----------------------------------------|------------------------------------------------------------------------------------|----------------------------------|-----|----------|--------|
| 4.1 | Theme Preference (Light/Dark/System)    | User-selectable theme; system tracks OS preference; persisted server-side          | `enhancement`, `mvp`, `profile` | Yes | Yes      | #2435  |
| 4.2 | Default Landing Page After Login        | Choose where to land: dashboard, last project, specific project/page               | `enhancement`, `mvp`, `profile` | Yes | Yes      | #2436  |
| 4.3 | Keyboard Shortcut Customization         | Override default keyboard shortcuts from a settings panel                          | `enhancement`, `profile`        | No  | Yes      | #2437  |
| 4.4 | Favorite Projects Quick Access List     | Pin up to 10 projects; visible in nav sidebar for one-click access                 | `enhancement`, `mvp`, `profile` | Yes | Yes      | #2438  |

---

## Epic 5: Developer Settings

**GitHub Epic:** #2412

### Summary Table

| #   | Title                                   | Description                                                                        | Labels                                    | MVP | Parallel | Issue  |
|-----|-----------------------------------------|------------------------------------------------------------------------------------|-------------------------------------------|-----|----------|--------|
| 5.1 | Personal API Keys (User-Scoped)         | User-scoped API keys that only inherit the user's permissions, not tenant admin    | `enhancement`, `mvp`, `profile`, `rest`  | Yes | No       | #2439  |
| 5.2 | SSH Keys for Git Operations             | Upload SSH public keys for Git-based schema sync workflows                         | `enhancement`, `profile`, `rest`         | No  | Yes      | #2440  |
| 5.3 | Personal Webhook Endpoints              | Configure webhooks for personal-account events (schema edit, review assigned)     | `enhancement`, `profile`, `rest`         | No  | Yes      | #2442  |
| 5.4 | CLI / SDK Authentication Tokens         | Generate long-lived CLI tokens with narrower scopes than API keys                  | `enhancement`, `profile`, `rest`         | No  | Yes      | #2441  |
| 5.5 | API Usage Statistics (Personal)         | Per-user breakdown of API call volume across personal and tenant keys             | `enhancement`, `profile`                 | No  | Yes      | #2443  |

---

## Epic 6: Enterprise Identity & Governance

**GitHub Epic:** #2413

### Summary Table

| #   | Title                                         | Description                                                                      | Labels                                          | MVP | Parallel | Issue  |
|-----|-----------------------------------------------|----------------------------------------------------------------------------------|-------------------------------------------------|-----|----------|--------|
| 6.1 | SAML 2.0 SSO Integration                      | IdP-initiated and SP-initiated SAML 2.0 with metadata exchange                  | `enhancement`, `profile`, `security`           | No  | No       | #2444  |
| 6.2 | OIDC (OpenID Connect) Support                 | OIDC provider integration; map claims to Objectified roles                       | `enhancement`, `profile`, `security`           | No  | Yes      | #2445  |
| 6.3 | LDAP / Active Directory Sync                  | Sync users, groups, and role assignments from LDAP/AD on configurable schedule  | `enhancement`, `profile`, `security`           | No  | No       | #2446  |
| 6.4 | SCIM 2.0 Provisioning                         | Implement SCIM 2.0 API for automated user provisioning/deprovisioning           | `enhancement`, `profile`, `security`, `rest`   | No  | No       | #2447  |
| 6.5 | Mandatory MFA Enforcement (Tenant Policy)     | Tenant-wide policy requiring all users to enroll 2FA within N days              | `enhancement`, `profile`, `security`           | No  | Yes      | #2448  |
| 6.6 | IP-Based Access Restrictions per User         | Allow only specified CIDRs per user account; block all other IPs                | `enhancement`, `profile`, `security`           | No  | Yes      | #2449  |
| 6.7 | Conditional Access Policies                   | Access rules based on: location, device trust, time-of-day, risk score          | `enhancement`, `profile`, `security`           | No  | No       | #2450  |
| 6.8 | User Access Reviews / Recertification         | Periodic manager review of each user's role assignments; automated reminders    | `enhancement`, `profile`, `security`           | No  | No       | #2451  |
| 6.9 | Delegation & Proxy Access                     | Delegate account access for vacation mode; impersonation for support (audited)  | `enhancement`, `profile`, `security`           | No  | No       | #2452  |
| 6.10 | Bulk User Import/Export (CSV, SCIM)          | Import new users from CSV or SCIM batch payload; export user roster as CSV      | `enhancement`, `profile`, `rest`               | No  | Yes      | #2453  |
| 6.11 | Enterprise Directory (People Search)         | Org-wide people search by name, role, department, skills; org chart view        | `enhancement`, `profile`                       | No  | Yes      | #2454  |
| 6.12 | Right to Be Forgotten Workflow               | Trigger full PII deletion across all data stores for a specific user            | `enhancement`, `profile`, `security`           | No  | No       | #2455  |

### Detailed Issue Descriptions

#### 6.4 — SCIM 2.0 Provisioning

Implement the SCIM 2.0 REST API so enterprise IdPs (Okta, Azure AD, etc.) can automatically provision, update, and deprovision Objectified users without manual admin intervention. Support: User create/read/update/delete, Group create/read/update/delete, and the `/ServiceProviderConfig` discovery endpoint.

**OpenAPI Endpoints (SCIM 2.0 standard paths):**
```
GET  /scim/v2/ServiceProviderConfig   → 200: ServiceProviderConfig
GET  /scim/v2/Users                   → 200: UserList (SCIM ListResponse)
POST /scim/v2/Users                   → 201: User
GET  /scim/v2/Users/{id}              → 200: User
PUT  /scim/v2/Users/{id}              → 200: User
PATCH /scim/v2/Users/{id}             → 200: User (partial update)
DELETE /scim/v2/Users/{id}            → 204

GET  /scim/v2/Groups                  → 200: GroupList
POST /scim/v2/Groups                  → 201: Group
PUT  /scim/v2/Groups/{id}             → 200: Group
DELETE /scim/v2/Groups/{id}           → 204
```

**Acceptance Criteria:**
- Passes the Okta SCIM 2.0 integration test suite
- User deprovisioning suspends the user account (does not delete data)
- Group membership changes map to Objectified team membership
- SCIM bearer token separate from regular API keys; rotatable independently
- All SCIM operations logged in the audit trail

Part of Epic: Enterprise Identity & Governance (#2413)
