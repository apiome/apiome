# Objectified: Roles & Permissions (RBAC) - Feature Roadmap

> Production-grade Role-Based Access Control implementation for the Objectified commercial platform. Provides a layered authorization model from core tenant membership roles through fine-grained path and schema permissions, covering UI gating, REST enforcement, API key scopes, session governance, MFA policy, and compliance auditability.
>
> **Revenue Model**: Built-in RBAC (roles RP-01 through RP-10) included in all commercial tiers; advanced session governance (RP-11), MFA policy by role (RP-12), network access restrictions (RP-13), and audit ledger export (RP-14) gated at Pro/Enterprise; ownership transfer and version workflow controls are Enterprise-only
>
> **Tech Stack**: Next.js + TypeScript + Radix UI (frontend), `objectified-rest` (REST enforcement), PostgreSQL + Drizzle ORM (`objectified-db`), Redis (permission cache), JWT + API key dual authentication, TOTP (otplib)

---

## MVP Definition

- Core tenant membership role model: `tenant_membership` table with role enum, indexes, and audit timestamps
- Auth context hydration: every authenticated request carries `account_id`, `tenant_id`, and effective role
- RBAC policy matrix: roles (administrator, tenant-admin, member, schema-editor, viewer, publisher, auditor) mapped to permission actions (read, create, update, delete, publish, push, merge, admin)
- RBAC enforcement on all protected REST endpoints (403 with machine-readable error codes)
- Role-aware navigation: users only see sections permitted by their role; graceful 403 deep-link handling
- Tenant administrator management UI (Radix table/dialog workflows)
- API key scopes aligned to RBAC (keys cannot exceed granted role permissions)

---

## Epic 1 (#1543): Foundation — Membership Model & Auth Context

### Summary Table

| #   | Title                                           | Description                                                                       | Labels                                              | MVP | Parallel |
|-----|-------------------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 1.1 (RP-01) (#2224) | Core Tenant Membership Role Model      | `tenant_membership` table with role enum/lookup, indexes, audit timestamps        | `enhancement`, `mvp`, `roles`, `database`          | Yes | No       |
| 1.2 (RP-02) (#2225) | Auth Context Hydration                 | JWT and API key middleware inject `account_id`, `tenant_id`, effective role       | `enhancement`, `mvp`, `roles`, `rest`              | Yes | No       |
| 1.3 (RP-03) (#2226) | Tenant Administrator Management APIs   | List, add, remove admin roles; orphan-prevention invariants; OpenAPI documented   | `enhancement`, `mvp`, `roles`, `rest`              | Yes | No       |

### Detailed Issue Descriptions

#### 1.1 (RP-01) (#2224) — Core Tenant Membership Role Model

Establish the foundational `tenant_membership` table that all permission decisions will depend on. Role values are constrained through a PostgreSQL enum to ensure naming consistency across all services.

```
┌──────────────────────────────────────────────────────┐
│              tenant_membership                       │
├──────────────────────────────────────────────────────┤
│ id           UUID PK DEFAULT gen_random_uuid()       │
│ tenant_id    UUID FK NOT NULL                        │
│ account_id   UUID FK NOT NULL                        │
│ role         tenant_role ENUM NOT NULL               │
│ granted_by   UUID FK (accounts) nullable             │
│ created_at   TIMESTAMPTZ NOT NULL DEFAULT now()      │
│ updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()      │
│ UNIQUE (tenant_id, account_id)                       │
└──────────────────────────────────────────────────────┘

tenant_role ENUM:
  'super_admin' | 'administrator' | 'tenant_admin' |
  'schema_editor' | 'publisher' | 'member' | 'viewer' | 'auditor'

Indexes:
  (tenant_id, account_id)  — unique membership lookup
  (tenant_id, role)        — list users by role within tenant
  (account_id)             — list tenants for a user
```

**Acceptance Criteria:**
- Migration creates enum type and table; idempotent on re-run
- `UNIQUE (tenant_id, account_id)` prevents duplicate memberships
- Index on `(tenant_id, role)` supports "list all schema-editors in tenant" queries
- Seed script creates at least one `super_admin` membership for development

**Tech Stack:** PostgreSQL enum, Drizzle ORM migration, objectified-db

Part of Epic: Foundation — Membership Model & Auth Context

---

#### 1.2 (RP-02) (#2225) — Auth Context Hydration

Extend the authentication middleware so every authenticated request carries a `RequestContext` object with `account_id`, `tenant_id`, and `role[]` (array to support future multi-role). Support both JWT bearer tokens and API key headers. Return clear error responses for: missing tenant context, invalid membership, and disabled memberships.

```typescript
interface RequestContext {
  accountId: string;
  tenantId: string;
  roles: TenantRole[];
  apiKeyId?: string;      // present if authenticated via API key
  sessionId?: string;     // present if authenticated via JWT session
}

// Middleware attaches to req.ctx on every protected route
```

**Acceptance Criteria:**
- Both `Authorization: Bearer {jwt}` and `X-API-Key: {key}` populate `req.ctx` identically
- Missing `tenant_id` context returns `401` with `{"error": "tenant_context_required"}`
- Disabled membership returns `403` with `{"error": "membership_disabled"}`
- Context hydration adds < 5ms overhead (Redis-cached after first lookup)

**Tech Stack:** Next.js middleware, JWT decode, Redis permission cache (TTL: 5 minutes)

Part of Epic: Foundation — Membership Model & Auth Context

---

## Epic 2 (#1547): Policy Matrix & REST Enforcement

### Summary Table

| #   | Title                                           | Description                                                                       | Labels                                              | MVP | Parallel |
|-----|-------------------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 2.1 (RP-04) (#2227) | RBAC Policy Matrix & Permission Resolver | Centralized matrix: roles × permissions × scopes; reusable resolver function     | `enhancement`, `mvp`, `roles`, `rest`              | Yes | No       |
| 2.2 (RP-05) (#2228) | Enforce RBAC on All Protected Endpoints  | Apply resolver to every tenant/project/version/schema/path endpoint; 403 on deny | `enhancement`, `mvp`, `roles`, `rest`              | Yes | No       |
| 2.3 (RP-10) (#2229) | API Key Scopes Aligned to RBAC           | API keys bound to tenant + optional project + explicit scope set; cannot exceed role | `enhancement`, `mvp`, `roles`, `api-keys`, `rest` | Yes | No      |

### Detailed Issue Descriptions

#### 2.1 (RP-04) (#2227) — RBAC Policy Matrix & Permission Resolver

Create a single source-of-truth policy file that maps roles to permitted actions. Build a `resolvePermission(ctx, action, resource?)` function used by all REST handlers. The function is synchronous (policy is in-memory) and never hits the database on the hot path.

```typescript
type Action =
  | 'read' | 'create' | 'update' | 'delete'
  | 'publish' | 'push' | 'merge' | 'admin';

type Resource = 'tenant' | 'project' | 'version' | 'schema' | 'path' | 'api_key';

// Policy matrix (excerpt):
const POLICY: Record<TenantRole, Record<Resource, Action[]>> = {
  administrator: {
    tenant:  ['read','create','update','delete','admin'],
    project: ['read','create','update','delete'],
    version: ['read','create','update','delete','publish'],
    schema:  ['read','create','update','delete'],
    path:    ['read','create','update','delete','publish'],
    api_key: ['read','create','update','delete'],
  },
  schema_editor: {
    tenant:  ['read'],
    project: ['read'],
    version: ['read','create','update'],
    schema:  ['read','create','update','delete'],
    path:    ['read','create','update'],
    api_key: ['read'],
  },
  viewer: {
    tenant:  ['read'],
    project: ['read'],
    version: ['read'],
    schema:  ['read'],
    path:    ['read'],
    api_key: [],
  },
  // ... other roles
};

function resolvePermission(
  ctx: RequestContext,
  action: Action,
  resource: Resource
): boolean {
  return ctx.roles.some(role =>
    POLICY[role]?.[resource]?.includes(action) ?? false
  );
}
```

**Acceptance Criteria:**
- Policy is a TypeScript constant (zero runtime dependencies, fully type-checked)
- `deny-by-default`: any unrecognized role/resource/action combination returns `false`
- Unit tests cover all 8 roles × 6 resources × 8 actions = 384 combinations
- Policy changes are code-reviewed and require a migration entry documenting the intent

Part of Epic: Policy Matrix & REST Enforcement

---

#### 2.2 (RP-05) (#2228) — Enforce RBAC on All Protected Endpoints

Apply the RBAC resolver as middleware on every route that mutates or reads protected resources. Use a `requirePermission(action, resource)` middleware factory that calls `resolvePermission` and returns 403 on denial.

```typescript
// Express middleware factory
function requirePermission(action: Action, resource: Resource) {
  return (req: Request, res: Response, next: NextFunction) => {
    if (!resolvePermission(req.ctx, action, resource)) {
      return res.status(403).json({
        error: 'permission_denied',
        action,
        resource,
        message: `Your role does not permit '${action}' on '${resource}'`,
      });
    }
    next();
  };
}

// Usage:
router.delete('/schemas/:id',
  requirePermission('delete', 'schema'),
  schemaController.delete
);
```

**Acceptance Criteria:**
- Every route that previously had implicit role-checking is now explicit with `requirePermission`
- Integration tests confirm 403 for unauthorized role attempts on every protected route
- OpenAPI spec updated with `403` response schema and `security` requirement on each route
- No unprotected mutation endpoints remain after this ticket

Part of Epic: Policy Matrix & REST Enforcement

---

## Epic 3 (#1553): UI Role-Awareness & UX

### Summary Table

| #   | Title                                           | Description                                                                       | Labels                                          | MVP | Parallel |
|-----|-------------------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------------------|-----|----------|
| 3.1 (RP-06) (#2230) | Role-Aware Navigation & Page Gating     | Show/hide nav sections by role; tenant switcher; graceful unauthorized deep links | `enhancement`, `mvp`, `roles`, `ui`            | Yes | No       |
| 3.2 (RP-07) (#2231) | Tenant Administrators UI                | Radix Table/Dialog for list, add, remove admin roles; confirmation prompts        | `enhancement`, `mvp`, `roles`, `ui`            | Yes | No       |
| 3.3 (RP-08) (#2232) | Permission-Conditioned Component States | Hidden/disabled/read-only action controls; locked schema banner                   | `enhancement`, `mvp`, `roles`, `ui`            | Yes | No       |
| 3.4 (RP-09) (#2233) | Permission-Denied UX & Role Indicators  | Consistent 403 UX with explanation and next-action CTA; role shown in header      | `enhancement`, `mvp`, `roles`, `ui`            | Yes | Yes      |

### Detailed Issue Descriptions

#### 3.1 (RP-06) (#2230) — Role-Aware Navigation & Page Gating

Update the sidebar navigation component to conditionally render items based on `req.ctx.roles`. Use server-side rendering so unauthorized routes are never visible in the HTML. Add a tenant switcher dropdown for multi-tenant users. Handle unauthorized deep links by rendering a permission-denied screen.

```
Navigation rendering by role:
  viewer:        Projects, Schemas (read-only), Documentation
  member:        + Paths
  schema_editor: + Schema Editor (edit mode)
  publisher:     + Publish Controls, Version Management
  tenant_admin:  + Settings, Users, API Keys
  administrator: + Admin Portal, Billing, Tenant Management
```

**Acceptance Criteria:**
- Navigation rendered server-side; unauthorized items absent from HTML source
- Tenant switcher persists selected tenant in an httpOnly cookie (not localStorage)
- Deep link to unauthorized page renders `<PermissionDenied>` component with "Contact admin" CTA
- Role changes take effect within one request (Redis permission cache cleared on role update)

Part of Epic: UI Role-Awareness & UX

---

## Epic 4 (#1558): Session Governance & MFA Policy

### Summary Table

| #   | Title                                           | Description                                                                       | Labels                                              | MVP | Parallel |
|-----|-------------------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 4.1 (RP-11) (#2234) | Session Governance & Timeout Policy    | Configurable session timeout + refresh tokens; re-auth flows; revocation          | `enhancement`, `roles`, `security`                 | No  | No       |
| 4.2 (RP-12) (#2235) | Optional MFA Policy by Role & Action   | Enforce TOTP MFA for specific roles or sensitive actions (publish, delete, admin) | `enhancement`, `roles`, `security`                 | No  | No       |
| 4.3 (RP-13) (#2236) | Admin/API Network Access Restrictions  | CIDR-based restrictions for admin routes and API keys; early middleware check      | `enhancement`, `roles`, `security`                 | No  | No       |

### Detailed Issue Descriptions

#### 4.1 (RP-11) (#2234) — Session Governance & Timeout Policy

Implement configurable session timeout with refresh token support per tenant. Add session warning UI shown N minutes before expiry with "Stay signed in" action. Ensure session invalidation propagates immediately on role change or membership removal.

**Configuration:**
```
Tenant Session Policy:
  session_timeout_minutes:   60  (default)
  refresh_token_ttl_days:    30
  mfa_reauth_on_timeout:     false
  warn_before_expire_minutes: 5
```

**Acceptance Criteria:**
- Refresh token rotation: old token invalidated on use, new token issued
- Role change triggers immediate Redis cache invalidation for the affected user
- Session warning modal appears at `timeout - warn_before_expire_minutes`
- Multi-tab: signing out in one tab broadcasts `storage` event to sign out others

Part of Epic: Session Governance & MFA Policy

---

#### 4.2 (RP-12) (#2235) — Optional MFA Policy by Role & Action

Allow tenant admins to configure MFA requirements. When a protected action is attempted by a user who has not completed MFA within the session, challenge them with a TOTP dialog before proceeding.

```
MFA Policy Configuration:
  require_mfa_for_roles: [administrator, publisher]
  require_mfa_for_actions: [version:publish, tenant:delete, api_key:create]
  mfa_session_duration_minutes: 30  (re-prompts after this period)
```

**Acceptance Criteria:**
- MFA challenge enforced server-side (not client-only) via session flag check
- TOTP verification dialog uses existing `otplib` integration
- MFA session flag (`mfa_verified_at`) stored in JWT claims with expiry
- Recovery code path available if TOTP device unavailable

Part of Epic: Session Governance & MFA Policy

---

## Epic 5 (#1564): Audit & Ownership

### Summary Table

| #   | Title                                           | Description                                                                       | Labels                                              | MVP | Parallel |
|-----|-------------------------------------------------|-----------------------------------------------------------------------------------|-----------------------------------------------------|-----|----------|
| 5.1 (RP-14) (#2237) | Role & Access Audit Ledger             | Dedicated audit table: login attempts, role grants/removes, API key lifecycle    | `enhancement`, `mvp`, `roles`, `database`, `rest`  | Yes | No       |
| 5.2 (RP-15) (#2238) | Ownership Transfer & Safety Controls   | Transfer tenant admin ownership; prevent lockout via invariants; audit-logged     | `enhancement`, `roles`                             | No  | No       |
| 5.3 (RP-16) (#2239) | Permission-Aware Version Workflow      | RBAC on push/merge/branch/publish; protected branch policy per role              | `enhancement`, `roles`, `rest`                     | No  | No       |

### Detailed Issue Descriptions

#### 5.1 (RP-14) (#2237) — Role & Access Audit Ledger

Create a dedicated `rbac_audit_ledger` table that captures every authentication and authorization event. Unlike the general `audit_log`, this table is optimized for compliance export and access pattern analysis.

```
┌──────────────────────────────────────────────────────┐
│            rbac_audit_ledger                         │
├──────────────────────────────────────────────────────┤
│ id           UUID PK                                 │
│ tenant_id    UUID FK                                 │
│ actor_id     UUID FK (accounts)                      │
│ event_type   ENUM:                                   │
│              auth.login.success | auth.login.failure │
│              auth.logout | session.revoked           │
│              role.granted | role.revoked             │
│              permission.denied                       │
│              api_key.created | api_key.rotated       │
│              api_key.revoked | ownership.transferred │
│ target_id    UUID nullable                           │
│ target_type  VARCHAR (account | api_key | session)   │
│ role_value   VARCHAR nullable                        │
│ outcome      ENUM success | denied | error           │
│ ip_address   INET                                    │
│ user_agent   VARCHAR                                 │
│ metadata     JSONB                                   │
│ occurred_at  TIMESTAMPTZ                             │
└──────────────────────────────────────────────────────┘
```

**OpenAPI Endpoints:**
```
GET /api/v1/admin/rbac-audit
  ?tenant_id=&event_type=&actor_id=&from=&to=&limit=100&cursor=
  → 200: AuditLedgerPage

POST /api/v1/admin/rbac-audit/export
  Body: { format: csv|json, from, to, filters }
  → 202: ExportJob
```

**Acceptance Criteria:**
- Table is insert-only at the database role level (no UPDATE/DELETE granted to app role)
- Query endpoint responds in < 300ms using indexed cursor pagination
- CSV export includes all columns with UTC timestamps
- Retention period configurable (default: 2 years)

Part of Epic: Audit & Ownership

---

#### 5.3 (RP-16) (#2239) — Permission-Aware Version Workflow Controls

Apply RBAC permission checks to all version workflow operations. The `publisher` role is required for publish; the `administrator` role is required for delete; `push` and `merge` require at least `schema_editor`. Protected branches can be configured to require elevated role or MFA.

```typescript
// Version workflow permission matrix
const VERSION_WORKFLOW_PERMISSIONS = {
  'version:create':  ['schema_editor', 'publisher', 'administrator'],
  'version:update':  ['schema_editor', 'publisher', 'administrator'],
  'version:publish': ['publisher', 'administrator'],
  'version:delete':  ['administrator'],
  'version:push':    ['schema_editor', 'publisher', 'administrator'],
  'version:merge':   ['publisher', 'administrator'],
  'version:branch':  ['schema_editor', 'publisher', 'administrator'],
} as const;
```

**Acceptance Criteria:**
- Publish button hidden/disabled in UI for users without `publisher` role
- 403 returned from REST endpoint if `publisher` role not present
- Protected version flag (`protected: true`) adds MFA requirement for publish (if RP-12 configured)
- Version action history includes the actor's role at the time of the action

Part of Epic: Audit & Ownership
