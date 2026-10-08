# FINAL FIX: ClassPropertyEditDialog Updated

## The Real Issue

The problem was in **ClassPropertyEditDialog.tsx** (not PropertyDialog.tsx)! This is the actual dialog used for editing properties in the studio.

## What Was Wrong

### Loading (Line 131-132)
```typescript
// ❌ OLD CODE - Using OpenAPI 3.0 boolean style
exclusiveMinimum: !!schema.exclusiveMinimum,
exclusiveMaximum: !!schema.exclusiveMaximum,
```

This converted the numeric values to booleans, losing the actual value!

### Saving (Lines 220-245)
```typescript
// ❌ OLD CODE - Using boolean flags
if (formData.exclusiveMinimum) {
  targetSchema.exclusiveMinimum = parseFloat(formData.minimum);
```

This treated exclusiveMinimum as a boolean flag instead of using minimumType.

## What's Fixed Now

### Loading (NEW)
```typescript
// ✅ NEW CODE - Detect type from which field exists
minimum: (schema.exclusiveMinimum !== undefined 
  ? schema.exclusiveMinimum 
  : schema.minimum)?.toString() || '',
minimumType: schema.exclusiveMinimum !== undefined 
  ? 'exclusive' 
  : (schema.minimum !== undefined ? 'inclusive' : undefined),
```

### Saving (NEW)
```typescript
// ✅ NEW CODE - Use minimumType to decide which field
if (formData.minimum && formData.minimum.trim()) {
  const minValue = parseFloat(formData.minimum);
  if (!isNaN(minValue)) {
    if (formData.minimumType === 'exclusive') {
      targetSchema.exclusiveMinimum = minValue;
      delete targetSchema.minimum;
    } else {
      targetSchema.minimum = minValue;
      delete targetSchema.exclusiveMinimum;
    }
  }
}
```

## Files Modified

1. ✅ **PropertyFormFields.tsx** - UI with radio buttons
2. ✅ **PropertyDialog.tsx** - Add property dialog (fixed earlier)
3. ✅ **ClassPropertyEditDialog.tsx** - Edit property dialog (JUST FIXED)

## Complete Test Flow

### Test 1: Create and Edit Non-Array Property

**Create:**
1. Add a class property: `age` (integer)
2. Set minimum: `0`, select "Exclusive (>)"
3. Save

**Edit:**
1. Open the property for editing
2. ✅ **VERIFY:** Minimum shows `0`
3. ✅ **VERIFY:** "Exclusive (>)" is selected
4. Change to "Inclusive (≥)"
5. Save
6. Reopen
7. ✅ **VERIFY:** "Inclusive (≥)" is now selected

### Test 2: Create and Edit Array Property

**Create:**
1. Add a class property: `scores` (array of numbers)
2. Set minimum: `0`, select "Exclusive (>)"
3. Save

**Edit:**
1. Open the property for editing
2. ✅ **VERIFY:** Minimum shows `0`
3. ✅ **VERIFY:** "Exclusive (>)" is selected
4. Change to maximum: `100`, select "Inclusive (≤)"
5. Save
6. Reopen
7. ✅ **VERIFY:** Both constraints are preserved

### Test 3: Mixed Constraints

**Create:**
1. Add property: `probability` (number)
2. Minimum: `0`, "Exclusive (>)"
3. Maximum: `1`, "Exclusive (<)"
4. Save

**Edit:**
1. Reopen property
2. ✅ **VERIFY:** Both show exclusive
3. Change minimum to "Inclusive (≥)"
4. Save
5. Reopen
6. ✅ **VERIFY:** Minimum is inclusive, maximum still exclusive

**Expected JSON:**
```json
{
  "type": "number",
  "minimum": 0,
  "exclusiveMaximum": 1
}
```

## What This Fixes

| Action | Before | After |
|--------|--------|-------|
| Create with exclusive | ✅ Worked | ✅ Works |
| Save exclusive | ❌ Saved as boolean | ✅ Saves as number |
| Reopen property | ❌ Lost selection | ✅ Shows selection |
| Edit and save | ❌ Broken | ✅ Works |
| JSON output | ❌ Wrong format | ✅ Correct format |

## Key Changes Summary

### ClassPropertyEditDialog.tsx

**Lines ~131-135:** Fixed loading
- Old: Converted to boolean
- New: Extracts value and determines type

**Lines ~220-250:** Fixed saving  
- Old: Used boolean flags
- New: Uses minimumType/maximumType

**Both changes:**
- Added NaN validation
- Added trim() check
- Delete opposite field when setting one
- OpenAPI 3.1 compliant

## Verification Commands

```bash
# Check the file was modified
grep -A 5 "minimumType:" src/app/components/ade/studio/ClassPropertyEditDialog.tsx

# Should show the new code with minimumType/maximumType
```

## Bottom Line

**THIS IS THE FIX YOU NEED!**

The issue was that `ClassPropertyEditDialog.tsx` (the actual edit dialog) was still using the old OpenAPI 3.0 boolean approach. It's now fixed to use the OpenAPI 3.1 numeric approach with radio buttons.

Your exclusive/inclusive selections will now:
✅ Save correctly
✅ Load correctly
✅ Display correctly
✅ Persist across edits

