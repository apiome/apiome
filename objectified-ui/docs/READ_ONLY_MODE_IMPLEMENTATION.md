# Read-Only Mode Implementation

## Overview
This document describes the implementation of read-only mode for published versions in the Studio canvas. When a version is marked as published (locked), all editing operations are disabled to prevent modifications.

## Changes Made

### 1. ReactFlow Canvas (studio/page.tsx)
**Line ~843-848**: Added read-only properties to ReactFlow component:
- `nodesDraggable={!isReadOnly}` - Prevents dragging nodes in read-only mode
- `nodesConnectable={!isReadOnly}` - Prevents creating new connections in read-only mode
- `elementsSelectable={true}` - Allows selection for viewing (still enabled)
- `nodesFocusable={true}` - Allows focusing on nodes (still enabled)
- `edgesFocusable={true}` - Allows focusing on edges (still enabled)

### 2. Event Handlers (studio/page.tsx)
Added read-only checks to all edit/delete handlers:

**handlePropertyDrop** (~Line 152):
```typescript
if (isReadOnly) {
  return;
}
```
Prevents dropping properties onto classes in read-only mode.

**handlePropertyDelete** (~Line 217):
```typescript
if (isReadOnly) {
  return;
}
```
Prevents deleting properties from classes in read-only mode.

**handleClassEdit** (~Line 261):
```typescript
if (isReadOnly) {
  return;
}
```
Prevents opening the class edit dialog in read-only mode.

**handlePropertyEdit** (~Line 274):
```typescript
if (isReadOnly) {
  return;
}
```
Prevents opening the property edit dialog in read-only mode.

**handleClassDelete** (~Line 289):
```typescript
if (isReadOnly) {
  return;
}
```
Prevents deleting classes in read-only mode.

### 3. ClassNode Component (components/ade/studio/ClassNode.tsx)
**Lines ~53, ~99, ~170, ~248**: The component already had read-only checks:
- Prevents drag-and-drop of properties onto classes
- Hides delete button on class header
- Hides edit/delete buttons on properties
- Disables double-click to edit

The `isReadOnly` flag is passed through node data at line ~318 in page.tsx:
```typescript
isReadOnly: isReadOnly
```

### 4. StudioSideNav Component (components/ade/studio/StudioSideNav.tsx)
**Already implemented** - The sidebar already had read-only checks:
- **Line 279**: Add Class button disabled when `isReadOnly`
- **Line 234, 246**: Edit/Delete buttons disabled for classes when `isReadOnly`
- **Line 333**: Properties are not draggable when `isReadOnly` (updated cursor style)
- **Line 335**: Drag start prevented when `isReadOnly`
- **Line 393, 405**: Edit/Delete buttons disabled for properties when `isReadOnly`
- **Line 435**: Add Property button disabled when `isReadOnly`

### 5. Read-Only Indicator (studio/page.tsx)
**Line ~880**: A visual indicator is displayed on the canvas when in read-only mode:
```typescript
{isReadOnly && (
  <Panel position="top-left" className="bg-yellow-100 dark:bg-yellow-900/40...">
    <div className="flex items-center gap-1.5">
      <svg>...</svg>
      <span>Read Only</span>
    </div>
  </Panel>
)}
```

## How It Works

1. **Version Selection**: When a user selects a version in the canvas dropdowns (line ~668):
   ```typescript
   const version = versions.find(v => v.id === versionId);
   setIsReadOnly(version?.published || false);
   ```

2. **Dependency Tracking**: The `isReadOnly` flag is included in dependency arrays:
   - **Line ~646**: `reloadClasses` useCallback includes `isReadOnly` in dependencies
   - **Line ~657**: `useEffect` that loads classes includes `isReadOnly` in dependencies
   
   This ensures that when the `isReadOnly` state changes, all nodes are re-created with the updated flag, properly enabling or disabling edit controls.

3. **Flag Propagation**: The `isReadOnly` flag from the StudioContext is:
   - Passed to ReactFlow properties to disable interactions
   - Passed to all node data so ClassNode components can hide edit controls
   - Passed to StudioSideNav to disable buttons
   - Checked in all event handlers before performing any modifications

3. **Visual Feedback**: When read-only mode is active:
   - A yellow "Read Only" indicator appears in the top-left of the canvas
   - All edit/delete buttons are disabled with appropriate tooltips
   - Properties cannot be dragged from the sidebar
   - Nodes cannot be dragged on the canvas
   - The cursor changes from "grab" to "default" for properties

## Testing
To test read-only mode:
1. Create a project and version in the Studio
2. Add some classes and properties
3. Mark the version as published (this sets the `published` flag to true)
4. Select the published version in the canvas
5. Verify that:
   - The "Read Only" indicator appears
   - All edit/delete buttons are disabled
   - Nodes cannot be dragged
   - Properties cannot be dragged onto classes
   - Double-clicking nodes does nothing
   - Layout buttons still work (read-only allows viewing)

## Important Notes

### Critical Fixes Applied

#### 1. Dependency Tracking Issue (Fixed)
The initial implementation had a bug where `isReadOnly` was not included in the dependency arrays of:
- `reloadClasses` useCallback (line ~138)
- The `useEffect` that loads classes when version changes (line ~647)

This caused nodes to retain stale `isReadOnly` values. The fix ensures that whenever `isReadOnly` changes, all nodes are re-created with the current flag value.

#### 2. Auto-Selection Issue (Fixed)
When a project was selected and the first version was auto-selected (line ~672), the `isReadOnly` flag was not being set. This caused issues when the only version or the first version in the list was published.

**Fix**: Now when auto-selecting the first version:
```typescript
const firstVersion = versionsData[0];
setSelectedVersionId(firstVersion.id);
setIsReadOnly(firstVersion.published || false);
```

#### 3. State Reset Issues (Fixed)
The `isReadOnly` flag was not being reset when:
- Project selection changed (line ~687)
- Project was deselected (line ~583)

**Fix**: Added `setIsReadOnly(false)` in both cases to ensure clean state.

## Future Enhancements
- Consider adding a visual overlay or watermark to make read-only mode more obvious
- Add toast notifications when users try to edit in read-only mode
- Consider making the entire canvas have a subtle color tint in read-only mode

