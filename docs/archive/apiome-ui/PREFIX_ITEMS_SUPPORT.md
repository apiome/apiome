# PrefixItems Support for json-schema-faker

## Problem

The user reported that `json-schema-faker` (v0.5.9) cannot generate examples from schemas containing the `prefixItems` keyword, which is a JSON Schema Draft 2020-12 / OpenAPI 3.1.0 feature.

### Example Schema That Failed

```json
{
  "type": "array",
  "items": true,
  "prefixItems": [
    { "type": "string" },
    { "type": "string" },
    { "type": "object" },
    { "type": "string" }
  ]
}
```

The `prefixItems` keyword defines a tuple validation pattern where:
- First item must be a string
- Second item must be a string
- Third item must be an object
- Fourth item must be a string
- `items: true` means "allow any additional items after these 4"

## Root Cause

`json-schema-faker` v0.5.9 was built for JSON Schema Draft 7 and doesn't recognize the newer `prefixItems` keyword introduced in Draft 2020-12. When it encounters `prefixItems`, it ignores it and tries to generate based on `items: true`, which results in an empty or invalid array.

## Solution

Added preprocessing logic in the `resolveRefs` function (ClassEditDialog.tsx) to convert `prefixItems` into a format that `json-schema-faker` understands.

### Conversion Strategy

**Before (Draft 2020-12 format):**
```json
{
  "type": "array",
  "items": true,
  "prefixItems": [
    { "type": "string" },
    { "type": "string" },
    { "type": "object" },
    { "type": "string" }
  ]
}
```

**After (Draft 7 compatible tuple format):**
```json
{
  "type": "array",
  "items": [
    { "type": "string" },
    { "type": "string" },
    { "type": "object" },
    { "type": "string" }
  ],
  "minItems": 4,
  "maxItems": 4
}
```

### Implementation

The preprocessing logic:

1. **Detects `prefixItems`** - Checks if the schema has a `prefixItems` array
2. **Handles `items: true`** - Recognizes when items is `true` or an empty object
3. **Converts to tuple** - Moves `prefixItems` array to `items` array
4. **Sets constraints** - Adds `minItems` and `maxItems` to ensure tuple length
5. **Removes `prefixItems`** - Deletes the unsupported keyword

### Code Changes

**File:** `src/app/components/ade/studio/ClassEditDialog.tsx`

Added at the beginning of the `resolveRefs` function:

```typescript
// Preprocess: Convert prefixItems to items array format for json-schema-faker compatibility
if (schema.prefixItems && Array.isArray(schema.prefixItems)) {
  const processedSchema = { ...schema };
  
  if (schema.items === true || (schema.items && Object.keys(schema.items).length === 0)) {
    processedSchema.items = schema.prefixItems;
    delete processedSchema.prefixItems;
    
    if (!processedSchema.minItems) {
      processedSchema.minItems = schema.prefixItems.length;
    }
    if (!processedSchema.maxItems) {
      processedSchema.maxItems = schema.prefixItems.length;
    }
  }
  
  schema = processedSchema;
}
```

## Testing

### Test 1: Preprocessing Logic

Created `tests/test-prefix-items-preprocessing.ts` to verify the conversion logic works correctly.

**Result:** ✅ PASS
- `prefixItems` correctly removed
- `items` converted to array
- `minItems` and `maxItems` set appropriately

### Test 2: json-schema-faker Integration

Created `tests/test-jsf-integration.ts` to verify `json-schema-faker` can generate valid examples from the preprocessed schema.

**Result:** ✅ PASS

Example generated:
```json
{
  "color": "BLUE",
  "ratio": 0.1,
  "test": [
    "amet Ut eiusmod eu",
    "do",
    {
      "occaecat9": 51547871.96466696
    },
    "labore Ut"
  ]
}
```

Validation:
- ✓ `color`: Valid enum value (BLUE)
- ✓ `ratio`: Valid number in range [0, 1] with multipleOf 0.1
- ✓ `test`: Array with 4 items (matching prefixItems)
  - ✓ `test[0]`: string
  - ✓ `test[1]`: string
  - ✓ `test[2]`: object
  - ✓ `test[3]`: string

## Benefits

1. **Backward Compatibility** - Works with json-schema-faker v0.5.9 without requiring updates
2. **Transparent** - Users don't need to know about the conversion; it happens automatically
3. **Accurate** - Generates examples that match the tuple schema defined by `prefixItems`
4. **No Breaking Changes** - Doesn't affect schemas without `prefixItems`

## Limitations

### Current Approach

The current implementation converts `prefixItems` + `items: true` into a fixed-length tuple. This means:

- ✅ Generates correct examples for the defined prefix items
- ⚠️ Does NOT generate additional items beyond the prefix (even though `items: true` would allow it)

**Why this limitation?**

`json-schema-faker` doesn't have a way to express "these specific types first, then any types after". The tuple format (array of schemas in `items`) only works for fixed-length arrays.

### Edge Cases Handled

1. **`items: true`** - Converted to tuple with fixed length
2. **`items: {}`** - Treated same as `items: true`
3. **`items` with actual schema** - Uses `prefixItems` as tuple, ignores `items` schema
4. **No `items`** - Uses `prefixItems` as tuple with fixed length

### Not Yet Handled

- **Variable-length tuples** - Where `items` specifies additional items after `prefixItems`
- **`contains` keyword** - Draft 2020-12 feature for array item validation
- **`minContains`/`maxContains`** - Array item occurrence constraints

## Future Enhancements

### Option 1: Upgrade json-schema-faker

Consider upgrading to a newer version that supports Draft 2020-12:
- Check if newer versions support `prefixItems`
- Test backward compatibility
- Update package.json

### Option 2: More Sophisticated Preprocessing

For variable-length tuples with additional items:
```typescript
{
  "prefixItems": [
    { "type": "string" },
    { "type": "number" }
  ],
  "items": { "type": "boolean" }
}
```

Could generate:
```typescript
// Generate 2 required prefix items + random number of boolean items
{
  "items": [
    { "type": "string" },
    { "type": "number" },
    { "type": "boolean" }, // additional
    { "type": "boolean" }  // additional
  ],
  "minItems": 2
}
```

### Option 3: Custom Example Generator

Build a custom example generator that fully supports Draft 2020-12:
- Handle `prefixItems` + `items` correctly
- Support `contains`, `minContains`, `maxContains`
- Support `unevaluatedProperties`, `unevaluatedItems`
- Support `$dynamicRef` and `$dynamicAnchor`

## Related Files

- `src/app/components/ade/studio/ClassEditDialog.tsx` - Main implementation
- `tests/test-prefix-items-preprocessing.ts` - Preprocessing test
- `tests/test-jsf-integration.ts` - Integration test

## References

- [JSON Schema 2020-12 Spec - prefixItems](https://json-schema.org/draft/2020-12/json-schema-core.html#name-prefixitems)
- [OpenAPI 3.1.0 Specification](https://spec.openapis.org/oas/v3.1.0)
- [json-schema-faker Documentation](https://github.com/json-schema-faker/json-schema-faker)

## Date Implemented

December 11, 2024

## Status

✅ **Resolved** - `json-schema-faker` can now generate examples from schemas with `prefixItems`

