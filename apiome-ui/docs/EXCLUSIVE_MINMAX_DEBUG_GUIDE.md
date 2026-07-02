# Exclusive Min/Max JSON Generation - Debug Guide

## Issue Description
The JSON Schema was not being generated correctly for exclusive/inclusive minimum/maximum values.

## Root Causes Identified & Fixed

### 1. Value Clearing Issue
**Problem:** When the user cleared the minimum/maximum value, the `minimumType` or `maximumType` was not being cleared, potentially causing invalid schema generation.

**Fix:** Updated the onChange handlers to clear the type when the value is cleared:
```typescript
onChange={(e) => {
  onChange('minimum', e.target.value);
  if (e.target.value && !data.minimumType) {
    onChange('minimumType', 'inclusive');
  } else if (!e.target.value) {
    onChange('minimumType', undefined);  // Clear type when value is cleared
  }
}}
```

### 2. NaN Validation Issue
**Problem:** If parseFloat() returned NaN (from invalid input), it would still be added to the schema.

**Fix:** Added validation to check for NaN before adding to schema:
```typescript
if (formData.minimum && formData.minimum.trim()) {
  const minValue = parseFloat(formData.minimum);
  if (!isNaN(minValue)) {  // Only add if valid number
    if (formData.minimumType === 'exclusive') {
      schema.exclusiveMinimum = minValue;
    } else {
      schema.minimum = minValue;
    }
  }
}
```

## Testing Checklist

### Test 1: Basic Exclusive Minimum
**Steps:**
1. Open property dialog
2. Select type: `number`
3. Enter minimum: `0`
4. Select: "Exclusive (>)"
5. Switch to JSON view

**Expected Result:**
```json
{
  "type": "number",
  "exclusiveMinimum": 0
}
```

**NOT:**
```json
{
  "type": "number",
  "minimum": 0,
  "exclusiveMinimum": 0
}
```

---

### Test 2: Basic Inclusive Minimum
**Steps:**
1. Open property dialog
2. Select type: `number`
3. Enter minimum: `0`
4. Leave default: "Inclusive (≥)" selected
5. Switch to JSON view

**Expected Result:**
```json
{
  "type": "number",
  "minimum": 0
}
```

---

### Test 3: Switching Between Types
**Steps:**
1. Open property dialog
2. Select type: `number`
3. Enter minimum: `10`
4. Select: "Inclusive (≥)"
5. Verify JSON shows: `"minimum": 10`
6. Switch to: "Exclusive (>)"
7. Verify JSON shows: `"exclusiveMinimum": 10` (NOT `"minimum": 10`)

**Expected Behavior:**
- Only ONE field should appear in JSON
- Changing radio button should change which field appears
- The value should remain the same

---

### Test 4: Clearing Values
**Steps:**
1. Open property dialog
2. Select type: `number`
3. Enter minimum: `5`, select "Exclusive (>)"
4. Verify JSON shows: `"exclusiveMinimum": 5`
5. Clear the minimum field (delete the value)
6. Verify JSON no longer shows minimum or exclusiveMinimum

**Expected Result:**
```json
{
  "type": "number"
}
```

---

### Test 5: Both Minimum and Maximum (Exclusive)
**Steps:**
1. Open property dialog
2. Select type: `number`
3. Enter minimum: `0`, select "Exclusive (>)"
4. Enter maximum: `1`, select "Exclusive (<)"
5. Switch to JSON view

**Expected Result:**
```json
{
  "type": "number",
  "exclusiveMinimum": 0,
  "exclusiveMaximum": 1
}
```

---

### Test 6: Mixed Inclusive/Exclusive
**Steps:**
1. Open property dialog
2. Select type: `integer`
3. Enter minimum: `1`, select "Inclusive (≥)"
4. Enter maximum: `100`, select "Exclusive (<)"
5. Switch to JSON view

**Expected Result:**
```json
{
  "type": "integer",
  "minimum": 1,
  "exclusiveMaximum": 100
}
```

---

### Test 7: Array of Numbers
**Steps:**
1. Open property dialog
2. Check: "An array of..."
3. Select type: `number`
4. Enter minimum: `0`, select "Exclusive (>)"
5. Switch to JSON view

**Expected Result:**
```json
{
  "type": "array",
  "items": {
    "type": "number",
    "exclusiveMinimum": 0
  }
}
```

---

### Test 8: Negative Values
**Steps:**
1. Open property dialog
2. Select type: `number`
3. Enter minimum: `-273.15`, select "Exclusive (>)"
4. Switch to JSON view

**Expected Result:**
```json
{
  "type": "number",
  "exclusiveMinimum": -273.15
}
```

---

### Test 9: Zero Value
**Steps:**
1. Open property dialog
2. Select type: `integer`
3. Enter minimum: `0`, select "Inclusive (≥)"
4. Switch to JSON view

**Expected Result:**
```json
{
  "type": "integer",
  "minimum": 0
}
```

**Note:** Zero should NOT be treated as "empty" or falsy

---

### Test 10: Decimal Values
**Steps:**
1. Open property dialog
2. Select type: `number`
3. Enter minimum: `0.001`, select "Exclusive (>)"
4. Enter maximum: `0.999`, select "Exclusive (<)"
5. Switch to JSON view

**Expected Result:**
```json
{
  "type": "number",
  "exclusiveMinimum": 0.001,
  "exclusiveMaximum": 0.999
}
```

---

### Test 11: Edit Existing Property (Inclusive → Exclusive)
**Steps:**
1. Create a property with `"minimum": 5`
2. Save and close
3. Edit the property
4. Verify "Inclusive (≥)" is selected
5. Change to "Exclusive (>)"
6. Save
7. Reopen property
8. Verify JSON shows `"exclusiveMinimum": 5`

---

### Test 12: Edit Existing Property (Exclusive → Inclusive)
**Steps:**
1. Create a property with `"exclusiveMinimum": 0`
2. Save and close
3. Edit the property
4. Verify "Exclusive (>)" is selected
5. Change to "Inclusive (≥)"
6. Save
7. Reopen property
8. Verify JSON shows `"minimum": 0`

---

## Common Issues & Solutions

### Issue: Both minimum and exclusiveMinimum appear in JSON
**Cause:** Logic error in conditional statement
**Solution:** Ensure if-else structure (not two separate if statements)

### Issue: Value becomes NaN in JSON
**Cause:** Invalid numeric input not validated
**Solution:** Added `!isNaN(minValue)` check

### Issue: Type persists after value is cleared
**Cause:** minimumType not cleared when value is empty
**Solution:** Added `else if (!e.target.value) { onChange('minimumType', undefined); }`

### Issue: Zero value not saved
**Cause:** Treating "0" as falsy
**Solution:** Check for empty string specifically, not just falsy values

### Issue: Radio button not defaulting properly
**Cause:** Not setting default when value is first entered
**Solution:** Auto-set to 'inclusive' when value is entered and no type is set

---

## Code Locations

### Form UI
- File: `PropertyFormFields.tsx`
- Lines: ~600-680 (minimum/maximum fields with radio buttons)

### Schema Generation (JSON View)
- File: `PropertyDialog.tsx`
- Function: `buildPropertyJsonSchema()`
- Lines: ~160-230

### Schema Generation (Submit)
- File: `PropertyDialog.tsx`
- Function: `handleSubmit()`
- Lines: ~240-330

### Property Loading
- File: `PropertyDialog.tsx`
- useEffect hook
- Lines: ~105-150

---

## Validation Rules

1. **Empty Check:** `formData.minimum && formData.minimum.trim()`
2. **NaN Check:** `!isNaN(minValue)`
3. **Exclusive/Inclusive:** Only ONE field output (minimum OR exclusiveMinimum)
4. **Type Clearing:** When value is cleared, type is also cleared
5. **Default Type:** When value is entered, defaults to 'inclusive' if not set

---

## JSON Schema Compliance

✅ OpenAPI 3.1.x
✅ JSON Schema draft 2020-12
✅ JSON Schema draft 2019-09

In these specifications:
- `exclusiveMinimum` is a NUMBER (not boolean)
- `exclusiveMaximum` is a NUMBER (not boolean)
- Only one of `minimum` or `exclusiveMinimum` should be present
- Only one of `maximum` or `exclusiveMaximum` should be present

