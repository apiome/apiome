# Database Schema Compatibility Fix

## Issue
Error when loading version data:
```
error: column v.published_by does not exist
Error fetching public versions: error: column v.published_by does not exist
```

## Root Cause
The database queries in `lib/db/helper.ts` were trying to access columns that don't exist in the current database schema:
- `v.published_by`
- `u.name as publisher_name` 
- `u.email as publisher_email`

These columns may have existed in a newer version of the Apiome schema or were planned features that haven't been implemented yet in the database.

## Solution Applied

Removed references to non-existent columns from two functions:

### 1. `getPublicVersionsForProject()`

**Removed:**
- `v.published_by` column
- `u.name as publisher_name` column
- `u.email as publisher_email` column
- `LEFT JOIN apiome.users u ON v.published_by = u.id` (entire join)

**Now queries only:**
- `v.id`
- `v.version_id`
- `v.description`
- `v.change_log`
- `v.published`
- `v.visibility`
- `v.created_at`
- `v.updated_at`
- `v.published_at`

### 2. `getPublicVersionDetails()`

**Removed:**
- `v.published_by` column
- `u.name as publisher_name` column
- `u.email as publisher_email` column
- `LEFT JOIN apiome.users u ON v.published_by = u.id` (entire join)

**Now queries:**
- All version columns (without published_by)
- Project info (name, slug, description)
- Tenant info (name, slug, description)

## Files Modified

- ✅ `lib/db/helper.ts` - Removed non-existent column references
- ✅ `TROUBLESHOOTING.md` - Added database schema mismatch troubleshooting

## Verification

✅ **Build successful**: All TypeScript compilation passes  
✅ **No published_by references**: Verified with grep search  
✅ **No UI dependencies**: No components were using the removed fields  

## Database Schema Notes

The current database schema has these columns in `apiome.versions`:
- `id`
- `version_id`
- `description`
- `change_log`
- `published`
- `visibility`
- `created_at`
- `updated_at`
- `published_at`

**Missing columns** (that may exist in other Apiome installations):
- `published_by` - User ID who published the version

## For Future Database Migrations

If your database gets updated to include the `published_by` column, you can re-add it to the queries:

```typescript
// In getPublicVersionsForProject:
const result = await connectionPool.query(
  `SELECT v.id, v.version_id, v.description, v.change_log, v.published, v.visibility, 
          v.created_at, v.updated_at, v.published_at, v.published_by,
          u.name as publisher_name, u.email as publisher_email
   FROM apiome.versions v
   JOIN apiome.projects p ON v.project_id = p.id
   JOIN apiome.tenants t ON p.tenant_id = t.id
   LEFT JOIN apiome.users u ON v.published_by = u.id
   WHERE t.slug = $1
     AND p.slug = $2
     AND v.published = true
     AND v.visibility = 'public'
     AND t.deleted_at IS NULL
     AND p.deleted_at IS NULL
     AND v.deleted_at IS NULL
   ORDER BY v.created_at DESC`,
  [tenantSlug, projectSlug]
);
```

And display the publisher info in the UI:
```tsx
{version.publisher_name && (
  <p className="text-xs text-zinc-500">
    Published by {version.publisher_name}
  </p>
)}
```

## Status: RESOLVED ✅

**Date Fixed**: December 14, 2024

The application now works with the current database schema. All queries have been updated to only reference columns that exist in the database.

### Verification
- ✅ Build successful with no errors
- ✅ All SQL queries updated and verified
- ✅ No remaining references to `published_by`, `publisher_name`, or `publisher_email`
- ✅ Application ready for use

See [DATABASE_SCHEMA_FIX_VERIFICATION.md](DATABASE_SCHEMA_FIX_VERIFICATION.md) for detailed verification results.

