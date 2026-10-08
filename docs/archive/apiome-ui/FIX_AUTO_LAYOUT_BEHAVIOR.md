# Fix: Auto-Layout Behavior on Canvas

## Problem
The canvas was triggering auto-layout when it should not. The auto-layout should only be refreshed when:
1. A class is deleted
2. A class is added
3. The user explicitly selects a different auto-layout direction

Under no other circumstances should the layout be re-done, particularly not when:
- Properties are added or removed
- Properties are expanded/collapsed
- Property details are edited
- Read-only mode is toggled
- Other UI state changes

## Root Causes

### 1. Unnecessary Dependencies in useEffect
The main `loadClasses` useEffect had too many dependencies:
```typescript
// BEFORE - triggers on ANY callback or state change
}, [selectedVersionId, selectedProjectId, canvasRefreshKey, layoutDirection, 
    setNodes, setEdges, fitView, handlePropertyDrop, handlePropertyEdit, 
    handlePropertyDelete, handleClassEdit, generateOpenApiSpec, projects, 
    versions, isReadOnly, globalExpandedProperties, handleTogglePropertyExpansion]);
```

These callbacks were recreated on every render when their dependencies changed, causing the entire canvas to reload and re-layout.

### 2. Property Operations Applying Auto-Layout
When properties were added or deleted, the code was calling `getLayoutedElements()`, which unnecessarily repositioned all nodes:
```typescript
// BEFORE - auto-layout on property add/delete
const layoutedNodes = getLayoutedElements(newNodes, newEdges, { direction: layoutDirection });
setNodes(layoutedNodes);
```

### 3. reloadClasses Always Applied Auto-Layout
The `reloadClasses` helper function always applied auto-layout, even when called for minor edits that shouldn't affect node positions.

## Solution

### 1. Use Stable Callback References
Created `useRef` references for all event handler callbacks to prevent unnecessary re-renders:

```typescript
// Create stable refs for callbacks
const handlePropertyDropRef = useRef<any>(null);
const handlePropertyEditRef = useRef<any>(null);
const handlePropertyDeleteRef = useRef<any>(null);
const handleClassEditRef = useRef<any>(null);
const handleClassDeleteRef = useRef<any>(null);
const handleCreateReferenceRef = useRef<any>(null);
const handleTogglePropertyExpansionRef = useRef<any>(null);

// Update refs after each callback definition
handlePropertyDropRef.current = handlePropertyDrop;
// ... etc
```

### 2. Use Refs in Node Data
Modified `classesToNodes` to use the stable refs instead of direct callback references:

```typescript
// AFTER - use stable refs
onPropertyDrop: (...args: any[]) => handlePropertyDropRef.current?.(...args),
onPropertyEdit: (...args: any[]) => handlePropertyEditRef.current?.(...args),
// ... etc
```

### 3. Remove Unnecessary Dependencies
Cleaned up the `loadClasses` useEffect dependencies:

```typescript
// AFTER - only essential dependencies
}, [selectedVersionId, selectedProjectId, canvasRefreshKey, layoutDirection, 
    setNodes, setEdges, fitView, generateOpenApiSpec, projects, versions]);
```

Removed: `handlePropertyDrop`, `handlePropertyEdit`, `handlePropertyDelete`, `handleClassEdit`, `isReadOnly`, `globalExpandedProperties`, `handleTogglePropertyExpansion`

### 4. Preserve Node Positions on Property Changes
Modified property add/delete operations to preserve existing node positions:

```typescript
// AFTER - preserve positions when updating properties
const existingPositions = new Map(nodes.map(n => [n.id, n.position]));
const newNodes = await classesToNodes(classesWithProperties);
// Restore positions from existing nodes
newNodes.forEach(node => {
  const existingPos = existingPositions.get(node.id);
  if (existingPos) {
    node.position = existingPos;
  }
});
setNodes(newNodes);
```

### 5. Add Parameter to reloadClasses
Modified `reloadClasses` to accept an optional `applyLayout` parameter:

```typescript
const reloadClasses = useCallback(async (applyLayout = false) => {
  // ...
  if (applyLayout) {
    // Apply auto-layout for class add/delete
    const layoutedNodes = getLayoutedElements(newNodes, newEdges, { direction: layoutDirection });
    // ...
  } else {
    // Preserve existing positions
    // ...
  }
});
```

Updated class delete to pass `true`:
```typescript
await reloadClasses(true); // Apply auto-layout when class is deleted
```

## Behavior After Fix

### Auto-Layout WILL Trigger On:
1. **Version Selection** - When a different version is selected (`selectedVersionId` changes)
2. **Class Added** - When a new class is created (`canvasRefreshKey` increments)
3. **Class Deleted** - When a class is deleted (`reloadClasses(true)` is called)
4. **Layout Direction Change** - When user selects a different layout (TB, LR, etc.) (`layoutDirection` changes)

### Auto-Layout WILL NOT Trigger On:
1. Property added to a class
2. Property removed from a class
3. Property edited (name, constraints, etc.)
4. Property expanded/collapsed
5. Reference created
6. Read-only mode toggled
7. Other UI state changes

## Files Modified
- `/home/kenji/Development/apiome/apiome-ui/src/app/ade/studio/page.tsx`

## Testing Checklist
- [ ] Load a version with classes - layout should apply
- [ ] Add a property to a class - nodes should NOT move
- [ ] Remove a property from a class - nodes should NOT move
- [ ] Edit a property - nodes should NOT move
- [ ] Expand/collapse properties - nodes should NOT move
- [ ] Create a reference - nodes should NOT move
- [ ] Toggle read-only mode - nodes should NOT move
- [ ] Delete a class - layout should apply (nodes redistribute)
- [ ] Add a new class - layout should apply
- [ ] Change layout direction - layout should apply with new direction

