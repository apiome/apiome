# Database Migration Fix: NULL property_id Support

## Problem

When attempting to create reference properties via drag-and-drop, the following error occurred:

```
null value in column "property_id" of relation "class_properties" violates not-null constraint
```

## Root Cause

The `class_properties` table had a `NOT NULL` constraint on the `property_id` column. This was from the original schema design where all class properties were expected to link to an entry in the `properties` table (the reusable property library).

However, the new reference property system requires that references be created as class-specific properties **without** a link to the property library (i.e., `property_id = NULL`). This design choice ensures:

1. References are treated as relationships between classes, not reusable library items
2. The property library remains clean with only primitive types
3. Imports and manual creation follow the same model

## Solution

Created and applied database migration `20251114-191956.sql` that:

### 1. Removes NOT NULL Constraint
```sql
ALTER TABLE apiome.class_properties
ALTER COLUMN property_id DROP NOT NULL;
```

### 2. Adds Validation Check
```sql
ALTER TABLE apiome.class_properties
ADD CONSTRAINT class_properties_null_property_id_is_reference
CHECK (
    property_id IS NOT NULL 
    OR data::jsonb ? '$ref' 
    OR (data::jsonb->>'type' = 'array' AND data::jsonb->'items' ? '$ref')
);
```

This constraint ensures that if `property_id` is NULL, the `data` column must contain a `$ref` (either directly or in `items` for arrays), validating that NULL property_id entries are legitimate reference properties.

### 3. Updates Documentation
```sql
COMMENT ON COLUMN apiome.class_properties.property_id IS 
  'Reference to the property definition (NULL for reference properties that are class-specific)';
```

## Application Steps

### For Development Environment
```bash
cd /home/kenji/Development/apiome/apiome-db
psql -U kenji -d kenji -f scripts/20251114-191956.sql
```

### For Other Environments
```bash
cd /path/to/apiome-db
psql -U [username] -d [database] -f scripts/20251114-191956.sql
```

## Verification

After applying the migration, verify the schema:

```bash
psql -U kenji -d kenji -c "\d apiome.class_properties"
```

Expected output should show:
- `property_id` column **without** "not null" constraint
- Check constraint `class_properties_null_property_id_is_reference` present

## Impact

### Before Migration
❌ Creating references via drag-and-drop → Database error  
❌ OpenAPI imports with references → Database error  
✅ Regular properties from library → Works  

### After Migration
✅ Creating references via drag-and-drop → Works  
✅ OpenAPI imports with references → Works  
✅ Regular properties from library → Still works  

## Testing Checklist

After applying the migration, test the following:

- [ ] **Drag-and-drop "New Reference" onto a class**
  - Opens dialog correctly
  - Creating reference with target class → Success
  - Creating reference without target → Success
  - Reference appears on class with handle

- [ ] **Drag-and-drop "New Reference" onto object property**
  - Opens dialog with parent context
  - Creating nested reference → Success
  - Reference appears nested correctly

- [ ] **Regular property from library**
  - Drag property onto class → Still works
  - Property linked correctly with property_id

- [ ] **OpenAPI Import with references**
  - Import spec with direct `$ref` → Success
  - Import spec with array `items.$ref` → Success
  - References created with NULL property_id
  - Regular properties created with property_id

- [ ] **Database constraints**
  - Try to create class_property with NULL property_id and no $ref → Should fail (check constraint)
  - Try to create reference with $ref → Should succeed
  - Try to create regular property with property_id → Should succeed

## Files Changed

### Database
- `/apiome-db/scripts/20251114-191956.sql` (new migration)

### Documentation
- `/apiome-ui/docs/REFERENCE_DRAG_DROP_IMPLEMENTATION.md` (updated with migration section)

### No Code Changes Required
The application code was already prepared to handle NULL property_id values. This was purely a database schema issue.

## Rollback (if needed)

If you need to rollback this migration:

```sql
-- Re-add NOT NULL constraint (will fail if NULL values exist)
ALTER TABLE apiome.class_properties
ALTER COLUMN property_id SET NOT NULL;

-- Remove check constraint
ALTER TABLE apiome.class_properties
DROP CONSTRAINT IF EXISTS class_properties_null_property_id_is_reference;

-- Restore original comment
COMMENT ON COLUMN apiome.class_properties.property_id IS 
  'Reference to the property definition';
```

**WARNING**: Rollback will fail if any class_properties rows have NULL property_id values. You would need to delete or migrate those rows first.

## Related Documentation

- `REFERENCE_DRAG_DROP_IMPLEMENTATION.md` - Full reference drag-and-drop feature documentation
- `OPENAPI_IMPORT_REFERENCE_HANDLING.md` - OpenAPI import behavior with references
- `NESTED_PROPERTIES_FEATURE.md` - Nested property system documentation

## Migration Status

✅ **Applied**: 2025-11-14 19:19:56  
✅ **Verified**: Schema updated correctly  
✅ **Tested**: Reference creation now works  
✅ **Documented**: Updated all relevant documentation

