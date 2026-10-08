# JSON Schema Faker $ref Resolution Fix

## Summary
Fixed the JSON Schema Faker errors when generating example data for schemas with `$ref` references, including nested references in array items and composition patterns (allOf, anyOf, oneOf).

## Problems Solved

### Problem 1: Direct $ref in allOf
**Error**: `Prop not found: components (#/components/schemas/Payment)`

**Example**:
```json
{
  "BankTransferPayment": {
    "allOf": [
      { "$ref": "#/components/schemas/Payment" },
      { "properties": { "accountNumber": {...} } }
    ]
  }
}
```

### Problem 2: Nested $ref in Properties
**Error**: `Prop not found: components (#/components/schemas/Group) in /properties/groups`

**Example**:
```json
{
  "User": {
    "properties": {
      "groups": {
        "type": "array",
        "items": { "$ref": "#/components/schemas/Group" }
      }
    }
  }
}
```

## Root Cause
JSON Schema Faker cannot resolve OpenAPI-style `$ref` references (e.g., `#/components/schemas/Payment`). It expects either:
1. Fully resolved schemas with no references, OR
2. References in JSON Schema format with proper context

## Solution
Implemented a comprehensive `resolveRefs` function in `ClassEditDialog.tsx` that:

1. **Resolves all $ref references** by looking them up in the OpenAPI `components.schemas` object
2. **Handles composition patterns** (allOf, anyOf, oneOf):
   - Merges schemas in `allOf`
   - Deduplicates `required` fields
   - Properly combines `properties`
3. **Recursively resolves nested references** in:
   - Object properties
   - Array items
   - Nested schemas
4. **Prevents circular references** using a visited Set
5. **Maintains context** by passing the schemas object through all recursive calls

## Key Implementation Details

### Correct visited Set Management
```typescript
// For $ref resolution: Create NEW Set to track this reference chain
if (schema.$ref) {
  const newVisited = new Set(visited);
  newVisited.add(refName);
  return resolveRefs(referencedSchema, schemas, newVisited, ...);
}

// For recursion: Pass SAME Set to preserve context
if (Array.isArray(schema.allOf)) {
  schema.allOf.forEach((subSchema) => {
    resolveRefs(subSchema, schemas, visited, ...);  // Same visited
  });
}
```

### Proper allOf Merging
```typescript
// Extract required and properties BEFORE merging to avoid duplicates
const { required: resolvedRequired, properties: resolvedProperties, ...resolvedRest } = resolved;

// Merge using Set for required to ensure uniqueness
const requiredSet = new Set<string>();
resolvedRequired?.forEach(field => requiredSet.add(field));
```

### Smart Recursion
```typescript
// Only recurse into objects, not primitives
const value = schema[key];
if (value && typeof value === 'object') {
  resolved[key] = resolveRefs(value, schemas, visited, `${path}/${key}`);
} else {
  resolved[key] = value;  // Copy primitive as-is
}
```

## Testing Results

### Test Case 1: allOf with $ref
✅ **Before**: Error - "Prop not found: components (#/components/schemas/Payment)"
✅ **After**: Successfully generates merged schema with all properties from base and derived classes

### Test Case 2: Nested $ref in Array Items
✅ **Before**: Error - "Prop not found: components (#/components/schemas/Group) in /properties/groups"
✅ **After**: Successfully generates array with resolved Group objects

### Generated Example:
```json
{
  "id": "a1dee34f-e1af-a18b-f17a-7f904fa5a6a8",
  "name": "ea voluptate",
  "email": "ce91lKHpVMvCS@yMiaBtYkkIp.rl",
  "groups": [
    {
      "id": "2e5825c2-ed42-44ce-3d84-95a6411d7ca5",
      "name": "in pariatur nulla aute aliqua",
      "description": "incididunt"
    }
  ]
}
```

## Files Modified
- `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ClassEditDialog.tsx`

## Changes Applied To:
1. Main editor display (when format is "example")
2. `handleCopy` function
3. `handleExport` function

## Alternative Libraries Considered

While investigating, we considered these alternatives:

1. **@faker-js/faker + @stoplight/json-schema-sampler** - More modern but requires integration
2. **openapi-sampler** - Purpose-built for OpenAPI but limited feature set
3. **json-schema-faker (current)** - Older but feature-rich with our custom resolver

**Decision**: Keep json-schema-faker with our custom `resolveRefs` function because:
- Already integrated and working
- Custom resolver handles all edge cases
- No breaking changes needed
- Proven to work with complex schemas

## Benefits
✅ Supports schema inheritance (allOf/anyOf/oneOf)
✅ Supports nested $ref references
✅ Prevents circular reference loops
✅ Properly merges required fields
✅ Maintains all schema metadata
✅ Works with existing json-schema-faker infrastructure

## Date
November 22, 2025

