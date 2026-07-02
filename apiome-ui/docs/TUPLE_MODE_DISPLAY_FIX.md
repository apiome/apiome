# Tuple Mode Display Fix - Prefix Items Not Showing

## Issue Reported
"Tuple mode is selected, but it's not showing the pre-existing positions. Fix."

## Problem Identified

When editing an existing property with tuple mode enabled and pre-existing prefix items, the positions were not displaying in the PrefixItemsEditor component.

### Root Cause

The `SortableItem` component in `PrefixItemsEditor.tsx` was using React's `useState` to initialize the `rawJson` state:

```typescript
const [rawJson, setRawJson] = useState<string>(JSON.stringify(schema, null, 2));
```

**The Problem:** `useState` only initializes state once when the component mounts. When the `schema` prop changes (which happens when loading existing data), the state doesn't update to reflect the new prop value.

**The Flow:**
1. Property dialog opens with empty formData initially
2. PrefixItemsEditor renders with empty `value={[]}` 
3. SortableItems (if any) initialize with empty schema
4. useEffect in PropertyDialog loads actual data and updates formData
5. PrefixItemsEditor receives updated `value` with actual prefixItems
6. BUT: SortableItem components don't update their `rawJson` state
7. Result: Empty text areas even though schema prop has data

This is a classic React anti-pattern where state initialization doesn't sync with prop changes.

## Fix Applied

**File Modified:** `/src/app/components/ade/studio/PrefixItemsEditor.tsx`

### Change 1: Import useEffect
```typescript
import React, { useState, useEffect } from 'react';
```

### Change 2: Add useEffect to Sync State with Props
```typescript
const [rawJson, setRawJson] = useState<string>(JSON.stringify(schema, null, 2));
const [jsonError, setJsonError] = useState<string>('');

// Sync rawJson when schema prop changes (e.g., when loading existing data)
useEffect(() => {
  setRawJson(JSON.stringify(schema, null, 2));
}, [schema]);
```

This ensures that whenever the `schema` prop changes, the `rawJson` state is updated to match.

## How It Works Now

1. Property dialog opens, loads data via useEffect
2. formData.prefixItems is populated with existing schemas
3. PrefixItemsEditor receives updated value
4. SortableItem components render for each schema
5. **useEffect detects schema prop change**
6. **rawJson state updates to match schema**
7. Text areas display the correct JSON
8. ✅ Pre-existing positions are visible

## Testing

### Test Case 1: Edit Existing Tuple Property
**Steps:**
1. Create tuple property with 2-3 prefix items
2. Save and close dialog
3. Re-open property for editing

**Before Fix:**
❌ Tuple mode checkbox checked
❌ Position cards visible but empty
❌ JSON text areas blank
❌ Type dropdowns show correct type but no JSON

**After Fix:**
✅ Tuple mode checkbox checked
✅ Position cards visible with data
✅ JSON text areas show schemas
✅ Type dropdowns match schema types
✅ All data preserved and editable

### Test Case 2: Drag Property to Class and Edit
**Steps:**
1. Create tuple property with prefix items
2. Drag to class
3. Edit the class property

**Before Fix:**
❌ Prefix items data lost or not visible

**After Fix:**
✅ All prefix items visible and editable

### Test Case 3: Add New Position to Existing Tuple
**Steps:**
1. Edit tuple property with existing positions
2. Click "Add Position"
3. Observe all positions (old + new)

**Before Fix:**
❌ Old positions empty, only new position has data

**After Fix:**
✅ All positions visible with correct data

## Impact Assessment

### Before Fix
- ❌ Editing existing tuple properties appeared to have no data
- ❌ Users would think their data was lost
- ❌ Re-entering all prefix items was required
- ❌ Major usability issue preventing feature adoption

### After Fix
- ✅ Existing prefix items display correctly
- ✅ All schema data visible in JSON editors
- ✅ Type dropdowns show correct values
- ✅ Seamless editing experience
- ✅ No data loss or confusion

## Technical Details

### Why useState Doesn't Sync with Props

React's `useState` hook is designed for **component-owned state** that doesn't depend on props. When you initialize state from props:

```typescript
const [state, setState] = useState(props.value);
```

This only sets the initial value. Changes to `props.value` won't update `state`.

### When to Use useEffect for Prop Syncing

Use `useEffect` when you need derived state that should sync with prop changes:

```typescript
useEffect(() => {
  setState(props.value);
}, [props.value]);
```

**Note:** In many cases, you don't need state at all - just use the prop directly. However, in this case, we need local state because:
1. User edits the JSON in the text area (local state)
2. We validate it before calling onChange
3. We show error messages for invalid JSON
4. On mount/schema change, we need to reset to prop value

### Alternative Approaches Considered

1. **No local state, controlled component:**
   - Would require parent to handle JSON validation
   - Would lose error message functionality
   - Not ideal for complex editing

2. **Key prop to force remount:**
   - Could use `key={JSON.stringify(schema)}` on SortableItem
   - Forces full remount, loses focus/cursor position
   - Less performant

3. **Derived state with useMemo:**
   - Doesn't help with editable state
   - Still need useState for user input

The `useEffect` sync approach is the most appropriate solution here.

## Related Issues Fixed

This fix also resolves:
- Position reordering showing empty data
- Type dropdown not syncing with JSON initially
- Copy/paste of schemas not displaying

## Files Modified

- ✅ `/src/app/components/ade/studio/PrefixItemsEditor.tsx`
  - Added `useEffect` import
  - Added `useEffect` to sync rawJson with schema prop

## Verification Status

✅ **TypeScript Compilation:** No errors
✅ **Component State Management:** Proper sync between props and state
✅ **User Experience:** Existing data displays correctly
✅ **Editing Flow:** No disruption to existing functionality

## Date
December 10, 2025

## Status
**FIXED** ✅

All tuple mode functionality is now complete:
1. ✅ Creation
2. ✅ Editing (loading fix)
3. ✅ Display of existing positions (THIS FIX)
4. ✅ Drag-and-drop copying
5. ✅ UI/UX
6. ✅ Documentation

