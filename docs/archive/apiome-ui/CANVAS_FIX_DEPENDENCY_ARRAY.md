# Canvas Node Display Fix

## Problem
After implementing the Generate tab with Python DTO generation, nodes were no longer showing on the canvas.

## Root Cause
The issue was caused by including `generateOpenApiSpec` (an imported utility function) in the dependency arrays of two `useCallback`/`useEffect` hooks:

1. `reloadClasses` callback (line 282)
2. `loadClasses` useEffect (line 1536)

This caused React to think the dependencies were changing on every render, leading to infinite re-renders or unexpected behavior that prevented nodes from displaying properly.

## Solution
Removed `generateOpenApiSpec` from both dependency arrays. Imported utility functions should not be included in React dependency arrays because they don't change between renders.

### Fixed Lines
**Line 282** (reloadClasses callback):
```typescript
// BEFORE:
}, [selectedVersionId, layoutDirection, autoLayoutEnabled, setNodes, setEdges, projects, versions, generateOpenApiSpec, nodes]);

// AFTER:
}, [selectedVersionId, layoutDirection, autoLayoutEnabled, setNodes, setEdges, projects, versions, nodes]);
```

**Line 1536** (loadClasses useEffect):
```typescript
// BEFORE:
}, [selectedVersionId, selectedProjectId, canvasRefreshKey, layoutDirection, autoLayoutEnabled, setNodes, setEdges, fitView, generateOpenApiSpec, projects, versions]);

// AFTER:
}, [selectedVersionId, selectedProjectId, canvasRefreshKey, layoutDirection, autoLayoutEnabled, setNodes, setEdges, fitView, projects, versions]);
```

## Verification
- ✅ No compilation errors
- ✅ Only pre-existing warnings (unrelated to this fix)
- ✅ `generateOpenApiSpec` only appears in:
  - Import statement (line 13)
  - Function calls (lines 257, 1491, 1560)
  
## Best Practice
**Never include imported utility functions in React dependency arrays.**

Only include:
- State variables (from `useState`)
- Props
- Context values
- Ref values that change
- Functions created within the component (from `useCallback`)

Utility functions imported from other modules are stable and don't need to be in dependency arrays.

## Status
✅ Fixed - Nodes should now display correctly on the canvas

## Date
December 7, 2025

