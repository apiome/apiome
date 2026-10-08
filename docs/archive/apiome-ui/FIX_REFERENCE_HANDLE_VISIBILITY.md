# Fix: Only Show Handles for Reference Properties

## Problem

All properties in a class were showing connection handles (small circles on the right side), even though only properties with `$ref` (references) should be connectable to other classes.

**Issue**: 
- String properties had handles
- Number properties had handles  
- Boolean properties had handles
- Object properties (without $ref) had handles
- **Only** properties with `$ref` should have handles

## Root Cause

The `ClassNode` component was unconditionally rendering a Handle for every property:

```typescript
{/* Property reference handle: connectable to assign or reassign $ref */}
<Handle
  type="source"
  position={Position.Right}
  id={`prop-${p.id}`}
  style={{
    right: '-6px',
    background: hasRef(p) ? '#5b68ea' : '#9ca3af',  // Color changed based on $ref
    // ...
  }}
  isConnectable={!typedData.isReadOnly}
/>
```

While the handle color changed based on whether the property had a `$ref`, the handle itself was always rendered for all properties.

## Solution

Wrap the Handle component in a conditional that checks if the property has a `$ref`:

```typescript
{/* Property reference handle: only show for properties with $ref */}
{hasRef(p) && (
  <Handle
    type="source"
    position={Position.Right}
    id={`prop-${p.id}`}
    style={{
      right: '-6px',
      background: '#5b68ea',  // Always blue since we only render for refs
      width: '10px',
      height: '10px',
      border: '2px solid white',
      borderRadius: '50%',
      position: 'absolute',
      top: '50%',
      transform: 'translateY(-50%)',
      zIndex: 1000
    }}
    isConnectable={!typedData.isReadOnly}
  />
)}
```

## hasRef Function

The `hasRef` helper function already existed and correctly identifies reference properties:

```typescript
const hasRef = (prop: ClassProperty): boolean => {
  const d = parseData(prop);
  return !!(d?.$ref || (d?.type === 'array' && d?.items?.$ref));
};
```

This checks for:
1. **Direct references**: `{ "$ref": "#/components/schemas/ClassName" }`
2. **Array of references**: `{ "type": "array", "items": { "$ref": "..." } }`

## Behavior After Fix

### Properties WITH Handles (Connectable)
✅ Reference properties: `{ "$ref": "#/components/schemas/User" }`
✅ Array of references: `{ "type": "array", "items": { "$ref": "#/components/schemas/Group" } }`

### Properties WITHOUT Handles (Not Connectable)
❌ String properties: `{ "type": "string" }`
❌ Number properties: `{ "type": "number" }`
❌ Boolean properties: `{ "type": "boolean" }`
❌ Object properties (inline): `{ "type": "object", "properties": {...} }`
❌ Array of primitives: `{ "type": "array", "items": { "type": "string" } }`
❌ Array of inline objects: `{ "type": "array", "items": { "type": "object", "properties": {...} } }`

## Visual Impact

### Before Fix
```
┌─────────────────────────────┐
│ User                        │
├─────────────────────────────┤
│ • id (string)            ○ │ ← Handle on string (wrong!)
│ • name (string)          ○ │ ← Handle on string (wrong!)
│ • age (number)           ○ │ ← Handle on number (wrong!)
│ • groups (Group[])       ● │ ← Handle on ref (correct)
└─────────────────────────────┘
```

### After Fix
```
┌─────────────────────────────┐
│ User                        │
├─────────────────────────────┤
│ • id (string)               │ ← No handle (correct!)
│ • name (string)             │ ← No handle (correct!)
│ • age (number)              │ ← No handle (correct!)
│ • groups (Group[])       ● │ ← Handle on ref (correct!)
└─────────────────────────────┘
```

## Edge Creation

The edge creation logic in `page.tsx` was already correct - it only created edges for properties with `$ref`:

```typescript
const createPropertyRefEdges = (classes: any[]): Edge[] => {
  // ...
  cls.properties.forEach((prop: any) => {
    const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
    let refClassName: string | null = null;

    // Direct $ref
    if (propData.$ref) {
      refClassName = extractClassNameFromRef(propData.$ref);
    }
    // $ref in items (for array types)
    else if (propData.type === 'array' && propData.items?.$ref) {
      refClassName = extractClassNameFromRef(propData.items.$ref);
    }

    // Create edge if we found a reference to another class
    if (refClassName && classNameToId.has(refClassName)) {
      // ...create edge
    }
  });
};
```

The issue was purely in the UI rendering layer (ClassNode), not the edge logic.

## Connection Workflow

### Creating a New Reference
1. Drag "New Reference" from sidebar onto a class (or object property)
2. Dialog opens to configure the reference
3. Optionally select a target class
4. Reference created with handle visible

### Connecting an Existing Reference
1. Hover over a reference property with a handle
2. Drag from the handle to a target class
3. `$ref` is updated in the database
4. Edge appears on canvas connecting the two classes

### Non-Reference Properties
1. No handle visible
2. Cannot be dragged to create connections
3. Edit button allows changing type, constraints, etc.
4. Can be converted to a reference by manually editing (future enhancement)

## Files Changed

**File**: `/apiome-ui/src/app/components/ade/studio/ClassNode.tsx`

**Change**: Wrapped Handle component in conditional `{hasRef(p) && (...)}`

**Lines**: ~383-400

## Testing Checklist

- [x] String properties don't show handles
- [x] Number properties don't show handles
- [x] Boolean properties don't show handles
- [x] Object properties (inline) don't show handles
- [x] Array of primitives don't show handles
- [x] Direct `$ref` properties DO show handles
- [x] Array of `$ref` properties DO show handles
- [x] Handles are blue when connected
- [x] Can drag from ref handle to create connection
- [x] Edges only appear for properties with `$ref`

## Related Documentation

- `REFERENCE_DRAG_DROP_IMPLEMENTATION.md` - Reference creation via drag-and-drop
- `OPENAPI_IMPORT_REFERENCE_HANDLING.md` - How references are imported
- `CLASS_NODE_HANDLE_VISIBILITY.md` - This document

## Date
November 14, 2025

## Status
✅ **FIXED** - Only reference properties show connection handles

