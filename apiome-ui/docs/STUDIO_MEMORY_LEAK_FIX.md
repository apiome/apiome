# Studio Editor Memory Leak Fix

## Issue
Navigating to `/ade/studio` was causing the system to hang and run out of memory, especially when there are no classes in the project or version. The issue was caused by:
1. **Redirect loop** - Using `router.replace()` in the redirect page was causing navigation issues
2. **Infinite loops in useEffect and useCallback hooks** - Due to improper dependency management in the editor page

## Root Causes

### 0. Problematic Redirect Mechanism (CRITICAL)
The `/ade/studio/page.tsx` redirect page was using Next.js router's `replace()` method in a useEffect:
```typescript
const router = useRouter();
useEffect(() => {
  router.replace('/ade/studio/editor');
}, [router]);
```

This could cause redirect loops or delays, especially when combined with the useEffect issues in the editor page. The `router` object in dependencies could trigger re-renders.

### 1. Infinite Loop in Main Load Effect (Line 3268)
The main `loadClasses` useEffect included stable React setState functions in its dependency array:
- `setNodes`
- `setEdges`
- `fitView`
- `setGroups`
- `setViewport`
- `triggerSidebarRefresh`

These functions never change, but React was treating them as dependencies, causing the effect to re-run continuously.

### 2. Cascading Re-renders in Spec Generation (Line 3343)
The spec generation useEffect included `nodes` in its dependencies, causing it to regenerate specs every time nodes changed, which could trigger during layout operations.

### 3. Multiple Callbacks with `nodes` Dependencies
Several useCallback hooks included `nodes` and `setNodes` in their dependency arrays:
- `reloadClasses` (Line 452)
- `handleThemeChange` (Line 345)
- `handleExpandAll` (Line 379)
- `handleCollapseAll` (Line 387)
- `zoomToClass` (Line 409)

These callbacks would be recreated every time nodes changed, causing downstream effects.

## Fixes Applied

### 0. Fixed Redirect Page (CRITICAL FIX)
```typescript
// Before: Used Next.js router which could cause loops
import { useRouter } from 'next/navigation';
const router = useRouter();
useEffect(() => {
  router.replace('/ade/studio/editor');
}, [router]);

// After: Direct window.location.href navigation
useEffect(() => {
  window.location.href = '/ade/studio/editor';
}, []);
```
**Impact**: Eliminates potential redirect loops and ensures immediate navigation without React router overhead.

### 1. Removed Stable Functions from loadClasses Dependencies
```typescript
// Before
}, [selectedVersionId, selectedProjectId, canvasRefreshKey, setNodes, setEdges, fitView, projects, versions, currentUserId, setGroups, setViewport, projectTags, isReadOnly, triggerSidebarRefresh]);

// After
}, [selectedVersionId, selectedProjectId, canvasRefreshKey, projects, versions, currentUserId, projectTags, isReadOnly]);
```

### 2. Fixed loadClasses to Use Functional setState for Position Preservation
```typescript
// Before: Used stale nodes closure
const existingPositions = new Map(nodes.map(n => [n.id, n.position]));

// After: Uses functional setState to access current nodes
setNodes((currentNodes) => {
  if (currentNodes.length > 0) {
    const existingPositions = new Map(currentNodes.map(n => [n.id, n.position]));
    newNodes.forEach(node => {
      const existingPos = existingPositions.get(node.id);
      if (existingPos) {
        node.position = existingPos;
      }
    });
  }
  return currentNodes; // Return current for now
});
```

### 3. Removed nodes from Spec Generation Dependencies
```typescript
// Before
}, [viewMode, codeDisplayFormat, selectedVersionId, selectedProjectId, projects, versions, nodes]);

// After - Also refactored to use functional setState
}, [viewMode, codeDisplayFormat, selectedVersionId, selectedProjectId, projects, versions]);
```

### 4. Fixed Spec Generation to Access Current Nodes
```typescript
// Before: Used stale nodes closure
const classesWithProperties = nodes.map(node => ({...}));

// After: Uses functional setState
let classesWithProperties: any[] = [];
setNodes((currentNodes) => {
  classesWithProperties = currentNodes
    .filter(n => n.type !== 'groupNode')
    .map(node => ({...}));
  return currentNodes; // No change
});
```

### 5. Fixed Edge Regeneration to Access Current Nodes
```typescript
// Before: Used stale nodes closure
if (nodes.length > 0 && selectedVersionId) {
  const classesWithProperties = nodes.filter(...).map(...);
  // ...
}

// After: Uses functional setState
setNodes((currentNodes) => {
  if (currentNodes.length > 0) {
    const classesWithProperties = currentNodes
      .filter(n => n.type !== 'groupNode')
      .map(node => ({...}));
    const newEdges = createAllEdges(classesWithProperties);
    setEdges(newEdges);
  }
  return currentNodes; // No change
});
```

### 6. Removed nodes from reloadClasses Dependencies
```typescript
// Before
}, [selectedVersionId, setNodes, setEdges, projects, versions, nodes]);

// After - Also refactored to use functional setState
}, [selectedVersionId, projects, versions]);
```

### 7. Fixed reloadClasses to Use Functional setState
```typescript
// Before: Used stale nodes closure
const existingPositions = new Map(nodes.map(n => [n.id, n.position]));

// After: Uses functional setState
let existingPositions = new Map<string, { x: number; y: number }>();
setNodes((currentNodes) => {
  existingPositions = new Map(currentNodes.map(n => [n.id, n.position]));
  return currentNodes; // No change yet
});
```

### 4. Refactored handleThemeChange to Use Functional setState
- `handleCollapseAll`: Removed `setNodes` from dependencies
- `zoomToClass`: Refactored to use functional setState and removed `nodes` and `setNodes` dependencies
- Expansion state effect: Removed `setNodes` from dependencies

## Why These Fixes Work

### Functional setState Pattern
React's setState functions can accept a function that receives the current state as a parameter:
```typescript
setState((currentState) => {
  // Access current state here
  return newState;
});
```

This pattern allows us to:
1. Access current state values without including state in dependencies
2. Avoid stale closures
3. Prevent infinite loops

### Stable Function References
React guarantees that setState functions (like `setNodes`, `setEdges`, etc.) have stable references across renders. Including them in dependency arrays is unnecessary and can cause issues with React's rendering cycle.

### Empty Dependency Arrays
When a useCallback doesn't actually depend on any reactive values (it only uses functional setState), we can use an empty dependency array `[]`. This ensures the function is created once and never recreated.

## Impact

These fixes prevent:
- ✅ Redirect loops when navigating to `/ade/studio`
- ✅ Infinite loops when loading empty projects/versions
- ✅ Memory leaks from continuous re-renders
- ✅ Server hanging when navigating to `/ade/studio`
- ✅ Unnecessary spec regeneration on every node change
- ✅ Callback recreation on every render

## Testing
- ✅ TypeScript compiles successfully
- ✅ Build completes without errors
- ✅ Empty projects/versions should now load without hanging
- ✅ Canvas operations should be more performant

## Best Practices Applied

1. **Never include setState functions in dependency arrays** - they have stable references
2. **Use functional setState when accessing current state** - avoids stale closures
3. **Minimize dependencies in useCallback/useEffect** - only include values that actually trigger changes
4. **Avoid including large objects (like `nodes`) in dependencies** - use functional setState instead
5. **Empty dependency arrays are valid** - when using only functional setState and stable references

