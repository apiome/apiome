# Group Class Position Fix

## Issue
Classes dragged inside groups were not saving their positions to the `apiome.group_classes` table. This caused groups to not properly restore when the canvas was reloaded, as the position data (`position_x` and `position_y`) was not being persisted.

## Root Cause
The regression was caused by multiple issues:

1. **handleAddNodeToGroup** - When adding a class to a group via drag-and-drop, only the in-memory state was updated. The database was never updated with the class-to-group relationship or position.

2. **syncGroupsForVersion** - When saving the canvas layout, this function only saved `sort_order` for classes in groups, but NOT `position_x` and `position_y`.

3. **handleNodeDragStop** - When dragging a class within a group (without leaving/entering), there was no database update to persist the new position.

4. **getGroupsForVersion** - The function fetched `position_x` and `position_y` from the database but didn't return them in the response, so they couldn't be used when loading the canvas.

5. **Canvas Loading** - The loading logic didn't apply the saved class positions from groups when restoring the layout.

## Solution

### 1. Database Helper Functions

#### Added `updateClassPositionInGroup`
```typescript
export async function updateClassPositionInGroup(
  groupId: string,
  classId: string,
  positionX: number,
  positionY: number
)
```
New function to update just the position of a class within a group without changing group membership.

#### Updated `getGroupsForVersion`
Now returns a `classPositions` map for each group:
```typescript
classPositions: {
  [classId: string]: { x: number | null; y: number | null }
}
```

#### Updated `syncGroupsForVersion`
Now accepts an optional `nodePositions` parameter and saves positions when syncing:
```typescript
export async function syncGroupsForVersion(
  versionId: string,
  groups: any[],
  nodePositions?: Record<string, { x: number; y: number }>
)
```

#### Updated `saveDefaultCanvasLayout`
Extracts node positions from the nodes array and passes them to `syncGroupsForVersion`:
```typescript
const nodePositions: Record<string, { x: number; y: number }> = {};
if (nodes && Array.isArray(nodes)) {
  nodes.forEach((node: any) => {
    if (node.id && node.position && node.type !== 'groupNode') {
      nodePositions[node.id] = { x: node.position.x, y: node.position.y };
    }
  });
}
await syncGroupsForVersion(versionId, groups, nodePositions);
```

### 2. Editor Page Changes

#### Updated `handleAddNodeToGroup`
Now immediately persists to database when adding a class to a group:
```typescript
const result = await addClassToGroup(groupId, nodeId, {
  positionX: nodePosition.x,
  positionY: nodePosition.y,
  sortOrder: updatedNodeIds.length - 1
});
```

#### Updated `handleNodeDragStop`
Added several cases to persist position updates:

- **Case 2 (Moving between groups)**: If not completely outside, update position in current group
- **Case 3 (Dragging outside)**: If still partially inside, update position in database
- **Case 4 (Dragging within same group)**: NEW - Update position when moving within the same group

```typescript
// Case 4: Node dragged within the same group
else if (currentGroupId && targetGroupId && currentGroupId === targetGroupId) {
  await updateClassPositionInGroup(currentGroupId, node.id, node.position.x, node.position.y);
}
```

#### Updated Canvas Loading
Now extracts and uses saved class positions from groups:

```typescript
// Extract class positions from all groups
loadedGroups.forEach((g: any) => {
  if (g.classPositions) {
    Object.assign(classPositionsInGroups, g.classPositions);
  }
});

// When restoring nodes, prefer group positions
if (classPositionsInGroups[node.id]) {
  const savedPos = classPositionsInGroups[node.id];
  if (savedPos.x !== null && savedPos.y !== null) {
    return {
      ...node,
      position: { x: savedPos.x, y: savedPos.y }
    };
  }
}
```

#### Added Imports
```typescript
import {
  // ...existing imports
  addClassToGroup,
  updateClassPositionInGroup
} from '../../../../../lib/db/helper';
```

## Testing

To test this fix:

1. **Create a group** on the canvas
2. **Drag a class into the group** - verify it gets added
3. **Move the class within the group** to a new position
4. **Save the layout** (manual save button)
5. **Reload the canvas** (refresh the page or switch versions)
6. **Verify** the class is still in the group at the correct position

## Database Schema

The fix leverages existing columns in `apiome.group_classes`:
- `group_id` - UUID reference to the group
- `class_id` - UUID reference to the class
- `position_x` - X coordinate of the class within the canvas
- `position_y` - Y coordinate of the class within the canvas
- `sort_order` - Display order within the group

These columns were already in the schema but weren't being properly used.

## Files Modified

### `/Users/kenji/Development/apiome/apiome-ui/lib/db/helper.ts`
- Updated `getGroupsForVersion()` to return `classPositions`
- Updated `syncGroupsForVersion()` to save node positions
- Updated `saveDefaultCanvasLayout()` to extract and pass node positions
- Added `updateClassPositionInGroup()` function

### `/Users/kenji/Development/apiome/apiome-ui/src/app/ade/studio/editor/page.tsx`
- Updated `handleAddNodeToGroup()` to persist immediately
- Updated `handleNodeDragStop()` to handle all position update cases
- Updated group loading logic to extract and use `classPositions`
- Updated node restoration logic to prefer group positions
- Added imports for new database functions

## Date
January 3, 2026

