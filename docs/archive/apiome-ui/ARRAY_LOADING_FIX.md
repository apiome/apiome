# Critical Fix: Array Types Not Loading Constraints

## The Problem

When you save a property with exclusive/inclusive constraints and then reopen it to edit, the form wasn't showing your previous selection. This was particularly an issue with **array types**.

### Root Cause

For array types, JSON Schema stores item constraints inside the `items` object:

```json
{
  "type": "array",
  "items": {
    "type": "number",
    "exclusiveMinimum": 0    ← Constraint is HERE
  }
}
```

But the loading code was looking at the root level:
```typescript
// ❌ WRONG - This looks at property.exclusiveMinimum
if (property.exclusiveMinimum !== undefined) {
  // Never found for array types!
}
```

## The Fix

Updated the loading logic to check the correct location based on property type:

```typescript
// ✅ CORRECT - Check items for array types, root for others
const minMaxSource = isArray && (property as any).items 
  ? (property as any).items    // For arrays: look in items
  : property;                  // For non-arrays: look at root

if (minMaxSource.exclusiveMinimum !== undefined) {
  minimumValue = minMaxSource.exclusiveMinimum.toString();
  minimumType = 'exclusive';
} else if (minMaxSource.minimum !== undefined) {
  minimumValue = minMaxSource.minimum.toString();
  minimumType = 'inclusive';
}
```

## Test Scenario

### Test Case 1: Array of Positive Numbers

**Step 1: Create Property**
1. Open property dialog
2. Property name: `scores`
3. Check "An array of..."
4. Type: `number`
5. Minimum: `0`
6. Select: "Exclusive (>)"
7. Save

**Expected JSON:**
```json
{
  "type": "array",
  "items": {
    "type": "number",
    "exclusiveMinimum": 0
  }
}
```

**Step 2: Edit Property**
1. Reopen the `scores` property
2. **✅ VERIFY:** Minimum field shows `0`
3. **✅ VERIFY:** "Exclusive (>)" radio is selected
4. **✅ VERIFY:** JSON view shows `"exclusiveMinimum": 0` inside items

**Step 3: Change to Inclusive**
1. Select "Inclusive (≥)"
2. Save
3. Reopen property
4. **✅ VERIFY:** "Inclusive (≥)" is now selected
5. **✅ VERIFY:** JSON shows `"minimum": 0` (not exclusiveMinimum)

---

### Test Case 2: Non-Array Number

**Step 1: Create Property**
1. Property name: `age`
2. DON'T check "An array of..."
3. Type: `integer`
4. Minimum: `0`
5. Select: "Exclusive (>)"
6. Save

**Expected JSON:**
```json
{
  "type": "integer",
  "exclusiveMinimum": 0
}
```

**Step 2: Edit Property**
1. Reopen the `age` property
2. **✅ VERIFY:** Minimum field shows `0`
3. **✅ VERIFY:** "Exclusive (>)" radio is selected
4. **✅ VERIFY:** JSON view shows `"exclusiveMinimum": 0` at root level

---

### Test Case 3: Array with Mixed Constraints

**Step 1: Create Property**
1. Property name: `probabilities`
2. Check "An array of..."
3. Type: `number`
4. Minimum: `0`, select "Exclusive (>)"
5. Maximum: `1`, select "Exclusive (<)"
6. Save

**Expected JSON:**
```json
{
  "type": "array",
  "items": {
    "type": "number",
    "exclusiveMinimum": 0,
    "exclusiveMaximum": 1
  }
}
```

**Step 2: Edit Property**
1. Reopen property
2. **✅ VERIFY:** Minimum shows `0` with "Exclusive (>)" selected
3. **✅ VERIFY:** Maximum shows `1` with "Exclusive (<)" selected
4. **✅ VERIFY:** JSON shows both exclusive constraints

**Step 3: Change One to Inclusive**
1. Change maximum to "Inclusive (≤)"
2. Save
3. Reopen
4. **✅ VERIFY:** Minimum still "Exclusive (>)"
5. **✅ VERIFY:** Maximum now "Inclusive (≤)"
6. **✅ VERIFY:** JSON shows:
```json
{
  "exclusiveMinimum": 0,
  "maximum": 1
}
```

---

## Other Fields Also Fixed

The same fix was applied to these fields for array types:
- ✅ `format`
- ✅ `pattern`
- ✅ `minLength`
- ✅ `maxLength`
- ✅ `multipleOf`
- ✅ `enum`
- ✅ `default`

All of these now correctly load from `items` for array types.

## What Was Changed

**File:** `PropertyDialog.tsx`

**Lines:** ~105-146

**Change:**
```typescript
// BEFORE: Always looked at property.minimum
const minimumValue = property.minimum?.toString() || '';

// AFTER: Looks at items for arrays
const minMaxSource = isArray && (property as any).items 
  ? (property as any).items 
  : property;
const minimumValue = minMaxSource.minimum?.toString() || '';
```

## Impact

| Scenario | Before Fix | After Fix |
|----------|-----------|-----------|
| Create array with exclusive min | ✅ Works | ✅ Works |
| Edit array with exclusive min | ❌ Shows blank/wrong | ✅ Shows correct |
| Save changes | ✅ Saves correctly | ✅ Saves correctly |
| Reopen after save | ❌ Lost selection | ✅ Preserves selection |
| Non-array properties | ✅ Works | ✅ Still works |

## Quick Verification

1. Create an array property with `exclusiveMinimum: 0`
2. Save and close
3. Edit the property
4. Check if "Exclusive (>)" is selected ← **This should now work!**

## Related Files

- `PropertyDialog.tsx` - Loading logic fixed
- `PropertyFormFields.tsx` - UI components (unchanged)
- `EXCLUSIVE_MINMAX_FIX_SUMMARY.md` - Complete fix documentation

