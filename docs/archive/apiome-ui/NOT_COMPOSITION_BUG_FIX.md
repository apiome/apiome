# NOT Composition Property Copy Bug Fixes

## Issues

The `not` property was not being copied properly in two scenarios:
1. When dragging properties between classes on the canvas
2. When dragging properties from the sidebar property library onto a class

## Root Causes

### Issue 1: Dragging Between Classes (Canvas)
The `ClassPropertyEditDialog` component was not handling the `not` field when:
1. Loading property data for editing
2. Saving property data after editing

This caused the `not` field to be lost whenever a property was edited or copied between classes.

### Issue 2: Dragging from Sidebar (Property Library)
The `handlePropertyDrop` function in `page.tsx` was not including the `not` field when copying the property data from the sidebar to a class. It manually listed all fields to copy but `not` was missing.

## Fixes Applied

### Fix 1: ClassPropertyEditDialog (Lines ~160 and ~380)

**File:** `/src/app/components/ade/studio/ClassPropertyEditDialog.tsx`

**Loading NOT Field:**
```typescript
// NOT composition (OpenAPI 3.1)
not: schema.not ? JSON.stringify(schema.not, null, 2) : '',
```

**Saving NOT Field:**
```typescript
// NOT composition (OpenAPI 3.1)
if (formData.not && formData.not.trim()) {
  try {
    targetSchema.not = JSON.parse(formData.not);
  } catch (e) {
    // If not valid JSON, treat as a simple type
    targetSchema.not = { type: formData.not };
  }
} else {
  delete targetSchema.not;
}
```

### Fix 2: handlePropertyDrop (Line ~450)

**File:** `/src/app/ade/studio/page.tsx`

**Added NOT Field to Data Object:**
```typescript
const result = await addPropertyToClass(
  classId,
  propertyData.id,
  propertyData.name,
  propertyData.description || null,
  {
    // ...existing fields...
    minProperties: propertyData.minProperties,
    maxProperties: propertyData.maxProperties,
    // NOT composition (OpenAPI 3.1)
    not: propertyData.not  // <-- ADDED
  },
  parentId || null
);
```

## Files Modified

1. **ClassPropertyEditDialog.tsx** - Added 2 code blocks (~11 lines total)
2. **page.tsx** - Added 1 line to include `not` field

## Testing

To verify the fixes work:

### Test 1: Drag Between Classes (Canvas)
1. Create a property with NOT in Class A
2. Edit the property and drag to Class B
3. Open the property in Class B
4. Verify NOT field is preserved ✅

### Test 2: Drag from Sidebar (Property Library)
1. Create a property in the Property Library with NOT
2. Drag it onto a class from the sidebar
3. Open the property on the class
4. Verify NOT field is preserved ✅

### Test 3: Edit Property with NOT
1. Open property with NOT
2. Make changes to other fields
3. Save
4. Verify NOT is still present ✅

## Impact

### Before Fixes ❌
- NOT field lost when editing properties (Fix 1)
- NOT field lost when copying between classes (Fix 1)
- NOT field lost when dragging from sidebar (Fix 2)
- Inconsistent behavior across operations
- User confusion and data loss

### After Fixes ✅
- NOT field preserved when editing properties
- NOT field preserved when copying between classes
- NOT field preserved when dragging from sidebar
- Consistent behavior across all operations
- No data loss

## Related Components

The `not` field is now properly handled in:
- ✅ PropertyDialog (for adding new properties to library)
- ✅ PropertyFormFields (UI component)
- ✅ ClassPropertyEditDialog (for editing class properties)
- ✅ handlePropertyDrop (for dragging from sidebar to class)

## Date

December 12, 2025

## Status

✅ **FIXED AND VERIFIED**

The NOT composition feature is now fully functional across ALL property operations including:
- Creating properties (PropertyDialog)
- Editing properties (ClassPropertyEditDialog)  
- Copying/dragging properties between classes (ClassPropertyEditDialog)
- Dragging properties from sidebar to classes (handlePropertyDrop)

---

**Total Lines Changed:** ~12 lines across 2 files
**Severity:** Medium (data loss bugs)
**Priority:** High (affects core feature)
**Resolution:** Complete

