# Workflow audit list API (`#2578`, P1-06)

Tenant-scoped read API for the append-only **`apiome.workflow_audit`** ledger (git-like workflow actions).

## Endpoint

`GET /v1/versions/{tenant_slug}/workflow-audit`

Authentication: same as other version APIs — **JWT** (`Authorization: Bearer …`) or **API key** (`X-API-Key`), scoped to the tenant in the URL.

## Query parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `action` | string, repeatable | Filter `action` (e.g. `version.push`, `version.pull`). Repeat for multiple values (OR). |
| `actorId` | UUID | Filter by `actor_id`. |
| `outcome` | string | `success` or `failure`. |
| `versionId` | UUID | Filter by revision id (`versions.id`) on the row. |
| `projectId` | UUID | Restrict to a project; must exist under the tenant or **404**. |
| `since` | ISO 8601 datetime | Inclusive lower bound on `created_at`. |
| `until` | ISO 8601 datetime | Inclusive upper bound on `created_at`. |
| `limit` | int (1–500, default 50) | Page size. |
| `offset` | int (≥ 0, default 0) | **Offset mode:** skip rows (newest-first order). |
| `cursor` | string | **Cursor mode:** opaque token from `pagination.nextCursor`. |

Do **not** pass **`cursor`** together with a **non-zero** `offset` (**400**).

## Sort order

Rows are returned **newest first**: `created_at DESC`, `id DESC`.

## Response JSON (`schemaVersion` 1)

Stable envelope (bump **`schemaVersion`** only on incompatible changes):

```json
{
  "schemaVersion": 1,
  "items": [
    {
      "id": "uuid",
      "tenantId": "uuid",
      "projectId": "uuid or null",
      "versionId": "uuid or null",
      "action": "string",
      "outcome": "success | failure",
      "actorId": "uuid or null",
      "detail": {},
      "createdAt": "ISO 8601 string"
    }
  ],
  "pagination": {
    "limit": 50,
    "total": 123,
    "hasMore": true,
    "offset": 0,
    "nextOffset": 50,
    "nextCursor": null
  }
}
```

### Offset mode

- **`pagination.offset`**: starting offset of this page.
- **`pagination.nextOffset`**: pass as `offset` on the next request when **`hasMore`** is true.
- **`pagination.nextCursor`**: when **`hasMore`** is true, also set to a cursor for the last row on this page — you may use either **`nextOffset`** or **`nextCursor`** for the following page (not both).

### Cursor mode

- Omit **`offset`** (or use **`0`**). Pass **`cursor`** from the previous response’s **`pagination.nextCursor`**.
- **`pagination.offset`** / **`nextOffset`** are null.
- **`total`** is still the count of all rows matching the filters (excluding pagination).

## `version.rollback` detail shape (`#2582`)

For **`action`** = **`version.rollback`**, **`detail`** is a JSON object that may include:

| Key | Meaning |
|-----|---------|
| `fromRevision` | Branch tip revision (`versions.id`) before the rollback attempt (when known). |
| `toRevision` | On **success**, the new head revision created by the rollback; on failed attempts before a new row exists, the **target** revision id; if a new revision was inserted but the transaction failed, the attempted new revision id may appear via `attemptedNewRevisionId`. |
| `branchName` | Git-like branch label. |
| `reason` | Optional operator reason from the rollback request body. |
| `targetRevisionId` / `priorTipRevisionId` | Snapshot source and previous tip (same lineage as `metadata.rollback` on the new revision). |

**`actorId`** and **`createdAt`** on the audit row identify **who** and **when**; they are not duplicated inside **`detail`**.

## Errors

| Code | When |
|------|------|
| 400 | Bad UUID, bad ISO datetime, invalid `outcome`, invalid `cursor`, or `cursor` + non-zero `offset`. |
| 404 | `projectId` set but project not found for the tenant. |
