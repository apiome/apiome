# Persisted publication change reports (CR-02, #2700)

This document describes the REST contract for **stored** change reports tied to a **published** schema revision (`versions.id`). Ephemeral diff-only APIs remain under `POST /v1/openapi/change-report` (CR-01).

## Data model (summary)

| Column | Purpose |
|--------|---------|
| `change_model_json` | Immutable `ChangeReportModel` JSON after first insert; source for **regenerate**. |
| `rendered_body`, `header_snapshot`, `footnote_snapshot` | Last **render** output (template pipeline; placeholder until CR-03). |
| `edited_*` | Optional **full snapshots** of user overrides per field. `NULL` means “use rendered value” for that field. |
| `effective*` (response only) | `edited*` if set, else rendered\* (per field). |

**Idempotency:** `published_revision_id` is unique. Seeding the same revision twice does not create duplicate rows; the first `change_model_json` is kept.

## Authorization

| Operation | JWT | API key | Who may call |
|-----------|-----|---------|----------------|
| `GET …/change-report` | Yes | Yes | Any caller with tenant access (same as other version reads). |
| `PATCH …/change-report` | Yes | No | Version **creator** or **tenant administrator**. |
| `POST …/change-report/regenerate` | Yes | No | Same as PATCH. |

## Routes

Base path: `/v1/versions/{tenantSlug}/{projectId}/{versionRecordId}`

### GET `/change-report`

Returns **404** if no row exists, **400** if the revision is not published.

**200 response (abbreviated):**

```json
{
  "id": "uuid",
  "tenantId": "uuid",
  "projectId": "uuid",
  "publishedRevisionId": "uuid",
  "baselineRevisionId": "uuid or null",
  "changeModelJson": { },
  "renderedBody": "string or null",
  "headerSnapshot": "string or null",
  "footnoteSnapshot": "string or null",
  "editedRenderedBody": "string or null",
  "editedHeaderSnapshot": "string or null",
  "editedFootnoteSnapshot": "string or null",
  "effectiveRenderedBody": "string or null",
  "effectiveHeaderSnapshot": "string or null",
  "effectiveFootnoteSnapshot": "string or null",
  "editedAt": "ISO-8601 or null",
  "editedBy": "uuid or null",
  "templateVersionId": "uuid or null",
  "renderedAt": "ISO-8601 or null",
  "regeneratedAt": "ISO-8601 or null",
  "createdAt": "ISO-8601",
  "updatedAt": "ISO-8601"
}
```

### PATCH `/change-report`

**User edits** use **full snapshots**, not diffs. Optional body:

```json
{
  "editedRenderedBody": "optional string; null clears override for body",
  "editedHeaderSnapshot": "optional",
  "editedFootnoteSnapshot": "optional",
  "clearEdits": false
}
```

- Set `clearEdits` to `true` to drop all `edited_*` fields and clear `editedAt` / `editedBy`.
- Otherwise include at least one `edited*` field (can be `null` to clear that slice only).

**200:** Same shape as GET.

### POST `/change-report/regenerate`

Re-renders from stored `changeModelJson` using the **Mustache** template pipeline (**CR-03**). See **`apiome-rest/docs/CHANGE_REPORT_TEMPLATES_API.md`**.

```json
{
  "templateVersionId": "optional uuid; when omitted, existing linkage is kept",
  "discardUserEdits": true
}
```

- `discardUserEdits` (default `true`): when true, clears all `edited_*` after render; when false, keeps user edit snapshots while updating rendered layers.

**200:** Same shape as GET.

## Database migration

Apply `apiome-db/scripts/20260414-140000.sql` to create `apiome.change_reports`.

### Rollback

```sql
SET search_path TO apiome, public;
DROP TABLE IF EXISTS change_reports CASCADE;
```
