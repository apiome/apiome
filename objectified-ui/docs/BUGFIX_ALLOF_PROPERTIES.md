# Bug Fix: allOf Classes Losing Additional Properties

## Problem
When editing a class in the canvas and adding an `allOf` definition to extend from another class, the additional properties defined directly on that class were disappearing. The class would show the `allOf` reference but lose all its own properties.

## Root Cause
There were two issues in the codebase:

### Issue 1: Schema Generation (openapi.ts)
In the `generateClassSchema` function (`/src/app/utils/openapi.ts`), when a schema had composition keywords (`allOf`, `anyOf`, or `oneOf`), the code was intentionally NOT including the `properties` and `required` fields in the output:

```typescript
if (hasComposition) {
  // Preserve composition structure - don't add type, properties, or required at root
  classSchema = {
    description: classData.description || undefined,
    ...schemaWithoutProperties
  };
}
```

This was incorrect because in OpenAPI, you CAN have properties alongside `allOf`. This is the standard way to extend a base class with additional fields:

```yaml
allOf:
  - $ref: '#/components/schemas/BaseClass'
properties:
  additionalField: 
    type: string
```

### Issue 2: Schema Saving (layout.tsx)
In the class dialog submit handler (`/src/app/ade/studio/layout.tsx`), when building the schema to save, the code was creating a NEW schema from scratch containing only the composition-related fields (allOf, anyOf, oneOf, discriminator, additionalProperties):

```typescript
const schema: any = { type: 'object' };

if (classForm.allOf.length > 0) {
  schema.allOf = classForm.allOf.map(...);
}
```

This completely discarded any existing `properties` and `required` fields that were defined in the class.

## Solution

### Fix 1: Include Properties with Composition Keywords
Modified `generateClassSchema` in `/src/app/utils/openapi.ts` to include properties even when composition keywords are present:

```typescript
if (hasComposition) {
  classSchema = {
    description: classData.description || undefined,
    ...schemaWithoutProperties
  };
  
  // Add properties if we have any defined in the class_properties table
  if (Object.keys(properties).length > 0) {
    classSchema.properties = properties;
    if (required.length > 0) {
      classSchema.required = required;
    }
  }
}
```

### Fix 2: Preserve Existing Schema When Editing
Modified `handleClassSubmit` in `/src/app/ade/studio/layout.tsx` to preserve the existing schema structure when editing a class:

```typescript
// Build schema - preserve existing schema structure when editing
let schema: any;
if (classDialog.mode === 'edit' && classDialog.selectedClass) {
  // Start with existing schema to preserve properties, required, and other fields
  const existingSchema = typeof classDialog.selectedClass.schema === 'string' 
    ? JSON.parse(classDialog.selectedClass.schema) 
    : classDialog.selectedClass.schema;
  schema = { ...existingSchema };
} else {
  // New class - start with basic object type
  schema = { type: 'object' };
}

// Update only the composition-related fields
// (allOf, anyOf, oneOf, discriminator, additionalProperties)
// Delete fields if they're not being used
```

## Testing
To test this fix:

1. Create a base class (e.g., "Animal") with some properties
2. Create a derived class (e.g., "Dog") with its own properties
3. Edit the "Dog" class and set `allOf` to extend from "Animal"
4. Save the class
5. Verify that:
   - The `allOf` reference is present in the schema
   - The Dog class's own properties are still present
   - The generated OpenAPI spec includes both the inheritance and additional properties

## Impact
This fix ensures that classes can properly use OpenAPI composition keywords (allOf/anyOf/oneOf) while maintaining their own additional properties. This is essential for:
- Class inheritance/extension patterns
- Polymorphic schemas
- Proper OpenAPI spec generation
- API documentation accuracy

## Files Modified
- `/Users/kenji/Development/objectified/objectified-ui/src/app/utils/openapi.ts`
- `/Users/kenji/Development/objectified/objectified-ui/src/app/ade/studio/layout.tsx`

