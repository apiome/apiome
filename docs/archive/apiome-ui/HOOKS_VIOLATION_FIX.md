# Fix: "Rendered more hooks than during the previous render" Error

## Problem

**Error Message:**
```
Rendered more hooks than during the previous render.
src/app/ade/studio/paths/components/ResponseSection.tsx (249:45) @ renderPropertyNode

  247 |   // Render property tree node
  248 |   const renderPropertyNode = (node: PropertyTreeNode, depth = 0) => {
> 249 |     const [expanded, setExpanded] = useState(true);
```

**Root Cause:**
The `renderPropertyNode` function was a regular function that was being called during render, and it contained a `useState` hook. This violates the Rules of Hooks in React, which state that:
- Hooks can only be called at the top level of a React component
- Hooks cannot be called inside regular functions, loops, or conditionals

## Solution

Converted `renderPropertyNode` from a regular function into a proper React component called `PropertyTreeNodeComponent`.

### Before (Broken):
```typescript
// Inside ResponseSection component
const renderPropertyNode = (node: PropertyTreeNode, depth = 0) => {
  const [expanded, setExpanded] = useState(true); // ❌ Hook in regular function!
  
  return (
    <Box>
      {/* ... */}
      {expanded && node.children.map((child) => renderPropertyNode(child, depth + 1))}
    </Box>
  );
};

// Usage
{propertyTree.map((node) => renderPropertyNode(node))}
```

### After (Fixed):
```typescript
// Separate component outside ResponseSection
interface PropertyTreeNodeComponentProps {
  node: PropertyTreeNode;
  depth: number;
  isDark: boolean;
  onDeleteProperty: (id: string) => void;
}

function PropertyTreeNodeComponent({ 
  node, 
  depth, 
  isDark, 
  onDeleteProperty 
}: PropertyTreeNodeComponentProps) {
  const [expanded, setExpanded] = useState(true); // ✅ Hook in component!
  
  return (
    <Box>
      {/* ... */}
      {expanded && node.children.map((child) => (
        <PropertyTreeNodeComponent
          key={child.id}
          node={child}
          depth={depth + 1}
          isDark={isDark}
          onDeleteProperty={onDeleteProperty}
        />
      ))}
    </Box>
  );
}

// Usage in ResponseSection
{propertyTree.map((node) => (
  <PropertyTreeNodeComponent
    key={node.id}
    node={node}
    depth={0}
    isDark={isDark}
    onDeleteProperty={handleDeleteProperty}
  />
))}
```

## Changes Made

**File:** `/src/app/ade/studio/paths/components/ResponseSection.tsx`

1. **Extracted Component**: Created `PropertyTreeNodeComponent` as a separate function component
2. **Moved State**: The `useState` hook is now properly at the top level of a component
3. **Added Props Interface**: Defined `PropertyTreeNodeComponentProps` for type safety
4. **Updated Recursion**: Changed from function call to component rendering
5. **Updated Usage**: Replaced `renderPropertyNode(node)` with `<PropertyTreeNodeComponent ... />`

## Why This Matters

### Rules of Hooks Violations Can Cause:
- ❌ "Rendered more hooks than during the previous render" errors
- ❌ State not persisting correctly
- ❌ Hooks being called in wrong order
- ❌ React's internal state tracking to break

### Proper Component Pattern Ensures:
- ✅ Hooks are called consistently on every render
- ✅ State is properly managed per component instance
- ✅ React can track hook order reliably
- ✅ Component behavior is predictable

## Rules of Hooks Recap

**✅ DO:**
- Call hooks at the top level of function components
- Call hooks at the top level of custom hooks
- Always call hooks in the same order

**❌ DON'T:**
- Call hooks inside regular functions
- Call hooks inside loops
- Call hooks inside conditions
- Call hooks after early returns

## Testing

- ✅ Component compiles without errors
- ✅ No more hooks violation warnings
- ✅ Property tree rendering works correctly
- ✅ Expand/collapse state works per node
- ✅ Recursive rendering works properly

## Related Documentation

- [React Hooks Rules](https://react.dev/reference/rules/rules-of-hooks)
- [useState Hook](https://react.dev/reference/react/useState)
- [Component Composition](https://react.dev/learn/passing-props-to-a-component)

---

**Status:** ✅ Fixed
**Date:** January 17, 2026
**File:** ResponseSection.tsx
**Type:** React Hooks Violation
