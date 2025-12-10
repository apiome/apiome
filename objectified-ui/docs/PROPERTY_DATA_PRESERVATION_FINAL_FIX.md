# FINAL COMPREHENSIVE FIX - Property Data Preservation

## The REAL Problem

The code was **REBUILDING** the property data object from scratch instead of **PRESERVING** the original data. This caused ANY field not explicitly listed in the code to be lost.

## The Solution

Changed from **selective copying** to **complete preservation**:

### Before (BROKEN) ❌
```typescript
// Building from scratch - LOSES unlisted fields
const dataObject: any = {
  required: formData.required,
};
if (formData.title) dataObject.title = formData.title;
// ... only listed fields are saved
```

### After (FIXED) ✅
```typescript
// Preserve ALL original fields
const originalData = (mode === 'edit' && property) ? 
  (typeof (property as any).data === 'string' ? 
    JSON.parse((property as any).data) : 
    ((property as any).data || {}))
  : {};

const dataObject: any = {
  ...originalData,  // ← PRESERVES EVERYTHING
  required: formData.required || false,
  readOnly: formData.readOnly || false,
  // ... then update specific fields
};
```

## Key Changes

### 1. Preserve Original Data
```typescript
const originalData = (mode === 'edit' && property) ? ... : {};
const dataObject: any = { ...originalData, ... };
```

### 2. Preserve Original Items for Arrays
```typescript
const originalItems = originalData.items || {};
const itemsSchema: any = {
  ...originalItems,  // ← PRESERVES item fields
  type: propertyType
};
```

### 3. Delete When Empty (Don't Leave Stale Data)
```typescript
if (formData.format) itemsSchema.format = formData.format;
else delete itemsSchema.format;  // ← Clean up when cleared
```

### 4. Proper Exclusive/Inclusive Handling
```typescript
if (formData.minimum && formData.minimum.trim()) {
  const minValue = parseFloat(formData.minimum);
  if (!isNaN(minValue)) {
    if (formData.minimumType === 'exclusive') {
      dataObject.exclusiveMinimum = minValue;
      delete dataObject.minimum;  // ← Remove conflicting field
    } else {
      dataObject.minimum = minValue;
      delete dataObject.exclusiveMinimum;  // ← Remove conflicting field
    }
  }
} else {
  delete dataObject.minimum;
  delete dataObject.exclusiveMinimum;
}
```

## What This Fixes

| Scenario | Before | After |
|----------|--------|-------|
| Custom fields in data | ❌ Lost | ✅ Preserved |
| multipleOf | ❌ Lost | ✅ Preserved |
| readOnly/writeOnly | ❌ Lost | ✅ Preserved |
| deprecated | ❌ Lost | ✅ Preserved |
| example | ❌ Lost | ✅ Preserved |
| additionalProperties | ❌ Lost | ✅ Preserved |
| ANY unlisted field | ❌ Lost | ✅ Preserved |
| Cleared fields | ❌ Stale data | ✅ Properly deleted |

## The Approach

### Edit Mode
1. ✅ Load original property data
2. ✅ Spread it to preserve ALL fields
3. ✅ Update only modified fields
4. ✅ Delete fields that are cleared
5. ✅ Save complete data back

### Add Mode
1. ✅ Start with empty object
2. ✅ Build from form data
3. ✅ Only include set fields

## Complete File Changes

**PropertyDialog.tsx** - `handleSubmit()` function:

1. **Line ~312:** Get original data in edit mode
2. **Line ~316:** Spread original data to preserve everything
3. **Line ~325:** Delete title when empty
4. **Line ~334:** Delete example when empty
5. **Line ~344-347:** Delete array constraints when empty
6. **Line ~351:** Preserve original items schema
7. **Line ~355-404:** Delete item fields when empty, handle exclusive/inclusive
8. **Line ~408-457:** Delete root fields when empty, handle exclusive/inclusive
9. **Line ~463:** Delete additionalProperties when default

## Testing

### Test 1: Custom Field Preservation
```sql
-- Add custom field to property in database
UPDATE odb.class_properties 
SET data = jsonb_set(data, '{customField}', '"customValue"')
WHERE name = 'testProperty';
```

1. Edit the property in UI
2. Change multipleOf to 2
3. Save
4. **Check database**
5. ✅ Verify: `customField` is still there

### Test 2: All Standard Fields
1. Create property with:
   - multipleOf: 2
   - exclusiveMinimum: 0
   - readOnly: true
   - deprecated: true
   - example: 10
2. Save
3. Edit property
4. Change multipleOf to 5
5. Save
6. **Check database**
7. ✅ Verify: ALL fields still present, multipleOf changed to 5

### Test 3: Clearing Fields
1. Edit property with multipleOf: 2
2. Clear multipleOf field
3. Save
4. **Check database**
5. ✅ Verify: `multipleOf` is removed (not set to null or NaN)

### Test 4: Exclusive to Inclusive
1. Create property with exclusiveMinimum: 0
2. Save
3. Edit property
4. Change to "Inclusive (≥)"
5. Save
6. **Check database**
7. ✅ Verify: Has `minimum: 0`, NO `exclusiveMinimum`

## The Core Principle

**PRESERVE FIRST, MODIFY SECOND**

Instead of:
- ❌ Building from scratch (loses data)

We now:
- ✅ Preserve everything
- ✅ Update what changed
- ✅ Delete what's cleared

This is the SAME approach that `ClassPropertyEditDialog.tsx` already uses successfully:
```typescript
const originalData = typeof editingClassProperty.data === 'string'
  ? JSON.parse(editingClassProperty.data)
  : (editingClassProperty.data || {});

const updatedData: any = {
  ...originalData,  // ← This is the key
  required: formData.required,
  // ...
};
```

## Files Modified

- ✅ PropertyDialog.tsx
  - handleSubmit() completely rewritten
  - Now preserves ALL original data
  - Properly deletes cleared fields
  - Handles exclusive/inclusive correctly

## Build Status

✅ No compilation errors (only pre-existing warnings)
✅ Uses spread operator for complete preservation
✅ Deletes cleared fields to prevent stale data
✅ Handles all edge cases

## Result

**ALL property data is now preserved.** The system will:
- ✅ Keep every field from the original property
- ✅ Update only the fields you change
- ✅ Remove fields you clear
- ✅ Never lose custom or unlisted fields

This is the **correct and complete** fix!

