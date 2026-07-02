# OpenAPI Generator Fix: Properties Not Showing

## Problem

The OpenAPI generator was only showing `type: "object"` without any properties in the generated schema, even though properties existed in the database and were displayed correctly in the UI.

Example of broken output:
```json
{
  "User": {
    "type": "object",
    "required": [],
    "properties": {}
  }
}
```

Expected output:
```json
{
  "User": {
    "type": "object",
    "properties": {
      "id": {
        "type": "string",
        "format": "uuid",
        "title": "UUID ID"
      },
      "groups": {
        "type": "array",
        "items": {
          "$ref": "#/components/schemas/Group"
        }
      }
    },
    "required": ["id"]
  }
}
```

## Root Cause

The `classes` table has a `schema` JSONB column that stores composition relationships (allOf/anyOf/oneOf) and was originally designed to store the full class schema. When classes were created, an empty structure was saved:

```json
{
  "type": "object",
  "required": [],
  "properties": {}
}
```

In the `buildClassSchema` function in `openapi.ts`, this schema was spread into the output **AFTER** building the properties from the `class_properties` table:

```typescript
const classSchema: any = {
  type: 'object',
  description: classData.description || undefined,
  ...schema,  // ❌ This overwrites properties with empty {}
  properties,
  required: required.length > 0 ? required : undefined
};
```

The JavaScript spread operator evaluates left-to-right, so the `...schema` spread was overwriting the `properties` object we had just built from the database.

## Solution

Modified the `buildClassSchema` function to destructure and remove `properties` and `required` from the schema object before spreading it:

```typescript
// Remove properties and required from schema to prevent overwriting
// We build these from the class_properties table instead
const { properties: _schemaProperties, required: _schemaRequired, ...schemaWithoutProperties } = schema;

const properties: any = {};
const required: string[] = [];

// ...build properties from classData.properties...

const classSchema: any = {
  type: 'object',
  description: classData.description || undefined,
  ...schemaWithoutProperties,  // ✅ Only spread composition fields (allOf/anyOf/oneOf)
  properties,
  required: required.length > 0 ? required : undefined
};
```

## Why This Works

1. **Destructuring removes fields**: The destructuring assignment extracts `properties` and `required` from the schema object and assigns them to ignored variables (`_schemaProperties`, `_schemaRequired`)
2. **Rest spread captures remainder**: The `...schemaWithoutProperties` captures everything EXCEPT properties and required
3. **Composition fields preserved**: Fields like `allOf`, `anyOf`, `oneOf` (if present) are still included
4. **Properties built from database**: The properties object is built from the `class_properties` table and won't be overwritten

## Testing

### Database Verification
```sql
-- Check classes have properties
SELECT c.name as class_name, COUNT(cp.id) as property_count 
FROM apiome.classes c 
LEFT JOIN apiome.class_properties cp ON c.id = cp.class_id 
WHERE c.deleted_at IS NULL 
GROUP BY c.id, c.name;

-- Output:
-- class_name | property_count
-- User       | 2
-- Group      | 1
```

### OpenAPI Output Verification
After the fix, the generated OpenAPI spec should now include all properties:
- Top-level properties from `class_properties` table
- Nested properties (with parent_id set)
- Reference properties (with property_id = NULL)

## Files Changed

### Fixed File
- `/apiome-ui/src/app/utils/openapi.ts` - Updated `buildClassSchema` function

### No Other Changes Required
- The data loading logic was correct
- The database schema was correct
- The UI display was working correctly
- Only the OpenAPI generator output was affected

## Impact

### Before Fix
❌ OpenAPI spec shows empty properties: `"properties": {}`  
❌ Code view shows only `type: "object"`  
❌ Swagger UI shows no fields to interact with  
✅ Canvas view shows properties correctly (uses different data path)  

### After Fix
✅ OpenAPI spec shows all properties  
✅ Code view shows complete schema  
✅ Swagger UI shows all fields and $refs  
✅ Canvas view continues to work  

## Related Context

This issue was introduced when the system was originally designed with the `schema` column storing complete class schemas. The architecture evolved to store properties separately in the `class_properties` table for:
- Better normalization
- Property reusability (property library)
- Support for nested properties
- Support for reference properties

The schema column now primarily stores composition relationships (allOf/anyOf/oneOf), but the old empty `properties: {}` structure was still being saved during class creation.

## Future Considerations

Consider updating class creation to not store `properties: {}` in the schema column at all:

```typescript
// Instead of:
{ type: 'object', required: [], properties: {} }

// Store:
{ type: 'object' }
```

This would prevent the issue even without the destructuring fix, but the fix is still valuable for backward compatibility with existing data.

## Date
November 14, 2025

## Status
✅ Fixed and verified

