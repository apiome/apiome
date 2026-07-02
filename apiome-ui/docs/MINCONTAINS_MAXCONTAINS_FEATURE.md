# Feature: minContains and maxContains for Array Validation

## Overview
Added support for `minContains` and `maxContains` keywords (OpenAPI 3.1.0 / JSON Schema draft 2020-12) that allow specifying the minimum and maximum number of array items that must match a `contains` schema. These fields are only enabled when a `contains` schema is defined.

## Implementation

### Files Modified
1. `/src/app/components/ade/studio/PropertyFormFields.tsx`
2. `/src/app/components/ade/studio/PropertyDialog.tsx`
3. `/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`
4. `/public/WHATS_NEW.md`

### Interface Changes

**PropertyFormData** - Added minContains and maxContains fields:
```typescript
// Array constraints
minItems?: string;
maxItems?: string;
uniqueItems?: boolean;
contains?: string; // OpenAPI 3.1: JSON Schema that at least one array item must match
minContains?: string; // OpenAPI 3.1: Minimum number of items that must match contains schema
maxContains?: string; // OpenAPI 3.1: Maximum number of items that must match contains schema
```

### UI Implementation

**Conditional Display:**
- Min Contains and Max Contains fields only appear when a `contains` schema is set
- Displayed in a two-column grid layout below the contains field
- Both are number input fields with minimum value of 1

**Auto-clear Behavior:**
- When the `contains` field is cleared, `minContains` and `maxContains` are automatically cleared
- Ensures data consistency (minContains/maxContains without contains is invalid)

**UI Components:**
```typescript
{data.contains && data.contains.trim() && (
  <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 2, mt: 2 }}>
    <TextField label="Min Contains" type="number" ... />
    <TextField label="Max Contains" type="number" ... />
  </Box>
)}
```

### Validation Rules

**Saving:**
- Only saved when `contains` is defined
- Parses as integer with minimum value of 1
- Validates that values are numbers and >= 1
- Deletes fields when empty or invalid

**Loading:**
- Loads existing values from property data
- Converts numbers to strings for form display
- Falls back to empty string if not set

**Cleanup:**
- When `contains` is deleted, `minContains` and `maxContains` are also deleted
- Ensures schema validity

## Use Cases

### Use Case 1: Require At Least 2 Emails
```json
{
  "type": "array",
  "items": { "type": "string" },
  "contains": {
    "type": "string",
    "format": "email"
  },
  "minContains": 2
}
```
Array must contain at least 2 email addresses.

### Use Case 2: Allow Up To 3 High Values
```json
{
  "type": "array",
  "items": { "type": "number" },
  "contains": {
    "type": "number",
    "minimum": 100
  },
  "maxContains": 3
}
```
Array can have at most 3 numbers >= 100.

### Use Case 3: Require 1-5 Primary Items
```json
{
  "type": "array",
  "items": { "type": "object" },
  "contains": {
    "type": "object",
    "properties": {
      "primary": { "const": true }
    },
    "required": ["primary"]
  },
  "minContains": 1,
  "maxContains": 5
}
```
Array must have between 1 and 5 objects with `primary: true`.

### Use Case 4: Require Exactly 2 Matches
```json
{
  "type": "array",
  "items": { "type": "string" },
  "contains": {
    "type": "string",
    "pattern": "^admin-"
  },
  "minContains": 2,
  "maxContains": 2
}
```
Array must contain exactly 2 strings starting with "admin-".

### Use Case 5: Require At Least 3 Unique IDs
```json
{
  "type": "array",
  "items": { "type": "object" },
  "contains": {
    "type": "object",
    "required": ["id"],
    "properties": {
      "id": { "type": "string" }
    }
  },
  "minContains": 3
}
```
Array must have at least 3 objects with an "id" property.

## OpenAPI 3.1 Compliance

### JSON Schema Draft 2020-12
Both `minContains` and `maxContains` are part of JSON Schema draft 2020-12, which is fully supported in OpenAPI 3.1.0 and higher.

### Validation Rules
- `minContains`: Minimum number of items that must match the contains schema (default: 1)
- `maxContains`: Maximum number of items that can match the contains schema (no default limit)
- Both require `contains` to be defined
- Both must be >= 1
- `minContains` <= `maxContains` (if both are set)

### Relationship with contains
| Keyword | Required? | Meaning |
|---------|-----------|---------|
| `contains` | Yes | Schema that items must match |
| `minContains` | No | Minimum matching items (default: 1) |
| `maxContains` | No | Maximum matching items (default: unlimited) |

## Testing

### Test 1: Basic Min Contains
1. Create array property
2. Add contains schema: `{"type": "string", "minLength": 5}`
3. Set Min Contains: `2`
4. Save
5. Verify JSON shows:
```json
{
  "type": "array",
  "contains": {
    "type": "string",
    "minLength": 5
  },
  "minContains": 2
}
```

### Test 2: Min and Max Together
1. Create array property
2. Add contains schema: `{"type": "number", "minimum": 100}`
3. Set Min Contains: `1`
4. Set Max Contains: `3`
5. Save
6. Verify both fields in JSON

### Test 3: Auto-clear on Contains Clear
1. Create array with contains, minContains, and maxContains
2. Save
3. Reopen property
4. Clear the contains field
5. Verify minContains and maxContains fields disappear
6. Save
7. Verify minContains and maxContains removed from JSON

### Test 4: Edit Existing Values
1. Open property with contains and minContains
2. Verify Min Contains field shows existing value
3. Change value to 5
4. Save
5. Verify change persists

### Test 5: Invalid Values
1. Try entering 0 in minContains → Field should reject or not save
2. Try entering negative number → Should be rejected
3. Try entering non-number → Should not save

## Example Schemas

### E-commerce: Require Multiple Payment Methods
```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "type": { "enum": ["credit_card", "paypal", "bank"] }
    }
  },
  "contains": {
    "type": "object",
    "properties": {
      "type": { "const": "credit_card" }
    }
  },
  "minContains": 1,
  "maxContains": 3
}
```

### Survey: Limit Required Answers
```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "question": { "type": "string" },
      "answer": { "type": "string" }
    }
  },
  "contains": {
    "type": "object",
    "required": ["answer"],
    "properties": {
      "answer": { "type": "string", "minLength": 1 }
    }
  },
  "minContains": 3
}
```

### Team Roles: Require Admin Count Range
```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "role": { "enum": ["admin", "user", "guest"] }
    }
  },
  "contains": {
    "type": "object",
    "properties": {
      "role": { "const": "admin" }
    }
  },
  "minContains": 1,
  "maxContains": 5
}
```

## Benefits

1. **Precise Validation** - Control exactly how many items must match a schema
2. **Business Logic** - Enforce rules like "must have 2-3 admins"
3. **OpenAPI 3.1 Compliance** - Uses latest JSON Schema features
4. **User-Friendly** - Fields only appear when relevant (contains is set)
5. **Data Consistency** - Auto-clears when contains is removed

## UI/UX Design Choices

### Conditional Visibility
- Fields only shown when `contains` has a value
- Prevents user confusion and invalid configurations
- Clear visual feedback of dependency

### Grid Layout
- Two-column grid for min/max side-by-side
- Consistent with other min/max fields (minItems/maxItems, minLength/maxLength)
- Space-efficient and intuitive

### Helper Text
- "Minimum matching items" for minContains
- "Maximum matching items" for maxContains
- Clear and concise labels

### Validation
- Minimum input value: 1 (enforced by inputProps)
- Number type for proper numeric keyboard on mobile
- NaN validation on save

## Limitations

- User must manually ensure `minContains` <= `maxContains`
- No built-in validation for this constraint (could be added)
- No visual indication of the relationship between contains/minContains/maxContains
- Future enhancement: Could add warning if minContains > maxContains

## Future Enhancements

Could potentially add:
- Validation warning if minContains > maxContains
- Visual indicator showing the relationship between fields
- Templates for common scenarios (e.g., "2-3 admin users")
- Preview/test mode to validate sample arrays

## Standards Compliance

✅ **OpenAPI 3.1.0+** - Full support for minContains/maxContains  
✅ **JSON Schema draft 2020-12** - Correct implementation  
✅ **Dependent Fields** - Only valid when contains is set  
✅ **Validation** - Proper integer constraints (>= 1)  

## Build Status

✅ No compilation errors
✅ Only pre-existing warnings
✅ All dialogs support minContains/maxContains
✅ JSON preview includes fields
✅ Auto-clear behavior working
✅ Ready to deploy

## Date Added
December 10, 2025

## Related Features
- **contains** - Base schema that items must match
- **minItems/maxItems** - Overall array size constraints
- **uniqueItems** - Array item uniqueness constraint

## Documentation References
- JSON Schema draft 2020-12: https://json-schema.org/draft/2020-12/json-schema-validation.html#name-contains
- OpenAPI 3.1.0: https://spec.openapis.org/oas/v3.1.0

