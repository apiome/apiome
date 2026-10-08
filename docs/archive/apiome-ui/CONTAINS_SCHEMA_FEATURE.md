# Feature: Contains Schema for Array Validation

## Overview
Added support for the `contains` keyword (OpenAPI 3.1.0 / JSON Schema draft 2020-12) that allows specifying that at least one array item must match a particular schema. This is useful for validation without constraining all items.

## Implementation

### Files Modified
1. `/src/app/components/ade/studio/PropertyFormFields.tsx`
2. `/src/app/components/ade/studio/PropertyDialog.tsx`
3. `/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`

### Interface Changes

**PropertyFormData** - Added contains field:
```typescript
// Array constraints
minItems?: string;
maxItems?: string;
uniqueItems?: boolean;
contains?: string; // OpenAPI 3.1: JSON Schema that at least one array item must match
```

### UI Implementation

Added a multiline text field in the Array Constraints section:
- Label: "Contains (JSON Schema)"
- Input: Multiline (3 rows) for JSON schema
- Placeholder: `{"type": "string", "minLength": 5}`
- Helper text: "OpenAPI 3.1: JSON Schema that at least one item must match"
- Additional caption: "Example: Require at least one item to be a string with minimum length 5"

### Behavior

**Saving:**
- Parses the input as JSON when saving
- If not valid JSON, wraps as a simple type: `{ type: inputValue }`
- Deletes the field if empty

**Loading:**
- Converts existing contains schema to formatted JSON string (with indentation)
- Displays in the multiline text field when editing

**JSON Preview:**
- Includes contains in the buildPropertyJsonSchema function
- Shows in JSON/YAML preview mode

## Use Cases

### Use Case 1: Mixed Type Arrays with Required String
```json
{
  "type": "array",
  "items": {},
  "contains": {
    "type": "string",
    "minLength": 5
  }
}
```
Array can contain any types, but at least one item must be a string with minimum length 5.

### Use Case 2: Require Specific Value
```json
{
  "type": "array",
  "items": {
    "type": "string"
  },
  "contains": {
    "const": "active"
  }
}
```
Array of strings, but must contain "active".

### Use Case 3: Require Tagged Item
```json
{
  "type": "array",
  "items": {
    "type": "object"
  },
  "contains": {
    "type": "object",
    "required": ["id"],
    "properties": {
      "id": { "type": "string" }
    }
  }
}
```
Array of objects, but at least one must have an "id" property.

### Use Case 4: Numeric Constraint
```json
{
  "type": "array",
  "items": {
    "type": "number"
  },
  "contains": {
    "type": "number",
    "minimum": 100
  }
}
```
Array of numbers, but at least one must be >= 100.

## OpenAPI 3.1 Compliance

### JSON Schema Draft 2020-12
The `contains` keyword is part of JSON Schema draft 2020-12, which is fully supported in OpenAPI 3.1.0 and higher.

### Validation Rules
- At least ONE array item must validate against the contains schema
- Other items can be anything (unless further constrained by `items`)
- Can be combined with `minContains` and `maxContains` (future enhancement)

## Testing

### Test 1: Basic String Constraint
1. Create array property: type = array of any
2. Add contains schema: `{"type": "string", "minLength": 5}`
3. Save
4. Verify JSON shows:
```json
{
  "type": "array",
  "contains": {
    "type": "string",
    "minLength": 5
  }
}
```

### Test 2: Edit Existing
1. Open property with contains schema
2. Verify contains field shows formatted JSON
3. Modify schema
4. Save
5. Verify changes persist

### Test 3: Clear Contains
1. Open property with contains schema
2. Clear the contains field
3. Save
4. Verify contains is removed from schema

### Test 4: Simple Type Entry
1. Enter just "string" (not valid JSON)
2. Save
3. Verify it's converted to: `{"type": "string"}`

## Example Schemas

### Mixed Array with Required Email
```json
{
  "type": "array",
  "contains": {
    "type": "string",
    "format": "email"
  }
}
```

### Array Must Include Specific Enum Value
```json
{
  "type": "array",
  "items": {
    "type": "string",
    "enum": ["draft", "active", "inactive"]
  },
  "contains": {
    "const": "active"
  }
}
```

### Array of Objects with Required Primary
```json
{
  "type": "array",
  "items": {
    "type": "object"
  },
  "contains": {
    "type": "object",
    "properties": {
      "primary": { "const": true }
    },
    "required": ["primary"]
  }
}
```

## Benefits

1. **Flexible Validation** - Validate that specific items exist without constraining all items
2. **OpenAPI 3.1 Compliance** - Uses latest JSON Schema features
3. **Complex Requirements** - Handle business logic like "must have at least one primary contact"
4. **Type Safety** - Ensure mixed-type arrays have required elements

## Limitations

- `minContains` and `maxContains` not yet implemented (future enhancement)
- User must write valid JSON schema manually
- No visual schema builder (could be added in future)

## Future Enhancements

Could potentially add:
- `minContains`: Minimum number of items that must match
- `maxContains`: Maximum number of items that must match
- Visual schema builder for contains
- Validation/preview of contains schema
- Common templates (e.g., "must contain email", "must contain ID")

## Standards Compliance

✅ **OpenAPI 3.1.0+** - Full support for contains keyword  
✅ **JSON Schema draft 2020-12** - Correct implementation  
✅ **Backward Compatible** - Optional field, doesn't affect existing schemas  

## Build Status

✅ No compilation errors
✅ Only pre-existing warnings
✅ All dialogs support contains (PropertyDialog, ClassPropertyEditDialog)
✅ Ready to deploy

## Date Added
December 10, 2025

