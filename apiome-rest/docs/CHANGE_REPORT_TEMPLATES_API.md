# Change report templates (CR-03, #2701)

Publication change reports are rendered server-side with **Mustache** (`chevron` on Python): **header**, **body**, and **footnote** strings. There is no arbitrary code execution in templates.

## System default

- **Semver:** `1.0.0`
- **Id:** `00000000-0000-4000-a000-000000000001` (inserted by migration/startup seed; same content is bundled in the app for fallback)

The footnote template includes a **`generatorVersion`** token (package version string).

## Resolution order (regenerate & future publish hook)

1. Optional explicit `templateVersionId` on `POST …/change-report/regenerate`
2. Project `changeReportTemplateVersionId` (if set)
3. Tenant `changeReportTemplateVersionId` (if set)
4. System template `1.0.0`

System templates (`ownerTenantId: null`) are visible to all tenants. Tenant-created templates are scoped to that tenant.

## Routes (base: `/v1/tenants/{tenantSlug}`)

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/change-report-template-versions` | JWT or API key | List **id**, **semver**, **ownerTenantId**, **createdAt** (no full template bodies) |
| POST | `/change-report-template-versions` | JWT, **tenant admin** | Create a tenant-scoped template triple; **400** if Mustache invalid |
| PUT | `/change-report-template-default` | JWT, **tenant admin** | Set/clear tenant default (`templateVersionId` or `null`) |
| PUT | `/projects/{projectId}/change-report-template-default` | JWT, **project creator or tenant admin** | Set/clear project override |

### Validation errors

POST returns **400** with a short message if:

- `semver` is not a simple token (1–64 chars from `[A-Za-z0-9._-]`), or
- any of `headerTemplate`, `bodyTemplate`, `footnoteTemplate` fails a minimal Mustache render (syntax / structure).

### Project settings (alternative)

`PUT /v1/projects/{tenantSlug}/{projectId}` accepts optional `changeReportTemplateVersionId` (same semantics as the dedicated PUT above) for clients that already update projects in one call.

## Database

Apply `apiome-db/scripts/20260414-150000.sql` (adds `change_report_template_versions`, tenant/project FK columns).

See also: `apiome-rest/docs/CHANGE_REPORT_PERSISTENCE_API.md`.
