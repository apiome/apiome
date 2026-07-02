# JSON Generation Fix - Exclusive/Inclusive Min/Max

## Summary

Fixed issues with JSON Schema generation for exclusive/inclusive minimum and maximum values in the property form.

## Issues Fixed

### 1. ✅ Array Types Not Loading Constraints Correctly
**Problem:** When editing properties with array types, the minimum/maximum constraints were being read from the root property object instead of from `items`, causing the form to not reflect the saved values.

**Solution:** Modified `PropertyDialog.tsx` loading logic to check `items` object for array types:
```typescript
// For array types, check inside items; for non-array, check at root level
const minMaxSource = isArray && (property as any).items ? (property as any).items : property;

if (minMaxSource.exclusiveMinimum !== undefined) {
  minimumValue = minMaxSource.exclusiveMinimum.toString();
  minimumType = 'exclusive';
} else if (minMaxSource.minimum !== undefined) {
  minimumValue = minMaxSource.minimum.toString();
  minimumType = 'inclusive';
}
```

### 2. ✅ Type Not Cleared When Value Removed
**Problem:** When user cleared the minimum/maximum value, the `minimumType`/`maximumType` remained set, potentially causing issues.

**Solution:** Modified `PropertyFormFields.tsx` to clear the type when value is empty:
```typescript
// PropertyFormFields.tsx - Minimum field onChange
onChange={(e) => {
  onChange('minimum', e.target.value);
  if (e.target.value && !data.minimumType) {
    onChange('minimumType', 'inclusive');
  } else if (!e.target.value) {
    onChange('minimumType', undefined);  // ← NEW: Clear type
  }
}}

// Same fix applied to Maximum field
```

### 3. ✅ NaN Values Added to Schema
**Problem:** If `parseFloat()` returned `NaN` from invalid input, it would still be added to the JSON Schema output.

**Solution:** Added validation in `PropertyDialog.tsx` to check for `NaN` before adding to schema:

**Updated in 3 places:**
- `buildPropertyJsonSchema()` - for JSON view
- `handleSubmit()` - for array items schema
- `handleSubmit()` - for non-array schema

```typescript
// BEFORE
if (formData.minimum) {
  if (formData.minimumType === 'exclusive') {
    schema.exclusiveMinimum = parseFloat(formData.minimum);
  } else {
    schema.minimum = parseFloat(formData.minimum);
  }
}

// AFTER
if (formData.minimum && formData.minimum.trim()) {
  const minValue = parseFloat(formData.minimum);
  if (!isNaN(minValue)) {  // ← NEW: Validate number
    if (formData.minimumType === 'exclusive') {
      schema.exclusiveMinimum = minValue;
    } else {
      schema.minimum = minValue;
    }
  }
}
```

## Files Modified

### PropertyFormFields.tsx
**Changes:**
- Line ~605: Added type clearing logic for minimum field
- Line ~645: Added type clearing logic for maximum field

**Impact:** Prevents orphaned `minimumType`/`maximumType` values when the actual value is cleared.

### PropertyDialog.tsx
**Changes:**
- Lines ~105-130: Fixed loading logic to read constraints from `items` for array types
- Lines ~131-146: Updated formData initialization to use `minMaxSource` for array types
- Lines ~180-195: Added NaN validation in `buildPropertyJsonSchema()` for array items
- Lines ~205-220: Added NaN validation in `buildPropertyJsonSchema()` for non-array schema
- Lines ~275-290: Added NaN validation in `handleSubmit()` for array items
- Lines ~305-320: Added NaN validation in `handleSubmit()` for non-array schema

**Impact:** 
- Array type properties now correctly load and save their constraints
- Prevents invalid `NaN` values in generated JSON Schema output

## Testing

Run through the test cases in `/docs/EXCLUSIVE_MINMAX_DEBUG_GUIDE.md` to verify:

1. ✅ Exclusive minimum generates `exclusiveMinimum` field
2. ✅ Inclusive minimum generates `minimum` field
3. ✅ Only ONE field appears (not both)
4. ✅ Switching radio buttons changes the output field
5. ✅ Clearing value removes field from JSON
6. ✅ Zero values work correctly
7. ✅ Negative values work correctly
8. ✅ Decimal values work correctly
9. ✅ Array types work correctly
10. ✅ Editing array type properties preserves exclusive/inclusive settings
9. ✅ Array types work correctly

## Expected Behavior

### Example 1: User enters minimum = "10", selects "Exclusive (>)"
```json
{
  "type": "number",
  "exclusiveMinimum": 10
}
```

### Example 2: User enters minimum = "10", selects "Inclusive (≥)"
```json
{
  "type": "number",
  "minimum": 10
}
```

### Example 3: User enters and then clears minimum value
```json
{
  "type": "number"
}
```
(No minimum or exclusiveMinimum field present)

### Example 4: Mixed constraints (0 < value ≤ 100)
```json
{
  "type": "number",
  "exclusiveMinimum": 0,
  "maximum": 100
}
```

## Validation Flow

```
User Input → onChange Handler → Form State Update
                    ↓
            Auto-set type if needed
            Clear type if value empty
                    ↓
Form State → buildPropertyJsonSchema()
                    ↓
            Check value exists and is not empty
            Parse to number
            Validate not NaN
                    ↓
            Output correct field based on type
                    ↓
JSON Output (either minimum OR exclusiveMinimum)
```

## Standards Compliance

✅ **OpenAPI 3.1.x** - Uses numeric values for exclusiveMinimum/exclusiveMaximum
✅ **JSON Schema draft 2020-12** - Follows latest specification
✅ **Backward Compatible** - Properly loads existing properties

## Additional Improvements

1. **Trim whitespace** - Added `.trim()` check to ignore spaces
2. **Explicit NaN check** - Prevents invalid numeric values
3. **Type lifecycle management** - Type is cleared when value is removed
4. **Consistent behavior** - Same logic applied to all schema building functions

## Known Limitations

- Radio buttons disabled when no value is present (intentional UX decision)
- Default type is "inclusive" when value is first entered
- Only works for numeric types (number, integer) - as intended

## Related Documentation

- `/docs/EXCLUSIVE_MINMAX_OPENAPI_3.1.md` - Implementation overview
- `/docs/EXCLUSIVE_MINMAX_EXAMPLES.md` - Usage examples
- `/docs/EXCLUSIVE_MINMAX_DEBUG_GUIDE.md` - Testing guide

