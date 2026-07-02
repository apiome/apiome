# Read-Only Mode Viewing Update

## Overview
Updated the canvas read-only mode to allow viewing and repositioning while maintaining editing restrictions.

## Changes Made

### 1. **ReactFlow Canvas (page.tsx)**
Changed `nodesDraggable` property:
- **Before**: `nodesDraggable={!isReadOnly}` (disabled dragging)
- **After**: `nodesDraggable={true}` (always enabled)

**Reason**: Users should be able to reposition nodes for better viewing even in read-only mode.

### 2. **ClassNode Component (ClassNode.tsx)**
Updated `handleDoubleClick` function:
- **Before**: Returned early if `isReadOnly`, preventing any dialog from opening
- **After**: Always opens the class edit dialog, which handles read-only restrictions internally

**Reason**: Users should be able to view class schemas even in read-only mode.

### 3. **ClassEditDialog Component (ClassEditDialog.tsx)**
Added read-only support:
- Added `isReadOnly?: boolean` prop
- Updated dialog title to show "View Class" instead of "Edit Class" when read-only
- Added visual "Read Only" badge in dialog header

### 4. **Parent Component (page.tsx)**
- Removed early return in `handleClassEdit` that prevented opening dialog
- Added `isReadOnly={isReadOnly}` prop when rendering `ClassEditDialog`
- Dialog now opens for viewing even when read-only

## Behavior in Read-Only Mode

### ✅ **ALLOWED** (View & Navigate)
- ✅ **Drag nodes** to reposition them on canvas
- ✅ **Double-click nodes** to view class schema
- ✅ **Select nodes** to highlight them
- ✅ **View class properties** in the dialog
- ✅ **View OpenAPI spec** (JSON/YAML/Example)
- ✅ **Copy schema** to clipboard
- ✅ **Download schema** files
- ✅ **Switch between JSON/YAML/Example** views
- ✅ **Use layout buttons** to rearrange canvas

### ❌ **DISABLED** (Edit Operations)
- ❌ **Create new connections** between nodes
- ❌ **Drop properties** onto classes
- ❌ **Edit class properties** (buttons hidden)
- ❌ **Delete classes** (buttons hidden)
- ❌ **Add new classes** (sidebar button disabled)
- ❌ **Edit properties** (buttons hidden)
- ❌ **Delete properties** (buttons hidden)

## User Experience Flow

### Viewing a Locked Version

1. **Select a published version** in the canvas
2. **Read-Only indicator** appears in top-left corner
3. **User can:**
   - Drag nodes around to see relationships better
   - Double-click any node to view its schema
   - Dialog opens showing full class definition
   - View schema in JSON, YAML, or example format
   - Copy or download the schema

### Dialog in Read-Only Mode

**Title Bar Shows:**
```
View Class: Customer     [Read Only]
```

**Features Available:**
- Format toggle (JSON/YAML/Example)
- Copy button
- Download button
- Refresh example button (for Example view)
- Close button

**Features Disabled:**
- No save/edit buttons (since dialog is view-only)
- Schema is displayed but not editable

## Code Examples

### Opening Dialog in Read-Only Mode
```typescript
// User double-clicks a node
handleDoubleClick() {
  // Opens dialog regardless of read-only status
  onClassEdit({
    id, name, description, schema, properties
  });
}

// Dialog opens with isReadOnly flag
<ClassEditDialog
  open={true}
  editingClassData={classData}
  nodes={nodes}
  isReadOnly={true}  // <-- Controls view-only mode
/>
```

### Dialog Title Logic
```typescript
{isReadOnly ? 'View Class: ' : 'Edit Class: '}{editingClassData.name}
```

## Visual Indicators

### Canvas
- Yellow "Read Only" badge in top-left corner
- Nodes have pointer cursor (indicating they're interactive)
- Sidebar buttons are disabled
- Node edit/delete buttons are hidden

### Dialog
- Title shows "View Class" instead of "Edit Class"
- Orange "Read Only" badge next to title
- All viewing features enabled
- No save/edit options displayed

## Benefits

1. **Better UX**: Users can explore and understand schemas even for locked versions
2. **Documentation**: Developers can review published API specifications
3. **Validation**: Team members can verify schemas without risk of modification
4. **Flexibility**: Nodes can be rearranged for better visualization
5. **Learning**: New team members can explore without accidentally making changes

## Testing Checklist

- [x] Nodes are draggable in read-only mode
- [x] Double-clicking a node opens the view dialog
- [x] Dialog shows "View Class" title in read-only mode
- [x] Dialog shows "Read Only" badge
- [x] All viewing features work (JSON/YAML/Example)
- [x] Copy and download buttons work
- [x] No edit buttons appear in read-only dialog
- [x] Cannot create new connections
- [x] Cannot drop properties onto classes
- [x] Sidebar buttons remain disabled
- [x] Layout buttons still work

## Migration Notes

**Before this change:**
- Locked versions were "look but don't touch"
- Nodes couldn't be moved
- Schemas couldn't be viewed
- Very restrictive

**After this change:**
- Locked versions are "explore and learn"
- Nodes can be repositioned
- Schemas can be viewed in detail
- Balanced restriction and usability

## Future Enhancements

1. **Export Canvas Layout**: Save node positions even for read-only versions
2. **Annotations**: Allow adding view-only notes/comments
3. **Comparison View**: Compare locked version with draft version
4. **Print/PDF**: Export canvas with current layout as PDF
5. **Share Link**: Generate shareable link with specific node positions

## Summary

✅ **Read-only mode now supports:**
- Node repositioning for better viewing
- Double-click to view class schemas
- Full schema viewing in multiple formats
- Copy and download capabilities

❌ **Read-only mode still prevents:**
- All editing operations
- Creating connections
- Modifying properties
- Deleting classes

The balance between viewing and editing has been improved to provide a better user experience while maintaining data integrity for published versions.

