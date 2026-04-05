# Objectified: Security & Access Control - Feature Roadmap

> Comprehensive security layer covering role-based access control (RBAC), fine-grained permission categories, SSO expansion, user and team management, and compliance-grade audit/permission tooling. Builds on the existing foundation of GitHub/GitLab OAuth, JWT token management, and API key encryption.
>
> **Revenue Model**: Built-in roles (Viewer → Editor → Admin) included in all tiers; custom roles, resource-level permissions, team management, and permission matrix export gated at Pro; access request workflows, periodic access reviews, and over-privilege detection are Enterprise-only
>
> **Tech Stack**: NextJS App Router, PostgreSQL (RBAC schema), Redis (permission cache), OpenAPI 3.1, SAML 2.0, OIDC, node-saml

---

## MVP Definition

- Built-in role hierarchy: Super Admin, Tenant Owner, Tenant Admin, Project Admin, Editor, Reviewer, Viewer, API Consumer
- Granular permission categories: tenant, project, version, schema, path, export, and AI permissions
- Role assignment UI on user profile with role effective and expiration dates
- User invitation by email with role assignment; bulk CSV invite
- User status management: active/inactive/pending/suspended
- Team creation with role-based project access
- Permission matrix view: grid of roles vs permissions with export to CSV
- All permission changes logged in audit trail

---

## Epic 1 (#1647): Role-Based Access Control

### Summary Table

| #   | Title                                     | Description                                                                        | Labels                                      | MVP | Parallel |
|-----|-------------------------------------------|------------------------------------------------------------------------------------|---------------------------------------------|-----|----------|
| 1.1 (#1649) | Built-In Role Definitions & Hierarchy     | Define 8 built-in roles from Super Admin to API Consumer with clear hierarchy      | `enhancement`, `mvp`, `security`, `rest`   | Yes | No       |
| 1.2 (#1651) | Role Assignment UI                        | Assign roles from the user profile Roles tab; support future-dated and expiring    | `enhancement`, `mvp`, `security`           | Yes | No       |
| 1.3 (#1653) | Custom Role Creation                      | Create custom roles by cloning a built-in role and adjusting individual permissions| `enhancement`, `security`                  | No  | No       |
| 1.4 (#1655) | Custom Role Management                    | Enable/disable custom roles; custom name, description, icon; audit on change       | `enhancement`, `security`                  | No  | Yes      |
| 1.5 (#1657) | Permission Matrix View                    | Grid visualization: roles as columns, permissions as rows; compare roles side-by-side | `enhancement`, `mvp`, `security`        | Yes | No       |
| 1.6 (#1659) | Permission Matrix Export                  | Export the permission matrix as CSV for compliance documentation                   | `enhancement`, `security`                  | No  | Yes      |
| 1.7 (#1661) | Access Request Workflow                   | Users request access to a project; approval workflow with email notification       | `enhancement`, `security`                  | No  | No       |
| 1.8 (#1663) | Graceful Permission Degradation           | Hide unauthorized UI elements rather than showing them disabled                    | `enhancement`, `mvp`, `security`           | Yes | Yes      |
| 1.9 (#1665) | Permission Caching                        | Cache resolved permissions in Redis (TTL: 5 minutes) to reduce DB load            | `enhancement`, `security`                  | No  | Yes      |
| 1.10 (#1667) | Real-Time Permission Validation          | Re-validate permissions on route change; clear cache on role assignment change    | `enhancement`, `mvp`, `security`           | Yes | No       |

### Detailed Issue Descriptions

#### 1.1 (#1649) — Built-In Role Definitions & Hierarchy

Define the canonical set of built-in roles and store them in a `system_role` table. Higher roles inherit all permissions of lower roles. The hierarchy: API Consumer < Viewer < Reviewer < Editor < Project Admin < Tenant Admin < Tenant Owner < Super Admin.

```
Role Hierarchy (permissions cumulative top-down):

Super Admin
  └── Tenant Owner
        └── Tenant Admin
              └── Project Admin
                    └── Editor
                          └── Reviewer
                                └── Viewer
                                      └── API Consumer

Built-in roles are immutable (system-managed).
Custom roles are tenant-managed.
```

| Role           | Key Capabilities                                          |
|----------------|-----------------------------------------------------------|
| Super Admin    | Full system access, manage all tenants                    |
| Tenant Owner   | Full tenant + billing + delete tenant                     |
| Tenant Admin   | Manage users, projects, settings (no billing/delete)      |
| Project Admin  | Full project access, manage project members               |
| Editor         | Create/edit schemas, paths, versions (no project settings)|
| Reviewer       | Comment, approve/reject, read-only schema access          |
| Viewer         | Read-only access to schemas and documentation             |
| API Consumer   | API key access only, no UI access                         |

**Acceptance Criteria:**
- `system_role` table seeded in migration with all 8 roles and descriptions
- Role hierarchy enforced: a user cannot assign a role higher than their own
- Built-in roles cannot be modified or deleted by tenants
- OpenAPI enum schema documents all role names

Part of Epic: Role-Based Access Control

---

#### 1.5 (#1657) — Permission Matrix View

Render a scrollable grid that maps every defined permission string (rows) against every role (columns). A checkmark indicates the role grants that permission. Built-in roles are shown first, then custom roles. Clicking a cell for a custom role toggles the permission (with confirmation).

```
Permission Matrix                              [Export CSV]
────────────────────────────────────────────────────────────────
Permission           │ Viewer │ Editor │ Proj Admin │ Custom A │
─────────────────────┼────────┼────────┼────────────┼──────────┤
schemas:read         │   ✓   │   ✓   │     ✓      │    ✓    │
schemas:write        │        │   ✓   │     ✓      │    ✓    │
schemas:delete       │        │        │     ✓      │         │
project:update       │        │        │     ✓      │         │
ai:generate          │        │   ✓   │     ✓      │    □    │  ← toggleable for custom roles
────────────────────────────────────────────────────────────────
```

**Acceptance Criteria:**
- Matrix renders all 40+ permission strings without horizontal scroll on 1440px viewport
- Custom role permission toggles persist via PATCH to `/api/v1/admin/roles/{id}/permissions`
- Built-in role columns are read-only (no toggles)
- Export generates a CSV with the same data

Part of Epic: Role-Based Access Control

---

## Epic 2 (#1669): Permission Categories

### Summary Table

| #   | Title                                    | Description                                                                       | Labels                              | MVP | Parallel |
|-----|------------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------|-----|----------|
| 2.1 (#1671) | Tenant Permission Set                    | `tenant:*` permissions: read, update, delete, billing, users:*, api-keys:*       | `enhancement`, `mvp`, `security`   | Yes | No       |
| 2.2 (#1673) | Project & Version Permission Set         | `project:*` and `version:*` permissions: create, read, update, delete, publish   | `enhancement`, `mvp`, `security`   | Yes | Yes      |
| 2.3 (#1675) | Schema Permission Set                    | `class:*` and `property:*` permissions: create, read, update, delete             | `enhancement`, `mvp`, `security`   | Yes | Yes      |
| 2.4 (#1677) | Path Permission Set                      | `path:*` permissions: create, read, update, delete, publish                      | `enhancement`, `mvp`, `security`   | Yes | Yes      |
| 2.5 (#1679) | Export Permission Set                    | `export:openapi`, `export:code`, `export:documentation`, `export:diagram`        | `enhancement`, `mvp`, `security`   | Yes | Yes      |
| 2.6 (#1681) | AI Permission Set                        | `ai:chat`, `ai:generate`, `ai:review`, `ai:configure`                            | `enhancement`, `security`          | No  | Yes      |
| 2.7 (#1683) | Resource-Level Permission Overrides      | Override permissions at project, version, class, or path level for specific users | `enhancement`, `security`         | No  | No       |
| 2.8 (#1685) | Permission Inheritance Chain             | Project → Version → Class inheritance with explicit override capability           | `enhancement`, `security`          | No  | No       |

### Detailed Issue Descriptions

#### 2.7 (#1683) — Resource-Level Permission Overrides

Allow Project Admins to restrict access at a finer granularity than the tenant role: grant a user Viewer on a project, but override them to Editor on specific sensitive classes. Store overrides in a `resource_permission_override` table.

```
┌──────────────────────────────────────────────┐
│  resource_permission_override                │
├──────────────────────────────────────────────┤
│ id            UUID PK                        │
│ tenant_id     UUID FK                        │
│ user_id       UUID FK                        │
│ resource_type ENUM (project|version|class|path) │
│ resource_id   UUID                           │
│ permissions   TEXT[]  -- granted permissions │
│ deny          TEXT[]  -- explicitly denied   │
│ granted_by    UUID FK (users)                │
│ created_at    TIMESTAMPTZ                    │
└──────────────────────────────────────────────┘
```

**Acceptance Criteria:**
- Override evaluation: deny list checked first, then grant list, then role permissions
- Overrides visible in the user's permission summary on their profile
- Adding an override requires at least Project Admin role on the target resource
- All override changes logged in audit trail

Part of Epic: Permission Categories

---

## Epic 3 (#1687): User Management

### Summary Table

| #   | Title                                    | Description                                                                       | Labels                              | MVP | Parallel |
|-----|------------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------|-----|----------|
| 3.1 (#1689) | User Invitation by Email                 | Invite users by email with role pre-assignment; invitation expires in 7 days      | `enhancement`, `mvp`, `security`   | Yes | No       |
| 3.2 (#1691) | Bulk Invite via CSV                      | Upload a CSV of email addresses and roles; validate and send invitations in batch | `enhancement`, `security`          | No  | Yes      |
| 3.3 (#1693) | Invitation Management                    | View pending invitations; resend, revoke; shareable invitation link               | `enhancement`, `security`, `rest`  | No  | Yes      |
| 3.4 (#1695) | User Status Management                   | Active / Inactive / Pending / Suspended states; suspend with reason; last login   | `enhancement`, `mvp`, `security`   | Yes | No       |
| 3.5 (#1697) | User Profile View (Admin)                | Admin view of user: linked accounts, permission summary, activity, status history | `enhancement`, `mvp`, `security`   | Yes | Yes      |
| 3.6 (#1699) | Session Management (Admin)               | Admin can view and revoke any user's active sessions                             | `enhancement`, `security`          | No  | Yes      |
| 3.7 (#1701) | SSO: Okta Integration                    | SAML 2.0 / OIDC integration with Okta; attribute mapping to Objectified roles    | `enhancement`, `security`          | No  | No       |
| 3.8 (#1703) | SSO: Azure AD Integration                | Azure AD OAuth 2.0 / OIDC login; group-to-role mapping                           | `enhancement`, `security`          | No  | Yes      |
| 3.9 (#1705) | SSO: AWS Cognito Integration             | AWS Cognito OIDC/SAML login integration                                          | `enhancement`, `security`          | No  | Yes      |

### Detailed Issue Descriptions

#### 3.1 (#1689) — User Invitation by Email

Allow Tenant Admins to invite new users by email. The invitation record stores: invited email, assigned role, invited-by user, expiration timestamp (7 days), and a cryptographically secure token. The invitee receives an email with a link that either creates their account or links to an existing account.

**OpenAPI Endpoints:**
```
POST /api/v1/invitations
  Body: { email, role_id, project_id? }
  → 201: Invitation { id, expires_at, invite_link }

GET  /api/v1/invitations         → 200: InvitationList
DELETE /api/v1/invitations/{id}  → 204 (revoke)
POST /api/v1/invitations/{id}/resend → 200
```

**Acceptance Criteria:**
- Invitation token is a 32-byte random hex string (URL-safe)
- Inviting a user with an existing account sends a link-account flow, not a registration flow
- Expired tokens return 410 Gone with a clear message
- Invitations logged in audit trail with inviter, invitee, and role

Part of Epic: User Management

---

## Epic 4 (#1707): Team Management

### Summary Table

| #   | Title                                   | Description                                                                       | Labels                              | MVP | Parallel |
|-----|-----------------------------------------|-----------------------------------------------------------------------------------|-------------------------------------|-----|----------|
| 4.1 (#1709) | Team CRUD                               | Create, rename, and delete teams within a tenant                                 | `enhancement`, `mvp`, `security`   | Yes | No       |
| 4.2 (#1711) | Team Role Assignments                   | Assign a role to a team; all team members inherit the team role on projects       | `enhancement`, `mvp`, `security`   | Yes | No       |
| 4.3 (#1713) | Add / Remove Team Members               | Add users to teams; remove users; set team leads                                 | `enhancement`, `mvp`, `security`   | Yes | Yes      |
| 4.4 (#1715) | Team-Based Project Access               | Grant a team access to a project; team role applied to all current + future members| `enhancement`, `security`         | No  | Yes      |
| 4.5 (#1717) | Team Activity Dashboard                 | Per-team contribution metrics, pending reviews, and active member count          | `enhancement`, `security`          | No  | Yes      |

---

## Epic 5 (#1719): Audit & Compliance

### Summary Table

| #   | Title                                     | Description                                                                       | Labels                                       | MVP | Parallel |
|-----|-------------------------------------------|-----------------------------------------------------------------------------------|----------------------------------------------|-----|----------|
| 5.1 (#1721) | Permission Change Audit Log              | Log every role assignment/revocation and permission grant/deny with actor + timestamp | `enhancement`, `mvp`, `security`        | Yes | No       |
| 5.2 (#1723) | Permission Change Notifications           | Notify affected user when their roles or resource permissions change              | `enhancement`, `security`                   | No  | Yes      |
| 5.3 (#1725) | Periodic Access Reviews                   | Scheduled workflow: managers certify each user's role assignments are still valid | `enhancement`, `security`                   | No  | No       |
| 5.4 (#1727) | Compliance Report: Who Has Access to What | Export showing every user, their roles, and resource-level overrides             | `enhancement`, `security`, `rest`           | No  | Yes      |
| 5.5 (#1729) | Over-Privileged User Detection            | Flag users whose role grants permissions they have never exercised in 90 days    | `enhancement`, `security`                   | No  | Yes      |
| 5.6 (#1731) | Permission Cleanup Recommendations        | Surface specific permission downgrades recommended based on usage patterns       | `enhancement`, `security`                   | No  | Yes      |

### Detailed Issue Descriptions

#### 5.5 (#1729) — Over-Privileged User Detection

Compare each user's assigned role permissions against their actual permission usage (from audit log) over a rolling 90-day window. Flag any user where > 50% of their granted permissions have never been exercised. Surface these as a list in the Compliance dashboard with a "Review" button for each.

**Algorithm:**
```
For each user:
  granted_perms = resolve_role_permissions(user.role)
  used_perms = distinct permissions from audit_log
               where actor_id = user.id
               AND occurred_at > NOW() - 90 days
  unused_perms = granted_perms - used_perms
  if (unused_perms.count / granted_perms.count) > 0.5:
    flag as over-privileged
    recommend = minimum role that covers used_perms
```

**Acceptance Criteria:**
- Analysis runs on-demand and as a scheduled weekly job
- Results surfaced in Compliance dashboard with recommended replacement role
- Clicking "Review" opens the access review workflow (5.3)
- Analysis result not auto-applied — requires manual admin action

Part of Epic: Audit & Compliance
