# New Class Button Fix

## Issue
The "New Class" button in the Studio sidebar was not functioning. Clicking it did nothing.

## Root Cause
The `ClassEditDialog` component had several issues that prevented it from handling the "add new class" mode:

1. **Early return on null data**: The component had `if (!editingClassData) return null;` which prevented the dialog from rendering when creating a new class (where `editingClassData` is intentionally `null`).

2. **Missing create function**: The dialog only called `updateClass()` but never `createClass()` for new classes.

3. **Missing versionId prop**: The `createClass()` function requires a `versionId`, but this wasn't being passed to the dialog.

4. **Form state not initialized for add mode**: The `useEffect` hook only populated form data when `editingClassData` was truthy, meaning the form stayed empty in add mode.

5. **Schema generation failed for null data**: The OpenAPI spec generation code directly accessed `editingClassData.name` without checking if it was null.

## Changes Made

### 1. ClassEditDialog.tsx
- **Added `createClass` import** to support creating new classes
- **Added `versionId` prop** to the component interface
- **Updated `useEffect`** to handle both add mode (null `editingClassData`) and edit mode:
  - When `editingClassData` is null, the form is reset to empty state
  - When `editingClassData` exists, the form is populated with the class data
- **Removed early return** that prevented dialog rendering in add mode
- **Updated `handleSave`** to call either `createClass()` or `updateClass()` based on whether `editingClassData` is null
- **Fixed schema generation** to use a preview object when `editingClassData` is null
- **Updated dialog title** to show "Add Class", "Edit Class", or "View Class" based on mode
- **Fixed export function** to handle null `editingClassData`

### 2. layout.tsx
- **Added `versionId` prop** when rendering `ClassEditDialog` component

## Testing
To test the fix:

1. Navigate to the Studio
2. Select a project and version from the canvas
3. Click the "+" FAB button in the Classes tab of the sidebar
4. Verify the "Add Class" dialog opens
5. Enter a class name and description
6. Click Save
7. Verify the new class appears in the sidebar and on the canvas

## Files Modified
- `/Users/kenji/Development/apiome/apiome-ui/src/app/components/ade/studio/ClassEditDialog.tsx`
- `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/layout.tsx`

## Date
December 8, 2025

