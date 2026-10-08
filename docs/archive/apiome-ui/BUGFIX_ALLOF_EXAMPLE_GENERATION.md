# Bug Fix: allOf Example Generation Missing Inherited Properties

## Problem
When viewing a class in the Class Edit Dialog and switching to the "EXAMPLE" view, the generated example data only included properties defined directly on the class itself. Properties inherited through `allOf` composition from parent classes were not being included in the generated examples.

## Root Cause
The `resolveRefs` function in `/src/app/components/ade/studio/ClassEditDialog.tsx` was resolving `$ref` references and merging `allOf` schemas, but had an issue with the merge order when combining inherited properties with additional properties.

The original code looked like this:

```typescript
// Handle allOf by merging schemas
if (Array.isArray(schema.allOf)) {
  const merged: any = {};
  const requiredSet = new Set<string>();

  schema.allOf.forEach((subSchema: any, index: number) => {
    const resolved = resolveRefs(subSchema, schemas, visited, `${path}/allOf[${index}]`);
    
    // Extract and merge properties from resolved schemas
    const { required: resolvedRequired, properties: resolvedProperties, ...resolvedRest } = resolved;
    
    Object.assign(merged, resolvedRest);
    
    if (resolvedProperties) {
      merged.properties = { ...merged.properties, ...resolvedProperties };
    }
    
    if (resolvedRequired) {
      resolvedRequired.forEach((field: string) => requiredSet.add(field));
    }
  });

  if (requiredSet.size > 0) {
    merged.required = Array.from(requiredSet);
  }

  // Keep other properties from the original schema
  const { allOf, ...rest } = schema;
  return { ...merged, ...rest }; // ❌ PROBLEM: rest overwrites merged properties
}
```

The issue was in the final line: `return { ...merged, ...rest }`. The `rest` object contained the original schema's `properties` and `required` arrays (at the same level as `allOf`). By spreading `rest` after `merged`, it would overwrite the carefully merged properties from the `allOf` resolution.

## Solution

Modified the `resolveRefs` function to explicitly extract and merge the `properties` and `required` fields from the original schema:

```typescript
// Handle allOf by merging schemas
if (Array.isArray(schema.allOf)) {
  const merged: any = {};
  const requiredSet = new Set<string>();

  schema.allOf.forEach((subSchema: any, index: number) => {
    const resolved = resolveRefs(subSchema, schemas, visited, `${path}/allOf[${index}]`);
    
    const { required: resolvedRequired, properties: resolvedProperties, ...resolvedRest } = resolved;
    
    Object.assign(merged, resolvedRest);
    
    if (resolvedProperties) {
      merged.properties = { ...merged.properties, ...resolvedProperties };
    }
    
    if (resolvedRequired) {
      resolvedRequired.forEach((field: string) => requiredSet.add(field));
    }
  });

  if (requiredSet.size > 0) {
    merged.required = Array.from(requiredSet);
  }

  // Keep other properties from the original schema
  const { allOf, required: restRequired, properties: restProperties, ...rest } = schema;
  
  // ✅ Merge properties from original schema (these are additional properties)
  if (restProperties) {
    merged.properties = { ...merged.properties, ...restProperties };
  }
  
  // ✅ Merge required from original schema
  if (restRequired) {
    restRequired.forEach((field: string) => requiredSet.add(field));
    merged.required = Array.from(requiredSet);
  }
  
  return { ...merged, ...rest };
}
```

### Key Changes:
1. **Explicit extraction**: Extract `properties` and `required` from the original schema separately from other fields
2. **Proper merging**: Merge the additional properties into the already-merged inherited properties
3. **Required array handling**: Add additional required fields to the Set and regenerate the array

This ensures that the resolved schema contains:
- All properties from inherited classes (via `allOf`)
- All additional properties defined at the class level
- All required fields from both sources

## Testing
To test this fix:

1. Create a base class (e.g., "Animal") with properties like `name`, `age`
2. Create a derived class (e.g., "Dog") with its own properties like `breed`, `barkVolume`
3. Edit the "Dog" class and set `allOf` to extend from "Animal"
4. Open the Class Edit Dialog for "Dog"
5. Switch to the "EXAMPLE" view
6. Verify that the generated example includes:
   - Properties from Animal: `name`, `age`
   - Properties from Dog: `breed`, `barkVolume`

## Impact
This fix ensures that `json-schema-faker` receives a fully resolved schema with all inherited and additional properties, allowing it to generate complete example data that accurately represents the full class structure including inheritance.

The same `resolveRefs` function is also used in the `handleCopy` and `handleExport` functions, so they will also benefit from this fix when exporting example data.

